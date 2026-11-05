"""Create milestone ZIP under backups/ (excludes .venv, output, backups)."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUPS = ROOT / "backups"
INCLUDE_DIRS = ("app", "config", "scripts", "tests", "docs", "templates", "packaging")
INCLUDE_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "README.md",
    "readme.md",
)
EXCLUDE_DIR_NAMES = {".venv", "output", ".pytest_cache", "backups", "__pycache__", ".git"}


def _should_skip(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)


def main(stem: str = "multiple_table_ui") -> Path:
    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = BACKUPS / f"{stem}_{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDE_DIRS:
            base = ROOT / name
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.is_dir() or _should_skip(path.relative_to(ROOT)):
                    continue
                arc = path.relative_to(ROOT).as_posix()
                zf.write(path, arc)
        for name in INCLUDE_FILES:
            path = ROOT / name
            if path.is_file():
                zf.write(path, name)
    print(out)
    print(f"bytes={out.stat().st_size}")
    return out


if __name__ == "__main__":
    import sys

    stem = sys.argv[1] if len(sys.argv) > 1 else "milestone"
    main(stem)
