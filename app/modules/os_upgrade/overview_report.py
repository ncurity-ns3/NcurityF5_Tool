from __future__ import annotations

import html
from pathlib import Path

from app.modules.os_upgrade.device_overview import DeviceOverviewReport
from app.modules.os_upgrade.overview_parsers import RouteRow, SelfIpRow, VlanRow
from app.modules.os_upgrade.report_table_styles import MAIN_TABLE_CSS, TABLE_COLGROUP

_EXTRA_STYLES = """
body{font-family:'Malgun Gothic',Segoe UI,sans-serif;margin:24px;font-size:14px;}
h1{margin-bottom:8px;}
h2{margin-top:32px;margin-bottom:12px;border-bottom:1px solid #ccc;padding-bottom:6px;}
.cmd{color:#666;font-size:0.88em;}
.err{color:#b42318;}
.empty{color:#999;}
"""


def _render_vlan_grid(rows: list[VlanRow]) -> str:
    if not rows:
        return "<span class='empty'>—</span>"
    parts = [
        '<div class="scroll"><table class="grid grid-mac"><thead><tr>',
        "<th>VLAN</th><th>IF</th><th>Tag</th><th>회선</th>",
        "</tr></thead><tbody>",
    ]
    for row in rows:
        parts.append(
            "<tr>"
            f"<td>{html.escape(row.vlan)}</td>"
            f"<td>{html.escape(row.interface)}</td>"
            f"<td>{html.escape(row.tagging)}</td>"
            f"<td>{html.escape(row.media)}</td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_self_grid(rows: list[SelfIpRow]) -> str:
    if not rows:
        return "<span class='empty'>—</span>"
    parts = [
        '<div class="scroll"><table class="grid grid-mac"><thead><tr>',
        "<th>이름</th><th>Address</th><th>비고</th>",
        "</tr></thead><tbody>",
    ]
    for row in rows:
        cls = "empty" if not row.value or row.value == "—" else ""
        parts.append(
            "<tr>"
            f"<td>{html.escape(row.item)}</td>"
            f'<td class="{cls}">{html.escape(row.value)}</td>'
            f"<td>{html.escape(row.remark)}</td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_route_grid(rows: list[RouteRow]) -> str:
    if not rows:
        return "<span class='empty'>—</span>"
    parts = [
        '<div class="scroll"><table class="grid grid-ping"><thead><tr>',
        "<th>Route</th><th>GW</th>",
        "</tr></thead><tbody>",
    ]
    for row in rows:
        cls = "empty" if not row.gw or row.gw == "—" else ""
        parts.append(
            "<tr>"
            f"<td>{html.escape(row.name)}</td>"
            f'<td class="{cls}">{html.escape(row.gw)}</td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_overview_html(reports: list[DeviceOverviewReport], *, title: str) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title>",
        f"<style>{_EXTRA_STYLES}{MAIN_TABLE_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
    ]
    for report in reports:
        parts.append(
            f"<h2>{html.escape(report.device_label)} "
            f"<small>({html.escape(report.platform_kind)})</small></h2>"
        )
        if report.errors:
            parts.append(
                "<p class='err'>" + html.escape("; ".join(report.errors)) + "</p>"
            )

        parts.append('<table class="main">')
        parts.append(TABLE_COLGROUP)
        parts.append(
            "<thead><tr><th>항목</th><th>결과</th><th>비고</th></tr></thead><tbody>"
        )

        for field in report.fields:
            cls = "result empty" if not field.value or field.value == "—" else "result"
            parts.append(
                "<tr>"
                f"<th>{html.escape(field.item)}</th>"
                f'<td class="{cls}">{html.escape(field.value)}</td>'
                f'<td class="remark">{html.escape(field.remark)}</td>'
                "</tr>"
            )

        parts.append(
            "<tr>"
            "<th>VLAN</th>"
            f'<td class="result nested">{_render_vlan_grid(report.vlan_rows)}</td>'
            '<td class="remark cmd">tmsh list net vlan<br>tmsh show net interface</td>'
            "</tr>"
        )

        parts.append(
            "<tr>"
            "<th>Self IP</th>"
            f'<td class="result nested">{_render_self_grid(report.self_ip_rows)}</td>'
            '<td class="remark cmd">tmsh list net self</td>'
            "</tr>"
        )

        parts.append(
            "<tr>"
            "<th>Route</th>"
            f'<td class="result nested">{_render_route_grid(report.route_rows)}</td>'
            '<td class="remark cmd">tmsh list net route</td>'
            "</tr>"
        )

        parts.append("</tbody></table>")

    parts.append("</body></html>")
    return "".join(parts)


def write_overview_html(path: Path, reports: list[DeviceOverviewReport], *, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_overview_html(reports, title=title), encoding="utf-8")
