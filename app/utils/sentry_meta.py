"""Helpers for reading Sentry event `_meta` truncation annotations."""

from __future__ import annotations

from typing import Any


_TRUNCATE_REMS = frozenset({"!limit", "!config"})


def _meta_leaf(node: Any) -> dict | None:
    """Return the annotation dict for a meta node (often under key '')."""
    if not isinstance(node, dict):
        return None
    if "len" in node or "rem" in node:
        return node
    empty = node.get("")
    if isinstance(empty, dict) and ("len" in empty or "rem" in empty):
        return empty
    return None


def _is_truncated_leaf(leaf: dict) -> bool:
    if "len" in leaf:
        return True
    rem = leaf.get("rem")
    if not isinstance(rem, list):
        return False
    for entry in rem:
        if isinstance(entry, (list, tuple)) and entry and entry[0] in _TRUNCATE_REMS:
            return True
    return False


def _kind_for_value(value: Any) -> str:
    if isinstance(value, list):
        return "collection"
    if isinstance(value, dict):
        return "mapping"
    if isinstance(value, str):
        return "string"
    return "value"


def _label_for_kind(kind: str, original_len: int | None) -> str:
    if original_len is None:
        return "truncated"
    if kind == "collection":
        return f"truncated · originally {original_len} items"
    if kind == "mapping":
        return f"truncated · originally {original_len} keys"
    if kind == "string":
        return f"truncated · originally {original_len} characters"
    return f"truncated · originally {original_len}"


def lookup_frame_var_meta(
    event_meta: dict | None,
    *,
    exception_index: int = 0,
    frame_index: int,
    var_name: str,
) -> dict | None:
    """Look up `_meta` leaf for exception.values[i].stacktrace.frames[j].vars[name]."""
    if not event_meta or not isinstance(event_meta, dict):
        return None

    node: Any = event_meta
    for key in (
        "exception",
        "values",
        str(exception_index),
        "stacktrace",
        "frames",
        str(frame_index),
        "vars",
        var_name,
    ):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None

    return _meta_leaf(node)


def truncation_info_for_var(
    event_meta: dict | None,
    *,
    exception_index: int = 0,
    frame_index: int,
    var_name: str,
    value: Any = None,
) -> dict | None:
    """Return truncation display info for a frame local, or None if complete."""
    leaf = lookup_frame_var_meta(
        event_meta,
        exception_index=exception_index,
        frame_index=frame_index,
        var_name=var_name,
    )
    if not leaf or not _is_truncated_leaf(leaf):
        return None

    original_len = leaf.get("len")
    if original_len is not None and not isinstance(original_len, int):
        try:
            original_len = int(original_len)
        except (TypeError, ValueError):
            original_len = None

    kind = _kind_for_value(value)
    return {
        "original_len": original_len,
        "kind": kind,
        "label": _label_for_kind(kind, original_len),
    }


def annotate_frame_var_truncations(
    frames: list[dict],
    event_meta: dict | None,
    *,
    exception_index: int = 0,
    reversed_for_display: bool = True,
) -> list[dict]:
    """Attach `_var_truncations` maps onto frames (mutates and returns the list).

    When `reversed_for_display` is True, frames are newest-first (Broke UI order)
    while `_meta` frame indices refer to the original SDK order.
    """
    n = len(frames)
    for display_index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            continue
        orig_index = (n - 1 - display_index) if reversed_for_display else display_index
        vars_map = frame.get("vars") or {}
        if not isinstance(vars_map, dict):
            frame["_var_truncations"] = {}
            continue

        truncations: dict[str, dict] = {}
        for var_name, value in vars_map.items():
            info = truncation_info_for_var(
                event_meta,
                exception_index=exception_index,
                frame_index=orig_index,
                var_name=var_name,
                value=value,
            )
            if info:
                truncations[var_name] = info
        frame["_var_truncations"] = truncations

    return frames
