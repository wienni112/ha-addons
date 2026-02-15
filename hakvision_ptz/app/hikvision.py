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

    # ---------------------------------------------------------------------
    # Connection Test
    # ---------------------------------------------------------------------

    def test_connection(self):
        url = f"{self.base}/ISAPI/System/status"
        log.info("Testing Hikvision ISAPI connection to %s", url)
        try:
            with httpx.Client(auth=self.auth, timeout=5.0) as c:
                r = c.get(url)
                log.info("ISAPI status response: %s", r.status_code)

                if r.status_code == 200:
                    log.info("Hikvision connection OK")
                elif r.status_code in (401, 403):
                    log.error("Authentication failed (%s)", r.status_code)
                else:
                    log.error("Unexpected response from camera: %s", r.status_code)

        except Exception as e:
            log.exception("Failed to connect to Hikvision camera: %s", e)

    # ---------------------------------------------------------------------
    # PTZ Status (Pan / Tilt / Zoom)
    # ---------------------------------------------------------------------

    def get_ptz_status(self) -> dict:
        """
        Reads PTZ status/position from the camera.
        Returns dict with pan/tilt/zoom as floats (if available).
        Zoom field name differs between models → robust fallback detection.
        """

        url = f"{self.base}/ISAPI/PTZCtrl/channels/{self.cfg.channel}/status"

        with httpx.Client(auth=self.auth, timeout=5.0) as c:
            r = c.get(url)
            r.raise_for_status()

        root = ET.fromstring(r.text)

        def to_float(x):
            try:
                return float(x)
            except Exception:
                return None

        # Standard fields (most common Hikvision naming)
        az = root.findtext(".//h:azimuth", default=None, namespaces=_HIK_NS)
        el = root.findtext(".//h:elevation", default=None, namespaces=_HIK_NS)
        zm = root.findtext(".//h:zoom", default=None, namespaces=_HIK_NS)

        pan = to_float(az)
        tilt = to_float(el)
        zoom = to_float(zm)

        # -----------------------------------------------------------------
        # Zoom Fallback Detection (for models with different XML fields)
        # -----------------------------------------------------------------
        if zoom is None:
            candidates = []

            for elem in root.iter():
                tag = elem.tag

                # Remove namespace prefix {ns}
                if isinstance(tag, str) and tag.startswith("{"):
                    tag = tag.split("}", 1)[1]

                if isinstance(tag, str) and "zoom" in tag.lower():
                    val = (elem.text or "").strip()
                    z = to_float(val)
                    if z is not None:
                        candidates.append((tag, z))

            if candidates:
                log.debug("Zoom candidates detected: %s", candidates)

                preferred_names = [
                    "zoom",
                    "zoomLevel",
                    "absoluteZoom",
                    "zoomPos",
                    "zoomPosition",
                ]

                # Prefer well-known names
                for pref in preferred_names:
                    for tag, value in candidates:
                        if tag.lower() == pref.lower():
                            zoom = value
                            break
                    if zoom is not None:
                        break

                # Fallback: first numeric candidate
                if zoom is None:
                    zoom = candidates[0][1]

        return {
            "pan": pan,
            "tilt": tilt,
            "zoom": zoom,
        }

    # ---------------------------------------------------------------------
    # Internal PUT helper
    # ---------------------------------------------------------------------

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

    # ---------------------------------------------------------------------
    # PTZ Movement
    # ---------------------------------------------------------------------

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

    # ---------------------------------------------------------------------
    # Presets
    # ---------------------------------------------------------------------

    def goto_preset(self, preset_id: int):
        path = f"/ISAPI/PTZCtrl/channels/{self.cfg.channel}/presets/{preset_id}/goto"
        # Many Hikvision devices accept an empty body here.
        return self._put(path, "")
