import json
from pathlib import Path

import pytest

from app.core.audit import AuditLogger
from app.core.job_store import JobStore
from app.core.models import DeviceTarget, JobStatus
from app.modules.os_upgrade.collector import run_os_upgrade_snapshot


def _fixture() -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parent / "fixtures" / "tmos_lab.json"
        ).read_text(encoding="utf-8")
    )


def test_pre_snapshot_creates_job_and_files(tmp_path: Path) -> None:
    job = run_os_upgrade_snapshot(
        job_store=JobStore(tmp_path / "jobs.db"),
        audit=AuditLogger(tmp_path / "audit"),
        output_root=tmp_path / "out",
        phase="pre",
        site_name="lab",
        target_version="17.1.2",
        maintenance_window="2026-05-22 22:00-06:00",
        targets=[DeviceTarget(label="lab-device-01", host="203.0.113.10")],
        mock_fixtures={"lab-device-01": _fixture()},
    )
    assert job.module == "os_upgrade_check"
    assert job.status == JobStatus.completed

    job_dir = tmp_path / "out" / job.job_id
    pre_dir = job_dir / "pre_snapshot"
    assert (pre_dir / "raw_collection.json").is_file()
    assert (pre_dir / "exceptions.json").is_file()
    assert (pre_dir / "checklist.json").is_file()
    assert (pre_dir / "manifest.json").is_file()

    meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
    assert meta["target_version"] == "17.1.2"
    assert meta["phases_completed"] == ["pre"]
    assert meta["presets"]["pre"] == "os_upgrade_pre"


def test_post_snapshot_requires_existing_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.db")
    audit = AuditLogger(tmp_path / "audit")
    out = tmp_path / "out"
    fixture = _fixture()
    target = DeviceTarget(label="lab-device-01", host="203.0.113.10")

    pre_job = run_os_upgrade_snapshot(
        job_store=store,
        audit=audit,
        output_root=out,
        phase="pre",
        site_name="lab",
        target_version="17.1.2",
        targets=[target],
        mock_fixtures={"lab-device-01": fixture},
    )

    post_job = run_os_upgrade_snapshot(
        job_store=store,
        audit=audit,
        output_root=out,
        phase="post",
        site_name="lab",
        target_version="17.1.2",
        targets=[target],
        mock_fixtures={"lab-device-01": fixture},
        job_id=pre_job.job_id,
    )
    assert post_job.job_id == pre_job.job_id
    assert post_job.status == JobStatus.completed

    job_dir = out / pre_job.job_id
    assert (job_dir / "pre_snapshot" / "raw_collection.json").is_file()
    assert (job_dir / "post_snapshot" / "raw_collection.json").is_file()
    meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
    assert meta["phases_completed"] == ["pre", "post"]


def test_post_without_job_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="phase=pre"):
        run_os_upgrade_snapshot(
            job_store=JobStore(tmp_path / "jobs.db"),
            audit=AuditLogger(tmp_path / "audit"),
            output_root=tmp_path / "out",
            phase="post",
            site_name="lab",
            target_version="17.1.2",
            targets=[DeviceTarget(label="x", host="1.2.3.4")],
            mock_fixtures={"x": _fixture()},
        )
