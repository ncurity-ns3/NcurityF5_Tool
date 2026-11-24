"""Release Notes Checker uses exact builds and named bug lists."""

from __future__ import annotations

import json
import os
import tarfile
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.gui.views.release_notes_view import ReleaseNotesCheckerView
from app.gui.widgets.report_window import ReportWindow
from app.modules.nhealth.config_profile import (
    applies_to_config,
    profile_from_texts,
    read_config_profile,
)
from app.modules.nhealth.release_catalog import (
    ReleaseItem,
    at_least_severity,
    fill_missing_severity,
    load_release_catalog,
    parse_release_html,
    parse_version_text,
    severity_from_bug_page,
)
from app.modules.nhealth.release_notes import (
    ReleaseNoteError,
    WatchedBug,
    advanced_issue_report,
    basic_issue_report,
    check_watched_bugs,
    load_bug_lists,
    save_bug_lists,
    upsert_named_bug,
)
from app.modules.nhealth.release_report import write_bug_report

_app = QApplication.instance() or QApplication([])

_HTML = """
<html><body>
Version: 21.1.0.1 Build: 26.0
<b>Fixed in this Release</b>
<b>TMOS Fixes</b>
<table>
<tr><td>ID Number</td><td>Links to More Info</td><td>Description</td><td>Fixed Versions</td></tr>
<tr><td><a href="#A701341-8">701341-8</a></td><td>BT701341</td>
<td>mcpd continuously restarts</td><td>21.1.0.1</td></tr>
</table>
<b>Known Issues in BIG-IP v21.1.x</b>
<b>Local Traffic Manager Issues</b>
<table>
<tr><td>ID Number</td><td>Links to More Info</td><td>Description</td></tr>
<tr><td>2355421-1</td><td>BT2355421</td><td>Azure traffic loss</td></tr>
</table>
<b>Application Security Manager Fixes</b>
<table>
<tr><td>ID Number</td><td>CVE</td><td>Description</td><td>Fixed Versions</td></tr>
<tr><td>929709-9</td><td>CVE-2020-11023</td><td>jQuery vulnerability</td><td>21.1.0.1</td></tr>
</table>
</body></html>
"""


def _notes():
    return parse_release_html(
        _HTML,
        version="21.1.0.1",
        url="https://techdocs.example/21",
        source="fixture",
    )


def test_exact_version_rejects_a_train_label() -> None:
    assert parse_version_text("21.1.0.1 (Build 26.0)") == "21.1.0.1"
    try:
        parse_version_text("21.1.x")
    except ReleaseNoteError:
        return
    raise AssertionError("21.1.x should be rejected")


def test_bug_list_is_named_and_release_note_sets_the_verdict(tmp_path: Path) -> None:
    lists = upsert_named_bug([], "고객A", "BT701341", "mcpd restart")
    lists = upsert_named_bug(lists, "고객A", "2355421", "azure")
    lists = upsert_named_bug(lists, "고객B", "999999", "없는 버그")
    notes = _notes()
    assert notes.build == "26.0"
    found = check_watched_bugs(notes, list(lists[0].bugs))
    by_id = {row.bug_id: row.verdict for row in found}
    assert by_id["BT701341"] == "Fixed"
    assert by_id["2355421"] == "유효"
    missing = check_watched_bugs(notes, [WatchedBug("999999", "없는 버그")])
    assert missing[0].verdict == "미포함"
    basic = basic_issue_report(notes, ["LTM", "AWAF"])
    assert basic[0].module == "LTM"
    assert "Known 1" in basic[0].item
    assert "취약점 1" in basic[1].item
    path = tmp_path / "bug_lists.json"
    save_bug_lists(path, lists)
    assert [entry.name for entry in load_bug_lists(path)] == ["고객A", "고객B"]


def test_catalog_skips_train_labels(tmp_path: Path) -> None:
    path = tmp_path / "versions.json"
    path.write_text(
        json.dumps(
            {
                "versions": [
                    {"version": "21.1.x", "build": ""},
                    {"version": "17.1.3.6", "build": "20.0"},
                    {"version": "21.1.0.1", "build": "26.0"},
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = load_release_catalog(path)
    assert [entry.version for entry in loaded] == ["21.1.0.1", "17.1.3.6"]
    assert loaded[0].label == "21.1.0.1 (Build 26.0)"


def test_advanced_keeps_modules_that_are_in_the_config(tmp_path: Path) -> None:
    archive = tmp_path / "lab.ucs"
    with tarfile.open(archive, "w") as tar:
        conf = (
            b"sys global-settings { hostname bigip.example.com }\n"
            b"sys provision ltm { level nominal }\n"
            b"sys provision asm { level none }\n"
            b"ltm virtual /Common/vs1 { }\n"
        )
        info = tarfile.TarInfo("config/bigip.conf")
        info.size = len(conf)
        tar.addfile(info, BytesIO(conf))
        version = b"Product: BIG-IP\nVersion: 17.1.2.1\nBuild: 0.0.12\n"
        ver = tarfile.TarInfo("VERSION")
        ver.size = len(version)
        tar.addfile(ver, BytesIO(version))
    profile = read_config_profile(archive)
    assert profile.version == "17.1.2.1"
    assert profile.build == "0.0.12"
    assert "LTM" in profile.modules
    assert "AWAF" not in profile.modules
    rows = advanced_issue_report(_notes(), profile)
    modules = {row.module for row in rows}
    assert "LTM" in modules
    assert "AWAF" not in modules
    empty = profile_from_texts({})
    assert empty.modules == ()


def test_screen_uses_named_lists_exact_builds_and_a_report_button(tmp_path: Path) -> None:
    catalog = tmp_path / "versions.json"
    catalog.write_text(
        json.dumps({"versions": [{"version": "21.1.0.1", "build": "26.0"}]}),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    view = ReleaseNotesCheckerView(data, catalog)
    view.show()
    _app.processEvents()
    labels = [view.bug_version.itemText(i) for i in range(view.bug_version.count())]
    assert any(label.startswith("21.1.0.1") and "Build 26.0" in label for label in labels)
    assert all(".x" not in label for label in labels)
    assert view.bug_report_btn.text() == "레포트"
    assert view.issue_report_btn.text() == "레포트"
    assert not view.bug_report_btn.isEnabled()
    view.bug_id.setText("701341")
    view.bug_title.setText("mcpd restart")
    view._add_bug()
    assert view.bug_table.item(0, 0).text() == "701341"
    view.list_name.setText("고객A")
    view._save_list()
    view._draft = []
    view._show_draft()
    view.bug_id.setText("888")
    view.bug_title.setText("other")
    view._add_bug()
    view.list_name.setText("고객B")
    view._save_list()
    view.list_combo.setCurrentText("고객A")
    view._load_list()
    _app.processEvents()
    assert view.bug_table.item(0, 0).text() == "701341"
    view.tabs.setCurrentIndex(1)
    _app.processEvents()
    assert view.severity_combo.count() == 6
    assert view.issue_version.height() == view.mode_combo.height()
    assert view.module_box.isVisible()
    view.mode_combo.setCurrentIndex(1)
    _app.processEvents()
    assert view.file_box.isVisible()
    assert not view.module_box.isVisible()
    again = ReleaseNotesCheckerView(data, catalog)
    again.list_combo.setCurrentText("고객A")
    again._load_list()
    assert again.bug_table.rowCount() == 1
    view.close()
    again.close()


_SEVERITY_HTML = """
<html><body>
Version: 17.5.1.11 Build: 12.0
<b>Fixed in this Release</b>
<b>TMOS Fixes</b>
<table>
<tr><td>ID Number</td><td>Description</td><td>Severity</td><td>Fixed Versions</td></tr>
<tr><td>1001-1</td><td>mcpd restart</td><td>1-Blocking</td><td>17.5.1.11</td></tr>
<tr><td>1003-1</td><td>logon page fails</td><td>3-Major</td><td>17.5.1.11</td></tr>
<tr><td>1004-1</td><td>SAML assertion fails</td><td>4-Minor</td><td>17.5.1.11</td></tr>
</table>
<b>APM Fixes</b>
<table>
<tr><td>ID Number</td><td>Description</td><td>Severity</td></tr>
<tr><td>1005-1</td><td>APM SAML logon fails</td><td>2-Critical</td></tr>
</table>
</body></html>
"""


def test_severity_keeps_the_selected_rank_and_above() -> None:
    notes = parse_release_html(
        _SEVERITY_HTML,
        version="17.5.1.11",
        url="https://techdocs.example/17",
        source="fixture",
    )
    by_id = {item.bug_id: item.severity for item in notes.items}
    assert by_id["1001-1"] == "1-Blocking"
    kept = [item.bug_id for item in notes.items if at_least_severity(item, 3)]
    assert kept == ["1001-1", "1003-1", "1005-1"]


def test_advanced_drops_a_feature_the_config_does_not_have(tmp_path: Path) -> None:
    notes = parse_release_html(
        _SEVERITY_HTML,
        version="17.5.1.11",
        url="https://techdocs.example/17",
        source="fixture",
    )
    profile = profile_from_texts(
        {
            "bigip.conf": (
                "sys provision ltm { level nominal }\n"
                "sys provision apm { level nominal }\n"
                "ltm virtual /Common/v { }\n"
                "apm profile access /Common/a { }\n"
            )
        }
    )
    assert "APM" in profile.features
    assert "SAML" not in profile.features
    rows = advanced_issue_report(notes, profile)
    apm = next(row for row in rows if row.source == "Release Note" and row.module == "APM")
    assert "Fixed 0" in apm.item
    tmos = next(row for row in rows if row.source == "Release Note" and row.module == "TMOS")
    assert "Fixed 2" in tmos.item
    from app.modules.nhealth.release_report import write_issue_report

    path = tmp_path / "issue.html"
    visible = [
        item
        for item in notes.items
        if applies_to_config(item.description, profile.features)
    ]
    write_issue_report(path, notes, list(profile.modules), visible, profile)
    html = path.read_text(encoding="utf-8")
    assert 'id="kw"' in html
    assert "applyFilters" in html
    assert "<option value='TMOS'>TMOS</option>" in html
    assert "<option value='LTM'>LTM</option>" in html
    assert "<option value='APM'>APM</option>" in html
    assert "<option value='AWAF'>" not in html
    assert "<option value='fixed'>Fixed</option>" in html
    assert "value='1-Blocking'" in html
    assert "value='3-Major'" in html
    assert "value='4-Minor'" not in html
    assert "filter-group" in html
    assert "data-module='TMOS'" in html
    assert "data-module='LTM'" in html
    assert "data-module='APM'" in html
    assert "SAML assertion" not in html
    assert "mcpd restart" in html


def test_bug_report_has_the_issue_filters(tmp_path: Path) -> None:
    notes = _notes()
    checks = check_watched_bugs(
        notes,
        [
            WatchedBug("701341", "mcpd"),
            WatchedBug("2355421", "azure"),
            WatchedBug("999999", "없는 버그"),
        ],
    )
    assert checks[0].module == "TMOS"
    assert checks[1].module == "LTM"
    path = tmp_path / "bugs.html"
    write_bug_report(path, notes, checks, "고객A")
    html = path.read_text(encoding="utf-8")
    assert "id='mod'" in html
    assert "id='kind'" in html
    assert "id='sev-filters'" in html
    assert "<option value='TMOS'>TMOS</option>" in html
    assert "<option value='LTM'>LTM</option>" in html
    assert "<option value='fixed'>Fixed</option>" in html
    assert "<option value='known'>Known</option>" in html
    assert "<option value='missing'>미포함</option>" in html
    assert "data-module='TMOS'" in html
    assert "data-kind='fixed'" in html
    assert "value='none'" in html


def test_report_window_allows_maximize(tmp_path: Path) -> None:
    page = tmp_path / "report.html"
    page.write_text("<html><body>report</body></html>", encoding="utf-8")
    window = ReportWindow(page)
    flags = window.windowFlags()
    assert flags & Qt.WindowType.WindowMaximizeButtonHint
    assert flags & Qt.WindowType.WindowMinimizeButtonHint
    window.close()


def test_bug_page_severity_meta() -> None:
    page = '<html><head><meta name="severity" content="2-Critical"/></head></html>'
    assert severity_from_bug_page(page) == "2-Critical"
    swapped = '<meta content="4-Minor" name="severity"/>'
    assert severity_from_bug_page(swapped) == "4-Minor"
    assert severity_from_bug_page("<html></html>") == ""


def test_missing_severity_is_filled_from_the_cache(tmp_path: Path) -> None:
    cache = tmp_path / "severity"
    cache.mkdir()
    (cache / "1001.txt").write_text("1-Blocking", encoding="utf-8")
    item = ReleaseItem(
        "1001-1",
        "",
        "mcpd restart",
        "17.5.1.11",
        "TMOS Fixes",
        "TMOS",
        "fixed",
    )
    filled = fill_missing_severity([item], cache)
    assert filled[0].severity == "1-Blocking"
    assert at_least_severity(filled[0], 1)
