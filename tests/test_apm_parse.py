from __future__ import annotations

from app.modules.health_check.apm_parse import (
    apm_license_not_available,
    parse_apm_access_info_total,
    parse_apm_license_available_ccu,
    parse_apm_license_connectivity,
)
from app.modules.health_check.module_report import build_module_summary_for_device


def test_parse_apm_access_info_total() -> None:
    text = "Total Sessions  12\nTotal Users  5"
    assert parse_apm_access_info_total(text) == 12


def test_parse_apm_license_ccu_legacy() -> None:
    text = """
Licensed CCU  500
CCU in use  42
Available CCU  458
"""
    avail, lic, used = parse_apm_license_available_ccu(text)
    assert avail == 458
    assert lic == 500
    assert used == 42


def test_parse_apm_license_connectivity_global_access() -> None:
    text = """
 total connectivity sessions: 3.0K
 current connectivity sessions: 0
"""
    display, total, current = parse_apm_license_connectivity(text)
    assert display == "3.0K"
    assert total == 3000
    assert current == 0
    avail, lic, used = parse_apm_license_available_ccu(text)
    assert avail == 3000
    assert lic == 3000
    assert used == 0


def test_apm_license_syntax_error_is_not_available() -> None:
    assert apm_license_not_available('Syntax Error: "apm" unexpected argument')


def test_module_report_apm_session_and_license() -> None:
    data = {
        "apm": {
            "sessions": {
                "_source": "bash",
                "metric": "session_total",
                "value": 7,
            },
            "license": {
                "_source": "bash",
                "metric": "license_ccu",
                "connectivity_total": "3.0K",
                "available_ccu": 3000,
                "detail": "Total connectivity sessions 3.0K, Current 0",
            },
        }
    }
    summary = build_module_summary_for_device(data)
    assert summary["apm"][1]["value"] == "7"
    assert "access-info" in summary["apm"][1]["detail"]
    assert summary["apm"][2]["value"] == "3.0K CCU"
    assert "connectivity" in summary["apm"][2]["detail"].lower()
