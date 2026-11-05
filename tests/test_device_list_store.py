from pathlib import Path

from app.gui.device_list_store import DeviceListStore
from app.gui.widgets.multi_device_entry import MODEL_ISERIES, DeviceRowData


def test_save_and_load_list(tmp_path: Path) -> None:
    store = DeviceListStore(tmp_path)
    rows = [
        DeviceRowData(model=MODEL_ISERIES, label="a", tmos_host="10.0.0.1"),
        DeviceRowData(model=MODEL_ISERIES, label="b", tmos_host="10.0.0.2"),
    ]
    saved = store.save(label="Lab List", per_device_auth=True, devices=rows)
    assert saved.label == "Lab List"
    assert saved.per_device_auth is True
    assert len(saved.devices) == 2

    loaded = store.get(saved.list_id)
    assert loaded is not None
    assert loaded.devices[0].tmos_host == "10.0.0.1"
    assert loaded.devices[1].label == "b"

    store.delete(saved.list_id)
    assert store.get(saved.list_id) is None
