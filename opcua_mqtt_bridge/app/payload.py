from typing import Any


def parse_payload(payload: str, tag_type: str) -> Any:
    v = (payload or "").strip()
    t = (tag_type or "").strip().lower()

    if t in ("bool", "boolean"):
        if v.lower() in ("true", "1", "on", "yes"):
            return True
        if v.lower() in ("false", "0", "off", "no"):
            return False
        raise ValueError(f"Invalid bool payload: {payload}")

    if t in ("int", "dint", "sint", "lint"):
        return int(float(v))  # allow "1.0"

    if t in ("uint", "udint", "usint", "ulint", "word", "dword"):
        n = int(float(v))
        if n < 0:
            raise ValueError(f"Negative not allowed for unsigned type {tag_type}: {payload}")
        return n

    if t in ("float", "real", "lreal", "double", "number"):
        return float(v)

    if t in ("string", "str"):
        return v

    if t in ("datetime", "date", "time"):
        # we parse datetime later (bridge.py) to support "Z"
        return v

    # Fallback
    if v.lower() in ("true", "false", "on", "off", "1", "0"):
        return v.lower() in ("true", "on", "1")
    try:
        return float(v)
    except Exception:
        return v
