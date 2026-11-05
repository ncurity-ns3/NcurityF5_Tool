from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QPushButton, QVBoxLayout

from app.gui.widgets.report_viewer import ReportViewer


class ReportWindow(QDialog):
    """full-size report viewer in a separate window."""

    def __init__(self, html_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Health Check Report — {html_path.parent.name}")
        self.resize(1100, 800)
        layout = QVBoxLayout(self)
        viewer = ReportViewer(self)
        viewer.load_html_file(html_path)
        layout.addWidget(viewer, stretch=1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
