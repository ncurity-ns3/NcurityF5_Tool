from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from app.gui.form_controls import configure_form_combobox
from app.modules.os_upgrade.k7727_versions import load_k7727_versions


class PreChecklistDialog(QDialog):
    """작업 전 Check List — 목표 TMOS 버전 선택 (K7727)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("작업 전 Check List")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "업그레이드 목표 버전을 선택하세요.\n"
                "Service Check Date와 K7727 License Check Date를 비교합니다."
            )
        )

        form = QFormLayout()
        self.version_combo = QComboBox()
        configure_form_combobox(self.version_combo)
        self._entries = load_k7727_versions()
        for ent in self._entries:
            self.version_combo.addItem(ent.label, ent.version)
        if self._entries:
            self.version_combo.setCurrentIndex(0)
        form.addRow("목표 버전", self.version_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_version_key(self) -> str:
        return str(self.version_combo.currentData() or "")
