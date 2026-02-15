import logging
from dataclasses import dataclass
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger("hakvision_ptz.isapi")

_HIK_NS = {"h": "http://www.hikvision.com/ver20/XMLSchema"}


@dataclass
class HikvisionConfig:
    host: str
    port: int
    username: str
    password: str
    channel: int


class HikvisionISAPI:
    def __init__(self, cfg: HikvisionConfig):
        self.cfg = cfg
        self.base = f"http://{cfg.host}:{cfg.port}"
        self.auth = httpx.DigestAuth(cfg.username, cfg.password)

    def test_connection(self):
        url = f"{self.base}/ISAPI/System/status"
        log.info("Testing Hikvision ISAPI connection to %s", url)
        try:
            with httpx.Client(auth=self.auth, timeout=5.0) as c:
                r = c.get(url)
                log.info("ISAPI status response: %s", r.status_code)
                if r.status_code == 200:
                    log.info("Hikvision connection OK")
                else:
                    log.error("Hikvision auth failed or unexpected response: %s", r.status_code)
        except Exception as e:
            log.exception("Failed to connect to Hikvision camera: %s", e)

    def get_ptz_status(self) -> dict:
        """
        Reads PTZ status/position from the camera.
        Returns dict with pan/tilt/zoom as floats (if available).
        """
        url = f"{self.base}/ISAPI/PTZCtrl/channels/{self.cfg.channel}/status"
        with httpx.Client(auth=self.auth, timeout=5.0) as c:
            r = c.get(url)
            r.raise_for_status()

        root = ET.fromstring(r.text)

        az = root.findtext(".//h:azimuth", default=None, namespaces=_HIK_NS)
        el = root.findtext(".//h:elevation", default=None, namespaces=_HIK_NS)
        zm = root.findtext(".//h:zoom", default=None, namespaces=_HIK_NS)

        def f(x):
            try:
                return float(x)
            except Exception:
                return None

        return {
            "pan": f(az),
            "tilt": f(el),
            "zoom": f(zm),
        }

    def _put(self, path: str, body: str):
        url = f"{self.base}{path}"
        try:
            with httpx.Client(auth=self.auth, timeout=5.0) as c:
                r = c.put(
                    url,
                    content=body.encode("utf-8"),
                    headers={"Content-Type": "application/xml"},
                )
                log.info("ISAPI PUT %s → %s", path, r.status_code)
                r.raise_for_status()
                return r.text
        except Exception as e:
            log.exception("ISAPI request failed: %s", e)
            raise

    def continuous_move(self, pan: int, tilt: int, zoom: int):
        path = f"/ISAPI/PTZCtrl/channels/{self.cfg.channel}/continuous"
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PTZData version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <pan>{pan}</pan>
  <tilt>{tilt}</tilt>
  <zoom>{zoom}</zoom>
</PTZData>"""
        return self._put(path, xml)

    def stop(self):
        return self.continuous_move(0, 0, 0)

    def goto_preset(self, preset_id: int):
        path = f"/ISAPI/PTZCtrl/channels/{self.cfg.channel}/presets/{preset_id}/goto"
        # Many Hikvision devices accept an empty XML body here.
        return self._put(path, "")
