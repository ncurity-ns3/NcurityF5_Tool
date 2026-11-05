"""납품확인서 작성 폼."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.branding import ORG_NAME
from app.gui.form_controls import create_form_combobox
from app.gui.theme import (
    mark_mode_choice_radio,
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
    mark_step_card,
)
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.gui.widgets.ncurity_radio import NcurityRadioButton
from app.modules.delivery_doc import (
    DeliveryFormData,
    ProductItem,
    format_sn_with_cursor,
    generate_delivery_confirmation,
    is_complete_sn,
)
from app.runtime.paths import output_dir

DEVICES = [
    "BIG-IP r2600",
    "BIG-IP r2800",
    "BIG-IP r4600",
    "BIG-IP r4800",
    "BIG-IP r5600",
    "BIG-IP r5800",
    "BIG-IP r5900",
    "BIG-IP r10600",
    "BIG-IP r10800",
    "BIG-IP r10900",
]

VE_LICENSES = [
    "10Mbps",
    "25Mbps",
    "200Mbps",
    "1Gbps",
    "3Gbps",
    "5Gbps",
    "10Gbps",
    "40Gbps",
]

LICENSES = ["APM", "AWAF", "DNS", "LTM", "SSL-O"]

ADD_ONS = [
    "None",
    "APM",
    "AWAF",
    "DNS",
    "LTM",
    "SSL-O",
    "Routing Bundle",
    "CCU",
    "URL Filter",
    "SWG",
]

GBICS = [
    "Multi 1G UTP ( RJ45 )",
    "Multi 1G Fiber ( LC )",
    "Multi 10G Fiber ( LC )",
    "Multi 25G Fiber ( LC )",
    "Multi 40G Fiber ( MPO )",
    "Multi 40G Fiber ( BiDi, LC )",
    "Multi 100G Fiber ( MPO )",
    "Multi 100G Fiber ( Bidi, LC )",
    "Single 1G Fiber",
    "Single 10G Fiber",
]

_SETTINGS_ORG = ORG_NAME
_SETTINGS_APP = "DeliveryConfirmationTool"
_VE_VERSION_KEY = "ve_version"
_DEFAULT_VE_VERSION = "V23"


def _today_header_date() -> str:
    today = date.today()
    return f"{today.year}. {today.month:02d}. {today.day:02d}."


def _cached_ve_version() -> str:
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    value = settings.value(_VE_VERSION_KEY, _DEFAULT_VE_VERSION)
    return str(value) if value else _DEFAULT_VE_VERSION


def _persist_ve_version(text: str) -> None:
    value = text.strip() or _DEFAULT_VE_VERSION
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_VE_VERSION_KEY, value)


class _GbicRow(QWidget):
    """Checkbox + optional qty (digits only) + EA label."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(10)

        self.checkbox = NcurityCheckBox(name)
        row.addWidget(self.checkbox, stretch=1)

        self.qty = QLineEdit()
        self.qty.setPlaceholderText("0")
        self.qty.setFixedWidth(48)
        self.qty.setFixedHeight(30)
        self.qty.setMaxLength(2)
        self.qty.setValidator(QIntValidator(1, 99, self.qty))
        self.qty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qty.setVisible(False)

        self.ea_label = QLabel("EA")
        self.ea_label.setProperty("role", "muted")
        self.ea_label.setVisible(False)

        row.addWidget(self.qty)
        row.addWidget(self.ea_label)
        self.checkbox.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.qty.setVisible(checked)
        self.ea_label.setVisible(checked)
        if checked:
            self.qty.setFocus()
        else:
            self.qty.clear()

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def quantity(self) -> str:
        return self.qty.text().strip()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)
        self.qty.setVisible(checked)
        self.ea_label.setVisible(checked)
        if not checked:
            self.qty.clear()


class ProductRow(QFrame):
    """단일 제품 행 — Appliance / Virtual Edition + 대수 + S/N."""

    remove_requested = pyqtSignal(object)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("productRow")
        self.setStyleSheet(
            "#productRow {"
            "  background-color: #FFFFFF;"
            "  border: 1px solid #E2E8F0;"
            "  border-left: 3px solid #B8D4F0;"
            "  border-radius: 10px;"
            "}"
        )
        self._index = index
        self._sn_updating = False
        self._key_updating = False
        self._sn_edits: list[QLineEdit] = []
        self._sn_wraps: list[QWidget] = []
        self._key_edits: list[QLineEdit] = []
        self._key_wraps: list[QWidget] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel(f"제품 {index}")
        self.title.setProperty("role", "infoTitle")
        header.addWidget(self.title)
        header.addStretch()
        self.remove_btn = QPushButton("삭제")
        mark_secondary_button(self.remove_btn)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(self.remove_btn)
        root.addLayout(header)

        radio_row = QHBoxLayout()
        radio_row.setSpacing(24)
        self.radio_appliance = NcurityRadioButton("Appliance")
        self.radio_ve = NcurityRadioButton("Virtual Edition")
        mark_mode_choice_radio(self.radio_appliance)
        mark_mode_choice_radio(self.radio_ve)
        self.radio_appliance.setChecked(True)
        self.class_group = QButtonGroup(self)
        self.class_group.addButton(self.radio_appliance)
        self.class_group.addButton(self.radio_ve)
        radio_row.addWidget(self.radio_appliance)
        radio_row.addWidget(self.radio_ve)
        radio_row.addStretch()
        root.addLayout(radio_row)

        self.device_label = QLabel("Device")
        self.device_combo = create_form_combobox()
        self.device_combo.addItems(DEVICES)
        root.addWidget(self.device_label)
        root.addWidget(self.device_combo)

        self.ve_version_label = QLabel("VE Version")
        self.ve_version = QLineEdit()
        self.ve_version.setText(_cached_ve_version())
        self.ve_version.setPlaceholderText("예: V23")
        self.ve_version.setMinimumHeight(36)
        self.ve_version.textChanged.connect(_persist_ve_version)
        root.addWidget(self.ve_version_label)
        root.addWidget(self.ve_version)

        self.ve_license_label = QLabel("VE License")
        self.ve_license = create_form_combobox()
        self.ve_license.addItems(VE_LICENSES)
        root.addWidget(self.ve_license_label)
        root.addWidget(self.ve_license)

        qty_row = QHBoxLayout()
        qty_row.setSpacing(8)
        qty_label = QLabel("대수")
        self.quantity = QLineEdit()
        self.quantity.setPlaceholderText("1")
        self.quantity.setText("1")
        self.quantity.setFixedWidth(56)
        self.quantity.setFixedHeight(30)
        self.quantity.setMaxLength(2)
        self.quantity.setValidator(QIntValidator(1, 99, self.quantity))
        self.quantity.setAlignment(Qt.AlignmentFlag.AlignCenter)
        unit = QLabel("대")
        unit.setProperty("role", "muted")
        qty_row.addWidget(qty_label)
        qty_row.addWidget(self.quantity)
        qty_row.addWidget(unit)
        qty_row.addStretch()
        root.addLayout(qty_row)

        self.sn_label = QLabel("S/N")
        root.addWidget(self.sn_label)
        self.sn_hint = QLabel("F5-XXXX-XXXX 형식 · 대시 생략 가능 · 자동 대문자")
        self.sn_hint.setProperty("role", "muted")
        root.addWidget(self.sn_hint)
        self._sn_host = QVBoxLayout()
        self._sn_host.setSpacing(6)
        root.addLayout(self._sn_host)

        self.license_key_label = QLabel("License Key")
        root.addWidget(self.license_key_label)
        self.license_key_hint = QLabel("대수만큼 입력 · 자동 대문자")
        self.license_key_hint.setProperty("role", "muted")
        root.addWidget(self.license_key_hint)
        self._key_host = QVBoxLayout()
        self._key_host.setSpacing(6)
        root.addLayout(self._key_host)

        self.radio_appliance.toggled.connect(self._on_class_changed)
        self.quantity.textChanged.connect(self._rebuild_id_fields)
        self._rebuild_id_fields()
        self._on_class_changed()

    def set_index(self, index: int) -> None:
        self._index = index
        self.title.setText(f"제품 {index}")

    def set_removable(self, removable: bool) -> None:
        self.remove_btn.setVisible(removable)

    def _on_class_changed(self) -> None:
        appliance = self.radio_appliance.isChecked()
        self.device_label.setVisible(appliance)
        self.device_combo.setVisible(appliance)
        for w in (
            self.ve_version_label,
            self.ve_version,
            self.ve_license_label,
            self.ve_license,
        ):
            w.setVisible(not appliance)
        self.sn_label.setVisible(appliance)
        self.sn_hint.setVisible(appliance)
        for wrap in self._sn_wraps:
            wrap.setVisible(appliance)
        self.license_key_label.setVisible(not appliance)
        self.license_key_hint.setVisible(not appliance)
        for wrap in self._key_wraps:
            wrap.setVisible(not appliance)

    def _current_qty(self) -> int:
        text = self.quantity.text().strip()
        if not text:
            return 0
        try:
            return max(0, min(99, int(text)))
        except ValueError:
            return 0

    def _rebuild_id_fields(self) -> None:
        self._rebuild_sn_fields()
        self._rebuild_license_key_fields()

    def _clear_host(self, host: QVBoxLayout) -> None:
        while host.count():
            item = host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_sn_fields(self) -> None:
        qty = self._current_qty()
        old_values = [e.text() for e in self._sn_edits]
        self._clear_host(self._sn_host)
        self._sn_edits.clear()
        self._sn_wraps.clear()

        appliance = self.radio_appliance.isChecked()
        for i in range(qty):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(f"S/N {i + 1}")
            label.setFixedWidth(48)
            edit = QLineEdit()
            edit.setPlaceholderText("F5-XXXX-XXXX")
            edit.setMinimumHeight(30)
            if i < len(old_values):
                edit.setText(old_values[i])
            edit.textChanged.connect(lambda _t, e=edit: self._on_sn_changed(e))
            row.addWidget(label)
            row.addWidget(edit, stretch=1)
            wrap = QWidget()
            wrap.setLayout(row)
            wrap.setVisible(appliance)
            self._sn_host.addWidget(wrap)
            self._sn_wraps.append(wrap)
            self._sn_edits.append(edit)

    def _rebuild_license_key_fields(self) -> None:
        qty = self._current_qty()
        old_values = [e.text() for e in self._key_edits]
        self._clear_host(self._key_host)
        self._key_edits.clear()
        self._key_wraps.clear()

        ve = self.radio_ve.isChecked()
        for i in range(qty):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(f"Key {i + 1}")
            label.setFixedWidth(48)
            edit = QLineEdit()
            edit.setPlaceholderText("영문 대문자 License Key")
            edit.setMinimumHeight(30)
            if i < len(old_values):
                edit.setText(old_values[i])
            edit.textChanged.connect(lambda _t, e=edit: self._on_license_key_changed(e))
            row.addWidget(label)
            row.addWidget(edit, stretch=1)
            wrap = QWidget()
            wrap.setLayout(row)
            wrap.setVisible(ve)
            self._key_host.addWidget(wrap)
            self._key_wraps.append(wrap)
            self._key_edits.append(edit)

    def _on_sn_changed(self, edit: QLineEdit) -> None:
        if self._sn_updating:
            return
        formatted, new_pos = format_sn_with_cursor(edit.text(), edit.cursorPosition())
        if formatted == edit.text():
            return
        self._sn_updating = True
        edit.setText(formatted)
        edit.setCursorPosition(new_pos)
        self._sn_updating = False

    def _on_license_key_changed(self, edit: QLineEdit) -> None:
        if self._key_updating:
            return
        text = edit.text()
        upper = text.upper()
        if upper == text:
            return
        self._key_updating = True
        pos = edit.cursorPosition()
        edit.setText(upper)
        edit.setCursorPosition(pos)
        self._key_updating = False

    def collect(self) -> ProductItem | None:
        qty_text = self.quantity.text().strip()
        if not qty_text:
            return None
        classification = "Appliance" if self.radio_appliance.isChecked() else "Virtual Edition"
        serials = [e.text().strip().upper() for e in self._sn_edits] if classification == "Appliance" else []
        keys = [e.text().strip().upper() for e in self._key_edits] if classification == "Virtual Edition" else []
        return ProductItem(
            classification=classification,
            device=self.device_combo.currentText() if classification == "Appliance" else "",
            ve_version=self.ve_version.text().strip() if classification == "Virtual Edition" else "",
            ve_license=self.ve_license.currentText() if classification == "Virtual Edition" else "",
            quantity=int(qty_text),
            serial_numbers=serials,
            license_keys=keys,
        )

    def validation_error(self) -> str | None:
        if not self.quantity.text().strip():
            return f"제품 {self._index}: 대수를 입력해 주세요."
        qty = self._current_qty()
        if self.radio_appliance.isChecked():
            if len(self._sn_edits) != qty:
                self._rebuild_sn_fields()
            for i, edit in enumerate(self._sn_edits, start=1):
                value = edit.text().strip()
                if not value:
                    return f"제품 {self._index}: S/N {i}을(를) 입력해 주세요."
                if not is_complete_sn(value):
                    return f"제품 {self._index}: S/N {i} 형식을 확인해 주세요. (F5-XXXX-XXXX)"
        else:
            if not self.ve_version.text().strip():
                return f"제품 {self._index}: VE Version을 입력해 주세요."
            if len(self._key_edits) != qty:
                self._rebuild_license_key_fields()
            for i, edit in enumerate(self._key_edits, start=1):
                if not edit.text().strip():
                    return f"제품 {self._index}: License Key {i}을(를) 입력해 주세요."
        return None


class DeliveryFormView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._gbic_updating = False
        self.product_rows: list[ProductRow] = []

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(0, 0, 0, 0)

        title = QLabel("납품확인서 작성")
        mark_page_title(title)
        root.addWidget(title)

        subtitle = QLabel("입력한 값으로 Word 납품확인서를 생성합니다. 품목 상세 표는 이후 단계에서 확장됩니다.")
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(14)

        basic_card = QFrame()
        mark_step_card(basic_card)
        basic_layout = QVBoxLayout(basic_card)
        basic_layout.setContentsMargins(16, 14, 16, 14)
        basic_layout.setSpacing(10)
        basic_title = QLabel("기본 정보")
        basic_title.setProperty("role", "infoTitle")
        basic_layout.addWidget(basic_title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.doc_no = QLineEdit()
        self.doc_no.setPlaceholderText("예: 2026-0001")
        self.author = QLineEdit()
        self.author.setPlaceholderText("작성자 이름")
        self.doc_date = QLineEdit()
        self.doc_date.setText(_today_header_date())
        self.doc_date.setPlaceholderText("예: 2026. 07. 30.")
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("고객사명")
        self.solution = QLineEdit()
        self.solution.setPlaceholderText("솔루션 명")
        self.delivery_place = QLineEdit()
        self.delivery_place.setPlaceholderText("납품 장소")

        form.addRow("문서번호", self.doc_no)
        form.addRow("작성자", self.author)
        form.addRow("작성일자", self.doc_date)
        form.addRow("고객사명", self.customer)
        form.addRow("솔루션 명", self.solution)
        form.addRow("납품 장소", self.delivery_place)
        basic_layout.addLayout(form)
        body_layout.addWidget(basic_card)

        class_card = QFrame()
        mark_step_card(class_card)
        self._product_card_layout = QVBoxLayout(class_card)
        self._product_card_layout.setContentsMargins(16, 14, 16, 14)
        self._product_card_layout.setSpacing(12)

        product_header = QHBoxLayout()
        class_title = QLabel("제품")
        class_title.setProperty("role", "infoTitle")
        product_header.addWidget(class_title)
        product_header.addStretch()
        self.add_product_btn = QPushButton("Add")
        mark_secondary_button(self.add_product_btn)
        self.add_product_btn.clicked.connect(self._add_product_row)
        product_header.addWidget(self.add_product_btn)
        self._product_card_layout.addLayout(product_header)

        product_hint = QLabel("Appliance / Virtual Edition을 조합해 여러 제품을 추가할 수 있습니다.")
        product_hint.setProperty("role", "muted")
        product_hint.setWordWrap(True)
        self._product_card_layout.addWidget(product_hint)

        self._product_list = QVBoxLayout()
        self._product_list.setSpacing(10)
        self._product_card_layout.addLayout(self._product_list)
        body_layout.addWidget(class_card)

        option_card = QFrame()
        mark_step_card(option_card)
        option_layout = QVBoxLayout(option_card)
        option_layout.setContentsMargins(16, 14, 16, 14)
        option_layout.setSpacing(10)
        option_title = QLabel("License")
        option_title.setProperty("role", "infoTitle")
        option_layout.addWidget(option_title)

        option_layout.addWidget(QLabel("License"))
        self.license_combo = create_form_combobox()
        self.license_combo.addItems(LICENSES)
        option_layout.addWidget(self.license_combo)

        option_layout.addWidget(QLabel("Add-On"))
        self.addon_combo = create_form_combobox()
        self.addon_combo.addItems(ADD_ONS)
        self.addon_combo.setCurrentText("None")
        option_layout.addWidget(self.addon_combo)

        self.ccu_label = QLabel("CCU 수량")
        self.ccu_edit = QLineEdit()
        self.ccu_edit.setPlaceholderText("예: 100  →  표시: 100 CCU")
        self.ccu_edit.setMinimumHeight(36)
        option_layout.addWidget(self.ccu_label)
        option_layout.addWidget(self.ccu_edit)

        self.period_label = QLabel("기간 (URL Filter / SWG)")
        self.period_edit = QLineEdit()
        self.period_edit.setPlaceholderText("예시: 1년, 3년, 5년")
        self.period_edit.setMinimumHeight(36)
        option_layout.addWidget(self.period_label)
        option_layout.addWidget(self.period_edit)

        body_layout.addWidget(option_card)

        gbic_card = QFrame()
        mark_step_card(gbic_card)
        gbic_layout = QVBoxLayout(gbic_card)
        gbic_layout.setContentsMargins(16, 14, 16, 14)
        gbic_layout.setSpacing(6)
        gbic_title = QLabel("GBIC")
        gbic_title.setProperty("role", "infoTitle")
        gbic_layout.addWidget(gbic_title)
        hint = QLabel("필요한 모듈을 체크하고 수량을 입력하세요. (숫자만, EA는 자동 표시)")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        gbic_layout.addWidget(hint)

        self.gbic_none = NcurityCheckBox("None")
        self.gbic_none.setChecked(True)
        self.gbic_none.toggled.connect(self._on_gbic_none_toggled)
        gbic_layout.addWidget(self.gbic_none)

        self.gbic_rows: list[_GbicRow] = []
        for name in GBICS:
            row = _GbicRow(name)
            row.checkbox.toggled.connect(self._on_gbic_item_toggled)
            self.gbic_rows.append(row)
            gbic_layout.addWidget(row)

        body_layout.addWidget(gbic_card)
        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.generate_btn = QPushButton("납품확인서 생성")
        mark_primary_button(self.generate_btn)
        self.open_folder_btn = QPushButton("출력 폴더 열기")
        mark_secondary_button(self.open_folder_btn)
        actions.addWidget(self.generate_btn)
        actions.addWidget(self.open_folder_btn)
        actions.addStretch()
        root.addLayout(actions)

        self.addon_combo.currentTextChanged.connect(self._on_addon_changed)
        self.generate_btn.clicked.connect(self._on_generate)
        self.open_folder_btn.clicked.connect(self._on_open_folder)

        self._add_product_row()
        self._on_addon_changed(self.addon_combo.currentText())

    def _add_product_row(self) -> None:
        if self.product_rows:
            sep = QFrame()
            sep.setObjectName("productSep")
            sep.setFixedHeight(1)
            sep.setStyleSheet(
                "QFrame#productSep {"
                "  background-color: #B8D4F0;"
                "  border: none;"
                "  max-height: 1px;"
                "}"
            )
            self._product_list.addWidget(sep)
        row = ProductRow(len(self.product_rows) + 1)
        row.remove_requested.connect(self._remove_product_row)
        self.product_rows.append(row)
        self._product_list.addWidget(row)
        self._refresh_product_headers()

    def _remove_product_row(self, row: ProductRow) -> None:
        if len(self.product_rows) <= 1:
            return
        layout_index = self._product_list.indexOf(row)
        if layout_index > 0:
            prev = self._product_list.itemAt(layout_index - 1)
            if prev is not None:
                prev_w = prev.widget()
                if prev_w is not None and prev_w.objectName() == "productSep":
                    self._product_list.removeWidget(prev_w)
                    prev_w.deleteLater()
        self.product_rows.remove(row)
        self._product_list.removeWidget(row)
        row.deleteLater()
        self._refresh_product_headers()
        if self._product_list.count() > 0:
            first = self._product_list.itemAt(0)
            if first is not None:
                first_w = first.widget()
                if first_w is not None and first_w.objectName() == "productSep":
                    self._product_list.removeWidget(first_w)
                    first_w.deleteLater()

    def _refresh_product_headers(self) -> None:
        removable = len(self.product_rows) > 1
        for i, row in enumerate(self.product_rows, start=1):
            row.set_index(i)
            row.set_removable(removable)

    def _on_gbic_none_toggled(self, checked: bool) -> None:
        if self._gbic_updating:
            return
        if checked:
            self._gbic_updating = True
            for row in self.gbic_rows:
                row.set_checked(False)
            self._gbic_updating = False
        elif not any(row.is_selected() for row in self.gbic_rows):
            self._gbic_updating = True
            self.gbic_none.setChecked(True)
            self._gbic_updating = False

    def _on_gbic_item_toggled(self, checked: bool) -> None:
        if self._gbic_updating:
            return
        if checked:
            self._gbic_updating = True
            self.gbic_none.setChecked(False)
            self._gbic_updating = False
        elif not any(row.is_selected() for row in self.gbic_rows):
            self._gbic_updating = True
            self.gbic_none.setChecked(True)
            self._gbic_updating = False

    def _on_addon_changed(self, text: str) -> None:
        is_ccu = text == "CCU"
        is_period = text in ("URL Filter", "SWG")
        self.ccu_label.setVisible(is_ccu)
        self.ccu_edit.setVisible(is_ccu)
        self.period_label.setVisible(is_period)
        self.period_edit.setVisible(is_period)

    def _collect_gbic_items(self) -> list[tuple[str, int]] | None:
        if self.gbic_none.isChecked():
            return []
        items: list[tuple[str, int]] = []
        for row in self.gbic_rows:
            if not row.is_selected():
                continue
            qty_text = row.quantity()
            if not qty_text:
                QMessageBox.warning(
                    self,
                    "입력 확인",
                    f"GBIC 수량을 입력해 주세요.\n• {row.name}",
                )
                return None
            items.append((row.name, int(qty_text)))
        if not items:
            QMessageBox.warning(self, "입력 확인", "GBIC을 선택하거나 None을 체크해 주세요.")
            return None
        return items

    def _collect_products(self) -> list[ProductItem] | None:
        products: list[ProductItem] = []
        for row in self.product_rows:
            err = row.validation_error()
            if err:
                QMessageBox.warning(self, "입력 확인", err)
                return None
            item = row.collect()
            if item is None:
                QMessageBox.warning(self, "입력 확인", f"제품 {row._index}: 입력을 확인해 주세요.")
                return None
            products.append(item)
        if not products:
            QMessageBox.warning(self, "입력 확인", "제품을 하나 이상 추가해 주세요.")
            return None
        return products

    def _collect(self) -> DeliveryFormData | None:
        required = [
            ("문서번호", self.doc_no.text()),
            ("작성자", self.author.text()),
            ("작성일자", self.doc_date.text()),
            ("고객사명", self.customer.text()),
            ("솔루션 명", self.solution.text()),
            ("납품 장소", self.delivery_place.text()),
        ]
        missing = [name for name, value in required if not value.strip()]
        if missing:
            QMessageBox.warning(self, "입력 확인", f"다음 항목을 입력해 주세요.\n• " + "\n• ".join(missing))
            return None

        products = self._collect_products()
        if products is None:
            return None

        addon = self.addon_combo.currentText()
        addon_detail = ""
        if addon == "CCU":
            ccu = self.ccu_edit.text().strip()
            if not ccu:
                QMessageBox.warning(self, "입력 확인", "CCU 수량을 입력해 주세요.")
                return None
            addon_detail = f"{ccu} CCU"
        elif addon in ("URL Filter", "SWG"):
            period = self.period_edit.text().strip()
            if not period:
                QMessageBox.warning(self, "입력 확인", "기간을 입력해 주세요. (예: 1년, 3년, 5년)")
                return None
            addon_detail = period

        gbic_items = self._collect_gbic_items()
        if gbic_items is None:
            return None

        return DeliveryFormData(
            doc_no=self.doc_no.text().strip(),
            author=self.author.text().strip(),
            doc_date=self.doc_date.text().strip(),
            customer=self.customer.text().strip(),
            solution=self.solution.text().strip(),
            delivery_place=self.delivery_place.text().strip(),
            products=products,
            license_name=self.license_combo.currentText(),
            add_on=addon,
            add_on_detail=addon_detail,
            gbic_items=gbic_items,
        )

    def _on_generate(self) -> None:
        data = self._collect()
        if data is None:
            return
        try:
            path = generate_delivery_confirmation(data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "생성 실패", str(exc))
            return
        QMessageBox.information(self, "생성 완료", f"납품확인서를 생성했습니다.\n\n{path}")

    def _on_open_folder(self) -> None:
        folder = str(output_dir())
        try:
            import os

            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            QMessageBox.information(self, "출력 폴더", folder)
