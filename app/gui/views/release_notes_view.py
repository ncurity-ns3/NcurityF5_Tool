"""Release Notes Checker: named bug lists, exact builds, and a report."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.widgets.report_window import ReportWindow
from app.gui.workers.release_notes_worker import (
    ReleaseNotesWorker,
    ReleaseVersionWorker,
    SearchResult,
)
from app.modules.nhealth.release_catalog import (
    load_release_catalog,
    parse_version_text,
    save_release_catalog,
    shipped_catalog_path,
)
from app.modules.nhealth.release_notes import (
    MODULES,
    ReleaseNoteError,
    WatchedBug,
    bugs_for,
    delete_bug_list,
    load_bug_lists,
    replace_bug_list,
    save_bug_lists,
    upsert_named_bug,
)

_FILE_FILTER = "UCS / QKView (*.ucs *.qkview)"


def _table(columns: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setProperty("role", "copyGrid")
    table.setHorizontalHeaderLabels(list(columns))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setMinimumHeight(140)
    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    if len(columns) > 1:
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    return table


def _fill(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            table.setItem(row_index, column, item)


_MODULE_ROW = {
    "TMOS": "#E8F1FF",
    "LTM": "#E7F6EE",
    "AWAF": "#FEF3C7",
    "DNS": "#EDE9FE",
    "SSL-O": "#CFFAFE",
    "APM": "#FCE7F3",
}


def _paint_modules(table: QTableWidget) -> None:
    for row in range(table.rowCount()):
        module = table.item(row, 1)
        if module is None:
            continue
        color = _MODULE_ROW.get(module.text())
        if color is None:
            continue
        brush = QBrush(QColor(color))
        for column in range(table.columnCount()):
            cell = table.item(row, column)
            if cell is not None:
                cell.setBackground(brush)


class ReleaseNotesCheckerView(QWidget):
    def __init__(
        self,
        data_dir: Path | None = None,
        catalog_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data_dir = data_dir or local_data_dir()
        self._catalog_path = catalog_path
        self._bug_path = self._data_dir / "nhealth" / "bug_lists.json"
        self._cache_dir = self._data_dir / "nhealth" / "release_cache"
        self._report_dir = self._data_dir / "nhealth" / "reports"
        self._user_catalog = self._data_dir / "nhealth" / "release_versions.json"
        self._lists = load_bug_lists(self._bug_path)
        self._draft: list[WatchedBug] = []
        self._versions = self._load_versions()
        self._archive: Path | None = None
        self._worker: ReleaseNotesWorker | ReleaseVersionWorker | None = None
        self._bug_report: Path | None = None
        self._issue_report: Path | None = None
        self._version_combos: list[QComboBox] = []
        self.setAcceptDrops(True)
        self._build()
        self._reload_list_combo()

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
        title = QLabel("Release Notes Checker")
        mark_page_title(title)
        outer.addWidget(title)
        subtitle = QLabel(
            "버그 목록을 이름으로 저장하고, 실제 릴리즈 번호의 Release Note와 비교합니다. "
            "이슈 정리는 Basic이면 모듈 기준, Advanced이면 UCS·QKView 설정 기준입니다."
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

        self.tabs = QTabWidget()
        self.tabs.setObjectName("releaseNotesTabs")
        self.tabs.addTab(self._bug_tab(), "버그 포함 확인")
        self.tabs.addTab(self._issue_tab(), "이슈 정리")
        root.addWidget(self.tabs)

        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        outer.addWidget(self.status)
        outer.addWidget(self.progress)

    def _version_combo(self) -> QComboBox:
        combo = QComboBox()
        configure_form_combobox(combo)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if combo.lineEdit() is not None:
            combo.lineEdit().setPlaceholderText("예: 17.1.3.6")
        self._version_combos.append(combo)
        self._fill_one_version(combo)
        return combo

    def _fill_versions(self) -> None:
        for combo in self._version_combos:
            self._fill_one_version(combo)

    def _fill_one_version(self, combo: QComboBox) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        for entry in self._versions:
            combo.addItem(entry.label, entry.version)
        combo.setCurrentText(current)
        combo.blockSignals(False)

    def _bug_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        name_box = QGroupBox("버그 목록")
        name_form = QFormLayout(name_box)
        self.list_name = self._form_line(QLineEdit())
        self.list_name.setPlaceholderText("목록 이름")
        name_form.addRow("이름", self.list_name)
        self._align_form_label(name_form, self.list_name)
        saved_row = QHBoxLayout()
        self.list_combo = QComboBox()
        configure_form_combobox(self.list_combo)
        load_btn = QPushButton("Load")
        save_btn = QPushButton("Save")
        delete_btn = QPushButton("Delete")
        load_btn.clicked.connect(self._load_list)
        save_btn.clicked.connect(self._save_list)
        delete_btn.clicked.connect(self._delete_list)
        saved_row.addWidget(self.list_combo, stretch=1)
        saved_row.addWidget(load_btn)
        saved_row.addWidget(save_btn)
        saved_row.addWidget(delete_btn)
        name_form.addRow("저장된 목록", saved_row)
        self._align_form_label(name_form, saved_row)
        layout.addWidget(name_box)

        add_row = QHBoxLayout()
        self.bug_id = self._form_line(QLineEdit())
        self.bug_id.setPlaceholderText("Bug ID")
        self.bug_title = self._form_line(QLineEdit())
        self.bug_title.setPlaceholderText("버그 제목")
        add_btn = QPushButton("추가")
        mark_primary_button(add_btn)
        add_btn.clicked.connect(self._add_bug)
        list_add_btn = QPushButton("목록에 추가")
        mark_secondary_button(list_add_btn)
        list_add_btn.clicked.connect(self._add_to_list)
        add_row.addWidget(self.bug_id, stretch=1)
        add_row.addWidget(self.bug_title, stretch=2)
        add_row.addWidget(add_btn)
        add_row.addWidget(list_add_btn)
        layout.addLayout(add_row)

        self.bug_table = _table(("Bug ID", "제목"))
        layout.addWidget(self.bug_table)
        remove_row = QHBoxLayout()
        remove_btn = QPushButton("선택 삭제")
        remove_btn.clicked.connect(self._remove_bugs)
        remove_row.addWidget(remove_btn)
        remove_row.addStretch()
        layout.addLayout(remove_row)

        search_box = QGroupBox("버전 Release Note")
        search_form = QFormLayout(search_box)
        version_row = QHBoxLayout()
        self.bug_version = self._version_combo()
        refresh_btn = QPushButton("버전 목록 새로고침")
        mark_secondary_button(refresh_btn)
        refresh_btn.clicked.connect(self._refresh_versions)
        self.refresh_btn = refresh_btn
        version_row.addWidget(self.bug_version, stretch=1)
        version_row.addWidget(refresh_btn)
        search_form.addRow("버전", version_row)
        self._align_form_label(search_form, version_row)
        action_row = QHBoxLayout()
        self.bug_search_btn = QPushButton("서치")
        mark_primary_button(self.bug_search_btn)
        self.bug_search_btn.clicked.connect(self._search_bugs)
        self.bug_report_btn = QPushButton("레포트")
        mark_secondary_button(self.bug_report_btn)
        self.bug_report_btn.setEnabled(False)
        self.bug_report_btn.clicked.connect(self._open_bug_report)
        action_row.addWidget(self.bug_search_btn)
        action_row.addWidget(self.bug_report_btn)
        action_row.addStretch()
        search_form.addRow("", action_row)
        layout.addWidget(search_box)

        self.bug_summary = QLabel("서치 결과가 여기에 표시됩니다.")
        self.bug_summary.setWordWrap(True)
        self.bug_summary.setProperty("role", "muted")
        layout.addWidget(self.bug_summary)
        self.bug_result = _table(("Bug ID", "제목", "판정", "상태", "비고"))
        layout.addWidget(self.bug_result)
        return page

    def _issue_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        mode_box = QGroupBox("점검 방식")
        mode_form = QFormLayout(mode_box)
        mode_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        mode_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        mode_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        mode_form.setHorizontalSpacing(16)
        mode_form.setVerticalSpacing(10)

        self.mode_combo = QComboBox()
        configure_form_combobox(self.mode_combo)
        self.mode_combo.addItem("Basic", "basic")
        self.mode_combo.addItem("Advanced", "advanced")
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        mode_form.addRow("방식", self.mode_combo)
        self._align_form_label(mode_form, self.mode_combo)

        self.issue_version = self._version_combo()
        mode_form.addRow("버전", self.issue_version)
        self._align_form_label(mode_form, self.issue_version)

        self.severity_combo = QComboBox()
        configure_form_combobox(self.severity_combo)
        self.severity_combo.addItem("전체", 0)
        self.severity_combo.addItem("1-Blocking 이상", 1)
        self.severity_combo.addItem("2-Critical 이상", 2)
        self.severity_combo.addItem("3-Major 이상", 3)
        self.severity_combo.addItem("4-Minor 이상", 4)
        self.severity_combo.addItem("5-Cosmetic 이상", 5)
        mode_form.addRow("Severity", self.severity_combo)
        self._align_form_label(mode_form, self.severity_combo)

        self.mode_note = QLabel("선택한 버전의 Release Note, 버그, 취약점을 모듈별로 정리합니다.")
        self.mode_note.setWordWrap(True)
        self.mode_note.setProperty("role", "muted")
        mode_form.addRow("", self.mode_note)

        self.module_box = QGroupBox("모듈")
        grid = QGridLayout(self.module_box)
        self.module_checks: list[NcurityCheckBox] = []
        for index, name in enumerate(MODULES):
            box = NcurityCheckBox(name)
            self.module_checks.append(box)
            grid.addWidget(box, index // 3, index % 3)
        mode_form.addRow("", self.module_box)

        self.file_box = QWidget()
        file_row = QHBoxLayout(self.file_box)
        file_row.setContentsMargins(0, 0, 0, 0)
        self.file_label = QLabel("선택된 파일 없음")
        self.file_label.setProperty("role", "muted")
        pick = QPushButton("UCS / QKView 선택…")
        pick.clicked.connect(self._pick_archive)
        clear = QPushButton("지우기")
        clear.clicked.connect(self._clear_archive)
        file_row.addWidget(self.file_label, stretch=1)
        file_row.addWidget(pick)
        file_row.addWidget(clear)
        mode_form.addRow("파일", self.file_box)
        self._file_caption = mode_form.labelForField(self.file_box)
        self._align_form_label(mode_form, self.file_box)
        self.file_box.setVisible(False)
        if self._file_caption is not None:
            self._file_caption.setVisible(False)
        hint = QLabel("파일을 이 화면에 놓아도 됩니다. 설정에 있는 기능의 이슈만 정리합니다.")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        self.file_hint = hint
        mode_form.addRow("", hint)
        hint.setVisible(False)
        layout.addWidget(mode_box)

        action_row = QHBoxLayout()
        self.issue_search_btn = QPushButton("서치")
        mark_primary_button(self.issue_search_btn)
        self.issue_search_btn.clicked.connect(self._search_issues)
        self.issue_report_btn = QPushButton("레포트")
        mark_secondary_button(self.issue_report_btn)
        self.issue_report_btn.setEnabled(False)
        self.issue_report_btn.clicked.connect(self._open_issue_report)
        action_row.addWidget(self.issue_search_btn)
        action_row.addWidget(self.issue_report_btn)
        action_row.addStretch()
        layout.addLayout(action_row)
        self.issue_summary = QLabel("서치 결과가 여기에 표시됩니다.")
        self.issue_summary.setWordWrap(True)
        self.issue_summary.setProperty("role", "muted")
        layout.addWidget(self.issue_summary)
        self.issue_result = _table(("출처", "모듈", "항목", "상태", "비고"))
        layout.addWidget(self.issue_result)
        return page

    def _form_line(self, edit: QLineEdit) -> QLineEdit:
        edit.setProperty("formControl", "formLine")
        edit.setFixedHeight(36)
        return edit

    def _align_form_label(self, form: QFormLayout, field: QWidget) -> None:
        label = form.labelForField(field)
        if label is not None:
            label.setProperty("role", "formLabel")

    def _reload_list_combo(self, select: str = "") -> None:
        self.list_combo.blockSignals(True)
        self.list_combo.clear()
        self.list_combo.addItem("")
        for entry in self._lists:
            self.list_combo.addItem(entry.name)
        self.list_combo.setCurrentText(select)
        self.list_combo.blockSignals(False)

    def _current_list_name(self) -> str:
        typed = self.list_name.text().strip()
        if typed:
            return typed
        return self.list_combo.currentText().strip()

    def _show_draft(self) -> None:
        _fill(self.bug_table, [(bug.bug_id, bug.title) for bug in self._draft])

    def _take_bug(self) -> WatchedBug:
        bug_id = self.bug_id.text().strip()
        if not bug_id:
            raise ReleaseNoteError("Bug ID를 입력하세요.")
        return WatchedBug(bug_id, self.bug_title.text().strip())

    def _put_draft(self, bug: WatchedBug) -> None:
        kept = [item for item in self._draft if item.bug_id.casefold() != bug.bug_id.casefold()]
        kept.append(bug)
        kept.sort(key=lambda item: item.bug_id.casefold())
        self._draft = kept
        self._show_draft()

    def _store_lists(self, select: str) -> None:
        save_bug_lists(self._bug_path, self._lists)
        self._reload_list_combo(select)

    def _load_list(self) -> None:
        name = self.list_combo.currentText().strip()
        if not name:
            QMessageBox.information(self, "Release Notes Checker", "불러올 목록을 선택하세요.")
            return
        self._draft = bugs_for(self._lists, name)
        self.list_name.setText(name)
        self._show_draft()

    def _save_list(self) -> None:
        if not self._draft:
            QMessageBox.information(self, "Release Notes Checker", "저장할 버그가 없습니다.")
            return
        name = self._current_list_name()
        if not name:
            name, ok = QInputDialog.getText(self, "Save", "저장할 목록 이름:")
            if not ok or not name.strip():
                return
            name = name.strip()
        try:
            self._lists = replace_bug_list(self._lists, name, self._draft)
        except ReleaseNoteError as exc:
            QMessageBox.warning(self, "Release Notes Checker", str(exc))
            return
        self.list_name.setText(name)
        self._store_lists(name)

    def _add_bug(self) -> None:
        try:
            bug = self._take_bug()
        except ReleaseNoteError as exc:
            QMessageBox.warning(self, "Release Notes Checker", str(exc))
            return
        self._put_draft(bug)
        self.bug_id.clear()
        self.bug_title.clear()

    def _add_to_list(self) -> None:
        try:
            bug = self._take_bug()
            name = self._current_list_name()
            if not name:
                raise ReleaseNoteError("목록을 선택하거나 이름을 입력하세요.")
            self._lists = upsert_named_bug(self._lists, name, bug.bug_id, bug.title)
        except ReleaseNoteError as exc:
            QMessageBox.warning(self, "Release Notes Checker", str(exc))
            return
        self._put_draft(bug)
        self.bug_id.clear()
        self.bug_title.clear()
        self.list_name.setText(name)
        self._store_lists(name)

    def _remove_bugs(self) -> None:
        rows = sorted({item.row() for item in self.bug_table.selectedItems()})
        if not rows:
            QMessageBox.information(self, "Release Notes Checker", "삭제할 버그를 선택하세요.")
            return
        drop = {self.bug_table.item(row, 0).text() for row in rows if self.bug_table.item(row, 0)}
        self._draft = [bug for bug in self._draft if bug.bug_id not in drop]
        self._show_draft()

    def _delete_list(self) -> None:
        name = self.list_combo.currentText().strip()
        if not name:
            QMessageBox.information(self, "Release Notes Checker", "삭제할 목록을 선택하세요.")
            return
        self._lists = delete_bug_list(self._lists, name)
        if self.list_name.text().strip() == name:
            self.list_name.clear()
        self._store_lists("")

    def _selected_version(self, combo: QComboBox) -> str:
        text = combo.currentText().strip()
        data = combo.currentData()
        if isinstance(data, str) and data and text.startswith(data):
            return data
        return parse_version_text(text)

    def _search_bugs(self) -> None:
        try:
            version = self._selected_version(self.bug_version)
            if not self._draft:
                raise ReleaseNoteError("추가한 버그가 없습니다.")
        except ReleaseNoteError as exc:
            QMessageBox.warning(self, "Release Notes Checker", str(exc))
            return
        worker = ReleaseNotesWorker(
            mode="bugs",
            version=version,
            cache_dir=self._cache_dir,
            report_dir=self._report_dir,
            bugs=list(self._draft),
            list_name=self._current_list_name() or "작업 목록",
        )
        self._start(worker)

    def _search_issues(self) -> None:
        advanced = self.mode_combo.currentData() == "advanced"
        try:
            version = self._selected_version(self.issue_version)
            if advanced:
                if self._archive is None:
                    raise ReleaseNoteError("UCS 또는 QKView 파일을 선택하세요.")
                modules: list[str] = []
                archive = self._archive
            else:
                modules = [box.text() for box in self.module_checks if box.isChecked()]
                if not modules:
                    raise ReleaseNoteError("모듈을 하나 이상 선택하세요.")
                archive = None
            rank = self.severity_combo.currentData()
            severity_max = rank if isinstance(rank, int) and rank > 0 else None
        except ReleaseNoteError as exc:
            QMessageBox.warning(self, "Release Notes Checker", str(exc))
            return
        worker = ReleaseNotesWorker(
            mode="advanced" if advanced else "basic",
            version=version,
            cache_dir=self._cache_dir,
            report_dir=self._report_dir,
            modules=modules,
            archive=archive,
            severity_max=severity_max,
        )
        self._start(worker)

    def _refresh_versions(self) -> None:
        self._start(ReleaseVersionWorker())

    def _start(self, worker: ReleaseNotesWorker | ReleaseVersionWorker) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = worker
        self._set_busy(True)
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
        self._set_busy(False)
        self.progress.setValue(100)
        self.progress.setVisible(False)
        if isinstance(result, list):
            self._versions = result
            save_release_catalog(self._user_catalog, result)
            self._fill_versions()
            self.status.setText(f"버전 {len(result)}개")
            return
        if not isinstance(result, SearchResult):
            return
        if result.kind == "bugs":
            _fill(self.bug_result, list(result.rows))
            self.bug_summary.setText(result.headline)
            self._bug_report = result.report_path
            self.bug_report_btn.setEnabled(result.report_path.is_file())
        else:
            _fill(self.issue_result, list(result.rows))
            _paint_modules(self.issue_result)
            self.issue_summary.setText(result.headline)
            self._issue_report = result.report_path
            self.issue_report_btn.setEnabled(result.report_path.is_file())
        self.status.setText(result.headline)

    def _on_fail(self, message: str) -> None:
        self._set_busy(False)
        self.progress.setVisible(False)
        self.status.setText(message)
        QMessageBox.warning(self, "Release Notes Checker", message)

    def _set_busy(self, busy: bool) -> None:
        self.bug_search_btn.setEnabled(not busy)
        self.issue_search_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)

    def _open_bug_report(self) -> None:
        self._open_report(self._bug_report)

    def _open_issue_report(self) -> None:
        self._open_report(self._issue_report)

    def _open_report(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            QMessageBox.information(self, "Release Notes Checker", "먼저 서치하세요.")
            return
        ReportWindow(path, self, title=f"Release Notes — {path.stem}").exec()

    def _on_mode(self) -> None:
        advanced = self.mode_combo.currentData() == "advanced"
        self.module_box.setVisible(not advanced)
        self.file_box.setVisible(advanced)
        self.file_hint.setVisible(advanced)
        if self._file_caption is not None:
            self._file_caption.setVisible(advanced)
        self.mode_note.setText(
            "UCS 또는 QKView 설정에 있는 기능의 Release Note, 버그, 취약점을 정리합니다."
            if advanced
            else "선택한 버전의 Release Note, 버그, 취약점을 모듈별로 정리합니다."
        )

    def _pick_archive(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "UCS 또는 QKView 선택", "", _FILE_FILTER)
        if chosen:
            self._set_archive(Path(chosen))

    def _set_archive(self, path: Path) -> None:
        self._archive = path
        self.file_label.setText(path.name)
        self.file_label.setToolTip(str(path))

    def _clear_archive(self) -> None:
        self._archive = None
        self.file_label.setText("선택된 파일 없음")
        self.file_label.setToolTip("")

    def _drop_ok(self, event) -> bool:
        return bool(
            self.tabs.currentIndex() == 1
            and self.mode_combo.currentData() == "advanced"
            and event.mimeData().hasUrls()
        )

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._drop_ok(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._drop_ok(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not self._drop_ok(event):
            event.ignore()
            return
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            path = Path(local)
            if path.suffix.lower() not in {".ucs", ".qkview"}:
                continue
            self._set_archive(path)
            event.acceptProposedAction()
            return
        event.ignore()
