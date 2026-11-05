from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.gui.theme import mark_page_subtitle


class LoadingProgressDialog(QDialog):
    """Modal 0–100% progress; closes itself when it reaches 100%."""

    def __init__(self, title: str, message: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setMinimumWidth(420)
        self._closing = False

        root = QVBoxLayout(self)
        self.message = QLabel(message or title)
        self.message.setWordWrap(True)
        mark_page_subtitle(self.message)
        root.addWidget(self.message)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setProperty("role", "muted")
        root.addWidget(self.detail)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p%")
        root.addWidget(self.bar)

    def set_progress(self, current: int, total: int, detail: str = "") -> None:
        total = max(int(total), 1)
        current = max(0, min(int(current), total))
        percent = int(current * 100 / total)
        self.bar.setValue(percent)
        if detail:
            self.detail.setText(f"{detail}  ({current}/{total})")
        else:
            self.detail.setText(f"{current} / {total}")

    def finish(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.bar.setValue(100)
        QTimer.singleShot(220, self.accept)

    def fail_and_close(self) -> None:
        self._closing = True
        self.reject()
