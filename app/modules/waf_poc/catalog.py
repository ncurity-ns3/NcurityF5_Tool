"""OWASP Top 10 PoC cases. 2025 is selectable, with no curl list yet."""

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


def _case(case_id: str, year: int, group: str, title: str, filename: str) -> PocCase:
    return PocCase(case_id, year, group, title, filename)


_A1 = "A1 Injection"
_A4 = "A4 XML External Entities"
_A5 = "A5 Broken Access Control"
_A6 = "A6 Security Misconfiguration"
_A7 = "A7 Cross-Site Scripting"
_A8 = "A8 Insecure Deserialization"

_CASES: tuple[PocCase, ...] = (
    _case("2017-01", 2017, _A1, "01 SQL Injection", "01-sql-injection.sh"),
    _case("2017-02", 2017, _A1, "02 Blind SQL Injection", "02-blind-sql.sh"),
    _case("2017-03", 2017, _A1, "03 Mass SQL Injection", "03-mass-sql.sh"),
    _case("2017-04a", 2017, _A1, "04 OS Command Injection 01", "04-os-command-01.sh"),
    _case("2017-04b", 2017, _A1, "04 OS Command Injection 02", "04-os-command-02.sh"),
    _case("2017-04c", 2017, _A1, "04 OS Command Injection 03", "04-os-command-03.sh"),
    _case("2017-04d", 2017, _A1, "04 OS Command Injection 04", "04-os-command-04.sh"),
    _case("2017-05", 2017, _A1, "05 RCE Injection", "05-rce.sh"),
    _case("2017-06", 2017, _A4, "06 XXE", "06-xxe.sh"),
    _case("2017-07", 2017, _A5, "07 Parameter Name", "07-parameter-name.sh"),
    _case("2017-08", 2017, _A5, "08 불필요한 파일 정보 노출 차단", "08-file-exposure.sh"),
    _case("2017-09", 2017, _A5, "09 불필요한 경로 접근 차단", "09-path-access.sh"),
    _case("2017-10", 2017, _A6, "10 취약한 HTTP 메소드 공격 차단", "10-http-method.sh"),
    _case("2017-11a", 2017, _A7, "11-1 Reflected XSS", "11-1-reflected-xss.sh"),
    _case("2017-11b", 2017, _A7, "11-2 Stored XSS", "11-2-stored-xss.sh"),
    _case("2017-11c", 2017, _A7, "11-3 html 속성 및 onevent handler", "11-3-xss-handlers.sh"),
    _case("2017-12", 2017, _A5, "12 파일 다운로드 공격 차단", "12-file-download.sh"),
    _case("2017-15", 2017, _A8, "15 역직렬화 취약점 공격 차단", "15-deserialization.sh"),
    _case(
        "a1-01",
        2021,
        "A1 Broken Access Control",
        "01 Parameter Name 공격 탐지",
        "a1-01-parameter-name.sh",
    ),
    _case(
        "a1-02",
        2021,
        "A1 Broken Access Control",
        "02 불필요한 파일 정보 노출 차단",
        "a1-02-file-exposure.sh",
    ),
    _case(
        "a1-03",
        2021,
        "A1 Broken Access Control",
        "03 불필요한 경로 접근 차단",
        "a1-03-path-access.sh",
    ),
    _case("a3-01", 2021, "A3 Injection", "01 SQL Injection", "a3-01-sql-injection.sh"),
    _case("a3-02", 2021, "A3 Injection", "02 Blind SQL Injection", "a3-02-blind-sql.sh"),
    _case("a3-03", 2021, "A3 Injection", "03 Mass SQL Injection", "a3-03-mass-sql.sh"),
    _case("a3-04", 2021, "A3 Injection", "04 OS Command Injection", "a3-04-os-command.sh"),
    _case("a3-05", 2021, "A3 Injection", "05 OS Command Injection", "a3-05-os-command.sh"),
    _case("a3-06", 2021, "A3 Injection", "06 OS Command Injection", "a3-06-os-command.sh"),
    _case("a3-07", 2021, "A3 Injection", "07 OS Command Injection", "a3-07-os-command.sh"),
    _case("a3-08", 2021, "A3 Injection", "08 RCE Injection", "a3-08-rce.sh"),
    _case("a3-09", 2021, "A3 Injection", "09 Reflected XSS", "a3-09-reflected-xss.sh"),
    _case("a3-10", 2021, "A3 Injection", "10 Stored XSS", "a3-10-stored-xss.sh"),
    _case(
        "a3-11",
        2021,
        "A3 Injection",
        "11 html 속성 및 onevent handler",
        "a3-11-xss-handlers.sh",
    ),
    _case(
        "a4-01",
        2021,
        "A4 Insecure Design",
        "01 예측 가능한 리소스 위치 차단",
        "a4-01-predictable-resource.sh",
    ),
    _case("a4-02", 2021, "A4 Insecure Design", "02 정보 유출 차단", "a4-02-info-leak.sh"),
    _case(
        "a4-03",
        2021,
        "A4 Insecure Design",
        "03 HTTP Compliance 위배 차단",
        "a4-03-http-compliance.sh",
    ),
    _case(
        "a5-02",
        2021,
        "A5 Security Misconfiguration",
        "02 취약한 HTTP Method 공격 차단",
        "a5-02-http-method.sh",
    ),
    _case(
        "a8-01",
        2021,
        "A8 Software and Data Integrity",
        "01 쿠키 무결성 검증",
        "a8-01-cookie.sh",
    ),
    _case(
        "a8-02",
        2021,
        "A8 Software and Data Integrity",
        "02 역직렬화 취약점 공격 차단",
        "a8-02-deserialization.sh",
    ),
    _case(
        "a10-01",
        2021,
        "A10 Server-Side Request Forgery",
        "01 SSRF Host 등록을 통한 차단",
        "a10-01-ssrf.sh",
    ),
)


def cases_for_year(year: int) -> tuple[PocCase, ...]:
    if year not in YEARS:
        raise ValueError(f"지원하지 않는 OWASP 연도입니다: {year}")
    return tuple(case for case in _CASES if case.year == year)
