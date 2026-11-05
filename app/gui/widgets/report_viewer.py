from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

try:
    from PyQt6.QtWebEngineCore import QWebEnginePage
except ImportError:  # pragma: no cover
    QWebEnginePage = None  # type: ignore[misc, assignment]

from app.gui.qt_utils import webengine_available


class ReportViewer(QWidget):
    """QWebEngine must be bootstrapped in app.gui.main before QApplication."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._view: QWidget | None = None
        self._placeholder = QLabel("Run Health Check 후 리포트가 여기에 표시됩니다.")
        self._placeholder.setWordWrap(True)
        self._layout.addWidget(self._placeholder)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        self._placeholder.hide()
        if webengine_available():
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            self._view = QWebEngineView()
            if QWebEnginePage is not None:
                page = self._view.page()
                if isinstance(page, QWebEnginePage):

                    def _on_load_finished(ok: bool) -> None:
                        if not ok or not isinstance(self._view, QWebEngineView):
                            return
                        self._view.setZoomFactor(1.0)
                        page.runJavaScript(
                            "document.querySelectorAll('table').forEach("
                            "t => { t.style.tableLayout = 'fixed'; });"
                        )

                    page.loadFinished.connect(_on_load_finished)
        else:
            self._view = QTextBrowser()
            self._view.setPlaceholderText(
                "html 미리보기: PyQt6-WebEngine 필요 (개발 PC에서만 pip install)\n"
                "현장 배포 exe에는 포함 예정"
            )
        self._layout.addWidget(self._view)

    def load_html_file(self, path: Path) -> None:
        if not path.is_file():
            return
        self._ensure_view()
        assert self._view is not None
        if webengine_available():
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            if isinstance(self._view, QWebEngineView):
                self._view.load(QUrl.fromLocalFile(str(path.resolve())))
                return
        if isinstance(self._view, QTextBrowser):
            self._view.setHtml(path.read_text(encoding="utf-8"))
