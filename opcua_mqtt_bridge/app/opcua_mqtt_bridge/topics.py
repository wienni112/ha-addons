def normalize_topic(prefix: str, suffix: str) -> str:
    prefix = (prefix or "").rstrip("/")
    suffix = (suffix or "").lstrip("/")
    return f"{prefix}/{suffix}"


def topic_value(prefix: str, path: str) -> str:
    return normalize_topic(prefix, path)


def topic_set(prefix: str, path: str) -> str:
    return normalize_topic(prefix, f"{path}/set")


def topic_status(prefix: str, path: str) -> str:
    return normalize_topic(prefix, f"{path}/status")


def topic_error(prefix: str, path: str) -> str:
    return normalize_topic(prefix, f"{path}/error")
