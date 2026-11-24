"""Left menu collapse and VPE detail readability / diagram scrolling."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PyQt6.QtGui import (
    QDragEnterEvent,
    QMouseEvent,
    QPalette,
    QTextCursor,
    QTextOption,
    QWheelEvent,
)
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

from app.gui.branding import APP_TITLE, ORG_NAME
from app.gui.main_window import _NAV_COLLAPSED, _NAV_EXPANDED, _NAV_SETTINGS_KEY, MainWindow
from app.gui.views.vpe_viewer_view import VpeViewerView

_app = QApplication.instance() or QApplication([])
_ROOT = Path(__file__).resolve().parents[2]


def _restore_nav_setting(previous) -> None:
    settings = QSettings(ORG_NAME, APP_TITLE)
    if previous is None:
        settings.remove(_NAV_SETTINGS_KEY)
    else:
        settings.setValue(_NAV_SETTINGS_KEY, previous)


def test_nav_collapse_persists_and_keeps_the_page() -> None:
    settings = QSettings(ORG_NAME, APP_TITLE)
    previous = settings.value(_NAV_SETTINGS_KEY)
    settings.setValue(_NAV_SETTINGS_KEY, False)
    window = None
    again = None
    try:
        window = MainWindow(_ROOT)
        window.resize(1140, 800)
        window.show()
        _app.processEvents()
        window.stack.setCurrentIndex(4)
        _app.processEvents()

        assert window.nav_collapsed() is False
        assert window._nav_frame.width() == _NAV_EXPANDED
        assert window.nav.isVisible() is True
        assert window._nav_toggle.toolTip() == "왼쪽 메뉴 접기"
        assert window._nav_toggle.is_open() is True

        QTest.mouseClick(window._nav_toggle, Qt.MouseButton.LeftButton)
        _app.processEvents()

        assert window.nav_collapsed() is True
        assert window._nav_frame.width() == _NAV_COLLAPSED
        assert window.nav.isVisible() is False
        toggle_top = window._nav_toggle.mapTo(window._nav_frame, QPoint(0, 0)).y()
        assert toggle_top < 24
        assert window._nav_logo.isVisible() is False
        assert window._nav_toggle.toolTip() == "왼쪽 메뉴 열기"
        assert window._nav_toggle.is_open() is False
        assert window.stack.currentIndex() == 4

        again = MainWindow(_ROOT)
        again.show()
        _app.processEvents()
        assert again.nav_collapsed() is True
        assert again._nav_frame.width() == _NAV_COLLAPSED

        QTest.mouseClick(again._nav_toggle, Qt.MouseButton.LeftButton)
        _app.processEvents()
        assert again.nav_collapsed() is False
        assert again.nav.isVisible() is True
        assert window.stack.currentIndex() == 4
    finally:
        if window is not None:
            window.close()
        if again is not None:
            again.close()
        _app.processEvents()
        _restore_nav_setting(previous)


def _nav_item(window: MainWindow, label: str):
    for row in range(window.nav.count()):
        item = window.nav.item(row)
        if item.text().strip() == label:
            return item
    raise AssertionError(label)


def _click_nav(window: MainWindow, label: str) -> None:
    item = _nav_item(window, label)
    rect = window.nav.visualItemRect(item)
    QTest.mouseClick(window.nav.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    _app.processEvents()


def test_big_sections_collapse_and_keep_the_active_page() -> None:
    settings = QSettings(ORG_NAME, APP_TITLE)
    previous = settings.value(_NAV_SETTINGS_KEY)
    settings.setValue(_NAV_SETTINGS_KEY, False)
    window = None
    try:
        window = MainWindow(_ROOT)
        window.resize(1140, 800)
        window.show()
        _app.processEvents()
        qkview = _nav_item(window, "정기 점검")
        logs = _nav_item(window, "Log Search")
        labels = [window.nav.item(row).text().strip() for row in range(window.nav.count())]
        assert labels.count("Home") == 1
        assert labels.count("Initial Setup") == 1
        assert labels.count("Reports") == 1
        assert labels.count("Settings") == 1
        assert window.nav.currentItem().text().strip() == "Home"
        assert window.nav.currentItem().toolTip() == "접기"
        assert qkview.isHidden() is True
        assert logs.isHidden() is True

        _click_nav(window, "Device Check")
        assert qkview.isHidden() is False
        assert logs.isHidden() is True
        assert window.stack.currentIndex() == 0

        _click_nav(window, "트러블슈팅 자료 수집")
        assert window.stack.currentIndex() == 4
        assert window.nav.currentItem().text().strip() == "트러블슈팅 자료 수집"

        _click_nav(window, "Device Check")
        assert qkview.isHidden() is True
        assert window.stack.currentIndex() == 4
        assert window.nav.currentItem().text().strip() == "Device Check"

        _click_nav(window, "N-Health")
        assert logs.isHidden() is False
        assert qkview.isHidden() is True
        assert window.nav.currentItem().text().strip() == "Device Check"
    finally:
        if window is not None:
            window.close()
        _app.processEvents()
        _restore_nav_setting(previous)


def test_nhealth_sits_between_waf_and_initial_setup() -> None:
    settings = QSettings(ORG_NAME, APP_TITLE)
    previous = settings.value(_NAV_SETTINGS_KEY)
    settings.setValue(_NAV_SETTINGS_KEY, False)
    window = None
    try:
        window = MainWindow(_ROOT)
        labels = []
        for row in range(window.nav.count()):
            item = window.nav.item(row)
            index = item.data(Qt.ItemDataRole.UserRole)
            labels.append((item.text().strip(), index))
        names = [label for label, _index in labels]
        waf = names.index("Custom 공격 구문")
        initial = names.index("Initial Setup")
        section = names[waf + 1 : initial]
        assert section == [
            "N-Health",
            "Release Notes Checker",
            "CVE Vulnerability Checker",
            "Config Viewer",
            "Log Search",
        ]
        for label, index in labels:
            if label not in {
                "Release Notes Checker",
                "CVE Vulnerability Checker",
                "Config Viewer",
                "Log Search",
            }:
                continue
            page = window.stack.widget(int(index))
            assert page.findChild(QLabel).text() == label
    finally:
        if window is not None:
            window.close()
        _app.processEvents()
        _restore_nav_setting(previous)


def _show_scrollable(view: VpeViewerView) -> None:
    view.resize(900, 520)
    view.show()
    view._hint.hide()
    view._scroll.show()
    view._view.show()
    view._view.resize(700, 360)
    view._page.setMinimumSize(1600, 2400)
    _app.processEvents()


def _send_wheel(widget, delta_y: int, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    local = QPointF(40, 40)
    event = QWheelEvent(
        local,
        QPointF(widget.mapToGlobal(QPoint(40, 40))),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_detail_text_is_large_wrapped_and_high_contrast() -> None:
    view = VpeViewerView()
    view._set_detail("설명\n" + ("customization-group-very-long-value-" * 12))
    _app.processEvents()

    font = view._detail.font()
    assert font.pixelSize() >= 14 or font.pointSize() >= 11
    assert view._detail.wordWrapMode() == QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
    cursor = view._detail.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    assert cursor.blockFormat().lineHeight() == 160
    text = view._detail.palette().color(QPalette.ColorRole.Text)
    base = view._detail.palette().color(QPalette.ColorRole.Base)
    assert text.red() < 50 and text.green() < 70 and text.blue() < 80
    assert base.red() > 240 and base.green() > 240 and base.blue() > 240
    assert "customization-group-very-long-value-" in view._detail.toPlainText()
    view.close()


def test_wheel_scrolls_the_flow_and_ctrl_wheel_zooms() -> None:
    view = VpeViewerView()
    _show_scrollable(view)
    bar = view._scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)

    _send_wheel(view._view.viewport(), -120)
    _app.processEvents()
    assert bar.value() == 72

    zoom_before = view._zoom
    scroll_before = bar.value()
    _send_wheel(view._view.viewport(), 120, Qt.KeyboardModifier.ControlModifier)
    _app.processEvents()
    assert view._zoom > zoom_before
    assert bar.value() == scroll_before
    view.close()


def test_middle_click_shows_autoscroll_mark_and_moves() -> None:
    view = VpeViewerView()
    _show_scrollable(view)
    bar = view._scroll.verticalScrollBar()
    bar.setValue(0)
    viewport = view._view.viewport()
    local = QPointF(80, 80)
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        QPointF(viewport.mapToGlobal(QPoint(80, 80))),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, press)
    _app.processEvents()
    assert view._mark.isVisible() is True
    origin = view._auto_origin
    view._auto_point = view._scroll.viewport().mapToGlobal(origin + QPoint(0, 80))
    view._auto_tick()
    assert bar.value() > 0
    QApplication.sendEvent(viewport, press)
    _app.processEvents()
    assert view._mark.isVisible() is False
    view.close()


def test_profile_and_description_panels_collapse() -> None:
    view = VpeViewerView()
    view.resize(1000, 600)
    view.show()
    _app.processEvents()
    assert view._profiles.isVisible() is True
    assert view._detail.isVisible() is True
    view._profile_toggle.click()
    view._detail_toggle.click()
    _app.processEvents()
    assert view._profiles.isVisible() is False
    assert view._detail.isVisible() is False
    assert view._profile_toggle.is_open() is False
    assert view._detail_toggle.is_open() is False
    assert view._profile_wrap.maximumWidth() <= 40
    assert view._detail_box.maximumWidth() <= 40
    view._profile_toggle.click()
    view._detail_toggle.click()
    assert view._profiles.isVisible() is True
    assert view._detail.isVisible() is True
    view.close()


def test_detail_shows_aaa_settings_and_irule_code_card() -> None:
    view = VpeViewerView()
    view._model = {
        "objects": {
            "/Common/HTTP_FIDO_HKMC": {
                "name": "/Common/HTTP_FIDO_HKMC",
                "object_kind": "aaa http",
                "auth-type": "form-based",
                "start-uri": "/fido/start",
            },
            "/Common/AD_CORP": {
                "name": "/Common/AD_CORP",
                "object_kind": "aaa active-directory",
                "domain": "corp.local",
            },
        }
    }
    view._show_detail(
        {
            "caption": "HTTP Auth(FIDO)",
            "id": "/Common/item",
            "kind": "action",
            "item_type": "action",
            "agent_details": [
                {
                    "name": "/Common/ag",
                    "agent_kind": "aaa-http",
                    "server": "/Common/HTTP_FIDO_HKMC",
                },
                {
                    "name": "/Common/adag",
                    "agent_kind": "aaa-active-directory",
                    "server": "/Common/AD_CORP",
                },
            ],
        },
        {"edges": []},
    )
    text = view._detail.toPlainText()
    assert "form-based" in text
    assert "/fido/start" in text
    assert "corp.local" in text
    assert "인증 방식" in text
    source = "    set id [ACCESS::session data get]"
    view._set_detail("iRule\n- Rule_Fido", [("Rule_Fido", source)])
    html = view._detail.toHtml()
    assert "Consolas" in html
    assert "ACCESS::session" in view._detail.toPlainText()
    assert view._copy.isHidden() is False
    view.close()


def test_drop_on_the_drawn_graph_is_accepted() -> None:
    view = VpeViewerView()
    _show_scrollable(view)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/temp/sample.ucs")])
    event = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view._view.viewport(), event)
    assert event.isAccepted() is True
    view.close()
