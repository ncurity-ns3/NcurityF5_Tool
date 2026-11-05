from __future__ import annotations

import html
from pathlib import Path

from app.modules.os_upgrade.ucs_config_check import UcsConfigCheckResult


def render_ucs_check_html(units: list[UcsConfigCheckResult], *, title: str) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title>",
        "<style>",
        "body{font-family:'Malgun Gothic',Segoe UI,sans-serif;margin:24px;font-size:14px;color:#1a2332;}",
        "h1{margin-bottom:8px;} h2{margin-top:28px;border-bottom:1px solid #e2e8f0;padding-bottom:6px;}",
        "table{border-collapse:collapse;width:100%;margin:12px 0;}",
        "th,td{border:1px solid #e2e8f0;padding:8px 10px;text-align:left;vertical-align:top;}",
        "th{background:#f1f5f9;width:220px;font-weight:600;}",
        ".sub th{background:#f8fafc;font-size:13px;}",
        ".muted{color:#64748b;font-size:12px;}",
        ".scroll{overflow-x:auto;}",
        "</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
    ]
    for unit in units:
        head = unit.hostname or "—"
        parts.append(f"<h2>{html.escape(head)}</h2>")
        if unit.errors:
            parts.append(
                f"<p class='muted'>{html.escape('; '.join(unit.errors))}</p>"
            )
        parts.append("<table>")
        for row in unit.rows:
            parts.append(
                "<tr>"
                f"<th>{html.escape(row.label)}</th>"
                f"<td>{html.escape(row.value or '—')}</td>"
                f"<td class='muted'>{html.escape(row.remark)}</td>"
                "</tr>"
            )
        parts.append("</table>")

        if unit.vlan_rows:
            parts.append("<h3>VLAN 정보</h3><div class='scroll'><table class='sub'>")
            parts.append(
                "<tr><th>VLAN</th><th>Interface</th><th>Tag/Untag</th><th>Trunk 멤버</th></tr>"
            )
            for v in unit.vlan_rows:
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(v.vlan)}</td>"
                    f"<td>{html.escape(v.interface)}</td>"
                    f"<td>{html.escape(v.tagging)}</td>"
                    f"<td>{html.escape(v.trunk_members or '—')}</td>"
                    "</tr>"
                )
            parts.append("</table></div>")

        if unit.self_ip_rows:
            parts.append("<h3>Self IP / Floating IP</h3><div class='scroll'><table class='sub'>")
            parts.append("<tr><th>이름</th><th>Address</th><th>VLAN</th><th>Floating</th></tr>")
            for s in unit.self_ip_rows:
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(s.name)}</td>"
                    f"<td>{html.escape(s.address)}</td>"
                    f"<td>{html.escape(s.vlan)}</td>"
                    f"<td>{'Y' if s.floating else '—'}</td>"
                    "</tr>"
                )
            parts.append("</table></div>")

        if unit.route_rows:
            parts.append("<h3>Routing Table (Routes)</h3><div class='scroll'><table class='sub'>")
            parts.append("<tr><th>Route</th><th>Gateway</th><th>Network</th></tr>")
            for r in unit.route_rows:
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(r.name)}</td>"
                    f"<td>{html.escape(r.gw)}</td>"
                    f"<td>{html.escape(r.network)}</td>"
                    "</tr>"
                )
            parts.append("</table></div>")

    parts.append("</body></html>")
    return "".join(parts)


def write_ucs_check_html(path: Path, units: list[UcsConfigCheckResult], *, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ucs_check_html(units, title=title), encoding="utf-8")
