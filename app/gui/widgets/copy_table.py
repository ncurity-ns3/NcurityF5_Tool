"""Selectable table text and a header sort icon on the right of each column."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPolygon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)

from app.gui.theme import BRAND_PRIMARY, TEXT


class SortHeader(QHeaderView):
    """Click a column to sort. Every column shows an up/down icon on the right."""

    sort_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._column = -1
        self._ascending = True
        self._skip: set[int] = set()
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setSortIndicatorShown(False)
        self._use_hand_cursor()
        self.sectionClicked.connect(self._on_click)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._use_hand_cursor()
        super().enterEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        if self.cursor().shape() == Qt.CursorShape.SplitHCursor:
            return
        self._use_hand_cursor()

    def _use_hand_cursor(self) -> None:
        hand = Qt.CursorShape.PointingHandCursor
        self.setCursor(hand)
        self.viewport().setCursor(hand)

    @property
    def column(self) -> int:
        return self._column

    @property
    def ascending(self) -> bool:
        return self._ascending

    def set_skip(self, columns: set[int]) -> None:
        self._skip = set(columns)

    def set_state(self, column: int, ascending: bool) -> None:
        self._column = column
        self._ascending = ascending
        self.viewport().update()

    def _on_click(self, index: int) -> None:
        if index in self._skip:
            return
        if index == self._column:
            self._ascending = not self._ascending
        else:
            self._column = index
            self._ascending = True
        self.viewport().update()
        self.sort_requested.emit(index)

    def paintSection(self, painter: QPainter | None, rect, logical_index: int) -> None:  # noqa: N802
        if painter is None:
            return
        super().paintSection(painter, rect, logical_index)
        if logical_index in self._skip:
            return
        active = logical_index == self._column
        up = BRAND_PRIMARY if active and self._ascending else "#CBD5E1"
        down = BRAND_PRIMARY if active and not self._ascending else "#CBD5E1"
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = rect.right() - 16
        mid = rect.center().y()
        _triangle(painter, x, mid - 8, up=True, color=up)
        _triangle(painter, x, mid + 2, up=False, color=down)
        painter.restore()


def install_sort_header(table: QTableWidget, *, skip: set[int] | None = None) -> SortHeader:
    header = SortHeader(table)
    header.set_skip(skip or set())
    table.setHorizontalHeader(header)
    header.setHighlightSections(False)
    header.setStretchLastSection(True)
    header.setMinimumSectionSize(72)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    font = QFont()
    font.setPointSize(10)
    font.setWeight(QFont.Weight.DemiBold)
    header.setFont(font)
    header.setStretchLastSection(False)
    header._use_hand_cursor()
    table.setProperty("role", "copyGrid")
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setCursor(Qt.CursorShape.IBeamCursor)
    table.viewport().setCursor(Qt.CursorShape.IBeamCursor)
    table.setItemDelegate(_CellTextDelegate(table))
    style = table.style()
    style.unpolish(table)
    style.polish(table)
    return header


class _CellTextDelegate(QStyledItemDelegate):
    """Skip item text when a cell widget already draws it, so the two do not overlap."""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001
        view = self.parent()
        if isinstance(view, QTableWidget) and view.cellWidget(index.row(), index.column()):
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            opt.features = opt.features & ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
            widget = opt.widget
            style = widget.style() if widget is not None else view.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
            return
        super().paint(painter, option, index)


def selectable_label(
    text: str,
    *,
    background: str = "#FFFFFF",
    color: str = TEXT,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    wrap: bool = False,
) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setAlignment(align)
    label.setToolTip(text)
    label.setCursor(Qt.CursorShape.IBeamCursor)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    label.setAutoFillBackground(True)
    label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    label.setStyleSheet(
        "QLabel {"
        f" background: {background}; color: {color}; padding: 6px 10px;"
        "}"
        "QLabel:hover {"
        f" background: #E8F1FF; color: {color};"
        "}"
    )
    return label


def _triangle(painter: QPainter, x: int, y: int, *, up: bool, color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if up:
        points = [QPoint(x, y + 5), QPoint(x + 8, y + 5), QPoint(x + 4, y)]
    else:
        points = [QPoint(x, y), QPoint(x + 8, y), QPoint(x + 4, y + 5)]
    painter.drawPolygon(QPolygon(points))
