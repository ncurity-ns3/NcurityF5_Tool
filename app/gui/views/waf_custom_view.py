"""Custom WAF request builder. Sends only to the entered IP and Host."""

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
    QPlainTextEdit,
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
from app.gui.workers.waf_custom_worker import WafCustomWorker
from app.modules.waf_poc.curlutil import Target
from app.modules.waf_poc.custom_request import LoginPlan


class _PairEditor(QWidget):
    def __init__(self, add_label: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._rows = QVBoxLayout()
        self._rows.setSpacing(6)
        layout.addLayout(self._rows)
        add = QPushButton(add_label)
        mark_secondary_button(add)
        add.setFixedHeight(32)
        add.clicked.connect(lambda: self.add_row())
        layout.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)

    def add_row(self, name: str = "", value: str = "") -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        name_edit = QLineEdit(name)
        value_edit = QLineEdit(value)
        name_edit.setPlaceholderText("이름")
        value_edit.setPlaceholderText("값")
        name_edit.setFixedHeight(36)
        value_edit.setFixedHeight(36)
        remove = QPushButton("삭제")
        mark_secondary_button(remove)
        remove.setFixedHeight(36)
        remove.clicked.connect(lambda: self._remove(row))
        layout.addWidget(name_edit, stretch=1)
        layout.addWidget(value_edit, stretch=2)
        layout.addWidget(remove)
        self._rows.addWidget(row)

    def pairs(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for index in range(self._rows.count()):
            row = self._rows.itemAt(index).widget()
            if row is None:
                continue
            edits = row.findChildren(QLineEdit)
            if len(edits) >= 2:
                found.append((edits[0].text(), edits[1].text()))
        return found

    def _remove(self, row: QWidget) -> None:
        self._rows.removeWidget(row)
        row.deleteLater()


class WafCustomView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: WafCustomWorker | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        title = QLabel("요청 작성")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel(
            "입력한 IP와 Host로만 보냅니다. "
            "Method, URI, 헤더, 쿠키, 파라미터, 로그인을 직접 넣습니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        form = QVBoxLayout(host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(12)
        form.addWidget(self._build_target())
        form.addWidget(self._build_request())
        form.addWidget(self._build_headers())
        form.addWidget(self._build_cookies())
        form.addWidget(self._build_login())
        scroll.setWidget(host)
        root.addWidget(scroll, stretch=1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.send_btn = QPushButton("요청 전송")
        mark_primary_button(self.send_btn)
        self.send_btn.setFixedHeight(36)
        self.login_btn = QPushButton("로그인 시도")
        mark_secondary_button(self.login_btn)
        self.login_btn.setFixedHeight(36)
        self.stop_btn = QPushButton("중지")
        mark_secondary_button(self.stop_btn)
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setEnabled(False)
        self.status_label = QLabel("대기")
        self.status_label.setProperty("role", "muted")
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.login_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.status_label, stretch=1)
        root.addLayout(buttons)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setAcceptRichText(False)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setPlaceholderText("전송 결과가 여기에 표시됩니다.")
        self.log.setMinimumHeight(140)
        root.addWidget(self.log)
        self.send_btn.clicked.connect(lambda: self._start(False))
        self.login_btn.clicked.connect(lambda: self._start(True))
        self.stop_btn.clicked.connect(self._stop)
        self.method.currentTextChanged.connect(self._sync_body)
        self.body_mode.currentTextChanged.connect(self._sync_body)
        self.auth_type.currentTextChanged.connect(self._sync_login)
        self.use_numbers.toggled.connect(self._sync_login)
        self._sync_body()
        self._sync_login()

    def shutdown(self) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.stop_now()
        worker.wait(3000)
        self._worker = None

    def _build_target(self) -> QFrame:
        card = QFrame()
        mark_step_card(card)
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self.ip = QLineEdit("192.168.41.91")
        self.host = QLineEdit("curl.ncurity.com")
        self.protocol = create_form_combobox()
        self.protocol.addItems(["HTTP", "HTTPS"])
        self.port = PortSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(80)
        configure_port_spinbox(self.port)
        for edit in (self.ip, self.host):
            edit.setFixedHeight(36)
        grid.addWidget(_label("IP"), 0, 0)
        grid.addWidget(self.ip, 1, 0)
        grid.addWidget(_label("Host"), 0, 1)
        grid.addWidget(self.host, 1, 1)
        grid.addWidget(_label("프로토콜"), 2, 0)
        grid.addWidget(self.protocol, 3, 0)
        grid.addWidget(_label("포트"), 2, 1)
        grid.addWidget(self.port, 3, 1)
        self.insecure = NcurityCheckBox("HTTPS 인증서 검증 안 함")
        self.insecure.setChecked(True)
        grid.addWidget(self.insecure, 4, 0, 1, 2)
        self.protocol.currentTextChanged.connect(self._on_protocol)
        return card

    def _build_request(self) -> QFrame:
        card = QFrame()
        mark_step_card(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel("요청")
        heading.setProperty("role", "infoTitle")
        layout.addWidget(heading)
        row = QHBoxLayout()
        self.method = create_form_combobox()
        self.method.addItems(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
        self.uri = QLineEdit("/")
        self.uri.setFixedHeight(36)
        method_col = QVBoxLayout()
        method_col.addWidget(_label("Method"))
        method_col.addWidget(self.method)
        uri_col = QVBoxLayout()
        uri_col.addWidget(_label("URI"))
        uri_col.addWidget(self.uri)
        row.addLayout(method_col)
        row.addLayout(uri_col, stretch=1)
        layout.addLayout(row)
        layout.addWidget(_label("Query 파라미터  ·  주소 뒤에 붙습니다"))
        self.query = _PairEditor("Query 추가")
        layout.addWidget(self.query)
        layout.addWidget(_label("Body 파라미터  ·  POST, PUT, PATCH, DELETE"))
        self.body_mode = create_form_combobox()
        self.body_mode.addItems(["폼 파라미터", "직접 입력"])
        layout.addWidget(self.body_mode)
        self.body_fields = _PairEditor("Body 추가")
        layout.addWidget(self.body_fields)
        self.raw_body = QPlainTextEdit()
        self.raw_body.setPlaceholderText('{"username":"user","password":"secret"}')
        self.raw_body.setFixedHeight(90)
        layout.addWidget(self.raw_body)
        return card

    def _build_headers(self) -> QFrame:
        card = QFrame()
        mark_step_card(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel("Header")
        heading.setProperty("role", "infoTitle")
        layout.addWidget(heading)
        self.use_content_type = NcurityCheckBox("Content-Type")
        self.use_content_type.setChecked(True)
        self.content_type = create_form_combobox()
        self.content_type.addItems(
            [
                "application/x-www-form-urlencoded",
                "application/json",
                "text/plain",
                "application/xml",
            ]
        )
        self.use_user_agent = NcurityCheckBox("User-Agent")
        self.use_user_agent.setChecked(True)
        self.user_agent = QLineEdit("Mozilla/5.0")
        self.user_agent.setFixedHeight(36)
        self.use_accept = NcurityCheckBox("Accept")
        self.accept = QLineEdit("*/*")
        self.accept.setFixedHeight(36)
        self.use_referer = NcurityCheckBox("Referer")
        self.referer = QLineEdit()
        self.referer.setFixedHeight(36)
        layout.addWidget(self.use_content_type)
        layout.addWidget(self.content_type)
        layout.addWidget(self.use_user_agent)
        layout.addWidget(self.user_agent)
        layout.addWidget(self.use_accept)
        layout.addWidget(self.accept)
        layout.addWidget(self.use_referer)
        layout.addWidget(self.referer)
        layout.addWidget(_label("Custom Header"))
        self.custom_headers = _PairEditor("헤더 추가")
        layout.addWidget(self.custom_headers)
        return card

    def _build_cookies(self) -> QFrame:
        card = QFrame()
        mark_step_card(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel("Cookie")
        heading.setProperty("role", "infoTitle")
        layout.addWidget(heading)
        self.cookies = _PairEditor("쿠키 추가")
        layout.addWidget(self.cookies)
        return card

    def _build_login(self) -> QFrame:
        card = QFrame()
        mark_step_card(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel("로그인")
        heading.setProperty("role", "infoTitle")
        layout.addWidget(heading)
        self.login_first = NcurityCheckBox("요청 전송 전에 로그인")
        layout.addWidget(self.login_first)
        self.login_uri = QLineEdit("/login")
        self.login_uri.setFixedHeight(36)
        layout.addWidget(_label("Login URI"))
        layout.addWidget(self.login_uri)
        self.auth_type = create_form_combobox()
        self.auth_type.addItems(["HTML Form", "HTTP Basic Authentication", "Request Body"])
        layout.addWidget(_label("Authentication Type"))
        layout.addWidget(self.auth_type)
        self.username = QLineEdit("user")
        self.password = QLineEdit()
        self.username.setFixedHeight(36)
        self.password.setFixedHeight(36)
        self.password.setPlaceholderText("비밀번호")
        account = QHBoxLayout()
        user_col = QVBoxLayout()
        user_col.addWidget(_label("계정"))
        user_col.addWidget(self.username)
        pass_col = QVBoxLayout()
        pass_col.addWidget(_label("비밀번호"))
        pass_col.addWidget(self.password)
        account.addLayout(user_col, stretch=1)
        account.addLayout(pass_col, stretch=1)
        layout.addLayout(account)
        self.use_numbers = NcurityCheckBox("계정 뒤에 번호 붙이기  ·  user1, user2 …")
        self.use_numbers.setChecked(True)
        layout.addWidget(self.use_numbers)
        self.number_from = PortSpinBox()
        self.number_to = PortSpinBox()
        self.attempts = PortSpinBox()
        self.pause = PortSpinBox()
        for spin, low, high, value in (
            (self.number_from, 1, 100, 1),
            (self.number_to, 1, 100, 10),
            (self.attempts, 1, 20, 1),
            (self.pause, 0, 10, 0),
        ):
            spin.setRange(low, high)
            spin.setValue(value)
            configure_port_spinbox(spin)
        numbers = QGridLayout()
        numbers.addWidget(_label("시작 번호"), 0, 0)
        numbers.addWidget(self.number_from, 1, 0)
        numbers.addWidget(_label("끝 번호"), 0, 1)
        numbers.addWidget(self.number_to, 1, 1)
        numbers.addWidget(_label("계정당 시도 횟수"), 0, 2)
        numbers.addWidget(self.attempts, 1, 2)
        numbers.addWidget(_label("간격(초)"), 0, 3)
        numbers.addWidget(self.pause, 1, 3)
        layout.addLayout(numbers)
        self.form_fields = QWidget()
        form_layout = QHBoxLayout(self.form_fields)
        form_layout.setContentsMargins(0, 0, 0, 0)
        self.user_field = QLineEdit("username")
        self.password_field = QLineEdit("password")
        self.user_field.setFixedHeight(36)
        self.password_field.setFixedHeight(36)
        form_layout.addWidget(self.user_field)
        form_layout.addWidget(self.password_field)
        self.form_hint = _label("HTML Form 필드 이름  ·  앞이 계정, 뒤가 비밀번호")
        layout.addWidget(self.form_hint)
        layout.addWidget(self.form_fields)
        self.body_template = QPlainTextEdit()
        self.body_template.setPlainText('{"username":"{user}","password":"{password}"}')
        self.body_template.setFixedHeight(80)
        self.body_type = create_form_combobox()
        self.body_type.addItems(
            ["application/json", "application/x-www-form-urlencoded", "text/plain"]
        )
        self.body_hint = _label("Request Body  ·  {user} 와 {password} 가 계정으로 바뀝니다")
        layout.addWidget(self.body_hint)
        layout.addWidget(self.body_type)
        layout.addWidget(self.body_template)
        self.carry_cookies = NcurityCheckBox("로그인 응답의 쿠키를 다음 요청에 포함")
        self.carry_cookies.setChecked(True)
        layout.addWidget(self.carry_cookies)
        return card

    def _on_protocol(self, text: str) -> None:
        if text == "HTTPS":
            self.port.setValue(443)
        elif text == "HTTP":
            self.port.setValue(80)

    def _sync_body(self) -> None:
        verb = self.method.currentText()
        enabled = verb in {"POST", "PUT", "PATCH", "DELETE"}
        raw = self.body_mode.currentText() == "직접 입력"
        self.body_mode.setEnabled(enabled)
        self.body_fields.setEnabled(enabled and not raw)
        self.raw_body.setEnabled(enabled and raw)

    def _sync_login(self) -> None:
        kind = self.auth_type.currentText()
        show_form = kind == "HTML Form"
        show_body = kind == "Request Body"
        self.form_hint.setVisible(show_form)
        self.form_fields.setVisible(show_form)
        self.body_hint.setVisible(show_body)
        self.body_template.setVisible(show_body)
        self.body_type.setVisible(show_body)
        numbered = self.use_numbers.isChecked()
        self.number_from.setEnabled(numbered)
        self.number_to.setEnabled(numbered)

    def _headers(self) -> list[tuple[str, str]]:
        headers: list[tuple[str, str]] = []
        if self.use_content_type.isChecked():
            headers.append(("Content-Type", self.content_type.currentText()))
        if self.use_user_agent.isChecked() and self.user_agent.text().strip():
            headers.append(("User-Agent", self.user_agent.text().strip()))
        if self.use_accept.isChecked() and self.accept.text().strip():
            headers.append(("Accept", self.accept.text().strip()))
        if self.use_referer.isChecked() and self.referer.text().strip():
            headers.append(("Referer", self.referer.text().strip()))
        headers.extend(self.custom_headers.pairs())
        return headers

    def _login_plan(self) -> LoginPlan:
        kind = {"HTML Form": "form", "HTTP Basic Authentication": "basic", "Request Body": "body"}[
            self.auth_type.currentText()
        ]
        return LoginPlan(
            uri=self.login_uri.text(),
            kind=kind,
            username=self.username.text(),
            password=self.password.text(),
            use_numbers=self.use_numbers.isChecked(),
            number_from=int(self.number_from.value()),
            number_to=int(self.number_to.value()),
            attempts=int(self.attempts.value()),
            pause_seconds=int(self.pause.value()),
            user_field=self.user_field.text(),
            password_field=self.password_field.text(),
            body_template=self.body_template.toPlainText(),
            content_type=self.body_type.currentText(),
        )

    def _target(self) -> Target:
        scheme = "https" if self.protocol.currentText() == "HTTPS" else "http"
        return Target.parse(self.ip.text(), self.host.text(), scheme, int(self.port.value()))

    def _start(self, login_only: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            target = self._target()
            login = self._login_plan() if login_only or self.login_first.isChecked() else None
        except ValueError as exc:
            QMessageBox.warning(self, "요청 작성", str(exc))
            return
        if login_only and login is None:
            return
        self.log.clear()
        self._set_running(True)
        self.status_label.setText("전송 중")
        worker = WafCustomWorker(
            target,
            method=self.method.currentText(),
            uri=self.uri.text(),
            query=self.query.pairs(),
            body_mode="raw" if self.body_mode.currentText() == "직접 입력" else "form",
            body_fields=self.body_fields.pairs(),
            raw_body=self.raw_body.toPlainText(),
            headers=self._headers(),
            cookies=self.cookies.pairs(),
            insecure=self.insecure.isChecked(),
            login=login,
            login_only=login_only,
            carry_cookies=self.carry_cookies.isChecked(),
        )
        worker.log_line.connect(self._append_log)
        worker.run_done.connect(self.status_label.setText)
        worker.run_failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
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

    def _on_failed(self, message: str) -> None:
        self._append_log(message)
        self.status_label.setText("실패")

    def _on_finished(self) -> None:
        self._set_running(False)
        self._worker = None

    def _set_running(self, running: bool) -> None:
        self.send_btn.setEnabled(not running)
        self.login_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    return label
