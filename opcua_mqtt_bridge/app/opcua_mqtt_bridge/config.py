import json
from typing import Any, Dict

OPTIONS_FILE = "/data/options.json"


def load_options() -> Dict[str, Any]:
    with open(OPTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
