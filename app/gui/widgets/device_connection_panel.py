from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pydantic import SecretStr

from app.core.models import ConnectionProfile, DeviceTarget, PlatformKind
from app.gui.connection_test import (
    ConnectionTestOutcome,
    ConnectionTestPlan,
    build_multiple_plan,
    build_single_plan,
)
from app.gui.device_list_store import DeviceListStore
from app.gui.device_models import MODEL_ISERIES, MODEL_RSERIES, normalize_device_model
from app.gui.form_controls import PortSpinBox, configure_port_spinbox, create_form_combobox
from app.gui.device_profile_store import DeviceProfileStore
from app.gui.session_manager import SessionManager
from app.gui.theme import mark_primary_button
from app.gui.widgets.multi_device_entry import DeviceRowData
from app.gui.widgets.multi_device_table import MultiDeviceTablePanel
from app.gui.widgets.ncurity_radio import NcurityRadioButton
from app.gui.workers.test_connection_worker import TestConnectionWorker


class DeviceConnectionPanel(QWidget):
    """Single/Multiple 장비 연결 UI — Health Check·OS Upgrade 등에서 공유."""

    status_message = pyqtSignal(str)
    connection_test_finished = pyqtSignal(bool)
    disconnected = pyqtSignal()

    def __init__(
        self,
        data_dir: Path,
        parent: QWidget | None = None,
        *,
        tmos_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.data_dir = data_dir
        self.tmos_only = tmos_only
        self.profile_store = DeviceProfileStore(data_dir)
        self.list_store = DeviceListStore(data_dir)
        self._test_worker: TestConnectionWorker | None = None
        self._build_ui()
        if tmos_only:
            self._apply_tmos_only_mode()
        self._reload_saved_sessions()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_test_worker()
        super().closeEvent(event)

    @staticmethod
    def storage_paths(data_dir: Path) -> tuple[Path, Path]:
        """(Single 프로필, Multiple 목록) JSON 저장 디렉터리."""
        return data_dir / "devices", data_dir / "lists"

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        saved_box = QGroupBox("저장된 연결 (Session)")
        saved_form = QFormLayout(saved_box)
        row = QHBoxLayout()
        self.session_combo = create_form_combobox()
        self.session_combo.setMinimumWidth(200)
        self.session_combo.setMaximumWidth(480)
        self.load_session_btn = QPushButton("Load")
        self.save_session_btn = QPushButton("Save")
        self.delete_session_btn = QPushButton("Delete")
        row.addWidget(self.session_combo, stretch=1)
        row.addWidget(self.load_session_btn)
        row.addWidget(self.save_session_btn)
        row.addWidget(self.delete_session_btn)
        self.session_field_label = QLabel("프로필")
        saved_form.addRow(self.session_field_label, row)
        self.add_from_saved_btn = QPushButton("+ 저장된 장비에서 추가…")
        self.add_from_saved_btn.setVisible(False)
        saved_form.addRow("", self.add_from_saved_btn)
        root.addWidget(saved_box)

        self.mode_box = QGroupBox("Target Mode")
        mode_layout = QHBoxLayout(self.mode_box)
        self.single_radio = NcurityRadioButton("Single")
        self.multiple_radio = NcurityRadioButton("Multiple")
        self.single_radio.setChecked(True)
        mode_layout.addWidget(self.single_radio)
        mode_layout.addWidget(self.multiple_radio)
        self.single_radio.toggled.connect(self._on_target_mode_changed)
        self.multiple_radio.toggled.connect(self._on_target_mode_changed)
        root.addWidget(self.mode_box)

        self.single_group = QGroupBox("장비 연결 (Single)")
        self.single_form = QFormLayout(self.single_group)
        single_form = self.single_form
        self.single_platform_combo = create_form_combobox()
        self.single_platform_combo.addItems([MODEL_ISERIES, MODEL_RSERIES])
        self.single_platform_combo.currentTextChanged.connect(self._on_single_platform_changed)
        self.label_edit = QLineEdit("lab-device-01")

        self.f5os_host_edit = QLineEdit()
        self.f5os_port_spin = PortSpinBox()
        self.f5os_port_spin.setRange(1, 65535)
        self.f5os_port_spin.setValue(443)
        self.host_edit = QLineEdit()
        self.port_spin = PortSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(443)
        configure_port_spinbox(self.f5os_port_spin)
        configure_port_spinbox(self.port_spin)
        self.f5os_host_label = QLabel("F5OS MGMT IP")
        self.f5os_port_label = QLabel("F5OS Port")

        single_form.addRow("장비 모델", self.single_platform_combo)
        single_form.addRow("장비 라벨", self.label_edit)
        single_form.addRow(self.f5os_host_label, self.f5os_host_edit)
        single_form.addRow(self.f5os_port_label, self.f5os_port_spin)
        single_form.addRow("TMOS MGMT IP", self.host_edit)
        single_form.addRow("TMOS Port", self.port_spin)
        root.addWidget(self.single_group)

        self.multi_group = QGroupBox("장비 목록 (Multiple)")
        multi_layout = QVBoxLayout(self.multi_group)
        auth_mode_row = QHBoxLayout()
        self.auth_common_radio = NcurityRadioButton("공통 계정")
        self.auth_per_device_radio = NcurityRadioButton("장비별 계정")
        self.auth_common_radio.setChecked(True)
        auth_mode_row.addWidget(self.auth_common_radio)
        auth_mode_row.addWidget(self.auth_per_device_radio)
        auth_mode_row.addStretch()
        multi_layout.addLayout(auth_mode_row)
        self.auth_common_radio.toggled.connect(self._on_multi_auth_mode_changed)
        self.auth_per_device_radio.toggled.connect(self._on_multi_auth_mode_changed)

        hint = QLabel(
            "장비당 2행 표 — Model/Label 병합, Stack: F5OS(위) → TMOS(아래). "
            "iSeries or VE는 TMOS 1행만."
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        multi_layout.addWidget(hint)

        self.device_table = MultiDeviceTablePanel()
        self.device_table.devices_structure_changed.connect(self._refresh_common_auth_panel)
        multi_layout.addWidget(self.device_table)
        row_btn = QHBoxLayout()
        self.add_row_btn = QPushButton("+ Add Device")
        self.remove_row_btn = QPushButton("Remove Selected")
        row_btn.addWidget(self.add_row_btn)
        row_btn.addWidget(self.remove_row_btn)
        row_btn.addStretch()
        multi_layout.addLayout(row_btn)
        self.multi_group.setVisible(False)
        root.addWidget(self.multi_group)

        self.auth_group = QGroupBox("인증 (공통)")
        auth_form = QFormLayout(self.auth_group)

        self.f5os_auth_box = QGroupBox("F5OS 인증 (공통)")
        f5os_auth_form = QFormLayout(self.f5os_auth_box)
        self.f5os_user_edit = QLineEdit("admin")
        self.f5os_pass_edit = QLineEdit()
        self.f5os_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        f5os_auth_form.addRow("F5OS 사용자 ID", self.f5os_user_edit)
        f5os_auth_form.addRow("F5OS 비밀번호", self.f5os_pass_edit)
        auth_form.addRow(self.f5os_auth_box)

        self.user_edit = QLineEdit("admin")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        auth_form.addRow("TMOS 사용자 ID", self.user_edit)
        auth_form.addRow("TMOS 비밀번호", self.pass_edit)
        root.addWidget(self.auth_group)

        conn_btn = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        mark_primary_button(self.test_btn)
        self.disconnect_btn = QPushButton("Disconnect")
        conn_btn.addWidget(self.test_btn)
        conn_btn.addWidget(self.disconnect_btn)
        conn_btn.addStretch()
        root.addLayout(conn_btn)

        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.test_progress.setTextVisible(True)
        self.test_progress.setFormat("연결 테스트 준비…")
        root.addWidget(self.test_progress)

        self.session_label = QLabel("연결 상태: (없음)")
        self.session_label.setWordWrap(True)
        root.addWidget(self.session_label)

        profiles_dir, lists_dir = self.storage_paths(self.data_dir)
        self.path_hint = QLabel(
            f"저장 경로 — Single: <code>{profiles_dir}</code> · "
            f"Multiple 목록: <code>{lists_dir}</code>"
        )
        self.path_hint.setWordWrap(True)
        self.path_hint.setProperty("role", "muted")
        self.path_hint.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.path_hint)

        self.test_btn.clicked.connect(self._test_connection)
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.add_row_btn.clicked.connect(lambda: self._add_device_entry())
        self.remove_row_btn.clicked.connect(self._remove_device_entries)
        self.session_combo.currentIndexChanged.connect(self._on_session_profile_selected)
        self.load_session_btn.clicked.connect(self._load_saved_session)
        self.save_session_btn.clicked.connect(self._save_current_session)
        self.delete_session_btn.clicked.connect(self._delete_saved_session)
        self.add_from_saved_btn.clicked.connect(self._add_row_from_saved)
        self.host_edit.textChanged.connect(self._refresh_session_label)
        self.port_spin.valueChanged.connect(self._refresh_session_label)

        self._on_single_platform_changed()
        self.device_table.add_device(DeviceRowData(model=MODEL_ISERIES, label="device-02"))

    def _apply_tmos_only_mode(self) -> None:
        """VPE Macro 등 — Single TMOS만. Target Mode / 플랫폼 / F5OS 숨김."""
        self.single_radio.setChecked(True)
        self.mode_box.setVisible(False)
        self.multi_group.setVisible(False)
        self.add_from_saved_btn.setVisible(False)
        self.single_platform_combo.setCurrentText(MODEL_ISERIES)
        self.single_platform_combo.setVisible(False)
        platform_label = self.single_form.labelForField(self.single_platform_combo)
        if platform_label is not None:
            platform_label.setVisible(False)
        self.f5os_host_label.setVisible(False)
        self.f5os_host_edit.setVisible(False)
        self.f5os_port_label.setVisible(False)
        self.f5os_port_spin.setVisible(False)
        self.f5os_auth_box.setVisible(False)
        self.single_group.setTitle("장비 연결")
        profiles_dir, _lists_dir = self.storage_paths(self.data_dir)
        self.path_hint.setText(f"저장 경로 — 프로필: <code>{profiles_dir}</code> (비밀번호 미저장)")

    @staticmethod
    def _platform_from_label(label: str) -> PlatformKind:
        if label == MODEL_RSERIES:
            return PlatformKind.rseries
        return PlatformKind.iseries

    @staticmethod
    def _label_from_platform(platform: PlatformKind) -> str:
        return MODEL_RSERIES if platform == PlatformKind.rseries else MODEL_ISERIES

    def _single_platform(self) -> PlatformKind:
        if self.tmos_only:
            return PlatformKind.iseries
        return self._platform_from_label(self.single_platform_combo.currentText())

    def _needs_f5os_auth(self) -> bool:
        if self.tmos_only:
            return False
        if self.single_radio.isChecked():
            return self._single_platform() == PlatformKind.rseries
        return self.device_table.any_rseries()

    def _clear_common_auth_fields(self) -> None:
        self.user_edit.clear()
        self.pass_edit.clear()
        self.f5os_user_edit.clear()
        self.f5os_pass_edit.clear()

    def _restore_common_auth_defaults(self) -> None:
        if not self.user_edit.text().strip():
            self.user_edit.setText("admin")
        if not self.f5os_user_edit.text().strip():
            self.f5os_user_edit.setText("admin")

    def _refresh_common_auth_panel(self) -> None:
        if self._is_per_device_auth():
            self.auth_group.setVisible(False)
            self._clear_common_auth_fields()
        else:
            self.auth_group.setVisible(True)
            self._restore_common_auth_defaults()
            show_f5os = self._needs_f5os_auth()
            self.f5os_auth_box.setVisible(show_f5os)
            if show_f5os and self.multiple_radio.isChecked():
                self.f5os_auth_box.setToolTip(
                    "목록에 rSeries가 있을 때 표시 — F5OS MGMT IP는 표의 F5OS 행에 입력"
                )

        if self.single_radio.isChecked():
            rseries = (not self.tmos_only) and self._single_platform() == PlatformKind.rseries
            self.f5os_host_label.setVisible(rseries)
            self.f5os_host_edit.setVisible(rseries)
            self.f5os_port_label.setVisible(rseries)
            self.f5os_port_spin.setVisible(rseries)

    def _on_single_platform_changed(self) -> None:
        self._refresh_common_auth_panel()
        self._refresh_session_label()

    def _is_per_device_auth(self) -> bool:
        return self.multiple_radio.isChecked() and self.auth_per_device_radio.isChecked()

    def _on_target_mode_changed(self) -> None:
        multiple = self.multiple_radio.isChecked()
        self.single_group.setVisible(not multiple)
        self.multi_group.setVisible(multiple)
        self.add_from_saved_btn.setVisible(multiple)
        self.session_field_label.setText("목록" if multiple else "프로필")
        self._reload_saved_sessions()
        if multiple:
            self._on_multi_auth_mode_changed()
        else:
            self._refresh_common_auth_panel()
            self._on_single_platform_changed()
        self._refresh_session_label()

    def _on_multi_auth_mode_changed(self) -> None:
        if not self.multiple_radio.isChecked():
            return
        per_device = self._is_per_device_auth()
        rows = self.device_table.snapshot()
        self.device_table.set_per_device_auth(per_device)
        if not rows:
            self.device_table.add_device()
        self._refresh_common_auth_panel()
        self._refresh_session_label()

    def _add_device_entry(self, data: DeviceRowData | None = None) -> None:
        self.device_table.add_device(data)
        self._refresh_common_auth_panel()

    def _remove_device_entries(self) -> None:
        if not self.device_table.remove_selected_device():
            QMessageBox.information(
                self,
                "Remove",
                "삭제할 장비 행을 선택한 뒤 Remove Selected를 누르세요.",
            )
        self._refresh_common_auth_panel()

    def _device_target(
        self,
        *,
        label: str,
        platform: PlatformKind,
        host: str,
        port: int,
        f5os_host: str,
        f5os_port: int,
    ) -> DeviceTarget:
        return DeviceTarget(
            label=label,
            platform=platform,
            host=host,
            port=port,
            f5os_host=f5os_host if platform == PlatformKind.rseries else "",
            f5os_port=f5os_port,
            verify_tls=False,
        )

    def _target_from_data(self, data: DeviceRowData) -> DeviceTarget | None:
        platform = (
            PlatformKind.rseries
            if normalize_device_model(data.model) == MODEL_RSERIES
            else PlatformKind.iseries
        )
        if platform == PlatformKind.iseries and not data.tmos_host:
            return None
        if platform == PlatformKind.rseries and not data.tmos_host and not data.f5os_host:
            return None
        return self._device_target(
            label=data.label,
            platform=platform,
            host=data.tmos_host,
            port=data.tmos_port,
            f5os_host=data.f5os_host,
            f5os_port=data.f5os_port,
        )

    def _credentials_from_data(self, data: DeviceRowData) -> tuple[str, str]:
        if self._is_per_device_auth():
            return data.tmos_user, data.tmos_pass
        return self.user_edit.text().strip() or "admin", self.pass_edit.text()

    def _f5os_credentials_from_data(self, data: DeviceRowData) -> tuple[str, str]:
        if self._is_per_device_auth():
            return data.f5os_user, data.f5os_pass
        return self.f5os_user_edit.text().strip() or "admin", self.f5os_pass_edit.text()

    def _refresh_session_label(self) -> None:
        if self.multiple_radio.isChecked():
            i_cnt = r_cnt = 0
            for data in self.device_table.snapshot():
                if normalize_device_model(data.model) == MODEL_RSERIES:
                    r_cnt += 1
                else:
                    i_cnt += 1
            mode = "장비별" if self._is_per_device_auth() else "공통"
            self.session_label.setText(
                f"연결 상태: Multiple — iSeries/VE {i_cnt}대, rSeries {r_cnt}대, 인증={mode}"
            )
            return
        parts: list[str] = []
        host = self.host_edit.text().strip()
        port = self.port_spin.value()
        tmos = SessionManager.instance().status_text(host, port, scope="tmos")
        if tmos:
            parts.append(tmos)
        if self._single_platform() == PlatformKind.rseries:
            fh = self.f5os_host_edit.text().strip()
            fp = self.f5os_port_spin.value()
            f5os = SessionManager.instance().status_text(fh, fp, scope="f5os")
            if f5os:
                parts.append(f5os)
        self.session_label.setText(
            "연결 상태: " + (" | ".join(parts) if parts else "(없음)")
        )

    def _set_connection_status(self, ok: bool, message: str) -> None:
        color = "#1a7f37" if ok else "#b42318"
        self.session_label.setText(f'<span style="color:{color}">{message}</span>')
        self.session_label.setTextFormat(Qt.TextFormat.RichText)
        self.status_message.emit(message)

    def _is_test_running(self) -> bool:
        return self._test_worker is not None and self._test_worker.isRunning()

    def _build_test_plan(self) -> ConnectionTestOutcome | ConnectionTestPlan:
        if self.single_radio.isChecked():
            platform = self._single_platform()
            return build_single_plan(
                platform=platform,
                label=self.label_edit.text().strip() or "device",
                f5os_host=self.f5os_host_edit.text().strip(),
                f5os_port=self.f5os_port_spin.value(),
                f5os_user=self.f5os_user_edit.text().strip() or "admin",
                f5os_pass=self.f5os_pass_edit.text(),
                tmos_host=self.host_edit.text().strip(),
                tmos_port=self.port_spin.value(),
                tmos_user=self.user_edit.text().strip() or "admin",
                tmos_pass=self.pass_edit.text(),
            )
        return build_multiple_plan(
            self.device_table.snapshot(),
            per_device_auth=self._is_per_device_auth(),
            common_tmos_user=self.user_edit.text().strip() or "admin",
            common_tmos_pass=self.pass_edit.text(),
            common_f5os_user=self.f5os_user_edit.text().strip() or "admin",
            common_f5os_pass=self.f5os_pass_edit.text(),
        )

    def _begin_test_ui(self, total_steps: int) -> None:
        self.test_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, max(total_steps, 1))
        self.test_progress.setValue(0)
        self.test_progress.setFormat("연결 테스트 중… (%v/%m)")
        self.session_label.setText("연결 상태: 테스트 시작…")
        self.session_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_message.emit("연결 테스트 중…")
        self.setCursor(QCursor(Qt.CursorShape.WaitCursor))

    def _on_test_progress(self, current: int, total: int, message: str) -> None:
        self.test_progress.setMaximum(max(total, 1))
        self.test_progress.setValue(current)
        self.test_progress.setFormat(f"연결 테스트 중… ({current}/{total})")
        self.session_label.setText(f"연결 상태: 테스트 중 — {message}")
        self.status_message.emit(f"연결 테스트 ({current}/{total}) {message}")

    def _restore_test_controls(self) -> None:
        self.test_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(True)
        self.test_progress.setVisible(False)
        self.unsetCursor()

    def _release_test_worker(self) -> None:
        worker = self._test_worker
        if worker is None:
            return
        self._test_worker = None
        try:
            worker.progress.disconnect(self._on_test_progress)
        except TypeError:
            pass
        try:
            worker.finished_ok.disconnect(self._on_test_finished)
        except TypeError:
            pass
        try:
            worker.finished.disconnect(self._on_test_thread_finished)
        except TypeError:
            pass
        worker.deleteLater()

    def _on_test_thread_finished(self) -> None:
        self._restore_test_controls()
        worker = self.sender()
        if not isinstance(worker, TestConnectionWorker):
            return
        if worker is self._test_worker:
            self._release_test_worker()
        else:
            worker.deleteLater()

    def _stop_test_worker(self, *, wait_ms: int = 30_000) -> None:
        worker = self._test_worker
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            if not worker.wait(wait_ms):
                worker.terminate()
                worker.wait(2000)
        self._restore_test_controls()
        if worker is self._test_worker:
            self._release_test_worker()
        elif not worker.isRunning():
            worker.deleteLater()

    def _register_sessions(self, outcome: ConnectionTestOutcome) -> None:
        for reg in outcome.sessions:
            SessionManager.instance().set(
                reg.host, reg.port, reg.username, "live-session", scope=reg.scope
            )

    def _test_connection(self) -> None:
        if self._is_test_running():
            return

        built = self._build_test_plan()
        if isinstance(built, ConnectionTestOutcome):
            if built.blocked:
                QMessageBox.warning(self, "Test Connection", built.block_message)
            return

        plan = built
        real_steps = sum(1 for s in plan.steps if s.stack_label in ("F5OS", "TMOS"))
        if real_steps == 0:
            QMessageBox.warning(self, "Test Connection", "테스트할 연결 항목이 없습니다.")
            return

        if self._test_worker is not None:
            self._stop_test_worker(wait_ms=500)

        self._begin_test_ui(real_steps)
        worker = TestConnectionWorker(plan)
        self._test_worker = worker
        worker.progress.connect(self._on_test_progress)
        worker.finished_ok.connect(self._on_test_finished)
        worker.finished.connect(self._on_test_thread_finished)
        worker.start()

    def _on_test_finished(self, outcome: object) -> None:
        ok = False
        if isinstance(outcome, ConnectionTestOutcome):
            ok = outcome.ok_all
            self._register_sessions(outcome)
            self._set_connection_status(outcome.ok_all, outcome.summary)
            self._refresh_session_label()
            title = "Test Connection — Success" if outcome.ok_all else "Test Connection — Failed"
            (QMessageBox.information if outcome.ok_all else QMessageBox.warning)(
                self, title, "\n".join(outcome.lines)
            )
        self.connection_test_finished.emit(ok)

    def _disconnect(self) -> None:
        self._stop_test_worker()
        SessionManager.instance().clear_all()
        self.session_label.setText("연결 상태: 세션 삭제됨")
        self.status_message.emit("Disconnected")
        self.disconnected.emit()

    def tmos_credentials(self) -> tuple[str, int, str, str]:
        """(host, port, username, password) for the Single TMOS form."""
        return (
            self.host_edit.text().strip(),
            int(self.port_spin.value()),
            self.user_edit.text().strip() or "admin",
            self.pass_edit.text(),
        )

    def _connection_from_data(
        self, target: DeviceTarget, data: DeviceRowData
    ) -> ConnectionProfile:
        user, password = self._credentials_from_data(data)
        if not password and target.host.strip():
            raise ValueError(f"{target.label}: TMOS 비밀번호가 필요합니다.")
        f5os_user, f5os_pass = None, None
        if target.platform == PlatformKind.rseries and target.f5os_host.strip():
            f5os_user, f5os_pass = self._f5os_credentials_from_data(data)
            if not f5os_pass:
                raise ValueError(f"{target.label}: F5OS 비밀번호가 필요합니다.")
        return ConnectionProfile(
            target=target,
            username=user,
            password=SecretStr(password or " "),
            f5os_username=f5os_user,
            f5os_password=SecretStr(f5os_pass) if f5os_pass else None,
        )

    def collect_targets_and_connections(
        self,
    ) -> tuple[list[DeviceTarget], list[ConnectionProfile]]:
        if self.single_radio.isChecked():
            platform = self._single_platform()
            target = self._device_target(
                label=self.label_edit.text().strip() or "device",
                platform=platform,
                host=self.host_edit.text().strip(),
                port=self.port_spin.value(),
                f5os_host=self.f5os_host_edit.text().strip(),
                f5os_port=self.f5os_port_spin.value(),
            )
            data = DeviceRowData(
                model=self.single_platform_combo.currentText(),
                label=target.label,
                tmos_host=target.host,
                tmos_port=target.port,
                f5os_host=target.f5os_host,
                f5os_port=target.f5os_port,
                tmos_user=self.user_edit.text().strip() or "admin",
                tmos_pass=self.pass_edit.text(),
                f5os_user=self.f5os_user_edit.text().strip() or "admin",
                f5os_pass=self.f5os_pass_edit.text(),
            )
            return [target], [self._connection_from_data(target, data)]

        targets: list[DeviceTarget] = []
        connections: list[ConnectionProfile] = []
        for data in self.device_table.snapshot():
            target = self._target_from_data(data)
            if target is None:
                continue
            targets.append(target)
            connections.append(self._connection_from_data(target, data))
        return targets, connections

    def _reload_saved_sessions(self) -> None:
        current = self.session_combo.currentData()
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem("(선택 없음)", None)
        if self.multiple_radio.isChecked():
            for item in self.list_store.list_lists():
                n = len(item.devices)
                self.session_combo.addItem(f"{item.label} ({n}대)", item.list_id)
        else:
            for profile in self.profile_store.list_profiles():
                kind = "rSeries" if profile.platform == PlatformKind.rseries else "iSeries"
                text = f"[{kind}] {profile.label}"
                if profile.platform == PlatformKind.rseries and profile.f5os_host:
                    text += f" — F5OS {profile.f5os_host}:{profile.f5os_port}"
                if profile.host:
                    text += f" | TMOS {profile.host}:{profile.port}"
                self.session_combo.addItem(text, profile.profile_id)
        if current:
            idx = self.session_combo.findData(current)
            if idx >= 0:
                self.session_combo.setCurrentIndex(idx)
        self.session_combo.blockSignals(False)

    def _profile_to_row(self, profile) -> DeviceRowData:
        return DeviceRowData(
            model=self._label_from_platform(profile.platform),
            label=profile.label,
            f5os_host=profile.f5os_host,
            f5os_port=profile.f5os_port,
            tmos_host=profile.host,
            tmos_port=profile.port,
            tmos_user=profile.username,
            f5os_user=profile.f5os_username or profile.username,
        )

    def _on_session_profile_selected(self, _index: int) -> None:
        if self.single_radio.isChecked() and self.session_combo.currentData():
            self._load_saved_session(show_pick_hint=False)

    def _load_saved_session(self, *, show_pick_hint: bool = True) -> None:
        item_id = self.session_combo.currentData()
        if not item_id:
            if show_pick_hint:
                hint = (
                    "불러올 목록을 선택하세요."
                    if self.multiple_radio.isChecked()
                    else "불러올 프로필을 선택하세요."
                )
                QMessageBox.information(self, "Load Session", hint)
            return
        if self.multiple_radio.isChecked():
            saved = self.list_store.get(item_id)
            if saved is None:
                QMessageBox.warning(self, "Load Session", "목록을 찾을 수 없습니다.")
                self._reload_saved_sessions()
                return
            self._apply_saved_device_list(saved)
            QMessageBox.information(
                self,
                "Load Session",
                f"장비 목록 불러옴: {saved.label} ({len(saved.devices)}대)",
            )
        else:
            profile = self.profile_store.get(item_id)
            if profile is None:
                QMessageBox.warning(self, "Load Session", "프로필을 찾을 수 없습니다.")
                self._reload_saved_sessions()
                return
            row = self._profile_to_row(profile)
            self.single_platform_combo.blockSignals(True)
            self.single_platform_combo.setCurrentText(row.model)
            self.single_platform_combo.blockSignals(False)
            self.label_edit.setText(row.label)
            self.f5os_host_edit.setText(row.f5os_host)
            self.f5os_port_spin.setValue(row.f5os_port)
            self.host_edit.setText(row.tmos_host)
            self.port_spin.setValue(row.tmos_port)
            self.user_edit.setText(row.tmos_user)
            self.f5os_user_edit.setText(row.f5os_user)
        self._refresh_common_auth_panel()
        self._refresh_session_label()

    def _apply_saved_device_list(self, saved) -> None:
        self.auth_common_radio.blockSignals(True)
        self.auth_per_device_radio.blockSignals(True)
        self.auth_per_device_radio.setChecked(saved.per_device_auth)
        self.auth_common_radio.setChecked(not saved.per_device_auth)
        self.auth_common_radio.blockSignals(False)
        self.auth_per_device_radio.blockSignals(False)
        devices = list(saved.devices)
        self.device_table.set_per_device_auth(saved.per_device_auth)
        if devices:
            self.device_table.rebuild(devices)
        else:
            self.device_table.rebuild([])
            self.device_table.add_device()
        self._refresh_common_auth_panel()

    def _validate_device_row(self, data: DeviceRowData, platform: PlatformKind) -> str | None:
        if platform == PlatformKind.iseries:
            if not data.tmos_host.strip():
                return f"{data.label}: TMOS MGMT IP가 필요합니다."
        elif platform == PlatformKind.rseries:
            if not data.f5os_host.strip():
                return f"{data.label}: F5OS MGMT IP가 필요합니다."
            if not data.tmos_host.strip():
                return f"{data.label}: TMOS (tenant) MGMT IP가 필요합니다."
        return None

    def _save_current_session(self) -> None:
        if self.single_radio.isChecked():
            platform = self._single_platform()
            label = self.label_edit.text().strip()
            host = self.host_edit.text().strip()
            port = self.port_spin.value()
            user = self.user_edit.text().strip() or "admin"
            f5os_host = self.f5os_host_edit.text().strip()
            f5os_port = self.f5os_port_spin.value()
            f5os_user = self.f5os_user_edit.text().strip() or user
        else:
            devices = self.device_table.snapshot()
            if not devices:
                QMessageBox.warning(self, "Save Session", "저장할 장비가 없습니다.")
                return
            for i, data in enumerate(devices):
                err = self._validate_device_row(data, self.device_table.platform_at(i))
                if err:
                    QMessageBox.warning(self, "Save Session", err)
                    return
            name, ok = QInputDialog.getText(
                self,
                "Save List",
                "현재 표 전체를 저장할 목록 이름:",
            )
            if not ok or not name.strip():
                return
            saved = self.list_store.save(
                label=name.strip(),
                per_device_auth=self._is_per_device_auth(),
                devices=devices,
            )
            self._reload_saved_sessions()
            idx = self.session_combo.findData(saved.list_id)
            if idx >= 0:
                self.session_combo.blockSignals(True)
                self.session_combo.setCurrentIndex(idx)
                self.session_combo.blockSignals(False)
            QMessageBox.information(
                self,
                "Save Session",
                f"목록 저장됨: {saved.label} ({len(saved.devices)}대, 비밀번호 미저장)",
            )
            return
        if platform == PlatformKind.iseries:
            if not host:
                QMessageBox.warning(self, "Save Session", "TMOS MGMT IP가 필요합니다.")
                return
        elif platform == PlatformKind.rseries:
            if not f5os_host:
                QMessageBox.warning(self, "Save Session", "rSeries: F5OS MGMT IP가 필요합니다.")
                return
            if not host:
                QMessageBox.warning(
                    self,
                    "Save Session",
                    "rSeries: TMOS (tenant) MGMT IP도 저장하는 것을 권장합니다.",
                )
                return
        self.profile_store.save(
            label=label,
            platform=platform,
            host=host,
            port=port,
            username=user,
            f5os_host=f5os_host,
            f5os_port=f5os_port,
            f5os_username=f5os_user,
        )
        self._reload_saved_sessions()
        QMessageBox.information(self, "Save Session", "저장됨 (비밀번호는 저장하지 않음)")

    def _delete_saved_session(self) -> None:
        item_id = self.session_combo.currentData()
        if not item_id:
            QMessageBox.information(self, "Delete Session", "삭제할 항목을 선택하세요.")
            return
        if self.multiple_radio.isChecked():
            self.list_store.delete(item_id)
        else:
            self.profile_store.delete(item_id)
        self._reload_saved_sessions()

    def _pick_device_profiles(self) -> list[str]:
        profiles = self.profile_store.list_profiles()
        if not profiles:
            return []
        dialog = QDialog(self)
        dialog.setWindowTitle("저장된 장비 선택")
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel("표에 추가할 장비 프로필을 선택하세요 (Ctrl/Shift로 다중 선택).")
        )
        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for profile in profiles:
            kind = "rSeries" if profile.platform == PlatformKind.rseries else "iSeries"
            text = f"[{kind}] {profile.label}"
            if profile.host:
                text += f" — TMOS {profile.host}"
            if profile.f5os_host:
                text += f" | F5OS {profile.f5os_host}"
            row_item = QListWidgetItem(text)
            row_item.setData(Qt.ItemDataRole.UserRole, profile.profile_id)
            list_widget.addItem(row_item)
        layout.addWidget(list_widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return []
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in list_widget.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]

    def _add_row_from_saved(self) -> None:
        self.multiple_radio.setChecked(True)
        profile_ids = self._pick_device_profiles()
        if not profile_ids:
            if not self.profile_store.list_profiles():
                QMessageBox.information(
                    self,
                    "Add from Saved",
                    "저장된 장비 프로필이 없습니다.\n"
                    "Single 모드에서 Save하거나, 표에 직접 입력하세요.",
                )
            return
        added = 0
        for profile_id in profile_ids:
            profile = self.profile_store.get(profile_id)
            if profile is None:
                continue
            self._add_device_entry(self._profile_to_row(profile))
            added += 1
        if added:
            QMessageBox.information(
                self,
                "Add from Saved",
                f"장비 {added}대를 목록에 추가했습니다.",
            )
        self._refresh_common_auth_panel()
        self._refresh_session_label()
