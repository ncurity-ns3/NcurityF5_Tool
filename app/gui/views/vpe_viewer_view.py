"""APM access-policy viewer hosted on localhost and shown in the main window."""

from __future__ import annotations

import threading

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.gui.qt_utils import webengine_available
from app.gui.theme import mark_page_subtitle, mark_page_title


class VpeViewerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._httpd = None
        self._thread: threading.Thread | None = None
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
        self._host = QWidget()
        host_layout = QVBoxLayout(self._host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        self._status = QLabel("뷰어를 준비하는 중입니다.")
        self._status.setWordWrap(True)
        host_layout.addWidget(self._status)
        self._web = None
        root.addWidget(self._host, stretch=1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_started()

    def shutdown(self) -> None:
        server = self._httpd
        self._httpd = None
        if server is not None:
            server.shutdown()

    def _ensure_started(self) -> None:
        if self._httpd is not None or self._web is not None:
            return
        if not webengine_available():
            self._status.setText("이 환경에서는 페이지 뷰어를 열 수 없습니다. PyQt6-WebEngine이 필요합니다.")
            return
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from werkzeug.serving import make_server

        from app.modules.vpe_viewer.server import app

        try:
            self._httpd = make_server("127.0.0.1", 0, app, threaded=True)
        except OSError as exc:
            self._status.setText(f"뷰어 서버를 시작하지 못했습니다. {exc}")
            return
        port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="vpe-viewer", daemon=True)
        self._thread.start()
        self._status.hide()
        self._web = QWebEngineView(self._host)
        self._host.layout().addWidget(self._web)
        self._web.setUrl(QUrl(f"http://127.0.0.1:{port}/"))
