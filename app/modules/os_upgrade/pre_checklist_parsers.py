from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from app.modules.health_check.tmos_bash_parse import parse_ha_status
from app.modules.os_upgrade.k7727_versions import BigIpTargetVersion
from app.modules.os_upgrade.overview_parsers import parse_tmos_list_net_route


@dataclass(frozen=True)
class LicenseUpgradeCheck:
    target_version: str
    license_check_date: str
    service_check_date: str
    verdict: str
    detail: str


@dataclass(frozen=True)
class VlanMacRow:
    vlan: str
    mac: str


@dataclass(frozen=True)
class ArpRow:
    name: str
    address: str
    hwaddress: str
    vlan: str
    expire_in_sec: str
    status: str


@dataclass(frozen=True)
class GatewayPingRow:
    gw: str
    result: str
    detail: str


@dataclass(frozen=True)
class HaCheckResult:
    ha_mode: str
    is_redundant: bool
    failover_summary: str
    detail: str


# F5 BIG-IP 기본 crontab (사용자 정의 제외)
_F5_DEFAULT_CRON_MARKERS: tuple[str, ...] = (
    "/usr/bin/diskmonitor",
    "/usr/bin/diskwearoutstat",
    "/usr/bin/updatecheck",
    "/usr/bin/phonehome_upload",
    "/usr/bin/coreexpiration",
    "/usr/bin/copy_rrd",
)


def _is_f5_default_cron_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.upper().startswith("MAILTO="):
        return True
    return any(marker in s for marker in _F5_DEFAULT_CRON_MARKERS)


def filter_custom_crontab_lines(crontab_text: str) -> list[str]:
    """F5 기본 스케줄 제외한 사용자 crontab 줄만."""
    custom: list[str] = []
    for line in crontab_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _is_f5_default_cron_line(stripped):
            continue
        custom.append(stripped)
    return custom


@dataclass(frozen=True)
class IcallEntry:
    kind: str
    name: str


@dataclass(frozen=True)
class LinuxCheckResult:
    icall_summary: str
    icall_entries: tuple[IcallEntry, ...]
    crontab_summary: str
    crontab_custom_lines: tuple[str, ...]
    scripts_summary: str
    script_names: tuple[str, ...]


def _parse_date_token(text: str) -> date | None:
    text = (text or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def parse_service_check_date(license_text: str) -> str:
    for line in license_text.splitlines():
        if "service check date" in line.lower():
            m = re.search(
                r"Service\s+Check\s+Date\s+(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{8})",
                line,
                re.I,
            )
            if m:
                d = _parse_date_token(m.group(1))
                if d:
                    return d.strftime("%Y/%m/%d")
            parts = line.split()
            if parts:
                d = _parse_date_token(parts[-1])
                if d:
                    return d.strftime("%Y/%m/%d")
    return ""


def evaluate_license_upgrade(
    service_check_raw: str,
    target: BigIpTargetVersion,
    *,
    internet_available: bool = True,
) -> LicenseUpgradeCheck:
    svc = parse_service_check_date(service_check_raw)
    lic = target.license_check_date.strftime("%Y/%m/%d")
    if not internet_available:
        return LicenseUpgradeCheck(
            target_version=target.version,
            license_check_date=lic,
            service_check_date=svc or "—",
            verdict="인터넷 사용 불가",
            detail=(
                "K7727 License Check Date 확인에 인터넷(my.f5.com) 연결이 필요합니다. "
                "오프라인 환경에서는 OS Upgrade 가능 여부를 자동 판정하지 않습니다."
            ),
        )
    svc_d = _parse_date_token(svc)
    lic_d = target.license_check_date
    if not svc_d:
        return LicenseUpgradeCheck(
            target_version=target.version,
            license_check_date=lic,
            service_check_date=svc or "—",
            verdict="확인 불가",
            detail="Service Check Date 파싱 실패",
        )
    if svc_d >= lic_d:
        verdict = "OS Upgrade 가능"
    else:
        verdict = "License Active 필요"
    return LicenseUpgradeCheck(
        target_version=target.version,
        license_check_date=lic,
        service_check_date=svc,
        verdict=verdict,
        detail="",
    )


def parse_vlan_mac_table(vlan_show_text: str) -> list[VlanMacRow]:
    rows: list[VlanMacRow] = []
    blocks = re.split(r"Net::Vlan:\s*", vlan_show_text, flags=re.I)
    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        vlan_name = lines[0].strip()
        mac = ""
        for line in lines[1:]:
            m = re.search(r"Mac\s+Address\s*\([^)]*\)\s+([0-9a-fA-F:]{11,17})", line, re.I)
            if m:
                mac = m.group(1).strip()
                break
        if vlan_name:
            rows.append(VlanMacRow(vlan=vlan_name, mac=mac or "—"))
    rows.sort(key=lambda r: r.vlan.lower())
    return rows


def parse_arp_table(arp_text: str) -> list[ArpRow]:
    rows: list[ArpRow] = []
    for line in arp_text.splitlines():
        line = line.strip()
        if not line or line.startswith("-") or line.lower().startswith("net::arp"):
            continue
        if line.lower().startswith("name") and "address" in line.lower():
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        name, addr, hw = parts[0], parts[1], parts[2]
        vlan = parts[3]
        expire = parts[4]
        status = parts[5]
        rows.append(
            ArpRow(
                name=name,
                address=addr,
                hwaddress=hw,
                vlan=vlan,
                expire_in_sec=expire,
                status=status,
            )
        )
    return rows


def unique_gateway_ips(route_text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in parse_tmos_list_net_route(route_text):
        gw = (row.gw or "").strip()
        if not gw or gw == "—" or gw in seen:
            continue
        seen.add(gw)
        out.append(gw)
    return out


_PING_TIMEOUT_MARKERS: tuple[str, ...] = (
    "요청 시간이 만료",
    "request timed out",
    "timed out",
    "time exceeded",
    "no answer",
    "destination host unreachable",
    "network is unreachable",
)


def _ping_line_is_timeout(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in _PING_TIMEOUT_MARKERS)


def _ping_line_is_reply(line: str) -> bool:
    """성공 응답 줄 — Linux icmp / Windows·한국어 응답."""
    if re.search(r"bytes from\s+\S+:\s*icmp_seq=", line, re.I):
        return True
    if "의 응답" in line:
        return True
    if re.search(r"reply from\s+\S+", line, re.I):
        return True
    if re.search(r"bytes=\d+.*ttl=", line, re.I):
        return True
    return False


def _ping_reply_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if _ping_line_is_reply(line))


def _ping_timeout_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if _ping_line_is_timeout(line))


def _ping_stats_from_summary(text: str) -> tuple[int | None, int | None]:
    low = text.lower()
    m = re.search(r"(\d+)\s+packets?\s+transmitted[,\s]+(\d+)\s+received", low)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"보냄\s*=\s*(\d+)\s*,\s*받음\s*=\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)%\s*packet loss", low)
    if m and int(m.group(1)) >= 100:
        m_tx = re.search(r"(\d+)\s+packets?\s+transmitted[,\s]+(\d+)\s+received", low)
        if m_tx:
            return int(m_tx.group(1)), int(m_tx.group(2))
    return None, None


def _parse_ping_counts(ping_output: str) -> tuple[int | None, int | None]:
    """(시도, 성공) — 통계 줄 우선, 없으면 응답/타임아웃 줄 수."""
    text = ping_output or ""
    stats = _ping_stats_from_summary(text)
    if stats[0] is not None and stats[1] is not None:
        return stats

    replies = _ping_reply_count(text)
    timeouts = _ping_timeout_count(text)
    if replies:
        tx = replies + timeouts if timeouts else replies
        return tx, replies
    if timeouts:
        return timeouts, 0
    return None, None


def _summarize_ping_detail(ping_output: str) -> str:
    """Raw ping stdout → 짧은 요약 (n회 시도 · m회 성공)."""
    text = (ping_output or "").strip()
    if not text:
        return "출력 없음"
    low = text.lower()
    tx, rx = _parse_ping_counts(text)
    if tx is not None and rx is not None:
        return f"{tx}회 시도 · {rx}회 성공"

    if "unknown host" in low or "not found" in low or "cannot resolve" in low:
        return "호스트 확인 실패"
    if _ping_timeout_count(text) and _ping_reply_count(text) == 0:
        return "응답 없음 (시간 만료)"
    if "100% packet loss" in low or "100.0% packet loss" in low or "100% 손실" in text:
        return "100% packet loss"
    if "permission denied" in low or "operation not permitted" in low:
        return "ping 실행 불가"
    if re.search(r"(?:ping|pING)\s+\S+", text) and _ping_reply_count(text) == 0:
        return "응답 없음"
    first = text.splitlines()[0].strip()
    return first[:80] if first else "요약 불가"


def parse_ping_result(gw: str, ping_output: str) -> GatewayPingRow:
    text = ping_output or ""
    low = text.lower()
    detail = _summarize_ping_detail(text)
    if "unknown host" in low or "not found" in low or "cannot resolve" in low:
        return GatewayPingRow(gw=gw, result="FAIL", detail=detail)
    if "permission denied" in low or "operation not permitted" in low:
        return GatewayPingRow(gw=gw, result="SKIP", detail=detail)

    tx, rx = _parse_ping_counts(text)
    if tx is not None and rx is not None:
        if rx > 0:
            return GatewayPingRow(gw=gw, result="OK", detail=detail)
        return GatewayPingRow(gw=gw, result="FAIL", detail=detail)

    if _ping_reply_count(text) > 0:
        n = _ping_reply_count(text)
        return GatewayPingRow(
            gw=gw,
            result="OK",
            detail=f"{n}회 시도 · {n}회 성공",
        )

    if (
        _ping_timeout_count(text) > 0
        or "100% packet loss" in low
        or "100.0% packet loss" in low
        or "100% 손실" in text
    ):
        return GatewayPingRow(gw=gw, result="FAIL", detail=detail)

    if re.search(r"(?:ping|pING)\s+\S+", text, re.I) and _ping_reply_count(text) == 0:
        return GatewayPingRow(gw=gw, result="FAIL", detail=detail)
    return GatewayPingRow(gw=gw, result="UNKNOWN", detail=detail)


def parse_ha_failover_check(
    failover_show: str,
    ha_group_list: str,
    failover_status_show: str,
) -> HaCheckResult:
    combined = "\n".join((failover_show, ha_group_list, failover_status_show))
    ha_mode, ha_detail = parse_ha_status(combined)
    is_redundant = ha_mode in ("Active", "Standby")
    parts: list[str] = []

    for m in re.finditer(r"ha-group\s+(\S+)\s*\{", ha_group_list, re.I):
        parts.append(f"ha-group: {m.group(1)}")

    fs_block = re.search(r"fail-safe\s*\{([^}]+)\}", failover_show, re.I | re.S)
    if fs_block:
        inner = fs_block.group(1)
        action = re.search(r"action\s+(\S+)", inner, re.I)
        timeout = re.search(r"timeout\s+(\S+)", inner, re.I)
        vlan = re.search(r"vlan\s+(\S+)", inner, re.I)
        gateway = re.search(r"gateway\s+(\S+)", inner, re.I)
        fs_parts = ["Fail-Safe"]
        if action:
            fs_parts.append(f"action={action.group(1)}")
        if timeout:
            fs_parts.append(f"timeout={timeout.group(1)}")
        if vlan:
            fs_parts.append(f"vlan={vlan.group(1)}")
        if gateway:
            fs_parts.append(f"gateway={gateway.group(1)}")
        parts.append(", ".join(fs_parts))

    pool_m = re.search(r"pool\s+(\S+)", failover_show, re.I)
    if pool_m and "fail-safe" not in (pool_m.group(0) or "").lower():
        parts.append(f"pool: {pool_m.group(1)}")

    if not is_redundant:
        summary = "Standalone — 이중화 미구성"
    elif parts:
        summary = " | ".join(parts)
    else:
        summary = f"{ha_mode} — Failover 옵션(ha-group/fail-safe) 미검출"

    return HaCheckResult(
        ha_mode=ha_mode,
        is_redundant=is_redundant,
        failover_summary=summary,
        detail=ha_detail[:400],
    )


def parse_icall_entries(icall_text: str) -> list[IcallEntry]:
    """tmsh list sys icall — handler / script 항목 (이름 단위)."""
    entries: list[IcallEntry] = []
    seen: set[tuple[str, str]] = set()
    for line in icall_text.splitlines():
        m = re.match(
            r"sys\s+icall\s+(handler|script)\s+(.+?)\s*\{?\s*$",
            line.strip(),
            re.I,
        )
        if not m:
            continue
        name = m.group(2).strip().rstrip("{").strip()
        key = (m.group(1).lower(), name)
        if key in seen:
            continue
        seen.add(key)
        entries.append(IcallEntry(kind=m.group(1), name=name))
    entries.sort(key=lambda e: (e.kind, e.name.lower()))
    return entries


def parse_linux_checks(
    icall_text: str,
    crontab_text: str,
    bash_ls_text: str,
) -> LinuxCheckResult:
    icall_entries = parse_icall_entries(icall_text)
    icall_summary = f"{len(icall_entries)}건" if icall_entries else "없음"

    custom_cron = filter_custom_crontab_lines(crontab_text)
    cron_body = crontab_text.strip()
    if not cron_body or "no crontab" in cron_body.lower():
        cron_summary = "없음"
    elif custom_cron:
        cron_summary = f"{len(custom_cron)}건"
    else:
        cron_summary = "없음"

    scripts = [
        ln.strip()
        for ln in bash_ls_text.splitlines()
        if ln.strip().endswith(".sh")
    ]
    scripts_summary = f"{len(scripts)}건" if scripts else "없음"

    return LinuxCheckResult(
        icall_summary=icall_summary,
        icall_entries=tuple(icall_entries),
        crontab_summary=cron_summary,
        crontab_custom_lines=tuple(custom_cron),
        scripts_summary=scripts_summary,
        script_names=tuple(scripts),
    )
