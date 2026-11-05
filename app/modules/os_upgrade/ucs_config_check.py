"""UCS /config 파일 기반 오프라인 점검 항목 파싱."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.modules.os_upgrade.k7727_versions import BigIpTargetVersion, find_version_entry
from app.modules.os_upgrade.overview_parsers import _cidr, _is_floating_self_block
from app.modules.os_upgrade.pre_checklist import LicenseUpgradeCheck
from app.modules.os_upgrade.pre_checklist_parsers import (
    _parse_date_token,
    parse_service_check_date,
)
from app.modules.os_upgrade.ucs_reader import merge_ucs_config, parse_hostname_from_config


@dataclass(frozen=True)
class UcsCheckRow:
    label: str
    value: str
    remark: str = ""


@dataclass(frozen=True)
class UcsVlanRow:
    vlan: str
    interface: str
    tagging: str
    trunk_members: str = ""


@dataclass(frozen=True)
class UcsRouteRow:
    name: str
    gw: str
    network: str


@dataclass(frozen=True)
class UcsSelfIpRow:
    name: str
    address: str
    vlan: str
    floating: bool


@dataclass
class UcsConfigCheckResult:
    hostname: str = ""
    rows: list[UcsCheckRow] = field(default_factory=list)
    vlan_rows: list[UcsVlanRow] = field(default_factory=list)
    self_ip_rows: list[UcsSelfIpRow] = field(default_factory=list)
    route_rows: list[UcsRouteRow] = field(default_factory=list)
    license_check: LicenseUpgradeCheck | None = None
    errors: list[str] = field(default_factory=list)

    def ordered_summary(self) -> list[str]:
        return [f"{r.label}: {r.value or '—'}" for r in self.rows]

    def brief_summary_line(self) -> str:
        by_label = {r.label: (r.value or "").strip() for r in self.rows}
        platform = by_label.get("Platform") or "—"
        hostname = self.hostname or by_label.get("Hostname") or "—"
        return f"Platform: {platform} · Hostname: {hostname}"


def _q(s: str) -> str:
    m = re.search(r'"([^"]+)"', s or "")
    if m:
        return m.group(1).strip()
    return (s or "").strip().strip('"')


def _field(body: str, *names: str) -> str:
    for name in names:
        m = re.search(rf'{re.escape(name)}\s+"([^"]+)"', body, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(rf"{re.escape(name)}\s+(\S+)", body, re.I)
        if m:
            return m.group(1).strip().strip('"')
    return ""


def _split_blocks(text: str, keyword: str) -> list[tuple[str, str]]:
    pat = rf"{keyword}\s+(\S+)\s*\{{"
    parts = re.split(pat, text, flags=re.I)
    out: list[tuple[str, str]] = []
    i = 1
    while i + 1 < len(parts):
        out.append((parts[i].strip(), parts[i + 1]))
        i += 2
    return out


def _brace_block(text: str, open_brace_index: int) -> str:
    depth = 0
    for i in range(open_brace_index, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index : i + 1]
    return ""


def _is_physical_interface(name: str) -> bool:
    short = name.rstrip("/").split("/")[-1]
    return bool(
        re.match(r"^\d+\.\d+$", short)
        or re.match(r"^mgmt$", short, re.I)
        or re.match(r"^port-channel[\d.]+$", short, re.I)
    )


def parse_cm_device_self(bigip_base: str) -> dict[str, str]:
    """self-device true 가 있는 cm device = 이 UCS를 떠난 로컬 장비."""
    blocks = _split_blocks(bigip_base, "cm device")
    chosen: tuple[str, str] | None = None
    for name, body in blocks:
        if re.search(r"\bself-device\s+true\b", body, re.I):
            chosen = (name, body)
            break
    if chosen is None:
        for name, body in blocks:
            if re.search(r"\bplatform-id\s+\S+", body, re.I):
                chosen = (name, body)
                break
    if chosen is None and blocks:
        chosen = blocks[0]
    if chosen is None:
        return {}
    _name, body = chosen
    serial = _field(body, "chassis-id").strip()
    return {
        "device_name": _name,
        "platform": _field(body, "marketing-name"),
        "hostname": _field(body, "hostname"),
        "serial": serial,
        "tmos_version": _field(body, "version"),
        "mgmt_ip": _field(body, "management-ip"),
    }


def parse_trunk_map(bigip_base: str) -> dict[str, list[str]]:
    trunks: dict[str, list[str]] = {}
    for name, body in _split_blocks(bigip_base, "net trunk"):
        members = _parse_trunk_member_interfaces(body)
        short = name.rstrip("/").split("/")[-1]
        trunks[short] = members
        trunks[name] = members
    return trunks


def _parse_trunk_member_interfaces(body: str) -> list[str]:
    m = re.search(r"interfaces\s*\{", body, re.I)
    if not m:
        return []
    block = _brace_block(body, m.end() - 1)
    if not block:
        return []
    inner = block[1:-1]
    members: list[str] = []
    for tok in re.finditer(r"(\d+\.\d+|mgmt|port-channel[\d.]+)", inner, re.I):
        val = tok.group(1)
        if val not in members:
            members.append(val)
    return members


def _vlan_numeric_tag(body: str) -> str:
    m = re.search(r"^\s*tag\s+(\d+)\s*$", body, re.I | re.M)
    return m.group(1) if m else ""


def _parse_vlan_iface_bindings(body: str) -> list[tuple[str, bool]]:
    """interfaces { ex_tr { } } 또는 1.5 { tagged } — trunk 이름 포함."""
    m = re.search(r"interfaces\s*\{", body, re.I)
    if not m:
        return []
    block = _brace_block(body, m.end() - 1)
    if not block:
        return []
    inner = block[1:-1]
    entries: list[tuple[str, bool]] = []
    for im in re.finditer(r"([\w./-]+)\s*\{([^}]*)\}", inner):
        iface = im.group(1).strip()
        tagged = bool(re.search(r"\btagged\b", im.group(2), re.I))
        entries.append((iface, tagged))
    return entries


def _format_vlan_tagging(vlan_tag: str, iface_tagged: bool) -> str:
    mode = "Tag" if iface_tagged else "Untag"
    return f"{vlan_tag} {mode}" if vlan_tag else mode


def parse_ucs_vlan_rows(bigip_base: str) -> list[UcsVlanRow]:
    trunks = parse_trunk_map(bigip_base)
    rows: list[UcsVlanRow] = []
    for vlan_name, body in _split_blocks(bigip_base, "net vlan"):
        vlan_tag = _vlan_numeric_tag(body)
        bindings = _parse_vlan_iface_bindings(body)
        if not bindings:
            rows.append(
                UcsVlanRow(
                    vlan=vlan_name,
                    interface="—",
                    tagging="—" if not vlan_tag else f"{vlan_tag} —",
                    trunk_members="—",
                )
            )
            continue
        for iface_name, is_tagged in bindings:
            short = iface_name.rstrip("/").split("/")[-1]
            members = trunks.get(iface_name) or trunks.get(short) or []
            uses_trunk = bool(members) or not _is_physical_interface(short)
            if uses_trunk:
                iface_col = "Trunk 사용"
                trunk_col = ", ".join(members) if members else "—"
            else:
                iface_col = short
                trunk_col = "—"
            rows.append(
                UcsVlanRow(
                    vlan=vlan_name,
                    interface=iface_col,
                    tagging=_format_vlan_tagging(vlan_tag, is_tagged),
                    trunk_members=trunk_col,
                )
            )
    return rows


def parse_ucs_route_rows(bigip_conf: str) -> list[UcsRouteRow]:
    rows: list[UcsRouteRow] = []
    for name, body in _split_blocks(bigip_conf, "net route"):
        gw = _field(body, "gw", "gateway")
        network = _field(body, "network", "destination")
        rows.append(UcsRouteRow(name=name, gw=gw or "—", network=network or "—"))
    return rows


def parse_ucs_self_ip_rows(bigip_base: str) -> list[UcsSelfIpRow]:
    rows: list[UcsSelfIpRow] = []
    for name, body in _split_blocks(bigip_base, "net self"):
        addr = _field(body, "address")
        if not addr:
            continue
        mask = _field(body, "netmask")
        vlan = _field(body, "vlan")
        rows.append(
            UcsSelfIpRow(
                name=name,
                address=_cidr(addr, mask) or addr,
                vlan=vlan,
                floating=_is_floating_self_block(body),
            )
        )
    return rows


def evaluate_license_from_ucs(
    license_text: str, target: BigIpTargetVersion
) -> LicenseUpgradeCheck:
    """UCS bigip.license — K7727 날짜와 Service Check Date (오프라인 비교)."""
    svc = parse_service_check_date(license_text)
    lic = target.license_check_date.strftime("%Y/%m/%d")
    svc_d = _parse_date_token(svc)
    if not svc_d:
        return LicenseUpgradeCheck(
            target_version=target.version,
            license_check_date=lic,
            service_check_date=svc or "—",
            verdict="확인 불가",
            detail="Service Check Date 파싱 실패",
        )
    verdict = "OS Upgrade 가능" if svc_d >= target.license_check_date else "License Active 필요"
    return LicenseUpgradeCheck(
        target_version=target.version,
        license_check_date=lic,
        service_check_date=svc,
        verdict=verdict,
        detail="K7727 기준 오프라인 비교",
    )


def analyze_ucs_config_texts(
    texts: dict[str, str],
    *,
    target_version: str | None = None,
) -> UcsConfigCheckResult:
    base = texts.get("bigip_base.conf", "")
    conf = texts.get("bigip.conf", "")
    license_text = texts.get("bigip.license", "")

    result = UcsConfigCheckResult()
    dev = parse_cm_device_self(base)
    result.hostname = dev.get("hostname") or parse_hostname_from_config(
        merge_ucs_config(texts)
    )

    result.rows = [
        UcsCheckRow("Platform", dev.get("platform", "")),
        UcsCheckRow("Hostname", dev.get("hostname", "")),
        UcsCheckRow("Serial Number", dev.get("serial", "")),
        UcsCheckRow("TMOS Version", dev.get("tmos_version", "")),
    ]

    lic_row = UcsCheckRow("OS Upgrade 가능 여부", "—", remark="목표 버전 미선택")
    if target_version:
        ent = find_version_entry(target_version)
        if ent and license_text.strip():
            lic = evaluate_license_from_ucs(license_text, ent)
            result.license_check = lic
            lic_row = UcsCheckRow(
                "OS Upgrade 가능 여부",
                lic.verdict,
                remark=f"Service Check {lic.service_check_date} · K7727 {ent.license_check_date:%Y-%m-%d}",
            )
        elif ent:
            lic_row = UcsCheckRow(
                "OS Upgrade 가능 여부",
                "확인 불가",
                remark="bigip.license 없음",
            )
        else:
            lic_row = UcsCheckRow("OS Upgrade 가능 여부", "확인 불가", remark="목표 버전 매핑 없음")
    result.rows.append(lic_row)

    result.rows.append(UcsCheckRow("TMOS MGMT-IP", dev.get("mgmt_ip", "")))
    result.vlan_rows = parse_ucs_vlan_rows(base)
    result.self_ip_rows = parse_ucs_self_ip_rows(base)
    result.route_rows = parse_ucs_route_rows(conf)

    if not dev.get("hostname"):
        result.errors.append("cm device (self-device) 정보 없음")
    if not result.hostname:
        result.errors.append("Hostname 없음")

    return result
