"""Resolve dev vs PyInstaller bundle paths (read-only assets vs writable output)."""

from __future__ import annotations

import sys
from pathlib import Path

from app.gui.app_paths import local_data_dir


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path | None:
    """PyInstaller extract dir (_internal); None when running from source."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return None


def dev_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def gui_project_root() -> Path:
    """
    Root passed to MainWindow and module output folders.

    Dev: repository root (output/ under repo).
    Frozen: %LOCALAPPDATA%\\f5tool (writable; avoids Program Files restrictions).
    """
    if is_frozen():
        root = local_data_dir()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return dev_project_root()


def install_dir() -> Path | None:
    """Directory containing NcurityF5Tool.exe when frozen."""
    if not is_frozen():
        return None
    return Path(sys.executable).resolve().parent


def template_path() -> Path:
    """Word template for the delivery confirmation document."""
    name = Path("templates") / "delivery_confirmation_template.docx"
    if is_frozen():
        bundled = bundle_root()
        if bundled is not None:
            candidate = bundled / name
            if candidate.is_file():
                return candidate
        installed = install_dir()
        if installed is not None:
            candidate = installed / name
            if candidate.is_file():
                return candidate
    return dev_project_root() / name


def output_dir() -> Path:
    """Writable folder for generated delivery confirmation documents."""
    path = gui_project_root() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path
