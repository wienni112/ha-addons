from dataclasses import dataclass
import httpx

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

    def _put(self, path: str, body: str):
        url = f"{self.base}{path}"
        with httpx.Client(auth=self.auth, timeout=5.0) as c:
            r = c.put(url, content=body.encode("utf-8"), headers={"Content-Type": "application/xml"})
            r.raise_for_status()
            return r.text

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
