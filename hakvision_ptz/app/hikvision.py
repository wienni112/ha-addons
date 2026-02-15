import logging
from dataclasses import dataclass
import httpx

log = logging.getLogger("hakvision_ptz.isapi")

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

    def _put(self, path: str, body: str):
        url = f"{self.base}{path}"
        try:
            with httpx.Client(auth=self.auth, timeout=5.0) as c:
                r = c.put(url, content=body.encode("utf-8"),
                          headers={"Content-Type": "application/xml"})
                log.info("ISAPI PUT %s → %s", path, r.status_code)
                r.raise_for_status()
                return r.text
        except Exception as e:
            log.exception("ISAPI request failed: %s", e)
            raise

    def continuous_move(self, pan: int, tilt: int, zoom: int):
        path = f"/ISAPI/PTZCtrl/channels/{self.cfg.channel}/continuous"
        xml = f"""<PTZData>
<pan>{pan}</pan>
<tilt>{tilt}</tilt>
<zoom>{zoom}</zoom>
</PTZData>"""
        return self._put(path, xml)

    def stop(self):
        return self.continuous_move(0, 0, 0)

    def goto_preset(self, preset_id: int):
        path = f"/ISAPI/PTZCtrl/channels/{self.cfg.channel}/presets/{preset_id}/goto"
        return self._put(path, "")
