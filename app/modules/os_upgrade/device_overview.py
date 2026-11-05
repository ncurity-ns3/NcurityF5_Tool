from __future__ import annotations

from collections.abc import Callable

from app.core.bigip_client import BigipClient
from app.core.f5os_client import F5osClient
from app.core.models import ConnectionProfile, PlatformKind
from app.modules.health_check.tmos_bash_parse import parse_ha_status
from app.modules.os_upgrade.overview_parsers import (
    RouteRow,
    SelfIpRow,
    VlanRow,
    build_f5os_vlan_table,
    build_self_ip_rows,
    build_tmos_vlan_table,
    parse_tmos_list_net_route,
    parse_f5os_platform_state,
    parse_net_self_entries,
    parse_tmos_platform_hw,
    parse_tmos_show_sys_version,
    resolve_tmos_serial,
)

_BLANK = ""
StepCallback = Callable[[str], None]

SUMMARY_ITEMS = (
    "Platform",
    "Hostname",
    "Serial",
    "현 운영 F5OS Version",
    "현 운영 Tenant Version",
    "이중화 구성 (HA Config)",
    "VLAN 정보 (VLAN Info)",
    "Self IP",
    "Route (GW)",
)


class OverviewField:
    __slots__ = ("item", "value", "remark")

    def __init__(self, item: str, value: str, remark: str = "") -> None:
        self.item = item
        self.value = value or "—"
        self.remark = remark


class DeviceOverviewReport:
    def __init__(self, device_label: str, platform_kind: str) -> None:
        self.device_label = device_label
        self.platform_kind = platform_kind
        self.fields: list[OverviewField] = []
        self.vlan_rows: list[VlanRow] = []
        self.self_ip_rows: list[SelfIpRow] = []
        self.route_rows: list[RouteRow] = []
        self.errors: list[str] = []

    def status_for(self, item: str) -> str:
        if item == "현 운영 F5OS Version" and self.platform_kind == "iSeries/VE":
            return "N/A"
        if item == "F5OS MGMT-IP" and self.platform_kind == "iSeries/VE":
            return "N/A"
        if item == "VLAN 정보 (VLAN Info)":
            return "OK" if self.vlan_rows else "FAIL"
        if item == "Self IP":
            if any(r.value and r.value != "—" for r in self.self_ip_rows):
                return "OK"
            return "FAIL"
        if item == "Route (GW)":
            if any(r.gw and r.gw != "—" for r in self.route_rows):
                return "OK"
            return "FAIL"
        for f in self.fields:
            if f.item == item:
                if not f.value or f.value == "—":
                    return "FAIL"
                return "OK"
        return "FAIL"

    def summary_line(self) -> str:
        parts: list[str] = []
        for key in SUMMARY_ITEMS:
            st = self.status_for(key)
            if st == "N/A":
                parts.append(f"{key} N/A")
            elif st == "OK":
                parts.append(f"{key} ✓")
            else:
                parts.append(f"{key} ✗")
        return " | ".join(parts)


def _field(item: str, value: str, remark: str = "") -> OverviewField:
    return OverviewField(item=item, value=value or _BLANK, remark=remark)


def collect_device_overview(
    connection: ConnectionProfile,
    *,
    on_step: StepCallback | None = None,
) -> DeviceOverviewReport:
    def step(msg: str) -> None:
        if on_step:
            on_step(msg)

    target = connection.target
    is_rseries = target.platform == PlatformKind.rseries
    report = DeviceOverviewReport(
        device_label=target.label,
        platform_kind="rSeries" if is_rseries else "iSeries/VE",
    )

    tmos_host = target.host.strip()
    if not tmos_host:
        report.errors.append("TMOS MGMT IP 없음")
        return report

    client = BigipClient(connection)
    client.authenticate()

    try:
        step("Hardware")
        hw_text = client.run_util_bash("tmsh show sys hardware")
        license_text = client.run_util_bash("tmsh show sys license")

        step("Platform")
        platform = parse_tmos_platform_hw(hw_text)

        step("Hostname")
        gs = client.get_system_info()
        hostname = str(gs.get("hostname", "") or "").strip()

        step("Serial")
        serial = resolve_tmos_serial(hw_text, license_text)

        step("TMOS Version")
        ver_text = client.run_util_bash("tmsh show sys version")
        tenant_ver = parse_tmos_show_sys_version(ver_text)

        step("HA")
        fo_text = client.run_util_bash(
            "tmsh show sys failover 2>/dev/null; "
            "echo '---F5TOOL_HA---'; "
            "tmsh show cm failover-status 2>/dev/null"
        )
        ha_status, _ = parse_ha_status(fo_text)

        step("VLAN")
        vlan_text = client.run_util_bash("tmsh list net vlan")
        if_text = client.run_util_bash("tmsh show net interface")
        report.vlan_rows = build_tmos_vlan_table(vlan_text, if_text)

        step("Self IP")
        self_text = client.run_util_bash("tmsh list net self")
        report.self_ip_rows = build_self_ip_rows(self_text)

        step("Route")
        route_text = client.run_util_bash("tmsh list net route")
        report.route_rows = parse_tmos_list_net_route(route_text)

        f5os_ver = _BLANK
        f5os_mgmt = _BLANK
        f5os_platform = _BLANK
        f5os_remark = "rSeries 전용" if not is_rseries else ""
        if is_rseries and not target.f5os_host.strip():
            report.errors.append("F5OS MGMT IP 미입력 — F5OS Version/플랫폼 미수집")
        elif is_rseries and target.f5os_host.strip():
            f5os_mgmt = target.f5os_host.strip()
            if ":" in f5os_mgmt:
                host_part, _, port_part = f5os_mgmt.rpartition(":")
                if port_part.isdigit():
                    f5os_mgmt = host_part.strip()
            user = connection.f5os_username or connection.username
            pw = connection.f5os_password or connection.password
            pwd = pw.get_secret_value()

            step("F5OS (REST API)")
            try:
                f5_client = F5osClient(
                    f5os_mgmt,
                    target.f5os_port,
                    user,
                    pwd,
                )
                f5os_ver, _ver_src = f5_client.fetch_os_version_rest()
                f5os_platform = f5_client.fetch_platform_description_rest()
                if not f5os_platform:
                    cli = f5_client.fetch_f5os_cli_outputs_rest()
                    f5os_platform = parse_f5os_platform_state(
                        cli.get("show components component platform state", "")
                    )
                    f5_rows = build_f5os_vlan_table(cli)
                    if f5_rows and not report.vlan_rows:
                        report.vlan_rows = f5_rows
                    elif f5_rows and report.vlan_rows:
                        tmos_keys = {r.vlan.lower() for r in report.vlan_rows}
                        for fr in f5_rows:
                            if fr.vlan.lower() not in tmos_keys:
                                report.vlan_rows.append(fr)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"F5OS REST: {exc}"[:160])
            if not f5os_ver:
                report.errors.append(
                    "F5OS Version: REST/API 수집 실패 "
                    "(F5OS MGMT IP·계정·443, image/state 또는 CLI exec 확인)"
                )

        if is_rseries and f5os_platform:
            platform = f5os_platform

        tmos_remark = ""
        for ent in parse_net_self_entries(self_text):
            vlan_ref = str(ent.get("vlan", "")).lower()
            if "mgmt" in vlan_ref or str(ent.get("name", "")).lower().endswith("mgmt"):
                mask = str(ent.get("netmask", "")).strip()
                if mask:
                    tmos_remark = f"서브넷 : {mask}"
                break

        report.fields = [
            _field("Platform", platform),
            _field("Hostname", hostname),
            _field("Serial", serial),
            _field(
                "현 운영 F5OS Version",
                _BLANK if not is_rseries else f5os_ver,
                f5os_remark,
            ),
            _field("현 운영 Tenant Version", tenant_ver),
            _field(
                "F5OS MGMT-IP",
                _BLANK if not is_rseries else f5os_mgmt,
                f5os_remark,
            ),
            _field("TMOS MGMT-IP", tmos_host, tmos_remark),
            _field("이중화 구성 (HA Config)", ha_status),
        ]
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc)[:300])

    return report
