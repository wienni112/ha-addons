import json
import time
from dataclasses import dataclass
import paho.mqtt.client as mqtt
import logging
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
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if cfg.username:
            self.client.username_pw_set(cfg.username, cfg.password)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

def _on_connect(self, client, userdata, flags, reason_code, properties=None):
    log.info("Connected to MQTT (%s:%s), subscribing...", self.cfg.host, self.cfg.port)
    base = f"{self.cfg.topic_prefix}/{self.cfg.camera_id}/cmd/#"
    client.subscribe(base, qos=0)
    log.info("Subscribed to %s", base)

def _on_message(self, client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace").strip()
    log.info("MQTT RX topic=%s payload=%s", msg.topic, payload)

    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        data = {"_raw": payload}

    self.on_message_cb(msg.topic, data, time.time())
    def loop_forever(self):
        self.client.connect(self.cfg.host, self.cfg.port, keepalive=30)
        self.client.loop_forever()
