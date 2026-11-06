"""APM access-policy viewer drawn with the same widgets as the other pages."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
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
        root.addLayout(tools)

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

        splitter = QSplitter()
        splitter.addWidget(self._profiles)
        splitter.addWidget(self._canvas)
        splitter.addWidget(self._detail)
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

    def _show_policy(self, name: str) -> None:
        from app.modules.vpe_viewer.server import _policy_bundle

        if self._model is None:
            return
        bundle = _policy_bundle(self._model, name)
        if not bundle or not bundle.get("policies"):
            self._status.setText(f"정책을 찾을 수 없습니다: {name}")
            return
        policy = bundle["policies"][0]
        self._draw(policy)
        caption = policy.get("caption") or name.rsplit("/", 1)[-1]
        self._status.setText(str(caption))

    def _draw(self, policy: dict) -> None:
        self._hint.hide()
        self._view.show()
        self._scene.clear()
        title = QGraphicsSimpleTextItem(str(policy.get("caption") or ""))
        title.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        title.setBrush(QBrush(QColor("#0260EA")))
        title.setPos(24, 8)
        self._scene.addItem(title)
        laid = layout_graph(policy)
        offset_x = 24
        offset_y = 48
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
        bounds = self._scene.itemsBoundingRect().adjusted(-24, -12, 48, 36)
        self._scene.setSceneRect(bounds)
        self._detail.clear()
        QTimer.singleShot(0, self._fit)

    def _on_node(self, node: dict, graph: dict) -> None:
        if node.get("kind") == "macro":
            target = str(node.get("macro") or node.get("id") or "")
            if target:
                self._show_policy(target)
                return
        self._show_detail(node, graph)

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
        self._detail.setPlainText("\n".join(lines))

    def _fit(self) -> None:
        rect = self._scene.sceneRect()
        if rect.isEmpty():
            return
        self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
