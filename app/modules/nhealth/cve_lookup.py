"""CVE applicability for one BIG-IP version.

해당 여부 comes from the F5 K article for that CVE. The selected version is
compared with the article's BIG-IP and BIG-IP APM rows. An NVD version bound
is never labeled Fixed.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path

import httpx

from app.modules.nhealth.f5_article_search import (
    KDocument,
    advisory_query,
    document_for_cve,
    document_from_item,
    find_f5_articles,
    search_documents,
)
from app.modules.nhealth.k_article import article_judgment, cve_ids, cve_summaries
from app.modules.nhealth.release_catalog import (
    ReleaseItem,
    ReleaseNotes,
    fill_missing_severity,
    severity_rank,
    version_sort_key,
)

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.I)
_K_RE = re.compile(r"\bK\d{5,}\b", re.I)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
_VERSION_TOKEN = re.compile(r"\d+\.\d+\.\d+(?:\.\d+)?")
_BUG_ROOT_RE = re.compile(r"^\s*(\d{4,})")
_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_NVD_GAP_SECONDS = 6.5
_SUMMARY_LIMIT = 110
_PASTE_LIMIT = 100


class CveLookupError(ValueError):
    """The CVE search has no readable CVE id, or too many ids."""


@dataclass(frozen=True)
class CveHit:
    cve: str
    summary: str
    status: str
    nvd_url: str
    f5_label: str
    f5_url: str
    severity: str = ""
    remedy: str = ""


def parse_cve_text(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _CVE_RE.finditer(text or ""):
        cve = match.group(0).upper()
        if cve in seen:
            continue
        seen.add(cve)
        found.append(cve)
    return found


def lookup_k_cves(
    version: str,
    pasted: str = "",
    cache_dir: Path | None = None,
    on_progress=None,
    nvd_cache: Path | None = None,
    on_nvd=None,
) -> list[CveHit]:
    """Judge CVEs from K articles. Severity comes from NVD when a score exists."""
    selected = parse_cve_text(pasted)
    if pasted.strip() and not selected:
        raise CveLookupError("CVE 번호를 확인하세요. 예: CVE-2023-46747")
    if len(selected) > _PASTE_LIMIT:
        raise CveLookupError(f"한 번에 {_PASTE_LIMIT}개까지 확인할 수 있습니다.")
    store = cache_dir or Path()
    if selected:
        documents = _documents_for_cves(selected, store, on_progress)
        hits = [_hit_from_document(version, cve, documents.get(cve)) for cve in selected]
    else:
        documents = _documents_for_version(version, store, on_progress)
        hits = _hits_for_version(version, documents)
    if nvd_cache is None:
        return hits
    return apply_nvd_severity(hits, nvd_cache, on_nvd)


def _documents_for_cves(
    cves: list[str],
    cache_dir: Path,
    on_progress,
) -> dict[str, KDocument]:
    found: dict[str, KDocument] = {}
    pending: list[str] = []
    cache_dir.mkdir(parents=True, exist_ok=True)
    for cve in cves:
        cached = _read_document(cache_dir / f"{cve}.k.json")
        if cached is None:
            pending.append(cve)
        else:
            found[cve] = cached
    if not pending:
        if on_progress is not None:
            on_progress(len(cves), len(cves))
        return found
    try:
        total = len(cves)
        done = total - len(pending)

        def load(cve: str) -> tuple[str, KDocument | None]:
            results = search_documents(f'"{cve}"', limit=8)
            document = document_for_cve(cve, results)
            if document is not None:
                _write_document(cache_dir / f"{cve}.k.json", document)
            return cve, document

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(load, cve) for cve in pending]
            for finished in as_completed(futures):
                cve, document = finished.result()
                if document is not None:
                    found[cve] = document
                done += 1
                if on_progress is not None and (done == total or done % 4 == 0):
                    on_progress(done, total)
    except Exception as exc:
        raise CveLookupError("K 문서를 확인하지 못했습니다.") from exc
    return found


def _documents_for_version(version: str, cache_dir: Path, on_progress) -> list[KDocument]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _read_document_list(cache_dir / f"version-{version}.json")
    if cached is not None:
        if on_progress is not None:
            on_progress(1, 1)
        return cached
    try:
        results = search_documents(f'"{version}"', aq=advisory_query(), limit=40)
    except Exception as exc:
        raise CveLookupError("K 문서를 확인하지 못했습니다.") from exc
    documents: list[KDocument] = []
    seen: set[str] = set()
    for item in results:
        document = document_from_item(item)
        if document is None or document.label in seen or not document.details:
            continue
        seen.add(document.label)
        documents.append(document)
    if documents:
        _write_document_list(cache_dir / f"version-{version}.json", documents)
    if on_progress is not None:
        on_progress(1, 1)
    return documents


def _hits_for_version(version: str, documents: list[KDocument]) -> list[CveHit]:
    chosen: dict[str, CveHit] = {}
    for document in documents:
        for cve in cve_ids(document.details):
            hit = _hit_from_document(version, cve, document)
            current = chosen.get(cve)
            chosen[cve] = hit if current is None else _prefer_hit(current, hit)
    return [hit for hit in chosen.values() if hit.status != "확인 불가"]


def _prefer_hit(current: CveHit, new: CveHit) -> CveHit:
    return new if _status_rank(new.status) < _status_rank(current.status) else current


def _status_rank(status: str) -> int:
    if status == "해당됨":
        return 0
    if status.endswith(" Fixed"):
        return 1
    if status == "해당 없음":
        return 2
    return 3


def _hit_from_document(version: str, cve: str, document: KDocument | None) -> CveHit:
    nvd_url = f"https://nvd.nist.gov/vuln/detail/{cve}"
    if document is None:
        return CveHit(cve, "확인 불가", "확인 불가", nvd_url, "", "")
    status, severity, remedy = article_judgment(document.details, version)
    summary = describe_vulnerability(
        document.title,
        cve_summaries(document.details).get(cve, ""),
    )
    return CveHit(
        cve,
        summary,
        status,
        nvd_url,
        document.label,
        document.url,
        severity,
        remedy,
    )


def _read_document(path: Path) -> KDocument | None:
    loaded = _read_json(path)
    if not isinstance(loaded, dict):
        return None
    if "title" not in loaded:
        return None
    label = str(loaded.get("label") or "")
    url = str(loaded.get("url") or "")
    details = str(loaded.get("details") or "")
    if not label or not url or not details:
        return None
    return KDocument(label, url, details, str(loaded.get("title") or ""))


def _write_document(path: Path, document: KDocument) -> None:
    path.write_text(
        json.dumps(
            {
                "label": document.label,
                "url": document.url,
                "details": document.details,
                "title": document.title,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_document_list(path: Path) -> list[KDocument] | None:
    loaded = _read_json(path)
    if not isinstance(loaded, list) or not loaded:
        return None
    documents: list[KDocument] = []
    for item in loaded:
        if not isinstance(item, dict):
            return None
        if "title" not in item:
            return None
        label = str(item.get("label") or "")
        url = str(item.get("url") or "")
        details = str(item.get("details") or "")
        if not label or not url or not details:
            return None
        documents.append(KDocument(label, url, details, str(item.get("title") or "")))
    return documents


def _write_document_list(path: Path, documents: list[KDocument]) -> None:
    payload = [
        {
            "label": document.label,
            "url": document.url,
            "details": document.details,
            "title": document.title,
        }
        for document in documents
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def evaluate_cves(
    notes: ReleaseNotes,
    pasted: str = "",
    nvd_cache: Path | None = None,
    severity_dir: Path | None = None,
    f5_cache: Path | None = None,
    on_progress=None,
    on_severity=None,
    on_f5=None,
) -> list[CveHit]:
    order, grouped = _index_notes(notes)
    selected = parse_cve_text(pasted)
    if pasted.strip() and not selected:
        raise CveLookupError("CVE 번호를 확인하세요. 예: CVE-2023-46747")
    if len(selected) > _PASTE_LIMIT:
        raise CveLookupError(f"한 번에 {_PASTE_LIMIT}개까지 확인할 수 있습니다.")
    cves = selected or order
    hits: list[CveHit] = []
    total = len(cves)
    last_network = False
    for index, cve in enumerate(cves, start=1):
        if on_progress is not None:
            on_progress(index, total, cve)
        items = grouped.get(cve) or []
        if items:
            hits.append(_hit_from_items(notes.version, cve, items))
            last_network = False
            continue
        if last_network:
            time.sleep(_NVD_GAP_SECONDS)
        hit, fetched = _lookup_nvd(notes.version, cve, nvd_cache or Path())
        hits.append(hit)
        last_network = fetched
    if severity_dir is not None:
        hits = _fill_severity(hits, grouped, severity_dir, on_severity)
    if f5_cache is not None:
        hits = _attach_f5_articles(hits, f5_cache, on_f5)
    return hits


def write_cve_report(path: Path, heading: str, hits: list[CveHit]) -> None:
    rows = []
    for hit in hits:
        kind, _label = _kind_of_status(hit.status)
        severity = hit.severity or "none"
        rows.append(
            f"<tr class='{_status_class(hit.status)}' data-kind='{kind}' "
            f"data-severity='{escape(severity)}'>"
            f"<td>{escape(hit.cve)}</td>"
            f"<td>{escape(hit.summary)}</td>"
            f"<td>{escape(hit.severity or '미확인')}</td>"
            f"<td class='status'>{escape(hit.status)}</td>"
            f"<td>{_remedy_html(hit.remedy)}</td>"
            f"<td><a href='{escape(hit.nvd_url)}'>NVD</a></td>"
            f"<td>{_f5_html(hit.f5_label, hit.f5_url)}</td>"
            "</tr>"
        )
    headers = (
        "CVE 취약점",
        "취약 내용",
        "Severity",
        "해당 여부",
        "해결 버전",
        "NVD Link",
        "F5 Link",
    )
    body = _table(headers, rows)
    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>CVE Vulnerability Checker</title>
<style>
body {{ margin: 0; background: #F7F9FC; color: #1A2332; font: 14px/1.5 "Segoe UI", sans-serif; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 28px 24px 48px; }}
h1 {{ font-size: 22px; margin: 0 0 8px; }}
.meta {{ color: #64748B; margin: 0 0 16px; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch; margin: 0 0 8px; }}
.filter-group {{
    display: flex; flex-direction: column; gap: 6px;
    background: #fff; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px 12px;
}}
.filter-group .cap {{ font-size: 11px; font-weight: 650; color: #64748B; }}
.filters select, .search input {{
    height: 36px; box-sizing: border-box; border: 1px solid #E2E8F0; border-radius: 8px;
    padding: 0 12px; font: 14px "Segoe UI", sans-serif; color: #1A2332; background: #fff;
}}
.filters select {{ min-width: 140px; }}
.search {{ display: flex; align-items: center; gap: 8px; }}
.search input {{ width: 280px; max-width: 100%; }}
.sev {{ display: flex; flex-wrap: wrap; gap: 8px 14px; }}
#kw-count {{ color: #64748B; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; margin-top: 16px; }}
th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #E2E8F0;
         vertical-align: top; }}
th {{ background: #F1F5F9; font-size: 12px; }}
a {{ color: #0260EA; }}
tr.fixed td.status {{ color: #0A6E31; font-weight: 700; }}
tr.open td.status {{ color: #B45309; font-weight: 700; }}
tr.clear td.status, tr.unknown td.status {{ color: #64748B; }}
</style></head>
<body><main>
<h1>CVE Vulnerability Checker</h1>
<p class="meta">{escape(heading)}</p>
<div class="filters">
{_report_filters(hits)}
<div class="filter-group"><span class="cap">키워드</span>
<div class="search">
<input id="kw" type="search" placeholder="CVE, 설명" oninput="applyFilters()">
<span id="kw-count"></span>
</div></div>
</div>
{body or "<p>표시할 CVE가 없습니다.</p>"}
</main>
<script>
function applyFilters() {{
  var kw = document.getElementById('kw');
  var q = kw ? kw.value.trim().toLowerCase() : '';
  var kindEl = document.getElementById('kind');
  var kind = kindEl ? kindEl.value : '';
  var boxes = document.querySelectorAll('#sev-filters input');
  var sevOn = null;
  if (boxes.length) {{
    sevOn = {{}};
    for (var b = 0; b < boxes.length; b++) {{
      if (boxes[b].checked) sevOn[boxes[b].value] = true;
    }}
  }}
  var rows = document.querySelectorAll('table.issues tbody tr');
  var shown = 0;
  for (var i = 0; i < rows.length; i++) {{
    var row = rows[i];
    var rowKind = row.getAttribute('data-kind') || '';
    var rowSev = row.getAttribute('data-severity') || 'none';
    var ok = (!q || row.innerText.toLowerCase().indexOf(q) !== -1)
      && (!kind || rowKind === kind)
      && (!sevOn || sevOn[rowSev]);
    row.style.display = ok ? '' : 'none';
    if (ok) shown++;
  }}
  var count = document.getElementById('kw-count');
  if (count) count.textContent = (q || kind || sevOn) ? (shown + ' / ' + rows.length) : '';
}}
</script>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


_SEVERITY_ORDER = ("Critical", "High", "Medium", "Low")
_KIND_ORDER = (
    ("fixed", "Fixed"),
    ("affected", "해당됨"),
    ("clear", "해당 없음"),
    ("unknown", "확인 불가"),
)


def _report_filters(hits: list[CveHit]) -> str:
    present: list[str] = []
    unknown = False
    for hit in hits:
        if not hit.severity:
            unknown = True
        elif hit.severity not in present:
            present.append(hit.severity)
    present.sort(key=lambda name: _SEVERITY_ORDER.index(name) if name in _SEVERITY_ORDER else 9)
    checks = [
        f"<label><input type='checkbox' value='{escape(name)}' checked "
        f"onchange='applyFilters()'> {escape(name)}</label>"
        for name in present
    ]
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
    seen: set[str] = set()
    kinds: list[tuple[str, str]] = []
    for hit in hits:
        kind, label = _kind_of_status(hit.status)
        if kind in seen:
            continue
        seen.add(kind)
        kinds.append((kind, label))
    kinds.sort(key=lambda item: _kind_index(item[0]))
    options = "".join(f"<option value='{kind}'>{escape(label)}</option>" for kind, label in kinds)
    status = (
        "<div class='filter-group'><span class='cap'>해당 여부</span>"
        "<select id='kind' onchange='applyFilters()'>"
        f"<option value=''>전체</option>{options}</select></div>"
    )
    return severity + status


def _kind_index(kind: str) -> int:
    for index, (value, _label) in enumerate(_KIND_ORDER):
        if value == kind:
            return index
    return 9


def _remedy_html(text: str) -> str:
    lines = [escape(line) for line in (text or "").split("\n") if line.strip()]
    return "<br>".join(lines)


def _kind_of_status(status: str) -> tuple[str, str]:
    if status.endswith(" Fixed"):
        return "fixed", "Fixed"
    for kind, label in _KIND_ORDER:
        if status == label:
            return kind, label
    return "unknown", "확인 불가"


def _index_notes(notes: ReleaseNotes) -> tuple[list[str], dict[str, list[ReleaseItem]]]:
    grouped: dict[str, list[ReleaseItem]] = {}
    order: list[str] = []
    for item in notes.items:
        blob = f"{item.cve} {item.description} {item.links}"
        for cve in parse_cve_text(blob):
            if cve not in grouped:
                grouped[cve] = []
                order.append(cve)
            grouped[cve].append(item)
    return order, grouped


def _hit_from_items(version: str, cve: str, items: list[ReleaseItem]) -> CveHit:
    summary = ""
    for item in items:
        summary = korean_summary(item.description)
        if summary:
            break
    label, url = "", ""
    for item in items:
        label, url = f5_article(item.links)
        if label:
            break
    severity = ""
    for item in items:
        severity = normalize_severity(item.severity)
        if severity:
            break
    return CveHit(
        cve,
        summary,
        _status(version, items),
        nvd_page(cve),
        label,
        url,
        severity,
    )


def _status(version: str, items: list[ReleaseItem]) -> str:
    train = _train(version)
    selected = version_sort_key(version)
    included: list[str] = []
    newer = False
    other = False
    known = False
    for item in items:
        fixes = _VERSION_TOKEN.findall(item.fixed_versions or "")
        if not fixes and item.kind in {"known", "vulnerability"}:
            known = True
        for fix in fixes:
            if _train(fix) == train:
                if version_sort_key(fix) <= selected:
                    included.append(fix)
                else:
                    newer = True
            else:
                other = True
    if included:
        return f"{max(included, key=version_sort_key)} Fixed"
    if newer or known:
        return "해당됨"
    if other:
        return "해당 없음"
    return "확인 불가"


def _train(version: str) -> tuple[int, int]:
    major, minor, *_rest = version.split(".")
    return int(major), int(minor)


def brief_summary(text: str, limit: int = _SUMMARY_LIMIT) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = re.sub(r"^(?:CVE-\d{4}-\d{4,}\s*[:\-]\s*)+", "", cleaned).strip()
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip() + "…"


_KO_PHRASES = (
    ("arbitrary code execution", "임의 코드 실행"),
    ("remote code execution", "원격 코드 실행"),
    ("denial of service", "서비스 거부"),
    ("privilege escalation", "권한 상승"),
    ("information disclosure", "정보 유출"),
    ("sensitive information", "민감 정보"),
    ("out-of-bounds write", "범위를 벗어난 쓰기"),
    ("out-of-bounds read", "범위를 벗어난 읽기"),
    ("out-of-bounds", "범위 밖 메모리 접근"),
    ("use-after-free", "해제 후 재사용"),
    ("use after free", "해제 후 재사용"),
    ("integer overflow", "정수 오버플로"),
    ("buffer overflow", "버퍼 오버플로"),
    ("command injection", "명령 삽입"),
    ("code injection", "코드 삽입"),
    ("sql injection", "SQL 삽입"),
    ("cross-site scripting", "크로스사이트 스크립팅"),
    ("authentication bypass", "인증 우회"),
    ("path traversal", "경로 탐색"),
    ("memory corruption", "메모리 손상"),
    ("uninitialized memory", "초기화되지 않은 메모리"),
    ("race condition", "경쟁 상태"),
    ("side-channel", "부채널"),
    ("resource exhaustion", "자원 고갈"),
    ("null pointer", "널 포인터"),
    ("vulnerabilities", "취약점"),
    ("vulnerability", "취약점"),
    ("conversion", "변환"),
    ("processing", "처리"),
    ("connection", "연결"),
    ("overflow", "오버플로"),
    ("injection", "삽입"),
    ("header", "헤더"),
    ("memory", "메모리"),
    ("server", "서버"),
    ("crash", "중단"),
    ("error", "오류"),
    ("path", "경로"),
)
_GLUE_RE = re.compile(
    r"\b(and|or|the|a|an|of|to|for|with|from|in|on|by|via|that|this|is|are|"
    r"be|when|which|after|before|into|over|under|may|can|could)\b",
    re.I,
)
_PRODUCTS = (
    "Node.js",
    "OpenJDK",
    "jQuery",
    "BIG-IP",
    "OpenSSL",
    "PostgreSQL",
    "Apache",
    "Python",
    "Jetty",
    "kernel",
    "nginx",
    "PHP",
    "Vim",
    "Java",
    "BIND",
)
_IMPACTS = tuple(
    (phrase, label)
    for phrase, label in _KO_PHRASES
    if label
    in {
        "임의 코드 실행",
        "원격 코드 실행",
        "서비스 거부",
        "권한 상승",
        "정보 유출",
        "메모리 손상",
        "경쟁 상태",
        "자원 고갈",
    }
)


_MECHANISMS = (
    ("session serializer mismatch", "세션 직렬화 불일치"),
    ("overwritten session", "세션 파일 덮어쓰기"),
    ("use-after-free", "해제 후 재사용"),
    ("use after free", "해제 후 재사용"),
    ("magic method", "매직 메서드"),
    ("folded http response headers", "접힌 HTTP 응답 헤더"),
    ("http response headers", "HTTP 응답 헤더"),
)


def describe_vulnerability(title: str, detail: str) -> str:
    """Name the product from the F5 title and the effect from the article text."""
    product = _title_product(title) or _named_product(f"{title} {detail}")
    mechanism = _mechanism(detail)
    impacts = _matched_impacts(detail)
    if product and mechanism and impacts:
        return f"{product} {mechanism}{_ro(mechanism)} {', '.join(impacts)} 취약점"
    if product and impacts:
        return f"{product} {', '.join(impacts)} 취약점"
    if product and mechanism:
        return f"{product} {mechanism} 취약점"
    if product:
        return f"{product} 취약점"
    if mechanism and impacts:
        return f"{mechanism}{_ro(mechanism)} {', '.join(impacts)} 취약점"
    if impacts:
        return f"{', '.join(impacts)} 취약점"
    if mechanism:
        return f"{mechanism} 취약점"
    sentence = korean_summary(detail)
    return sentence or "확인 불가"


def _title_product(title: str) -> str:
    cleaned = re.sub(r"^K\d{5,}:\s*", "", title or "", flags=re.I)
    cleaned = _CVE_RE.sub(" ", cleaned)
    match = re.search(
        r"([A-Za-z0-9.+_-][A-Za-z0-9 .+/_-]{0,40}?)\s+vulnerabilit",
        cleaned,
        re.I,
    )
    if match is None:
        return ""
    name = re.sub(r"^(?:multiple|several)\s+", "", match.group(1), flags=re.I).strip()
    return name


def _named_product(text: str) -> str:
    lowered = text.lower()
    for name in _PRODUCTS:
        if name.lower() in lowered:
            return name
    return ""


def _ro(word: str) -> str:
    last = word[-1] if word else ""
    code = ord(last)
    if not 0xAC00 <= code <= 0xD7A3:
        return "로"
    jong = (code - 0xAC00) % 28
    if jong in {0, 8}:
        return "로"
    return "으로"


def _mechanism(text: str) -> str:
    lowered = (text or "").lower()
    for needle, label in _MECHANISMS:
        if needle in lowered:
            return label
    return ""


def _matched_impacts(text: str) -> list[str]:
    lowered = (text or "").lower()
    found: list[str] = []
    for needle, label in _IMPACTS:
        if needle in lowered and label not in found:
            found.append(label)
    return found[:2]


def korean_summary(text: str) -> str:
    sentence = brief_summary(text)
    if not sentence:
        return ""
    if re.search(r"[가-힣]", sentence):
        return sentence
    plain = _CVE_RE.sub(" ", sentence)
    translated = plain
    for english, korean in _KO_PHRASES:
        translated = re.sub(rf"\b{re.escape(english)}\b", korean, translated, flags=re.I)
    translated = _GLUE_RE.sub(" ", translated)
    translated = re.sub(r"\s+", " ", translated).strip(" .,;:-")
    if not translated or _english_words(translated) > 5:
        return _compose_korean(plain)
    if "취약점" not in translated:
        translated = f"{translated} 취약점"
    return translated


def _english_words(text: str) -> int:
    kept = {name.lower() for name in _PRODUCTS}
    return sum(
        1 for word in re.findall(r"[A-Za-z][A-Za-z0-9.+_-]{2,}", text) if word.lower() not in kept
    )


def _compose_korean(plain: str) -> str:
    low = plain.lower()
    product = next((name for name in _PRODUCTS if name.lower() in low), "")
    impact = next((label for needle, label in _IMPACTS if needle in low), "")
    if product and impact:
        return f"{product} {impact} 취약점"
    if product:
        return f"{product} 취약점"
    if impact:
        return f"{impact} 취약점"
    return "공개된 취약점"


_RANK_LABEL = {1: "Critical", 2: "Critical", 3: "High", 4: "Medium", 5: "Low"}
_CVSS_LABEL = {"CRITICAL": "Critical", "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}


def normalize_severity(text: str) -> str:
    rank = severity_rank(text)
    if rank in _RANK_LABEL:
        return _RANK_LABEL[rank]
    return _CVSS_LABEL.get((text or "").strip().upper(), "")


def _fill_severity(hits, grouped, severity_dir: Path, on_severity) -> list[CveHit]:
    root_for: dict[str, str] = {}
    for hit in hits:
        if hit.severity:
            continue
        for item in grouped.get(hit.cve) or []:
            match = _BUG_ROOT_RE.match(item.bug_id or "")
            if match:
                root_for[hit.cve] = match.group(1)
                break
    if not root_for:
        return hits
    placeholders = [
        ReleaseItem(
            bug_id=root,
            links="",
            description="",
            fixed_versions="",
            section="",
            module="",
            kind="fixed",
        )
        for root in dict.fromkeys(root_for.values())
    ]
    filled = fill_missing_severity(placeholders, severity_dir, on_severity)
    by_root: dict[str, str] = {}
    for item in filled:
        label = normalize_severity(item.severity)
        match = _BUG_ROOT_RE.match(item.bug_id or "")
        if match and label:
            by_root[match.group(1)] = label
    updated: list[CveHit] = []
    for hit in hits:
        label = by_root.get(root_for.get(hit.cve, ""), "")
        if label and not hit.severity:
            updated.append(replace(hit, severity=label))
        else:
            updated.append(hit)
    return updated


def _attach_f5_articles(hits: list[CveHit], cache_dir: Path, on_progress) -> list[CveHit]:
    missing = [hit.cve for hit in hits if not hit.f5_url]
    found = find_f5_articles(missing, cache_dir, on_progress)
    updated: list[CveHit] = []
    for hit in hits:
        article = found.get(hit.cve)
        if article and not hit.f5_url:
            updated.append(replace(hit, f5_label=article[0], f5_url=article[1]))
        else:
            updated.append(hit)
    return updated


def apply_nvd_severity(hits: list[CveHit], cache_dir: Path, on_progress=None) -> list[CveHit]:
    """Replace severity with the NVD score. Status stays the K article result."""
    updated: list[CveHit] = []
    last_network = False
    total = len(hits)
    for index, hit in enumerate(hits, start=1):
        if on_progress is not None:
            on_progress(index, total)
        if last_network:
            time.sleep(_NVD_GAP_SECONDS)
        payload, fetched = _nvd_payload(hit.cve, cache_dir)
        last_network = fetched
        entry = _nvd_entry(payload)
        severity = normalize_severity(_nvd_severity(entry)) if entry else ""
        summary = _summary_with_nvd(hit.summary, _nvd_description(entry))
        updated.append(
            replace(
                hit,
                severity=severity or hit.severity,
                summary=summary,
            )
        )
    return updated


def _nvd_entry(payload: dict) -> dict:
    vulns = payload.get("vulnerabilities") if isinstance(payload, dict) else None
    if not vulns:
        return {}
    entry = vulns[0].get("cve", {})
    return entry if isinstance(entry, dict) else {}


def _nvd_description(entry: dict) -> str:
    for item in entry.get("descriptions") or []:
        if item.get("lang") == "en":
            return str(item.get("value") or "")
    return ""


def _summary_with_nvd(current: str, description: str) -> str:
    if not description:
        return current
    refined = describe_vulnerability("", description)
    if current in {"", "확인 불가", "공개된 취약점"}:
        return refined
    if _has_impact(refined) and not _has_impact(current):
        product = _title_product(current) or _named_product(current)
        if product:
            return describe_vulnerability(f"{product} vulnerability", description)
        return refined
    return current


def _has_impact(text: str) -> bool:
    return any(label in (text or "") for _needle, label in _IMPACTS)


def _nvd_severity(entry: dict) -> str:
    metrics = entry.get("metrics") or {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        rows = metrics.get(key) or []
        if not rows:
            continue
        data = rows[0].get("cvssData") or {}
        value = data.get("baseSeverity") or rows[0].get("baseSeverity") or ""
        if value:
            return str(value)
    return ""


def nvd_page(cve: str) -> str:
    return f"https://nvd.nist.gov/vuln/detail/{cve}"


def f5_article(text: str) -> tuple[str, str]:
    for url in _URL_RE.findall(text or ""):
        match = re.search(r"/article/(K\d{5,})", url, re.I)
        if match and "f5.com" in url.lower():
            label = match.group(1).upper()
            return label, url.split("?", 1)[0]
    match = _K_RE.search(text or "")
    if not match:
        return "", ""
    label = match.group(0).upper()
    return label, f"https://my.f5.com/manage/s/article/{label}"


def _lookup_nvd(version: str, cve: str, cache_dir: Path) -> tuple[CveHit, bool]:
    payload, fetched = _nvd_payload(cve, cache_dir)
    vulns = payload.get("vulnerabilities") if isinstance(payload, dict) else None
    if not vulns:
        return CveHit(cve, "", "확인 불가", nvd_page(cve), "", ""), fetched
    entry = vulns[0].get("cve", {})
    summary = ""
    for item in entry.get("descriptions") or []:
        if item.get("lang") == "en":
            summary = korean_summary(str(item.get("value", "")))
            break
    refs = " ".join(
        str(item.get("url", "")).strip()
        for item in entry.get("references") or []
        if str(item.get("url", "")).strip()
    )
    label, url = f5_article(refs)
    return (
        CveHit(
            cve,
            summary,
            _nvd_status(version, entry),
            nvd_page(cve),
            label,
            url,
            normalize_severity(_nvd_severity(entry)),
        ),
        fetched,
    )


def _nvd_status(version: str, entry: dict) -> str:
    matches = [
        match
        for match in _f5_matches(entry)
        if "big-ip" in str(match.get("criteria", "")).lower()
        or "big_ip" in str(match.get("criteria", "")).lower()
    ]
    if not matches:
        return "확인 불가"
    if any(_covers(version, match) for match in matches):
        return "해당됨"
    return "해당 없음"


def _f5_matches(entry: dict) -> list[dict]:
    found: list[dict] = []
    for config in entry.get("configurations") or []:
        _walk_matches(config.get("nodes") or [], found)
    return found


def _walk_matches(nodes: list, found: list[dict]) -> None:
    for node in nodes:
        for match in node.get("cpeMatch") or []:
            if ":f5:" in str(match.get("criteria", "")).lower():
                found.append(match)
        _walk_matches(node.get("children") or [], found)


def _covers(version: str, match: dict) -> bool:
    start_inc = str(match.get("versionStartIncluding") or "").strip()
    start_exc = str(match.get("versionStartExcluding") or "").strip()
    end_inc = str(match.get("versionEndIncluding") or "").strip()
    end_exc = str(match.get("versionEndExcluding") or "").strip()
    current = version_sort_key(version)
    if start_inc and current < version_sort_key(start_inc):
        return False
    if start_exc and current <= version_sort_key(start_exc):
        return False
    if end_inc and current > version_sort_key(end_inc):
        return False
    if end_exc and current >= version_sort_key(end_exc):
        return False
    if any((start_inc, start_exc, end_inc, end_exc)):
        return True
    parts = str(match.get("criteria", "")).split(":")
    pinned = parts[5] if len(parts) > 5 else ""
    return pinned in {"*", "-", ""} or pinned == version


def _nvd_payload(cve: str, cache_dir: Path) -> tuple[dict, bool]:
    cache = cache_dir / f"{cve}.json"
    if cache.is_file():
        try:
            loaded = json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            return loaded, False
    for attempt in range(2):
        try:
            response = httpx.get(
                _NVD_URL,
                params={"cveId": cve},
                timeout=20.0,
                headers={"User-Agent": "NcurityF5Tool"},
            )
        except Exception:
            return {}, True
        if response.status_code == 429 and attempt == 0:
            time.sleep(_NVD_GAP_SECONDS)
            continue
        if response.status_code != 200:
            return {}, True
        try:
            payload = response.json()
        except Exception:
            return {}, True
        if isinstance(payload, dict):
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload), encoding="utf-8")
            return payload, True
        return {}, True
    return {}, True


def _f5_html(label: str, url: str) -> str:
    if not label or not url:
        return "아직 공식문서 없음"
    return f"<a href='{escape(url)}'>{escape(label)}</a>"


def _status_class(status: str) -> str:
    if status.endswith(" Fixed"):
        return "fixed"
    if status == "해당됨":
        return "open"
    if status == "해당 없음":
        return "clear"
    return "unknown"


def _table(headers: tuple[str, ...], rows: list[str]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{escape(name)}</th>" for name in headers)
    return (
        f"<table class='issues'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
