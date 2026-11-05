"""Radio button with painted blue selection (Windows QSS indicator is often black)."""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QRadioButton, QWidget

from app.gui.theme import BRAND_ACCENT, BRAND_PRIMARY, BG_SURFACE, BORDER_STRONG, TEXT, TEXT_MUTED

_INDICATOR = 20
_DOT = 10
_SPACING = 10


class NcurityRadioButton(QRadioButton):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        w = _INDICATOR + _SPACING + text_w + 8
        h = max(base.height(), _INDICATOR + 8)
        return QSize(w, h)

    def hitButton(self, pos) -> bool:  # noqa: ANN001
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        ind_y = (self.height() - _INDICATOR) // 2
        outer = QRect(0, ind_y, _INDICATOR, _INDICATOR)
        text_left = _INDICATOR + _SPACING
        text_rect = QRect(text_left, 0, max(0, self.width() - text_left), self.height())

        if self.isChecked():
            border = QColor(BRAND_PRIMARY)
            fill = QColor(BG_SURFACE)
        else:
            border = QColor(BORDER_STRONG)
            fill = QColor(BG_SURFACE)

        if not self.isEnabled():
            fill = QColor("#F1F5F9")
            border = QColor("#CBD5E1")

        painter.setBrush(fill)
        painter.setPen(QPen(border, 2))
        painter.drawEllipse(outer.adjusted(1, 1, -1, -1))

        if self.isChecked():
            dot_x = outer.x() + (_INDICATOR - _DOT) // 2
            dot_y = outer.y() + (_INDICATOR - _DOT) // 2
            dot = QRect(dot_x, dot_y, _DOT, _DOT)
            painter.setBrush(QColor(BRAND_PRIMARY))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot)

        weight = QFont.Weight.Medium if self.isChecked() else QFont.Weight.Normal
        role = self.property("role")
        if role == "modeChoiceRadio":
            weight = QFont.Weight.Medium

        painter.setPen(QColor(TEXT if self.isEnabled() else TEXT_MUTED))
        font = self.font()
        font.setWeight(weight)
        painter.setFont(font)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )

        if self.hasFocus():
            focus = outer.adjusted(-2, -2, 2, 2)
            painter.setPen(QPen(QColor(BRAND_ACCENT), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(focus)
