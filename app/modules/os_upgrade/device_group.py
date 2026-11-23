"""Device Group name for the OS upgrade check.

Live devices use GET /tm/cm/device-group. UCS archives keep the same object
in bigip.conf or bigip_base.conf. The trust group is on every box, so the
row shows the sync-failover name.
"""

from __future__ import annotations

import re
from typing import Any

_BUILTIN = {"device_trust_group", "datasync-global-dg", "gtm"}
_BLOCK_RE = re.compile(r"cm\s+device-group\s+(\S+)\s*\{", re.I)
_TYPE_RE = re.compile(r"\btype\s+(\S+)", re.I)


def _short_name(name: str) -> str:
    text = str(name or "").strip().strip('"').strip("{}")
    return text.rstrip("/").split("/")[-1]


def choose_device_group_names(entries: list[tuple[str, str]]) -> str:
    """Prefer sync-failover. Skip the built-in trust group when that is all there is."""
    failover: list[str] = []
    custom: list[str] = []
    seen: set[str] = set()
    for raw_name, kind in entries:
        name = _short_name(raw_name)
        if not name or name in seen or not re.fullmatch(r"[A-Za-z0-9_.:-]+", name):
            continue
        seen.add(name)
        if str(kind or "").strip() == "sync-failover":
            failover.append(name)
        elif name not in _BUILTIN:
            custom.append(name)
    chosen = failover or custom
    return ", ".join(chosen) if chosen else "없음"


def device_group_entries_from_config(text: str) -> list[tuple[str, str]]:
    parts = _BLOCK_RE.split(text or "")
    entries: list[tuple[str, str]] = []
    index = 1
    while index + 1 < len(parts):
        body = parts[index + 1]
        kind = ""
        match = _TYPE_RE.search(body)
        if match is not None:
            kind = match.group(1).strip().strip('"')
        entries.append((parts[index], kind))
        index += 2
    return entries


def device_group_names_from_config(text: str) -> str:
    return choose_device_group_names(device_group_entries_from_config(text))


def device_group_names_from_rest(body: dict[str, Any] | None) -> str:
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return "없음"
    entries: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entries.append((str(item.get("name") or ""), str(item.get("type") or "")))
    return choose_device_group_names(entries)


def read_device_group_name(client: Any) -> str:
    """REST first. tmsh list via the existing curl bash call if REST fails."""
    try:
        body = client.get("/tm/cm/device-group")
    except (OSError, RuntimeError, ValueError):
        body = None
    except Exception:  # noqa: BLE001 — httpx and device faults stay on this row
        body = None
    if isinstance(body, dict) and not body.get("_unavailable") and "items" in body:
        return device_group_names_from_rest(body)
    text = client.run_util_bash("tmsh -q list cm device-group")
    return device_group_names_from_config(text)
