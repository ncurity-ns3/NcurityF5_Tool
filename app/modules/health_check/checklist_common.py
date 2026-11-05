from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "health_check_common.yaml"


@dataclass(frozen=True)
class ChecklistItemDef:
    id: str
    name: str
    layer: str
    criteria: str


@dataclass
class CheckResult:
    item_id: str
    name: str
    layer: str
    status: str  # pass | fail | warn | skip | na
    value: str
    criteria: str
    detail: str = ""


def load_checklist_defs() -> list[ChecklistItemDef]:
    if not _CONFIG_PATH.is_file():
        return _builtin_defs()
    raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    items = raw.get("items", []) if isinstance(raw, dict) else []
    out: list[ChecklistItemDef] = []
    for row in items:
        if isinstance(row, dict) and row.get("id"):
            out.append(
                ChecklistItemDef(
                    id=str(row["id"]),
                    name=str(row.get("name", row["id"])),
                    layer=str(row.get("layer", "tmos")),
                    criteria=str(row.get("criteria", "")),
                )
            )
    return out or _builtin_defs()


def _builtin_defs() -> list[ChecklistItemDef]:
    return [
        ChecklistItemDef("uptime", "Uptime", "tmos", "365일 초과 warn"),
        ChecklistItemDef("power", "장비 전원 상태", "both", "PSU up"),
        ChecklistItemDef("temperature", "장비 온도", "both", "< 48°C"),
        ChecklistItemDef("interface", "인터페이스 상태", "both", "oper up"),
        ChecklistItemDef("ntp", "NTP 상태", "both", "연동"),
        ChecklistItemDef("clock", "System Time", "both", "date vs clock 시각 차이 없음"),
        ChecklistItemDef("disk", "Disk 사용량", "both", "< 80%"),
        ChecklistItemDef("daemons", "주요 서비스 데몬", "tmos", "tmm,bigd,mcpd"),
        ChecklistItemDef("cpu", "CPU Usage", "tmos", "max < 80%"),
        ChecklistItemDef("memory", "Memory Usage", "tmos", "max < 80%"),
        ChecklistItemDef("concurrent_connections", "Concurrent Connection", "tmos", "표시"),
        ChecklistItemDef("new_connections", "New Connection", "tmos", "표시"),
        ChecklistItemDef("throughput", "Throughput", "tmos", "표시"),
        ChecklistItemDef("ssl_cert", "SSL 인증서 만료", "tmos", "90일 warn"),
        ChecklistItemDef(
            "ha_status",
            "HA 상태",
            "tmos",
            "Standalone / Active / Standby / Force Offline",
        ),
        ChecklistItemDef("policy_backup", "정책 백업 (UCS)", "tmos", "UCS 존재"),
    ]
