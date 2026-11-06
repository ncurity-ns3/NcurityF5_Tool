"""OWASP Top 10 PoC cases. 2017 and 2025 are selectable, with no curl list yet."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

YEARS: tuple[int, ...] = (2017, 2021, 2025)
DEFAULT_YEAR = 2021

_SAMPLE_MARK = "curl "


def payload_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "waf_poc" / "payloads"
        if bundled.is_dir():
            return bundled
    return Path(__file__).resolve().parent / "payloads"


@dataclass(frozen=True)
class PocCase:
    case_id: str
    year: int
    group: str
    title: str
    filename: str

    @property
    def path(self) -> Path:
        return payload_root() / str(self.year) / self.filename

    def commands(self) -> tuple[str, ...]:
        text = self.path.read_text(encoding="utf-8")
        lines: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(_SAMPLE_MARK):
                raise ValueError(f"{self.filename}: curl 명령만 포함할 수 있습니다.")
            lines.append(line)
        if not lines:
            raise ValueError(f"{self.filename}: 보낼 curl이 없습니다.")
        return tuple(lines)


_CASES: tuple[PocCase, ...] = (
    PocCase(
        "a1-01",
        2021,
        "A1 Broken Access Control",
        "01 Parameter Name 공격 탐지",
        "a1-01-parameter-name.sh",
    ),
    PocCase(
        "a1-02",
        2021,
        "A1 Broken Access Control",
        "02 불필요한 파일 정보 노출 차단",
        "a1-02-file-exposure.sh",
    ),
    PocCase(
        "a1-03",
        2021,
        "A1 Broken Access Control",
        "03 불필요한 경로 접근 차단",
        "a1-03-path-access.sh",
    ),
    PocCase("a3-01", 2021, "A3 Injection", "01 SQL Injection", "a3-01-sql-injection.sh"),
    PocCase("a3-02", 2021, "A3 Injection", "02 Blind SQL Injection", "a3-02-blind-sql.sh"),
    PocCase("a3-03", 2021, "A3 Injection", "03 Mass SQL Injection", "a3-03-mass-sql.sh"),
    PocCase(
        "a3-04",
        2021,
        "A3 Injection",
        "04 OS Command Injection",
        "a3-04-os-command.sh",
    ),
    PocCase(
        "a3-05",
        2021,
        "A3 Injection",
        "05 OS Command Injection",
        "a3-05-os-command.sh",
    ),
    PocCase(
        "a3-06",
        2021,
        "A3 Injection",
        "06 OS Command Injection",
        "a3-06-os-command.sh",
    ),
    PocCase(
        "a3-07",
        2021,
        "A3 Injection",
        "07 OS Command Injection",
        "a3-07-os-command.sh",
    ),
)


def cases_for_year(year: int) -> tuple[PocCase, ...]:
    if year not in YEARS:
        raise ValueError(f"지원하지 않는 OWASP 연도입니다: {year}")
    return tuple(case for case in _CASES if case.year == year)
