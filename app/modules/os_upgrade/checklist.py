from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from app.modules.health_check.checklist_common import ChecklistItemDef

Phase = Literal["pre", "post"]

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_PHASE_FILES: dict[Phase, str] = {
    "pre": "os_upgrade_pre.yaml",
    "post": "os_upgrade_post.yaml",
}


@dataclass(frozen=True)
class OsUpgradePhaseConfig:
    phase: Phase
    preset: str
    version: int
    categories: tuple[str, ...]
    perform_ucs_backup: bool
    items: tuple[ChecklistItemDef, ...]


def config_path_for_phase(phase: Phase) -> Path:
    return _CONFIG_DIR / _PHASE_FILES[phase]


def load_phase_config(phase: Phase, *, path: Path | None = None) -> OsUpgradePhaseConfig:
    yaml_path = path or config_path_for_phase(phase)
    if not yaml_path.is_file():
        return _builtin_phase_config(phase)

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return _builtin_phase_config(phase)

    collect = raw.get("collect") if isinstance(raw.get("collect"), dict) else {}
    categories = collect.get("categories", ["common", "ltm"])
    if not isinstance(categories, list):
        categories = ["common", "ltm"]

    items_raw = raw.get("items", [])
    items: list[ChecklistItemDef] = []
    if isinstance(items_raw, list):
        for row in items_raw:
            if isinstance(row, dict) and row.get("id"):
                items.append(
                    ChecklistItemDef(
                        id=str(row["id"]),
                        name=str(row.get("name", row["id"])),
                        layer=str(row.get("layer", "tmos")),
                        criteria=str(row.get("criteria", "")),
                    )
                )

    file_phase = str(raw.get("phase", phase))
    if file_phase not in ("pre", "post"):
        file_phase = phase

    return OsUpgradePhaseConfig(
        phase=file_phase,  # type: ignore[arg-type]
        preset=str(raw.get("preset", f"os_upgrade_{phase}")),
        version=int(raw.get("version", 1)),
        categories=tuple(str(c) for c in categories),
        perform_ucs_backup=bool(collect.get("perform_ucs_backup", phase == "pre")),
        items=tuple(items) if items else _builtin_phase_config(phase).items,
    )


def _builtin_phase_config(phase: Phase) -> OsUpgradePhaseConfig:
    ucs = phase == "pre"
    base_items = (
        ChecklistItemDef("sys_version", "현재 버전", "tmos", "version baseline"),
        ChecklistItemDef("ha_status", "HA 상태", "tmos", "no Force Offline"),
        ChecklistItemDef("disk", "디스크 여유", "both", "< 80%"),
        ChecklistItemDef("pool_availability", "Pool/VS 가용성", "tmos", "ltm summary"),
    )
    post_extra = (
        ChecklistItemDef(
            "target_version",
            "Target version 검증",
            "meta",
            "matches job target_version",
        ),
    )
    items = base_items + (post_extra if phase == "post" else ())
    return OsUpgradePhaseConfig(
        phase=phase,
        preset=f"os_upgrade_{phase}",
        version=1,
        categories=("common", "ltm"),
        perform_ucs_backup=ucs,
        items=items,
    )
