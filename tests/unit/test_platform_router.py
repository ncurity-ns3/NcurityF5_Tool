from __future__ import annotations

import json
from pathlib import Path

from app.core.models import DeviceTarget, HealthCheckProfile, PlatformKind
from app.modules.health_check.collector import run_health_check_job
from app.core.job_store import JobStore
from app.core.audit import AuditLogger


def test_rseries_fixture_job(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "tmos_lab.json").read_text(
            encoding="utf-8"
        )
    )
    fixture["f5os"] = {"overview": {"product": "rseries"}, "health": {"status": "ok"}}
    target = DeviceTarget(
        label="r1",
        platform=PlatformKind.rseries,
        host="203.0.113.20",
        f5os_host="203.0.113.21",
    )
    job = run_health_check_job(
        job_store=JobStore(tmp_path / "jobs.db"),
        audit=AuditLogger(tmp_path / "audit"),
        output_root=tmp_path / "out",
        site_name="lab",
        period="",
        engineer_notes="",
        targets=[target],
        check_profile=HealthCheckProfile(categories=["ltm"]),
        mock_fixtures={"r1": fixture},
    )
    assert job.status.value in ("completed", "failed")
    raw = json.loads((tmp_path / "out" / job.job_id / "raw_collection.json").read_text())
    assert raw[0]["data"].get("f5os") is not None
