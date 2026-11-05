from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from app.gui.dialogs.loading_progress_dialog import LoadingProgressDialog
from app.gui.form_controls import PortSpinBox, configure_port_spinbox, create_form_combobox
from app.gui.theme import mark_page_subtitle, mark_primary_button, mark_secondary_button
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.widgets.ncurity_radio import NcurityRadioButton
from app.gui.workers.vpe_macro_worker import VpeMacroJob, VpeMacroResult, VpeMacroWorker
from app.modules.vpe_macro.apm_macro import (
    AccessProfileRef,
    ApplyPlan,
    MacroSnapshot,
    build_apply_plan,
    snapshot_display_name,
    snapshot_macro_name,
)

_PROFILE_PLACEHOLDER = "Access Profile을 선택하세요"
_SAME_DEVICE_NAME_RULE = (
    "Macro는 장비 전역 객체입니다. 이름 목록을 먼저 조회해서 마지막 번호를 본 뒤, "
    "auth_ad / _1 / _2 / _3이 있으면 _4를 만듭니다. 원본에는 연결하지 않습니다."
)


@dataclass
class LoadMacroRequest:
    snapshot: MacroSnapshot
    target_profile_path: str
    target_macro_name: str
    host: str
    port: int
    username: str
    password: str
    other_device: bool
    target_profile: AccessProfileRef | None = None


class SavedMacroPickDialog(QDialog):
    """In-app file list. QFileDialog 열기는 frozen Windows exe에서 프로세스를 종료시킨다."""

    file_chosen = pyqtSignal(str)

    def __init__(self, files: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load Macro — 저장된 파일")
        self.resize(520, 380)
        self._path = ""
        root = QVBoxLayout(self)
        hint = QLabel(
            "저장한 Macro를 선택하세요. Windows 파일 탐색기 창은 사용하지 않습니다."
        )
        hint.setWordWrap(True)
        mark_page_subtitle(hint)
        root.addWidget(hint)
        self.list = QListWidget()
        for label, path in files:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list.addItem(item)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)
        root.addWidget(self.list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("열기")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is None:
            QMessageBox.information(self, "Load Macro", "파일을 선택하세요.")
            return
        self._path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not self._path:
            QMessageBox.information(self, "Load Macro", "파일을 선택하세요.")
            return
        self.file_chosen.emit(self._path)
        super().accept()

    def selected_path(self) -> str:
        return self._path


class LoadMacroDialog(QDialog):
    load_requested = pyqtSignal(object)

    def __init__(
        self,
        *,
        snapshot: MacroSnapshot,
        profiles: list[AccessProfileRef],
        source_profile_path: str = "",
        this_device_connected: bool = False,
        this_host: str = "",
        this_port: int = 443,
        this_username: str = "",
        this_password: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self._this_profiles = list(profiles)
        self._source_profile_path = source_profile_path
        self._this_connected = this_device_connected
        self._this_host = this_host
        self._this_port = this_port
        self._this_username = this_username
        self._this_password = this_password
        self._other_profiles: list[AccessProfileRef] = []
        self._other_host = ""
        self._other_port = 443
        self._other_username = ""
        self._other_password = ""
        self._other_connected = False
        self._plan: ApplyPlan | None = None
        self._worker: VpeMacroWorker | None = None
        self._loading: LoadingProgressDialog | None = None
        self.setWindowTitle("Load Macro")
        self.setMinimumSize(640, 740)
        self.resize(640, 740)
        self._build_ui()
        self.this_radio.blockSignals(True)
        self.other_radio.blockSignals(True)
        if this_device_connected and profiles:
            self.this_radio.setChecked(True)
        else:
            self.other_radio.setChecked(True)
        self.this_radio.blockSignals(False)
        self.other_radio.blockSignals(False)
        self._on_mode_changed()
        self.resize(640, 740)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        caption = self.snapshot.macro_caption or self.snapshot.macro_full_path
        lead = QLabel(
            f"저장한 Macro <b>{caption}</b>을(를) 대상 Access Profile에 Load합니다."
        )
        lead.setWordWrap(True)
        lead.setTextFormat(Qt.TextFormat.RichText)
        mark_page_subtitle(lead)
        root.addWidget(lead)

        self.rule_label = QLabel(_SAME_DEVICE_NAME_RULE)
        self.rule_label.setWordWrap(True)
        self.rule_label.setProperty("role", "muted")
        root.addWidget(self.rule_label)

        source = QLabel(
            f"원본: {self.snapshot.access_profile or self.snapshot.policy_name or '—'}  ·  "
            f"{self.snapshot.source_host or self.snapshot.source_hostname or '—'}"
        )
        source.setWordWrap(True)
        source.setProperty("role", "muted")
        root.addWidget(source)

        mode_box = QGroupBox("Load 대상")
        mode_layout = QVBoxLayout(mode_box)
        self.this_radio = NcurityRadioButton("해당 장비에서 Load (지금 연결된 BIG-IP)")
        self.other_radio = NcurityRadioButton("다른 장비에서 Load")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.this_radio)
        self.mode_group.addButton(self.other_radio)
        if not self._this_connected:
            self.this_radio.setEnabled(False)
            self.this_radio.setToolTip("먼저 메인 화면에서 Test Connection을 하세요.")
        mode_layout.addWidget(self.this_radio)
        mode_layout.addWidget(self.other_radio)
        root.addWidget(mode_box)

        self.other_box = QGroupBox("다른 장비 연결")
        other_form = QFormLayout(self.other_box)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("MGMT IP")
        self.port_spin = PortSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(443)
        configure_port_spinbox(self.port_spin)
        self.user_edit = QLineEdit("admin")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("비밀번호는 저장되지 않습니다")
        connect_row = QHBoxLayout()
        self.connect_btn = QPushButton("Access Profile 조회")
        mark_secondary_button(self.connect_btn)
        self.connect_status = QLabel("")
        self.connect_status.setWordWrap(True)
        connect_row.addWidget(self.connect_btn)
        connect_row.addWidget(self.connect_status, stretch=1)
        other_form.addRow("MGMT IP", self.host_edit)
        other_form.addRow("Port", self.port_spin)
        other_form.addRow("ID", self.user_edit)
        other_form.addRow("Password", self.pass_edit)
        other_form.addRow("", connect_row)
        root.addWidget(self.other_box)

        form = QFormLayout()
        self.profile_combo: QComboBox = create_form_combobox()
        self.profile_combo.setMinimumWidth(360)
        self.profile_combo.setMinimumContentsLength(24)
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.macro_name_edit = QLineEdit(snapshot_display_name(self.snapshot))
        self.macro_name_edit.setPlaceholderText("이미 있으면 마지막 번호 다음(_4)으로 만듭니다")
        self.macro_name_edit.setFixedHeight(36)
        self.macro_name_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("대상 Access Profile", self.profile_combo)
        form.addRow("Macro 이름", self.macro_name_edit)
        root.addLayout(form)

        self.preview = QListWidget()
        self.preview.setMinimumHeight(120)
        self.preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.preview, stretch=1)

        self.warn_label = QLabel()
        self.warn_label.setWordWrap(True)
        self.warn_label.setProperty("role", "muted")
        root.addWidget(self.warn_label)

        self.confirm = NcurityCheckBox(
            "이 작업이 장비 Access Policy를 변경하는 것에 동의합니다."
        )
        self.confirm.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.confirm.setMinimumHeight(self.confirm.sizeHint().height())
        root.addWidget(self.confirm)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Load")
            ok.setMinimumHeight(40)
            ok.setMinimumWidth(120)
            mark_primary_button(ok)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setMinimumHeight(40)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._buttons = buttons

        self.this_radio.toggled.connect(self._on_mode_changed)
        self.other_radio.toggled.connect(self._on_mode_changed)
        self.connect_btn.clicked.connect(self._on_connect_other)
        self.profile_combo.currentIndexChanged.connect(self._refresh_preview)
        self.macro_name_edit.textChanged.connect(self._refresh_preview)
        self.confirm.toggled.connect(self._refresh_enabled)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_worker()
        self._close_loading()
        self._this_password = ""
        self._other_password = ""
        self.pass_edit.clear()
        super().closeEvent(event)

    def uses_other_device(self) -> bool:
        return self.other_radio.isChecked()

    def selected_profile_path(self) -> str:
        return str(self.profile_combo.currentData() or "")

    def target_macro_name(self) -> str:
        return self.macro_name_edit.text().strip()

    def selected_profile(self) -> AccessProfileRef | None:
        path = self.selected_profile_path()
        for ref in self._active_profiles():
            if ref.full_path == path:
                return ref
        return None

    def _same_name_on_this_device(self) -> bool:
        if self.uses_other_device():
            return False
        wanted = self.target_macro_name()
        source = snapshot_macro_name(self.snapshot)
        display = snapshot_display_name(self.snapshot)
        return bool(wanted) and wanted.lower() in {source.lower(), display.lower()}

    def apply_credentials(self) -> tuple[str, int, str, str]:
        if self.uses_other_device():
            return (
                self._other_host,
                self._other_port,
                self._other_username,
                self._other_password,
            )
        return self._this_host, self._this_port, self._this_username, self._this_password

    def _active_profiles(self) -> list[AccessProfileRef]:
        if self.uses_other_device():
            return self._other_profiles
        return self._this_profiles

    def _on_mode_changed(self) -> None:
        other = self.uses_other_device()
        self.other_box.setVisible(other)
        self.rule_label.setVisible(not other)
        self._fill_profiles()
        self._refresh_preview()
        self._restore_dialog_size()

    def _restore_dialog_size(self) -> None:
        layout = self.layout()
        hint = layout.sizeHint() if layout is not None else None
        hint_w = hint.width() if hint is not None else 640
        hint_h = hint.height() if hint is not None else 740
        self.setMinimumSize(max(640, hint_w), max(740, hint_h))
        if self.width() < self.minimumWidth() or self.height() < self.minimumHeight():
            self.resize(
                max(self.width(), self.minimumWidth()),
                max(self.height(), self.minimumHeight()),
            )

    def _fill_profiles(self) -> None:
        profiles = self._active_profiles()
        source = "" if self.uses_other_device() else self._source_profile_path
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem(_PROFILE_PLACEHOLDER, "")
        for ref in profiles:
            label = ref.full_path
            if source and ref.full_path == source:
                label = f"{ref.full_path} (원본)"
            self.profile_combo.addItem(label, ref.full_path)
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)

    def _on_connect_other(self) -> None:
        host = self.host_edit.text().strip()
        user = self.user_edit.text().strip()
        password = self.pass_edit.text()
        if not host or not user or not password:
            QMessageBox.warning(self, "Load Macro", "MGMT IP, ID, Password를 입력하세요.")
            return
        self._stop_worker()
        self.connect_btn.setEnabled(False)
        self.connect_status.setText("로그인 중…")
        self._close_loading()
        job = VpeMacroJob(
            action="login",
            host=host,
            port=int(self.port_spin.value()),
            username=user,
            password=password,
        )
        worker = VpeMacroWorker(job)
        self._worker = worker
        worker.progress.connect(self.connect_status.setText)
        worker.percent.connect(self._on_login_percent)
        worker.finished_ok.connect(self._on_other_login_ok)
        worker.failed.connect(self._on_other_login_fail)
        worker.start()

    def _on_other_login_ok(self, result: object) -> None:
        self._worker = None
        self.connect_btn.setEnabled(True)
        if not isinstance(result, VpeMacroResult):
            self._close_loading()
            return
        self._other_host = self.host_edit.text().strip()
        self._other_port = int(self.port_spin.value())
        self._other_username = self.user_edit.text().strip()
        self._other_password = self.pass_edit.text()
        self._other_profiles = list(result.profiles)
        self._other_connected = True
        host_label = result.hostname or self._other_host
        self.connect_status.setText(
            f"연결됨 — {host_label}  ·  Access Profile {len(self._other_profiles)}개"
        )
        self._fill_profiles()
        self._refresh_preview()

    def _on_login_percent(self, current: int, total: int, detail: str = "") -> None:
        text = (detail or "조회 중…").strip()
        self.connect_status.setText(f"{text}  ({current}/{max(int(total), 1)})")

    def _on_other_login_fail(self, message: str) -> None:
        self._worker = None
        self.connect_btn.setEnabled(True)
        self._close_loading()
        self._other_connected = False
        self._other_profiles = []
        self._other_password = ""
        self.connect_status.setText("조회 실패")
        self._fill_profiles()
        self._refresh_preview()
        QMessageBox.critical(self, "Load Macro", message)

    def _open_loading(self) -> None:
        self._close_loading()
        dialog = LoadingProgressDialog(
            "Access Profile Loading",
            "Access Profile을 불러오는 중입니다…",
            self,
        )
        self._loading = dialog
        dialog.show()

    def _update_loading(self, current: int, total: int, detail: str = "") -> None:
        if self._loading is not None:
            self._loading.set_progress(current, total, detail)

    def _finish_loading(self) -> None:
        dialog = self._loading
        self._loading = None
        if dialog is not None:
            dialog.finish()

    def _close_loading(self) -> None:
        dialog = self._loading
        self._loading = None
        if dialog is not None:
            dialog.fail_and_close()

    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        for signal in (worker.progress, worker.percent, worker.finished_ok, worker.failed):
            try:
                signal.disconnect()
            except TypeError:
                pass
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)

    def _refresh_preview(self) -> None:
        self.preview.clear()
        target = self.selected_profile()
        name = self.target_macro_name()
        if target is None:
            self.warn_label.setText(_PROFILE_PLACEHOLDER)
            self._plan = None
            self._refresh_enabled()
            self._restore_dialog_size()
            return
        if not name:
            self.warn_label.setText("Load할 Macro 이름을 입력하세요.")
            self._plan = None
            self._refresh_enabled()
            self._restore_dialog_size()
            return
        try:
            plan = build_apply_plan(
                snapshot=self.snapshot,
                target_profile=target,
                existing_item_names=set(),
                target_macro_name=name,
            )
        except Exception as exc:  # noqa: BLE001
            self.warn_label.setText(str(exc))
            self._plan = None
            self._refresh_enabled()
            self._restore_dialog_size()
            return
        self._plan = plan
        for agent_type, body in plan.agents:
            agent_name = body.get("name") or "?"
            QListWidgetItem(f"agent  {agent_type}  {agent_name}", self.preview)
        for item in plan.items:
            kind = item.get("itemType") or "item"
            cap = item.get("caption") or item.get("name")
            QListWidgetItem(f"{kind}  {cap}", self.preview)
        warns: list[str] = []
        if self._same_name_on_this_device() and target is not None:
            warns.append(
                f"이름 {name} 계열이 있으면 목록에서 마지막 번호를 찾아 다음 번호로 만듭니다. "
                "원본 Macro는 변경하지 않습니다."
            )
        if plan.warnings:
            warns.extend(plan.warnings)
        self.warn_label.setText("\n".join(warns) if warns else "")
        self._refresh_enabled()
        self._restore_dialog_size()

    def _refresh_enabled(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is None:
            return
        if self.uses_other_device() and not self._other_connected:
            ok.setEnabled(False)
            return
        ok.setEnabled(
            self._plan is not None
            and self.confirm.isChecked()
            and bool(self.selected_profile())
            and bool(self.target_macro_name())
        )

    def accept(self) -> None:
        if self.uses_other_device() and not self._other_connected:
            QMessageBox.information(self, "Load Macro", "다른 장비의 Access Profile을 먼저 조회하세요.")
            return
        if not self.selected_profile() or not self.target_macro_name():
            QMessageBox.information(self, "Load Macro", "Access Profile과 Macro 이름을 선택하세요.")
            return
        host, port, username, password = self.apply_credentials()
        self.load_requested.emit(
            LoadMacroRequest(
                snapshot=self.snapshot,
                target_profile_path=self.selected_profile_path(),
                target_macro_name=self.target_macro_name(),
                host=host,
                port=port,
                username=username,
                password=password,
                other_device=self.uses_other_device(),
                target_profile=self.selected_profile(),
            )
        )
        super().accept()


# Older import path used by previous builds.
ApplyMacroDialog = LoadMacroDialog
