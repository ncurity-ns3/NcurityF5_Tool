from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QSettings, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
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
from app.gui.theme import BRAND_PRIMARY, TEXT_MUTED, polish_widget_scrollbars
from app.gui.views.cve_checker_view import CveCheckerView
from app.gui.views.delivery_form_view import DeliveryFormView
from app.gui.views.health_check_view import HealthCheckView
from app.gui.views.home_view import HomeView
from app.gui.views.hosted_content_view import HostedContentView
from app.gui.views.os_upgrade_check_view import OsUpgradeCheckView
from app.gui.views.placeholder_view import PlaceholderView
from app.gui.views.release_notes_view import ReleaseNotesCheckerView
from app.gui.views.ssl_cert_view import SslCertView
from app.gui.views.troubleshooting_view import TroubleshootingView
from app.gui.views.vpe_macro_view import VpeMacroView
from app.gui.views.vpe_viewer_view import VpeViewerView
from app.gui.views.waf_custom_view import WafCustomView
from app.gui.views.waf_view import WafView
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.gui.widgets.panel_toggle import PanelToggle

_NAV_EXPANDED = 268
_NAV_COLLAPSED = 40
_NAV_SETTINGS_KEY = "ui/navCollapsed"
_SECTION_ROLE = Qt.ItemDataRole.UserRole + 1
_HEADER_ROLE = Qt.ItemDataRole.UserRole + 2


def _chevron_icon(opened: bool, color: str) -> QIcon:
    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.8))
    if opened:
        points = (QPointF(4, 6), QPointF(8, 11), QPointF(12, 6))
    else:
        points = (QPointF(6, 4), QPointF(11, 8), QPointF(6, 12))
    painter.drawPolyline(QPolygonF(points))
    painter.end()
    return QIcon(pix)


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
        self._page_index = 0
        self._expanded_section: str | None = "Home"
        self._chevron_icons = {
            ("open", "brand"): _chevron_icon(True, BRAND_PRIMARY),
            ("shut", "brand"): _chevron_icon(False, BRAND_PRIMARY),
            ("shut", "muted"): _chevron_icon(False, TEXT_MUTED),
        }
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
                    ("트러블슈팅 자료 수집", 4),
                    ("납품확인서 작성", 5),
                ],
            ),
            ("APM", [("VPE Viewer", 6), ("VPE Macro Copy", 7), ("Host Content 추출", 8)]),
            ("WAF", [("OWASP Top 10 취약점 공격", 9), ("Custom 공격 구문", 10)]),
            (
                "N-Health",
                [
                    ("Release Notes Checker", 11),
                    ("CVE Vulnerability Checker", 12),
                    ("Config Viewer", 13),
                    ("Log Search", 14),
                ],
            ),
            ("Initial Setup", [("Initial Setup", 15)]),
            ("Reports", [("Reports", 16)]),
            ("Settings", [("Settings", 17)]),
        ]
        for title, pages in sections:
            direct = len(pages) == 1
            header = QListWidgetItem(title)
            header.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            header.setData(_SECTION_ROLE, title)
            header.setData(_HEADER_ROLE, True)
            header.setData(Qt.ItemDataRole.UserRole, pages[0][1] if direct else None)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.nav.addItem(header)
            if direct:
                continue
            for label, index in pages:
                item = QListWidgetItem("  " + label)
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setData(_SECTION_ROLE, title)
                self.nav.addItem(item)
        self._apply_sections()
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
        self.stack.addWidget(TroubleshootingView(project_root))
        self.stack.addWidget(DeliveryFormView())
        self.stack.addWidget(VpeViewerView())
        self.stack.addWidget(VpeMacroView(project_root))
        self.stack.addWidget(HostedContentView())
        self.stack.addWidget(WafView())
        self.stack.addWidget(WafCustomView())
        self.stack.addWidget(ReleaseNotesCheckerView())
        self.stack.addWidget(CveCheckerView())
        self.stack.addWidget(
            PlaceholderView(
                "Config Viewer",
                "UCS 또는 QKView에서 설정 정보를 보는 화면입니다.",
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
        self.nav.itemClicked.connect(self._on_nav_clicked)
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
        self._page_index = int(index)
        self.stack.setCurrentIndex(self._page_index)

    def _on_nav_clicked(self, item: QListWidgetItem) -> None:
        if not item.data(_HEADER_ROLE):
            return
        section = str(item.data(_SECTION_ROLE) or "")
        page = item.data(Qt.ItemDataRole.UserRole)
        if page is not None:
            self._page_index = int(page)
            self._expanded_section = section
            self.stack.setCurrentIndex(self._page_index)
            self._apply_sections()
            return
        self._expanded_section = None if self._expanded_section == section else section
        self._apply_sections()

    def _apply_sections(self) -> None:
        page_section = ""
        active_row = 0
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == self._page_index:
                active_row = row
                page_section = str(item.data(_SECTION_ROLE) or "")
        self.nav.blockSignals(True)
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            section = str(item.data(_SECTION_ROLE) or "")
            if item.data(_HEADER_ROLE):
                opened = self._expanded_section == section
                tone = "brand" if opened or section == page_section else "muted"
                kind = "open" if opened else "shut"
                item.setIcon(self._chevron_icons[(kind, tone)])
                item.setToolTip("접기" if opened else "펼치기")
                continue
            if section:
                item.setHidden(self._expanded_section != section)
        if page_section and self.nav.item(active_row).isHidden():
            header = self._header_row(page_section)
            if header is not None:
                active_row = header
        self.nav.setCurrentRow(active_row)
        self.nav.blockSignals(False)

    def _header_row(self, section: str) -> int | None:
        if not section:
            return None
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            if item.data(_HEADER_ROLE) and item.data(_SECTION_ROLE) == section:
                return row
        return None

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
        for view in self.findChildren(TroubleshootingView):
            view.shutdown()
        SessionManager.instance().clear_all()
        super().closeEvent(event)
