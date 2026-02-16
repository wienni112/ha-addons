import asyncio
import json
import logging
import os
import socket
import ssl
import time
from typing import Any, Dict, Optional, Tuple, List

import yaml
import paho.mqtt.client as mqtt
from asyncua import Client, ua
from asyncua.crypto.security_policies import (
    SecurityPolicyNone,
    SecurityPolicyBasic128Rsa15,
    SecurityPolicyBasic256,
    SecurityPolicyBasic256Sha256,
)

OPTIONS_FILE = "/data/options.json"


# -----------------------------
# Helpers: load config/tags
# -----------------------------
def load_options() -> Dict[str, Any]:
    with open(OPTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_tags(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("read", [])
    data.setdefault("rw", [])
    return data


# -----------------------------
# Type parsing for writes
# -----------------------------
def parse_payload(payload: str, tag_type: str) -> Any:
    v = payload.strip()
    t = (tag_type or "").strip().lower()

    if t in ("bool", "boolean"):
        if v.lower() in ("true", "1", "on", "yes"):
            return True
        if v.lower() in ("false", "0", "off", "no"):
            return False
        raise ValueError(f"Invalid bool payload: {payload}")

    if t in ("int", "dint", "sint", "lint"):
        return int(float(v))  # allow "1.0"

    if t in ("uint", "udint", "usint", "ulint", "word", "dword"):
        n = int(float(v))
        if n < 0:
            raise ValueError(f"Negative not allowed for unsigned type {tag_type}: {payload}")
        return n

    if t in ("float", "real", "lreal", "double", "number"):
        return float(v)

    if t in ("string", "str"):
        return v

    if t in ("datetime", "date", "time"):
        return v

    # Fallback: try bool -> float -> string
    if v.lower() in ("true", "false", "on", "off", "1", "0"):
        return v.lower() in ("true", "on", "1")
    try:
        return float(v)
    except Exception:
        return v


def normalize_topic(prefix: str, suffix: str) -> str:
    prefix = prefix.rstrip("/")
    suffix = suffix.lstrip("/")
    return f"{prefix}/{suffix}"


# -----------------------------
# OPC UA security mapping
# -----------------------------
def map_security_policy(policy: str):
    p = (policy or "None").strip()
    if p == "None":
        return SecurityPolicyNone
    if p == "Basic128Rsa15":
        return SecurityPolicyBasic128Rsa15
    if p == "Basic256":
        return SecurityPolicyBasic256
    if p == "Basic256Sha256":
        return SecurityPolicyBasic256Sha256
    raise ValueError(f"Unsupported security_policy: {policy}")


def map_security_mode(mode: str):
    m = (mode or "None").strip()
    if m == "None":
        return ua.MessageSecurityMode.None_
    if m == "Sign":
        return ua.MessageSecurityMode.Sign
    if m == "SignAndEncrypt":
        return ua.MessageSecurityMode.SignAndEncrypt
    raise ValueError(f"Unsupported security_mode: {mode}")


# -----------------------------
# Certificate helpers (ApplicationUri matching!)
# -----------------------------
def _cert_extract_uris_der(cert_der_path: str) -> List[str]:
    """
    Siemens/OPC UA Server can reject if ApplicationUri in cert doesn't match.
    We read URIs from SubjectAltName (URI) if present.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        from cryptography.x509.oid import ExtensionOID

        with open(cert_der_path, "rb") as f:
            der = f.read()
        cert = x509.load_der_x509_certificate(der, default_backend())

        uris: List[str] = []
        try:
            san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
            for u in san.get_values_for_type(x509.UniformResourceIdentifier):
                if isinstance(u, str) and u:
                    uris.append(u.strip())
        except Exception:
            pass

        return [u for u in uris if u]
    except Exception:
        return []


def choose_application_uri(opc_cfg: Dict[str, Any], client_cert_path: str, log: logging.Logger) -> str:
    """
    Priority:
      1) If cert contains URI -> use that (or force-match if config differs)
      2) Else opc_cfg.application_uri
      3) Else env APP_URI
      4) Else default urn:{hostname}:ha:OPCUA2MQTT
    """
    host = (os.getenv("HOSTNAME") or socket.gethostname() or "ha-addon").strip()
    default_uri = f"urn:{host}:ha:OPCUA2MQTT"

    cfg_uri = (opc_cfg.get("application_uri") or "").strip()
    env_uri = (os.getenv("APP_URI") or "").strip()

    cert_uris = _cert_extract_uris_der(client_cert_path) if os.path.exists(client_cert_path) else []
    cert_uri = cert_uris[0].strip() if cert_uris else ""

    # If we have a cert URI, ALWAYS use it to prevent BadCertificateUriInvalid
    if cert_uri:
        chosen = cfg_uri or env_uri or cert_uri or default_uri
        if chosen != cert_uri:
            log.warning(
                "ApplicationUri mismatch would be rejected by server. "
                "Config/Env wants '%s' but cert contains '%s'. Forcing cert URI.",
                chosen,
                cert_uri,
            )
        return cert_uri

    # No URI in cert -> use config/env/default
    return cfg_uri or env_uri or default_uri


# -----------------------------
# Subscription Handler
# -----------------------------
class SubHandler:
    def __init__(
        self,
        mqtt_client: mqtt.Client,
        topic_prefix: str,
        qos_state: int,
        retain_states: bool,
        log: logging.Logger,
    ):
        self.mqtt = mqtt_client
        self.prefix = topic_prefix.rstrip("/")
        self.qos = int(qos_state)
        self.retain = bool(retain_states)
        self.log = log
        self.nodeid_to_path: Dict[str, str] = {}

    def datachange_notification(self, node, val, data):
        try:
            nodeid_str = node.nodeid.to_string()
            path = self.nodeid_to_path.get(nodeid_str)
            if not path:
                return
            topic = normalize_topic(self.prefix, f"state/{path}")
            self.mqtt.publish(topic, val, qos=self.qos, retain=self.retain)
        except Exception as e:
            self.log.warning("DataChange publish failed: %s", e)


# -----------------------------
# MQTT setup helpers
# -----------------------------
def build_mqtt_client(mqtt_cfg: Dict[str, Any], log: logging.Logger) -> mqtt.Client:
    client_id = mqtt_cfg.get("client_id") or ""

    # Paho v2 deprecation: use Callback API v2 if available
    try:
        client = mqtt.Client(
            client_id=client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,  # type: ignore[attr-defined]
        )
    except Exception:
        client = mqtt.Client(client_id=client_id)

    if mqtt_cfg.get("username"):
        client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password") or "")

    # Optional TLS
    if mqtt_cfg.get("tls", False):
        ca = mqtt_cfg.get("tls_ca") or None
        cert = mqtt_cfg.get("tls_cert") or None
        key = mqtt_cfg.get("tls_key") or None
        insecure = bool(mqtt_cfg.get("tls_insecure", False))

        client.tls_set(
            ca_certs=ca,
            certfile=cert,
            keyfile=key,
            cert_reqs=ssl.CERT_REQUIRED if not insecure else ssl.CERT_NONE,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        client.tls_insecure_set(insecure)

    # Some brokers require this
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    return client


async def mqtt_connect_and_wait(
    mqtt_client: mqtt.Client,
    mqtt_cfg: Dict[str, Any],
    availability_topic: str,
    log: logging.Logger,
) -> bool:
    connected = asyncio.Event()

    def on_connect(_client, _userdata, _flags, rc, _props=None):
        if rc == 0:
            log.info("MQTT connected")
            connected.set()
        else:
            log.error("MQTT connect failed rc=%s", rc)

    def on_disconnect(_client, _userdata, rc, _props=None):
        log.warning("MQTT disconnected rc=%s", rc)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect

    # Last Will: if we die unexpectedly
    mqtt_client.will_set(availability_topic, "offline", qos=1, retain=True)

    host = mqtt_cfg["host"]
    port = int(mqtt_cfg["port"])
    keepalive = int(mqtt_cfg.get("keepalive", 60))

    try:
        mqtt_client.connect(host, port, keepalive=keepalive)
        mqtt_client.loop_start()
    except Exception as e:
        log.error("MQTT initial connect exception: %s", e)
        return False

    # Wait a bit for connection (non-blocking overall)
    try:
        await asyncio.wait_for(connected.wait(), timeout=8.0)
        return True
    except asyncio.TimeoutError:
        log.error("MQTT connect timeout (check host/port/credentials).")
        return False


# -----------------------------
# Main bridge
# -----------------------------
async def run_bridge_forever():
    # Logging early
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("opcua_mqtt_bridge")

    opts = load_options()

    # Load tags
    tags_file = opts["bridge"]["tags_file"]
    tags = load_tags(tags_file)

    # MQTT
    mqtt_cfg = opts["mqtt"]
    prefix = mqtt_cfg["topic_prefix"].rstrip("/")
    qos_state = int(mqtt_cfg.get("qos_state", 0))
    qos_cmd = int(mqtt_cfg.get("qos_cmd", 1))
    retain_states = bool(mqtt_cfg.get("retain_states", True))

    availability_topic = normalize_topic(prefix, "meta/availability")

    mqtt_client = build_mqtt_client(mqtt_cfg, log)

    mqtt_ok = await mqtt_connect_and_wait(mqtt_client, mqtt_cfg, availability_topic, log)
    if not mqtt_ok:
        # Still continue bridge loop; we will retry MQTT in reconnect cycles
        mqtt_client.publish(availability_topic, "offline", retain=True)
    else:
        mqtt_client.publish(availability_topic, "online", retain=True)

    # Async loop ref for thread-safe scheduling from paho callbacks
    loop = asyncio.get_running_loop()

    # Write-map: path -> (node, type)
    write_nodes: Dict[str, Tuple[Any, str]] = {}

    backoff = 1
    backoff_max = 30

    while True:
        client: Optional[Client] = None
        subscription = None

        try:
            opc_cfg = opts["opcua"]
            url = opc_cfg["url"]

            security_policy = opc_cfg.get("security_policy", "None")
            security_mode = opc_cfg.get("security_mode", "None")
            username = opc_cfg.get("username") or ""
            password = opc_cfg.get("password") or ""
            publishing_interval_ms = int(opc_cfg.get("publishing_interval_ms", 200))
            auto_trust_server = bool(opc_cfg.get("auto_trust_server", True))

            # PKI paths
            pki_dir = "/data/pki"
            client_cert = os.path.join(pki_dir, "client_cert.der")
            client_key = os.path.join(pki_dir, "client_key.pem")
            trusted_server_dir = os.path.join(pki_dir, "trusted_server")
            os.makedirs(trusted_server_dir, exist_ok=True)
            server_cert_path = os.path.join(trusted_server_dir, "server_cert.der")

            client = Client(url)

            # ApplicationUri MUST match cert (Siemens rejects otherwise)
            app_uri = choose_application_uri(opc_cfg, client_cert, log)
            log.info("Using OPC UA ApplicationUri: %s", app_uri)

            if hasattr(client, "set_application_uri"):
                client.set_application_uri(app_uri)
            else:
                client.application_uri = app_uri

            # Username/Password
            if username:
                client.set_user(username)
                client.set_password(password)

            # Security
            pol = map_security_policy(security_policy)
            mode = map_security_mode(security_mode)

            if pol is SecurityPolicyNone or mode == ua.MessageSecurityMode.None_:
                log.warning("OPC UA security disabled (policy/mode None).")
            else:
                if (not auto_trust_server) and (not os.path.exists(server_cert_path)):
                    raise FileNotFoundError(
                        f"Strict trust enabled but server cert missing: {server_cert_path}. "
                        f"Export server certificate (DER) and place it there."
                    )

                if auto_trust_server:
                    log.warning(
                        "auto_trust_server=true: Server certificate is NOT pinned (TOFU-like). "
                        "For strict pinning set auto_trust_server=false and provide server_cert.der."
                    )
                    await client.set_security(
                        pol,
                        certificate=client_cert,
                        private_key=client_key,
                        # server_certificate intentionally omitted
                    )
                else:
                    log.info("Strict server cert pinning enabled: %s", server_cert_path)
                    await client.set_security(
                        pol,
                        certificate=client_cert,
                        private_key=client_key,
                        server_certificate=server_cert_path,
                    )

            # Connect
            await client.connect()
            log.info("Connected to OPC UA: %s", url)

            # MQTT availability
            try:
                mqtt_client.publish(availability_topic, "online", retain=True)
            except Exception:
                pass

            # Subscription
            handler = SubHandler(mqtt_client, prefix, qos_state, retain_states, log)
            subscription = await client.create_subscription(publishing_interval_ms, handler)

            # Subscribe read nodes
            for tag in tags.get("read", []):
                path = tag["path"]
                nodeid = tag["node"]
                node = client.get_node(nodeid)
                handler.nodeid_to_path[node.nodeid.to_string()] = path
                await subscription.subscribe_data_change(node)

            # Subscribe rw nodes and build write map
            write_nodes.clear()
            for tag in tags.get("rw", []):
                path = tag["path"]
                nodeid = tag["node"]
                t = tag.get("type", "float")
                node = client.get_node(nodeid)
                handler.nodeid_to_path[node.nodeid.to_string()] = path
                write_nodes[path] = (node, t)
                await subscription.subscribe_data_change(node)

            log.info("Subscribed read=%d, rw=%d", len(tags.get("read", [])), len(tags.get("rw", [])))

            # MQTT write handler
            cmd_prefix = normalize_topic(prefix, "cmd/")

            def on_message(_client_m, _userdata, msg):
                try:
                    if not msg.topic.startswith(cmd_prefix):
                        return
                    path = msg.topic[len(cmd_prefix) :]
                    if path not in write_nodes:
                        return

                    payload = msg.payload.decode("utf-8", errors="replace")
                    node, t = write_nodes[path]

                    async def do_write():
                        try:
                            value = parse_payload(payload, t)
                            await node.write_value(value)
                        except Exception as e:
                            log.error("Write error %s: %s", path, e)

                    loop.call_soon_threadsafe(lambda: asyncio.create_task(do_write()))
                except Exception as e:
                    log.error("MQTT on_message error: %s", e)

            mqtt_client.on_message = on_message
            mqtt_client.subscribe(normalize_topic(prefix, "cmd/#"), qos=qos_cmd)

            # Reset backoff on success
            backoff = 1

            # Idle loop
            while True:
                await asyncio.sleep(1)

        except Exception as e:
            log.error("Bridge error: %s", e)

            try:
                mqtt_client.publish(availability_topic, "offline", retain=True)
            except Exception:
                pass

            # Cleanup
            try:
                if subscription is not None:
                    await subscription.delete()
            except Exception:
                pass

            try:
                if client is not None:
                    await client.disconnect()
            except Exception:
                pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)


def main():
    asyncio.run(run_bridge_forever())


if __name__ == "__main__":
    main()
