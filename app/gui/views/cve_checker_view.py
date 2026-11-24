"""CVE Vulnerability Checker for one BIG-IP version, with an optional CVE list."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.app_paths import local_data_dir
from app.gui.form_controls import configure_form_combobox
from app.gui.theme import (
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
)
from app.gui.widgets.report_window import ReportWindow
from app.gui.workers.cve_checker_worker import CveCheckerWorker, CveSearchResult
from app.gui.workers.release_notes_worker import ReleaseVersionWorker
from app.modules.nhealth.cve_lookup import CveHit
from app.modules.nhealth.release_catalog import (
    load_release_catalog,
    parse_version_text,
    save_release_catalog,
    shipped_catalog_path,
)
from app.modules.nhealth.release_notes import ReleaseNoteError

_COLUMNS = ("CVE 취약점", "취약 내용", "Severity", "해당 여부", "NVD Link", "F5 Link")


class CveCheckerView(QWidget):
    def __init__(
        self,
        data_dir: Path | None = None,
        catalog_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data_dir = data_dir or local_data_dir()
        self._catalog_path = catalog_path
        self._cache_dir = self._data_dir / "nhealth" / "release_cache"
        self._report_dir = self._data_dir / "nhealth" / "reports"
        self._user_catalog = self._data_dir / "nhealth" / "release_versions.json"
        self._versions = self._load_versions()
        self._worker: CveCheckerWorker | ReleaseVersionWorker | None = None
        self._report: Path | None = None
        self._build()

    def _load_versions(self):
        if self._catalog_path is not None:
            return load_release_catalog(self._catalog_path)
        if self._user_catalog.is_file():
            return load_release_catalog(self._user_catalog)
        return load_release_catalog(shipped_catalog_path())

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        title = QLabel("CVE Vulnerability Checker")
        mark_page_title(title)
        outer.addWidget(title)
        subtitle = QLabel(
            "버전을 고르면 그 버전이 나오는 K 문서의 CVE를 보여 줍니다. "
            "CVE 번호를 넣으면 그 번호의 K 문서만 확인합니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, stretch=1)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setSpacing(12)

        box = QGroupBox("점검")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.version_combo = QComboBox()
        configure_form_combobox(self.version_combo)
        self.version_combo.setEditable(True)
        self.version_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if self.version_combo.lineEdit() is not None:
            self.version_combo.lineEdit().setPlaceholderText("예: 17.5.1.11")
        self._fill_versions(self.version_combo)
        form.addRow("버전", self.version_combo)
        refresh = QPushButton("버전 목록 새로고침")
        refresh.clicked.connect(self._refresh_versions)
        form.addRow("", refresh)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("CVE-2026-109618\nCVE-2026-109619")
        self.paste.setMinimumHeight(160)
        form.addRow("CVE", self.paste)
        root.addWidget(box)
        hint = QLabel(
            "CVE를 비우면 선택한 버전의 K 문서를 확인합니다. "
            "번호를 넣으면 그 CVE만, 한 번에 100개까지 볼 수 있습니다. "
            "해당됨이면 화면에는 해당됨, 레포트에는 해결 버전을 표시합니다."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        root.addWidget(hint)
        root.addLayout(self._actions())

        self.summary = QLabel("버전을 고르고 서치하세요.")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        root.addWidget(self.summary)
        self.table = self._table()
        root.addWidget(self.table)

        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        outer.addWidget(self.status)
        outer.addWidget(self.progress)

    def _actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        button = QPushButton("서치")
        mark_primary_button(button)
        button.clicked.connect(self._search)
        report = QPushButton("레포트")
        mark_secondary_button(report)
        report.clicked.connect(self._open_report)
        row.addWidget(button)
        row.addWidget(report)
        row.addStretch()
        return row

    def _table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLUMNS))
        table.setProperty("role", "copyGrid")
        table.setHorizontalHeaderLabels(list(_COLUMNS))
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setWordWrap(True)
        table.setMinimumHeight(220)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return table

    def _fill_versions(self, combo: QComboBox) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        for entry in self._versions:
            combo.addItem(entry.label, entry.version)
        combo.setCurrentText(current)
        combo.blockSignals(False)

    def _selected_version(self) -> str:
        text = self.version_combo.currentText().strip()
        data = self.version_combo.currentData()
        if isinstance(data, str) and data and text.startswith(data):
            return data
        return parse_version_text(text)

    def _search(self) -> None:
        try:
            version = self._selected_version()
        except ReleaseNoteError as exc:
            QMessageBox.warning(self, "CVE Vulnerability Checker", str(exc))
            return
        self._start(
            CveCheckerWorker(
                version=version,
                pasted=self.paste.toPlainText(),
                cache_dir=self._cache_dir,
                report_dir=self._report_dir,
            )
        )

    def _refresh_versions(self) -> None:
        self._start(ReleaseVersionWorker())

    def _start(self, worker: CveCheckerWorker | ReleaseVersionWorker) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = worker
        self.progress.setValue(0)
        self.progress.setVisible(True)
        worker.progressed.connect(self._on_progress)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_fail)
        worker.start()

    def _on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def _on_done(self, result: object) -> None:
        self.progress.setValue(100)
        self.progress.setVisible(False)
        if isinstance(result, list):
            self._versions = result
            save_release_catalog(self._user_catalog, result)
            self._fill_versions(self.version_combo)
            self.status.setText(f"버전 {len(result)}개")
            return
        if not isinstance(result, CveSearchResult):
            return
        self._fill(list(result.hits))
        self.summary.setText(result.headline)
        self._report = result.report_path
        self.status.setText(result.headline)

    def _on_fail(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status.setText(message)
        QMessageBox.warning(self, "CVE Vulnerability Checker", message)

    def _fill(self, hits: list[CveHit]) -> None:
        self.table.setRowCount(len(hits))
        for row, hit in enumerate(hits):
            self._text(row, 0, hit.cve)
            self._text(row, 1, hit.summary)
            self._text(row, 2, hit.severity or "미확인")
            self._text(row, 3, hit.status, _status_color(hit.status))
            self.table.setCellWidget(row, 4, _link_label("NVD", hit.nvd_url))
            if hit.f5_label and hit.f5_url:
                self.table.setCellWidget(row, 5, _link_label(hit.f5_label, hit.f5_url))
            else:
                self._text(row, 5, "아직 공식문서 없음")
        self.table.resizeRowsToContents()

    def _text(self, row: int, column: int, value: str, color: QColor | None = None) -> None:
        item = QTableWidgetItem(value)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if color is not None:
            item.setForeground(color)
        self.table.setItem(row, column, item)

    def _open_report(self) -> None:
        if self._report is None or not self._report.is_file():
            QMessageBox.information(self, "CVE Vulnerability Checker", "먼저 서치하세요.")
            return
        ReportWindow(self._report, self, title=f"CVE — {self._report.stem}").exec()


def _status_color(status: str) -> QColor:
    if status.endswith(" Fixed"):
        return QColor("#0A6E31")
    if status == "해당됨":
        return QColor("#B45309")
    return QColor("#64748B")


class _LinkLabel(QLabel):
    def __init__(self, text: str, url: str) -> None:
        super().__init__(f"<a href='{escape(url)}'>{escape(text)}</a>")
        self._url = url
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.setOpenExternalLinks(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(url)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl(self._url))
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _link_label(text: str, url: str) -> QLabel:
    return _LinkLabel(text, url)
