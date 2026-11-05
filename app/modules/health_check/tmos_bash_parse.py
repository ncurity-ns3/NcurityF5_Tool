from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_CLOCK_SEP = "---F5TOOL_CLOCK---"


@dataclass(frozen=True)
class CamValues:
    """Current / Average / Max (엑셀 정기점검 표 형식)."""

    current: str
    average: str
    maximum: str

    def display(self) -> str:
        return f"{self.current} / {self.average} / {self.maximum}"


def parse_uptime_stdout(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"up\s+(\d+)\s+days?", text, re.I)
    if m:
        days = int(m.group(1))
        if days <= 0:
            return None
        return float(days) * 86400
    m = re.search(r"up\s+(\d+)\s+min", text, re.I)
    if m:
        mins = int(m.group(1))
        if mins <= 0:
            return None
        return float(mins) * 60
    m = re.search(r"up\s+(\d+):(\d+)", text)
    if m:
        hours, mins = int(m.group(1)), int(m.group(2))
        if hours == 0 and mins == 0:
            return None
        return hours * 3600 + mins * 60
    m = re.search(r"(\d+(?:\.\d+)?)\s+seconds", text, re.I)
    if m:
        sec = float(m.group(1))
        return sec if sec >= 300 else None
    return None


def format_uptime_display(seconds: float) -> str:
    days = seconds / 86400
    if days >= 1:
        return f"{days:.0f} days"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 60:.0f} min"


def parse_df_paths(text: str, paths: tuple[str, ...] = ("/var", "/shared")) -> dict[str, float]:
    """df -h: match exact mount points only (e.g. /var, /shared)."""
    result: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("Filesystem") or not line.strip():
            continue
        m = re.search(r"(\d+)%\s+(\S+)\s*$", line.strip())
        if not m:
            continue
        pct = float(m.group(1))
        mount = m.group(2)
        if mount in paths:
            result[mount] = pct
    return result


def parse_ntpq_np(text: str) -> dict[str, Any]:
    """ntpq -np: * = synced peer."""
    synced: list[str] = []
    peers: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "====" in s or s.lower().startswith("remote"):
            continue
        if s[0] in "*+-#o.":
            mark = s[0]
            parts = s[1:].split()
            if parts:
                peers.append(parts[0])
                if mark == "*":
                    synced.append(parts[0])
        elif re.match(r"^\d+\.\d+", s):
            parts = s.split()
            if parts:
                peers.append(parts[0])
    return {"synced": synced, "peers": peers, "is_synced": bool(synced)}


def is_virtual_edition_hardware(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return (
        "virtual edition" in low
        or "bigip virtual" in low
        or ("chassis" in low and "virtual" in low)
        or "marketing name" in low and "virtual" in low
    )


def parse_sys_service(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        low = line.lower()
        for name in ("tmm", "bigd", "mcpd"):
            if name in low and name not in found:
                if "running" in low:
                    found[name] = "running"
                elif "stopped" in low or "stop" in low:
                    found[name] = "stopped"
                else:
                    m = re.search(rf"{name}\s+(\S+)", low)
                    found[name] = m.group(1) if m else "seen"
    return found


def parse_vlan_in_use_interfaces(vlan_text: str) -> set[str]:
    """tmsh list net vlan — interfaces referenced by VLANs in use."""
    names: set[str] = set()
    for m in re.finditer(r"interfaces?\s*\{([^}]+)\}", vlan_text, re.I | re.S):
        for token in re.split(r"\s+", m.group(1).strip()):
            if re.match(r"^(\d+\.\d+|mgmt|port-channel[\d.]+)$", token, re.I):
                names.add(token.lower())
    for m in re.finditer(r"Interface\s+(\S+)", vlan_text, re.I):
        names.add(m.group(1).lower())
    if "mgmt" in vlan_text.lower() or "management" in vlan_text.lower():
        names.add("mgmt")
    return names


def parse_net_interface_status(show_text: str) -> dict[str, str]:
    """tmsh show net interface -> name -> oper status (up/down/...)."""
    status: dict[str, str] = {}
    current = ""
    for line in show_text.splitlines():
        m = re.match(
            r"^\s*(?:Net::Interface\s+)?(?:Interface\s+)?(\d+\.\d+|mgmt)\b",
            line,
            re.I,
        )
        if m:
            current = m.group(1).lower()
        low = line.lower().strip()
        if not current:
            continue
        if low.startswith("status") or "line-status" in low or "oper-status" in low:
            if re.search(r"\bup\b", low) and "down" not in low:
                status[current] = "up"
            elif "down" in low or "disconnected" in low:
                status[current] = "down"
    if not status:
        for line in show_text.splitlines():
            m = re.match(r"^(\d+\.\d+|mgmt)\s+(\S+)", line.strip(), re.I)
            if m:
                oper = m.group(2).lower()
                status[m.group(1).lower()] = "up" if oper == "up" else oper
    return status


def check_vlan_interfaces_up(
    vlan_text: str,
    interface_text: str,
) -> tuple[list[str], list[str]]:
    """
    Returns (up_list, down_list) for VLAN in-use interfaces.
    Missing or non-up oper status is treated as down.
    """
    in_use = parse_vlan_in_use_interfaces(vlan_text)
    oper = parse_net_interface_status(interface_text)
    if not in_use and oper:
        in_use = set(oper.keys())
    up_list: list[str] = []
    down_list: list[str] = []
    for name in sorted(in_use):
        if oper.get(name) == "up":
            up_list.append(name)
        else:
            down_list.append(name)
    return up_list, down_list


def split_clock_bash(text: str) -> tuple[str, str]:
    if _CLOCK_SEP in text:
        date_part, clock_part = text.split(_CLOCK_SEP, 1)
        return date_part.strip(), clock_part.strip()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "", ""
    return lines[0].strip(), "\n".join(lines[1:]).strip()


_EN_MONTH = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _parse_unix_date_clock(text: str) -> datetime | None:
    """Thu May 21 15:40:34 KST 2026 — locale-independent (Windows ko-KR safe)."""
    m = re.search(
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"(\d{1,2})\s+(\d{2}:\d{2}:\d{2})(?:\s+[A-Za-z]{2,6})?\s+(\d{4})\b",
        text,
        re.I,
    )
    if not m:
        return None
    month = _EN_MONTH.get(m.group(1).lower()[:3])
    if not month:
        return None
    try:
        return datetime(
            int(m.group(4)),
            month,
            int(m.group(2)),
            *map(int, m.group(3).split(":")),
        )
    except ValueError:
        return None


def _extract_datetime_token(text: str) -> datetime | None:
    parsed = _parse_unix_date_clock(text)
    if parsed:
        return parsed
    patterns = (
        (
            r"(\w{3}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})(?:\s+[A-Za-z]{2,6})?\s+(\d{4})",
            "%a %b %d %H:%M:%S %Y",
        ),
        (
            r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})",
            "%Y-%m-%d %H:%M:%S",
        ),
    )
    for pat, fmt in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        raw = m.group(1) if fmt.startswith("%a") else m.group(1)
        if fmt.startswith("%a") and m.lastindex and m.lastindex >= 2:
            raw = f"{m.group(1)} {m.group(2)}"
        for try_fmt in (fmt, fmt.replace("T", " ")):
            try:
                return datetime.strptime(raw.replace("T", " "), try_fmt)
            except ValueError:
                continue
    return None


def compare_system_clock(
    date_text: str, clock_text: str, *, max_delta_sec: int = 2
) -> tuple[bool, str, str]:
    """Compare bash `date` vs `clock` — no meaningful drift."""
    combined = f"{date_text}\n{clock_text}"
    dt_date = _extract_datetime_token(date_text)
    dt_clock = _extract_datetime_token(clock_text) or _extract_datetime_token(combined)
    if dt_date and dt_clock:
        delta = abs((dt_date - dt_clock).total_seconds())
        summary = dt_date.strftime("%a %b %d %H:%M:%S %Y")
        detail = f"date vs clock Δ{delta:.0f}s"
        return delta <= max_delta_sec, summary, detail
    times = set(re.findall(r"\d{2}:\d{2}:\d{2}", combined))
    if len(times) == 1:
        dt = _extract_datetime_token(date_text) or _extract_datetime_token(combined)
        val = (
            dt.strftime("%a %b %d %H:%M:%S %Y")
            if dt
            else date_text.strip()[:80]
        )
        return True, val, "date vs clock time match (HH:MM:SS)"
    dt_only = _extract_datetime_token(date_text) or _extract_datetime_token(combined)
    if dt_only and not clock_text.strip():
        return True, dt_only.strftime("%a %b %d %H:%M:%S %Y"), "date only (clock 없음)"
    return False, date_text.strip()[:80], "date/clock parse 실패"


def parse_ha_status(text: str) -> tuple[str, str]:
    """
    TMOS HA: Standalone | Active | Standby | Force Offline.
    Sources: tmsh show sys failover, show cm failover-status.
    """
    if not (text or "").strip():
        return "Unknown", "failover 출력 없음"
    detail = text.strip()[:300]
    low = detail.lower().replace("_", " ").replace("-", " ")
    if "force" in low and "offline" in low:
        return "Force Offline", detail
    m = re.search(r"status\s*:\s*([^\s\r\n]+)", detail, re.I)
    if m:
        token = m.group(1).upper().replace("-", " ")
        mapping = {
            "ACTIVE": "Active",
            "STANDBY": "Standby",
            "STANDALONE": "Standalone",
            "FORCED OFFLINE": "Force Offline",
            "FORCE OFFLINE": "Force Offline",
        }
        if token in mapping:
            return mapping[token], detail
    if re.search(r"\bstandalone\b", low):
        return "Standalone", detail
    if re.search(r"\bstandby\b", low):
        return "Standby", detail
    if re.search(r"\bactive\b", low) and not re.search(r"\binactive\b", low):
        return "Active", detail
    return "Unknown", detail


def parse_ssl_cert_check_stdout(text: str) -> dict[str, int]:
    """check-cert | grep -e expire | grep -v ca-bundle — one line per cert."""
    expired = 0
    will_expire = 0
    for line in text.splitlines():
        low = line.lower().strip()
        if not low or "syntax error" in low:
            continue
        if re.search(r"\bexpired\s+on\b", low):
            expired += 1
        elif re.search(r"\bwill\s+expire\s+on\b", low):
            will_expire += 1
    return {"expired": expired, "will_expire": will_expire}


def _ssl_cert_label_from_line(line: str) -> str:
    """인증서 파일명 우선 (/Common/…crt) — 동일 CN 11건 구분."""
    file_m = re.search(r"\bin file\s+(/[^\s]+)", line, re.I)
    if file_m:
        path = file_m.group(1).rstrip(")")
        return path.rsplit("/", 1)[-1] or path
    m = re.search(r"cn[=:\s]+([^\s,]+)", line, re.I)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"([*][\w.-]+\.[a-z]{2,})", line, re.I)
    if m2:
        return m2.group(1)
    return line.strip()[:80]


def _ssl_cert_lines(
    text: str,
    *,
    kind: str,
    limit: int = 50,
) -> tuple[list[str], int]:
    """kind: 'expired' | 'will_expire' — returns (labels, total_matching_lines)."""
    names: list[str] = []
    total = 0
    for line in text.splitlines():
        low = line.lower().strip()
        if not low or "syntax error" in low:
            continue
        is_expired = bool(re.search(r"\bexpired\s+on\b", low))
        is_will = bool(re.search(r"\bwill\s+expire\s+on\b", low))
        if kind == "expired":
            if not is_expired or is_will:
                continue
        elif kind == "will_expire":
            if not is_will or is_expired:
                continue
        else:
            continue
        total += 1
        if len(names) >= limit:
            continue
        label = _ssl_cert_label_from_line(line)
        if label and label not in names:
            names.append(label)
    return names, total


def parse_ssl_cert_expired_list(text: str, *, limit: int = 50) -> list[str]:
    labels, _ = _ssl_cert_lines(text, kind="expired", limit=limit)
    return labels


def parse_ssl_cert_will_expire_list(text: str, *, limit: int = 50) -> list[str]:
    labels, _ = _ssl_cert_lines(text, kind="will_expire", limit=limit)
    return labels


def format_ssl_cert_detail(text: str, *, limit: int = 50) -> str:
    """비고란: 만료·만료예정 — CN [파일명] (동일 CN 다건 구분)."""
    counts = parse_ssl_cert_check_stdout(text)
    expired_list, expired_total = _ssl_cert_lines(text, kind="expired", limit=limit)
    will_list, will_total = _ssl_cert_lines(text, kind="will_expire", limit=limit)
    parts: list[str] = []
    if expired_list or counts["expired"]:
        chunk = ", ".join(expired_list)
        if expired_total > len(expired_list):
            chunk += f" … 외 {expired_total - len(expired_list)}건"
        parts.append("만료: " + chunk)
    if will_list or counts["will_expire"]:
        chunk = ", ".join(will_list)
        if will_total > len(will_list):
            chunk += f" … 외 {will_total - len(will_list)}건"
        parts.append("만료예정: " + chunk)
    return " | ".join(parts)


def parse_tmos_psu_status(text: str) -> list[tuple[int, str]]:
    """
    tmsh show sys hardware — Appliance Power Supply Status table.
    Returns [(index, 'up'|'down'), ...].
    """
    rows: list[tuple[int, str]] = []
    in_section = False
    for line in text.splitlines():
        low = line.lower()
        if "appliance power supply status" in low:
            in_section = True
            continue
        if not in_section:
            continue
        if "index" in low and "status" in low:
            continue
        m = re.match(r"^\s*(\d+)\s+(\S+)", line)
        if m:
            idx = int(m.group(1))
            st = m.group(2).lower()
            norm = "up" if st == "up" else "down"
            rows.append((idx, norm))
            continue
        if rows and line.strip() and not line.startswith(" "):
            break
    return rows


def format_tmos_psu_value(psus: list[tuple[int, str]]) -> str:
    if not psus:
        return ""
    return " / ".join(f"PSU{idx} {st.capitalize()}" for idx, st in psus)


def parse_tmos_psu_up_down(text: str) -> tuple[int, int]:
    psus = parse_tmos_psu_status(text)
    if psus:
        up = sum(1 for _, s in psus if s == "up")
        return up, len(psus) - up
    up = 0
    down = 0
    for line in text.splitlines():
        low = line.lower()
        if "psu" not in low and "power supply" not in low:
            continue
        if re.search(r"\bup\b", low) and "down" not in low:
            up += 1
        elif "down" in low or "failed" in low or "absent" in low or "not-present" in low:
            down += 1
    return up, down


def _sane_celsius(value: float) -> bool:
    return -20.0 <= value <= 100.0


def parse_inlet_temperature_c(text: str) -> float | None:
    """Inlet Temperature Status — Temp(degC) column."""
    if is_virtual_edition_hardware(text):
        return None
    in_section = False
    for line in text.splitlines():
        if "inlet temperature status" in line.lower():
            in_section = True
            continue
        if not in_section:
            continue
        if "index" in line.lower() and "temp" in line.lower():
            continue
        m = re.match(
            r"^\s*\d+\s+\d+\s+(\d+(?:\.\d+)?)\s+\d+",
            line,
        )
        if m:
            v = float(m.group(1))
            if _sane_celsius(v):
                return v
        if in_section and line.strip() and not line.startswith(" "):
            break
    return None


def parse_sys_hardware_temp(text: str) -> float | None:
    if is_virtual_edition_hardware(text):
        return None
    inlet = parse_inlet_temperature_c(text)
    if inlet is not None:
        return inlet
    temps: list[float] = []
    for line in text.splitlines():
        low = line.lower()
        if "temperature" not in low and "temp" not in low:
            continue
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:c|°c|celsius)", line, re.I):
            v = float(m.group(1))
            if _sane_celsius(v) and v >= 10.0:
                temps.append(v)
        m = re.search(r"temperature[^\d]{0,30}(\d+(?:\.\d+)?)", line, re.I)
        if m:
            v = float(m.group(1))
            if _sane_celsius(v) and v >= 10.0:
                temps.append(v)
    return max(temps) if temps else None


def _parse_three_numbers(line: str) -> CamValues | None:
    nums = re.findall(r"(\d+(?:\.\d+)?(?:[KMG])?)", line)
    if len(nums) >= 3:
        return CamValues(current=nums[-3], average=nums[-2], maximum=nums[-1])
    return None


def _is_perf_section_header(line: str) -> bool:
    low = line.lower()
    return "current" in low and "average" in low


def _normalize_section(line: str) -> str:
    low = line.lower()
    if "cpu" in low and "performance" in low:
        return "cpu"
    if "memory used" in low and "%" in low:
        return "memory_used_header"
    if "memory" in low and "tmm" in low:
        return "memory_tmm"
    if "memory" in low and "performance" in low:
        return "memory_host"
    if "throughput" in low and "bit" in low:
        return "throughput_bits"
    if "throughput" in low and "packet" in low:
        return "throughput_packets"
    if "active connections" in low:
        return "active_connections_header"
    if "total new connections" in low:
        return "new_connections_header"
    return ""


def parse_sys_performance(text: str) -> dict[str, Any]:
    """
    Parse tmsh show sys performance (Sys::Performance blocks).
    """
    metrics: dict[str, Any] = {}
    section = ""
    in_active = False
    in_new = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or set(line.strip()) == {"-"}:
            continue
        sec_hint = _normalize_section(line) if _is_perf_section_header(line) else ""
        if sec_hint:
            section = sec_hint
            in_active = sec_hint == "active_connections_header"
            in_new = sec_hint == "new_connections_header"
            continue

        low = line.lower().strip()

        if section == "cpu" and "utilization" in low:
            cam = _parse_three_numbers(line)
            if cam:
                metrics["cpu"] = cam
            continue

        if re.search(r"tmm\s+memory\s+used", low, re.I) or re.search(
            r"tmm\s+memory\s+utilization", low, re.I
        ):
            cam = _parse_three_numbers(line)
            if cam:
                metrics["memory"] = cam
            continue

        if section == "memory_used_header" and "tmm" in low and "used" in low:
            cam = _parse_three_numbers(line)
            if cam:
                metrics["memory"] = cam
            continue

        if section == "throughput_bits" and low.startswith("service"):
            cam = _parse_three_numbers(line)
            if cam:
                metrics["throughput"] = cam
            continue

        if in_active and low.startswith("connections") and "client" not in low and "server" not in low:
            cam = _parse_three_numbers(line)
            if cam:
                metrics["active_connections"] = cam
            in_active = False
            continue

        if in_new and low.startswith("client connections"):
            cam = _parse_three_numbers(line)
            if cam:
                metrics["client_connections"] = cam
            in_new = False
            continue

        if "cpu" in low and "current" in low and "average" in low:
            section = "cpu"
        if "memory" in low and "tmm" in low:
            section = "memory_tmm"

    if "cpu" not in metrics:
        for block in re.split(r"Sys::Performance CPU", text, flags=re.I):
            cam = _parse_three_numbers(block)
            if cam:
                metrics["cpu"] = cam
                break
    if "memory" not in metrics:
        for block in re.split(r"Memory Used\(%\)", text, flags=re.I):
            for line in block.splitlines():
                if re.search(r"tmm\s+memory\s+used", line, re.I):
                    cam = _parse_three_numbers(line)
                    if cam:
                        metrics["memory"] = cam
                        break
            if "memory" in metrics:
                break

    return metrics
