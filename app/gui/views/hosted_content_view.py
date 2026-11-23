"""Extract APM Hosted Content files from a UCS."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme import (
    BRAND_PRIMARY,
    mark_page_subtitle,
    mark_page_title,
    mark_primary_button,
    mark_secondary_button,
    polish_widget_scrollbars,
)
from app.gui.workers.hosted_content_worker import HostedExtractWorker, HostedListWorker
from app.modules.hosted_content.extract import (
    HostedContentReport,
    HostedFile,
    format_size,
    hosted_display_folder,
    hosted_display_name,
)

_FILE_FILTER = "UCS (*.ucs)"
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_ROLE_FILE = Qt.ItemDataRole.UserRole
_ROLE_CHECK = Qt.ItemDataRole.UserRole + 1
_BOX = 14


class HostedContentView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._list_worker: HostedListWorker | None = None
        self._extract_worker: HostedExtractWorker | None = None
        self._path: Path | None = None
        self._files: tuple[HostedFile, ...] = ()
        self._checks: dict[str, bool] = {}
        self._guard = False
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        title = QLabel("Host Content 추출")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel(
            "UCS만 올릴 수 있습니다. Access › Webtops › Hosted Content 목록을 보여주고, "
            "선택한 파일을 폴더로 추출합니다. QKView에는 이 파일이 없습니다."
        )
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.file_label = QLabel("선택된 UCS 없음")
        self.file_label.setProperty("role", "muted")
        self.file_label.setWordWrap(True)
        pick = QPushButton("UCS 선택")
        mark_secondary_button(pick)
        pick.clicked.connect(self._pick_file)
        self.list_btn = QPushButton("목록 보기")
        mark_primary_button(self.list_btn)
        self.list_btn.clicked.connect(self._list)
        file_row.addWidget(self.file_label, stretch=1)
        file_row.addWidget(pick)
        file_row.addWidget(self.list_btn)
        root.addLayout(file_row)

        self.summary = QLabel("UCS를 올리면 Hosted Content 목록이 표시됩니다.")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        root.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        shell = QFrame()
        shell.setObjectName("deviceTableShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        self.table = _HostTree()
        self.table.setHeaderLabels(["이름", "크기"])
        self.table.setColumnCount(2)
        self.table.setItemDelegate(_RowDelegate(self.table))
        self.table.toggled.connect(self._on_toggled)
        self.table.setIndentation(22)
        self.table.setRootIsDecorated(True)
        self.table.setUniformRowHeights(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setCursor(Qt.CursorShape.ArrowCursor)
        self.table.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.setStyleSheet(_TREE_STYLE)
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(88)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        self.table.setColumnWidth(1, 128)
        self.table.setSortingEnabled(True)
        shell_layout.addWidget(self.table)
        root.addWidget(shell, stretch=1)

        actions = QHBoxLayout()
        self.select_all_btn = QPushButton("전체 선택")
        mark_secondary_button(self.select_all_btn)
        self.select_all_btn.clicked.connect(lambda: self._set_all(True))
        self.select_none_btn = QPushButton("전체 해제")
        mark_secondary_button(self.select_none_btn)
        self.select_none_btn.clicked.connect(lambda: self._set_all(False))
        actions.addWidget(self.select_all_btn)
        actions.addWidget(self.select_none_btn)
        actions.addStretch(1)
        self.extract_selected_btn = QPushButton("선택 항목 추출")
        mark_secondary_button(self.extract_selected_btn)
        self.extract_selected_btn.clicked.connect(self._extract_selected)
        self.extract_all_btn = QPushButton("전체 추출")
        mark_primary_button(self.extract_all_btn)
        self.extract_all_btn.clicked.connect(self._extract_all)
        actions.addWidget(self.extract_selected_btn)
        actions.addWidget(self.extract_all_btn)
        root.addLayout(actions)
        polish_widget_scrollbars(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            path = Path(local)
            if path.suffix.lower() != ".ucs":
                QMessageBox.warning(
                    self,
                    "Host Content 추출",
                    "UCS 파일만 올릴 수 있습니다. QKView는 지원하지 않습니다.",
                )
                event.ignore()
                return
            self._set_path(path)
            self._list()
            event.acceptProposedAction()
            return
        event.ignore()

    def _pick_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "UCS 선택", "", _FILE_FILTER)
        if chosen:
            self._set_path(Path(chosen))

    def _set_path(self, path: Path) -> None:
        self._path = path
        self.file_label.setText(path.name)
        self.file_label.setToolTip(str(path))

    def _busy(self) -> bool:
        listing = self._list_worker is not None and self._list_worker.isRunning()
        extracting = self._extract_worker is not None and self._extract_worker.isRunning()
        return listing or extracting

    def _list(self) -> None:
        if self._busy():
            return
        if self._path is None or not self._path.is_file():
            QMessageBox.warning(self, "Host Content 추출", "UCS 파일을 선택하세요.")
            return
        if self._path.suffix.lower() != ".ucs":
            QMessageBox.warning(
                self,
                "Host Content 추출",
                "UCS 파일만 올릴 수 있습니다. QKView는 지원하지 않습니다.",
            )
            return
        self.summary.setText(f"{self._path.name} 읽는 중…")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        worker = HostedListWorker(self._path)
        worker.progressed.connect(self.progress.setValue)
        worker.finished_ok.connect(self._on_list)
        worker.failed.connect(self._on_fail)
        self._list_worker = worker
        worker.start()

    def _on_list(self, report: object) -> None:
        self.progress.setValue(100)
        self.progress.setVisible(False)
        if isinstance(report, HostedContentReport):
            self.show_report(report)

    def _on_fail(self, message: str) -> None:
        self.progress.setVisible(False)
        self.summary.setText(message)
        QMessageBox.warning(self, "Host Content 추출", message[:500])

    def show_report(self, report: HostedContentReport) -> None:
        self._files = report.files
        self._checks = {item.virtual_path: item.present for item in report.files}
        present = sum(1 for item in report.files if item.present)
        missing = len(report.files) - present
        if not report.files:
            self.summary.setText(f"{report.source_name} — Hosted Content 항목이 없습니다.")
        else:
            self.summary.setText(
                f"{report.source_name}  ·  {len(report.files)}개"
                f"  ·  파일 있음 {present}  ·  UCS에 없음 {missing}"
            )
        self._fill()

    def _fill(self) -> None:
        grouped: dict[str, list[HostedFile]] = {}
        for item in self._files:
            grouped.setdefault(hosted_display_folder(item.virtual_path), []).append(item)
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setHeaderLabels(["이름", "크기"])
        for folder in sorted(grouped, key=str.casefold):
            files = sorted(
                grouped[folder],
                key=lambda item: hosted_display_name(item.name, item.filename).casefold(),
            )
            parent = _Node([folder, f"{len(files)}개"])
            parent.setData(1, _ROLE_FILE, sum(max(item.size, 0) for item in files))
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            parent.setToolTip(0, folder)
            for item in files:
                name = hosted_display_name(item.name, item.filename)
                child = _Node([name, format_size(item.size)])
                child.setData(0, _ROLE_FILE, item)
                child.setData(1, _ROLE_FILE, item.size)
                child.setFlags(Qt.ItemFlag.ItemIsEnabled)
                child.setToolTip(0, name)
                child.setTextAlignment(1, _RIGHT)
                if item.present and self._checks.get(item.virtual_path, False):
                    child.setData(0, _ROLE_CHECK, Qt.CheckState.Checked)
                else:
                    child.setData(0, _ROLE_CHECK, Qt.CheckState.Unchecked)
                if not item.present:
                    muted = QBrush(QColor("#94A3B8"))
                    child.setForeground(0, muted)
                    child.setForeground(1, muted)
                parent.addChild(child)
            self._refresh_folder(parent)
            self.table.addTopLevelItem(parent)
            parent.setExpanded(True)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _on_toggled(self, item: QTreeWidgetItem) -> None:
        if self._guard:
            return
        self._guard = True
        try:
            if item.childCount():
                turn_on = self._state(item) != Qt.CheckState.Checked
                self.apply_folder_check(item, turn_on)
            else:
                self._toggle_file(item)
        finally:
            self._guard = False
        self.table.viewport().update()

    def apply_folder_check(self, item: QTreeWidgetItem, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        any_present = False
        for index in range(item.childCount()):
            child = item.child(index)
            hosted = child.data(0, _ROLE_FILE)
            if not isinstance(hosted, HostedFile) or not hosted.present:
                child.setData(0, _ROLE_CHECK, Qt.CheckState.Unchecked)
                continue
            any_present = True
            child.setData(0, _ROLE_CHECK, state)
            self._checks[hosted.virtual_path] = checked
        item.setData(0, _ROLE_CHECK, state if any_present else Qt.CheckState.Unchecked)

    def _toggle_file(self, item: QTreeWidgetItem) -> None:
        hosted = item.data(0, _ROLE_FILE)
        if not isinstance(hosted, HostedFile) or not hosted.present:
            return
        checked = self._state(item) != Qt.CheckState.Checked
        item.setData(
            0,
            _ROLE_CHECK,
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
        )
        self._checks[hosted.virtual_path] = checked
        parent = item.parent()
        if parent is not None:
            self._refresh_folder(parent)

    def _refresh_folder(self, item: QTreeWidgetItem) -> None:
        present = 0
        checked = 0
        for index in range(item.childCount()):
            child = item.child(index)
            hosted = child.data(0, _ROLE_FILE)
            if not isinstance(hosted, HostedFile) or not hosted.present:
                continue
            present += 1
            if self._state(child) == Qt.CheckState.Checked:
                checked += 1
        if present == 0 or checked == 0:
            state = Qt.CheckState.Unchecked
        elif checked == present:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        item.setData(0, _ROLE_CHECK, state)

    def _state(self, item: QTreeWidgetItem) -> Qt.CheckState:
        value = item.data(0, _ROLE_CHECK)
        if isinstance(value, Qt.CheckState):
            return value
        return Qt.CheckState.Unchecked

    def _set_all(self, checked: bool) -> None:
        self._guard = True
        try:
            for index in range(self.table.topLevelItemCount()):
                self.apply_folder_check(self.table.topLevelItem(index), checked)
        finally:
            self._guard = False
        self.table.viewport().update()

    def _extract_selected(self) -> None:
        chosen: list[HostedFile] = []
        for index in range(self.table.topLevelItemCount()):
            folder = self.table.topLevelItem(index)
            for child_index in range(folder.childCount()):
                child = folder.child(child_index)
                hosted = child.data(0, _ROLE_FILE)
                if (
                    isinstance(hosted, HostedFile)
                    and hosted.present
                    and self._state(child) == Qt.CheckState.Checked
                ):
                    chosen.append(hosted)
        self._extract(chosen)

    def _extract_all(self) -> None:
        self._extract([item for item in self._files if item.present])

    def _extract(self, files: list[HostedFile]) -> None:
        if self._busy():
            return
        ready = [item for item in files if item.present]
        if self._path is None:
            QMessageBox.warning(self, "Host Content 추출", "UCS 파일을 선택하세요.")
            return
        if not ready:
            QMessageBox.information(self, "Host Content 추출", "추출할 파일이 없습니다.")
            return
        dest = QFileDialog.getExistingDirectory(self, "추출할 폴더 선택")
        if not dest:
            return
        self.summary.setText(f"{len(ready)}개 추출 중…")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        worker = HostedExtractWorker(self._path, ready, Path(dest))
        worker.progressed.connect(self.progress.setValue)
        worker.finished_ok.connect(self._on_extracted)
        worker.failed.connect(self._on_fail)
        self._extract_worker = worker
        worker.start()

    def _on_extracted(self, payload: object) -> None:
        self.progress.setValue(100)
        self.progress.setVisible(False)
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        written, missing, dest = payload
        text = f"{len(written)}개 파일을 저장했습니다.\n{dest}"
        if missing:
            text += f"\nUCS에 없는 항목 {len(missing)}개는 건너뛰었습니다."
        self.summary.setText(text.replace("\n", " "))
        QMessageBox.information(self, "Host Content 추출", text)


class _Node(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:  # noqa: N802
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        if column == 1:
            left = self.data(1, _ROLE_FILE) or 0
            right = other.data(1, _ROLE_FILE) or 0
            return int(left) < int(right)
        return self.text(0).casefold() < other.text(0).casefold()


class _HostTree(QTreeWidget):
    toggled = pyqtSignal(object)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            if index.isValid() and index.column() == 0 and _box_rect(self, index).contains(pos):
                item = self.itemFromIndex(index)
                if item is not None:
                    self.toggled.emit(item)
                    event.accept()
                    return
        super().mousePressEvent(event)


class _RowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001, N802
        hint = super().sizeHint(option, index)
        height = 30 if not index.parent().isValid() else 28
        return QSize(hint.width(), height)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        folder = not index.parent().isValid()
        hover = _row_hover(option, index)
        painter.save()
        painter.setClipRect(option.rect)
        if folder:
            fill = QColor("#F1F5F9") if hover else QColor("#F8FAFC")
        else:
            fill = QColor("#F8FAFC") if hover else QColor("#FFFFFF")
        painter.fillRect(option.rect, fill)
        painter.setPen(QPen(QColor("#E2E8F0"), 1))
        bottom = option.rect.bottom()
        painter.drawLine(option.rect.left(), bottom, option.rect.right(), bottom)
        painter.restore()
        if index.column() == 0:
            self._paint_name(painter, option, index, folder=folder)
        else:
            self._paint_size(painter, option, index, folder=folder)

    def _paint_name(self, painter: QPainter, option, index, *, folder: bool) -> None:  # noqa: ANN001
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        box = _box_rect_from(option.rect)
        state = index.data(_ROLE_CHECK)
        check = state if isinstance(state, Qt.CheckState) else Qt.CheckState.Unchecked
        hosted = index.data(_ROLE_FILE)
        enabled = folder or (isinstance(hosted, HostedFile) and hosted.present)
        if folder:
            enabled = _folder_has_file(index)
        _paint_box(painter, box, check, enabled=enabled)

        text_left = box.right() + 8
        text_rect = QRect(
            text_left,
            option.rect.top(),
            max(0, option.rect.right() - text_left - 4),
            option.rect.height(),
        )
        label = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        color = QColor("#1A2332")
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(brush, QBrush):
            color = brush.color()
        painter.save()
        painter.setPen(color)
        painter.setFont(opt.font)
        shown = opt.fontMetrics.elidedText(label, Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            shown,
        )
        painter.restore()

    def _paint_size(self, painter: QPainter, option, index, *, folder: bool) -> None:  # noqa: ANN001
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(QColor("#64748B") if folder else QColor("#334155"))
        rect = option.rect.adjusted(6, 0, -10, 0)
        painter.drawText(rect, int(_RIGHT), label)
        painter.restore()


def _folder_has_file(index) -> bool:  # noqa: ANN001
    model = index.model()
    if model is None:
        return False
    for row in range(model.rowCount(index)):
        child = model.index(row, 0, index)
        hosted = child.data(_ROLE_FILE)
        if isinstance(hosted, HostedFile) and hosted.present:
            return True
    return False


def _row_hover(option, index) -> bool:  # noqa: ANN001
    widget = option.widget
    if not isinstance(widget, QTreeWidget):
        return False
    pos = widget.viewport().mapFromGlobal(widget.cursor().pos())
    hovered = widget.indexAt(pos)
    if not hovered.isValid() or hovered.row() != index.row():
        return False
    return hovered.parent() == index.parent()


def _box_rect(view: QTreeWidget, index) -> QRect:  # noqa: ANN001
    return _box_rect_from(view.visualRect(index))


def _box_rect_from(rect: QRect) -> QRect:
    return QRect(rect.left() + 2, rect.center().y() - _BOX // 2, _BOX, _BOX)


def _paint_box(painter: QPainter, box: QRect, state: Qt.CheckState, *, enabled: bool) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        fill = QColor("#F1F5F9")
        border = QColor("#CBD5E1")
    elif state == Qt.CheckState.Unchecked:
        fill = QColor("#FFFFFF")
        border = QColor("#94A3B8")
    else:
        fill = QColor(BRAND_PRIMARY)
        border = QColor(BRAND_PRIMARY)
    painter.setBrush(fill)
    painter.setPen(QPen(border, 1.4))
    painter.drawRoundedRect(box.adjusted(1, 1, -1, -1), 3, 3)
    if enabled and state == Qt.CheckState.Checked:
        pen = QPen(QColor("#FFFFFF"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x, y, w, h = box.x(), box.y(), box.width(), box.height()
        painter.drawLine(x + 3, y + h // 2, x + w // 2 - 1, y + h - 4)
        painter.drawLine(x + w // 2 - 1, y + h - 4, x + w - 3, y + 3)
    elif enabled and state == Qt.CheckState.PartiallyChecked:
        dash = QPen(QColor("#FFFFFF"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(dash)
        painter.drawLine(box.left() + 3, box.center().y(), box.right() - 3, box.center().y())
    painter.restore()


_TREE_STYLE = """
QTreeWidget {
    background: #FFFFFF;
    border: none;
    color: #1A2332;
    font-size: 13px;
    outline: none;
}
QTreeWidget::item {
    color: #1A2332;
    padding: 2px 6px;
    border: none;
}
QTreeWidget::item:hover {
    background: #F8FAFC;
    color: #1A2332;
}
QHeaderView::section {
    background: #F1F5F9;
    color: #1A2332;
    font-size: 12px;
    font-weight: 600;
    padding: 8px 12px;
    border: none;
    border-right: 1px solid #E2E8F0;
    border-bottom: 2px solid #CBD5E1;
}
"""
