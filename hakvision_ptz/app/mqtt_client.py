import json
import time
import logging
import threading
from dataclasses import dataclass

import paho.mqtt.client as mqtt

log = logging.getLogger("hakvision_ptz.mqtt")


@dataclass
class MqttConfig:
    host: str
    port: int
    username: str
    password: str
    topic_prefix: str
    camera_id: str


class MqttSubscriber:
    def __init__(self, cfg: MqttConfig, on_message):
        self.cfg = cfg
        self.on_message_cb = on_message
        self.connected = threading.Event()

        # Paho v2 callback API (passt zu deiner _on_connect Signatur mit reason_code)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if cfg.username:
            self.client.username_pw_set(cfg.username, cfg.password)

        # Optional: Connection status (Last Will)
        will_topic = f"{cfg.topic_prefix}/{cfg.camera_id}/status/connection"
        self.client.will_set(will_topic, payload="offline", qos=0, retain=True)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("Connected to MQTT (%s:%s), subscribing...", self.cfg.host, self.cfg.port)
        base = f"{self.cfg.topic_prefix}/{self.cfg.camera_id}/cmd/#"
        client.subscribe(base, qos=0)
        log.info("Subscribed to %s", base)

        # Mark online
        online_topic = f"{self.cfg.topic_prefix}/{self.cfg.camera_id}/status/connection"
        client.publish(online_topic, payload="online", qos=0, retain=True)

        self.connected.set()

    def _on_disconnect(self, client, userdata, reason_code, properties=None):
        log.warning("Disconnected from MQTT (reason_code=%s)", reason_code)
        self.connected.clear()

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        log.info("MQTT RX topic=%s payload=%s", msg.topic, payload)

        try:
            data = json.loads(payload) if payload else {}
        except Exception:
            data = {"_raw": payload}

        self.on_message_cb(msg.topic, data, time.time())

    def publish(self, topic: str, payload: str, retain: bool = False, qos: int = 0):
        """
        Publish helper for main.py (status, ack, etc.)
        """
        self.client.publish(topic, payload=payload, qos=qos, retain=retain)

    def loop_forever(self):
        log.info("Connecting to MQTT broker %s:%s ...", self.cfg.host, self.cfg.port)
        self.client.connect(self.cfg.host, self.cfg.port, keepalive=30)
        self.client.loop_forever()
