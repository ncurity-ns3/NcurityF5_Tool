from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.gui.device_models import MODEL_ISERIES, MODEL_RSERIES, normalize_device_model
from app.gui.widgets.multi_device_entry import DeviceRowData


@dataclass(frozen=True)
class SavedDeviceList:
    list_id: str
    label: str
    per_device_auth: bool
    devices: tuple[DeviceRowData, ...]


_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _slug(label: str) -> str:
    """Filesystem-safe id; keeps Korean/unicode in the label for Windows paths."""
    base = _INVALID_NAME.sub("_", label.strip())
    return (base[:120] if base else "device_list")


def _row_from_raw(raw: dict) -> DeviceRowData:
    model = normalize_device_model(str(raw.get("model", MODEL_ISERIES)))
    return DeviceRowData(
        model=model,
        label=str(raw.get("label", "device")),
        f5os_host=str(raw.get("f5os_host", "")),
        f5os_port=int(raw.get("f5os_port", 443)),
        tmos_host=str(raw.get("tmos_host", "")),
        tmos_port=int(raw.get("tmos_port", 443)),
        tmos_user=str(raw.get("tmos_user", "admin")),
        f5os_user=str(raw.get("f5os_user", "admin")),
    )


def _row_to_raw(row: DeviceRowData) -> dict:
    return {
        "model": row.model,
        "label": row.label.strip(),
        "f5os_host": row.f5os_host.strip(),
        "f5os_port": row.f5os_port,
        "tmos_host": row.tmos_host.strip(),
        "tmos_port": row.tmos_port,
        "tmos_user": row.tmos_user.strip() or "admin",
        "f5os_user": row.f5os_user.strip() or "admin",
    }


class DeviceListStore:
    """Persist multiple-device table snapshots (no passwords) under lists/."""

    def __init__(self, base_dir: Path) -> None:
        self._dir = base_dir / "lists"
        self._dir.mkdir(parents=True, exist_ok=True)

    def list_lists(self) -> list[SavedDeviceList]:
        out: list[SavedDeviceList] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                out.append(self._from_raw(path.stem, raw))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(out, key=lambda item: item.label.lower())

    @staticmethod
    def _from_raw(list_id: str, raw: dict) -> SavedDeviceList:
        devices_raw = raw.get("devices", [])
        if not isinstance(devices_raw, list):
            devices_raw = []
        devices = tuple(_row_from_raw(d) for d in devices_raw if isinstance(d, dict))
        return SavedDeviceList(
            list_id=list_id,
            label=str(raw.get("label", list_id)),
            per_device_auth=bool(raw.get("per_device_auth", False)),
            devices=devices,
        )

    def save(
        self,
        *,
        label: str,
        per_device_auth: bool,
        devices: list[DeviceRowData],
    ) -> SavedDeviceList:
        list_id = _slug(label)
        payload = {
            "label": label.strip(),
            "per_device_auth": per_device_auth,
            "devices": [_row_to_raw(d) for d in devices],
        }
        path = self._dir / f"{list_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self._from_raw(list_id, payload)

    def get(self, list_id: str) -> SavedDeviceList | None:
        path = self._dir / f"{list_id}.json"
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return self._from_raw(list_id, raw)

    def delete(self, list_id: str) -> None:
        path = self._dir / f"{list_id}.json"
        if path.is_file():
            path.unlink()
