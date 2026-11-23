"""UCS / QKView SSL certificate usage."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme import (
    apply_device_table_style,
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
    polish_widget_scrollbars,
)
from app.gui.widgets.copy_table import install_sort_header, selectable_label
from app.gui.workers.ssl_cert_worker import SslCertWorker
from app.modules.ssl_cert.inspect import SslCertReport, SslCertRow

_FILE_FILTER = "UCS / QKView (*.ucs *.qkview);;모든 파일 (*.*)"
_COLUMNS = ("상태", "인증서", "SSL Profile", "Virtual Server", "만료")
_KIND_TEXT = {
    "expired": "만료됨",
    "soon": "30일 이내",
    "ok": "정상",
    "unknown": "확인 불가",
}
_KIND_FG = {
    "expired": "#B42318",
    "soon": "#B45309",
    "ok": "#0A6E31",
    "unknown": "#64748B",
}
_KIND_RANK = {"expired": 0, "soon": 1, "unknown": 2, "ok": 3}
_STAT_CAPTIONS = (
    ("stat_total", "총 인증서", "#0260EA"),
    ("stat_soon", "만료예정", "#B45309"),
    ("stat_expired", "만료", "#B42318"),
    ("stat_expired_off", "VS 미적용 만료", "#B42318"),
    ("stat_expired_on", "VS 적용 만료", "#B42318"),
)


class SslCertView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: SslCertWorker | None = None
        self._path: Path | None = None
        self._rows: tuple[SslCertRow, ...] = ()
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("SSL 인증서 확인")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel(
            "UCS 또는 QKView를 올리면, SSL Profile에 연결된 인증서와 "
            "그 Profile이 적용된 Virtual Server, 만료일을 보여 줍니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.file_label = QLabel("선택된 파일 없음")
        self.file_label.setProperty("role", "muted")
        self.file_label.setWordWrap(True)
        pick = QPushButton("파일 선택")
        mark_secondary_button(pick)
        pick.clicked.connect(self._pick_file)
        self.run_btn = QPushButton("확인")
        mark_primary_button(self.run_btn)
        self.run_btn.clicked.connect(self._run)
        file_row.addWidget(self.file_label, stretch=1)
        file_row.addWidget(pick)
        file_row.addWidget(self.run_btn)
        root.addLayout(file_row)

        self.summary = QLabel("파일을 올리면 사용 중인 인증서가 여기에 표시됩니다.")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        root.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        stats = QHBoxLayout()
        stats.setSpacing(8)
        for name, caption, accent in _STAT_CAPTIONS:
            frame, value = _stat_chip(caption, accent)
            setattr(self, name, value)
            stats.addWidget(frame, stretch=1)
        root.addLayout(stats)

        shell = QFrame()
        shell.setObjectName("deviceTableShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(_COLUMNS))
        apply_device_table_style(self.table)
        self._header = install_sort_header(self.table)
        self._header.sort_requested.connect(self._on_sort)
        self.table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setMinimumSectionSize(40)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        shell_layout.addWidget(self.table)
        root.addWidget(shell, stretch=1)
        polish_widget_scrollbars(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self._set_path(Path(local))
                self._run()
                event.acceptProposedAction()
                return
        event.ignore()

    def _pick_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "UCS 또는 QKView 선택", "", _FILE_FILTER)
        if chosen:
            self._set_path(Path(chosen))

    def _set_path(self, path: Path) -> None:
        self._path = path
        self.file_label.setText(path.name)
        self.file_label.setToolTip(str(path))

    def _run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if self._path is None or not self._path.is_file():
            QMessageBox.warning(self, "SSL 인증서 확인", "UCS 또는 QKView 파일을 선택하세요.")
            return
        self.run_btn.setEnabled(False)
        self.summary.setText(f"{self._path.name} 읽는 중…")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        worker = SslCertWorker(self._path)
        worker.progressed.connect(self.progress.setValue)
        worker.finished_ok.connect(self._on_ok)
        worker.failed.connect(self._on_fail)
        self._worker = worker
        worker.start()

    def _on_ok(self, report: object) -> None:
        self.run_btn.setEnabled(True)
        self.progress.setValue(100)
        self.progress.setVisible(False)
        if isinstance(report, SslCertReport):
            self.show_report(report)

    def _on_fail(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.summary.setText(message)
        QMessageBox.warning(self, "SSL 인증서 확인", message[:500])

    def show_report(self, report: SslCertReport) -> None:
        host = report.hostname or report.source_name or "장비"
        self._set_stats(report)
        if not report.rows:
            self.summary.setText(f"{host} — SSL Profile에 연결된 인증서가 없습니다.")
        else:
            self.summary.setText(
                f"{host}  ·  총 {len(report.rows)}건"
                f"  ·  만료예정 {report.soon_count}"
                f"  ·  만료 {report.expired_count}"
                f"  ·  VS 미적용 만료 {report.expired_off_virtual_count}"
                f"  ·  VS 적용 만료 {report.expired_on_virtual_count}"
            )
        self._rows = report.rows
        self._header.set_state(0, True)
        self._fill()

    def _set_stats(self, report: SslCertReport) -> None:
        self.stat_total.setText(str(len(report.rows)))
        self.stat_soon.setText(str(report.soon_count))
        self.stat_expired.setText(str(report.expired_count))
        self.stat_expired_off.setText(str(report.expired_off_virtual_count))
        self.stat_expired_on.setText(str(report.expired_on_virtual_count))

    def _on_sort(self, _column: int) -> None:
        self._fill()

    def _fill(self) -> None:
        rows = sorted(self._rows, key=self._sort_key, reverse=not self._header.ascending)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            self._fill_row(index, row)
        self.table.resizeRowsToContents()
        for index in range(self.table.rowCount()):
            self.table.setRowHeight(index, max(40, self.table.rowHeight(index)))
        self._fit_text_columns()

    def _fit_text_columns(self) -> None:
        """상태·만료는 글자가 잘리지 않게 내용 너비로 맞춘다."""
        for column, floor in ((0, 96), (4, 168)):
            self.table.resizeColumnToContents(column)
            if self.table.columnWidth(column) < floor:
                self.table.setColumnWidth(column, floor)

    def _sort_key(self, row: SslCertRow) -> tuple:
        virtual = ", ".join(row.virtuals)
        kind = _KIND_RANK.get(row.expiry_kind, 9)
        column = self._header.column
        if column == 1:
            return (row.cert.lower(), kind)
        if column == 2:
            return (row.profile.lower(), row.cert.lower())
        if column == 3:
            return (virtual.lower(), row.cert.lower())
        if column == 4:
            return (row.expiry_text, row.cert.lower())
        return (kind, row.expiry_text, row.cert.lower())

    def _fill_row(self, index: int, row: SslCertRow) -> None:
        status = _KIND_TEXT.get(row.expiry_kind, row.expiry_kind)
        virtual = "\n".join(row.virtuals) if row.virtuals else "없음"
        values = (status, row.cert, row.profile, virtual, row.expiry_text)
        fg = _KIND_FG.get(row.expiry_kind, "#1A2332")
        top = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setToolTip(value)
            self.table.setItem(index, column, item)
            color = fg if column in {0, 4} else "#1A2332"
            self.table.setCellWidget(
                index,
                column,
                selectable_label(value, background="#FFFFFF", color=color, align=top),
            )


def _stat_chip(caption: str, accent: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("sslStatChip")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(2)
    value = QLabel("—")
    value.setStyleSheet(
        f"color: {accent}; font-size: 18px; font-weight: 700; background: transparent;"
    )
    title = QLabel(caption)
    title.setStyleSheet("color: #64748B; font-size: 11px; background: transparent;")
    layout.addWidget(value)
    layout.addWidget(title)
    frame.setStyleSheet(
        "QFrame#sslStatChip {"
        " background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px;"
        "}"
    )
    return frame, value
