#!/usr/bin/env python3
"""diagnose PyQt6-WebEngine load (run from project venv)."""

from __future__ import annotations

import sys

from app.gui.qt_utils import bootstrap_webengine_before_qapplication, webengine_error_message


def main() -> int:
    print("python:", sys.executable)
    ok = bootstrap_webengine_before_qapplication()
    if ok:
        print("webengine bootstrap: OK (before QApplication)")
    else:
        print("webengine bootstrap: FAIL")
        print(webengine_error_message())
        return 1

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    app = QApplication([])
    view = QWebEngineView()
    print("QWebEngineView instance: OK", view)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
