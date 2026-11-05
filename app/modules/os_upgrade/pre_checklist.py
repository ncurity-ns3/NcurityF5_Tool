from __future__ import annotations

from collections.abc import Callable

from app.core.bigip_client import BigipClient
from app.core.models import ConnectionProfile
from app.modules.os_upgrade.k7727_versions import BigIpTargetVersion
from app.modules.os_upgrade.pre_checklist_parsers import (
    ArpRow,
    GatewayPingRow,
    HaCheckResult,
    LicenseUpgradeCheck,
    LinuxCheckResult,
    VlanMacRow,
    evaluate_license_upgrade,
    parse_arp_table,
    parse_ha_failover_check,
    parse_linux_checks,
    parse_ping_result,
    parse_vlan_mac_table,
    unique_gateway_ips,
)

# GW ping probe count (tmsh util/bash — not SSH)
PING_PROBE_COUNT = 4

StepCallback = Callable[[str], None]


class PreChecklistReport:
    def __init__(self, device_label: str, target_version: str) -> None:
        self.device_label = device_label
        self.target_version = target_version
        self.license_check: LicenseUpgradeCheck | None = None
        self.vlan_mac_rows: list[VlanMacRow] = []
        self.arp_rows: list[ArpRow] = []
        self.gateway_pings: list[GatewayPingRow] = []
        self.ha_check: HaCheckResult | None = None
        self.linux_check: LinuxCheckResult | None = None
        self.errors: list[str] = []

    def summary_line(self) -> str:
        parts: list[str] = []
        if self.license_check:
            v = self.license_check.verdict
            if v == "OS Upgrade 가능":
                parts.append("License ✓")
            elif v == "인터넷 사용 불가":
                parts.append("License N/A")
            else:
                parts.append("License ✗")
        parts.append(f"MAC {len(self.vlan_mac_rows)}")
        parts.append(f"ARP {len(self.arp_rows)}")
        ok_ping = sum(1 for p in self.gateway_pings if p.result == "OK")
        parts.append(f"GW ping {ok_ping}/{len(self.gateway_pings)}")
        if self.ha_check:
            parts.append(f"HA {self.ha_check.ha_mode}")
        if self.linux_check:
            parts.append("Linux ✓")
        return " | ".join(parts) if parts else "—"


def collect_pre_checklist(
    connection: ConnectionProfile,
    target: BigIpTargetVersion,
    *,
    internet_available: bool = True,
    include_license_check: bool = True,
    on_step: StepCallback | None = None,
) -> PreChecklistReport:
    def step(msg: str) -> None:
        if on_step:
            on_step(msg)

    label = connection.target.label
    report = PreChecklistReport(device_label=label, target_version=target.version)
    client = BigipClient(connection)
    client.authenticate()

    try:
        if include_license_check:
            step("License / Service Check Date")
            lic_text = client.run_util_bash(
                'tmsh show sys license | grep -i "Service Check Date"'
            )
            report.license_check = evaluate_license_upgrade(
                lic_text, target, internet_available=internet_available
            )

        step("MAC Table (show net vlan)")
        vlan_show = client.run_util_bash("tmsh show net vlan")
        report.vlan_mac_rows = parse_vlan_mac_table(vlan_show)

        step("ARP Table")
        arp_text = client.run_util_bash("tmsh show net arp")
        report.arp_rows = parse_arp_table(arp_text)

        step("Gateway ping")
        route_text = client.run_util_bash("tmsh list net route")
        gws = unique_gateway_ips(route_text)
        pings: list[GatewayPingRow] = []
        for gw in gws:
            step(f"ping {gw}")
            try:
                out = client.run_util_bash(
                    f"ping -c {PING_PROBE_COUNT} -W 2 {gw} 2>&1",
                    timeout=30.0,
                )
                pings.append(parse_ping_result(gw, out))
            except Exception as exc:  # noqa: BLE001
                pings.append(
                    GatewayPingRow(gw=gw, result="ERROR", detail=str(exc)[:200])
                )
        report.gateway_pings = pings

        step("HA / Failover")
        fo_show = client.run_util_bash("tmsh show sys failover 2>/dev/null")
        fo_list = client.run_util_bash("tmsh list sys failover 2>/dev/null")
        ha_grp = client.run_util_bash("tmsh list sys ha-group 2>/dev/null")
        cm_fo = client.run_util_bash("tmsh show cm failover-status 2>/dev/null")
        report.ha_check = parse_ha_failover_check(
            fo_list or fo_show,
            ha_grp,
            cm_fo or fo_show,
        )

        step("Linux (icall / crontab / scripts)")
        icall = client.run_util_bash("tmsh list sys icall 2>/dev/null")
        crontab = client.run_util_bash("crontab -l 2>&1")
        scripts = client.run_util_bash(
            "ls /var/tmp 2>/dev/null | grep '\\.sh' || true"
        )
        report.linux_check = parse_linux_checks(icall, crontab, scripts)
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc)[:300])

    return report
