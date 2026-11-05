"""Shared form control setup (theme helpers)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QComboBox, QLineEdit, QSizePolicy, QSpinBox, QWidget


class PortSpinBox(QSpinBox):
    """Port 입력 — 마우스 휠로 값이 바뀌지 않음 (스크롤은 부모로 전달)."""

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class FormComboBox(QComboBox):
    """Form combo — rounded ChoicePickerPopup instead of square OS list."""

    def showPopup(self) -> None:  # noqa: N802
        if self.property("formControl") != "formCombo" or self.count() == 0:
            super().showPopup()
            return
        from app.gui.widgets.choice_picker_popup import ChoicePickerPopup

        choices = [self.itemText(i) for i in range(self.count())]
        anchor = self.mapToGlobal(QPoint(0, self.height()))
        popup = ChoicePickerPopup(
            anchor,
            self.width(),
            choices,
            self.currentText(),
            self.window(),
            gap_below=4,
        )
        self._choice_popup = popup
        popup.choice_selected.connect(self._apply_choice)
        popup.destroyed.connect(lambda _obj=None: setattr(self, "_choice_popup", None))
        popup.show()

    def _apply_choice(self, label: str) -> None:
        idx = self.findText(label)
        if idx >= 0 and idx != self.currentIndex():
            self.setCurrentIndex(idx)
        elif idx >= 0:
            self.currentTextChanged.emit(self.currentText())


def configure_form_combobox(combo: QComboBox) -> None:
    """Dropdown in forms / dialogs (readable height + font)."""
    combo.setProperty("formControl", "formCombo")
    combo.setFixedHeight(36)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    _repolish(combo)


def create_form_combobox() -> FormComboBox:
    combo = FormComboBox()
    configure_form_combobox(combo)
    return combo


def configure_table_lineedit(edit: QLineEdit) -> None:
    """Compact line edit inside QTableWidget cells (must fit row height)."""
    edit.setProperty("formControl", "tableLine")
    edit.setFixedHeight(26)
    edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _repolish(edit)


def configure_table_combobox(combo: QComboBox) -> None:
    """Compact combo inside QTableWidget cells."""
    combo.setProperty("formControl", "tableCombo")
    combo.setMaximumHeight(24)
    combo.setMinimumHeight(22)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    _repolish(combo)


def configure_port_spinbox(spin: QSpinBox) -> None:
    """Port fields: type numbers directly, no up/down arrows, no wheel."""
    spin.setProperty("formControl", "portSpin")
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    spin.setFixedHeight(30)
    spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    _repolish(spin)


def apply_form_control_policies(root: QWidget) -> None:
    """Apply port spinbox policy to form spinboxes only (not table text cells)."""
    for spin in root.findChildren(QSpinBox):
        if spin.property("formControl") != "portSpin":
            configure_port_spinbox(spin)
