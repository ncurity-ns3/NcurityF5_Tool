"""Regression: Multiple Load must use list_store, not profile_store."""

from __future__ import annotations

from pathlib import Path

from app.gui.device_list_store import DeviceListStore
from app.gui.device_profile_store import DeviceProfileStore
from app.gui.widgets.multi_device_entry import MODEL_ISERIES, DeviceRowData


def test_multiple_load_uses_list_store_not_profile(tmp_path: Path) -> None:
    lists = DeviceListStore(tmp_path)
    profiles = DeviceProfileStore(tmp_path)

    saved = lists.save(
        label="3TeamVE+NSA테스트",
        per_device_auth=True,
        devices=[DeviceRowData(model=MODEL_ISERIES, label="a", tmos_host="10.0.0.1")],
    )
    # Same slug id must not exist as a single-device profile
    assert profiles.get(saved.list_id) is None
    assert lists.get(saved.list_id) is not None
    assert lists.get(saved.list_id).label == "3TeamVE+NSA테스트"
