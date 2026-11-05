from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.app_paths import local_data_dir
from app.gui.theme import (
    mark_mode_choice_radio,
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
    mark_step_card,
)
from app.gui.folder_utils import module_output_root, open_in_file_manager
from app.modules.os_upgrade.k7727_versions import load_k7727_versions
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.form_controls import configure_form_combobox
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.widgets.ncurity_radio import NcurityRadioButton
from app.gui.widgets.report_window import ReportWindow
from app.gui.workers.device_overview_worker import DeviceOverviewWorker
from app.gui.workers.pre_checklist_worker import PreChecklistWorker
from app.gui.workers.pre_work_worker import PreWorkWorker
from app.gui.workers.ucs_extract_worker import UcsExtractWorker
from app.modules.os_upgrade.device_overview import DeviceOverviewReport
from app.modules.os_upgrade.overview_paths import new_job_workspace, report_path
from app.modules.os_upgrade.overview_report import write_overview_html
from app.modules.os_upgrade.pre_checklist import PreChecklistReport
from app.modules.os_upgrade.pre_checklist_report import write_pre_checklist_html
from app.modules.os_upgrade.pre_work import PreWorkReport
from app.modules.os_upgrade.pre_work_report import write_pre_work_html
from app.modules.os_upgrade.ucs_reader import peek_ucs_hostname
from app.modules.os_upgrade.ucs_extract import UcsBatchExtractResult

_BTN_MIN_H = 34


@dataclass(frozen=True)
class WorkStepDef:
    key: str
    number: str
    title: str
    report_window_title: str


WORK_STEPS: tuple[WorkStepDef, ...] = (
    WorkStepDef("device_overview", "1", "장비 개요", "장비 개요 Report"),
    WorkStepDef("pre_checklist", "2", "작업 전 Check List", "작업 전 Check List Report"),
    WorkStepDef("pre_work", "3", "사전 작업", "사전 작업 Report"),
    WorkStepDef("post_checklist", "4", "작업 후 Check List", "작업 후 Check List Report"),
)


class OsUpgradeCheckView(QWidget):
    """OS 업그레이드 간 점검 — 장비 연결 + UCS 오프라인 + 작업 단계."""

    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.output_root = module_output_root(project_root, "os_upgrade")
        self.ucs_output_root = module_output_root(project_root, "os_upgrade_check")
        self.data_dir = local_data_dir()
        self._workspace: Path | None = None
        self._folder_name: str | None = None
        self._overview_worker: DeviceOverviewWorker | None = None
        self._pre_checklist_worker: PreChecklistWorker | None = None
        self._pre_work_worker: PreWorkWorker | None = None
        self._post_checklist_worker: PreChecklistWorker | None = None
        self._ucs_worker: UcsExtractWorker | None = None
        self._last_pre_work_reports: list[PreWorkReport] = []
        self._last_post_reports: list[PreChecklistReport] = []
        self._reports: dict[str, Path] = {}
        self._run_buttons: dict[str, QPushButton] = {}
        self._report_buttons: dict[str, QPushButton] = {}
        self._last_overview_reports: list[DeviceOverviewReport] = []
        self._last_pre_reports: list[PreChecklistReport] = []
        self._last_ucs_workspace: Path | None = None
        self._last_ucs_report: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setSpacing(12)

        title = QLabel("OS 업그레이드 간 점검")
        mark_page_title(title)
        root.addWidget(title)

        subtitle = QLabel(
            "점검 방식을 선택하세요. 장비 접속은 Test Connection 후 단계별 실행, "
            "UCS는 백업 파일만으로 Hostname 기준 오프라인 추출입니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        mode_box = QGroupBox("점검 방식")
        mode_layout = QHBoxLayout(mode_box)
        mode_layout.setSpacing(28)
        self.mode_device_radio = NcurityRadioButton("1. 실제 장비 접속 후 점검하기")
        self.mode_ucs_radio = NcurityRadioButton("2. UCS로 점검하기")
        self.mode_device_radio.setChecked(True)
        mark_mode_choice_radio(self.mode_device_radio)
        mark_mode_choice_radio(self.mode_ucs_radio)
        mode_layout.addWidget(self.mode_device_radio)
        mode_layout.addWidget(self.mode_ucs_radio)
        mode_layout.addStretch()
        root.addWidget(mode_box)

        self.mode_stack = QStackedWidget()

        # --- 장비 접속 모드 ---
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(12)

        self.connection = DeviceConnectionPanel(self.data_dir)
        self.connection.connection_test_finished.connect(self._on_connection_test_finished)
        device_layout.addWidget(self.connection)

        work_box = QGroupBox("작업 (Test Connection 이후)")
        work_layout = QVBoxLayout(work_box)
        work_layout.setSpacing(10)

        meta_form = QFormLayout()
        self.work_label_edit = QLineEdit()
        self.work_label_edit.setPlaceholderText("예: 고객사명, 사이트 — output/os_upgrade/날짜_라벨/ 폴더명")
        meta_form.addRow("작업 라벨", self.work_label_edit)
        self.target_version_combo = QComboBox()
        configure_form_combobox(self.target_version_combo)
        for ent in load_k7727_versions():
            self.target_version_combo.addItem(ent.label, ent.version)
        if self.target_version_combo.count():
            self.target_version_combo.setCurrentIndex(0)
        meta_form.addRow("목표 버전", self.target_version_combo)
        ver_hint = QLabel(
            "Check List: 작업 전만 License/Service Check Date 비교 · 작업 후는 생략"
        )
        ver_hint.setWordWrap(True)
        ver_hint.setProperty("role", "muted")
        work_layout.addLayout(meta_form)
        work_layout.addWidget(ver_hint)

        self.pre_work_ucs_backup_cb = NcurityCheckBox("사전 작업 시 UCS 백업 수행")
        self.pre_work_ucs_backup_cb.setChecked(True)
        self.pre_work_ucs_backup_cb.setToolTip(
            "체크 해제 시 Session·Linux·f5mku는 실행하고 UCS(stagger)만 생략합니다."
        )
        work_layout.addWidget(self.pre_work_ucs_backup_cb)

        steps_hint = QLabel("단계별 실행 · Report (실행 전에는 비활성)")
        steps_hint.setProperty("role", "muted")
        work_layout.addWidget(steps_hint)

        steps_row = QHBoxLayout()
        steps_row.setSpacing(10)
        for step in WORK_STEPS:
            card = QFrame()
            mark_step_card(card)
            col = QVBoxLayout(card)
            col.setContentsMargins(12, 12, 12, 12)
            col.setSpacing(8)

            title_lbl = QLabel(f"{step.number}. {step.title}")
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_lbl.setProperty("role", "stepTitle")
            col.addWidget(title_lbl)

            run_btn = QPushButton("실행")
            run_btn.setMinimumHeight(_BTN_MIN_H)
            mark_primary_button(run_btn)
            run_btn.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            run_btn.setEnabled(False)
            col.addWidget(run_btn)
            self._run_buttons[step.key] = run_btn

            report_btn = QPushButton("Report")
            report_btn.setMinimumHeight(_BTN_MIN_H)
            mark_secondary_button(report_btn)
            report_btn.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            report_btn.setEnabled(False)
            report_btn.setToolTip("해당 단계 「실행」 후 활성화됩니다.")
            col.addWidget(report_btn)
            self._report_buttons[step.key] = report_btn

            steps_row.addWidget(card, stretch=1)

        work_layout.addLayout(steps_row)

        self.overview_progress = QProgressBar()
        self.overview_progress.setVisible(False)
        self.overview_progress.setFormat("%p% — %v")
        work_layout.addWidget(self.overview_progress)

        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        self.progress_label.setProperty("role", "muted")
        work_layout.addWidget(self.progress_label)

        self.summary_edit = QTextEdit()
        self.summary_edit.setReadOnly(True)
        self.summary_edit.setPlaceholderText("단계 「실행」 후 요약(✓/✗)이 표시됩니다.")
        self.summary_edit.setMinimumHeight(120)
        self.summary_edit.setMaximumHeight(200)
        work_layout.addWidget(self.summary_edit)

        footer_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("작업 폴더 열기")
        self.open_folder_btn.setMinimumHeight(_BTN_MIN_H)
        footer_row.addWidget(self.open_folder_btn)
        footer_row.addStretch()
        work_layout.addLayout(footer_row)

        self.report_path_label = QLabel("저장 위치: (작업 실행 후 표시)")
        self.report_path_label.setWordWrap(True)
        self.report_path_label.setProperty("role", "muted")
        work_layout.addWidget(self.report_path_label)

        device_layout.addWidget(work_box)
        self.mode_stack.addWidget(device_page)

        # --- UCS 모드 ---
        ucs_page = QWidget()
        ucs_page_layout = QVBoxLayout(ucs_page)
        ucs_page_layout.setContentsMargins(0, 0, 0, 0)
        ucs_page_layout.setSpacing(12)

        ucs_box = QGroupBox("UCS 백업 파일")
        ucs_layout = QVBoxLayout(ucs_box)
        ucs_hint = QLabel(
            "고객사 .ucs 파일을 추가하세요. UCS 안의 config(.conf)와 "
            "용량이 큰 경우의 .im(gzip) 설정을 자동으로 읽어 점검합니다. "
            "목록에는 Hostname만 표시됩니다."
        )
        ucs_hint.setWordWrap(True)
        ucs_hint.setProperty("role", "muted")
        ucs_layout.addWidget(ucs_hint)

        ucs_meta = QFormLayout()
        self.ucs_work_label_edit = QLineEdit()
        self.ucs_work_label_edit.setPlaceholderText(
            "예: 고객사명 — output/os_upgrade_check/ 폴더명"
        )
        ucs_meta.addRow("작업 라벨", self.ucs_work_label_edit)
        self.ucs_target_version_combo = QComboBox()
        configure_form_combobox(self.ucs_target_version_combo)
        for ent in load_k7727_versions():
            self.ucs_target_version_combo.addItem(ent.label, ent.version)
        if self.ucs_target_version_combo.count():
            self.ucs_target_version_combo.setCurrentIndex(0)
        ucs_meta.addRow("목표 버전", self.ucs_target_version_combo)
        ucs_layout.addLayout(ucs_meta)

        self.ucs_list = QListWidget()
        self.ucs_list.setMinimumHeight(120)
        self.ucs_list.setMaximumHeight(220)
        self.ucs_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ucs_list.setToolTip("Hostname (UCS config 기준)")
        ucs_layout.addWidget(self.ucs_list)

        ucs_file_row = QHBoxLayout()
        self.ucs_add_btn = QPushButton("UCS 추가…")
        self.ucs_remove_btn = QPushButton("선택 제거")
        self.ucs_clear_btn = QPushButton("전체 지우기")
        ucs_file_row.addWidget(self.ucs_add_btn)
        ucs_file_row.addWidget(self.ucs_remove_btn)
        ucs_file_row.addWidget(self.ucs_clear_btn)
        ucs_file_row.addStretch()
        ucs_layout.addLayout(ucs_file_row)

        ucs_btn_row = QHBoxLayout()
        self.ucs_extract_btn = QPushButton("UCS에서 정보 추출")
        mark_primary_button(self.ucs_extract_btn)
        self.ucs_report_btn = QPushButton("UCS Report")
        mark_secondary_button(self.ucs_report_btn)
        self.ucs_report_btn.setEnabled(False)
        self.ucs_open_btn = QPushButton("UCS 폴더 열기")
        ucs_btn_row.addWidget(self.ucs_extract_btn)
        ucs_btn_row.addWidget(self.ucs_report_btn)
        ucs_btn_row.addWidget(self.ucs_open_btn)
        ucs_btn_row.addStretch()
        ucs_layout.addLayout(ucs_btn_row)

        self.ucs_progress = QProgressBar()
        self.ucs_progress.setVisible(False)
        self.ucs_progress.setFormat("%p%")
        ucs_layout.addWidget(self.ucs_progress)

        self.ucs_status_label = QLabel("")
        self.ucs_status_label.setWordWrap(True)
        self.ucs_status_label.setProperty("role", "muted")
        ucs_layout.addWidget(self.ucs_status_label)

        self.ucs_summary_edit = QTextEdit()
        self.ucs_summary_edit.setReadOnly(True)
        self.ucs_summary_edit.setPlaceholderText("UCS 추출 후 요약이 표시됩니다.")
        self.ucs_summary_edit.setMinimumHeight(100)
        self.ucs_summary_edit.setMaximumHeight(160)
        ucs_layout.addWidget(self.ucs_summary_edit)

        ucs_page_layout.addWidget(ucs_box)
        ucs_page_layout.addStretch()
        self.mode_stack.addWidget(ucs_page)

        root.addWidget(self.mode_stack, stretch=1)

        self.mode_device_radio.toggled.connect(self._on_mode_changed)
        self.mode_ucs_radio.toggled.connect(self._on_mode_changed)

        self._run_buttons["device_overview"].clicked.connect(self._run_device_overview)
        self._run_buttons["pre_checklist"].clicked.connect(self._run_pre_checklist)
        self._run_buttons["pre_work"].clicked.connect(self._run_pre_work)
        self._run_buttons["post_checklist"].clicked.connect(self._run_post_checklist)
        for step in WORK_STEPS:
            self._report_buttons[step.key].clicked.connect(
                lambda _checked=False, k=step.key: self._open_report(k)
            )
        self.open_folder_btn.clicked.connect(self._open_work_folder)
        self.ucs_add_btn.clicked.connect(self._add_ucs_files)
        self.ucs_remove_btn.clicked.connect(self._remove_ucs_files)
        self.ucs_clear_btn.clicked.connect(self._clear_ucs_list)
        self.ucs_extract_btn.clicked.connect(self._run_ucs_extract)
        self.ucs_report_btn.clicked.connect(self._open_ucs_report)
        self.ucs_open_btn.clicked.connect(self._open_ucs_folder)

    def _on_mode_changed(self) -> None:
        if self.mode_ucs_radio.isChecked():
            self.mode_stack.setCurrentIndex(1)
        else:
            self.mode_stack.setCurrentIndex(0)

    def _step_def(self, key: str) -> WorkStepDef:
        for step in WORK_STEPS:
            if step.key == key:
                return step
        raise KeyError(key)

    def _reset_reports_ui(self) -> None:
        self._reports.clear()
        for btn in self._report_buttons.values():
            btn.setEnabled(False)

    def _mark_report_ready(self, key: str, html_path: Path) -> None:
        self._reports[key] = html_path
        self._report_buttons[key].setEnabled(True)

    def _work_label(self) -> str:
        return self.work_label_edit.text().strip() or "work"

    def _target_version_key(self) -> str:
        return str(self.target_version_combo.currentData() or "")

    def _ucs_target_version_key(self) -> str:
        return str(self.ucs_target_version_combo.currentData() or "")

    def _ensure_workspace(self) -> Path:
        if self._workspace is None:
            label = self._work_label()
            if not self.work_label_edit.text().strip():
                QMessageBox.information(
                    self,
                    "작업 라벨",
                    "작업 라벨이 비어 있어 기본값 'work'로 폴더를 만듭니다.",
                )
            self._workspace, self._folder_name = new_job_workspace(
                self.output_root, label
            )
            self.report_path_label.setText(
                f"저장 위치: output/os_upgrade/{self._folder_name}/"
            )
        return self._workspace

    def _open_work_folder(self) -> None:
        if self._workspace and self._workspace.is_dir():
            open_in_file_manager(self._workspace)
            return
        open_in_file_manager(self.output_root)

    def _on_connection_test_finished(self, ok: bool) -> None:
        self._workspace = None
        self._folder_name = None
        self._reset_reports_ui()
        for btn in self._run_buttons.values():
            btn.setEnabled(True)
        hint = "연결 테스트 완료" if ok else "연결 테스트 완료 (일부 실패)"
        self.report_path_label.setText("저장 위치: (첫 「실행」 시 폴더 생성)")
        self.summary_edit.setPlainText(
            f"{hint}\n"
            "작업 라벨 입력 후 각 단계 「실행」 — Report는 HTML 생성 후 활성화됩니다."
        )

    def _set_run_buttons_enabled(self, enabled: bool) -> None:
        for btn in self._run_buttons.values():
            btn.setEnabled(enabled)

    def _begin_work_ui(self, progress_text: str) -> None:
        self._set_run_buttons_enabled(False)
        self.overview_progress.setVisible(True)
        self.overview_progress.setRange(0, 100)
        self.overview_progress.setValue(0)
        self.progress_label.setText(progress_text)

    def _end_work_ui(self) -> None:
        self._set_run_buttons_enabled(True)
        self.overview_progress.setVisible(False)
        self.progress_label.setText("")

    def _run_device_overview(self) -> None:
        if self._overview_worker and self._overview_worker.isRunning():
            return
        try:
            targets, connections = self.connection.collect_targets_and_connections()
        except ValueError as exc:
            QMessageBox.warning(self, "장비 개요", str(exc))
            return
        if not targets:
            QMessageBox.warning(self, "장비 개요", "대상 장비가 없습니다.")
            return

        self._begin_work_ui("장비 개요 수집 준비…")
        self.summary_edit.setPlainText("수집 중…")

        self._overview_worker = DeviceOverviewWorker(targets, connections)
        self._overview_worker.progress.connect(self._on_work_progress)
        self._overview_worker.finished_ok.connect(self._on_overview_ok)
        self._overview_worker.failed.connect(self._on_overview_fail)
        self._overview_worker.finished.connect(self._end_work_ui)
        self._overview_worker.start()

    def _on_work_progress(self, percent: int, message: str) -> None:
        self.overview_progress.setValue(percent)
        self.progress_label.setText(message)

    def _format_summary(self, reports: list[DeviceOverviewReport]) -> str:
        lines: list[str] = []
        for report in reports:
            line = f"{report.device_label}: {report.summary_line()}"
            if report.errors:
                line += f"\n  오류: {'; '.join(report.errors[:2])}"
            lines.append(line)
        return "\n\n".join(lines)

    def _short_report_path(self, html_path: Path) -> str:
        try:
            return str(html_path.relative_to(self.project_root))
        except ValueError:
            return html_path.name

    def _on_overview_ok(self, reports: object) -> None:
        if not isinstance(reports, list):
            return
        typed = [r for r in reports if isinstance(r, DeviceOverviewReport)]
        self._last_overview_reports = typed

        ws = self._ensure_workspace()
        html_path = report_path(ws, "device_overview")
        write_overview_html(html_path, typed, title="장비 개요")
        self._mark_report_ready("device_overview", html_path)

        rel = self._short_report_path(html_path)
        self.report_path_label.setText(
            f"저장: output/os_upgrade/{self._folder_name}/ · 최근 {rel}"
        )
        self.summary_edit.setPlainText(
            f"[1. 장비 개요] 완료 — {len(typed)}대\n"
            f"이 열 「Report」로 HTML을 엽니다.\n\n"
            f"{self._format_summary(typed)}"
        )

    def _format_pre_summary(self, reports: list[PreChecklistReport]) -> str:
        lines: list[str] = []
        for report in reports:
            line = f"{report.device_label} ({report.target_version}): {report.summary_line()}"
            if report.license_check:
                line += f"\n  License: {report.license_check.verdict}"
            if report.linux_check and report.linux_check.crontab_custom_lines:
                line += f"\n  crontab: {report.linux_check.crontab_summary}"
                for cron_ln in report.linux_check.crontab_custom_lines[:5]:
                    line += f"\n    {cron_ln}"
            if report.errors:
                line += f"\n  오류: {'; '.join(report.errors[:2])}"
            lines.append(line)
        return "\n\n".join(lines)

    def _run_pre_checklist(self) -> None:
        if self._pre_checklist_worker and self._pre_checklist_worker.isRunning():
            return
        version_key = self._target_version_key()
        if not version_key:
            QMessageBox.warning(self, "작업 전 Check List", "목표 버전을 선택하세요.")
            return
        try:
            targets, connections = self.connection.collect_targets_and_connections()
        except ValueError as exc:
            QMessageBox.warning(self, "작업 전 Check List", str(exc))
            return
        if not targets:
            QMessageBox.warning(self, "작업 전 Check List", "대상 장비가 없습니다.")
            return

        self._begin_work_ui("작업 전 Check List 준비…")
        self.summary_edit.setPlainText(f"수집 중… (목표: {version_key})")

        self._pre_checklist_worker = PreChecklistWorker(
            targets, connections, version_key
        )
        self._pre_checklist_worker.progress.connect(self._on_work_progress)
        self._pre_checklist_worker.finished_ok.connect(self._on_pre_checklist_ok)
        self._pre_checklist_worker.failed.connect(self._on_pre_checklist_fail)
        self._pre_checklist_worker.finished.connect(self._end_work_ui)
        self._pre_checklist_worker.start()

    def _on_pre_checklist_ok(self, reports: object) -> None:
        if not isinstance(reports, list):
            return
        typed = [r for r in reports if isinstance(r, PreChecklistReport)]
        self._last_pre_reports = typed

        ws = self._ensure_workspace()
        html_path = report_path(ws, "pre_checklist")
        write_pre_checklist_html(html_path, typed)
        self._mark_report_ready("pre_checklist", html_path)

        rel = self._short_report_path(html_path)
        self.report_path_label.setText(
            f"저장: output/os_upgrade/{self._folder_name}/ · 최근 {rel}"
        )
        self.summary_edit.setPlainText(
            f"[2. 작업 전 Check List] 완료 — {len(typed)}대\n"
            f"저장: pre_checklist/\n\n"
            f"{self._format_pre_summary(typed)}"
        )

    def _on_pre_checklist_fail(self, message: str) -> None:
        self.summary_edit.setPlainText(f"실패: {message[:400]}")
        QMessageBox.warning(self, "작업 전 Check List", message[:500])

    def _format_pre_work_summary(self, reports: list[PreWorkReport]) -> str:
        lines: list[str] = []
        for report in reports:
            line = f"{report.device_label}: {report.summary_line()}"
            if report.errors:
                line += f"\n  오류: {'; '.join(report.errors[:2])}"
            lines.append(line)
        return "\n\n".join(lines)

    def _run_pre_work(self) -> None:
        if self._pre_work_worker and self._pre_work_worker.isRunning():
            return
        try:
            targets, connections = self.connection.collect_targets_and_connections()
        except ValueError as exc:
            QMessageBox.warning(self, "사전 작업", str(exc))
            return
        if not targets:
            QMessageBox.warning(self, "사전 작업", "대상 장비가 없습니다.")
            return

        ws = self._ensure_workspace()
        run_ucs = self.pre_work_ucs_backup_cb.isChecked()
        self._begin_work_ui("사전 작업 준비…")
        if run_ucs:
            status = "수집·백업 중… (UCS는 마지막에 stagger)"
        else:
            status = "수집·백업 중… (UCS 백업 생략)"
        self.summary_edit.setPlainText(status)

        self._pre_work_worker = PreWorkWorker(
            targets, connections, ws, run_ucs_backup=run_ucs
        )
        self._pre_work_worker.progress.connect(self._on_work_progress)
        self._pre_work_worker.finished_ok.connect(self._on_pre_work_ok)
        self._pre_work_worker.failed.connect(self._on_pre_work_fail)
        self._pre_work_worker.finished.connect(self._end_work_ui)
        self._pre_work_worker.start()

    def _on_pre_work_ok(self, reports: object) -> None:
        if not isinstance(reports, list):
            return
        typed = [r for r in reports if isinstance(r, PreWorkReport)]
        self._last_pre_work_reports = typed

        ws = self._ensure_workspace()
        html_path = report_path(ws, "pre_work")
        write_pre_work_html(html_path, typed)
        self._mark_report_ready("pre_work", html_path)

        rel = self._short_report_path(html_path)
        self.report_path_label.setText(
            f"저장: output/os_upgrade/{self._folder_name}/ · 최근 {rel}"
        )
        ucs_note = (
            "UCS: ucs_backup.log"
            if any(r.ucs_log_rel for r in typed)
            else "UCS: 생략 (미선택)"
        )
        self.summary_edit.setPlainText(
            f"[3. 사전 작업] 완료 — {len(typed)}대\n"
            f"백업: backups/<장비>/ · {ucs_note}\n\n"
            f"{self._format_pre_work_summary(typed)}"
        )

    def _on_pre_work_fail(self, message: str) -> None:
        self.summary_edit.setPlainText(f"실패: {message[:400]}")
        QMessageBox.warning(self, "사전 작업", message[:500])

    def _run_post_checklist(self) -> None:
        if self._post_checklist_worker and self._post_checklist_worker.isRunning():
            return
        version_key = self._target_version_key()
        if not version_key:
            QMessageBox.warning(self, "작업 후 Check List", "목표 버전을 선택하세요.")
            return
        try:
            targets, connections = self.connection.collect_targets_and_connections()
        except ValueError as exc:
            QMessageBox.warning(self, "작업 후 Check List", str(exc))
            return
        if not targets:
            QMessageBox.warning(self, "작업 후 Check List", "대상 장비가 없습니다.")
            return

        self._begin_work_ui("작업 후 Check List 준비…")
        self.summary_edit.setPlainText(f"수집 중… (목표: {version_key})")

        self._post_checklist_worker = PreChecklistWorker(
            targets,
            connections,
            version_key,
            phase="post",
        )
        self._post_checklist_worker.progress.connect(self._on_work_progress)
        self._post_checklist_worker.finished_ok.connect(self._on_post_checklist_ok)
        self._post_checklist_worker.failed.connect(self._on_post_checklist_fail)
        self._post_checklist_worker.finished.connect(self._end_work_ui)
        self._post_checklist_worker.start()

    def _on_post_checklist_ok(self, reports: object) -> None:
        if not isinstance(reports, list):
            return
        typed = [r for r in reports if isinstance(r, PreChecklistReport)]
        self._last_post_reports = typed

        ws = self._ensure_workspace()
        html_path = report_path(ws, "post_checklist")
        write_pre_checklist_html(
            html_path,
            typed,
            title="작업 후 Check List",
            include_license_check=False,
        )
        self._mark_report_ready("post_checklist", html_path)

        rel = self._short_report_path(html_path)
        self.report_path_label.setText(
            f"저장: output/os_upgrade/{self._folder_name}/ · 최근 {rel}"
        )
        self.summary_edit.setPlainText(
            f"[4. 작업 후 Check List] 완료 — {len(typed)}대\n"
            f"저장: post_checklist/\n\n"
            f"{self._format_pre_summary(typed)}"
        )

    def _on_post_checklist_fail(self, message: str) -> None:
        self.summary_edit.setPlainText(f"실패: {message[:400]}")
        QMessageBox.warning(self, "작업 후 Check List", message[:500])

    def _on_overview_fail(self, message: str) -> None:
        self.summary_edit.setPlainText(f"실패: {message[:400]}")
        QMessageBox.warning(self, "장비 개요", message[:500])

    def _open_report(self, key: str) -> None:
        step = self._step_def(key)
        path = self._reports.get(key)
        if path and path.is_file():
            dlg = ReportWindow(path, self)
            dlg.setWindowTitle(step.report_window_title)
            dlg.exec()
        else:
            QMessageBox.information(
                self,
                "Report",
                f"먼저 「{step.number}. {step.title}」을 실행하세요.",
            )

    def _rel_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.project_root))
        except ValueError:
            return str(path)

    # --- UCS (오프라인) ---

    _UCS_ROLE_PATH = Qt.ItemDataRole.UserRole
    _UCS_ROLE_HOSTNAME = Qt.ItemDataRole.UserRole + 1

    def _ucs_paths_on_list(self) -> list[Path]:
        paths: list[Path] = []
        for i in range(self.ucs_list.count()):
            raw = self.ucs_list.item(i).data(self._UCS_ROLE_PATH)
            if raw:
                paths.append(Path(str(raw)))
        return paths

    def _ucs_hostnames_on_list(self) -> list[str]:
        names: list[str] = []
        for i in range(self.ucs_list.count()):
            item = self.ucs_list.item(i)
            host = str(item.data(self._UCS_ROLE_HOSTNAME) or "").strip()
            if not host:
                host = Path(str(item.data(self._UCS_ROLE_PATH) or "")).stem
            names.append(host)
        return names

    @staticmethod
    def _list_display_hostname(hostname: str, path: Path) -> str:
        host = hostname.strip()
        if host:
            return host
        return path.stem or path.name

    def _append_ucs_path(self, path: Path, *, existing: set[str]) -> bool:
        if not path.is_file() or path.suffix.lower() != ".ucs":
            return False
        key = str(path.resolve())
        if key in existing:
            return False
        hostname = peek_ucs_hostname(path)
        item = QListWidgetItem(self._list_display_hostname(hostname, path))
        item.setData(self._UCS_ROLE_PATH, key)
        item.setData(self._UCS_ROLE_HOSTNAME, hostname.strip())
        item.setToolTip(key)
        self.ucs_list.addItem(item)
        existing.add(key)
        return True

    def _add_ucs_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "UCS 백업 파일 선택 (복수 선택 가능)",
            "",
            "F5 UCS (*.ucs);;All files (*.*)",
        )
        if not paths:
            return
        existing = {str(p) for p in self._ucs_paths_on_list()}
        added = sum(
            1 for raw in paths if self._append_ucs_path(Path(raw), existing=existing)
        )
        if not added and paths:
            QMessageBox.information(self, "UCS", "이미 목록에 있는 .ucs 파일입니다.")

    def _remove_ucs_files(self) -> None:
        for item in self.ucs_list.selectedItems():
            row = self.ucs_list.row(item)
            self.ucs_list.takeItem(row)

    def _clear_ucs_list(self) -> None:
        self.ucs_list.clear()

    def _run_ucs_extract(self) -> None:
        if self._ucs_worker and self._ucs_worker.isRunning():
            return
        paths = self._ucs_paths_on_list()
        if not paths:
            QMessageBox.warning(self, "UCS", "UCS 파일을 추가하세요.")
            return
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            QMessageBox.warning(
                self,
                "UCS",
                "다음 UCS 파일을 찾을 수 없습니다:\n" + "\n".join(missing[:5]),
            )
            return

        labels = self._ucs_hostnames_on_list()
        site = self.ucs_work_label_edit.text().strip() or "ucs-work"
        target_version = self._ucs_target_version_key()
        self.ucs_extract_btn.setEnabled(False)
        self.ucs_status_label.setText(f"UCS 분석 중… ({len(paths)}개)")
        self.ucs_progress.setVisible(True)
        self.ucs_progress.setRange(0, 100)
        self.ucs_progress.setValue(0)

        self._ucs_worker = UcsExtractWorker(
            ucs_paths=paths,
            output_root=self.ucs_output_root,
            site_name=site,
            labels=labels,
            auto_unit_labels=False,
            target_version=target_version,
        )
        self._ucs_worker.progress.connect(self._on_ucs_progress)
        self._ucs_worker.finished_ok.connect(self._on_ucs_ok)
        self._ucs_worker.failed.connect(self._on_ucs_fail)
        self._ucs_worker.finished.connect(self._ucs_finished)
        self._ucs_worker.start()

    def _on_ucs_progress(self, percent: int, message: str) -> None:
        self.ucs_progress.setValue(percent)
        self.ucs_status_label.setText(message)

    def _ucs_finished(self) -> None:
        self.ucs_progress.setVisible(False)
        self.ucs_extract_btn.setEnabled(True)

    def _on_ucs_ok(self, result: object, workspace_str: str) -> None:
        if not isinstance(result, UcsBatchExtractResult):
            return
        ws = Path(workspace_str)
        self._last_ucs_workspace = ws
        html = ws / "report.html"
        self._last_ucs_report = html if html.is_file() else None
        self.ucs_report_btn.setEnabled(self._last_ucs_report is not None)
        n = len(result.units)
        self.ucs_status_label.setText(f"완료 — {n}대 · {self._rel_path(ws)}")
        lines = result.summary_lines()
        if result.failures:
            lines.append("실패:")
            for fail in result.failures:
                lines.append(f"  · {fail.get('file')}: {fail.get('message', '')[:120]}")
        self.ucs_summary_edit.setPlainText("\n".join(lines))
        for i, unit in enumerate(result.units):
            if i >= self.ucs_list.count():
                break
            item = self.ucs_list.item(i)
            if unit.hostname:
                item.setText(unit.hostname)
                item.setData(self._UCS_ROLE_HOSTNAME, unit.hostname)

    def _on_ucs_fail(self, message: str) -> None:
        self.ucs_status_label.setText("실패")
        self.ucs_summary_edit.setPlainText(f"실패: {message[:500]}")
        QMessageBox.warning(self, "UCS 추출", message[:500])

    def _open_ucs_report(self) -> None:
        if self._last_ucs_report and self._last_ucs_report.is_file():
            ReportWindow(self._last_ucs_report, self).exec()
        else:
            QMessageBox.information(self, "UCS Report", "먼저 UCS에서 정보 추출을 실행하세요.")

    def _open_ucs_folder(self) -> None:
        target = (
            self._last_ucs_workspace
            if self._last_ucs_workspace and self._last_ucs_workspace.is_dir()
            else self.ucs_output_root
        )
        open_in_file_manager(target)

    def closeEvent(self, event) -> None:  # noqa: N802
        for worker in (
            self._overview_worker,
            self._pre_checklist_worker,
            self._pre_work_worker,
            self._post_checklist_worker,
            self._ucs_worker,
        ):
            if worker and worker.isRunning():
                worker.wait(8000)
        super().closeEvent(event)
