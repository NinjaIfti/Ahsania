from typing import Any


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """{"lesions": [{"lobe": "RUL"}]} -> {"lesions[0].lobe": "RUL"}"""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else key))
        return out
    if isinstance(value, list):
        out = {}
        for i, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{i}]"))
        return out
    return {prefix: value}


def diff_values(old: Any, new: Any) -> list[dict[str, Any]]:
    """Leaf-level changes between two value trees; removed leaves have new=None."""
    before, after = flatten(old or {}), flatten(new or {})
    return [
        {"path": path, "old": before.get(path), "new": after.get(path)}
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    ]
