from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class BigIpTargetVersion:
    version: str
    license_check_date: date

    @property
    def label(self) -> str:
        return f"{self.version} (License Check: {self.license_check_date:%Y-%m-%d})"


def _project_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "k7727_bigip_versions.json"


def load_k7727_versions(config_path: Path | None = None) -> list[BigIpTargetVersion]:
    path = config_path or _project_config_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[BigIpTargetVersion] = []
    for item in raw.get("versions", []):
        ver = str(item.get("version", "")).strip()
        ds = str(item.get("license_check_date", "")).strip()
        if not ver or not ds:
            continue
        y, m, d = (int(x) for x in ds.split("-"))
        out.append(BigIpTargetVersion(version=ver, license_check_date=date(y, m, d)))
    return out


def find_version_entry(
    version_key: str,
    entries: list[BigIpTargetVersion] | None = None,
) -> BigIpTargetVersion | None:
    key = version_key.strip()
    pool = entries if entries is not None else load_k7727_versions()
    for ent in pool:
        if ent.version == key:
            return ent
    return None
