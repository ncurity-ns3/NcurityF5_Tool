from __future__ import annotations

import re


def parse_apm_access_info_total(text: str) -> int | None:
    """tmsh show apm access-info | grep -i Total — session total."""
    if not text:
        return None
    for line in text.splitlines():
        if "total" not in line.lower():
            continue
        m = re.search(r"(\d+)", line)
        if m:
            return int(m.group(1))
    return None


_RE_CONN_TOTAL = re.compile(
    r"total\s+connectivity\s+sessions:\s*([\d.]+)\s*([KMG])?",
    re.IGNORECASE,
)
_RE_CONN_CURRENT = re.compile(
    r"current\s+connectivity\s+sessions:\s*([\d.]+)\s*([KMG])?",
    re.IGNORECASE,
)


def _scale_license_number(num: str, suffix: str) -> int:
    value = float(num)
    mult = {"K": 1000, "M": 1_000_000, "G": 1_000_000_000}.get(suffix.upper(), 1)
    return int(value * mult)


def _format_license_quantity(num: str, suffix: str) -> str:
    s = suffix.upper() if suffix else ""
    return f"{num}{s}" if s else num


def parse_apm_license_connectivity(text: str) -> tuple[str | None, int | None, int | None]:
    """
    tmsh show apm license (Global Access) — total connectivity sessions = CCU 용량.
    Returns (display e.g. 3.0K, total_int, current_int).
    """
    if not text:
        return None, None, None
    total_display: str | None = None
    total_int: int | None = None
    current_int: int | None = None
    for line in text.splitlines():
        m = _RE_CONN_TOTAL.search(line)
        if m:
            num, suf = m.group(1), m.group(2) or ""
            total_display = _format_license_quantity(num, suf)
            total_int = _scale_license_number(num, suf)
            continue
        m = _RE_CONN_CURRENT.search(line)
        if m:
            num, suf = m.group(1), m.group(2) or ""
            current_int = _scale_license_number(num, suf)
    return total_display, total_int, current_int


def apm_license_not_available(text: str) -> bool:
    low = (text or "").lower()
    return "syntax error" in low or "unexpected argument" in low


def parse_apm_license_available_ccu(text: str) -> tuple[int | None, int | None, int | None]:
    """
    tmsh show apm license — CCU counts.
    Prefer total connectivity sessions; fall back to legacy Available/Licensed CCU lines.
    """
    _display, total_conn, current_conn = parse_apm_license_connectivity(text)
    if total_conn is not None:
        return total_conn, total_conn, current_conn

    if not text:
        return None, None, None
    available: int | None = None
    licensed: int | None = None
    in_use: int | None = None
    for line in text.splitlines():
        low = line.lower().strip()
        if not low or "ccu" not in low:
            continue
        m = re.search(r"(\d+)", line)
        if not m:
            continue
        val = int(m.group(1))
        if "available" in low:
            available = val
        elif "licensed" in low or "license" in low and "in use" not in low:
            if licensed is None or "licensed" in low:
                licensed = val
        elif "in use" in low or "in-use" in low or "used" in low:
            in_use = val
    return available, licensed, in_use
