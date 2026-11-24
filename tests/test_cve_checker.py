"""CVE checker reads a version's release note and an optional pasted list."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QTabWidget

from app.gui.views.cve_checker_view import CveCheckerView
from app.modules.nhealth.cve_lookup import (
    CveHit,
    CveLookupError,
    apply_nvd_severity,
    describe_vulnerability,
    evaluate_cves,
    lookup_k_cves,
    parse_cve_text,
    write_cve_report,
)
from app.modules.nhealth.f5_article_search import article_from_results
from app.modules.nhealth.k_article import article_judgment
from app.modules.nhealth.release_catalog import load_release_notes, parse_release_html

_app = QApplication.instance() or QApplication([])

_HTML = """
<html><body>
<b>Fixed in this Release</b>
<table>
<tr><td>ID Number</td><td>Links to More Info</td><td>Description</td><td>Fixed Versions</td></tr>
<tr><td>2693429-3</td><td>K000163821</td>
<td>PHP vulnerabilities CVE-2026-109618 and CVE-2026-109619</td><td>17.5.1.11</td></tr>
<tr><td>2524777-2</td><td>K000162605</td>
<td>BIG-IP APM vulnerability CVE-2026-94127</td><td>21.1.0.3, 17.5.1.10, 17.1.3.6</td></tr>
<tr><td>1006449-5</td><td>BT1006449</td>
<td>Other branch CVE-2024-27983</td><td>21.1.0.3</td></tr>
</table>
<b>Known Issues in BIG-IP v17.5.x</b>
<table>
<tr><td>ID Number</td><td>Links to More Info</td><td>Description</td></tr>
<tr><td>1991485</td><td>K000161170</td><td>Open issue CVE-2024-0001 remains</td></tr>
</table>
</body></html>
"""


def _notes(version: str = "17.5.1.11"):
    return parse_release_html(
        _HTML,
        version=version,
        url="https://techdocs.example/rel",
        source="fixture",
    )


def test_pasted_text_keeps_unique_cves_in_order() -> None:
    found = parse_cve_text("see cve-2023-46747, CVE-2023-46747\nCVE-2024-1234 and words")
    assert found == ["CVE-2023-46747", "CVE-2024-1234"]
    dozens = "\n".join(f"CVE-2020-{index:04d}" for index in range(40))
    assert len(parse_cve_text(dozens)) == 40


def test_version_search_lists_fixes_and_open_issues_for_that_train() -> None:
    hits = evaluate_cves(_notes(), "")
    by_cve = {hit.cve: hit for hit in hits}
    assert set(by_cve) == {
        "CVE-2026-109618",
        "CVE-2026-109619",
        "CVE-2026-94127",
        "CVE-2024-27983",
        "CVE-2024-0001",
    }
    assert by_cve["CVE-2026-109618"].status == "17.5.1.11 Fixed"
    assert by_cve["CVE-2026-109618"].summary == "PHP 취약점"
    assert by_cve["CVE-2026-109618"].f5_label == "K000163821"
    assert by_cve["CVE-2026-109618"].f5_url.endswith("/K000163821")
    assert by_cve["CVE-2026-109618"].nvd_url.endswith("CVE-2026-109618")
    assert by_cve["CVE-2026-94127"].status == "17.5.1.10 Fixed"
    assert by_cve["CVE-2024-0001"].status == "해당됨"
    assert by_cve["CVE-2024-27983"].status == "해당 없음"


def test_pasted_cves_are_the_only_rows(monkeypatch, tmp_path: Path) -> None:
    def _blocked(*_args, **_kwargs):
        raise AssertionError("NVD should stay unused when the release note has the CVE")

    monkeypatch.setattr("app.modules.nhealth.cve_lookup.httpx.get", _blocked)
    hits = evaluate_cves(
        _notes(),
        "CVE-2026-109619, CVE-2024-27983",
        tmp_path,
    )
    assert [hit.cve for hit in hits] == ["CVE-2026-109619", "CVE-2024-27983"]
    assert hits[0].status == "17.5.1.11 Fixed"
    assert hits[0].f5_label == "K000163821"
    assert hits[1].status == "해당 없음"


def test_nvd_range_is_not_labeled_fixed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.modules.nhealth.cve_lookup._NVD_GAP_SECONDS", 0)
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "descriptions": [
                        {
                            "lang": "en",
                            "value": (
                                "Node.js HTTP/2 processing can crash the server. Extra detail."
                            ),
                        }
                    ],
                    "references": [
                        {
                            "url": (
                                "https://my.f5.com/manage/s/article/K000139532"
                                "?utm_source=chatgpt.com"
                            )
                        }
                    ],
                    "metrics": {"cvssMetricV31": [{"cvssData": {"baseSeverity": "HIGH"}}]},
                    "configurations": [
                        {
                            "nodes": [
                                {
                                    "cpeMatch": [
                                        {
                                            "criteria": "cpe:2.3:a:f5:big-ip:*:*:*:*:*:*:*:*",
                                            "versionEndExcluding": "17.1.1",
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            }
        ]
    }

    class _Response:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(
        "app.modules.nhealth.cve_lookup.httpx.get",
        lambda *_args, **_kwargs: _Response(),
    )
    empty = parse_release_html("<html></html>", version="17.1.0.8", url="", source="fixture")
    inside = evaluate_cves(empty, "CVE-2024-27983", tmp_path / "cve")
    assert inside[0].status == "해당됨"
    assert "Fixed" not in inside[0].status
    assert "취약점" in inside[0].summary
    assert "crash the server" not in inside[0].summary
    assert inside[0].f5_label == "K000139532"
    assert inside[0].f5_url == "https://my.f5.com/manage/s/article/K000139532"
    assert inside[0].severity == "High"

    later = parse_release_html("<html></html>", version="17.5.1.11", url="", source="fixture")
    outside = evaluate_cves(later, "CVE-2024-27983", tmp_path / "cve")
    assert outside[0].status == "해당 없음"
    assert "Fixed" not in outside[0].status


def test_too_many_or_unreadable_cves_are_rejected(tmp_path: Path) -> None:
    notes = _notes()
    try:
        evaluate_cves(notes, "no identifiers here", tmp_path)
    except CveLookupError as exc:
        assert "CVE" in str(exc)
    else:
        raise AssertionError("paste without a CVE should fail")
    many = " ".join(f"CVE-2020-{index:04d}" for index in range(101))
    try:
        evaluate_cves(notes, many, tmp_path)
    except CveLookupError as exc:
        assert "100" in str(exc)
    else:
        raise AssertionError("more than 100 CVEs should fail")


def test_report_shows_nvd_and_f5_links(tmp_path: Path) -> None:
    hits = evaluate_cves(_notes(), "CVE-2026-109618")
    path = tmp_path / "cve.html"
    write_cve_report(path, "17.5.1.11", hits)
    text = path.read_text(encoding="utf-8")
    assert 'id="kw"' in text
    assert "CVE-2026-109618" in text
    assert "17.5.1.11 Fixed" in text
    assert "https://nvd.nist.gov/vuln/detail/CVE-2026-109618" in text
    assert "K000163821" in text
    assert "id='sev-filters'" in text
    assert "id='kind'" in text
    assert ">Fixed</option>" in text
    assert "미확인" in text
    full = tmp_path / "all.html"
    write_cve_report(full, "17.5.1.11", evaluate_cves(_notes(), ""))
    full_text = full.read_text(encoding="utf-8")
    assert ">해당됨</option>" in full_text
    assert ">해당 없음</option>" in full_text


def test_cve_page_has_version_and_paste_together(tmp_path: Path) -> None:
    catalog = tmp_path / "versions.json"
    catalog.write_text(
        json.dumps({"versions": [{"version": "17.5.1.11", "build": "0.0.8"}]}),
        encoding="utf-8",
    )
    view = CveCheckerView(data_dir=tmp_path, catalog_path=catalog)
    assert view.findChild(QLabel).text() == "CVE Vulnerability Checker"
    assert view.findChild(QTabWidget) is None
    assert view.findChild(QPlainTextEdit) is view.paste
    assert view.version_combo.findText("17.5.1.11 (Build 0.0.8)") >= 0
    assert view.progress.maximum() == 100
    assert view.progress.minimum() == 0
    assert view.table.columnCount() == 6


def test_saved_release_note_is_reused(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "notes"
    cache.mkdir()
    (cache / "17.5.1.11.html").write_text(_HTML, encoding="utf-8")

    def _blocked(*_args, **_kwargs):
        raise AssertionError("cached release note should not be downloaded again")

    monkeypatch.setattr("app.modules.nhealth.release_catalog._download_notes", _blocked)
    notes = load_release_notes("17.5.1.11", cache, prefer_cache=True)
    assert notes.source == "cache"
    hits = evaluate_cves(notes, "")
    assert any(hit.cve == "CVE-2026-109618" for hit in hits)


def test_cached_bug_severity_is_critical(tmp_path: Path) -> None:
    severity = tmp_path / "severity"
    severity.mkdir()
    (severity / "2693429.txt").write_text("2-Critical", encoding="utf-8")
    hits = evaluate_cves(_notes(), "CVE-2026-109618", severity_dir=severity)
    assert hits[0].severity == "Critical"


def test_f5_article_must_mention_the_cve() -> None:
    results = [
        {
            "title": "K000164058: Out-of-band Security Notification",
            "excerpt": "November release notice",
            "clickUri": "https://my.f5.com/manage/s/article/K000164058",
        },
        {
            "title": "K000164314: Multiple PHP vulnerabilities",
            "excerpt": "CVE-2026-129474 Use-after-free in magic method backtraces",
            "clickUri": "https://my.f5.com/manage/s/article/K000164314?utm=1",
        },
    ]
    label, url = article_from_results("CVE-2026-129474", results)
    assert label == "K000164314"
    assert url == "https://my.f5.com/manage/s/article/K000164314"


def test_missing_note_link_is_filled_from_f5_search(tmp_path: Path, monkeypatch) -> None:
    def fake(cves, cache_dir, on_progress=None):
        assert cves == ["CVE-2024-27983"]
        return {
            "CVE-2024-27983": (
                "K000139532",
                "https://my.f5.com/manage/s/article/K000139532",
            )
        }

    monkeypatch.setattr("app.modules.nhealth.cve_lookup.find_f5_articles", fake)
    hits = evaluate_cves(
        _notes(),
        "CVE-2026-109618, CVE-2024-27983",
        f5_cache=tmp_path,
    )
    assert hits[0].f5_label == "K000163821"
    assert hits[1].f5_label == "K000139532"
    assert hits[1].f5_url.endswith("/K000139532")


_CLEAR = """
<h2>Security Advisory Description</h2>
<p>CVE-2026-115560 PHP vulnerability in session handling.</p>
<p>Impact There is no impact; F5 products are not affected by this vulnerability.</p>
"""

_PHP = """
<h2>Security Advisory Description</h2>
<p>CVE-2026-109618 PHP use-after-free can lead to remote code execution.</p>
<p>CVE-2026-109619 PHP denial of service in the same component.</p>
<table>
<tr>
<td>Product</td><td>Branch</td><td>Versions known to be vulnerable</td>
<td>Fixes introduced in</td><td>Severity/CVSS score</td><td>Vulnerable component or feature</td>
</tr>
<tr>
<td rowspan="2">BIG-IP APM</td>
<td>21.x</td><td>21.1.0</td><td>21.1.0.4</td>
<td rowspan="2">High/8.1 (CVSS v3.1)</td>
<td rowspan="2">Data plane: Access profile</td>
</tr>
<tr>
<td>17.x</td>
<td>17.5.0 - 17.5.1<br>17.1.0 - 17.1.3</td>
<td>17.5.1.11<br>17.1.3.7<br>17.5.1.10 + Hotfix-BIGIP-17.5.1.10.0.37.35-ENG</td>
</tr>
<tr>
<td>BIG-IP (all modules)</td><td>17.x</td><td>17.5.0 - 17.5.1</td>
<td>17.5.1.11<br>17.5.1.10 + Hotfix-BIGIP-17.5.1.10.0.37.35-ENG</td>
<td>High/7.5 (CVSS v3.1)</td><td>Control plane</td>
</tr>
</table>
"""

_APM_ONLY = """
<table>
<tr>
<td>Product</td><td>Branch</td><td>Versions known to be vulnerable</td>
<td>Fixes introduced in</td><td>Severity/CVSS score</td><td>Vulnerable component or feature</td>
</tr>
<tr>
<td>BIG-IP APM</td><td>17.x</td><td>17.5.0 - 17.5.1</td><td>17.5.1.11</td>
<td>High/8.1</td><td>Access profile</td>
</tr>
<tr>
<td>BIG-IP (all modules)</td><td>All</td><td>None</td><td>Not applicable</td>
<td>Not vulnerable</td><td>None</td>
</tr>
</table>
<p>CVE-2026-121812 APM session bypass.</p>
"""


def _k_result(label: str, details: str, title: str) -> dict:
    return {
        "title": title,
        "excerpt": title,
        "clickUri": f"https://my.f5.com/manage/s/article/{label}",
        "raw": {"sfdetails__c": details, "f5_document_type": ["Security Advisory"]},
    }


def test_not_affected_k_article_is_clear() -> None:
    status, severity, remedy = article_judgment(_CLEAR, "17.5.1.11")
    assert status == "해당 없음"
    assert severity == ""
    assert remedy == ""


def test_fix_version_and_previous_build_include_apm() -> None:
    status, severity, remedy = article_judgment(_PHP, "17.5.1.11")
    assert status == "17.5.1.11 Fixed"
    assert severity == "High"
    assert "BIG-IP APM" in remedy

    status, severity, remedy = article_judgment(_PHP, "17.5.1.10")
    assert status == "해당됨"
    assert severity == "High"
    assert "BIG-IP APM" in remedy
    assert "BIG-IP (all modules)" in remedy
    assert "17.5.1.11" in remedy
    assert "Hotfix-BIGIP-17.5.1.10.0.37.35-ENG" in remedy
    assert "17.1.3.7" not in remedy


def test_affected_without_a_fix_says_fix_is_not_released() -> None:
    html = """
    <table>
    <tr>
    <td>Product</td><td>Branch</td><td>Versions known to be vulnerable</td>
    <td>Fixes introduced in</td><td>Severity/CVSS score</td><td>Vulnerable component</td>
    </tr>
    <tr>
    <td>BIG-IP (all modules)</td><td>17.x</td><td>17.5.0 - 17.5.1</td><td>None</td>
    <td>High/8.1</td><td>Control plane</td>
    </tr>
    </table>
    <p>CVE-2026-100001 PHP remote code execution.</p>
    """
    status, _severity, remedy = article_judgment(html, "17.5.1.10")
    assert status == "해당됨"
    assert remedy == "해결 버전 미출 시"
    blank = html.replace("<td>None</td>", "<td></td>")
    status, _severity, remedy = article_judgment(blank, "17.5.1.10")
    assert status == "해당됨"
    assert remedy == "해결 버전 미출 시"


def test_apm_row_alone_marks_the_version_affected() -> None:
    status, _severity, remedy = article_judgment(_APM_ONLY, "17.5.1.10")
    assert status == "해당됨"
    assert remedy == "BIG-IP APM: 17.5.1.11"
    fixed, _severity, _remedy = article_judgment(_APM_ONLY, "17.5.1.11")
    assert fixed == "17.5.1.11 Fixed"


def test_lookup_uses_k_articles_for_pasted_cves(monkeypatch, tmp_path: Path) -> None:
    def fake(query: str, *, aq: str = "", limit: int = 20):
        if "CVE-2026-115560" in query:
            return [
                _k_result(
                    "K000163878",
                    _CLEAR,
                    "PHP vulnerability CVE-2026-115560",
                )
            ]
        if "CVE-2026-109618" in query:
            return [
                _k_result(
                    "K000163821",
                    _PHP,
                    "PHP vulnerabilities CVE-2026-109618 and CVE-2026-109619",
                )
            ]
        raise AssertionError(query)

    monkeypatch.setattr("app.modules.nhealth.cve_lookup.search_documents", fake)
    hits = lookup_k_cves(
        "17.5.1.10",
        "CVE-2026-115560\nCVE-2026-109618",
        tmp_path,
    )
    assert [hit.cve for hit in hits] == ["CVE-2026-115560", "CVE-2026-109618"]
    assert hits[0].status == "해당 없음"
    assert hits[0].f5_label == "K000163878"
    assert hits[0].f5_url.endswith("/K000163878")
    assert hits[1].status == "해당됨"
    assert hits[1].f5_label == "K000163821"
    assert "BIG-IP APM" in hits[1].remedy
    assert "17.5.1.11" in hits[1].remedy
    path = tmp_path / "report.html"
    write_cve_report(path, "17.5.1.10", hits)
    report = path.read_text(encoding="utf-8")
    assert "해결 버전" in report
    assert "Hotfix-BIGIP-17.5.1.10.0.37.35-ENG" in report
    assert ">해당됨<" in report


def test_blank_cve_box_searches_k_articles_for_the_version(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def fake(query: str, *, aq: str = "", limit: int = 20):
        seen["query"] = query
        seen["aq"] = aq
        return [
            _k_result(
                "K000163821",
                _PHP,
                "PHP vulnerabilities CVE-2026-109618 and CVE-2026-109619",
            )
        ]

    monkeypatch.setattr("app.modules.nhealth.cve_lookup.search_documents", fake)
    hits = lookup_k_cves("17.5.1.11", "", tmp_path)
    assert seen["query"] == '"17.5.1.11"'
    assert "Security Advisory" in seen["aq"]
    by_cve = {hit.cve: hit for hit in hits}
    assert by_cve["CVE-2026-109618"].status == "17.5.1.11 Fixed"
    assert by_cve["CVE-2026-109619"].f5_label == "K000163821"


def test_f5_title_names_the_php_vulnerability() -> None:
    summary = describe_vulnerability(
        "K000163878: PHP vulnerability CVE-2026-115560",
        "Session serializer mismatch can lead to remote code execution.",
    )
    assert summary == "PHP 세션 직렬화 불일치로 원격 코드 실행 취약점"
    assert "공개된" not in summary
    magic = describe_vulnerability(
        "K000164314: Multiple PHP vulnerabilities",
        "Use-after-free in magic method backtraces can lead to remote code execution.",
    )
    assert magic == "PHP 해제 후 재사용으로 원격 코드 실행 취약점"
    assert "backtraces" not in magic


def test_nvd_score_fills_severity_without_changing_status(tmp_path: Path, monkeypatch) -> None:
    hit = CveHit(
        "CVE-2026-115560",
        "PHP 취약점",
        "해당 없음",
        "https://nvd.nist.gov/vuln/detail/CVE-2026-115560",
        "K000163878",
        "https://my.f5.com/manage/s/article/K000163878",
        "Medium",
    )
    payload = {
        "vulnerabilities": [
            {
                "cve": {
                    "descriptions": [
                        {
                            "lang": "en",
                            "value": (
                                "Session serializer mismatch can lead to remote code execution."
                            ),
                        }
                    ],
                    "metrics": {
                        "cvssMetricV40": [
                            {"cvssData": {"baseSeverity": "CRITICAL", "baseScore": 9.2}}
                        ]
                    },
                }
            }
        ]
    }
    monkeypatch.setattr(
        "app.modules.nhealth.cve_lookup._nvd_payload",
        lambda *_args, **_kwargs: (payload, False),
    )
    updated = apply_nvd_severity([hit], tmp_path)
    assert updated[0].status == "해당 없음"
    assert "Fixed" not in updated[0].status
    assert updated[0].severity == "Critical"
    assert updated[0].summary == "PHP 세션 직렬화 불일치로 원격 코드 실행 취약점"
