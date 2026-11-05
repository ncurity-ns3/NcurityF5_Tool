from __future__ import annotations

import html
from pathlib import Path

from app.modules.os_upgrade.pre_checklist import PreChecklistReport
from app.modules.os_upgrade.report_table_styles import MAIN_TABLE_CSS, TABLE_COLGROUP
from app.modules.os_upgrade.pre_checklist_parsers import (
    ArpRow,
    GatewayPingRow,
    LicenseUpgradeCheck,
    VlanMacRow,
)

_EXTRA_STYLES = """
body{font-family:'Malgun Gothic',Segoe UI,sans-serif;margin:24px;font-size:14px;}
h1{margin-bottom:8px;}
h2{margin-top:28px;margin-bottom:10px;border-bottom:1px solid #ccc;padding-bottom:6px;}
.ok{color:#0a6e31;font-weight:600;}
.warn{color:#b45309;font-weight:600;}
.fail{color:#b42318;font-weight:600;}
.cmd{color:#666;font-size:0.88em;}
.err{color:#b42318;}
.empty{color:#999;}
.linux-block{margin:10px 0;padding:8px 10px;border:1px solid #dde3ea;border-radius:6px;background:#fafbfc;}
.linux-head{margin-bottom:4px;}
.linux-head b{color:#1a3a52;}
details.linux-detail{margin:6px 0 0 16px;font-size:0.92em;}
details.linux-detail summary{cursor:pointer;color:#2a5a8a;font-weight:600;list-style:none;}
details.linux-detail summary::-webkit-details-marker{display:none;}
details.linux-detail summary::marker{content:'';}
details.linux-detail ul{margin:6px 0 0;padding-left:18px;}
details.linux-detail li{margin:2px 0;word-break:break-all;}
"""


def _verdict_class(verdict: str) -> str:
    if verdict == "OS Upgrade 가능":
        return "ok"
    if verdict == "License Active 필요":
        return "fail"
    if verdict == "인터넷 사용 불가":
        return "warn"
    return "warn"


def _render_license_cell(lic: LicenseUpgradeCheck | None) -> str:
    if not lic:
        return "<span class='empty'>—</span>"
    cls = _verdict_class(lic.verdict)
    parts = [
        f"<div><b class='{cls}'>{html.escape(lic.verdict)}</b></div>",
        f"<div>목표: {html.escape(lic.target_version)}</div>",
        f"<div>License Check Date: {html.escape(lic.license_check_date)}</div>",
        f"<div>Service Check Date: {html.escape(lic.service_check_date)}</div>",
    ]
    if lic.detail.strip():
        parts.append(
            f"<div style='margin-top:6px;font-size:0.92em'>{html.escape(lic.detail)}</div>"
        )
    return "".join(parts)


def _render_vlan_mac(rows: list[VlanMacRow]) -> str:
    if not rows:
        return "<span class='empty'>—</span>"
    parts = [
        '<div class="scroll"><table class="grid grid-mac"><thead><tr>',
        "<th>VLAN</th><th>Mac Address</th></tr></thead><tbody>",
    ]
    for r in rows:
        parts.append(
            f"<tr><td>{html.escape(r.vlan)}</td><td>{html.escape(r.mac)}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_arp(rows: list[ArpRow]) -> str:
    if not rows:
        return "<span class='empty'>—</span>"
    parts = [
        '<div class="scroll"><table class="grid grid-arp"><thead><tr>',
        "<th>Name</th><th>Address</th><th>HWaddress</th><th>Vlan</th>"
        "<th>Expire</th><th>Status</th></tr></thead><tbody>",
    ]
    for r in rows:
        parts.append(
            "<tr>"
            f"<td>{html.escape(r.name)}</td>"
            f"<td>{html.escape(r.address)}</td>"
            f"<td>{html.escape(r.hwaddress)}</td>"
            f"<td>{html.escape(r.vlan)}</td>"
            f"<td>{html.escape(r.expire_in_sec)}</td>"
            f"<td>{html.escape(r.status)}</td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_ping(rows: list[GatewayPingRow]) -> str:
    if not rows:
        return "<span class='empty'>GW 없음</span>"
    parts = [
        '<div class="scroll"><table class="grid grid-ping"><thead><tr>',
        "<th>GW</th><th>결과</th><th>상세</th></tr></thead><tbody>",
    ]
    for r in rows:
        cls = "ok" if r.result == "OK" else ("fail" if r.result == "FAIL" else "warn")
        parts.append(
            "<tr>"
            f"<td>{html.escape(r.gw)}</td>"
            f"<td class='{cls}'>{html.escape(r.result)}</td>"
            f"<td>{html.escape(r.detail)}</td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_ha(report: PreChecklistReport) -> tuple[str, str]:
    ha = report.ha_check
    if not ha:
        return "<span class='empty'>—</span>", ""
    body = (
        f"<div><b>{html.escape(ha.ha_mode)}</b></div>"
        f"<div>{html.escape(ha.failover_summary)}</div>"
    )
    return body, ha.detail


def _linux_section(
    label: str,
    summary: str,
    detail_items: list[str],
) -> str:
    head = (
        f'<div class="linux-block">'
        f'<div class="linux-head"><b>{html.escape(label)}</b>: '
        f"{html.escape(summary)}</div>"
    )
    if not detail_items:
        return head + "</div>"
    lis = "".join(f"<li>{html.escape(x)}</li>" for x in detail_items)
    return (
        head
        + f'<details class="linux-detail"><summary>▸ 목록</summary>'
        + f"<ul>{lis}</ul></details></div>"
    )


def _render_linux(report: PreChecklistReport) -> str:
    ln = report.linux_check
    if not ln:
        return "<span class='empty'>—</span>"

    icall_details = [
        f"{e.kind}: {e.name}" for e in ln.icall_entries
    ]
    cron_details = list(ln.crontab_custom_lines)
    script_details = list(ln.script_names)

    return (
        _linux_section("icall (handler/script)", ln.icall_summary, icall_details)
        + _linux_section("crontab (사용자 정의)", ln.crontab_summary, cron_details)
        + _linux_section(
            "script 존재 여부 (/var/tmp)",
            ln.scripts_summary,
            script_details,
        )
    )


def render_pre_checklist_html(
    reports: list[PreChecklistReport],
    *,
    title: str,
    include_license_check: bool = True,
) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title>",
        f"<style>{_EXTRA_STYLES}{MAIN_TABLE_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
    ]
    for report in reports:
        parts.append(f"<h2>{html.escape(report.device_label)}</h2>")
        if report.errors:
            parts.append(
                "<p class='err'>" + html.escape("; ".join(report.errors)) + "</p>"
            )
        ver_note = (
            f"(K7727 License Check Date)"
            if include_license_check
            else "(작업 후 — License/Service Check Date 생략)"
        )
        parts.append(
            f"<p>목표 버전: <b>{html.escape(report.target_version)}</b> "
            f"{html.escape(ver_note)}</p>"
        )
        parts.append('<table class="main">')
        parts.append(TABLE_COLGROUP)
        parts.append("<thead><tr>")
        parts.append("<th>항목</th><th>결과</th><th>비고</th></tr></thead><tbody>")

        n = 1
        if include_license_check:
            parts.append(
                f"<tr><th>{n}. OS upgrade 가능 여부</th>"
                f'<td class="result">{_render_license_cell(report.license_check)}</td>'
                '<td class="remark cmd">tmsh show sys license | grep Service Check Date<br>'
                "비교: K7727 License Check Date</td></tr>"
            )
            n += 1

        parts.append(
            f"<tr><th>{n}. MAC Table</th>"
            f'<td class="result nested">{_render_vlan_mac(report.vlan_mac_rows)}</td>'
            '<td class="remark cmd">tmsh show net vlan</td></tr>'
        )
        n += 1

        parts.append(
            f"<tr><th>{n}. ARP Table</th>"
            f'<td class="result nested">{_render_arp(report.arp_rows)}</td>'
            '<td class="remark cmd">tmsh show net arp</td></tr>'
        )
        n += 1

        parts.append(
            f"<tr><th>{n}. Gateway 통신</th>"
            f'<td class="result nested">{_render_ping(report.gateway_pings)}</td>'
            '<td class="remark cmd">list net route → ping GW (중복 제외)</td></tr>'
        )
        n += 1

        ha_cell, ha_remark = _render_ha(report)
        parts.append(
            f"<tr><th>{n}. 이중화 / Failover</th>"
            f'<td class="result">{ha_cell}</td>'
            f'<td class="remark">{html.escape(ha_remark)}<br>'
            '<span class="cmd">show/list sys failover, list sys ha-group</span></td></tr>'
        )
        n += 1

        parts.append(
            f"<tr><th>{n}. Linux 체크</th>"
            f'<td class="result">{_render_linux(report)}</td>'
            '<td class="remark cmd">list sys icall, crontab -l,<br>'
            "ls /var/tmp | grep .sh</td></tr>"
        )

        parts.append("</tbody></table>")

    parts.append("</body></html>")
    return "".join(parts)


def write_pre_checklist_html(
    path: Path,
    reports: list[PreChecklistReport],
    *,
    title: str = "작업 전 Check List",
    include_license_check: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_pre_checklist_html(
            reports,
            title=title,
            include_license_check=include_license_check,
        ),
        encoding="utf-8",
    )
