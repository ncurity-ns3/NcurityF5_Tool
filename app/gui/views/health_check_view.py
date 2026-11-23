from __future__ import annotations

import getpass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.models import PlatformKind
from app.gui.app_paths import local_data_dir
from app.gui.folder_utils import module_output_root, open_in_file_manager
from app.gui.theme import (
    mark_mode_choice_radio,
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
)
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.widgets.ncurity_radio import NcurityRadioButton
from app.gui.widgets.report_window import ReportWindow
from app.gui.workers.health_check_worker import HealthCheckWorker
from app.gui.workers.qkview_health_worker import QkviewHealthWorker
from app.gui.workers.ucs_backup_worker import UcsBackupWorker
from app.modules.health_check.findings import summarize_job_dir


class HealthCheckView(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.output_root = module_output_root(project_root, "health_check")
        self._last_job_dir: Path | None = None
        self.data_dir = local_data_dir()
        self._worker: HealthCheckWorker | None = None
        self._ucs_worker: UcsBackupWorker | None = None
        self._qk_worker: QkviewHealthWorker | None = None
        self._qk_paths: list[Path] = []
        self._last_run_targets = []
        self._last_run_connections = []
        self._last_run_results: list = []
        self._last_report_html: Path | None = None
        self._last_run_device_count = 0
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

        title = QLabel("정기 점검")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel(
            "점검 방식을 선택하세요. 장비 접속은 Test Connection 후 실행하고, "
            "QKView는 파일만으로 보고서를 만듭니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        mode_box = QGroupBox("점검 방식")
        mode_layout = QHBoxLayout(mode_box)
        mode_layout.setSpacing(28)
        self.mode_device_radio = NcurityRadioButton("1. 실제 장비 접속 후 점검하기")
        self.mode_qkview_radio = NcurityRadioButton("2. QKView로 점검하기")
        self.mode_device_radio.setChecked(True)
        mark_mode_choice_radio(self.mode_device_radio)
        mark_mode_choice_radio(self.mode_qkview_radio)
        mode_layout.addWidget(self.mode_device_radio)
        mode_layout.addWidget(self.mode_qkview_radio)
        mode_layout.addStretch()
        root.addWidget(mode_box)

        self.mode_stack = QStackedWidget()
        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(12)

        self.status_label = QLabel("Ready")

        self.connection = DeviceConnectionPanel(self.data_dir)
        self.connection.status_message.connect(self.status_label.setText)
        device_layout.addWidget(self.connection)

        meta_box = QGroupBox("점검 · 현장 정보")
        meta_form = QFormLayout(meta_box)
        self.site_edit = QLineEdit("lab-site")
        self.period_edit = QLineEdit()
        self.notes_edit = QLineEdit()
        self.chk_common = NcurityCheckBox("common (정기점검)")
        self.chk_common.setChecked(True)
        self.chk_common.setToolTip("Uptime, 전원/온도, NTP, Disk, CPU/Mem, SSL, UCS 등")
        self.chk_ucs_backup = NcurityCheckBox("점검 시 UCS 백업 수행")
        self.chk_ucs_backup.setChecked(True)
        self.chk_ucs_backup.setToolTip(
            "점검·리포트 후 UCS 백업(QThread). 장비 시작 1초 간격(staggered), "
            "tmsh save. ucs_backup.log 참고."
        )
        self.chk_ltm = NcurityCheckBox("LTM")
        self.chk_ltm.setChecked(False)
        self.chk_ltm.setToolTip("pool / virtual / node REST 조회")
        self.chk_apm = NcurityCheckBox("APM")
        self.chk_apm.setChecked(False)
        self.chk_apm.setToolTip("access profile, session, license REST 조회")
        self.chk_awaf = NcurityCheckBox("AWAF")
        self.chk_awaf.setChecked(False)
        self.chk_awaf.setToolTip("ASM policy, signature-update REST 조회")
        checks = QHBoxLayout()
        checks.addWidget(self.chk_common)
        checks.addWidget(self.chk_ucs_backup)
        checks.addWidget(self.chk_ltm)
        checks.addWidget(self.chk_apm)
        checks.addWidget(self.chk_awaf)
        meta_form.addRow("사이트명", self.site_edit)
        meta_form.addRow("점검 기간", self.period_edit)
        meta_form.addRow("비고", self.notes_edit)
        meta_form.addRow("항목", checks)
        device_layout.addWidget(meta_box)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("정기 점검 실행")
        mark_primary_button(self.run_btn)
        self.open_report_btn = QPushButton("Open Report Window")
        mark_secondary_button(self.open_report_btn)
        self.open_report_btn.setEnabled(False)
        self.open_folder_btn = QPushButton("폴더 열기")
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.open_report_btn)
        run_row.addWidget(self.open_folder_btn)
        run_row.addStretch()
        device_layout.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        device_layout.addWidget(self.progress)
        device_layout.addWidget(self.status_label)

        summary_box = QGroupBox("점검 결과 요약")
        summary_layout = QVBoxLayout(summary_box)
        self.summary_status = QLabel("—")
        self.summary_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_status.setStyleSheet("font-size: 22px; font-weight: bold; padding: 8px;")
        self.summary_count = QLabel("정기 점검 실행 후 표시됩니다.")
        self.summary_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_count.setWordWrap(True)
        self.summary_hint = QLabel("상세 내용은 Open Report Window에서 확인하세요.")
        self.summary_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_hint.setProperty("role", "muted")
        summary_layout.addWidget(self.summary_status)
        summary_layout.addWidget(self.summary_count)
        summary_layout.addWidget(self.summary_hint)
        device_layout.addWidget(summary_box)
        self.mode_stack.addWidget(device_page)

        qk_page = QWidget()
        qk_layout = QVBoxLayout(qk_page)
        qk_layout.setContentsMargins(0, 0, 0, 0)
        qk_box = QGroupBox("QKView 파일")
        qk_box_layout = QVBoxLayout(qk_box)
        qk_hint = QLabel(
            "QKView를 여러 개 선택하거나 이 화면에 놓으세요. "
            "상태점검과 30일 성능 그래프를 보고서로 만듭니다."
        )
        qk_hint.setWordWrap(True)
        qk_hint.setProperty("role", "muted")
        qk_box_layout.addWidget(qk_hint)
        self.qk_empty = QLabel("선택된 파일 없음")
        self.qk_empty.setProperty("role", "muted")
        qk_box_layout.addWidget(self.qk_empty)
        self.qk_files_box = QWidget()
        self.qk_files_layout = QVBoxLayout(self.qk_files_box)
        self.qk_files_layout.setContentsMargins(0, 4, 0, 4)
        self.qk_files_layout.setSpacing(4)
        qk_box_layout.addWidget(self.qk_files_box)
        file_row = QHBoxLayout()
        self.qk_pick_btn = QPushButton("QKView 선택…")
        self.qk_select_all_btn = QPushButton("전체 선택")
        self.qk_clear_btn = QPushButton("전체 해제")
        self.qk_remove_btn = QPushButton("선택 삭제")
        file_row.addWidget(self.qk_pick_btn)
        file_row.addWidget(self.qk_select_all_btn)
        file_row.addWidget(self.qk_clear_btn)
        file_row.addWidget(self.qk_remove_btn)
        file_row.addStretch()
        qk_box_layout.addLayout(file_row)
        qk_run = QHBoxLayout()
        self.qk_run_btn = QPushButton("QKView 점검")
        mark_primary_button(self.qk_run_btn)
        self.qk_report_btn = QPushButton("Open Report Window")
        mark_secondary_button(self.qk_report_btn)
        self.qk_report_btn.setEnabled(False)
        self.qk_folder_btn = QPushButton("폴더 열기")
        qk_run.addWidget(self.qk_run_btn)
        qk_run.addWidget(self.qk_report_btn)
        qk_run.addWidget(self.qk_folder_btn)
        qk_run.addStretch()
        qk_box_layout.addLayout(qk_run)
        self.qk_progress = QProgressBar()
        self.qk_progress.setRange(0, 100)
        self.qk_progress.setVisible(False)
        qk_box_layout.addWidget(self.qk_progress)
        self.qk_status_label = QLabel("Ready")
        self.qk_status_label.setWordWrap(True)
        self.qk_status_label.setProperty("role", "muted")
        qk_box_layout.addWidget(self.qk_status_label)
        qk_layout.addWidget(qk_box)
        qk_layout.addStretch()
        self.mode_stack.addWidget(qk_page)
        root.addWidget(self.mode_stack)

        self.setAcceptDrops(True)
        self.run_btn.clicked.connect(self._run_health_check)
        self.open_report_btn.clicked.connect(self._open_report_window)
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        self.mode_device_radio.toggled.connect(self._on_mode_changed)
        self.qk_pick_btn.clicked.connect(self._pick_qkview)
        self.qk_select_all_btn.clicked.connect(lambda: self._set_qk_checks(True))
        self.qk_clear_btn.clicked.connect(lambda: self._set_qk_checks(False))
        self.qk_remove_btn.clicked.connect(self._remove_checked_qkviews)
        self.qk_run_btn.clicked.connect(self._run_qkview)
        self.qk_report_btn.clicked.connect(self._open_report_window)
        self.qk_folder_btn.clicked.connect(self._open_output_folder)

    def _on_mode_changed(self) -> None:
        self.mode_stack.setCurrentIndex(1 if self.mode_qkview_radio.isChecked() else 0)

    def _remember_report(self, html: Path | None, job_dir: Path | None) -> None:
        self._last_report_html = html
        if job_dir is not None:
            self._last_job_dir = job_dir
        ready = html is not None and html.is_file()
        self.open_report_btn.setEnabled(ready)
        self.qk_report_btn.setEnabled(ready)

    def _pick_qkview(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(self, "QKView 선택", "", "QKView (*.qkview)")
        if chosen:
            self._add_qkviews([Path(path) for path in chosen])

    def _add_qkviews(self, paths: list[Path]) -> None:
        candidates = [
            path for path in paths if path.suffix.lower() == ".qkview" and path.is_file()
        ]
        if paths and not candidates:
            QMessageBox.warning(self, "QKView", "QKView 파일만 올릴 수 있습니다.")
            return
        seen = {path.resolve() for path in self._qk_paths}
        added = False
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            self._qk_paths.append(resolved)
            added = True
        if added:
            self._qk_paths.sort(key=lambda item: item.name.casefold())
            self._rebuild_qk_rows()

    def _qk_boxes(self) -> list[NcurityCheckBox]:
        return self.qk_files_box.findChildren(NcurityCheckBox)

    def _set_qk_checks(self, checked: bool) -> None:
        for box in self._qk_boxes():
            box.setChecked(checked)

    def _remove_checked_qkviews(self) -> None:
        chosen = {
            Path(str(box.property("qkPath")))
            for box in self._qk_boxes()
            if box.isChecked() and box.property("qkPath")
        }
        if not chosen:
            QMessageBox.information(self, "QKView", "삭제할 파일을 선택하세요.")
            return
        self._qk_paths = [item for item in self._qk_paths if item not in chosen]
        self._rebuild_qk_rows()

    def _rebuild_qk_rows(self) -> None:
        while self.qk_files_layout.count():
            item = self.qk_files_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.qk_empty.setVisible(not self._qk_paths)
        for path in self._qk_paths:
            box = NcurityCheckBox(path.name)
            box.setToolTip(str(path))
            box.setProperty("qkPath", str(path))
            self.qk_files_layout.addWidget(box)

    def _set_qk_busy(self, busy: bool) -> None:
        for button in (
            self.qk_run_btn,
            self.qk_pick_btn,
            self.qk_select_all_btn,
            self.qk_clear_btn,
            self.qk_remove_btn,
        ):
            button.setEnabled(not busy)
        self.qk_files_box.setEnabled(not busy)

    def _qk_drop_ok(self, event) -> bool:
        return bool(
            self.mode_qkview_radio.isChecked()
            and event.mimeData().hasUrls()
            and (self._qk_worker is None or not self._qk_worker.isRunning())
        )

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._qk_drop_ok(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._qk_drop_ok(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not self._qk_drop_ok(event):
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.toLocalFile()]
        self._add_qkviews(paths)
        if any(path.suffix.lower() == ".qkview" for path in paths):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _run_qkview(self) -> None:
        if self._qk_worker is not None and self._qk_worker.isRunning():
            return
        ready = [
            path
            for path in self._qk_paths
            if path.is_file() and path.suffix.lower() == ".qkview"
        ]
        if not ready:
            QMessageBox.warning(self, "QKView", "QKView 파일을 선택하세요.")
            return
        self._set_qk_busy(True)
        self.qk_progress.setVisible(True)
        self.qk_progress.setValue(0)
        count = len(ready)
        self.qk_status_label.setText(f"{count}개 QKView 분석 중…")
        self._qk_worker = QkviewHealthWorker(ready, self.output_root)
        self._qk_worker.progressed.connect(self._on_qkview_progress)
        self._qk_worker.finished_ok.connect(self._on_qkview_ok)
        self._qk_worker.failed.connect(self._on_qkview_fail)
        self._qk_worker.start()

    def _on_qkview_progress(self, percent: int, message: str) -> None:
        self.qk_progress.setValue(max(0, min(100, percent)))
        self.qk_status_label.setText(message)

    def _on_qkview_ok(self, html_path: str, job_dir: str, summary: str) -> None:
        html = Path(html_path)
        folder = Path(job_dir)
        self._remember_report(html, folder)
        self.qk_progress.setValue(100)
        self.qk_progress.setVisible(False)
        self._set_qk_busy(False)
        self.qk_status_label.setText(summary)
        bad = "확인 필요 0건" in summary
        self.summary_status.setText("Healthy" if bad else "Unhealthy")
        color = "#1a7f37" if bad else "#b42318"
        self.summary_status.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {color}; padding: 8px;"
        )
        self.summary_count.setText(summary)

    def _on_qkview_fail(self, message: str) -> None:
        self.qk_progress.setVisible(False)
        self._set_qk_busy(False)
        self.qk_status_label.setText("QKView 점검 실패")
        QMessageBox.warning(self, "QKView", message[:500])

    def _categories(self) -> list[str]:
        cats: list[str] = []
        if self.chk_common.isChecked():
            cats.append("common")
        if self.chk_ltm.isChecked():
            cats.append("ltm")
        if self.chk_apm.isChecked():
            cats.append("apm")
        if self.chk_awaf.isChecked():
            cats.append("awaf")
        return cats

    def _update_summary_panel(self, job_dir: Path) -> None:
        import json

        healthy, count, _ = summarize_job_dir(job_dir)
        device_n = self._last_run_device_count
        raw_path = job_dir / "raw_collection.json"
        if raw_path.is_file():
            try:
                device_n = len(json.loads(raw_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        if healthy:
            self.summary_status.setText("Healthy")
            self.summary_status.setStyleSheet(
                "font-size: 22px; font-weight: bold; color: #1a7f37; padding: 8px;"
            )
            self.summary_count.setText(f"점검 장비: {device_n}대 · Unhealthy 사유: 0건")
        else:
            self.summary_status.setText("Unhealthy")
            self.summary_status.setStyleSheet(
                "font-size: 22px; font-weight: bold; color: #b42318; padding: 8px;"
            )
            self.summary_count.setText(
                f"점검 장비: {device_n}대 · Unhealthy 사유: {count}건"
            )

    def _run_health_check(self) -> None:
        try:
            targets, connections = self.connection.collect_targets_and_connections()
        except ValueError as exc:
            QMessageBox.warning(self, "Run", str(exc))
            return
        if not targets:
            QMessageBox.warning(self, "Run", "대상 장비가 없습니다.")
            return
        if not self._categories():
            QMessageBox.warning(
                self, "Run", "점검 항목(common / LTM / APM / AWAF)을 하나 이상 선택하세요."
            )
            return
        for t in targets:
            if t.platform == PlatformKind.rseries and not t.f5os_host.strip() and not t.host.strip():
                QMessageBox.warning(
                    self, "Run", f"{t.label}: rSeries는 F5OS 또는 TMOS MGMT IP가 필요합니다."
                )
                return

        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.status_label.setText("Running…")

        self._last_run_device_count = len(targets)
        self._last_run_targets = targets
        self._last_run_connections = list(connections or [])
        self._last_run_results = []
        self._worker = HealthCheckWorker(
            project_root=self.project_root,
            output_root=self.output_root,
            data_dir=self.data_dir,
            site_name=self.site_edit.text(),
            period=self.period_edit.text(),
            notes=self.notes_edit.text(),
            targets=targets,
            categories=self._categories(),
            perform_ucs_backup=self.chk_ucs_backup.isChecked(),
            connections=connections,
            mock_fixtures=None,
            operator=getpass.getuser(),
        )
        self._worker.finished_ok.connect(self._on_job_ok)
        self._worker.failed.connect(self._on_job_fail)
        self._worker.start()

    def _on_job_ok(self, job: object, out_dir: str) -> None:
        job_dir = Path(out_dir)
        self._last_job_dir = job_dir
        html = job_dir / "report.html"
        self._remember_report(html if html.is_file() else None, job_dir)
        self._update_summary_panel(job_dir)
        self._load_run_results(job_dir)
        if self._should_run_ucs_backup():
            self._start_ucs_backup_worker(job_dir, getattr(job, "job_id", ""))
        else:
            self._finish_run_ui(job, job_dir)

    def _should_run_ucs_backup(self) -> bool:
        return self.chk_ucs_backup.isChecked() and "common" in self._categories()

    def _load_run_results(self, job_dir: Path) -> None:
        import json

        raw_path = job_dir / "raw_collection.json"
        self._last_run_results = []
        if raw_path.is_file():
            try:
                data = json.loads(raw_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._last_run_results = data
            except json.JSONDecodeError:
                pass

    def _start_ucs_backup_worker(self, job_dir: Path, job_id: str) -> None:
        from app.modules.health_check.ucs_backup import build_ucs_backup_jobs

        log_path = str(job_dir / "ucs_backup.log")
        conn_by_label = {c.target.label: c for c in self._last_run_connections}
        use_index = len(self._last_run_connections) == len(self._last_run_targets)
        jobs = build_ucs_backup_jobs(
            targets=self._last_run_targets,
            results=self._last_run_results,
            connections=self._last_run_connections,
            conn_by_label=conn_by_label,
            use_index=use_index,
            mock_fixtures=None,
        )
        if not jobs:
            self.status_label.setText("UCS: 대상 없음 (TMOS 연결 확인)")
            self._finish_run_ui_simple(job_id, job_dir)
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.status_label.setText(f"UCS 백업 시작 ({len(jobs)}대)…")
        self._ucs_worker = UcsBackupWorker(jobs, log_path)
        self._ucs_worker.progress.connect(self.status_label.setText)
        self._ucs_worker.finished_all.connect(
            lambda: self._on_ucs_backup_done(job_id, job_dir)
        )
        self._ucs_worker.failed.connect(self._on_ucs_backup_fail)
        self._ucs_worker.start()

    def _on_ucs_backup_done(self, job_id: str, job_dir: Path) -> None:
        self._finish_run_ui_simple(job_id, job_dir)
        self.status_label.setText(
            f"Completed — 점검+UCS 완료 ({self._last_run_device_count}대) Job {job_id}"
        )

    def _on_ucs_backup_fail(self, message: str) -> None:
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.status_label.setText("UCS 백업 오류")
        QMessageBox.warning(self, "UCS Backup", message[:500])

    def _finish_run_ui(self, job: object, job_dir: Path) -> None:
        self._finish_run_ui_simple(getattr(job, "job_id", ""), job_dir)

    def _finish_run_ui_simple(self, job_id: str, job_dir: Path) -> None:
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        if "UCS" not in self.status_label.text():
            self.status_label.setText(
                f"Completed — {self._last_run_device_count} device(s), Job {job_id}"
            )

    def _on_job_fail(self, message: str) -> None:
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.status_label.setText("Failed")
        self.summary_status.setText("Unhealthy")
        self.summary_status.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #b42318; padding: 8px;"
        )
        self.summary_count.setText("Unhealthy 사유: (job failed)")
        QMessageBox.critical(self, "정기 점검", message)

    def _open_report_window(self) -> None:
        if self._last_report_html and self._last_report_html.is_file():
            ReportWindow(self._last_report_html, self).exec()
        else:
            QMessageBox.information(self, "Report", "먼저 정기 점검을 실행하세요.")

    def _open_output_folder(self) -> None:
        target = self._last_job_dir if self._last_job_dir and self._last_job_dir.is_dir() else self.output_root
        open_in_file_manager(target)
