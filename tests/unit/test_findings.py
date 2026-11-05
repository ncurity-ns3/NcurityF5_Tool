from __future__ import annotations

import json
from pathlib import Path

from app.modules.health_check.findings import summarize_job_dir


def test_summarize_job_dir_healthy(tmp_path: Path) -> None:
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "exceptions.json").write_text("[]", encoding="utf-8")
    (job_dir / "raw_collection.json").write_text(
        json.dumps(
            [
                {
                    "device_label": "d1",
                    "host": "1.2.3.4",
                    "data": {"ltm": {"pools": {"items": []}}},
                    "errors": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    healthy, count, findings = summarize_job_dir(job_dir)
    assert healthy is True
    assert count == 0
    assert findings == []


def test_summarize_job_dir_counts_issues(tmp_path: Path) -> None:
    job_dir = tmp_path / "job2"
    job_dir.mkdir()
    (job_dir / "exceptions.json").write_text(
        json.dumps([{"device": "d1", "message": "collect timeout"}]),
        encoding="utf-8",
    )
    (job_dir / "raw_collection.json").write_text(
        json.dumps(
            [
                {
                    "device_label": "d1",
                    "host": "1.2.3.4",
                    "data": {
                        "ltm": {
                            "pools": {
                                "items": [
                                    {"name": "p1", "availabilityState": "offline"}
                                ]
                            }
                        }
                    },
                    "errors": ["apm: timeout"],
                }
            ]
        ),
        encoding="utf-8",
    )
    healthy, count, findings = summarize_job_dir(job_dir)
    assert healthy is False
    assert count == 3
    assert len(findings) == 3
