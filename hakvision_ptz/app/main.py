import os
import time
import logging
import threading

import bashio  # HA Add-on helper

from app.mqtt_client import MqttConfig, MqttSubscriber
from app.hikvision import HikvisionConfig, HikvisionISAPI

log = logging.getLogger("hakvision_ptz")

def clamp(v: int, mn: int, mx: int) -> int:
    return mn if v < mn else mx if v > mx else v

def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    log.info("Starting Hakvision PTZ Server...")

    mqtt_cfg = MqttConfig(
        host=bashio.config("mqtt_host"),
        port=int(bashio.config("mqtt_port")),
        username=bashio.config("mqtt_username"),
        password=bashio.config("mqtt_password"),
        topic_prefix=bashio.config("mqtt_topic_prefix"),
        camera_id=bashio.config("camera_id"),
    )

    hik_cfg = HikvisionConfig(
        host=bashio.config("hikvision_host"),
        port=int(bashio.config("hikvision_port")),
        username=bashio.config("hikvision_username"),
        password=bashio.config("hikvision_password"),
        channel=int(bashio.config("channel")),
    )

    deadzone = int(bashio.config("deadzone"))
    max_speed = int(bashio.config("max_speed"))
    default_speed = int(bashio.config("default_speed"))
    smooth_stop_ms = int(bashio.config("smooth_stop_ms"))

    hik = HikvisionISAPI(hik_cfg)
    last_move_ts = 0.0

    def handle(topic: str, data: dict, ts: float):
        nonlocal last_move_ts
        action = topic.split("/")[-1]

        try:
            if action == "move":
                pan = int(data.get("pan", 0))
                tilt = int(data.get("tilt", 0))
                zoom = int(data.get("zoom", 0))
                speed = int(data.get("speed", default_speed))

                if abs(pan) < deadzone: pan = 0
                if abs(tilt) < deadzone: tilt = 0
                if abs(zoom) < deadzone: zoom = 0

                speed = clamp(speed, 1, max_speed)
                pan = clamp(pan, -speed, speed)
                tilt = clamp(tilt, -speed, speed)
                zoom = clamp(zoom, -speed, speed)

                hik.continuous_move(pan, tilt, zoom)
                last_move_ts = ts
                log.info("MOVE pan=%s tilt=%s zoom=%s speed=%s", pan, tilt, zoom, speed)

            elif action == "stop":
                hik.stop()
                log.info("STOP")

            elif action == "preset":
                preset = int(data.get("preset"))
                hik.goto_preset(preset)
                log.info("PRESET goto %s", preset)

            else:
                log.warning("Unknown action: %s payload=%s", topic, data)

        except Exception as e:
            log.exception("Error handling topic=%s payload=%s: %s", topic, data, e)

    def watchdog():
        nonlocal last_move_ts
        while True:
            time.sleep(0.05)
            if last_move_ts and (time.time() - last_move_ts) * 1000 > smooth_stop_ms:
                try:
                    hik.stop()
                    log.info("Smooth-stop after %sms", smooth_stop_ms)
                except Exception:
                    log.exception("Smooth-stop failed")
                last_move_ts = 0.0

    threading.Thread(target=watchdog, daemon=True).start()
    MqttSubscriber(mqtt_cfg, handle).loop_forever()

if __name__ == "__main__":
    main()
