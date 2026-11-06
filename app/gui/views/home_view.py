from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.gui.branding import APP_TITLE, APP_VERSION_LABEL, ORG_NAME, load_home_logo_pixmap
from app.gui.theme import mark_page_subtitle, mark_page_title


class HomeView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Home")
        mark_page_title(title)
        root.addWidget(title)

        hero = QFrame()
        hero.setProperty("role", "heroCard")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 20, 24, 20)
        hero_layout.setSpacing(24)

        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = load_home_logo_pixmap(on_dark=False)
        if pix is not None:
            logo.setPixmap(pix)
            logo.setFixedSize(pix.width(), pix.height())
            logo.setToolTip(ORG_NAME)
        else:
            logo.setText("Ncurity")
            logo.setProperty("role", "pageTitle")
        hero_layout.addWidget(logo)

        text_col = QVBoxLayout()
        text_col.setSpacing(8)
        app_title = QLabel(APP_TITLE)
        app_title.setProperty("role", "infoTitle")
        app_title.setStyleSheet("font-size: 17px;")
        text_col.addWidget(app_title)
        version_lbl = QLabel(f"Version {APP_VERSION_LABEL}")
        version_lbl.setProperty("role", "muted")
        text_col.addWidget(version_lbl)
        lead = QLabel(
            "F5 BIG-IP 현장 점검·OS 업그레이드 작업을 위한 통합 도구입니다. "
            "왼쪽 메뉴에서 작업을 선택하세요."
        )
        lead.setWordWrap(True)
        lead.setProperty("role", "pageSubtitle")
        mark_page_subtitle(lead)
        text_col.addWidget(lead)
        hero_layout.addLayout(text_col, stretch=1)
        root.addWidget(hero)

        info = QFrame()
        info.setProperty("role", "infoCard")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_title = QLabel("빠른 안내")
        info_title.setProperty("role", "infoTitle")
        info_layout.addWidget(info_title)
        info_layout.addWidget(
            QLabel(
                "• <b>Device Check</b> — 정기 점검, OS 업그레이드 간 점검, 납품확인서 작성<br>"
                "• <b>WAF</b> — OWASP Top 10은 항목별 차단 요약, 요청 작성은 직접 전송<br>"
                "• <b>VPE Viewer</b> — qkview / UCS / bigip.conf의 APM Access Policy 흐름<br>"
                "• <b>VPE Macro Copy</b> — 로그인 후 Access Profile의 Macro 조회·복제·저장<br>"
                "• 저장 Session/장비 목록은 점검 메뉴에서 동일 경로 공유<br>"
                "• 리포트 HTML은 작업 폴더에 저장 · Report 버튼으로 미리보기"
            )
        )
        root.addWidget(info)

        soon = QLabel("Initial Setup · Reports — 다음 단계에서 제공 예정")
        soon.setProperty("role", "muted")
        root.addWidget(soon)
        root.addStretch()
