import asyncio
from typing import Any, Dict, List, Optional
from asyncua import Client, ua, Node


def _sanitize_path_part(s: str) -> str:
    s = (s or "").strip()
    repl = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
    for a, b in repl.items():
        s = s.replace(a, b)
    s = s.replace(" ", "_")

    out = []
    for ch in s:
        if ch.isalnum() or ch in ("_", "-", "."):
            out.append(ch.lower())
        else:
            out.append("_")

    p = "".join(out)
    while "__" in p:
        p = p.replace("__", "_")
    return p.strip("_")


def _join_path(parts: List[str]) -> str:
    return "/".join([_sanitize_path_part(p) for p in parts if p and str(p).strip()])


def _access_can_write(access_level: int) -> bool:
    return bool(access_level & 0x02)


async def browse_export(
    client: Client,
    max_depth: int,
    namespace_filter: Optional[List[int]],
    exclude_prefixes: List[str],
    include_only_prefixes: Optional[List[str]],
    log,
) -> Dict[str, Any]:
    root = client.nodes.objects
    results: List[Dict[str, Any]] = []

    async def walk(node: Node, path_parts: List[str], depth: int):
        if depth > max_depth:
            return
        try:
            children = await node.get_children()
        except Exception:
            return

        for ch in children:
            try:
                bn = await ch.read_browse_name()
                name = bn.Name or ""
                new_parts = path_parts + [name]
                node_path = "/".join(new_parts)

                if exclude_prefixes and any(node_path.startswith(p) for p in exclude_prefixes):
                    continue

                if include_only_prefixes:
                    top = new_parts[0] if new_parts else ""
                    if not any(top.startswith(p) for p in include_only_prefixes):
                        continue

                nclass = await ch.read_node_class()

                if nclass == ua.NodeClass.Variable:
                    nid = ch.nodeid
                    if namespace_filter and (nid.NamespaceIndex not in namespace_filter):
                        continue

                    try:
                        disp = await ch.read_display_name()
                        display_name = disp.Text or name
                    except Exception:
                        display_name = name

                    try:
                        vtype = await ch.read_data_type_as_variant_type()
                        data_type = str(vtype)
                    except Exception:
                        data_type = "Unknown"

                    try:
                        al = await ch.read_attribute(ua.AttributeIds.AccessLevel)
                        access_level = int(al.Value.Value)
                    except Exception:
                        access_level = 0

                    results.append(
                        {
                            "nodeId": nid.to_string(),
                            "browsePath": new_parts,
                            "nodePath": node_path,
                            "displayName": display_name,
                            "dataType": data_type,
                            "accessLevel": access_level,
                        }
                    )

                if nclass in (ua.NodeClass.Object, ua.NodeClass.Variable):
                    await walk(ch, new_parts, depth + 1)

            except Exception:
                continue

    await walk(root, [], 0)

    export = {
        "version": 1,
        "generatedAt": asyncio.get_running_loop().time(),
        "endpoint": str(getattr(client, "server_url", "")),
        "nodes": results,
    }
    log.info("Discovery export collected %d variables.", len(results))
    return export


def export_to_tags(export: Dict[str, Any]) -> Dict[str, Any]:
    tags = {"read": [], "rw": []}
    for n in export.get("nodes", []):
        path = _join_path(n.get("browsePath") or [])
        entry = {"path": path, "node": n["nodeId"], "type": n.get("dataType", "float")}
        if _access_can_write(int(n.get("accessLevel", 0))):
            tags["rw"].append(entry)
        else:
            tags["read"].append(entry)
    return tags
