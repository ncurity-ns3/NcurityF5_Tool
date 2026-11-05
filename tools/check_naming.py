#!/usr/bin/env python3
"""validate project file and folder names (lowercase, underscore, no spaces)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SEGMENT_RE = re.compile(r"^[a-z0-9_.]+$")

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".cursor",
        "mcps",
        "agent-transcripts",
        "terminals",
    }
)

_PROJECT_SUBDIRS = ("app", "docs", "tests", "tools", "templates", "scripts")


def is_valid_segment(name: str) -> bool:
    if not name:
        return False
    if " " in name:
        return False
    if any(c.isupper() for c in name):
        return False
    if "-" in name:
        return False
    return bool(_SEGMENT_RE.match(name))


def collect_violations(root: Path, *, subdirs: tuple[str, ...] | None = None) -> list[str]:
    violations: list[str] = []
    root = root.resolve()
    scan_roots: list[Path] = []
    chosen = subdirs or _PROJECT_SUBDIRS

    for name in chosen:
        candidate = root / name
        if candidate.is_dir():
            scan_roots.append(candidate)

    root_files = [p for p in root.iterdir() if p.is_file()]
    scan_items: list[Path] = scan_roots + root_files

    if not scan_items:
        scan_items = [root]

    for scan_root in scan_items:
        paths = [scan_root] if scan_root.is_file() else sorted(scan_root.rglob("*"))
        for path in paths:
            rel = path.relative_to(root)
            parts = rel.parts
            if not parts:
                continue
            if any(p in _SKIP_DIRS for p in parts):
                continue
            if parts[0].startswith(".") and parts[0] not in {".github"}:
                continue
            for segment in parts:
                if segment in _SKIP_DIRS:
                    break
                if not is_valid_segment(segment):
                    violations.append(f"{rel}: invalid segment '{segment}'")
                    break

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="check lowercase naming convention")
    parser.add_argument("root", nargs="?", default=".", help="project root")
    args = parser.parse_args(argv)
    root = Path(args.root)

    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    violations = collect_violations(root)
    if violations:
        print(f"naming convention failed ({len(violations)} issue(s)):")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(f"naming convention ok: {root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
