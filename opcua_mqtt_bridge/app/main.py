import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import yaml
import paho.mqtt.client as mqtt
from asyncua import Client, ua

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
    # Expect:
    # read: [{path,node,type?}, ...]
    # rw:   [{path,node,type?}, ...]
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
        return int(float(v))  # allow "1.0" as input

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
        # Most setups won't write datetime; keep as string.
        # If you need actual UA DateTime writing we can extend this.
        return v

    # Fallback: try bool -> float -> string
    if v.lower() in ("true", "false", "on", "off", "1", "0"):
        return v.lower() in ("true", "on", "1")
    try:
        return float(v)
    except Exception:
        return v


def normalize_topic(prefix: str, suffix: str) -> str:
    # Avoid accidental double slashes
    prefix = prefix.rstrip("/")
    suffix = suffix.lstrip("/")
    return f"{prefix}/{suffix}"


# -----------------------------
# OPC UA security mapping
# -----------------------------
def map_security_policy(policy: str):
    p = (policy or "None").strip()
    if p == "None":
        return None
    if p == "Basic256":
        return ua.SecurityPolicyBasic256
    if p == "Basic256Sha256":
        return ua.SecurityPolicyBasic256Sha256
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
# Subscription Handler
# -----------------------------
class SubHandler:
    def __init__(self, mqtt_client: mqtt.Client, topic_prefix: str, qos_state: int, retain_states: bool, log: logging.Logger):
        self.mqtt = mqtt_client
        self.prefix = topic_prefix.rstrip("/")
        self.qos = int(qos_state)
        self.retain = bool(retain_states)
        self.log = log
        # Map nodeid string -> path
        self.nodeid_to_path: Dict[str, str] = {}

    def datachange_notification(self, node, val, data):
        try:
            nodeid_str = node.nodeid.to_string()
            path = self.nodeid_to_path.get(nodeid_str)
            if not path:
                return
            topic = normalize_topic(self.prefix, f"state/{path}")
            # paho-mqtt can publish non-string; it will convert for us in most cases.
            self.mqtt.publish(topic, val, qos=self.qos, retain=self.retain)
        except Exception as e:
            self.log.warning("DataChange publish failed: %s", e)


# -----------------------------
# Main bridge
# -----------------------------
async def run_bridge_forever():
    opts = load_options()

    # Logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("opcua_mqtt_bridge")

    # Load tags
    tags_file = opts["bridge"]["tags_file"]
    tags = load_tags(tags_file)

    # MQTT
    mqtt_cfg = opts["mqtt"]
    prefix = mqtt_cfg["topic_prefix"].rstrip("/")
    qos_state = int(mqtt_cfg.get("qos_state", 0))
    qos_cmd = int(mqtt_cfg.get("qos_cmd", 1))
    retain_states = bool(mqtt_cfg.get("retain_states", True))

    mqtt_client = mqtt.Client(client_id=mqtt_cfg.get("client_id") or "")
    if mqtt_cfg.get("username"):
        mqtt_client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password") or "")
    mqtt_client.connect(mqtt_cfg["host"], int(mqtt_cfg["port"]), keepalive=60)
    mqtt_client.loop_start()

    availability_topic = normalize_topic(prefix, "meta/availability")
    mqtt_client.publish(availability_topic, "offline", retain=True)

    # Async loop ref (needed for thread-safe scheduling from paho callbacks)
    loop = asyncio.get_running_loop()

    # Write-map: path -> (node, type)
    write_nodes: Dict[str, Tuple[Any, str]] = {}

    # Reconnect loop parameters
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

            # Cert paths (client cert/key are created by run.sh under /data/pki)
            # You can change these later if you want
            pki_dir = "/data/pki"
            client_cert = os.path.join(pki_dir, "client_cert.der")
            client_key = os.path.join(pki_dir, "client_key.pem")
            trusted_server_dir = os.path.join(pki_dir, "trusted_server")
            os.makedirs(trusted_server_dir, exist_ok=True)
            server_cert_path = os.path.join(trusted_server_dir, "server_cert.der")

            client = Client(url)

            # Username/Password
            if username:
                client.set_user(username)
                client.set_password(password)

            # Security
            pol = map_security_policy(security_policy)
            mode = map_security_mode(security_mode)

            if pol is None or mode == ua.MessageSecurityMode.None_:
                log.warning("OPC UA security disabled (policy/mode None).")
            else:
                # Strict vs Auto trust:
                # - Strict: require server_cert_path to exist
                # - Auto trust: do NOT pin server cert (trust implicitly)
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
                        # server_certificate omitted intentionally
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
            mqtt_client.publish(availability_topic, "online", retain=True)

            # Build subscription
            handler = SubHandler(mqtt_client, prefix, qos_state, retain_states, log)
            subscription = await client.create_subscription(publishing_interval_ms, handler)

            # Subscribe nodes
            # Read nodes
            for tag in tags.get("read", []):
                path = tag["path"]
                nodeid = tag["node"]
                node = client.get_node(nodeid)
                handler.nodeid_to_path[node.nodeid.to_string()] = path
                await subscription.subscribe_data_change(node)

            # RW nodes (subscribe + allow write)
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

            # MQTT write handler (thread-safe)
            cmd_prefix = normalize_topic(prefix, "cmd/")

            def on_message(_client_m, _userdata, msg):
                try:
                    if not msg.topic.startswith(cmd_prefix):
                        return
                    path = msg.topic[len(cmd_prefix):]
                    if path not in write_nodes:
                        return

                    payload = msg.payload.decode("utf-8", errors="replace")
                    node, t = write_nodes[path]

                    async def do_write():
                        try:
                            value = parse_payload(payload, t)
                            await node.write_value(value)
                            # optional ack/meta
                            # mqtt_client.publish(normalize_topic(prefix, f"meta/last_write/{path}"), time.time(), retain=False)
                        except Exception as e:
                            log.error("Write error %s: %s", path, e)

                    loop.call_soon_threadsafe(lambda: asyncio.create_task(do_write()))
                except Exception as e:
                    log.error("MQTT on_message error: %s", e)

            mqtt_client.on_message = on_message
            mqtt_client.subscribe(normalize_topic(prefix, "cmd/#"), qos=qos_cmd)

            # Reset backoff on successful connect
            backoff = 1

            # Idle loop; subscription callbacks do the work
            while True:
                await asyncio.sleep(1)

        except Exception as e:
            log.error("Bridge error: %s", e)
            mqtt_client.publish(availability_topic, "offline", retain=True)

            # Clean up OPC UA client if partially connected
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

            # Backoff reconnect
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)


def main():
    asyncio.run(run_bridge_forever())


if __name__ == "__main__":
    main()
