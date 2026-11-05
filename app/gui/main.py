"""gui entry: python -m app.gui.main"""

from __future__ import annotations

import sys


def main() -> int:
    import os

    # Qt monitor EDID noise (e.g. Unknown Vendor ID: 0x4d4f4351) — harmless
    os.environ.setdefault("QT_LOGGING_RULES", "qt.gui.edid=false;*.warning=false")
    os.environ.setdefault("QT_LOGGING_TO_CONSOLE", "0")
    # Before QApplication: installer only ships qmodernwindowsstyle.dll, which
    # hides QTableWidgetItem selection fills. Fusion paints them; we also paint
    # rows in a custom delegate as a fallback.
    os.environ["QT_STYLE_OVERRIDE"] = "Fusion"

    from app.runtime.paths import is_frozen

    if not is_frozen():
        print("Ncurity F5 tool - gui starting (close the window to return to cmd)", flush=True)

    from app.gui.qt_utils import (
        bootstrap_webengine_before_qapplication,
        webengine_available,
        webengine_error_message,
    )

    # webengine must be initialized before QApplication instance
    bootstrap_webengine_before_qapplication()

    from app.gui.branding import apply_app_branding, apply_platform_dock_icon, platform_setup_before_qt
    from app.gui.theme import apply_ncurity_theme

    platform_setup_before_qt()

    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    apply_ncurity_theme(app)
    apply_app_branding(app)

    from app.runtime.paths import gui_project_root

    project_root = gui_project_root()

    from app.gui.main_window import MainWindow

    window = MainWindow(project_root)
    window.show()
    apply_platform_dock_icon()
    if not is_frozen():
        print("window shown — check taskbar if not visible", flush=True)

    if not webengine_available():
        detail = webengine_error_message()
        extra = f"\n\n상세: {detail}" if detail else ""
        QMessageBox.information(
            window,
            "Report Preview",
            "html 인앱 미리보기용 PyQt6-WebEngine을 불러오지 못했습니다.\n"
            "리포트는 텍스트로 표시됩니다.\n"
            "  scripts\\check_webengine.cmd\n"
            "고객 PC 배포 exe에는 WebEngine 포함 예정 (Python 설치 불필요)."
            + extra,
        )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
