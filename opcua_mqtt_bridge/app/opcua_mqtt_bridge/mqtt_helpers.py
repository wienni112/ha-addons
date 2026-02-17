import asyncio
from typing import Any, Dict
import paho.mqtt.client as mqtt


class MqttConnectError(RuntimeError):
    pass


async def mqtt_connect_or_fail(mqtt_client: mqtt.Client, cfg: Dict[str, Any], log) -> None:
    connected_evt = asyncio.Event()
    result: Dict[str, Any] = {"rc": None}

    def on_connect(_client, _userdata, _flags, reason_code, properties=None):
        # reason_code ist ein ReasonCode-Objekt oder int-ähnlich
        rc = int(reason_code)
        result["rc"] = rc
        connected_evt.set()

    def on_disconnect(_client, _userdata, reason_code, properties=None):
        log.warning("MQTT disconnected rc=%s", int(reason_code))

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

