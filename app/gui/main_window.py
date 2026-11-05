from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.gui.branding import (
    APP_TITLE,
    APP_VERSION_LABEL,
    NAV_HEADER_LOGO_MAX_HEIGHT,
    ORG_NAME,
    apply_window_icon,
    load_home_logo_pixmap,
)
from app.gui.form_controls import apply_form_control_policies
from app.gui.theme import polish_widget_scrollbars
from app.gui.session_manager import SessionManager
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.views.health_check_view import HealthCheckView
from app.gui.views.home_view import HomeView
from app.gui.views.os_upgrade_check_view import OsUpgradeCheckView
from app.gui.views.placeholder_view import PlaceholderView
from app.gui.views.vpe_macro_view import VpeMacroView
from app.gui.views.vpe_viewer_view import VpeViewerView


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path) -> None:
        super().__init__()

        self.project_root = project_root
        self.setWindowTitle(f"{APP_TITLE}  {APP_VERSION_LABEL}")
        apply_window_icon(self)
        self.resize(1140, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav_frame = QFrame()
        nav_frame.setObjectName("navFrame")
        nav_frame.setFixedWidth(228)
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        nav_header = QFrame()
        nav_header.setObjectName("navHeader")
        header_layout = QVBoxLayout(nav_header)
        header_layout.setContentsMargins(16, 16, 16, 12)
        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = load_home_logo_pixmap(max_height=NAV_HEADER_LOGO_MAX_HEIGHT, on_dark=False)
        if pix is not None:
            logo_lbl.setPixmap(pix)
            logo_lbl.setFixedSize(pix.width(), pix.height())
        header_layout.addWidget(logo_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(nav_header)

        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        sections = [
            ("Home", [("Home", 0)]),
            ("Device Check", [("정기 점검", 1), ("OS 업그레이드 간 점검", 2)]),
            ("APM", [("VPE Viewer", 3), ("VPE Macro Copy", 4)]),
            ("Initial Setup", [("Initial Setup", 5)]),
            ("Reports", [("Reports", 6)]),
            ("Settings", [("Settings", 7)]),
        ]
        for title, pages in sections:
            header = QListWidgetItem(title)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(Qt.ItemDataRole.UserRole, None)
            self.nav.addItem(header)
            for label, index in pages:
                item = QListWidgetItem("  " + label)
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.nav.addItem(item)
        self._select_page(0)
        nav_layout.addWidget(self.nav, stretch=1)

        layout.addWidget(nav_frame)

        content_host = QWidget()
        content_host.setObjectName("contentHost")
        content_layout = QVBoxLayout(content_host)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(HomeView())
        self.stack.addWidget(HealthCheckView(project_root))
        self.stack.addWidget(OsUpgradeCheckView(project_root))
        self.stack.addWidget(VpeViewerView())
        self.stack.addWidget(VpeMacroView(project_root))
        self.stack.addWidget(
            PlaceholderView(
                "Initial Setup",
                "초기 설정 설계 화면 — hostname, mgmt, vlan 등 (다음 구현)",
            )
        )
        self.stack.addWidget(
            PlaceholderView("Reports", "과거 job 리포트 브라우저 (다음 구현)")
        )
        self.stack.addWidget(
            PlaceholderView("Settings", "출력 폴더, 세션 옵션 (다음 구현)")
        )
        content_layout.addWidget(self.stack)
        layout.addWidget(content_host, stretch=1)

        self.nav.currentRowChanged.connect(self._on_nav)
        apply_form_control_policies(self)
        polish_widget_scrollbars(self)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"{APP_TITLE}  ·  {APP_VERSION_LABEL}  ·  offline  ·  {ORG_NAME}"
        )

        self.menuBar().hide()

    def _on_nav(self, row: int) -> None:
        item = self.nav.item(row)
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None:
            return
        self.stack.setCurrentIndex(int(index))

    def _select_page(self, page_index: int) -> None:
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == page_index:
                self.nav.setCurrentRow(row)
                return

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        polish_widget_scrollbars(self)

    def closeEvent(self, event) -> None:  # noqa: N802
        for panel in self.findChildren(DeviceConnectionPanel):
            panel._stop_test_worker()
        for view in self.findChildren(VpeMacroView):
            view.shutdown_workers()
        for view in self.findChildren(VpeViewerView):
            view.shutdown()
        SessionManager.instance().clear_all()
        super().closeEvent(event)
