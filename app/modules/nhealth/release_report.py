"""HTML report for a release-note search."""

from __future__ import annotations

from html import escape
from pathlib import Path

from app.modules.nhealth.config_profile import ConfigProfile
from app.modules.nhealth.release_catalog import (
    MODULE_HINTS,
    ReleaseItem,
    ReleaseNotes,
    severity_rank,
)
from app.modules.nhealth.release_notes import MODULES, BugCheck

_CSS = """
body { margin: 0; background: #F7F9FC; color: #1A2332;
       font: 14px/1.5 "Segoe UI", sans-serif; }
main { max-width: 1080px; margin: 0 auto; padding: 28px 24px 48px; }
h1 { font-size: 22px; font-weight: 650; margin: 0 0 6px; }
h2 { font-size: 16px; margin: 28px 0 8px; }
.meta { color: #64748B; margin: 0 0 18px; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch; margin: 0 0 20px; }
.filter-group {
    display: flex; flex-direction: column; gap: 6px;
    background: #fff; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px 12px;
}
.filter-group .cap { font-size: 11px; font-weight: 650; color: #64748B; }
.filters select, .search input {
    height: 36px; box-sizing: border-box;
    border: 1px solid #E2E8F0; border-radius: 8px; padding: 0 12px;
    font: 14px "Segoe UI", sans-serif; color: #1A2332; background: #fff;
}
.filters select { min-width: 140px; }
.search { display: flex; align-items: center; gap: 8px; }
.search input { width: 280px; max-width: 100%; }
.sev { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
#kw-count { color: #64748B; }
.module-block {
    background: #fff; border: 1px solid #E2E8F0; border-radius: 12px;
    margin: 16px 0; overflow: hidden;
}
.module-block > h2 {
    margin: 0; padding: 12px 16px; font-size: 16px;
    border-bottom: 1px solid #E2E8F0; background: #F1F5F9;
}
.module-block > .meta, .module-block > .empty-module { margin: 12px 16px; }
.module-block > table { width: calc(100% - 32px); margin: 12px 16px 16px; }
.module-block[data-module="TMOS"] > h2 { background: #E8F1FF; color: #0260EA; }
.module-block[data-module="LTM"] > h2 { background: #E7F6EE; color: #0A6E31; }
.module-block[data-module="AWAF"] > h2 { background: #FEF3C7; color: #B45309; }
.module-block[data-module="DNS"] > h2 { background: #EDE9FE; color: #6D28D9; }
.module-block[data-module="SSL-O"] > h2 { background: #CFFAFE; color: #0E7490; }
.module-block[data-module="APM"] > h2 { background: #FCE7F3; color: #BE185D; }
.kind-block {
    margin: 12px 16px; padding: 10px 12px 12px;
    background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px;
    border-left-width: 4px;
}
.kind-block[data-kind="fixed"] { border-left-color: #0A6E31; }
.kind-block[data-kind="known"] { border-left-color: #B45309; }
.kind-block[data-kind="vulnerability"] { border-left-color: #B91C1C; }
.kind-block h2 { margin: 0 0 8px; font-size: 14px; }
table { width: 100%; border-collapse: collapse; background: #fff; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #E2E8F0;
         vertical-align: top; }
th { background: #F1F5F9; font-size: 12px; }
.fixed { color: #0A6E31; }
.known { color: #B45309; }
.miss { color: #64748B; }
"""


def write_bug_report(
    path: Path,
    notes: ReleaseNotes,
    checks: list[BugCheck],
    list_name: str,
) -> None:
    rows = []
    for check in checks:
        kind, _label = _verdict_filter(check.verdict)
        module = check.module or "none"
        severity = _severity_token(check.severity) or "none"
        rows.append(
            f"<tr data-module='{escape(module)}' data-kind='{kind}' data-severity='{severity}'>"
            f"<td>{escape(check.bug_id)}</td>"
            f"<td>{escape(check.title)}</td>"
            f"<td class='{_verdict_class(check.verdict)}'>{escape(check.verdict)}</td>"
            f"<td>{escape(check.state)}</td>"
            f"<td>{escape(check.section)}</td>"
            f"<td>{escape(check.fixed_versions)}</td>"
            f"<td>{escape(check.description or check.note)}</td>"
            "</tr>"
        )
    body = _table(
        ("Bug ID", "제목", "판정", "상태", "섹션", "Fixed Versions", "설명"),
        rows,
    )
    _write(
        path,
        notes,
        f"버그 목록 · {escape(list_name)}",
        body or "<p>표시할 버그가 없습니다.</p>",
        _bug_filters(checks),
    )


def write_issue_report(
    path: Path,
    notes: ReleaseNotes,
    modules: list[str],
    items: list[ReleaseItem],
    profile: ConfigProfile | None = None,
) -> None:
    parts: list[str] = []
    if profile is not None:
        parts.append("<section class='module-block config-block'>")
        parts.append("<h2>설정</h2>")
        parts.append(
            "<p class='meta'>"
            f"호스트 {escape(profile.hostname or '—')} · "
            f"장비 버전 {escape(profile.version or '확인 불가')}"
            + (f" (Build {escape(profile.build)})" if profile.build else "")
            + "</p>"
        )
        remark_rows = [
            f"<tr><td>{escape(name)}</td><td>{escape(text)}</td></tr>"
            for name, text in profile.remarks
        ]
        parts.append(
            _table(("모듈", "설정"), remark_rows, css_class="config")
            or "<p>읽은 모듈이 없습니다.</p>"
        )
        parts.append("</section>")
    chosen = [name for name in MODULES if name in modules]
    for module in chosen:
        matched = [
            item
            for item in items
            if item.module == module or module in _text_modules(item)
        ]
        parts.append(f"<section class='module-block' data-module='{escape(module)}'>")
        parts.append(f"<h2>{escape(module)}</h2>")
        if not matched:
            parts.append("<p class='meta empty-module'>이 모듈로 표시된 항목이 없습니다.</p>")
            parts.append("</section>")
            continue
        for kind, title in (
            ("fixed", "Fixed"),
            ("known", "Known"),
            ("vulnerability", "취약점"),
        ):
            group = [item for item in matched if _in_group(item, kind)]
            if not group:
                continue
            rows = [_item_row(item, module, kind) for item in group]
            parts.append(f"<section class='kind-block' data-kind='{kind}'>")
            parts.append(f"<h2>{escape(title)} · <span class='shown'>{len(group)}</span></h2>")
            parts.append(_table(("ID", "Severity", "설명", "CVE", "Fixed Versions", "섹션"), rows))
            parts.append("</section>")
        parts.append("</section>")
    _write(path, notes, "이슈 정리", "".join(parts), _issue_filters(chosen, items))


def _text_modules(item: ReleaseItem) -> set[str]:
    blob = f"{item.section} {item.description} {item.links} {item.cve}".lower()
    return {name for name, hints in MODULE_HINTS.items() if any(hint in blob for hint in hints)}


def _in_group(item: ReleaseItem, kind: str) -> bool:
    if kind == "vulnerability":
        return item.kind == "vulnerability" or bool(item.cve)
    return item.kind == kind


_SEVERITY_LABELS = {
    1: "1-Blocking",
    2: "2-Critical",
    3: "3-Major",
    4: "4-Minor",
    5: "5-Cosmetic",
}
_KIND_LABELS = (("fixed", "Fixed"), ("known", "Known"), ("vulnerability", "취약점"))
_BUG_VERDICTS = (
    ("Fixed", "fixed", "Fixed"),
    ("유효", "known", "Known"),
    ("미포함", "missing", "미포함"),
    ("확인 불가", "unknown", "확인 불가"),
)


def _severity_token(text: str) -> str:
    return _SEVERITY_LABELS.get(severity_rank(text) or 0, "")


def _verdict_filter(verdict: str) -> tuple[str, str]:
    for source, kind, label in _BUG_VERDICTS:
        if verdict == source:
            return kind, label
    return "unknown", "확인 불가"


def _filter_controls(
    modules: list[str],
    kinds: list[tuple[str, str]],
    severities: list[str],
    unknown: bool,
) -> str:
    module_options = "".join(
        f"<option value='{escape(name)}'>{escape(name)}</option>" for name in modules
    )
    kind_options = "".join(
        f"<option value='{kind}'>{escape(label)}</option>" for kind, label in kinds
    )
    checks = []
    for token in severities:
        value = escape(token)
        checks.append(
            f"<label><input type='checkbox' value='{value}' checked "
            f"onchange='applyFilters()'> {value}</label>"
        )
    if unknown:
        checks.append(
            "<label><input type='checkbox' value='none' checked "
            "onchange='applyFilters()'> 미확인</label>"
        )
    severity = ""
    if checks:
        severity = (
            "<div class='filter-group'><span class='cap'>Severity</span>"
            f"<span class='sev' id='sev-filters'>{''.join(checks)}</span></div>"
        )
    return (
        "<div class='filter-group'><span class='cap'>모듈</span>"
        "<select id='mod' onchange='applyFilters()'>"
        f"<option value=''>전체</option>{module_options}</select></div>"
        f"{severity}"
        "<div class='filter-group'><span class='cap'>구분</span>"
        "<select id='kind' onchange='applyFilters()'>"
        f"<option value=''>전체</option>{kind_options}</select></div>"
    )


def _issue_filters(modules: list[str], items: list[ReleaseItem]) -> str:
    present = {
        kind
        for kind, _title in _KIND_LABELS
        if any(_in_group(item, kind) for item in items)
    }
    kinds = [(kind, title) for kind, title in _KIND_LABELS if kind in present]
    tokens: list[str] = []
    unknown = False
    for item in items:
        token = _severity_token(item.severity)
        if not token:
            unknown = True
        elif token not in tokens:
            tokens.append(token)
    tokens.sort(key=lambda text: severity_rank(text) or 9)
    return _filter_controls(modules, kinds, tokens, unknown)


def _bug_filters(checks: list[BugCheck]) -> str:
    modules = [name for name in MODULES if any(check.module == name for check in checks)]
    present = {check.verdict for check in checks}
    kinds = [
        (kind, label)
        for verdict, kind, label in _BUG_VERDICTS
        if verdict in present
    ]
    tokens: list[str] = []
    unknown = False
    for check in checks:
        token = _severity_token(check.severity)
        if not token:
            unknown = True
        elif token not in tokens:
            tokens.append(token)
    tokens.sort(key=lambda text: severity_rank(text) or 9)
    return _filter_controls(modules, kinds, tokens, unknown)


def _item_row(item: ReleaseItem, module: str, kind: str) -> str:
    severity = _severity_token(item.severity) or "none"
    return (
        f"<tr data-module='{escape(module)}' data-kind='{kind}' data-severity='{severity}'>"
        f"<td>{escape(item.bug_id)}</td>"
        f"<td>{escape(item.severity)}</td>"
        f"<td>{escape(item.description)}</td>"
        f"<td>{escape(item.cve)}</td>"
        f"<td>{escape(item.fixed_versions)}</td>"
        f"<td>{escape(item.section)}</td>"
        "</tr>"
    )


def _table(headers: tuple[str, ...], rows: list[str], css_class: str = "issues") -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{escape(name)}</th>" for name in headers)
    return (
        f"<table class='{css_class}'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _verdict_class(verdict: str) -> str:
    if verdict == "Fixed":
        return "fixed"
    if verdict == "유효":
        return "known"
    return "miss"


def _write(path: Path, notes: ReleaseNotes, heading: str, body: str, filters: str = "") -> None:
    build = f" (Build {escape(notes.build)})" if notes.build else ""
    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>Release Notes · {escape(notes.version)}</title>
<style>{_CSS}</style></head>
<body><main>
<h1>Release Notes Checker</h1>
<p class="meta">{heading}<br>
{escape(notes.version)}{build} · {escape(notes.source)}<br>
<a href="{escape(notes.url)}">{escape(notes.url)}</a></p>
<div class="filters">
{filters}
<div class="filter-group">
<span class="cap">키워드</span>
<div class="search">
<input id="kw" type="search" placeholder="ID, 설명, CVE" oninput="applyFilters()">
<span id="kw-count"></span>
</div>
</div>
</div>
{body}
</main>
<script>
function applyFilters() {{
  var kw = document.getElementById('kw');
  var q = kw ? kw.value.trim().toLowerCase() : '';
  var modEl = document.getElementById('mod');
  var kindEl = document.getElementById('kind');
  var module = modEl ? modEl.value : '';
  var kind = kindEl ? kindEl.value : '';
  var boxes = document.querySelectorAll('#sev-filters input');
  var sevOn = null;
  if (boxes.length) {{
    sevOn = {{}};
    for (var b = 0; b < boxes.length; b++) {{
      if (boxes[b].checked) sevOn[boxes[b].value] = true;
    }}
  }}
  var shown = 0;
  var total = 0;
  var rows = document.querySelectorAll('table.issues tbody tr');
  for (var i = 0; i < rows.length; i++) {{
    total++;
    var row = rows[i];
    var text = row.innerText.toLowerCase();
    var rowKind = row.getAttribute('data-kind') || '';
    var rowMod = row.getAttribute('data-module') || '';
    var rowSev = row.getAttribute('data-severity') || 'none';
    var ok = (!q || text.indexOf(q) !== -1)
      && (!module || rowMod === module)
      && (!kind || rowKind === kind)
      && (!sevOn || sevOn[rowSev]);
    row.style.display = ok ? '' : 'none';
    if (ok) shown++;
  }}
  var kinds = document.querySelectorAll('section.kind-block');
  for (var k = 0; k < kinds.length; k++) {{
    var block = kinds[k];
    var bodyRows = block.querySelectorAll('tbody tr');
    var visible = 0;
    for (var r = 0; r < bodyRows.length; r++) {{
      if (bodyRows[r].style.display !== 'none') visible++;
    }}
    var kindMatch = !kind || block.getAttribute('data-kind') === kind;
    block.style.display = kindMatch && visible ? '' : 'none';
    var count = block.querySelector('.shown');
    if (count) count.textContent = String(visible);
  }}
  var mods = document.querySelectorAll('section.module-block');
  for (var m = 0; m < mods.length; m++) {{
    var section = mods[m];
    var modMatch = !module || section.getAttribute('data-module') === module;
    var kids = section.querySelectorAll('section.kind-block');
    var live = false;
    for (var j = 0; j < kids.length; j++) {{
      if (kids[j].style.display !== 'none') live = true;
    }}
    section.style.display = modMatch && (live || !kids.length) ? '' : 'none';
  }}
  var countEl = document.getElementById('kw-count');
  var narrowed = q || module || kind;
  if (!narrowed && boxes.length) {{
    var checked = 0;
    for (var c = 0; c < boxes.length; c++) if (boxes[c].checked) checked++;
    narrowed = checked !== boxes.length;
  }}
  countEl.textContent = narrowed ? (shown + ' / ' + total) : '';
}}
</script>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
