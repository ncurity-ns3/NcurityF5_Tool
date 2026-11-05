from __future__ import annotations

from app.core.f5os_client import format_f5os_summary


def test_format_f5os_summary_components() -> None:
    data = {
        "openconfig-platform:components": {
            "component": [{"name": "lcd"}, {"name": "chassis"}],
        }
    }
    assert format_f5os_summary(data) == "platform OK — lcd, chassis"


def test_format_f5os_summary_no_raw_dict() -> None:
    data = {"openconfig-platform:components": {"component": []}}
    assert "{" not in format_f5os_summary(data)
