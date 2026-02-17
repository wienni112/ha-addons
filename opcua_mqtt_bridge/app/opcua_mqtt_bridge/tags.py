from typing import Any, Dict, List, Optional
from pathlib import Path
import os
import yaml


def load_tags(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("read", [])
    data.setdefault("rw", [])
    return data


def tags_is_empty(tags: Dict[str, Any]) -> bool:
    return (not tags.get("read")) and (not tags.get("rw"))


def write_yaml(path: str, data: Dict[str, Any]) -> None:
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def merge_tags(existing: Dict[str, Any], generated: Dict[str, Any]) -> Dict[str, Any]:
    existing_nodes = {
        t.get("node")
        for t in (existing.get("read", []) + existing.get("rw", []))
        if t.get("node")
    }
    out = {"read": list(existing.get("read", [])), "rw": list(existing.get("rw", []))}

    for e in generated.get("read", []):
        if e.get("node") and e["node"] not in existing_nodes:
            out["read"].append(e)

    for e in generated.get("rw", []):
        if e.get("node") and e["node"] not in existing_nodes:
            out["rw"].append(e)

    return out
