"""APM access-policy viewer drawn with the same widgets as the other pages."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme import mark_page_subtitle, mark_page_title, mark_primary_button, mark_secondary_button
from app.modules.vpe_viewer.layout import layout_graph

_NODE_COLORS = {
    1: "#67b246",
    2: "#d45b5b",
    3: "#e0c14a",
    4: "#e08a4a",
    5: "#4a90d9",
    6: "#8a6bb0",
    7: "#3aa0a0",
    8: "#c76b9a",
    16: "#8a6bb0",
}
_FILE_FILTER = "APM 설정 (*.qkview *.ucs *.conf *.tar *.gz *.tgz *.zip);;모든 파일 (*.*)"


class _LoadWorker(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: str, filename: str) -> None:
        super().__init__()
        self._path = path
        self._filename = filename

    def run(self) -> None:
        from app.modules.vpe_viewer.archive import build_model_from_path

        try:
            model = build_model_from_path(self._path, self._filename)
        except ValueError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"분석 실패: {exc}")
            return
        self.loaded.emit(model)


class _NodeItem(QGraphicsItem):
    def __init__(self, node: dict, graph: dict, on_click) -> None:
        super().__init__()
        self._node = node
        self._graph = graph
        self._on_click = on_click
        self._width = float(node["width"])
        self._height = float(node["height"])
        self.setPos(float(node["x"]) - self._width / 2, float(node["y"]) - self._height / 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, self._width, self._height)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        kind = str(self._node.get("kind") or "")
        color = QColor(_NODE_COLORS.get(int(self._node.get("color") or 1), _NODE_COLORS[1]))
        rect = self.boundingRect()
        caption = str(self._node.get("caption") or "")
        font = QFont("Malgun Gothic", 10)
        font.setBold(True)
        painter.setFont(font)
        if kind in {"start", "entry"}:
            painter.setPen(QPen(QColor("#3d7a2c"), 1))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(rect, 14, 14)
            painter.setPen(QColor("#ffffff"))
        elif kind.startswith("ending") or kind == "terminal":
            painter.setPen(QPen(QColor("#555555"), 0.8))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor("#ffffff"))
        elif kind == "macro":
            painter.setPen(QPen(QColor("#4b5d6e"), 1.4))
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawRect(rect)
            inset = max(4.0, min(7.0, self._width * 0.06))
            inner = rect.adjusted(inset, inset, -inset, -inset)
            painter.setBrush(QBrush(QColor("#c9d2da"), Qt.BrushStyle.BDiagPattern))
            painter.drawRect(inner)
            painter.setPen(QColor("#1d2a38"))
        else:
            painter.setPen(QPen(QColor("#5c6b7a"), 1.2))
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawRect(rect)
            painter.setPen(QColor("#1d2a38"))
        painter.drawText(
            rect.adjusted(6, 2, -6, -2),
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            caption,
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._on_click(self._node, self._graph)
        event.accept()


class _GraphView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, on_file, on_zoom=None) -> None:
        super().__init__(scene)
        self._on_file = on_file
        self._on_zoom = on_zoom
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile():
            self._on_file(urls[0].toLocalFile())
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and self._on_zoom is not None:
            factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
            self._on_zoom(factor)
            event.accept()
            return
        event.ignore()


def _paint_policy(scene: QGraphicsScene, policy: dict, on_node, *, titled: bool) -> dict:
    scene.clear()
    if titled:
        caption = str(policy.get("caption") or "")
        title = QGraphicsSimpleTextItem(caption)
        title.setFont(QFont("Malgun Gothic", 13, QFont.Weight.Bold))
        title.setBrush(QBrush(QColor("#0260EA")))
        title.setPos(16, 4)
        scene.addItem(title)
    laid = layout_graph(policy)
    offset_x = 16.0
    shift_y = 22.0 if titled else 0.0
    for node in laid["nodes"]:
        placed = {**node, "x": node["x"] + offset_x, "y": node["y"] + shift_y}
        scene.addItem(_NodeItem(placed, policy, on_node))
    edge_pen = QPen(QColor("#5d6b78"), 1.6)
    edge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    for edge in laid["edges"]:
        x1 = edge["x1"] + offset_x
        x2 = edge["x2"] + offset_x
        y = edge["y"] + shift_y
        path = QPainterPath()
        path.moveTo(x1, y)
        path.lineTo(x2, y)
        item = QGraphicsPathItem(path)
        item.setPen(edge_pen)
        scene.addItem(item)
        if x2 > x1 + 8:
            head = QPainterPath()
            head.moveTo(x2, y)
            head.lineTo(x2 - 8, y - 4)
            head.lineTo(x2 - 8, y + 4)
            head.closeSubpath()
            arrow = QGraphicsPathItem(head)
            arrow.setPen(QPen(Qt.PenStyle.NoPen))
            arrow.setBrush(QBrush(QColor("#6a7684")))
            scene.addItem(arrow)
        caption = str(edge.get("caption") or "")
        if caption:
            label = QGraphicsSimpleTextItem(caption)
            label.setFont(QFont("Malgun Gothic", 8, QFont.Weight.Bold))
            label.setBrush(QBrush(QColor("#1f3348")))
            label.setPos(x1 + 8, y - 16)
            scene.addItem(label)
    width = float(laid.get("width") or 480) + offset_x
    height = float(laid.get("height") or 160) + shift_y
    return {"width": width, "height": height}


def _place_graph_view(view: QGraphicsView, laid: dict, scale: float) -> None:
    width = float(laid["width"]) + 28
    height = float(laid["height"]) + 18
    view.resetTransform()
    view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    view.scale(scale, scale)
    view.setSceneRect(QRectF(0, 0, width, height))
    view.setFixedHeight(max(88, int(height * scale) + 8))
    view.setMinimumWidth(int(width * scale))


class _FlatGraphView(QGraphicsView):
    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class _MacroSection(QWidget):
    def __init__(self, policy: dict, on_node, on_toggle) -> None:
        super().__init__()
        self.policy = policy
        self.name = str(policy.get("name") or "")
        self.caption = str(policy.get("caption") or self.name.rsplit("/", 1)[-1])
        self._on_node = on_node
        self._drawn = False
        self._laid: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.bar = QPushButton(f"▸    Macro: {self.caption}")
        self.bar.setObjectName("vpeMacroBar")
        self.bar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bar.setFixedHeight(36)
        self.bar.clicked.connect(lambda: on_toggle(self.name))
        layout.addWidget(self.bar)
        self.scene = QGraphicsScene(self)
        self.view = _FlatGraphView(self.scene)
        self.view.setObjectName("vpeGraph")
        self.view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setBackgroundBrush(QBrush(QColor("#F7F8FA")))
        self.view.hide()
        layout.addWidget(self.view)

    def ensure_drawn(self) -> None:
        if self._drawn:
            return
        self._laid = _paint_policy(self.scene, self.policy, self._on_node, titled=False)
        self._drawn = True

    def set_open(self, opened: bool, scale: float) -> None:
        arrow = "▾" if opened else "▸"
        self.bar.setText(f"{arrow}    Macro: {self.caption}")
        self.bar.setProperty("open", opened)
        style = self.bar.style()
        if style is not None:
            style.unpolish(self.bar)
            style.polish(self.bar)
        if not opened:
            self.view.hide()
            return
        self.ensure_drawn()
        if self._laid is not None:
            _place_graph_view(self.view, self._laid, scale)
        self.view.show()


class VpeViewerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._model: dict | None = None
        self._worker: _LoadWorker | None = None
        self._policy: dict | None = None
        self._sections: list[_MacroSection] = []
        self._open_macros: set[str] = set()
        self._main_laid: dict | None = None
        self._main_width = 640.0
        self._zoom = 1.0
        self._draw_gen = 0
        self._copy_text = ""
        self._find_at = 0
        self._scene = QGraphicsScene(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        title = QLabel("VPE Viewer")
        mark_page_title(title)
        root.addWidget(title)
        subtitle = QLabel("qkview, UCS, bigip.conf를 올리면 APM Access Policy 흐름을 보여 줍니다.")
        subtitle.setWordWrap(True)
        mark_page_subtitle(subtitle)
        root.addWidget(subtitle)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self._upload = QPushButton("파일 업로드")
        mark_primary_button(self._upload)
        self._upload.clicked.connect(self._pick_file)
        tools.addWidget(self._upload)
        self._source = QLabel("qkview / ucs / bigip.conf")
        self._source.setProperty("role", "muted")
        tools.addWidget(self._source, stretch=1)
        self._search = QLineEdit()
        self._search.setPlaceholderText("프로필 검색")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(240)
        self._search.textChanged.connect(self._fill_profiles)
        tools.addWidget(self._search)
        zoom_out = QPushButton("축소")
        zoom_in = QPushButton("확대")
        zoom_fit = QPushButton("맞춤")
        for button in (zoom_out, zoom_in, zoom_fit):
            mark_secondary_button(button)
            tools.addWidget(button)
        zoom_out.clicked.connect(lambda: self._zoom_by(1 / 1.2))
        zoom_in.clicked.connect(lambda: self._zoom_by(1.2))
        zoom_fit.clicked.connect(self._fit)
        self._find = QLineEdit()
        self._find.setPlaceholderText("찾기  Ctrl+F")
        self._find.setClearButtonEnabled(True)
        self._find.setFixedWidth(180)
        self._find.returnPressed.connect(self._find_next)
        self._find.hide()
        tools.addWidget(self._find)
        root.addLayout(tools)
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._find_shortcut.activated.connect(self._open_find)
        self._find_esc = QShortcut(QKeySequence("Esc"), self._find)
        self._find_esc.activated.connect(self._find.hide)

        self._status = QLabel("qkview를 올리면 Access Policy 흐름도가 생성됩니다.")
        self._status.setWordWrap(True)
        self._status.setProperty("role", "muted")
        root.addWidget(self._status)

        self._profiles = QListWidget()
        self._profiles.setObjectName("vpeProfileList")
        self._profiles.currentItemChanged.connect(self._on_profile)
        self._view = _GraphView(self._scene, self._load_path, self._zoom_by)
        self._view.setObjectName("vpeGraph")
        self._view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setBackgroundBrush(QBrush(QColor("#F7F8FA")))
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("항목을 누르면 설정이 여기에 나옵니다.")
        self._hint = QLabel("qkview 파일을 여기에 놓으세요\n또는 위 버튼으로 .qkview / .ucs / bigip.conf 선택")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._canvas = QFrame()
        self._canvas.setObjectName("vpeCanvas")
        canvas_layout = QVBoxLayout(self._canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self._hint)
        self._page = QWidget()
        self._page.setObjectName("vpePage")
        self._page_layout = QVBoxLayout(self._page)
        self._page_layout.setContentsMargins(0, 0, 0, 0)
        self._page_layout.setSpacing(0)
        self._page_layout.addWidget(self._view)
        self._macro_split = QFrame()
        self._macro_split.setObjectName("vpeMacroSplit")
        self._macro_split.setFixedHeight(18)
        self._macro_split.hide()
        self._page_layout.addStretch(1)
        self._view.hide()
        self._scroll = QScrollArea()
        self._scroll.setObjectName("vpeScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._page)
        self._scroll.hide()
        canvas_layout.addWidget(self._scroll)
        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(6)
        self._copy = QPushButton("iRule 소스 복사")
        mark_secondary_button(self._copy)
        self._copy.clicked.connect(self._copy_irule)
        self._copy.hide()
        detail_layout.addWidget(self._copy)

        splitter = QSplitter()
        splitter.addWidget(self._profiles)
        splitter.addWidget(self._canvas)
        detail_layout.addWidget(self._detail)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 700, 280])
        root.addWidget(splitter, stretch=1)
        self.setStyleSheet(
            """
            QListWidget#vpeProfileList, QTextEdit, QFrame#vpeCanvas {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
            QListWidget#vpeProfileList::item { padding: 6px 8px; }
            QListWidget#vpeProfileList::item:selected { background: #EDF5FF; color: #0260EA; }
            QScrollArea#vpeScroll, QWidget#vpePage { background: #e8eaed; border: none; }
            QGraphicsView#vpeGraph { background: #F7F8FA; border: none; }
            QFrame#vpeMacroSplit {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #eef0f2, stop:1 #dfe3e7);
                border: none;
                border-top: 1px solid #c5ccd3;
                border-bottom: 1px solid #b7bec6;
            }
            QPushButton#vpeMacroBar {
                text-align: left;
                padding: 7px 14px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f7f8f9, stop:1 #e7eaed);
                border: none;
                border-top: 1px solid #c5ccd3;
                border-bottom: 1px solid #d5dbe2;
                color: #0260EA;
                font-weight: 700;
                font-size: 13px;
            }
            QPushButton#vpeMacroBar:hover { background: #e7eef6; }
            QPushButton#vpeMacroBar[open="true"] {
                background: #e4eef8;
                border-bottom: 1px solid #c5d4e6;
            }
            """
        )

    def shutdown(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.wait(3000)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self._load_path(path)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def _pick_file(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(self, "APM 설정 열기", "", _FILE_FILTER)
        if path:
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status.setText("이전 파일을 분석하는 중입니다.")
            return
        name = Path(path).name
        self._upload.setEnabled(False)
        self._source.setText(name)
        self._status.setText(f"{name} 분석 중…")
        self._worker = _LoadWorker(path, name)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(lambda: self._upload.setEnabled(True))
        self._worker.start()

    def _on_failed(self, message: str) -> None:
        self._status.setText(message)

    def _on_loaded(self, model: object) -> None:
        if not isinstance(model, dict):
            self._status.setText("분석 결과를 읽지 못했습니다.")
            return
        self._model = model
        summary = model.get("summary") or {}
        profiles = summary.get("profiles")
        policies = summary.get("policies")
        extra = ""
        if profiles is not None or policies is not None:
            extra = f"  프로필 {profiles or 0}개, 정책 {policies or 0}개"
        self._status.setText(f"{model.get('source') or '설정을 읽었습니다.'}{extra}")
        self._fill_profiles()
        self._select_first()

    def _fill_profiles(self) -> None:
        self._profiles.blockSignals(True)
        current = ""
        item = self._profiles.currentItem()
        if item is not None:
            current = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._profiles.clear()
        if self._model is None:
            self._profiles.blockSignals(False)
            return
        query = self._search.text().strip().lower()
        rows: list[tuple[str, str]] = []
        profiles = self._model.get("profiles") or []
        for profile in profiles:
            name = str(profile.get("name") or "")
            policy = str(profile.get("access_policy") or name)
            label = name.rsplit("/", 1)[-1] or policy.rsplit("/", 1)[-1]
            blob = f"{label} {name} {policy}".lower()
            if query and query not in blob:
                continue
            rows.append((label, policy))
        if not profiles:
            for policy in self._model.get("policies") or []:
                if policy.get("type") == "macro":
                    continue
                caption = str(policy.get("caption") or policy.get("name") or "")
                policy_name = str(policy.get("name") or "")
                if query and query not in caption.lower() and query not in policy_name.lower():
                    continue
                rows.append((caption, policy_name))
        restore: QListWidgetItem | None = None
        for label, policy in rows:
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, policy)
            row.setToolTip(policy)
            self._profiles.addItem(row)
            if policy == current:
                restore = row
        if restore is not None:
            self._profiles.setCurrentItem(restore)
        self._profiles.blockSignals(False)

    def _select_first(self) -> None:
        from app.modules.vpe_viewer.server import _first_policy_name

        if self._model is None:
            return
        preferred = _first_policy_name(self._model) or ""
        for row in range(self._profiles.count()):
            item = self._profiles.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == preferred:
                self._profiles.setCurrentItem(item)
                return
        if self._profiles.count():
            self._profiles.setCurrentRow(0)

    def _on_profile(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None or self._model is None:
            return
        name = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if name:
            self._show_policy(name)

    def _show_policy(self, name: str, focus: str = "") -> None:
        from app.modules.vpe_viewer.server import _policy_bundle

        if self._model is None:
            return
        bundle = _policy_bundle(self._model, name)
        if not bundle or not bundle.get("policies"):
            self._status.setText(f"정책을 찾을 수 없습니다: {name}")
            return
        policy = bundle["policies"][0]
        if policy.get("type") == "macro" and not focus:
            owners = [str(owner) for owner in (policy.get("owners") or []) if owner]
            if owners:
                self._show_policy(owners[0], focus=str(policy.get("name") or name))
                return
        self._policy = policy
        self._graphs = {item.get("name"): item for item in bundle["policies"] if item.get("name")}
        macros = [
            item
            for item in bundle["policies"][1:]
            if item.get("name") and item.get("name") != policy.get("name")
        ]
        self._draw_stack(policy, macros, focus)
        self._show_overview(policy)
        caption = policy.get("caption") or name.rsplit("/", 1)[-1]
        self._status.setText(str(caption))

    def _draw_stack(self, policy: dict, macros: list[dict], focus: str = "") -> None:
        self._hint.hide()
        self._scroll.show()
        self._view.show()
        self._clear_sections()
        self._open_macros = set()
        self._main_laid = _paint_policy(self._scene, policy, self._on_node, titled=True)
        self._main_width = float(self._main_laid["width"])
        focus_name = self._match_macro_name(focus, macros)
        if focus_name:
            self._open_macros.add(focus_name)
        if macros:
            self._page_layout.insertWidget(self._page_layout.count() - 1, self._macro_split)
            self._macro_split.show()
        for macro in macros:
            section = _MacroSection(macro, self._on_node, self._toggle_macro)
            self._sections.append(section)
            self._page_layout.insertWidget(self._page_layout.count() - 1, section)
        self._draw_gen += 1
        generation = self._draw_gen
        QTimer.singleShot(0, lambda: self._reveal_if(generation, focus_name))

    def _reveal_if(self, generation: int, focus: str) -> None:
        if generation != self._draw_gen:
            return
        self._reveal(focus)

    def _clear_sections(self) -> None:
        self._page_layout.removeWidget(self._macro_split)
        self._macro_split.hide()
        for section in self._sections:
            self._page_layout.removeWidget(section)
            section.deleteLater()
        self._sections = []

    def _match_macro_name(self, name: str, macros: list[dict]) -> str:
        if not name:
            return ""
        last = name.rsplit("/", 1)[-1]
        for macro in macros:
            macro_name = str(macro.get("name") or "")
            caption = str(macro.get("caption") or "")
            if name in {macro_name, caption} or macro_name.endswith("/" + last) or caption == last:
                return macro_name
        return ""

    def _section_for(self, name: str) -> _MacroSection | None:
        last = name.rsplit("/", 1)[-1]
        for section in self._sections:
            if name in {section.name, section.caption} or section.name.endswith("/" + last):
                return section
        return None

    def _apply_scale(self) -> None:
        if self._main_laid is None:
            return
        scale = self._zoom
        _place_graph_view(self._view, self._main_laid, scale)
        for section in self._sections:
            section.set_open(section.name in self._open_macros, scale)

    def _reveal(self, focus: str) -> None:
        self._zoom = 1.0
        self._apply_scale()
        if focus:
            self._scroll_to_macro(focus)
            return
        self._scroll.verticalScrollBar().setValue(0)

    def _scroll_vertically(self, widget: QWidget) -> None:
        top = widget.mapTo(self._page, widget.rect().topLeft()).y()
        bar = self._scroll.verticalScrollBar()
        bar.setValue(max(0, int(top) - 8))

    def _scroll_to_macro(self, name: str) -> None:
        section = self._section_for(name)
        if section is None:
            return
        self._open_macros.add(section.name)
        section.set_open(True, self._zoom)
        self._scroll_vertically(section)
        self._status.setText(f"Macro: {section.caption}")

    def _toggle_macro(self, name: str) -> None:
        section = self._section_for(name)
        if section is None:
            return
        if section.name in self._open_macros:
            self._open_macros.discard(section.name)
            section.set_open(False, self._zoom)
            return
        self._open_macros.add(section.name)
        section.set_open(True, self._zoom)
        self._scroll_vertically(section)
        self._status.setText(f"Macro: {section.caption}")

    def _zoom_by(self, factor: float) -> None:
        self._zoom = max(0.35, min(self._zoom * factor, 2.8))
        self._apply_scale()

    def _on_node(self, node: dict, graph: dict) -> None:
        if node.get("kind") == "macro":
            target = str(node.get("macro") or "")
            if target and self._section_for(target) is not None:
                self._scroll_to_macro(target)
                self._show_detail(node, graph)
                return
        self._show_detail(node, graph)

    def _open_find(self) -> None:
        self._find.show()
        self._find.setFocus()
        self._find.selectAll()
        self._find_at = 0

    def _find_next(self) -> None:
        query = self._find.text().strip().lower()
        if not query:
            return
        hits: list[tuple[str, object]] = []
        for row in range(self._profiles.count()):
            item = self._profiles.item(row)
            if item is not None and query in item.text().lower():
                hits.append(("profile", item))
        for item in self._scene.items():
            caption = str(item._node.get("caption") or "").lower() if isinstance(item, _NodeItem) else ""
            if caption and query in caption:
                hits.append(("node", item))
        for section in self._sections:
            if query in section.caption.lower() or query in section.name.lower():
                hits.append(("macro", section))
            section.ensure_drawn()
            for item in section.scene.items():
                caption = str(item._node.get("caption") or "").lower() if isinstance(item, _NodeItem) else ""
                if caption and query in caption:
                    hits.append(("macro-node", (section, item)))
        if query in self._detail.toPlainText().lower():
            hits.append(("detail", self._detail))
        if not hits:
            self._status.setText(f"'{self._find.text().strip()}' 을 찾지 못했습니다.")
            return
        kind, target = hits[self._find_at % len(hits)]
        self._find_at += 1
        if kind == "profile" and isinstance(target, QListWidgetItem):
            self._profiles.setCurrentItem(target)
            self._profiles.scrollToItem(target)
        elif kind == "node" and isinstance(target, _NodeItem):
            self._scroll_vertically(self._view)
            self._show_detail(target._node, target._graph)
        elif kind == "macro" and isinstance(target, _MacroSection):
            self._scroll_to_macro(target.name)
        elif kind == "macro-node" and isinstance(target, tuple):
            section, node = target
            if isinstance(section, _MacroSection) and isinstance(node, _NodeItem):
                self._scroll_to_macro(section.name)
                self._show_detail(node._node, node._graph)
        else:
            self._detail.setFocus()

    def _copy_irule(self) -> None:
        if not self._copy_text:
            return
        QApplication.clipboard().setText(self._copy_text)
        self._copy.setText("복사됨")
        QTimer.singleShot(1400, lambda: self._copy.setText("iRule 소스 복사"))

    def _set_detail(self, text: str, irule_source: str = "") -> None:
        self._detail.setPlainText(text)
        self._copy_text = irule_source
        self._copy.setVisible(bool(irule_source))
        self._copy.setText("iRule 소스 복사")

    def _show_overview(self, policy: dict) -> None:
        lines = [
            str(policy.get("caption") or ""),
            "",
            f"객체  {policy.get('name') or ''}",
            f"종류  {policy.get('type') or 'access-policy'}",
            "",
            "Virtual Server",
        ]
        virtuals = policy.get("virtuals") or []
        if not virtuals:
            lines.append("이 Access Profile이 적용된 Virtual Server가 설정에 없습니다.")
        for vs in virtuals:
            lines.append(f"- {str(vs.get('name') or '').rsplit('/', 1)[-1]}")
            dest = str(vs.get("destination") or "")
            if dest:
                lines.append(f"    목적지  {dest.rsplit('/', 1)[-1]}")
            rules = [str(rule).rsplit("/", 1)[-1] for rule in (vs.get("rules") or [])]
            lines.append("    적용 iRule  " + (", ".join(rules) if rules else "없음"))
        self._set_detail("\n".join(lines))

    def _lookup_irules(self, node: dict, policy: dict) -> tuple[list[dict], list[str], bool]:
        from app.modules.vpe_viewer.parser import _match_ltm_rules

        model = self._model or {}
        objects = model.get("objects") or {}
        agent_ids = []
        for agent in node.get("agent_details") or []:
            if not isinstance(agent, dict):
                continue
            if agent.get("agent_kind") == "irule-event" or agent.get("type") == "irule-event":
                if agent.get("id"):
                    agent_ids.append(str(agent["id"]))
        virtuals = policy.get("virtuals") or []
        allowed = []
        for vs in virtuals:
            vs_name = str(vs.get("name") or "")
            for rule in vs.get("rules") or []:
                allowed.append({"name": rule, "virtuals": [vs_name] if vs_name else []})
        found: list[dict] = []
        seen: set[str] = set()
        for agent_id in agent_ids:
            matched = _match_ltm_rules(
                agent_id,
                objects,
                allowed_rules=allowed if virtuals else None,
                fallback=not bool(virtuals),
            )
            for rule in matched:
                name = str(rule.get("name") or "")
                if not name or name in seen:
                    continue
                seen.add(name)
                found.append(rule)
        return found, agent_ids, bool(virtuals)

    def _show_detail(self, node: dict, graph: dict) -> None:
        lines = [
            str(node.get("caption") or ""),
            "",
            f"객체  {node.get('id') or ''}",
            "종류  "
            + str(node.get("kind") or "")
            + (f" / {node.get('item_type')}" if node.get("item_type") else ""),
        ]
        if node.get("macro"):
            lines.append(f"매크로  {node.get('macro')}")
        agents = [agent for agent in (node.get("agent_details") or []) if isinstance(agent, dict)]
        if agents:
            lines.extend(["", "에이전트 설정"])
            for agent in agents:
                lines.append(f"- {agent.get('name') or agent.get('agent_kind') or agent.get('type') or ''}")
                for key, value in agent.items():
                    if key in {"name", "_items", "_value"} or value in (None, "", [], {}):
                        continue
                    if isinstance(value, (dict, list)):
                        continue
                    lines.append(f"    {key}: {value}")
        elif node.get("agents"):
            names = []
            for agent in node.get("agents") or []:
                if isinstance(agent, dict):
                    names.append(str(agent.get("type") or agent.get("name") or ""))
            lines.extend(["", "에이전트  " + ", ".join(name for name in names if name)])
        edges = [edge for edge in (graph.get("edges") or []) if edge.get("from") == node.get("id")]
        lines.extend(["", "분기"])
        if not edges:
            lines.append("—")
        for edge in edges:
            dest = str(edge.get("to") or "").rsplit("/", 1)[-1]
            lines.append(f"{edge.get('caption') or ''} → {dest}")
            if edge.get("expression"):
                lines.append(str(edge["expression"]))
        irules, agent_ids, has_virtual = self._lookup_irules(node, graph)
        from app.modules.vpe_viewer.parser import _path_refs

        objects = (self._model or {}).get("objects") or {}
        refs = [
            ref
            for ref in _path_refs(node.get("agent_details") or [], objects)
            if (ref.get("object") or {}).get("object_kind") != "ltm rule"
        ]
        if refs:
            lines.extend(["", "참조 객체"])
            for ref in refs:
                title = str(ref.get("name") or "").rsplit("/", 1)[-1]
                kind = (ref.get("object") or {}).get("object_kind") or ref.get("key") or ""
                lines.append(f"- {title}  ({kind})")
        sources: list[str] = []
        if irules:
            lines.extend(["", "iRule"])
            for rule in irules:
                title = str(rule.get("name") or "").rsplit("/", 1)[-1]
                lines.append(f"- {title}  ({rule.get('object_kind') or 'ltm rule'})")
                source = str(rule.get("source") or "")
                if source:
                    sources.append(f"# {title}\n{source}")
                    lines.extend(["", source, ""])
        elif agent_ids and has_virtual:
            lines.extend(["", f"Access Profile이 적용된 Virtual Server iRule에서 agent_id {', '.join(agent_ids)} 를 찾지 못했습니다."])
        elif agent_ids:
            lines.extend(["", f"이 Access Profile에는 적용된 Virtual Server가 없고, 전체 ltm rule에서도 agent_id {', '.join(agent_ids)} 를 찾지 못했습니다."])
        if agent_ids and irules and not has_virtual:
            lines.extend(["", "이 Access Profile에는 적용된 Virtual Server가 없어 전체 ltm rule에서 agent_id로 찾았습니다."])
        self._set_detail("\n".join(lines), "\n\n".join(sources))

    def _fit(self) -> None:
        viewport = self._scroll.viewport()
        available = viewport.width() if viewport is not None else 0
        if available < 80:
            available = max(self._canvas.width() - 8, 640)
        self._zoom = min(max((available - 36) / max(self._main_width, 1), 0.35), 1.15)
        self._apply_scale()
        self._scroll.verticalScrollBar().setValue(0)
