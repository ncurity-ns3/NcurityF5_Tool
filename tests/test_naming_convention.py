"""pytest wrapper for tools/check_naming.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "tools" / "check_naming.py"


def test_project_paths_use_lowercase_naming() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), str(ROOT)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"naming check failed:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.parametrize(
    "segment,valid",
    [
        ("spec.md", True),
        ("health_check", True),
        ("SPEC.md", False),
        ("requirements-dev.txt", False),
    ],
)
def test_segment_rules(segment: str, valid: bool) -> None:
    from tools.check_naming import is_valid_segment

    assert is_valid_segment(segment) is valid
