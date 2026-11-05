from __future__ import annotations

import html
from pathlib import Path

from app.modules.os_upgrade.pre_work import CONFIG_SYNC_NOTICE, PreWorkReport
from app.modules.os_upgrade.report_table_styles import MAIN_TABLE_CSS, TABLE_COLGROUP

_EXTRA_STYLES = """
body{font-family:'Malgun Gothic',Segoe UI,sans-serif;margin:24px;font-size:14px;}
h1{margin-bottom:8px;}
h2{margin-top:28px;margin-bottom:10px;border-bottom:1px solid #ccc;padding-bottom:6px;}
.notice{margin:16px 0;padding:14px 16px;background:#fff8e6;border:1px solid #e6c200;
  border-radius:6px;font-size:1.05em;font-weight:600;color:#7a5a00;}
.ok{color:#0a6e31;font-weight:600;}
.fail{color:#b42318;font-weight:600;}
.warn{color:#b45309;}
.cmd{color:#666;font-size:0.88em;}
.err{color:#b42318;}
.empty{color:#999;}
ul.files{margin:6px 0 0;padding-left:18px;}
ul.files li{margin:3px 0;word-break:break-all;}
"""


def render_pre_work_html(reports: list[PreWorkReport], *, title: str) -> str:
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

        parts.append(f'<p class="notice">{html.escape(CONFIG_SYNC_NOTICE)}</p>')

        parts.append('<table class="main">')
        parts.append(TABLE_COLGROUP)
        parts.append(
            "<thead><tr><th>항목</th><th>결과</th><th>비고</th></tr></thead><tbody>"
        )

        parts.append(
            "<tr><th>1. Session 수</th>"
            f"<td class='result'><b>{html.escape(report.session_total)}</b></td>"
            '<td class="remark cmd">tmsh show apm access-info | grep Total</td></tr>'
        )

        linux_lines = [
            f"<li><span class='ok'>{html.escape(b.filename)}</span> "
            f"({html.escape(b.label)})</li>"
            for b in report.linux_backups
            if b.ok
        ]
        linux_body = (
            f"<ul class='files'>{''.join(linux_lines)}</ul>"
            if linux_lines
            else "<span class='empty'>백업 대상 없음 (icall script·/var/tmp .sh)</span>"
        )
        parts.append(
            "<tr><th>2. Linux 백업</th>"
            f"<td class='result nested'>{linux_body}</td>"
            '<td class="remark cmd">icall script: tmsh list (handler 제외)<br>'
            "/var/tmp/*.sh: cat · crontab.txt</td></tr>"
        )

        f5_cls = "ok" if report.f5mku_ok else "fail"
        ucs_cls = "ok" if report.ucs_log_rel else "warn"
        if report.ucs_status.startswith("생략"):
            ucs_cls = "warn"
        parts.append(
            "<tr><th>3. TMOS 백업</th>"
            f"<td class='result'>"
            f"<div><b class='{f5_cls}'>f5mku -K</b> → "
            f"{html.escape(report.f5mku_file or '—')}</div>"
            f"<div style='margin-top:8px'>UCS: "
            f"<span class='{ucs_cls}'>{html.escape(report.ucs_status)}</span></div>"
            f"</td>"
            '<td class="remark cmd">f5mku -K (txt)<br>'
            "UCS: 정기점검과 동일 (stagger)</td></tr>"
        )

        parts.append(
            "<tr><th>4. Config Sync</th>"
            f"<td class='result'>{html.escape(CONFIG_SYNC_NOTICE)}</td>"
            '<td class="remark">작업자 안내</td></tr>'
        )

        parts.append("</tbody></table>")
        if report.ucs_log_rel:
            parts.append(
                f"<p class='cmd'>UCS 로그: {html.escape(report.ucs_log_rel)}</p>"
            )

    parts.append("</body></html>")
    return "".join(parts)


def write_pre_work_html(
    path: Path,
    reports: list[PreWorkReport],
    *,
    title: str = "사전 작업",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_pre_work_html(reports, title=title), encoding="utf-8")
