import os, json, time, logging, threading
from app.mqtt_client import MqttConfig, MqttSubscriber
from app.hikvision import HikvisionConfig, HikvisionISAPI

log = logging.getLogger("hakvision_ptz")

def clamp(v: int, mn: int, mx: int) -> int:
    return mn if v < mn else mx if v > mx else v

def load_options() -> dict:
    with open("/data/options.json", "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    opt = load_options()
    logging.basicConfig(level=opt.get("log_level", "INFO"))
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

    deadzone = int(opt.get("deadzone", 1))
    max_speed = int(opt.get("max_speed", 7))
    default_speed = int(opt.get("default_speed", 4))
    smooth_stop_ms = int(opt.get("smooth_stop_ms", 250))

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
