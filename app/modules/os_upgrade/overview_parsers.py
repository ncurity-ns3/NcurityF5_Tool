from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.modules.health_check.tmos_bash_parse import is_virtual_edition_hardware


@dataclass(frozen=True)
class VlanRow:
    vlan: str
    interface: str
    tagging: str
    media: str


@dataclass(frozen=True)
class SelfIpRow:
    item: str
    value: str
    remark: str = ""


@dataclass(frozen=True)
class RouteRow:
    name: str
    gw: str


@dataclass
class SelfIpPick:
    self_cidr: str = ""
    floating_cidr: str = ""
    gateway: str = ""


def _norm_vlan_key(name: str) -> str:
    return str(name or "").strip().rstrip("/").split("/")[-1].lower()


def parse_tmos_platform_hw(hw_text: str) -> str:
    in_platform = False
    name = ""
    hypervisor = ""
    for line in hw_text.splitlines():
        if re.match(r"^\s*Platform\s*$", line, re.I):
            in_platform = True
            continue
        if in_platform and re.match(r"^\s*System Information", line, re.I):
            break
        if not in_platform:
            continue
        m = re.match(r"^\s*Name\s+(.+)", line)
        if m:
            name = m.group(1).strip()
        m = re.match(r"^\s*Hypervisor\s+(.+)", line)
        if m:
            hypervisor = m.group(1).strip()
    if not name:
        return ""
    if "virtual" in name.lower() and hypervisor:
        return f"{name} ({hypervisor})"
    return name


def parse_tmos_appliance_serial(hw_text: str) -> str:
    for line in hw_text.splitlines():
        m = re.search(r"Appliance Serial\s+(\S+)", line, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r"Chassis Serial\s+(\S+)", line, re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def parse_ve_serial_from_license(license_text: str) -> str:
    for line in license_text.splitlines():
        m = re.search(r"Registration key\s+(\S+)", line, re.I)
        if m:
            tail = m.group(1).split("-")[-1]
            return tail[-7:] if len(tail) >= 7 else tail
    return ""


def resolve_tmos_serial(hw_text: str, license_text: str) -> str:
    serial = parse_tmos_appliance_serial(hw_text)
    if serial and re.match(r"^f5-", serial, re.I):
        return serial
    if is_virtual_edition_hardware(hw_text):
        ve_sn = parse_ve_serial_from_license(license_text)
        if ve_sn:
            return ve_sn
    return serial


def parse_tmos_show_sys_version(text: str) -> str:
    version = ""
    build = ""
    for line in text.splitlines():
        m = re.match(r"^\s*Version\s+(\S+)", line)
        if m:
            version = m.group(1).strip()
        m = re.match(r"^\s*Build\s+(\S+)", line)
        if m:
            build = m.group(1).strip()
    if version and build:
        return f"{version}-{build}"
    return version


def parse_f5os_platform_state(text: str) -> str:
    for line in text.splitlines():
        if "state description" in line.lower():
            parts = line.split()
            if parts:
                return parts[-1].strip()
    m = re.search(r"state\s+description\s+(\S+)", text, re.I)
    return m.group(1).strip() if m else ""


def parse_f5os_system_version(text: str) -> str:
    """F5OS CLI `show system version` — e.g. system version os-version 1.8.0-16036."""
    if not text or not text.strip():
        return ""
    os_ver = ""
    svc_ver = ""
    for line in text.splitlines():
        low = line.lower()
        m = re.search(r"os-version\s+(\S+)", line, re.I)
        if m:
            os_ver = m.group(1).strip()
            continue
        m = re.search(r"service-version\s+(\S+)", line, re.I)
        if m and not svc_ver:
            svc_ver = m.group(1).strip()
            continue
        if "os-version" in low:
            parts = line.split()
            if parts:
                os_ver = parts[-1].strip()
        elif "service-version" in low and not svc_ver:
            parts = line.split()
            if parts:
                svc_ver = parts[-1].strip()
    if os_ver:
        return os_ver
    if svc_ver:
        return svc_ver
    for line in text.splitlines():
        m = re.match(r"^\s*(?:f5os-)?version\s*[: ]\s*(\S+)", line, re.I)
        if m:
            return m.group(1).strip()
        m = re.match(r"^\s*Version\s+(\S+)", line)
        if m:
            return m.group(1).strip()
    m = re.search(r"os-version\s*[:=]\s*(\S+)", text, re.I)
    if m:
        return m.group(1).strip()
    return ""


def parse_f5os_version_from_image_state(data: Any) -> str:
    """REST ``.../f5-system-image:image/state`` — in-use OS version."""
    if not isinstance(data, dict):
        return ""
    state = data
    for key in ("f5-system-image:state", "state", "image"):
        block = state.get(key) if isinstance(state, dict) else None
        if isinstance(block, dict):
            state = block
    if not isinstance(state, dict):
        return ""

    install = state.get("install")
    if isinstance(install, dict):
        for k in ("install-os-version", "install-service-version"):
            val = str(install.get(k, "") or "").strip()
            if val:
                return val

    os_block = state.get("os")
    entries: list[Any] = []
    if isinstance(os_block, dict):
        raw = os_block.get("os")
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = [raw]
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        in_use = ent.get("in-use")
        if in_use is None:
            in_use = ent.get("in_use")
        if str(in_use).lower() in ("true", "1", "yes"):
            for k in ("version-os", "version_os", "version"):
                val = str(ent.get(k, "") or "").strip()
                if val:
                    return val
    for ent in entries:
        if isinstance(ent, dict):
            val = str(ent.get("version-os", "") or ent.get("version", "") or "").strip()
            if val:
                return val
    return ""


def parse_f5os_system_image_version(text: str) -> str:
    """`show system image` — active OS row (USE true)."""
    if not text or not text.strip():
        return ""
    lines = [ln.rstrip() for ln in text.splitlines()]
    in_os = False
    for line in lines:
        low = line.lower()
        if "version os" in low and "status" in low:
            in_os = True
            continue
        if in_os:
            if re.match(r"^[-\s]+$", line) or not line.strip():
                continue
            if "version in" in low or "version iso" in low:
                break
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lower() in ("true", "false"):
                ver, use = parts[0], parts[-1].lower()
                if use == "true" and re.match(r"^\d", ver):
                    return ver
    return ""


def parse_interface_media_table(if_text: str) -> dict[str, str]:
    """tmsh show net interface — interface name -> Media column."""
    media: dict[str, str] = {}
    for line in if_text.splitlines():
        m = re.match(r"^(\d+\.\d+|mgmt)\s+\S+", line.strip(), re.I)
        if not m:
            continue
        iface = m.group(1).lower()
        parts = line.split()
        if len(parts) >= 2:
            media[iface] = parts[-1].strip()
    return media


def _parse_vlan_interface_tagging(body: str) -> list[tuple[str, bool]]:
    """interfaces { 1.3 { tagged } } — tagged 키워드로 Tag/Untag."""
    entries: list[tuple[str, bool]] = []
    im = re.search(r"interfaces\s*\{", body, re.I)
    if not im:
        return entries
    section = body[im.start() :]
    for m in re.finditer(
        r"(\d+\.\d+|mgmt|port-channel[\d.]+)\s*\{([^}]*)\}",
        section,
        re.I | re.S,
    ):
        iface = m.group(1)
        inner = m.group(2)
        entries.append((iface, bool(re.search(r"\btagged\b", inner, re.I))))
    if entries:
        return entries
    flat = re.search(r"interfaces?\s*\{([^}]+)\}", body, re.I | re.S)
    if flat:
        for token in re.split(r"\s+", flat.group(1).strip()):
            if re.match(r"^(\d+\.\d+|mgmt|port-channel[\d.]+)$", token, re.I):
                entries.append((token, False))
    return entries


def parse_vlan_blocks(vlan_text: str) -> list[tuple[str, list[tuple[str, bool]]]]:
    """vlan name -> [(interface, is_tagged), ...]."""
    rows: list[tuple[str, list[tuple[str, bool]]]] = []
    blocks = re.split(r"net\s+vlan\s+(\S+)\s*\{", vlan_text, flags=re.I)
    i = 1
    while i + 1 < len(blocks):
        name = blocks[i].strip()
        body = blocks[i + 1]
        i += 2
        rows.append((name, _parse_vlan_interface_tagging(body)))
    return rows


def _tmos_tagging_label(is_tagged: bool) -> str:
    return "Tag" if is_tagged else "Untag"


def parse_net_self_list(self_text: str) -> dict[str, list[tuple[str, str]]]:
    """tmsh list net self — vlan key -> [(address, netmask), ...]."""
    by_vlan: dict[str, list[tuple[str, str]]] = {}
    blocks = re.split(r"net\s+self\s+(\S+)\s*\{", self_text, flags=re.I)
    i = 1
    while i + 1 < len(blocks):
        _self_name = blocks[i].strip()
        body = blocks[i + 1]
        i += 2
        addr_m = re.search(r"address\s+(\S+)", body, re.I)
        mask_m = re.search(r"netmask\s+(\S+)", body, re.I)
        vlan_m = re.search(r"vlan\s+(\S+)", body, re.I)
        if not vlan_m or not addr_m:
            continue
        vlan_key = _norm_vlan_key(vlan_m.group(1))
        addr = addr_m.group(1).strip()
        mask = mask_m.group(1).strip() if mask_m else ""
        by_vlan.setdefault(vlan_key, []).append((addr, mask))
    return by_vlan


def _join_ip_subnet(pairs: list[tuple[str, str]]) -> tuple[str, str]:
    if not pairs:
        return "", ""
    ips: list[str] = []
    masks: list[str] = []
    for addr, mask in pairs:
        ips.append(addr)
        if mask and mask not in masks:
            masks.append(mask)
    ip_out = ", ".join(ips)
    subnet_out = ", ".join(masks) if masks else ""
    return ip_out, subnet_out


def build_tmos_vlan_table(vlan_text: str, if_text: str) -> list[VlanRow]:
    """VLAN only — Tagging은 interfaces { N { tagged } } 기준."""
    media = parse_interface_media_table(if_text)
    rows: list[VlanRow] = []
    for name, iface_entries in parse_vlan_blocks(vlan_text):
        if not iface_entries:
            iface_entries = [("—", False)]
        for iface, is_tagged in iface_entries:
            line_media = media.get(iface.lower(), "") if iface != "—" else ""
            rows.append(
                VlanRow(
                    vlan=name,
                    interface=iface,
                    tagging=_tmos_tagging_label(is_tagged),
                    media=line_media or "—",
                )
            )
    rows.sort(key=lambda r: (r.vlan.lower(), r.interface))
    return rows


def _is_floating_self_block(body: str) -> bool:
    floating = re.search(r"floating\s+(\S+)", body, re.I)
    if floating and floating.group(1).lower() in ("enabled", "true"):
        return True
    if floating and floating.group(1).lower() in ("disabled", "false"):
        return False
    tg = re.search(r"traffic-group\s+(\S+)", body, re.I)
    if tg:
        t = tg.group(1).lower()
        return "local-only" not in t and "traffic-group-local" not in t
    return False


def _side_from_name(name: str) -> str | None:
    low = name.lower()
    if re.search(r"(?:^|[/_-])(ex|ext|external|wan)(?:[/_-]|$)", low) or low.startswith(
        ("ex", "ext", "wan")
    ):
        return "external"
    if re.search(r"(?:^|[/_-])(in|int|internal|lan)(?:[/_-]|$)", low) or low.startswith(
        ("in", "int", "lan")
    ):
        return "internal"
    return None


def _cidr(addr: str, mask: str) -> str:
    addr = (addr or "").strip()
    if not addr:
        return ""
    mask = (mask or "").strip()
    if not mask:
        return addr
    if "/" in mask:
        return f"{addr}{mask}" if not mask.startswith("/") else f"{addr}/{mask.lstrip('/')}"
    parts = mask.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        ones = sum(bin(int(x)).count("1") for x in parts)
        return f"{addr}/{ones}"
    return f"{addr} ({mask})"


def parse_net_self_entries(self_text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    blocks = re.split(r"net\s+self\s+(\S+)\s*\{", self_text, flags=re.I)
    i = 1
    while i + 1 < len(blocks):
        self_name = blocks[i].strip()
        body = blocks[i + 1]
        i += 2
        addr_m = re.search(r"address\s+(\S+)", body, re.I)
        if not addr_m:
            continue
        mask_m = re.search(r"netmask\s+(\S+)", body, re.I)
        vlan_m = re.search(r"vlan\s+(\S+)", body, re.I)
        entries.append(
            {
                "name": self_name,
                "address": addr_m.group(1).strip(),
                "netmask": mask_m.group(1).strip() if mask_m else "",
                "vlan": vlan_m.group(1).strip() if vlan_m else "",
                "floating": _is_floating_self_block(body),
            }
        )
    return entries


def _classify_self_ips_from_entries(entries: list[dict[str, Any]]) -> dict[str, SelfIpPick]:
    picks = {"external": SelfIpPick(), "internal": SelfIpPick()}
    for ent in entries:
        name = ent.get("name", "")
        side = _side_from_name(str(name))
        if side is None:
            side = _side_from_name(str(ent.get("vlan", "")))
        if side is None:
            continue
        cidr = _cidr(str(ent.get("address", "")), str(ent.get("netmask", "")))
        pick = picks[side]
        if ent.get("floating"):
            if not pick.floating_cidr:
                pick.floating_cidr = cidr
        elif not pick.self_cidr:
            pick.self_cidr = cidr
    return picks


def _parse_default_gateways_routes(routes_body: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    items = routes_body.get("items", [])
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        dest = str(item.get("network", item.get("destination", ""))).strip()
        gw = str(item.get("gateway", "")).strip()
        name = str(item.get("name", "")).rstrip("/").split("/")[-1]
        if gw and dest in ("0.0.0.0", "0.0.0.0/0", "default"):
            out.append((name, gw))
    return out


def _assign_gateways(picks: dict[str, SelfIpPick], routes: list[tuple[str, str]]) -> None:
    for side, pick in picks.items():
        if pick.gateway:
            continue
        for name, gw in routes:
            if _side_from_name(name) == side:
                pick.gateway = gw
                break
    for side, pick in picks.items():
        if pick.gateway or not routes:
            continue
        if len(routes) == 1:
            pick.gateway = routes[0][1]
        elif side == "external":
            pick.gateway = routes[0][1]
        elif side == "internal" and len(routes) >= 2:
            pick.gateway = routes[1][1]


def parse_tmos_list_net_route(route_text: str) -> list[RouteRow]:
    """tmsh list net route — routing 이름, gw."""
    rows: list[RouteRow] = []
    blocks = re.split(r"net\s+route\s+(\S+)\s*\{", route_text, flags=re.I)
    i = 1
    while i + 1 < len(blocks):
        name = blocks[i].strip()
        body = blocks[i + 1]
        i += 2
        gw_m = re.search(r"\bgw\s+(\S+)", body, re.I)
        gw = gw_m.group(1).strip() if gw_m else "—"
        rows.append(RouteRow(name=name or "—", gw=gw))
    rows.sort(key=lambda r: r.name.lower())
    return rows


def build_self_ip_rows(self_text: str) -> list[SelfIpRow]:
    """tmsh list net self — 항목 열에 net self 객체 이름."""
    rows: list[SelfIpRow] = []
    for ent in parse_net_self_entries(self_text):
        name = str(ent.get("name", "")).strip()
        if not name:
            continue
        cidr = _cidr(str(ent.get("address", "")), str(ent.get("netmask", "")))
        remark_parts: list[str] = []
        vlan = str(ent.get("vlan", "")).strip()
        if vlan:
            remark_parts.append(f"vlan {vlan}")
        if ent.get("floating"):
            remark_parts.append("floating")
        rows.append(
            SelfIpRow(
                item=name,
                value=cidr or "—",
                remark=", ".join(remark_parts),
            )
        )
    rows.sort(key=lambda r: r.item.lower())
    return rows


def parse_f5os_iface_vlan_mode(running_config: str) -> dict[str, str]:
    """show run interfaces — native-vlan=Untag, trunk-vlans=Tag."""
    modes: dict[str, str] = {}
    current = ""
    for line in running_config.splitlines():
        m = re.match(r"interfaces\s+interface\s+(\S+)", line, re.I)
        if m:
            current = m.group(1).strip()
            continue
        if not current:
            continue
        if re.search(r"trunk-vlans\s+\[", line, re.I):
            modes[current] = "Tag"
        elif re.search(r"native-vlan\s+\d+", line, re.I):
            modes[current] = "Untag"
    return modes


def parse_f5os_iface_speed(summary_text: str) -> dict[str, str]:
    speeds: dict[str, str] = {}
    for line in summary_text.splitlines():
        m = re.match(r"^(\d+\.\d+|mgmt)\s+", line.strip(), re.I)
        if not m:
            continue
        parts = line.split()
        if len(parts) >= 2:
            speeds[m.group(1)] = parts[-1].replace("SPEED_", "")
    return speeds


def parse_f5os_show_vlan(text: str) -> list[tuple[str, str]]:
    """Best-effort vlan id/name -> interface from show vlan output."""
    rows: list[tuple[str, str]] = []
    current_vlan = ""
    for line in text.splitlines():
        if re.search(r"vlan", line, re.I) and re.search(r"\d+", line):
            tokens = line.split()
            for t in tokens:
                if re.match(r"^\d+\.\d+$", t):
                    rows.append((current_vlan or "vlan", t))
        m = re.match(r"^\s*(\d+)\s+(\S+)", line)
        if m:
            current_vlan = m.group(2)
    return rows


def build_f5os_vlan_table(cli: dict[str, str]) -> list[VlanRow]:
    running = cli.get("show run interfaces") or cli.get(
        "show running-config interfaces", ""
    )
    summary = cli.get("show interfaces interface summary", "")
    vlan_text = cli.get("show vlan", "")
    modes = parse_f5os_iface_vlan_mode(running)
    speeds = parse_f5os_iface_speed(summary)
    vlan_if = parse_f5os_show_vlan(vlan_text)
    rows: list[VlanRow] = []
    seen: set[str] = set()
    for vlan_name, iface in vlan_if:
        key = f"{vlan_name}:{iface}"
        if key in seen:
            continue
        seen.add(key)
        tag_disp = modes.get(iface, "—")
        spd = speeds.get(iface, "")
        media = "UTP" if iface == "1.0" else (spd or "—")
        rows.append(
            VlanRow(
                vlan=vlan_name or iface,
                interface=iface,
                tagging=tag_disp,
                media=media,
            )
        )
    if not rows and summary:
        for iface, spd in speeds.items():
            if iface == "mgmt":
                continue
            rows.append(
                VlanRow(
                    vlan="—",
                    interface=iface,
                    tagging=modes.get(iface, "—"),
                    media=spd or "—",
                )
            )
    rows.sort(key=lambda r: (r.vlan.lower(), r.interface))
    return rows


def format_f5os_vlan_rows(cli: dict[str, str]) -> list[str]:
    return [
        f"{r.vlan} | {r.interface} | {r.tagging} | {r.media}"
        for r in build_f5os_vlan_table(cli)
    ]
