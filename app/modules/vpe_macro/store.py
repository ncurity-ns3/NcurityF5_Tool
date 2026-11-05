from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.output_naming import sanitize_label
from app.core.redaction import redact_data
from app.modules.vpe_macro.apm_macro import MacroSnapshot


@dataclass(frozen=True)
class SavedMacroMeta:
    path: Path
    caption: str
    source_profile: str
    source_host: str
    saved_at: str


class MacroSnapshotStore:
    """Save/load APM macro snapshots under %LOCALAPPDATA%/f5tool/macros (no secrets)."""

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "macros"

    def list_saved(self) -> list[SavedMacroMeta]:
        if not self.root.is_dir():
            return []
        found: list[SavedMacroMeta] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            source = data.get("source") if isinstance(data.get("source"), dict) else {}
            found.append(
                SavedMacroMeta(
                    path=path,
                    caption=str(
                        data.get("macro_caption") or source.get("macro_caption") or path.stem
                    ),
                    source_profile=str(
                        data.get("access_profile") or source.get("access_profile") or ""
                    ),
                    source_host=str(source.get("host") or ""),
                    saved_at=str(data.get("saved_at") or ""),
                )
            )
        return found

    def save(self, snapshot: MacroSnapshot, filename_stem: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        stem = sanitize_label(filename_stem, max_len=80)
        path = self.root / f"{stem}.json"
        if path.exists():
            index = 2
            while True:
                candidate = self.root / f"{stem}_{index}.json"
                if not candidate.exists():
                    path = candidate
                    break
                index += 1
        payload = redact_data(snapshot.to_dict())
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_to_path(self, snapshot: MacroSnapshot, path: Path) -> Path:
        path = path.expanduser()
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = redact_data(snapshot.to_dict())
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, path: Path) -> MacroSnapshot:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Macro 파일이 올바르지 않습니다.")
        return MacroSnapshot.from_dict(redact_data(data))
