from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.models import PlatformKind
from app.gui.device_models import MODEL_ISERIES, MODEL_RSERIES, normalize_device_model
from app.gui.form_controls import PortSpinBox, configure_port_spinbox, create_form_combobox
from app.gui.theme import mark_device_card

__all__ = ["MODEL_ISERIES", "MODEL_RSERIES", "DeviceRowData", "normalize_device_model"]


@dataclass
class DeviceRowData:
    model: str = MODEL_ISERIES
    label: str = "device"
    f5os_host: str = ""
    f5os_port: int = 443
    tmos_host: str = ""
    tmos_port: int = 443
    tmos_user: str = "admin"
    tmos_pass: str = ""
    f5os_user: str = "admin"
    f5os_pass: str = ""


class MultiDeviceEntryWidget(QGroupBox):
    """one device — two lines: mgmt row + optional auth row (no cramped table)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.setTitle("장비")
        mark_device_card(self)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.model_combo = create_form_combobox()
        self.model_combo.addItems([MODEL_ISERIES, MODEL_RSERIES])
        if self.model_combo.count() > 0:
            self.model_combo.setCurrentIndex(0)
        self.label_edit = QLineEdit("device")
        self.label_edit.setPlaceholderText("장비 라벨")
        top.addWidget(QLabel("Model"))
        top.addWidget(self.model_combo)
        top.addWidget(QLabel("Label"))
        top.addWidget(self.label_edit, stretch=1)
        root.addLayout(top)

        self.f5os_block = QGroupBox("F5OS MGMT (rSeries)")
        f5os_form = QFormLayout(self.f5os_block)
        self.f5os_host_edit = QLineEdit()
        self.f5os_host_edit.setPlaceholderText("F5OS MGMT IP")
        self.f5os_port_spin = PortSpinBox()
        self.f5os_port_spin.setRange(1, 65535)
        self.f5os_port_spin.setValue(443)
        f5os_form.addRow("F5OS MGMT IP", self.f5os_host_edit)
        f5os_form.addRow("F5OS Port", self.f5os_port_spin)
        root.addWidget(self.f5os_block)

        self.tmos_block = QGroupBox("TMOS MGMT")
        tmos_form = QFormLayout(self.tmos_block)
        self.tmos_host_edit = QLineEdit()
        self.tmos_host_edit.setPlaceholderText("TMOS MGMT IP")
        self.tmos_port_spin = PortSpinBox()
        self.tmos_port_spin.setRange(1, 65535)
        self.tmos_port_spin.setValue(443)
        tmos_form.addRow("TMOS MGMT IP", self.tmos_host_edit)
        tmos_form.addRow("TMOS Port", self.tmos_port_spin)
        root.addWidget(self.tmos_block)

        self.auth_block = QGroupBox("인증 (장비별)")
        auth_form = QFormLayout(self.auth_block)
        self.tmos_user_edit = QLineEdit("admin")
        self.tmos_pass_edit = QLineEdit()
        self.tmos_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.f5os_user_edit = QLineEdit("admin")
        self.f5os_pass_edit = QLineEdit()
        self.f5os_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        auth_form.addRow("TMOS 사용자 ID", self.tmos_user_edit)
        auth_form.addRow("TMOS 비밀번호", self.tmos_pass_edit)
        self.f5os_user_label = QLabel("F5OS 사용자 ID")
        auth_form.addRow(self.f5os_user_label, self.f5os_user_edit)
        self.f5os_pass_label = QLabel("F5OS 비밀번호")
        auth_form.addRow(self.f5os_pass_label, self.f5os_pass_edit)
        root.addWidget(self.auth_block)
        self.auth_block.setVisible(False)

        configure_port_spinbox(self.f5os_port_spin)
        configure_port_spinbox(self.tmos_port_spin)

        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.label_edit.textChanged.connect(self._update_title)
        self._on_model_changed()

    def _update_title(self) -> None:
        label = self.label_edit.text().strip() or "장비"
        model = self.model_combo.currentText()
        self.setTitle(f"{label} — {model}")

    def _on_model_changed(self) -> None:
        rseries = self.platform() == PlatformKind.rseries
        self.f5os_block.setVisible(rseries)
        self.f5os_user_label.setVisible(rseries)
        self.f5os_user_edit.setVisible(rseries)
        self.f5os_pass_label.setVisible(rseries)
        self.f5os_pass_edit.setVisible(rseries)
        if not rseries:
            self.f5os_host_edit.clear()
        self._update_title()

    def platform(self) -> PlatformKind:
        if self.model_combo.currentText() == MODEL_RSERIES:
            return PlatformKind.rseries
        return PlatformKind.iseries

    def set_per_device_auth(self, enabled: bool) -> None:
        self.auth_block.setVisible(enabled)

    def to_data(self) -> DeviceRowData:
        return DeviceRowData(
            model=self.model_combo.currentText(),
            label=self.label_edit.text().strip() or "device",
            f5os_host=self.f5os_host_edit.text().strip(),
            f5os_port=self.f5os_port_spin.value(),
            tmos_host=self.tmos_host_edit.text().strip(),
            tmos_port=self.tmos_port_spin.value(),
            tmos_user=self.tmos_user_edit.text().strip() or "admin",
            tmos_pass=self.tmos_pass_edit.text(),
            f5os_user=self.f5os_user_edit.text().strip() or "admin",
            f5os_pass=self.f5os_pass_edit.text(),
        )

    def load_data(self, data: DeviceRowData) -> None:
        self.model_combo.setCurrentText(normalize_device_model(data.model))
        self.label_edit.setText(data.label)
        self.f5os_host_edit.setText(data.f5os_host)
        self.f5os_port_spin.setValue(data.f5os_port)
        self.tmos_host_edit.setText(data.tmos_host)
        self.tmos_port_spin.setValue(data.tmos_port)
        self.tmos_user_edit.setText(data.tmos_user)
        self.tmos_pass_edit.setText(data.tmos_pass)
        self.f5os_user_edit.setText(data.f5os_user)
        self.f5os_pass_edit.setText(data.f5os_pass)
        self._on_model_changed()
