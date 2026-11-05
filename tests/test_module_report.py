from __future__ import annotations

from app.modules.health_check.module_report import build_module_summary_for_device


def test_module_summary_ltm_counts() -> None:
    data = {
        "ltm": {
            "pools": {"items": [{"name": "p1"}]},
            "virtual_servers": {"items": []},
            "nodes": {"_unavailable": True, "_error": "404"},
        },
        "apm": {
            "sessions": {"items": [{"id": "1"}]},
        },
    }
    summary = build_module_summary_for_device(data)
    assert "ltm" in summary
    assert summary["ltm"][0]["value"] == "1"
    assert summary["ltm"][1]["value"] == "0"
    assert "404" in summary["ltm"][2]["detail"]
    assert summary["apm"][1]["value"] == "1"


def test_module_summary_http_400_message() -> None:
    data = {
        "awaf": {
            "policies": {
                "_unavailable": True,
                "_path": "/tm/asm/policies",
                "_error": "HTTP 400",
                "_http_status": 400,
            }
        }
    }
    summary = build_module_summary_for_device(data)
    assert "400" in summary["awaf"][0]["detail"]
    assert "미프로비저닝" in summary["awaf"][0]["detail"]
