"""GUI device model labels (internal platform remains PlatformKind.iseries)."""

from __future__ import annotations

MODEL_ISERIES = "iSeries or VE"
MODEL_RSERIES = "rSeries"

# Saved sessions / older builds
_LEGACY_ISERIES_LABELS = frozenset(
    {
        "iSeries",
        "iSeries (TMOS)",
        "iSeries or VE",
        "VE",
    }
)


def normalize_device_model(model: str) -> str:
    m = (model or "").strip()
    if m == MODEL_RSERIES:
        return MODEL_RSERIES
    if m in _LEGACY_ISERIES_LABELS or m.startswith("iSeries"):
        return MODEL_ISERIES
    return MODEL_ISERIES


def is_rseries_model(model: str) -> bool:
    return normalize_device_model(model) == MODEL_RSERIES
