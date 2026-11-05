from __future__ import annotations

from typing import Any


def is_rseries_device(data: dict[str, Any] | None) -> bool:
    """Prefer explicit platform tag from collector; fallback for older job JSON."""
    if not isinstance(data, dict):
        return False
    platform = data.get("_platform")
    if platform == "rseries":
        return True
    if platform == "iseries":
        return False
    return isinstance(data.get("f5os"), dict)


def f5os_collection_attempted(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    return isinstance(data.get("f5os"), dict)


def f5os_metrics_collected(f5os: dict[str, Any] | None) -> bool:
    if not isinstance(f5os, dict) or not f5os:
        return False
    return any(
        f5os.get(k)
        for k in (
            "uptime_seconds",
            "psu_units",
            "psu_health",
            "temperature_avg_c",
            "temperature_cam",
            "max_temperature_c",
            "interface_ports",
            "vlan_in_use_interfaces",
        )
    )


def has_f5os_platform_data(data: dict[str, Any] | None) -> bool:
    """rSeries with collected F5OS platform metrics (not raw REST blob only)."""
    if not is_rseries_device(data):
        return False
    common = data.get("common") if isinstance(data, dict) else None
    if isinstance(common, dict):
        return f5os_metrics_collected(common.get("f5os"))
    return False
