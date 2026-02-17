import asyncio
import datetime
import json
import logging
import os
import socket
import sys
import signal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import paho.mqtt.client as mqtt
from asyncua import Client, ua

from .config import load_options
from .topics import normalize_topic, topic_value, topic_status, topic_error
from .payload import parse_payload
from .security import (
    map_security_policy,
    map_security_mode,
    cert_contains_uri,
    pki_paths,
)
from .tags import load_tags, tags_is_empty, write_yaml, merge_tags
from .discovery import browse_export, export_to_tags
from .mqtt_helpers import mqtt_connect_or_fail


def _variant_for_type(value, t: str) -> ua.Variant:
    tt = (t or "").lower().strip()

    if tt in ("float", "real"):
        return ua.Variant(float(value), ua.VariantType.Float)

    if tt in ("double", "lreal"):
        return ua.Variant(float(value), ua.VariantType.Double)

    if tt in ("int", "int16"):
        return ua.Variant(int(value), ua.VariantType.Int16)

    if tt in ("dint", "int32"):
        return ua.Variant(int(value), ua.VariantType.Int32)

    if tt in ("uint", "uint16", "word"):
        return ua.Variant(int(value), ua.VariantType.UInt16)

    if tt in ("udint", "uint32", "dword"):
        return ua.Variant(int(value), ua.VariantType.UInt32)

    if tt in ("byte", "uint8"):
        return ua.Variant(int(value), ua.VariantType.Byte)

    if tt in ("bool", "boolean"):
        # parse_payload liefert bei bool i.d.R. schon bool – wir bleiben defensiv
        if isinstance(value, str):
            v = value.strip().lower()
            value = v in ("1", "true", "on", "yes")
        return ua.Variant(bool(value), ua.VariantType.Boolean)

    # fallback: asyncua soll raten
    return ua.Variant(value)


class SubHandler:
    def __init__(
        self,
        mqtt_client: mqtt.Client,
        topic_prefix: str,
        qos_state: int,
        retain_states: bool,
        log: logging.Logger,
        on_status=None,
    ):
        self.mqtt = mqtt_client
        self.prefix = topic_prefix.rstrip("/")
        self.qos = int(qos_state)
        self.retain = bool(retain_states)
        self.log = log
        self.on_status = on_status  # <-- hinzufügen
        self.nodeid_to_path: Dict[str, str] = {}

    def datachange_notification(self, node, val, data):
        try:
            nodeid_str = node.nodeid.to_string()
            path = self.nodeid_to_path.get(nodeid_str)
            if not path:
                return

            topic = topic_value(self.prefix, path)
            payload = val

            if isinstance(val, bool):
                payload = "true" if val else "false"
            elif isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
                payload = val.isoformat()
            elif isinstance(val, (list, dict)):
                payload = json.dumps(val, ensure_ascii=False, default=str)
            elif val is None:
                payload = None
            elif not isinstance(val, (str, bytes, bytearray, int, float)):
                payload = str(val)

            self.mqtt.publish(topic, payload, qos=self.qos, retain=self.retain)

        except Exception as e:
            self.log.warning("DataChange publish failed: %s", e)

    # ✅ neu: asyncua ruft das bei Subscription/Session Problemen auf
    def status_change_notification(self, status):
        try:
            self.log.warning("OPC-UA subscription status change: %s", status)
            if self.on_status:
                self.on_status(status)
        except Exception as e:
            self.log.warning("status_change_notification failed: %s", e)


async def run_bridge_forever():
    opts = load_options()
    stop_event = asyncio.Event()
    opc_online = asyncio.Event()
    reconnect_event = asyncio.Event()
    pending_write_tasks: set[asyncio.Task] = set()
    write_lock = asyncio.Lock()  # optional, aber sehr hilfreich

    loop = asyncio.get_running_loop()
    for sig in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(getattr(signal, sig), stop_event.set)
        except Exception:
            pass

    # Logging
    log_cfg = opts.get("log", {}) or {}
    level_name = (log_cfg.get("level") or "INFO").upper()
    asyncua_level = (log_cfg.get("asyncua") or "WARNING").upper()
    paho_level = (log_cfg.get("paho") or "WARNING").upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger("opcua_mqtt_bridge")

    for n in ("asyncua", "asyncua.client", "asyncua.client.ua_client", "asyncua.crypto"):
        logging.getLogger(n).setLevel(getattr(logging, asyncua_level, logging.WARNING))
    for n in ("paho", "paho.mqtt"):
        logging.getLogger(n).setLevel(getattr(logging, paho_level, logging.WARNING))

    log.info("Log levels → main=%s asyncua=%s paho=%s", level_name, asyncua_level, paho_level)

    bridge_cfg = opts.get("bridge", {}) or {}
    tags_file = bridge_cfg.get("tags_file", "/config/opcua_mqtt_bridge/tags.yaml")

    # Discovery/Export options
    auto_export = bool(bridge_cfg.get("auto_export_on_first_run", False))
    export_file = bridge_cfg.get("export_file", "/config/opcua_mqtt_bridge/opcua-structure.json")
    generated_tags_file = bridge_cfg.get("generated_tags_file", "/config/opcua_mqtt_bridge/tags.generated.yaml")
    merge_into = bool(bridge_cfg.get("merge_into_tags_file", True))
    browse_cfg = bridge_cfg.get("browse", {}) or {}

    existing_tags = load_tags(tags_file) if os.path.exists(tags_file) else {"read": [], "rw": []}
    need_export = auto_export and (not os.path.exists(export_file) or tags_is_empty(existing_tags))

    # MQTT config
    mqtt_cfg = opts["mqtt"]
    prefix = mqtt_cfg["topic_prefix"].rstrip("/")
    qos_state = int(mqtt_cfg.get("qos_state", 0))
    qos_cmd = int(mqtt_cfg.get("qos_cmd", 1))
    retain_states = bool(mqtt_cfg.get("retain_states", True))
    availability_topic = normalize_topic(prefix, "meta/availability")

    mqtt_client = mqtt.Client(
        client_id=mqtt_cfg.get("client_id") or "",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    if mqtt_cfg.get("username"):
        mqtt_client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password") or "")

    def _rc_to_int(rc) -> int:
        return int(getattr(rc, "value", rc if rc is not None else -1))

    # Write map (wird bei OPCUA-Connect gefüllt; on_message greift darauf zu)
    write_nodes: Dict[str, Tuple[Any, str]] = {}

    # MQTT on_message: <prefix>/<path>/set
    def on_message(_client_m, _userdata, msg):
        try:
            base = prefix.rstrip("/") + "/"
            if not msg.topic.startswith(base):
                return

            rel = msg.topic[len(base):]
            if not rel.endswith("/set"):
                return

            path = rel[:-4]
            if path not in write_nodes:
                return

            # never accept retained writes
            if getattr(msg, "retain", False):
                log.info("Ignoring retained write on %s", msg.topic)
                return

            payload = msg.payload.decode("utf-8", errors="replace")
            node, t = write_nodes[path]
            # Wenn OPC offline ist, keine Writes anstoßen (verhindert "Future already done")
            if not opc_online.is_set():
                log.info("Ignoring write (OPC offline) on %s", msg.topic)
                mqtt_client.publish(topic_error(prefix, path), "opc_offline", qos=1, retain=False)
                return

            async def do_write():
                try:
                    async with write_lock:
                        value = parse_payload(payload, t)

                        # DateTime: support ISO with Z
                        if (t or "").strip().lower() in ("datetime", "date", "time"):
                            vv = str(value)
                            if vv.endswith("Z"):
                                vv = vv[:-1] + "+00:00"
                            try:
                                value = datetime.datetime.fromisoformat(vv)
                            except Exception:
                                pass

                        variant = _variant_for_type(value, t)
                        dv = ua.DataValue(variant)
                        await node.write_value(dv)

                    mqtt_client.publish(topic_status(prefix, path), "ok", qos=1, retain=False)
                except Exception as e:
                    log.error("Write error %s: %s", path, e)
                    mqtt_client.publish(topic_error(prefix, path), str(e), qos=1, retain=False)

            def _schedule_write():
                task = asyncio.create_task(do_write())
                pending_write_tasks.add(task)
                task.add_done_callback(lambda t: pending_write_tasks.discard(t))

            # paho callbacks laufen im paho-thread -> ins asyncio loop schieben
            loop.call_soon_threadsafe(_schedule_write)

        except Exception as e:
            log.error("MQTT on_message error: %s", e)

    # MQTT runtime connect/disconnect
    def on_connect_runtime(client, userdata, flags, reason_code, properties=None):
        log.info("MQTT (re)connected rc=%s", _rc_to_int(reason_code))

        # online nur wenn OPC online ist, sonst offline behalten
        client.publish(
            availability_topic,
            "online" if opc_online.is_set() else "offline",
            qos=1,
            retain=True,
        )

        client.subscribe(normalize_topic(prefix, "#"), qos=qos_cmd)

    def on_disconnect_runtime(client, userdata, disconnect_flags=None, reason_code=None, properties=None):
        log.warning("MQTT disconnected flags=%s rc=%s", disconnect_flags, _rc_to_int(reason_code))
        # Optional: availability auf offline setzen (aber Vorsicht: bei kurzen Glitches flackert HA)
        # client.publish(availability_topic, "offline", qos=1, retain=True)

    mqtt_client.on_connect = on_connect_runtime
    mqtt_client.on_disconnect = on_disconnect_runtime
    mqtt_client.on_message = on_message

    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=10)
    mqtt_client.enable_logger(logging.getLogger("paho.mqtt.client"))

    mqtt_client.will_set(availability_topic, "offline", qos=1, retain=True)

    # Connect + wait for first CONNACK
    await mqtt_connect_or_fail(mqtt_client, mqtt_cfg, log)
    
    # weil wir bereits verbunden sind (on_connect war schon), einmal sicherheitshalber:
    mqtt_client.subscribe(normalize_topic(prefix, "#"), qos=qos_cmd)

    backoff = 1
    backoff_max = 30

    while True:
        client: Optional[Client] = None
        subscription = None

        try:
            reconnect_event.clear()
            opc_cfg = opts["opcua"]
            url = opc_cfg["url"]

            security_policy = opc_cfg.get("security_policy", "None")
            security_mode = opc_cfg.get("security_mode", "None")
            username = opc_cfg.get("username") or ""
            password = opc_cfg.get("password") or ""
            publishing_interval_ms = int(opc_cfg.get("publishing_interval_ms", 200))
            auto_trust_server = bool(opc_cfg.get("auto_trust_server", True))

            pki = pki_paths("/data/pki")

            client = Client(url)

            host_actual = (socket.gethostname() or "ha-addon").strip()
            uri_suffix = (opc_cfg.get("application_uri_suffix") or "OPCUA2MQTT").strip()
            default_app_uri = f"urn:{host_actual}:HA:{uri_suffix}"

            raw_app_uri = (opc_cfg.get("application_uri") or "").strip()
            app_uri = raw_app_uri if raw_app_uri.lower().startswith("urn:") else default_app_uri

            pol = map_security_policy(security_policy)
            mode = map_security_mode(security_mode)

            security_enabled = (getattr(pol, "__name__", "") != "SecurityPolicyNone") and (mode != ua.MessageSecurityMode.None_)

            if security_enabled:
                log.info("OPC UA requested security: policy=%s mode=%s", security_policy, security_mode)
                log.info("OPC UA security_enabled=%s", security_enabled)
                if not os.path.exists(pki["client_cert"]):
                    raise FileNotFoundError(
                        f"Client certificate missing: {pki['client_cert']}. Delete /data/pki and restart to regenerate."
                    )
                if not os.path.exists(pki["client_key"]):
                    raise FileNotFoundError(
                        f"Client private key missing: {pki['client_key']}. Delete /data/pki and restart to regenerate."
                    )
                if not cert_contains_uri(pki["client_cert"], app_uri):
                    raise RuntimeError(
                        f"Client certificate does not contain ApplicationUri '{app_uri}'. Delete /data/pki and restart."
                    )
            else:
                log.warning("OPC UA security disabled (policy/mode None). Skipping cert checks.")

            if hasattr(client, "set_application_uri"):
                client.set_application_uri(app_uri)
            else:
                client.application_uri = app_uri

            if username:
                client.set_user(username)
                client.set_password(password)

            if not security_enabled:
                log.warning("OPC UA security disabled (policy/mode None).")
            else:
                if (not auto_trust_server) and (not os.path.exists(pki["server_cert_path"])):
                    raise FileNotFoundError(
                        f"Strict trust enabled but server cert missing: {pki['server_cert_path']}"
                    )

                if auto_trust_server:
                    log.warning("auto_trust_server=true: Server cert NOT pinned (TOFU-like).")
                    await client.set_security(pol, certificate=pki["client_cert"], private_key=pki["client_key"])
                else:
                    log.info("Strict server cert pinning enabled: %s", pki["server_cert_path"])
                    await client.set_security(
                        pol,
                        certificate=pki["client_cert"],
                        private_key=pki["client_key"],
                        server_certificate=pki["server_cert_path"],
                    )

            # Optional endpoint logging (independent of security)
            if bool(opc_cfg.get("log_endpoints", False)):
                tmp = Client(url)
                try:
                    eps = await tmp.connect_and_get_server_endpoints()
                    for e in eps:
                        log.info("Endpoint: mode=%s policy=%s", e.SecurityMode, e.SecurityPolicyUri)
                finally:
                    try:
                        await tmp.disconnect()
                    except Exception:
                        pass

            await client.connect()
            log.info("Connected to OPC UA: %s", url)
            write_nodes.clear()
            opc_online.set()
            reconnect_event.clear()
            mqtt_client.publish(availability_topic, "online", qos=1, retain=True)

            # Auto export / merge
            if need_export:
                max_depth = int(browse_cfg.get("max_depth", 12))
                namespace_filter = browse_cfg.get("namespace_filter", [3])
                exclude_prefixes = browse_cfg.get("exclude_path_prefixes", ["Server/", "ServerStatus/"])
                include_only_prefixes = browse_cfg.get("include_only_prefixes", ["DB", "DataBlocksGlobal"])

                export = await browse_export(
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

                generated = export_to_tags(export)
                write_yaml(generated_tags_file, generated)

                if merge_into:
                    merged = merge_tags(existing_tags, generated)
                    write_yaml(tags_file, merged)
                    existing_tags = merged

                log.info(
                    "Auto-export completed. export=%s generated=%s merge_into=%s",
                    export_file,
                    generated_tags_file,
                    tags_file if merge_into else "(disabled)",
                )
                need_export = False

            tags = load_tags(tags_file)

            def _on_sub_status(_status):
                opc_online.clear()
                write_nodes.clear()  # <- neu

                for t in list(pending_write_tasks):
                    t.cancel()
                pending_write_tasks.clear()

                mqtt_client.publish(availability_topic, "offline", qos=1, retain=True)
                reconnect_event.set()

            handler = SubHandler(mqtt_client, prefix, qos_state, retain_states, log, on_status=_on_sub_status)

            subscription = await client.create_subscription(publishing_interval_ms, handler)

            # Subscribe read
            for tag in tags.get("read", []):
                path = tag["path"]
                nodeid = tag["node"]
                node = client.get_node(ua.NodeId.from_string(nodeid))
                handler.nodeid_to_path[node.nodeid.to_string()] = path
                await subscription.subscribe_data_change(node)

            # Subscribe rw + prepare write map
            for tag in tags.get("rw", []):
                path = tag["path"]
                nodeid = tag["node"]
                t = tag.get("type", "float")
                node = client.get_node(ua.NodeId.from_string(nodeid))
                handler.nodeid_to_path[node.nodeid.to_string()] = path
                write_nodes[path] = (node, t)
                await subscription.subscribe_data_change(node)

            log.info("Subscribed read=%d, rw=%d", len(tags.get("read", [])), len(tags.get("rw", [])))

            backoff = 1
            while not stop_event.is_set() and not reconnect_event.is_set():
                await asyncio.sleep(1)

            if reconnect_event.is_set():
                log.warning("Reconnect requested (subscription status change).")
                raise RuntimeError("reconnect_requested")

            # ---> STOP: sauber runterfahren
            log.info("Stop signal received, shutting down...")
            opc_online.clear()
            write_nodes.clear()
            for t in list(pending_write_tasks):
                t.cancel()
            pending_write_tasks.clear()

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

            mqtt_client.publish(availability_topic, "offline", qos=1, retain=True)
            try:
                mqtt_client.disconnect()
            except Exception:
                pass
            mqtt_client.loop_stop()
            break

        except Exception as e:
            if str(e) == "reconnect_requested":
                log.warning("Reconnect loop triggered.")
            else:
                log.error("Bridge error: %s", e)
            opc_online.clear()
            write_nodes.clear()
            for t in list(pending_write_tasks):
                t.cancel()
            pending_write_tasks.clear()

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

            mqtt_client.publish(availability_topic, "offline", qos=1, retain=True)
            if stop_event.is_set():
                break

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)
