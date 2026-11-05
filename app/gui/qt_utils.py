from __future__ import annotations

import os
from pathlib import Path

_WEBENGINE_READY: bool = False
_WEBENGINE_ERROR: str = ""


def _prepare_qt_dll_paths() -> None:
    """windows: Qt6 bin must be on dll search path for WebEngine."""
    import os

    os.environ.setdefault("QT_LOGGING_RULES", "qt.gui.edid=false;*.warning=false")
    os.environ.setdefault("QT_LOGGING_TO_CONSOLE", "0")
    try:
        import PyQt6

        qt_bin = Path(PyQt6.__file__).resolve().parent / "Qt6" / "bin"
        if qt_bin.is_dir():
            os.add_dll_directory(str(qt_bin))
        qt_plugins = Path(PyQt6.__file__).resolve().parent / "Qt6" / "plugins"
        if qt_plugins.is_dir():
            os.environ.setdefault("QT_PLUGIN_PATH", str(qt_plugins))
    except Exception:
        pass


def bootstrap_webengine_before_qapplication() -> bool:
    """
    must run before QApplication() is created.
    see: QtWebEngineWidgets import or AA_ShareOpenGLContexts.
    """
    global _WEBENGINE_READY, _WEBENGINE_ERROR
    _prepare_qt_dll_paths()
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    except Exception as exc:
        _WEBENGINE_ERROR = f"AA_ShareOpenGLContexts: {exc}"

    try:
        import PyQt6.QtWebEngineCore  # noqa: F401
        import PyQt6.QtWebEngineWidgets  # noqa: F401

        _WEBENGINE_READY = True
        _WEBENGINE_ERROR = ""
        return True
    except Exception as exc:
        _WEBENGINE_READY = False
        _WEBENGINE_ERROR = str(exc)
        return False


def webengine_available() -> bool:
    return _WEBENGINE_READY


def webengine_error_message() -> str:
    return _WEBENGINE_ERROR
