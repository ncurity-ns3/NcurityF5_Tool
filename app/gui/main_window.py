from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
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
from app.gui.session_manager import SessionManager
from app.gui.theme import polish_widget_scrollbars
from app.gui.views.delivery_form_view import DeliveryFormView
from app.gui.views.health_check_view import HealthCheckView
from app.gui.views.home_view import HomeView
from app.gui.views.hosted_content_view import HostedContentView
from app.gui.views.os_upgrade_check_view import OsUpgradeCheckView
from app.gui.views.placeholder_view import PlaceholderView
from app.gui.views.release_notes_view import ReleaseNotesCheckerView
from app.gui.views.ssl_cert_view import SslCertView
from app.gui.views.vpe_macro_view import VpeMacroView
from app.gui.views.vpe_viewer_view import VpeViewerView
from app.gui.views.waf_custom_view import WafCustomView
from app.gui.views.waf_view import WafView
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.widgets.panel_toggle import PanelToggle

_NAV_EXPANDED = 268
_NAV_COLLAPSED = 40
_NAV_SETTINGS_KEY = "ui/navCollapsed"


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

        self._nav_collapsed = False
        nav_frame = QFrame()
        self._nav_frame = nav_frame
        nav_frame.setObjectName("navFrame")
        nav_frame.setFixedWidth(_NAV_EXPANDED)
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)
        nav_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        nav_header = QFrame()
        self._nav_header = nav_header
        nav_header.setObjectName("navHeader")
        nav_header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        header_layout = QVBoxLayout(nav_header)
        header_layout.setContentsMargins(6, 8, 6, 8)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        self._nav_toggle = PanelToggle()
        self._nav_toggle.setObjectName("navToggle")
        self._nav_toggle.setToolTip("왼쪽 메뉴 접기")
        self._nav_toggle.clicked.connect(self._toggle_nav)
        toggle_row.addWidget(self._nav_toggle)
        toggle_row.addStretch(1)
        header_layout.addLayout(toggle_row)
        logo_lbl = QLabel()
        self._nav_logo = logo_lbl
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
            (
                "Device Check",
                [
                    ("정기 점검", 1),
                    ("OS 업그레이드 간 점검", 2),
                    ("SSL 인증서 확인", 3),
                    ("납품확인서 작성", 4),
                ],
            ),
            ("APM", [("VPE Viewer", 5), ("VPE Macro Copy", 6), ("Host Content 추출", 7)]),
            ("WAF", [("OWASP Top 10 취약점 공격", 8), ("Custom 공격 구문", 9)]),
            (
                "N-Health",
                [
                    ("Release Notes Checker", 10),
                    ("CVE Vulnerability Checker", 11),
                    ("Config Viewer", 12),
                    ("이슈 분석자료 수집", 13),
                    ("Log Search", 14),
                ],
            ),
            ("Initial Setup", [("Initial Setup", 15)]),
            ("Reports", [("Reports", 16)]),
            ("Settings", [("Settings", 17)]),
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
        self.set_nav_collapsed(self._stored_nav_collapsed(), persist=False)

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
        self.stack.addWidget(SslCertView())
        self.stack.addWidget(DeliveryFormView())
        self.stack.addWidget(VpeViewerView())
        self.stack.addWidget(VpeMacroView(project_root))
        self.stack.addWidget(HostedContentView())
        self.stack.addWidget(WafView())
        self.stack.addWidget(WafCustomView())
        self.stack.addWidget(ReleaseNotesCheckerView())
        self.stack.addWidget(
            PlaceholderView(
                "CVE Vulnerability Checker",
                "장비 버전의 CVE를 확인하는 화면입니다.",
            )
        )
        self.stack.addWidget(
            PlaceholderView(
                "Config Viewer",
                "UCS 또는 QKView에서 설정 정보를 보는 화면입니다.",
            )
        )
        self.stack.addWidget(
            PlaceholderView(
                "이슈 분석자료 수집",
                "이슈 분석에 필요한 QKView, 로그 tarball, Core 파일을 모으는 화면입니다.",
            )
        )
        self.stack.addWidget(
            PlaceholderView(
                "Log Search",
                "UCS 또는 QKView에서 로그를 찾는 화면입니다.",
            )
        )
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

    def nav_collapsed(self) -> bool:
        return self._nav_collapsed

    def set_nav_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        self._nav_collapsed = collapsed
        self._nav_frame.setFixedWidth(_NAV_COLLAPSED if collapsed else _NAV_EXPANDED)
        self.nav.setVisible(not collapsed)
        self._nav_logo.setVisible(not collapsed)
        self._nav_header.layout().setContentsMargins(6, 8, 6, 8)
        self._nav_toggle.set_open(not collapsed)
        self._nav_toggle.setToolTip("왼쪽 메뉴 열기" if collapsed else "왼쪽 메뉴 접기")
        if persist:
            QSettings(ORG_NAME, APP_TITLE).setValue(_NAV_SETTINGS_KEY, collapsed)

    def _toggle_nav(self) -> None:
        self.set_nav_collapsed(not self._nav_collapsed)

    def _stored_nav_collapsed(self) -> bool:
        value = QSettings(ORG_NAME, APP_TITLE).value(_NAV_SETTINGS_KEY, False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return bool(value)

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
        for view in self.findChildren(WafView):
            view.shutdown()
        for view in self.findChildren(WafCustomView):
            view.shutdown()
        SessionManager.instance().clear_all()
        super().closeEvent(event)
