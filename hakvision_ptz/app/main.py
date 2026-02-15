import os
import json
import time
import logging
import threading

from app.mqtt_client import MqttConfig, MqttSubscriber
from app.hikvision import HikvisionConfig, HikvisionISAPI

log = logging.getLogger("hakvision_ptz")


def clamp(v: int, mn: int, mx: int) -> int:
    return mn if v < mn else mx if v > mx else v


def axis_to_100(value) -> int:
    """
    Accepts:
      - int in [-100..100]
      - float in [-1.0..1.0] (auto scaled to -100..100)
    """
    try:
        x = float(value)
    except Exception:
        return 0

    # If normalized float
    if -1.0 <= x <= 1.0:
        x = x * 100.0

    return clamp(int(round(x)), -100, 100)


def load_options() -> dict:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    opt = load_options()

    logging.basicConfig(
        level=opt.get("log_level", "INFO"),
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log.info("Starting Hakvision PTZ Server...")

    mqtt_cfg = MqttConfig(
        host=opt.get("mqtt_host", "core-mosquitto"),
        port=int(opt.get("mqtt_port", 1883)),
        username=opt.get("mqtt_username", ""),
        password=opt.get("mqtt_password", ""),
        topic_prefix=opt.get("mqtt_topic_prefix", "ptz"),
        camera_id=opt.get("camera_id", "camera1"),
    )

    hik_cfg = HikvisionConfig(
        host=opt["hikvision_host"],
        port=int(opt.get("hikvision_port", 80)),
        username=opt["hikvision_username"],
        password=opt["hikvision_password"],
        channel=int(opt.get("channel", 1)),
    )

    deadzone = int(opt.get("deadzone", 5))          # now in percent (0-100)
    default_speed = int(opt.get("default_speed", 5))
    max_speed = int(opt.get("max_speed", 10))
    smooth_stop_ms = int(opt.get("smooth_stop_ms", 300))

    hik = HikvisionISAPI(hik_cfg)
    hik.test_connection()

    last_move_ts = 0.0

    def handle(topic: str, data: dict, ts: float):
        nonlocal last_move_ts

        action = topic.split("/")[-1]

        try:
            if action == "move":
                raw_pan = data.get("pan", 0)
                raw_tilt = data.get("tilt", 0)
                raw_zoom = data.get("zoom", 0)

                pan = axis_to_100(raw_pan)
                tilt = axis_to_100(raw_tilt)
                zoom = axis_to_100(raw_zoom)

                # deadzone (now percentage based)
                if abs(pan) < deadzone:
                    pan = 0
                if abs(tilt) < deadzone:
                    tilt = 0
                if abs(zoom) < deadzone:
                    zoom = 0

                # Optional speed multiplier for button-style commands
                speed = int(data.get("speed", default_speed))
                speed = clamp(speed, 1, max_speed)

                # If small direction values were sent (-1..1)
                if abs(float(raw_pan)) <= 1.0 and pan != 0:
                    pan = clamp(int(round((pan / 100.0) * speed * 10)), -100, 100)
                if abs(float(raw_tilt)) <= 1.0 and tilt != 0:
                    tilt = clamp(int(round((tilt / 100.0) * speed * 10)), -100, 100)
                if abs(float(raw_zoom)) <= 1.0 and zoom != 0:
                    zoom = clamp(int(round((zoom / 100.0) * speed * 10)), -100, 100)

                hik.continuous_move(pan, tilt, zoom)

                log.info("MOVE pan=%s tilt=%s zoom=%s", pan, tilt, zoom)

                duration_ms = int(data.get("duration_ms", 0))

                if duration_ms > 0:
                    def _stop_later():
                        time.sleep(duration_ms / 1000.0)
                        try:
                            hik.stop()
                            log.info("MOVE stop after %sms", duration_ms)
                        except Exception:
                            log.exception("MOVE stop failed")

                    threading.Thread(target=_stop_later, daemon=True).start()
                else:
                    last_move_ts = ts

            elif action == "stop":
                hik.stop()
                log.info("STOP")

            elif action == "preset":
                preset = int(data.get("preset"))
                hik.goto_preset(preset)
                log.info("PRESET goto %s", preset)

            else:
                log.warning("Unknown action: %s payload=%s", topic, data)

        except Exception:
            log.exception("Error handling topic=%s payload=%s", topic, data)

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
