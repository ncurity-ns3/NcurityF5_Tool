"""Multiple device table — 2 rows per rSeries; Model/Label span (PRD §3.3)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QKeyEvent, QMouseEvent, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLineEdit,
    QSizePolicy,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import PlatformKind
from app.gui.device_models import MODEL_ISERIES, MODEL_RSERIES, normalize_device_model
from app.gui.form_controls import configure_table_lineedit
from app.gui.theme import (
    apply_device_table_style,
    mark_device_table_shell,
    polish_widget_scrollbars,
)
from app.gui.widgets.choice_picker_popup import ChoicePickerPopup
from app.gui.widgets.multi_device_entry import DeviceRowData

COL_MODEL = 0
COL_LABEL = 1
COL_STACK = 2
COL_MGMT = 3
COL_PORT = 4
COL_USER = 5
COL_PASS = 6

_STACK_F5OS = "F5OS"
_STACK_TMOS = "TMOS"

_IDLE_BG = QColor("#FFFFFF")
_SEL_BG = QColor("#0260EA")
_SEL_SIBLING_BG = QColor("#5C9DF5")
_SEL_FG = QColor("#FFFFFF")
_SEL_SIBLING_FG = QColor("#E8F2FF")
_IDLE_FG = QColor("#1A2332")
_STACK_ACCENT = QColor("#0260EA")
_ZEBRA_EVEN = QColor("#FBFDFF")
_ZEBRA_ODD = QColor("#F3F8FD")
_TABLE_LINE_H = 26
_CELL_ALIGN = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter


def _role_color(value: object, fallback: QColor) -> QColor:
    if isinstance(value, QBrush) and value.style() != Qt.BrushStyle.NoBrush:
        return value.color()
    if isinstance(value, QColor) and value.isValid():
        return value
    return fallback


class _DeviceGridItemDelegate(QStyledItemDelegate):
    """Paint BackgroundRole/ForegroundRole ourselves.

    The installer ships only qmodernwindowsstyle.dll. That Windows 11 style
    ignores QTableWidgetItem.setBackground() when QSS defines ::item rules, so
    customer PCs see a focus ring with no blue row fill. Fusion on the
    developer PC still honors the item brush.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        cell_rect = option.rect
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.rect = cell_rect
        opt.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_HasFocus
            | QStyle.StateFlag.State_MouseOver
        )

        painter.save()
        painter.setClipRect(cell_rect)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        fill = _role_color(
            index.data(Qt.ItemDataRole.BackgroundRole), _IDLE_BG
        )
        painter.fillRect(cell_rect, fill)

        fg = _role_color(
            index.data(Qt.ItemDataRole.ForegroundRole), _IDLE_FG
        )
        painter.setPen(fg)

        font_role = index.data(Qt.ItemDataRole.FontRole)
        painter.setFont(font_role if isinstance(font_role, QFont) else opt.font)

        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text is None:
            text = ""
        align = index.data(Qt.ItemDataRole.TextAlignmentRole)
        if align is None:
            align = int(opt.displayAlignment)
        text_rect = opt.rect.adjusted(6, 0, -6, 0)
        painter.drawText(text_rect, int(align), str(text))
        painter.restore()


@dataclass
class _DeviceBlock:
    start_row: int
    row_count: int


def _qt_alive(widget: QObject | None) -> bool:
    if widget is None:
        return False
    try:
        import shiboken6

        return bool(shiboken6.isValid(widget))
    except Exception:  # noqa: BLE001
        try:
            _ = widget.metaObject()  # type: ignore[union-attr]
            return True
        except RuntimeError:
            return False


class _CellWidgetInteractionFilter(QObject):
    """Password/cell widgets: click or focus selects the whole device block (blue)."""

    def __init__(self, panel: "MultiDeviceTablePanel") -> None:
        super().__init__(panel)
        self._panel = panel

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if not self._panel._table_alive():
            return False
        if self._panel._suppress_focus_select:
            return False
        row = obj.property("_table_row")
        if row is None:
            return False
        idx = self._panel._block_index_for_row(int(row))
        if idx < 0:
            return False
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                self._panel._select_block(idx, keep_focus=obj, active_row=int(row))
        elif event.type() == QEvent.Type.FocusIn:
            self._panel._select_block(idx, keep_focus=obj, active_row=int(row))
        return False


class _PasswordKeyFilter(QObject):
    """Arrow keys move real focus between password fields (not just table current cell)."""

    def __init__(self, panel: "MultiDeviceTablePanel") -> None:
        super().__init__(panel)
        self._panel = panel

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if not self._panel._table_alive():
            return False
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return False
        if event.key() not in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            return False
        row = obj.property("_table_row")
        if row is None:
            return False
        delta = 1 if event.key() == Qt.Key.Key_Down else -1
        target = self._panel._adjacent_password_row(int(row), delta)
        if target is None or target == row:
            return False
        event.accept()
        self._panel._focus_password_row(target)
        return True


class _DeviceTableWidget(QTableWidget):
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        polish_widget_scrollbars(self)


class MultiDeviceTablePanel(QWidget):
    devices_structure_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        shell = QFrame()
        mark_device_table_shell(shell)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(10, 10, 10, 10)
        shell_layout.setSpacing(0)

        self.table = _DeviceTableWidget(0, 5)
        self._apply_headers(per_device=False)
        self.table.setMinimumHeight(220)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        apply_device_table_style(self.table)
        self.table.setItemDelegate(_DeviceGridItemDelegate(self.table))
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellPressed.connect(self._on_cell_pressed)
        shell_layout.addWidget(self.table)
        layout.addWidget(shell)
        self._blocks: list[_DeviceBlock] = []
        self._per_device_auth = False
        self._cell_widget_filter = _CellWidgetInteractionFilter(self)
        self._password_key_filter = _PasswordKeyFilter(self)
        self._selected_block_idx = -1
        self._active_row = -1
        self._suppress_focus_select = False

    def _table_alive(self) -> bool:
        return _qt_alive(self.table)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._detach_table_filters()
        super().closeEvent(event)

    def _detach_table_filters(self) -> None:
        if not _qt_alive(self.table):
            return
        for row in range(self.table.rowCount()):
            for col in range(self.table.columnCount()):
                widget = self.table.cellWidget(row, col)
                if widget is not None:
                    widget.removeEventFilter(self._cell_widget_filter)
                    widget.removeEventFilter(self._password_key_filter)

    def _apply_headers(self, *, per_device: bool) -> None:
        headers = ["Model", "Label", "Stack", "MGMT IP", "Port"]
        if per_device:
            headers.extend(["User", "Password"])
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

    def set_per_device_auth(self, enabled: bool) -> None:
        if self._per_device_auth == enabled:
            return
        rows = self.snapshot()
        self._per_device_auth = enabled
        self._apply_headers(per_device=enabled)
        self.rebuild(rows)

    def _text(self, row: int, col: int) -> str:
        widget = self.table.cellWidget(row, col)
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        item = self.table.item(row, col)
        return item.text().strip() if item else ""

    def _tag_row_widget(self, row: int, widget: QWidget) -> None:
        widget.setProperty("_table_row", row)
        widget.installEventFilter(self._cell_widget_filter)
        if isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.EchoMode.Password:
            widget.installEventFilter(self._password_key_filter)

    def _adjacent_password_row(self, row: int, delta: int) -> int | None:
        pass_col = self._auth_cols()[1]
        if pass_col < 0:
            return None
        rows = [
            r
            for r in range(self.table.rowCount())
            if isinstance(self.table.cellWidget(r, pass_col), QLineEdit)
        ]
        try:
            idx = rows.index(row)
        except ValueError:
            return None
        next_idx = idx + delta
        if 0 <= next_idx < len(rows):
            return rows[next_idx]
        return None

    def _focus_password_row(self, row: int) -> None:
        pass_col = self._auth_cols()[1]
        if pass_col < 0:
            return
        widget = self.table.cellWidget(row, pass_col)
        if not isinstance(widget, QLineEdit):
            return
        self._suppress_focus_select = True
        try:
            idx = self._block_index_for_row(row)
            if idx >= 0:
                self._select_block(idx, keep_focus=widget, active_row=row)
            widget.setFocus(Qt.FocusReason.OtherFocusReason)
        finally:
            self._suppress_focus_select = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        polish_widget_scrollbars(self.table)

    def _set_password(self, row: int, col: int, password: str) -> None:
        stub = QTableWidgetItem()
        stub.setFlags(Qt.ItemFlag.NoItemFlags)
        self.table.setItem(row, col, stub)
        edit = QLineEdit(password)
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        configure_table_lineedit(edit)
        self._apply_password_field_style(edit, in_selected_block=False)
        self.table.setCellWidget(row, col, edit)
        self._tag_row_widget(row, edit)

    @staticmethod
    def _apply_password_field_style(edit: QLineEdit, *, in_selected_block: bool) -> None:
        """Password box stays white + black text; blue border when device row is selected."""
        edit.setProperty("formControl", "tableLine")
        edit.setFixedHeight(_TABLE_LINE_H)
        edit.setMinimumHeight(_TABLE_LINE_H)
        edit.setMaximumHeight(_TABLE_LINE_H)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        border = "#0260EA" if in_selected_block else "#E2E8F0"
        edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #FFFFFF;"
            "  color: #1A2332;"
            f"  border: 1px solid {border};"
            "  border-radius: 6px;"
            "  padding: 4px 8px;"
            "  font-size: 13px;"
            f"  min-height: {_TABLE_LINE_H}px;"
            f"  max-height: {_TABLE_LINE_H}px;"
            "}"
        )

    def _set_text(self, row: int, col: int, text: str, *, editable: bool = True) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(_CELL_ALIGN)
        item.setForeground(QBrush(_IDLE_FG))
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, col, item)

    def _make_model_item(self, model: str) -> QTableWidgetItem:
        item = QTableWidgetItem(normalize_device_model(model))
        item.setTextAlignment(_CELL_ALIGN)
        item.setForeground(QBrush(_IDLE_FG))
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        item.setToolTip("클릭하여 모델 변경")
        return item

    def _mgmt_cols(self) -> tuple[int, int]:
        return COL_MGMT, COL_PORT

    def _auth_cols(self) -> tuple[int, int]:
        if self._per_device_auth:
            return COL_USER, COL_PASS
        return -1, -1

    def _open_model_picker(self, row: int) -> None:
        block_idx = self._block_index_for_row(row)
        if block_idx < 0:
            return
        start = self._blocks[block_idx].start_row
        item = self.table.item(start, COL_MODEL)
        if item is None:
            return
        current = normalize_device_model(item.text())
        rect = self.table.visualItemRect(item)
        anchor = self.table.viewport().mapToGlobal(rect.bottomLeft())
        popup = ChoicePickerPopup(
            anchor,
            max(rect.width(), 200),
            [MODEL_ISERIES, MODEL_RSERIES],
            current,
            self.table,
            gap_below=4,
        )
        popup.choice_selected.connect(
            lambda label, idx=block_idx, cur=current: self._on_model_picked(
                idx, cur, label
            )
        )
        popup.show()

    def _on_model_picked(self, block_idx: int, current: str, label: str) -> None:
        new_model = normalize_device_model(label)
        if new_model != normalize_device_model(current):
            self._apply_model_change(block_idx, new_model)

    def _insert_device(self, data: DeviceRowData) -> None:
        rseries = normalize_device_model(data.model) == MODEL_RSERIES
        row_count = 2 if rseries else 1
        start = self.table.rowCount()
        self.table.insertRow(start)
        if row_count == 2:
            self.table.insertRow(start + 1)

        self.table.setItem(start, COL_MODEL, self._make_model_item(data.model))
        label_item = QTableWidgetItem(data.label)
        label_item.setTextAlignment(_CELL_ALIGN)
        label_item.setForeground(QBrush(_IDLE_FG))
        self.table.setItem(start, COL_LABEL, label_item)

        if rseries:
            self._set_stack_row(
                start,
                _STACK_F5OS,
                data.f5os_host,
                str(data.f5os_port),
                data.f5os_user,
                data.f5os_pass,
            )
            self._set_stack_row(
                start + 1,
                _STACK_TMOS,
                data.tmos_host,
                str(data.tmos_port),
                data.tmos_user,
                data.tmos_pass,
            )
        else:
            self._set_stack_row(
                start,
                _STACK_TMOS,
                data.tmos_host,
                str(data.tmos_port),
                data.tmos_user,
                data.tmos_pass,
            )

        if row_count > 1:
            self.table.setSpan(start, COL_MODEL, row_count, 1)
            self.table.setSpan(start, COL_LABEL, row_count, 1)
        self._blocks.append(_DeviceBlock(start_row=start, row_count=row_count))

    def _block_index_for_row(self, row: int) -> int:
        for i, block in enumerate(self._blocks):
            if block.start_row <= row < block.start_row + block.row_count:
                return i
        return -1

    def _select_block_for_row(self, row: int) -> None:
        idx = self._block_index_for_row(row)
        if idx < 0:
            return
        self._select_block(idx, active_row=row)

    def _select_block(
        self,
        block_idx: int,
        *,
        keep_focus: QObject | None = None,
        active_row: int | None = None,
    ) -> None:
        if not self._table_alive():
            return
        if block_idx < 0 or block_idx >= len(self._blocks):
            return
        block = self._blocks[block_idx]
        if active_row is not None and block.start_row <= active_row < block.start_row + block.row_count:
            self._active_row = active_row
        elif keep_focus is not None:
            row_prop = keep_focus.property("_table_row")
            if row_prop is not None:
                self._active_row = int(row_prop)
        else:
            self._active_row = block.start_row
        self._selected_block_idx = block_idx
        self._apply_block_highlight(block_idx)
        if keep_focus is not None:
            return
        self._suppress_focus_select = True
        try:
            self.table.clearSelection()
            self.table.setCurrentCell(block.start_row, COL_LABEL)
        finally:
            self._suppress_focus_select = False

    def _on_cell_pressed(self, row: int, _col: int) -> None:
        if row >= 0:
            self._select_block_for_row(row)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if row < 0:
            return
        self._select_block_for_row(row)
        if col == COL_MODEL:
            self._open_model_picker(row)

    def _row_sel_colors(
        self, block: _DeviceBlock, row: int, *, selected: bool
    ) -> tuple[QColor, QColor]:
        if not selected:
            return (_ZEBRA_ODD if row % 2 else _ZEBRA_EVEN, _IDLE_FG)
        if block.row_count > 1 and row == self._active_row:
            return (_SEL_BG, _SEL_FG)
        if block.row_count > 1:
            return (_SEL_SIBLING_BG, _SEL_SIBLING_FG)
        return (_SEL_BG, _SEL_FG)

    def _apply_block_highlight(self, active_idx: int) -> None:
        if not self._table_alive():
            return
        for i, block in enumerate(self._blocks):
            selected = i == active_idx
            for r in range(block.start_row, block.start_row + block.row_count):
                for c in range(self.table.columnCount()):
                    color_row = r
                    if selected and block.row_count > 1 and c in (COL_MODEL, COL_LABEL):
                        color_row = self._active_row
                    bg, fg = self._row_sel_colors(block, color_row, selected=selected)
                    item = self.table.item(r, c)
                    if item is None:
                        continue
                    if not item.flags():
                        continue
                    item.setBackground(QBrush(bg))
                    item.setForeground(QBrush(fg))
                    if c == COL_STACK:
                        font = QFont(item.font())
                        font.setWeight(QFont.Weight.DemiBold)
                        item.setFont(font)
                        if selected:
                            if block.row_count > 1 and r != self._active_row:
                                item.setForeground(QBrush(_SEL_SIBLING_FG))
                            else:
                                item.setForeground(QBrush(_SEL_FG))
                        else:
                            item.setForeground(QBrush(_STACK_ACCENT))
            self._style_block_widgets(block, selected)
        self.table.viewport().update()

    def _highlight_block(self, block_idx: int) -> None:
        if block_idx < 0:
            return
        self._selected_block_idx = block_idx
        self._apply_block_highlight(block_idx)

    def _style_block_widgets(self, block: _DeviceBlock, selected: bool) -> None:
        pass_col = self._auth_cols()[1]
        if pass_col < 0:
            return
        for r in range(block.start_row, block.start_row + block.row_count):
            bg, _fg = self._row_sel_colors(block, r, selected=selected)
            stub = self.table.item(r, pass_col)
            if stub is not None:
                stub.setBackground(QBrush(bg))
            widget = self.table.cellWidget(r, pass_col)
            if isinstance(widget, QLineEdit):
                self._apply_password_field_style(widget, in_selected_block=selected)

    def _set_stack_row(
        self,
        row: int,
        stack: str,
        host: str,
        port: str,
        user: str,
        password: str,
    ) -> None:
        self._set_text(row, COL_STACK, stack, editable=False)
        mgmt_col, port_col = self._mgmt_cols()
        self._set_text(row, mgmt_col, host)
        self._set_text(row, port_col, port or "443")
        user_col, pass_col = self._auth_cols()
        if user_col >= 0:
            self._set_text(row, user_col, user or "admin")
            self._set_password(row, pass_col, password)

    def _apply_model_change(self, block_idx: int, new_model: str) -> None:
        if block_idx < 0:
            return
        devices = self.snapshot()
        if block_idx >= len(devices):
            return
        devices[block_idx].model = normalize_device_model(new_model)
        self.rebuild(devices)
        if block_idx < len(self._blocks):
            self._select_block_for_row(self._blocks[block_idx].start_row)
        self.devices_structure_changed.emit()

    def _clear_selection(self) -> None:
        """No row highlighted — zebra only (initial Multiple / after rebuild)."""
        self._selected_block_idx = -1
        self._active_row = -1
        if self._table_alive():
            self.table.clearSelection()
            self._apply_block_highlight(-1)

    def add_device(self, data: DeviceRowData | None = None) -> None:
        if data is None:
            n = len(self._blocks) + 1
            data = DeviceRowData(
                model=MODEL_ISERIES,
                label=f"device-{n}",
                tmos_port=443,
                f5os_port=443,
            )
        self._insert_device(data)
        if self._selected_block_idx >= 0:
            self._apply_block_highlight(self._selected_block_idx)
        else:
            self._clear_selection()

    def rebuild(self, devices: list[DeviceRowData]) -> None:
        self.table.setRowCount(0)
        self._blocks.clear()
        for device in devices:
            self._insert_device(device)
        self._clear_selection()

    def snapshot(self) -> list[DeviceRowData]:
        devices: list[DeviceRowData] = []
        mgmt_col, port_col = self._mgmt_cols()
        user_col, pass_col = self._auth_cols()
        for block in self._blocks:
            model_item = self.table.item(block.start_row, COL_MODEL)
            model = MODEL_ISERIES
            if model_item is not None:
                model = normalize_device_model(model_item.text())
            label_item = self.table.item(block.start_row, COL_LABEL)
            label = label_item.text().strip() if label_item else "device"
            data = DeviceRowData(model=model, label=label)
            for r in range(block.start_row, block.start_row + block.row_count):
                stack = self._text(r, COL_STACK)
                host = self._text(r, mgmt_col)
                port_s = self._text(r, port_col) or "443"
                try:
                    port = int(port_s)
                except ValueError:
                    port = 443
                user = self._text(r, user_col) if user_col >= 0 else "admin"
                pw = self._text(r, pass_col) if pass_col >= 0 else ""
                if stack == _STACK_F5OS:
                    data.f5os_host = host
                    data.f5os_port = port
                    data.f5os_user = user
                    data.f5os_pass = pw
                elif stack == _STACK_TMOS:
                    data.tmos_host = host
                    data.tmos_port = port
                    data.tmos_user = user
                    data.tmos_pass = pw
            devices.append(data)
        return devices

    def remove_selected_device(self) -> bool:
        idx = self._selected_block_idx
        if idx < 0:
            row = self.table.currentRow()
            idx = self._block_index_for_row(row)
        if idx < 0:
            return False
        devices = self.snapshot()
        if idx < len(devices):
            devices.pop(idx)
        self.rebuild(devices)
        return True

    def selected_device_index(self) -> int:
        return self._selected_block_idx

    def any_rseries(self) -> bool:
        return any(
            normalize_device_model(d.model) == MODEL_RSERIES for d in self.snapshot()
        )

    def device_count(self) -> int:
        return len(self._blocks)

    def platform_at(self, index: int) -> PlatformKind:
        devices = self.snapshot()
        if index < 0 or index >= len(devices):
            return PlatformKind.iseries
        if normalize_device_model(devices[index].model) == MODEL_RSERIES:
            return PlatformKind.rseries
        return PlatformKind.iseries
