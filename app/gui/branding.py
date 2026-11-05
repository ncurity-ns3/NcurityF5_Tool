"""Ncurity application branding (title, window icon, org metadata)."""

from __future__ import annotations

import sys
from pathlib import Path

from app import __version__ as APP_VERSION

APP_TITLE = "Ncurity F5 Big-IP Managing Tool"
APP_VERSION_LABEL = f"v{APP_VERSION}"
ORG_NAME = "Ncurity"
ORG_DOMAIN = "ncurity.co.kr"
APP_USER_MODEL_ID = "Ncurity.F5BigIPManagingTool.1"

# Taskbar / title bar / Dock: Ncurity symbol.
_APP_ICON_NAMES = ("ncurity_app_icon.ico", "ncurity_app_icon.png")
# Home banner: blue logo on white (symbol + 엔큐리티).
_HOME_LOGO_NAMES = ("ncurity_home_logo.png", "ncurity_app_icon.png")
# Nav header / blue strips: white logo variant.
_HOME_LOGO_ON_DARK_NAMES = ("ncurity_home_logo_white.png",)
HOME_LOGO_MAX_HEIGHT = 118
NAV_HEADER_LOGO_MAX_HEIGHT = 48


def resources_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "resources"


def _first_existing(names: tuple[str, ...]) -> Path | None:
    base = resources_dir()
    for name in names:
        path = base / name
        if path.is_file():
            return path
    return None


def app_icon_path() -> Path | None:
    return _first_existing(_APP_ICON_NAMES)


def home_logo_path(*, on_dark: bool = False) -> Path | None:
    if on_dark:
        path = _first_existing(_HOME_LOGO_ON_DARK_NAMES)
        if path is not None:
            return path
    return _first_existing(_HOME_LOGO_NAMES)


def load_app_icon():
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    base = resources_dir()
    # Windows: 멀티 해상도 .ico 를 쓰면 작업 표시줄이 24/32 등에 맞는 프레임을 고름.
    # 단일 대형 PNG만 addFile 하면 축소 시 흐릿·작게 보일 수 있음.
    ico = base / "ncurity_app_icon.ico"
    if ico.is_file():
        icon = QIcon(str(ico))
        if not icon.isNull():
            return icon

    png = base / "ncurity_app_icon.png"
    if png.is_file():
        icon = QIcon()
        for size in (16, 20, 24, 32, 40, 48, 64, 128, 256, 512):
            icon.addFile(str(png), QSize(size, size))
        if not icon.isNull():
            return icon

    path = app_icon_path()
    if path is None:
        return None
    fb = QIcon(str(path))
    return fb if not fb.isNull() else None


def platform_setup_before_qt() -> None:
    """Windows: separate taskbar pin from generic python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001
        pass


def apply_platform_dock_icon() -> None:
    """macOS Dock: override Python default when running via interpreter."""
    if sys.platform != "darwin":
        return
    png = resources_dir() / "ncurity_app_icon.png"
    if not png.is_file():
        return
    try:
        from AppKit import NSApplication, NSImage
    except ImportError:
        return
    img = NSImage.alloc().initWithContentsOfFile_(str(png.resolve()))
    if img is None:
        return
    NSApplication.sharedApplication().setApplicationIconImage_(img)


def load_home_logo_pixmap(*, max_height: int = HOME_LOGO_MAX_HEIGHT, on_dark: bool = False):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

    path = home_logo_path(on_dark=on_dark)
    if path is None:
        return None
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    if pix.height() <= max_height:
        return pix
    return pix.scaledToHeight(
        max_height,
        Qt.TransformationMode.SmoothTransformation,
    )


def apply_app_branding(app) -> None:
    """Set global Qt application name and default window icon (taskbar)."""
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    icon = load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)


def apply_window_icon(window) -> None:
    icon = load_app_icon()
    if icon is not None:
        window.setWindowIcon(icon)
