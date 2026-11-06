"""WAF PoC — OWASP Top 10 curl sender."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.form_controls import PortSpinBox, configure_port_spinbox, create_form_combobox
from app.gui.theme import (
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
    mark_step_card,
)
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.workers.waf_poc_worker import WafPocWorker
from app.modules.waf_poc.catalog import DEFAULT_YEAR, YEARS, PocCase, cases_for_year
from app.modules.waf_poc.curlutil import Target
from app.modules.waf_poc.runner import SendSummary


class WafView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checks: dict[str, NcurityCheckBox] = {}
        self._updating = False
        self._worker: WafPocWorker | None = None

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(0, 0, 0, 0)

        title = QLabel("WAF")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel(
            "OWASP Top 10 테스트 · PoC 전용. 입력한 IP와 Host로만 curl을 보냅니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        target = QFrame()
        mark_step_card(target)
        grid = QGridLayout(target)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        self.ip = QLineEdit("192.168.41.91")
        self.host = QLineEdit("curl.ncurity.com")
        self.ip.setFixedHeight(36)
        self.host.setFixedHeight(36)
        self.year = create_form_combobox()
        for value in YEARS:
            self.year.addItem(f"{value}년", value)
        year_index = self.year.findData(DEFAULT_YEAR)
        if year_index >= 0:
            self.year.setCurrentIndex(year_index)
        self.protocol = create_form_combobox()
        self.protocol.addItems(["HTTP", "HTTPS", "기타"])
        self.port = PortSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8080)
        configure_port_spinbox(self.port)
        self.custom_scheme = create_form_combobox()
        self.custom_scheme.addItems(["HTTP", "HTTPS"])

        grid.addWidget(_field_label("IP"), 0, 0)
        grid.addWidget(self.ip, 1, 0)
        grid.addWidget(_field_label("Host"), 0, 1)
        grid.addWidget(self.host, 1, 1)
        grid.addWidget(_field_label("OWASP 연도"), 2, 0)
        grid.addWidget(self.year, 3, 0)
        grid.addWidget(_field_label("프로토콜"), 2, 1)
        grid.addWidget(self.protocol, 3, 1)

        self.custom_row = QWidget()
        custom_layout = QHBoxLayout(self.custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(16)
        port_col = QVBoxLayout()
        port_col.setSpacing(8)
        port_col.addWidget(_field_label("포트"))
        port_col.addWidget(self.port)
        scheme_col = QVBoxLayout()
        scheme_col.setSpacing(8)
        scheme_col.addWidget(_field_label("기타 포트 프로토콜"))
        scheme_col.addWidget(self.custom_scheme)
        custom_layout.addLayout(port_col, stretch=1)
        custom_layout.addLayout(scheme_col, stretch=1)
        grid.addWidget(self.custom_row, 4, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.custom_row.setVisible(False)
        root.addWidget(target)

        cases_card = QFrame()
        mark_step_card(cases_card)
        cases_layout = QVBoxLayout(cases_card)
        cases_layout.setContentsMargins(16, 14, 16, 14)
        cases_layout.setSpacing(8)
        section = QLabel("OWASP Top 10 테스트")
        section.setProperty("role", "infoTitle")
        cases_layout.addWidget(section)
        self.select_all = NcurityCheckBox("전체 선택")
        self.select_all.setChecked(True)
        cases_layout.addWidget(self.select_all)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(180)
        self.case_host = QWidget()
        self.case_layout = QVBoxLayout(self.case_host)
        self.case_layout.setContentsMargins(0, 0, 0, 0)
        self.case_layout.setSpacing(6)
        self.case_layout.addStretch()
        scroll.setWidget(self.case_host)
        cases_layout.addWidget(scroll, stretch=1)
        root.addWidget(cases_card, stretch=1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.send_btn = QPushButton("전송")
        mark_primary_button(self.send_btn)
        self.send_btn.setFixedHeight(36)
        self.stop_btn = QPushButton("중지")
        mark_secondary_button(self.stop_btn)
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.status_label = QLabel("대기")
        self.status_label.setProperty("role", "muted")
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.status_label, stretch=1)
        root.addLayout(buttons)

        log_title = QLabel("전송 결과")
        log_title.setProperty("role", "infoTitle")
        root.addWidget(log_title)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setAcceptRichText(False)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setPlaceholderText("전송 결과가 여기에 표시됩니다.")
        self.log.setMinimumHeight(160)
        root.addWidget(self.log, stretch=1)

        self.year.currentIndexChanged.connect(self._reload_cases)
        self.protocol.currentTextChanged.connect(self._on_protocol)
        self.select_all.toggled.connect(self._toggle_all)
        self.send_btn.clicked.connect(self._send)
        self.stop_btn.clicked.connect(self._stop)
        self._reload_cases()

    def shutdown(self) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.stop_now()
        worker.wait(3000)
        self._worker = None

    def _on_protocol(self, text: str) -> None:
        self.custom_row.setVisible(text == "기타")

    def _reload_cases(self) -> None:
        while self.case_layout.count():
            item = self.case_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._checks.clear()
        year = int(self.year.currentData())
        cases = cases_for_year(year)
        self._updating = True
        if not cases:
            hint = QLabel(f"{year}년 테스트 항목은 아직 없습니다.")
            hint.setProperty("role", "muted")
            hint.setWordWrap(True)
            self.case_layout.addWidget(hint)
            self.select_all.setChecked(False)
            self.select_all.setEnabled(False)
        else:
            self.select_all.setEnabled(True)
            self.select_all.setChecked(True)
            current_group = ""
            for case in cases:
                if case.group != current_group:
                    current_group = case.group
                    label = QLabel(case.group)
                    label.setProperty("role", "infoTitle")
                    self.case_layout.addWidget(label)
                box = NcurityCheckBox(f"{case.title}  ({len(case.commands())}건)")
                box.setChecked(True)
                box.toggled.connect(self._sync_select_all)
                self._checks[case.case_id] = box
                self.case_layout.addWidget(box)
        self.case_layout.addStretch()
        self._updating = False

    def _toggle_all(self, checked: bool) -> None:
        if self._updating:
            return
        self._updating = True
        for box in self._checks.values():
            box.setChecked(checked)
        self._updating = False

    def _sync_select_all(self, _checked: bool = False) -> None:
        if self._updating:
            return
        self._updating = True
        boxes = list(self._checks.values())
        self.select_all.setChecked(bool(boxes) and all(box.isChecked() for box in boxes))
        self._updating = False

    def _selected_cases(self) -> list[PocCase]:
        year = int(self.year.currentData())
        selected: list[PocCase] = []
        for case in cases_for_year(year):
            box = self._checks.get(case.case_id)
            if box is not None and box.isChecked():
                selected.append(case)
        return selected

    def _current_target(self) -> Target:
        proto = self.protocol.currentText()
        if proto == "HTTPS":
            scheme, port = "https", 443
        elif proto == "기타":
            scheme = "https" if self.custom_scheme.currentText() == "HTTPS" else "http"
            port = int(self.port.value())
        else:
            scheme, port = "http", 80
        return Target.parse(self.ip.text(), self.host.text(), scheme, port)

    def _send(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            target = self._current_target()
        except ValueError as exc:
            QMessageBox.warning(self, "WAF", str(exc))
            return
        cases = self._selected_cases()
        if not cases:
            QMessageBox.information(self, "WAF", "보낼 항목을 선택해 주세요.")
            return
        self.log.clear()
        self._set_running(True)
        self.status_label.setText("전송 중")
        worker = WafPocWorker(cases, target)
        worker.log_line.connect(self._append_log)
        worker.run_done.connect(self._on_done)
        worker.run_failed.connect(self._on_failed)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        worker.start()

    def _stop(self) -> None:
        if self._worker is not None:
            self.status_label.setText("중지 중")
            self._worker.stop_now()

    def _append_log(self, text: str) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.log.toPlainText():
            cursor.insertText("\n")
        cursor.insertText(text.rstrip("\n"))
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _on_done(self, summary: object) -> None:
        if not isinstance(summary, SendSummary):
            return
        if summary.stopped:
            self.status_label.setText(f"중지 · 전송 {summary.sent}건")
        elif summary.failed:
            self.status_label.setText(f"완료 · 전송 {summary.sent}건, 실패 {summary.failed}건")
        else:
            self.status_label.setText(f"완료 · 전송 {summary.sent}건")

    def _on_failed(self, message: str) -> None:
        self._append_log(message)
        self.status_label.setText("실패")

    def _on_thread_finished(self) -> None:
        self._set_running(False)
        self._worker = None

    def _set_running(self, running: bool) -> None:
        self.send_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.ip.setEnabled(not running)
        self.host.setEnabled(not running)
        self.year.setEnabled(not running)
        self.protocol.setEnabled(not running)
        self.port.setEnabled(not running)
        self.custom_scheme.setEnabled(not running)
        self.select_all.setEnabled((not running) and bool(self._checks))
        for box in self._checks.values():
            box.setEnabled(not running)


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label
