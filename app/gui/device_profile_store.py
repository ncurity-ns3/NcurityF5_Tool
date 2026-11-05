from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.models import PlatformKind


@dataclass(frozen=True)
class SavedDeviceProfile:
    profile_id: str
    label: str
    platform: PlatformKind
    host: str
    port: int
    username: str
    f5os_host: str = ""
    f5os_port: int = 443
    f5os_username: str = ""


def _slug(label: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.strip().lower())
    return base.strip("_") or "device"


def _parse_platform(raw: str | None) -> PlatformKind:
    if raw in (PlatformKind.rseries.value, "rseries", "rSeries"):
        return PlatformKind.rseries
    return PlatformKind.iseries


class DeviceProfileStore:
    """persist mgmt connection profiles (no password) under %LOCALAPPDATA%\\f5tool\\devices."""

    def __init__(self, base_dir: Path) -> None:
        self._dir = base_dir / "devices"
        self._dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[SavedDeviceProfile]:
        profiles: list[SavedDeviceProfile] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                profiles.append(self._from_raw(path.stem, raw))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(profiles, key=lambda p: p.label.lower())

    @staticmethod
    def _from_raw(profile_id: str, raw: dict) -> SavedDeviceProfile:
        # host = TMOS MGMT; f5os_host = platform MGMT (rSeries)
        tmos_host = str(raw.get("host", raw.get("tmos_host", "")))
        return SavedDeviceProfile(
            profile_id=profile_id,
            label=str(raw.get("label", profile_id)),
            platform=_parse_platform(raw.get("platform")),
            host=tmos_host,
            port=int(raw.get("port", raw.get("tmos_port", 443))),
            username=str(raw.get("username", "admin")),
            f5os_host=str(raw.get("f5os_host", "")),
            f5os_port=int(raw.get("f5os_port", 443)),
            f5os_username=str(raw.get("f5os_username", raw.get("username", "admin"))),
        )

    def save(
        self,
        *,
        label: str,
        platform: PlatformKind,
        host: str,
        port: int,
        username: str,
        f5os_host: str = "",
        f5os_port: int = 443,
        f5os_username: str = "",
    ) -> SavedDeviceProfile:
        profile_id = _slug(label)
        payload = {
            "label": label.strip(),
            "platform": platform.value,
            "host": host.strip(),
            "port": port,
            "username": username.strip() or "admin",
            "f5os_host": f5os_host.strip(),
            "f5os_port": f5os_port,
            "f5os_username": (f5os_username.strip() or username.strip() or "admin"),
        }
        path = self._dir / f"{profile_id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self._from_raw(profile_id, payload)

    def delete(self, profile_id: str) -> None:
        path = self._dir / f"{profile_id}.json"
        if path.is_file():
            path.unlink()

    def get(self, profile_id: str) -> SavedDeviceProfile | None:
        path = self._dir / f"{profile_id}.json"
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return self._from_raw(profile_id, raw)
