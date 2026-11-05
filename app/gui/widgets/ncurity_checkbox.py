"""Checkbox with clear checked (blue) vs unchecked (white border) states."""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QCheckBox, QWidget

from app.gui.theme import BRAND_ACCENT, BRAND_PRIMARY, BG_SURFACE, BORDER_STRONG, TEXT, TEXT_MUTED

_INDICATOR = 20
_INDICATOR_LARGE = 28
_SPACING = 10
_SPACING_LARGE = 12


class NcurityCheckBox(QCheckBox):
    """Painted indicator — reliable on Fusion/Windows (no QSS image quirks)."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        large: bool = False,
    ) -> None:
        super().__init__(text, parent)
        self._large = large
        self._indicator = _INDICATOR_LARGE if large else _INDICATOR
        self._spacing = _SPACING_LARGE if large else _SPACING
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if large:
            font = self.font()
            font.setPointSize(max(font.pointSize(), 11))
            self.setFont(font)

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        w = self._indicator + self._spacing + text_w + 12
        h = max(base.height(), self._indicator + (14 if self._large else 8))
        return QSize(w, h)

    def hitButton(self, pos) -> bool:  # noqa: ANN001
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        ind_y = (self.height() - self._indicator) // 2
        box = QRect(0, ind_y, self._indicator, self._indicator)
        text_left = self._indicator + self._spacing
        text_rect = QRect(text_left, 0, max(0, self.width() - text_left), self.height())

        if self.isChecked():
            fill = QColor(BRAND_PRIMARY)
            border = QColor(BRAND_PRIMARY)
        else:
            fill = QColor(BG_SURFACE)
            border = QColor(BORDER_STRONG)

        if not self.isEnabled():
            fill = QColor("#F1F5F9")
            border = QColor("#CBD5E1")

        painter.setBrush(fill)
        painter.setPen(QPen(border, 2))
        painter.drawRoundedRect(box.adjusted(1, 1, -1, -1), 5, 5)

        if self.isChecked():
            pen = QPen(QColor("#FFFFFF"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            x, y, w, h = box.x(), box.y(), box.width(), box.height()
            painter.drawLine(x + 5, y + h // 2 + 1, x + w // 2 - 1, y + h - 5)
            painter.drawLine(x + w // 2 - 1, y + h - 5, x + w - 5, y + 5)

        painter.setPen(QColor(TEXT if self.isEnabled() else TEXT_MUTED))
        font = self.font()
        font.setWeight(QFont.Weight.Medium if self.isChecked() else QFont.Weight.Normal)
        painter.setFont(font)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )

        if self.hasFocus():
            focus = box.adjusted(-2, -2, 2, 2)
            painter.setPen(QPen(QColor(BRAND_ACCENT), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(focus, 6, 6)
