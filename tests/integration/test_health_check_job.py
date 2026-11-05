import json
from pathlib import Path

from app.core.audit import AuditLogger
from app.core.job_store import JobStore
from app.core.models import DeviceTarget, HealthCheckProfile, JobStatus
from app.modules.health_check.collector import run_health_check_job


def test_health_check_with_fixture(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "tmos_lab.json").read_text(
            encoding="utf-8"
        )
    )
    job = run_health_check_job(
        job_store=JobStore(tmp_path / "jobs.db"),
        audit=AuditLogger(tmp_path / "audit"),
        output_root=tmp_path / "out",
        site_name="lab",
        period="2026-05",
        engineer_notes="test",
        targets=[DeviceTarget(label="lab-device-01", host="203.0.113.10")],
        check_profile=HealthCheckProfile(categories=["common", "ltm"]),
        mock_fixtures={"lab-device-01": fixture},
    )
    assert job.status == JobStatus.completed
    assert job.output_dir
    assert (Path(job.output_dir) / "report.html").exists()
    assert "lab" in Path(job.output_dir).name
