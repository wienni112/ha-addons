import asyncio
import json
import logging
import os
import socket
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import yaml
import paho.mqtt.client as mqtt
from asyncua import Client, ua, Node
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
# Discovery / Export helpers
# -----------------------------
def _sanitize_path_part(s: str) -> str:
    s = (s or "").strip()
    repl = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
    for a, b in repl.items():
        s = s.replace(a, b)
    s = s.replace(" ", "_")

    out = []
    for ch in s:
        if ch.isalnum() or ch in ("_", "-", "."):
            out.append(ch.lower())
        else:
            out.append("_")

    p = "".join(out)
    while "__" in p:
        p = p.replace("__", "_")
    return p.strip("_")


def _join_path(parts: List[str]) -> str:
    return "/".join([_sanitize_path_part(p) for p in parts if p and str(p).strip()])


def _tags_is_empty(tags: Dict[str, Any]) -> bool:
    return (not tags.get("read")) and (not tags.get("rw"))


def _access_can_write(access_level: int) -> bool:
    # OPC UA AccessLevel bits: CurrentRead=0x01, CurrentWrite=0x02
    return bool(access_level & 0x02)


async def _browse_export(
    client: Client,
    max_depth: int,
    namespace_filter: Optional[List[int]],
    exclude_prefixes: List[str],
    include_only_prefixes: Optional[List[str]],
    log: logging.Logger,
) -> Dict[str, Any]:
    """
    Export model:
      nodes: [{ nodeId, browsePath, nodePath, displayName, dataType, accessLevel }]
    """
    root = client.nodes.objects
    results: List[Dict[str, Any]] = []

    async def walk(node: Node, path_parts: List[str], depth: int):
        if depth > max_depth:
            return
        try:
            children = await node.get_children()
        except Exception:
            return

        for ch in children:
            try:
                bn = await ch.read_browse_name()
                name = bn.Name or ""
                new_parts = path_parts + [name]
                node_path = "/".join(new_parts)

                # Exclude prefixes (logical path)
                if exclude_prefixes and any(node_path.startswith(p) for p in exclude_prefixes):
                    continue

                # Include-only: restrict by top-level segment
                if include_only_prefixes:
                    top = new_parts[0] if new_parts else ""
                    if not any(top.startswith(p) for p in include_only_prefixes):
                        continue

                nclass = await ch.read_node_class()

                if nclass == ua.NodeClass.Variable:
                    nid = ch.nodeid
                    if namespace_filter and (nid.NamespaceIndex not in namespace_filter):
                        continue

                    # DisplayName
                    try:
                        disp = await ch.read_display_name()
                        display_name = disp.Text or name
                    except Exception:
                        display_name = name

                    # DataType (best-effort)
                    try:
                        vtype = await ch.read_data_type_as_variant_type()
                        data_type = str(vtype)
                    except Exception:
                        data_type = "Unknown"

                    # AccessLevel
                    try:
                        al = await ch.read_attribute(ua.AttributeIds.AccessLevel)
                        access_level = int(al.Value.Value)
                    except Exception:
                        access_level = 0

                    results.append(
                        {
                            "nodeId": nid.to_string(),
                            "browsePath": new_parts,
                            "nodePath": node_path,
                            "displayName": display_name,
                            "dataType": data_type,
                            "accessLevel": access_level,
                        }
                    )

                # Walk deeper for Objects (and Variables to reach nested members)
                if nclass in (ua.NodeClass.Object, ua.NodeClass.Variable):
                    await walk(ch, new_parts, depth + 1)

            except Exception:
                continue

    await walk(root, [], 0)

    export = {
        "version": 1,
        "generatedAt": asyncio.get_running_loop().time(),
        "endpoint": str(getattr(client, "server_url", "")),
        "nodes": results,
    }
    log.info("Discovery export collected %d variables.", len(results))
    return export


def _export_to_tags(export: Dict[str, Any]) -> Dict[str, Any]:
    tags = {"read": [], "rw": []}
    for n in export.get("nodes", []):
        path = _join_path(n.get("browsePath") or [])
        entry = {
            "path": path,
            "node": n["nodeId"],
            # Keep as string; your parse_payload() already has fallbacks.
            "type": n.get("dataType", "float"),
        }
        if _access_can_write(int(n.get("accessLevel", 0))):
            tags["rw"].append(entry)
        else:
            tags["read"].append(entry)
    return tags


def _merge_tags(existing: Dict[str, Any], generated: Dict[str, Any]) -> Dict[str, Any]:
    # Keep existing entries by nodeId; add only missing nodes from generated.
    existing_nodes = {
        t.get("node")
        for t in (existing.get("read", []) + existing.get("rw", []))
        if t.get("node")
    }
    out = {"read": list(existing.get("read", [])), "rw": list(existing.get("rw", []))}

    for e in generated.get("read", []):
        if e.get("node") and e["node"] not in existing_nodes:
            out["read"].append(e)

    for e in generated.get("rw", []):
        if e.get("node") and e["node"] not in existing_nodes:
            out["rw"].append(e)

    return out


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

    # Fallback
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
# MQTT connect helper (handles wrong creds)
# -----------------------------
class MqttConnectError(RuntimeError):
    pass


async def mqtt_connect_or_fail(mqtt_client: mqtt.Client, cfg: Dict[str, Any], log: logging.Logger) -> None:
    """
    Connect to MQTT and wait for on_connect result.
    If credentials are wrong (rc=5), fail fast with clear error.
    """
    connected_evt = asyncio.Event()
    result: Dict[str, Any] = {"rc": None}

    def on_connect(_client, _userdata, _flags, rc, properties=None):  # properties for v2
        result["rc"] = rc
        connected_evt.set()

    def on_disconnect(_client, _userdata, rc, properties=None):
        log.warning("MQTT disconnected rc=%s", rc)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect

    host = cfg["host"]
    port = int(cfg["port"])
    keepalive = int(cfg.get("keepalive", 60))

    mqtt_client.connect_async(host, port, keepalive=keepalive)
    mqtt_client.loop_start()

    try:
        await asyncio.wait_for(connected_evt.wait(), timeout=10)
    except asyncio.TimeoutError as e:
        raise MqttConnectError("MQTT connect timeout (no CONNACK received).") from e

    rc = result["rc"]
    if rc == 0:
        log.info("MQTT connected to %s:%s", host, port)
        return

    if rc in (4, 5):
        raise MqttConnectError(
            f"MQTT authentication/authorization failed (rc={rc}). "
            "Check username/password + ACLs on the broker."
        )
    raise MqttConnectError(f"MQTT connect failed (rc={rc}).")


# -----------------------------
# Main bridge
# -----------------------------
async def run_bridge_forever():
    opts = load_options()

    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("opcua_mqtt_bridge")

    bridge_cfg = opts.get("bridge", {}) or {}
    tags_file = bridge_cfg.get("tags_file", "/config/opcua_mqtt_bridge/tags.yaml")

    # Discovery/Export options
    auto_export = bool(bridge_cfg.get("auto_export_on_first_run", False))
    export_file = bridge_cfg.get("export_file", "/config/opcua_mqtt_bridge/opcua-structure.json")
    generated_tags_file = bridge_cfg.get("generated_tags_file", "/config/opcua_mqtt_bridge/tags.generated.yaml")
    merge_into = bool(bridge_cfg.get("merge_into_tags_file", True))
    browse_cfg = bridge_cfg.get("browse", {}) or {}

    # Preload existing tags if any (for merge decision / first run detection)
    existing_tags = load_tags(tags_file) if os.path.exists(tags_file) else {"read": [], "rw": []}
    need_export = auto_export and (not os.path.exists(export_file) or _tags_is_empty(existing_tags))

    # MQTT config
    mqtt_cfg = opts["mqtt"]
    prefix = mqtt_cfg["topic_prefix"].rstrip("/")
    qos_state = int(mqtt_cfg.get("qos_state", 0))
    qos_cmd = int(mqtt_cfg.get("qos_cmd", 1))
    retain_states = bool(mqtt_cfg.get("retain_states", True))

    availability_topic = normalize_topic(prefix, "meta/availability")

    # Use Paho Callback API v2 to avoid deprecation warnings
    mqtt_client = mqtt.Client(
        client_id=mqtt_cfg.get("client_id") or "",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    if mqtt_cfg.get("username"):
        mqtt_client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password") or "")

    # LWT (Last Will) -> broker sets offline if we vanish
    mqtt_client.will_set(availability_topic, "offline", qos=1, retain=True)

    # Connect MQTT (fail fast on bad creds)
    try:
        await mqtt_connect_or_fail(mqtt_client, mqtt_cfg, log)
    except MqttConnectError as e:
        log.error("%s", e)
        raise

    # We are online on MQTT side now
    mqtt_client.publish(availability_topic, "online", qos=1, retain=True)

    loop = asyncio.get_running_loop()

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

            pki_dir = "/data/pki"
            client_cert = os.path.join(pki_dir, "client_cert.der")
            client_key = os.path.join(pki_dir, "client_key.pem")
            trusted_server_dir = os.path.join(pki_dir, "trusted_server")
            os.makedirs(trusted_server_dir, exist_ok=True)
            server_cert_path = os.path.join(trusted_server_dir, "server_cert.der")

            client = Client(url)

            # Application URI
            host_actual = (os.getenv("HOSTNAME") or socket.gethostname() or "ha-addon").strip()
            default_app_uri = f"urn:{host_actual}:ha:OPCUA2MQTT"
            app_uri = (opc_cfg.get("application_uri") or default_app_uri).strip()

            log.info("Using OPC UA ApplicationUri: %s", app_uri)

            if hasattr(client, "set_application_uri"):
                client.set_application_uri(app_uri)
            else:
                client.application_uri = app_uri

            if username:
                client.set_user(username)
                client.set_password(password)

            pol = map_security_policy(security_policy)
            mode = map_security_mode(security_mode)

            if pol is None or mode == ua.MessageSecurityMode.None_:
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
                    )
                else:
                    log.info("Strict server cert pinning enabled: %s", server_cert_path)
                    await client.set_security(
                        pol,
                        certificate=client_cert,
                        private_key=client_key,
                        server_certificate=server_cert_path,
                    )

            await client.connect()
            log.info("Connected to OPC UA: %s", url)

            # ---- NEW: Auto export/discovery on first run ----
            if need_export:
                max_depth = int(browse_cfg.get("max_depth", 12))
                namespace_filter = browse_cfg.get("namespace_filter", [3])
                exclude_prefixes = browse_cfg.get("exclude_path_prefixes", ["Server/", "ServerStatus/"])
                include_only_prefixes = browse_cfg.get("include_only_prefixes", ["DB", "DataBlocksGlobal"])

                export = await _browse_export(
                    client=client,
                    max_depth=max_depth,
                    namespace_filter=namespace_filter,
                    exclude_prefixes=exclude_prefixes,
                    include_only_prefixes=include_only_prefixes,
                    log=log,
                )

                Path(os.path.dirname(export_file)).mkdir(parents=True, exist_ok=True)
                with open(export_file, "w", encoding="utf-8") as f:
                    json.dump(export, f, ensure_ascii=False, indent=2)

                generated = _export_to_tags(export)

                Path(os.path.dirname(generated_tags_file)).mkdir(parents=True, exist_ok=True)
                with open(generated_tags_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(generated, f, sort_keys=False, allow_unicode=True)

                if merge_into:
                    merged = _merge_tags(existing_tags, generated)
                    Path(os.path.dirname(tags_file)).mkdir(parents=True, exist_ok=True)
                    with open(tags_file, "w", encoding="utf-8") as f:
                        yaml.safe_dump(merged, f, sort_keys=False, allow_unicode=True)
                    existing_tags = merged

                log.info(
                    "Auto-export completed. export=%s generated=%s merge_into=%s",
                    export_file,
                    generated_tags_file,
                    tags_file if merge_into else "(disabled)",
                )

                # After first successful export, do not re-run in this process
                need_export = False

            # Load tags for runtime (after possible merge/write)
            tags = load_tags(tags_file)

            handler = SubHandler(mqtt_client, prefix, qos_state, retain_states, log)
            subscription = await client.create_subscription(publishing_interval_ms, handler)

            # Read nodes
            for tag in tags.get("read", []):
                path = tag["path"]
                nodeid = tag["node"]
                node = client.get_node(nodeid)
                handler.nodeid_to_path[node.nodeid.to_string()] = path
                await subscription.subscribe_data_change(node)

            # RW nodes
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
                        except Exception as e:
                            log.error("Write error %s: %s", path, e)

                    loop.call_soon_threadsafe(lambda: asyncio.create_task(do_write()))
                except Exception as e:
                    log.error("MQTT on_message error: %s", e)

            mqtt_client.on_message = on_message
            mqtt_client.subscribe(normalize_topic(prefix, "cmd/#"), qos=qos_cmd)

            backoff = 1

            while True:
                await asyncio.sleep(1)

        except Exception as e:
            log.error("Bridge error: %s", e)

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

            # optional: publish offline if OPC UA down (MQTT still alive)
            mqtt_client.publish(availability_topic, "offline", qos=1, retain=True)

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)


def main():
    asyncio.run(run_bridge_forever())


if __name__ == "__main__":
    main()
