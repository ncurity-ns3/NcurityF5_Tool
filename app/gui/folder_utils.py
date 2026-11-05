from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.core.output_naming import make_dated_folder_name, sanitize_label

__all__ = ["make_dated_folder_name", "sanitize_label", "open_in_file_manager", "module_output_root"]


def open_in_file_manager(path: Path) -> None:
    """Open folder in OS file manager (Windows Explorer, macOS Finder, etc.)."""
    target = path.resolve()
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
        return
    subprocess.run(["xdg-open", str(target)], check=False)


def module_output_root(project_root: Path, module: str) -> Path:
    """output/<module>/ — health_check, os_upgrade 등 모듈별 루트.

    Dev: <repo>/output/<module>/.
    Frozen: %LOCALAPPDATA%\\f5tool\\output/<module>/ (gui_project_root).
    """
    return project_root / "output" / module
