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
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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
        font = QFont("Malgun Gothic", 9)
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
    def __init__(self, scene: QGraphicsScene, on_file) -> None:
        super().__init__(scene)
        self._on_file = on_file
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
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)


class VpeViewerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._model: dict | None = None
        self._worker: _LoadWorker | None = None
        self._policy: dict | None = None
        self._macro_anchors: dict[str, float] = {}
        self._main_rect: QRectF | None = None
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
        zoom_out.clicked.connect(lambda: self._view.scale(1 / 1.2, 1 / 1.2))
        zoom_in.clicked.connect(lambda: self._view.scale(1.2, 1.2))
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
        self._view = _GraphView(self._scene, self._load_path)
        self._view.setObjectName("vpeGraph")
        self._view.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setBackgroundBrush(QBrush(QColor("#F7F9FC")))
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
        canvas_layout.addWidget(self._view)
        self._view.hide()
        self._macros = QListWidget()
        self._macros.setObjectName("vpeMacroList")
        self._macros.setMaximumHeight(140)
        self._macros.hide()
        self._macros.itemClicked.connect(self._on_macro)
        canvas_layout.addWidget(self._macros)
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
            QListWidget#vpeProfileList, QListWidget#vpeMacroList, QTextEdit, QFrame#vpeCanvas {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }
            QListWidget#vpeProfileList::item { padding: 6px 8px; }
            QListWidget#vpeProfileList::item:selected { background: #EDF5FF; color: #0260EA; }
            QGraphicsView#vpeGraph { background: #F7F9FC; border: none; }
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
        self._fill_macros(policy)
        self._show_overview(policy)
        caption = policy.get("caption") or name.rsplit("/", 1)[-1]
        self._status.setText(str(caption))

    def _draw_stack(self, policy: dict, macros: list[dict], focus: str = "") -> None:
        self._hint.hide()
        self._view.show()
        self._scene.clear()
        self._macro_anchors = {}
        cursor = self._paint_section(policy, 8, macro=False)
        self._main_rect = QRectF(self._scene.itemsBoundingRect())
        for macro in macros:
            cursor += 18
            cursor = self._paint_section(macro, cursor, macro=True)
        bounds = self._scene.itemsBoundingRect().adjusted(-24, -12, 48, 36)
        self._scene.setSceneRect(bounds)
        QTimer.singleShot(0, lambda: self._reveal(focus))

    def _paint_section(self, policy: dict, top: float, *, macro: bool) -> float:
        caption = str(policy.get("caption") or policy.get("name") or "")
        if macro:
            name = str(policy.get("name") or "")
            self._macro_anchors[name] = top
            last = name.rsplit("/", 1)[-1]
            self._macro_anchors.setdefault(last, top)
            bar = QGraphicsRectItem(16, top, 420, 28)
            bar.setBrush(QBrush(QColor("#e7eef8")))
            bar.setPen(QPen(QColor("#c5d2e2")))
            self._scene.addItem(bar)
            header = QGraphicsSimpleTextItem(f"Macro: {caption}")
            header.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
            header.setBrush(QBrush(QColor("#0260EA")))
            header.setPos(28, top + 4)
            self._scene.addItem(header)
            graph_top = top + 40
        else:
            title = QGraphicsSimpleTextItem(caption)
            title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
            title.setBrush(QBrush(QColor("#0260EA")))
            title.setPos(24, top)
            self._scene.addItem(title)
            graph_top = top + 36
        return self._paint_graph(policy, graph_top)

    def _paint_graph(self, policy: dict, offset_y: float) -> float:
        laid = layout_graph(policy)
        offset_x = 24.0
        for node in laid["nodes"]:
            placed = {**node, "x": node["x"] + offset_x, "y": node["y"] + offset_y}
            self._scene.addItem(_NodeItem(placed, policy, self._on_node))
        edge_pen = QPen(QColor("#5d6b78"), 1.6)
        edge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for edge in laid["edges"]:
            x1 = edge["x1"] + offset_x
            x2 = edge["x2"] + offset_x
            y = edge["y"] + offset_y
            path = QPainterPath()
            path.moveTo(x1, y)
            path.lineTo(x2, y)
            item = QGraphicsPathItem(path)
            item.setPen(edge_pen)
            self._scene.addItem(item)
            if x2 > x1 + 8:
                head = QPainterPath()
                head.moveTo(x2, y)
                head.lineTo(x2 - 8, y - 4)
                head.lineTo(x2 - 8, y + 4)
                head.closeSubpath()
                arrow = QGraphicsPathItem(head)
                arrow.setPen(QPen(Qt.PenStyle.NoPen))
                arrow.setBrush(QBrush(QColor("#6a7684")))
                self._scene.addItem(arrow)
            caption = str(edge.get("caption") or "")
            if caption:
                label = QGraphicsSimpleTextItem(caption)
                label.setFont(QFont("Malgun Gothic", 8, QFont.Weight.Bold))
                label.setBrush(QBrush(QColor("#1f3348")))
                label.setPos(x1 + 10, y - 16)
                self._scene.addItem(label)
        return offset_y + float(laid.get("height") or 180)

    def _reveal(self, focus: str) -> None:
        self._fit()
        if focus:
            self._scroll_to_macro(focus)

    def _scroll_to_macro(self, name: str) -> None:
        top = self._macro_anchors.get(name)
        if top is None:
            last = name.rsplit("/", 1)[-1]
            top = self._macro_anchors.get(last)
        if top is None:
            for anchor, anchor_top in self._macro_anchors.items():
                if anchor.endswith("/" + name) or anchor.endswith("/" + name.rsplit("/", 1)[-1]):
                    top = anchor_top
                    break
        if top is None:
            return
        center_x = self._scene.sceneRect().center().x()
        self._view.centerOn(center_x, top + 80)
        caption = name.rsplit("/", 1)[-1]
        self._status.setText(f"Macro: {caption}")

    def _on_node(self, node: dict, graph: dict) -> None:
        if node.get("kind") == "macro":
            target = str(node.get("macro") or node.get("id") or "")
            short = target.rsplit("/", 1)[-1]
            if target in self._macro_anchors or short in self._macro_anchors:
                self._scroll_to_macro(target)
                self._show_detail(node, graph)
                return
        self._show_detail(node, graph)

    def _on_macro(self, item: QListWidgetItem) -> None:
        name = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if name:
            self._scroll_to_macro(name)

    def _fill_macros(self, policy: dict) -> None:
        self._macros.clear()
        if policy.get("type") == "macro":
            self._macros.hide()
            return
        names = []
        for macro in policy.get("macros") or []:
            if isinstance(macro, str) and macro:
                names.append(macro)
        for node in policy.get("nodes") or []:
            macro = node.get("macro")
            if isinstance(macro, str) and macro and macro not in names:
                names.append(macro)
        if not names:
            self._macros.hide()
            return
        graphs = getattr(self, "_graphs", {})
        for name in names:
            graph = graphs.get(name) or {}
            label = str(graph.get("caption") or name.rsplit("/", 1)[-1])
            row = QListWidgetItem(f"Macro: {label}")
            row.setData(Qt.ItemDataRole.UserRole, name)
            row.setToolTip(name)
            self._macros.addItem(row)
        self._macros.show()

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
            if isinstance(item, _NodeItem) and query in str(item._node.get("caption") or "").lower():
                hits.append(("node", item))
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
            self._view.centerOn(target)
            self._show_detail(target._node, target._graph)
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
        rect = self._scene.sceneRect()
        if self._main_rect is not None and not self._main_rect.isEmpty():
            rect = self._main_rect
        if rect.isEmpty():
            return
        self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
