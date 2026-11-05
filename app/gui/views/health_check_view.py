from __future__ import annotations

import getpass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.models import PlatformKind
from app.gui.app_paths import local_data_dir
from app.gui.folder_utils import module_output_root, open_in_file_manager
from app.gui.theme import mark_page_subtitle, mark_page_title, mark_primary_button, mark_secondary_button
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.widgets.report_window import ReportWindow
from app.gui.workers.health_check_worker import HealthCheckWorker
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
        subtitle = QLabel("Test Connection 후 점검 항목을 선택하고 실행하세요.")
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        self.status_label = QLabel("Ready")

        self.connection = DeviceConnectionPanel(self.data_dir)
        self.connection.status_message.connect(self.status_label.setText)
        root.addWidget(self.connection)

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
        root.addWidget(meta_box)

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
        root.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        root.addWidget(self.status_label)

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
        root.addWidget(summary_box)

        self.run_btn.clicked.connect(self._run_health_check)
        self.open_report_btn.clicked.connect(self._open_report_window)
        self.open_folder_btn.clicked.connect(self._open_output_folder)

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
        self.progress.setRange(0, 0)
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
        self._last_report_html = html if html.is_file() else None
        self.open_report_btn.setEnabled(self._last_report_html is not None)
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
        self.progress.setRange(0, 0)
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
