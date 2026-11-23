"""Line icon for showing or hiding a side panel. Matches the sidebar stroke, not a checkbox."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton


class PanelToggle(QAbstractButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._open = True
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_open(self, opened: bool) -> None:
        self._open = opened
        self.update()

    def is_open(self) -> bool:
        return self._open

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#EDF5FF"))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        stroke = QColor("#0260EA" if self.underMouse() or self._open else "#64748B")
        painter.setPen(QPen(stroke, 1.4))
        painter.setBrush(QColor("#F4F8FF") if self._open else Qt.GlobalColor.transparent)
        box = QRectF(5, 7, 18, 14)
        painter.drawRoundedRect(box, 2, 2)
        bar = box.left() + 6
        painter.drawLine(int(bar), int(box.top() + 2), int(bar), int(box.bottom() - 2))
        if self._open:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#0260EA"))
            bar_rect = QRectF(box.left() + 2, box.top() + 3, 2.4, box.height() - 6)
            painter.drawRoundedRect(bar_rect, 1, 1)
