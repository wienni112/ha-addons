import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.mqtt_client import MqttConfig, MqttSubscriber
from app.hikvision import HikvisionConfig, HikvisionISAPI

log = logging.getLogger("hakvision_ptz")

TZ_LOCAL = ZoneInfo("Europe/Berlin")


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


def ts_now():
    dt_utc = datetime.now(timezone.utc)
    dt_loc = dt_utc.astimezone(TZ_LOCAL)
    return (
        dt_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        dt_loc.isoformat(timespec="milliseconds"),
    )


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

    deadzone = int(opt.get("deadzone", 5))  # now in percent (0-100)
    default_speed = int(opt.get("default_speed", 5))
    max_speed = int(opt.get("max_speed", 10))
    smooth_stop_ms = int(opt.get("smooth_stop_ms", 300))
    status_poll_ms = int(opt.get("status_poll_ms", 500))

    hik = HikvisionISAPI(hik_cfg)
    hik.test_connection()

    last_move_ts = 0.0

    # Subscriber must exist before we can publish status from handle()
    subscriber = None  # will be set below
    status_topic = f"{mqtt_cfg.topic_prefix}/{mqtt_cfg.camera_id}/status/position"

    def publish_position(source: str):
        nonlocal subscriber
        if subscriber is None:
            return
        st = hik.get_ptz_status()
        ts_utc, ts_local = ts_now()
        payload = {
            "ts_utc": ts_utc,
            "ts_local": ts_local,
            "source": source,
            "pan": st.get("pan"),
            "tilt": st.get("tilt"),
            "zoom": st.get("zoom"),
        }
        subscriber.publish(status_topic, json.dumps(payload), retain=True, qos=0)
        log.info("STATUS published to %s (source=%s)", status_topic, source)

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
                # Example: pan=1 speed=7 -> 70
                if abs(float(raw_pan)) <= 1.0 and pan != 0:
                    pan = clamp(int(round((pan / 100.0) * speed * 10)), -100, 100)
                if abs(float(raw_tilt)) <= 1.0 and tilt != 0:
                    tilt = clamp(int(round((tilt / 100.0) * speed * 10)), -100, 100)
                if abs(float(raw_zoom)) <= 1.0 and zoom != 0:
                    zoom = clamp(int(round((zoom / 100.0) * speed * 10)), -100, 100)

                hik.continuous_move(pan, tilt, zoom)
                log.info("MOVE pan=%s tilt=%s zoom=%s", pan, tilt, zoom)

                # Immediately publish position after command (best-effort)
                try:
                    publish_position("after_cmd")
                except Exception:
                    log.exception("Failed to publish status after move")

                duration_ms = int(data.get("duration_ms", 0))

                if duration_ms > 0:
                    def _stop_later():
                        time.sleep(duration_ms / 1000.0)
                        try:
                            hik.stop()
                            log.info("MOVE stop after %sms", duration_ms)
                            try:
                                publish_position("after_cmd")
                            except Exception:
                                log.exception("Failed to publish status after stop")
                        except Exception:
                            log.exception("MOVE stop failed")

                    threading.Thread(target=_stop_later, daemon=True).start()
                else:
                    last_move_ts = ts

            elif action == "stop":
                hik.stop()
                log.info("STOP")
                try:
                    publish_position("after_cmd")
                except Exception:
                    log.exception("Failed to publish status after stop")

            elif action == "preset":
                preset = int(data.get("preset"))
                hik.goto_preset(preset)
                log.info("PRESET goto %s", preset)
                try:
                    publish_position("after_cmd")
                except Exception:
                    log.exception("Failed to publish status after preset")

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
                    try:
                        publish_position("after_cmd")
                    except Exception:
                        log.exception("Failed to publish status after smooth-stop")
                except Exception:
                    log.exception("Smooth-stop failed")
                last_move_ts = 0.0

    def status_poller():
        # Wait until MQTT is connected, then publish regularly
        if subscriber and not subscriber.connected.wait(timeout=30):
            log.warning("MQTT not connected after 30s, status poller will still try.")
        while True:
            try:
                publish_position("poll")
            except Exception:
                log.exception("Status poll failed")
            time.sleep(max(50, status_poll_ms) / 1000.0)

    threading.Thread(target=watchdog, daemon=True).start()

    subscriber = MqttSubscriber(mqtt_cfg, handle)

    # Start status polling thread (after subscriber is created)
    threading.Thread(target=status_poller, daemon=True).start()

    # Enter MQTT loop
    subscriber.loop_forever()


if __name__ == "__main__":
    main()
