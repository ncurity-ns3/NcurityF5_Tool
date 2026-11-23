"""Background release-note fetch and version discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.nhealth.config_profile import applies_to_config, read_config_profile
from app.modules.nhealth.release_catalog import (
    at_least_severity,
    discover_release_versions,
    fill_missing_severity,
    load_release_notes,
    severity_label,
)
from app.modules.nhealth.release_notes import (
    ReleaseNoteError,
    WatchedBug,
    advanced_issue_report,
    basic_issue_report,
    check_watched_bugs,
    module_items,
)
from app.modules.nhealth.release_report import write_bug_report, write_issue_report


@dataclass(frozen=True)
class SearchResult:
    kind: str
    headline: str
    rows: tuple[tuple[str, ...], ...]
    report_path: Path


class ReleaseNotesWorker(QThread):
    progressed = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        mode: str,
        version: str,
        cache_dir: Path,
        report_dir: Path,
        bugs: list[WatchedBug] | None = None,
        list_name: str = "",
        modules: list[str] | None = None,
        archive: Path | None = None,
        severity_max: int | None = None,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.version = version
        self.cache_dir = cache_dir
        self.report_dir = report_dir
        self.bugs = list(bugs or [])
        self.list_name = list_name
        self.modules = list(modules or [])
        self.archive = archive
        self.severity_max = severity_max

    def run(self) -> None:
        try:
            profile = None
            if self.mode == "advanced":
                self.progressed.emit(6, "설정을 읽는 중…")
                profile = read_config_profile(self.archive) if self.archive else None
                if profile is None:
                    raise ReleaseNoteError("UCS 또는 QKView 파일을 선택하세요.")
            self.progressed.emit(12, "Release Note를 가져오는 중…")
            notes = load_release_notes(
                self.version,
                self.cache_dir,
                on_percent=lambda value: self.progressed.emit(value, "Release Note를 받는 중…"),
            )
            self.progressed.emit(93, "레포트를 만드는 중…")
            result = self._result(notes, profile)
            self.progressed.emit(100, "완료")
            self.finished_ok.emit(result)
        except ReleaseNoteError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _result(self, notes, profile) -> SearchResult:
        build = f" (Build {notes.build})" if notes.build else ""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.mode == "bugs":
            checks = check_watched_bugs(notes, self.bugs)
            path = self.report_dir / f"{stamp}_bugs.html"
            write_bug_report(path, notes, checks, self.list_name)
            rows = tuple(
                (row.bug_id, row.title, row.verdict, row.state, row.note) for row in checks
            )
            headline = (
                f"{notes.version}{build} · {self.list_name} · {len(checks)}건 · {notes.source}"
            )
            return SearchResult("bugs", headline, rows, path)
        if self.mode == "advanced":
            modules = list(profile.modules)
            items = [
                item
                for item in module_items(notes, modules)
                if applies_to_config(f"{item.description} {item.cve}", profile.features)
            ]
        else:
            modules = self.modules
            items = module_items(notes, modules)
        note = severity_label(self.severity_max)
        if self.severity_max:
            self.progressed.emit(70, "Severity를 확인하는 중…")

            def _tick(done: int, total: int) -> None:
                span = 70 + int(20 * done / max(total, 1))
                self.progressed.emit(min(90, span), f"Severity 확인 {done}/{total}")

            items = fill_missing_severity(
                items,
                self.cache_dir / "severity",
                on_progress=_tick,
            )
            items = [item for item in items if at_least_severity(item, self.severity_max)]
        if self.mode == "advanced":
            issue_rows = advanced_issue_report(notes, profile, items, note)
        else:
            issue_rows = basic_issue_report(notes, modules, items, note)
        path = self.report_dir / f"{stamp}_{self.mode}.html"
        write_issue_report(path, notes, modules, items, profile)
        rows = tuple(
            (row.source, row.module, row.item, row.state, row.note) for row in issue_rows
        )
        headline = f"{notes.version}{build} · {len(items)}건 · {notes.source}"
        return SearchResult("issues", headline, rows, path)


class ReleaseVersionWorker(QThread):
    progressed = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            versions = discover_release_versions(
                on_progress=lambda percent, text: self.progressed.emit(percent, text)
            )
            if not versions:
                raise ReleaseNoteError("techdocs에서 릴리즈 버전을 찾지 못했습니다.")
            self.progressed.emit(100, f"{len(versions)}개 버전")
            self.finished_ok.emit(versions)
        except ReleaseNoteError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


