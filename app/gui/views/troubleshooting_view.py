"""Device troubleshooting collect: Qkview, logs, cores, and UCS."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.app_paths import local_data_dir
from app.gui.theme import mark_page_subtitle, mark_page_title, mark_primary_button
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.workers.troubleshooting_worker import TroubleshootingWorker
from app.gui.workers.vpe_macro_worker import release_qthread
from app.modules.troubleshooting.collect import Artifact

_COLUMNS = ("항목", "상태", "파일")


class TroubleshootingView(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self.data_dir = local_data_dir()
        self._worker: TroubleshootingWorker | None = None
        self._dest = ""
        self._build()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(720, 560)

    def shutdown(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(1500)
        self._worker = None

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        title = QLabel("트러블슈팅 자료 수집")
        mark_page_title(title)
        outer.addWidget(title)
        subtitle = QLabel(
            "Qkview, 로그 tarball, Core, UCS를 장비에서 만들어 이 PC 폴더로 받습니다. "
            "파일 이름은 날짜-Hostname 입니다. UCS를 고르면 f5mku -K 결과도 함께 저장합니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        outer.addWidget(subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, stretch=1)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setSpacing(12)

        self.connection = DeviceConnectionPanel(self.data_dir)
        root.addWidget(self.connection)

        box = QGroupBox("수집 항목")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 72)
        item_label = QLabel("항목")
        item_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        checks = QHBoxLayout()
        checks.setContentsMargins(0, 0, 0, 0)
        checks.setSpacing(18)
        checks.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.qkview = NcurityCheckBox("Qkview")
        self.logs = NcurityCheckBox("Log Tarball")
        self.cores = NcurityCheckBox("Core File Check")
        self.ucs = NcurityCheckBox("UCS")
        self.qkview.setChecked(True)
        self.logs.setChecked(True)
        self.ucs.setToolTip("체크하면 f5mku -K 결과를 같은 폴더에 저장합니다.")
        for box_check in (self.qkview, self.logs, self.cores, self.ucs):
            checks.addWidget(box_check, alignment=Qt.AlignmentFlag.AlignVCenter)
        checks.addStretch()
        grid.addWidget(item_label, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addLayout(checks, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        place_label = QLabel("저장 위치")
        place_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.folder_label = QLabel("폴더를 선택하세요.")
        self.folder_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.folder_label.setWordWrap(True)
        pick = QPushButton("저장 폴더")
        pick.clicked.connect(self._pick_folder)
        row_h = max(pick.sizeHint().height(), self.qkview.sizeHint().height())
        item_label.setMinimumHeight(row_h)
        place_label.setMinimumHeight(pick.sizeHint().height())
        self.folder_label.setMinimumHeight(pick.sizeHint().height())
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(12)
        folder_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        folder_row.addWidget(self.folder_label, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
        folder_row.addWidget(pick, alignment=Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(
            place_label,
            1,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        grid.addLayout(folder_row, 1, 1, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(box)

        actions = QHBoxLayout()
        run = QPushButton("수집")
        mark_primary_button(run)
        run.clicked.connect(self._start)
        actions.addWidget(run)
        actions.addStretch()
        root.addLayout(actions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        root.addWidget(self.status)
        root.addWidget(self.progress)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        root.addWidget(self.table)

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "저장 폴더")
        if not chosen:
            return
        self._dest = chosen
        self.folder_label.setText(chosen)

    def _start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if not any(box.isChecked() for box in (self.qkview, self.logs, self.cores, self.ucs)):
            QMessageBox.warning(self, "트러블슈팅", "수집할 항목을 하나 이상 선택하세요.")
            return
        if not self._dest:
            QMessageBox.warning(self, "트러블슈팅", "저장 폴더를 선택하세요.")
            return
        try:
            _targets, connections = self.connection.collect_targets_and_connections()
        except ValueError as exc:
            QMessageBox.warning(self, "트러블슈팅", str(exc))
            return
        if not connections:
            QMessageBox.warning(self, "트러블슈팅", "장비 주소를 입력하세요.")
            return
        worker = TroubleshootingWorker(
            connections,
            Path(self._dest),
            qkview=self.qkview.isChecked(),
            logs=self.logs.isChecked(),
            cores=self.cores.isChecked(),
            ucs=self.ucs.isChecked(),
        )
        self._worker = worker
        self._clear_results()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        worker.progressed.connect(self._on_progress)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_fail)
        worker.finished.connect(self._on_thread_finished)
        worker.start()

    def _clear_results(self) -> None:
        self.table.setRowCount(0)
        self.status.setText("")

    def _on_progress(self, value: int, text: str) -> None:
        self.progress.setValue(value)
        self.status.setText(text)

    def _on_done(self, result: object) -> None:
        self.progress.setValue(100)
        self.progress.setVisible(False)
        rows = list(result) if isinstance(result, list) else []
        self._fill(rows)
        self.status.setText(f"완료 {len(rows)}건")

    def _on_fail(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status.setText(message)
        QMessageBox.warning(self, "트러블슈팅", message)

    def _on_thread_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, TroubleshootingWorker) and worker is not self._worker:
            release_qthread(worker)

    def _fill(self, rows: list[Artifact]) -> None:
        self.table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            for column, value in enumerate((item.name, item.status, item.path)):
                cell = QTableWidgetItem(value)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(index, column, cell)
