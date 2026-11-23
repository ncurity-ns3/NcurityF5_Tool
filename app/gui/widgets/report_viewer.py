from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor
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
        self._placeholder = QLabel("보고서를 여는 중…")
        self._placeholder.setWordWrap(True)
        self._layout.addWidget(self._placeholder)

    def _ensure_view(self) -> None:
        if self._view is not None:
            return
        if webengine_available():
            from PyQt6.QtWebEngineWidgets import QWebEngineView

            view = QWebEngineView()
            view.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
            page = view.page()
            if QWebEnginePage is not None and isinstance(page, QWebEnginePage):
                page.setBackgroundColor(QColor("#F7F9FC"))

                def _on_load_finished(ok: bool) -> None:
                    if not isinstance(self._view, QWebEngineView):
                        return
                    if ok:
                        self._view.setZoomFactor(1.0)
                    self._placeholder.hide()
                    self._view.show()

                page.loadFinished.connect(_on_load_finished)
            view.hide()
            self._view = view
            if QWebEnginePage is None or not isinstance(page, QWebEnginePage):
                self._placeholder.hide()
                view.show()
        else:
            self._placeholder.hide()
            browser = QTextBrowser()
            browser.setPlaceholderText(
                "html 미리보기: PyQt6-WebEngine 필요 (개발 PC에서만 pip install)\n"
                "현장 배포 exe에는 포함 예정"
            )
            self._view = browser
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
