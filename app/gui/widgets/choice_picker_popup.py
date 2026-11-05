"""Dropdown popup for FormComboBox / table model picker (Ncurity style)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsDropShadowEffect,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

_ITEM_ROW_PX = 40
_POPUP_FONT_PT = 10


class ChoicePickerPopup(QFrame):
    """Rounded list under the field — tall rows, readable text, exact height."""

    choice_selected = pyqtSignal(str)

    def __init__(
        self,
        anchor: QPoint,
        width: int,
        choices: list[str],
        current: str,
        _parent=None,
        *,
        gap_below: int = 4,
    ) -> None:
        # Parenting a Qt.Popup to a dialog steals/shrinks that dialog's geometry
        # when the popup closes (Load Macro Access Profile combo). Keep it top-level.
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("modelPickerPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
        self.setPalette(pal)
        self.setStyleSheet(
            "QFrame#modelPickerPopup {"
            "  background-color: #FFFFFF;"
            "  border: 1px solid #0260EA;"
            "  border-radius: 8px;"
            "}"
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 35, 50, 28))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        list_font = QFont()
        list_font.setPointSize(_POPUP_FONT_PT)
        list_font.setWeight(QFont.Weight.Medium)
        fm = QFontMetrics(list_font)
        min_popup_w = max(
            (fm.horizontalAdvance(c) for c in choices),
            default=120,
        ) + 32

        self._list = QListWidget()
        self._list.setFont(list_font)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if len(choices) > 8
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.setVerticalScrollBarPolicy(scroll)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setMouseTracking(True)
        self._list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item {"
            "  padding: 8px 14px;"
            "  color: #1A2332;"
            "  background: transparent;"
            "}"
            "QListWidget::item:selected { background: transparent; color: #1A2332; }"
            "QListWidget::item:hover {"
            "  background-color: #0260EA;"
            "  color: #FFFFFF;"
            "}"
        )
        for label in choices:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, _ITEM_ROW_PX))
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self._list.addItem(item)
        self._list.itemClicked.connect(self._on_item)
        layout.addWidget(self._list)

        row_count = len(choices)
        visible_rows = min(row_count, 8)
        list_h = visible_rows * _ITEM_ROW_PX + 2
        self._list.setFixedHeight(list_h)
        frame_h = list_h + 8
        self.setFixedWidth(max(width, min_popup_w, 220))
        self.setFixedHeight(frame_h)
        self.move(anchor + QPoint(0, gap_below))

    def _on_item(self, item: QListWidgetItem) -> None:
        self.choice_selected.emit(item.text())
        self.close()
