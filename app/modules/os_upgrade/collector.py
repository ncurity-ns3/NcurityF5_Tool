from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.adapters.platform_router import collect_device
from app.core.audit import AuditLogger
from app.core.job_store import JobStore
from app.core.models import (
    CollectionResult,
    ConnectionProfile,
    DeviceTarget,
    ExecutionMode,
    HealthCheckProfile,
    JobRecord,
    JobStatus,
)
from app.core.redaction import redact_data
from app.modules.os_upgrade.checklist import load_phase_config

PhaseLiteral = Literal["pre", "post"]
_SNAPSHOT_DIRS: dict[PhaseLiteral, str] = {"pre": "pre_snapshot", "post": "post_snapshot"}


def health_check_profile_for_phase(
    phase: PhaseLiteral,
    *,
    job_dir: Path | None = None,
) -> HealthCheckProfile:
    cfg = load_phase_config(phase)
    ucs_log = None
    if job_dir is not None and cfg.perform_ucs_backup:
        ucs_log = str(job_dir / "ucs_backup.log")
    return HealthCheckProfile(
        categories=list(cfg.categories),
        perform_ucs_backup=cfg.perform_ucs_backup,
        ucs_log_path=ucs_log,
    )


def _write_job_meta(job_dir: Path, meta: dict[str, Any]) -> None:
    path = job_dir / "job_meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_job_meta(job_dir: Path) -> dict[str, Any]:
    path = job_dir / "job_meta.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _checksum_manifest(job_dir: Path, phase_dir: Path) -> None:
    entries: list[dict[str, str]] = []
    for file_path in sorted(phase_dir.rglob("*")):
        if not file_path.is_file():
            continue
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        rel = file_path.relative_to(job_dir).as_posix()
        entries.append({"path": rel, "sha256": digest})
    manifest_path = phase_dir / "manifest.json"
    manifest_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _collect_targets(
    targets: list[DeviceTarget],
    check_profile: HealthCheckProfile,
    *,
    connections: list[ConnectionProfile] | None,
    mock_fixtures: dict[str, dict] | None,
) -> tuple[list[CollectionResult], list[dict[str, Any]]]:
    results: list[CollectionResult] = []
    exceptions: list[dict[str, Any]] = []
    conn_by_label = {c.target.label: c for c in (connections or [])}
    use_index = bool(connections) and len(connections) == len(targets)

    for idx, target in enumerate(targets):
        mock = mock_fixtures.get(target.label) if mock_fixtures else None
        if use_index:
            connection = connections[idx]
        else:
            connection = conn_by_label.get(target.label)
        if mock is None and connection is None:
            exceptions.append(
                {
                    "device": target.label,
                    "severity": "high",
                    "message": "no connection or mock fixture",
                }
            )
            continue

        result = collect_device(
            target,
            check_profile,
            connection=connection,
            mock_responses=mock,
        )
        results.append(result)
        for err in result.errors:
            exceptions.append(
                {"device": target.label, "severity": "medium", "message": err}
            )
    return results, exceptions


def run_os_upgrade_snapshot(
    *,
    job_store: JobStore,
    audit: AuditLogger,
    output_root: Path,
    phase: PhaseLiteral,
    site_name: str,
    target_version: str,
    maintenance_window: str = "",
    engineer_notes: str = "",
    targets: list[DeviceTarget],
    connections: list[ConnectionProfile] | None = None,
    mock_fixtures: dict[str, dict] | None = None,
    operator: str | None = None,
    job_id: str | None = None,
) -> JobRecord:
    """Collect one phase (pre or post) into output/<job_id>/<phase>_snapshot/."""
    phase_cfg = load_phase_config(phase)

    if job_id:
        existing = job_store.get(job_id)
        if existing is None:
            raise ValueError(f"unknown job_id: {job_id}")
        if existing.module != "os_upgrade_check":
            raise ValueError(f"job {job_id} is not os_upgrade_check")
        job = existing
        job.status = JobStatus.running
    else:
        if phase != "pre":
            raise ValueError("new jobs must start with phase=pre")
        job = JobRecord(
            module="os_upgrade_check",
            mode=ExecutionMode.collect,
            operator=operator,
            output_dir=str(output_root),
            metadata={"phases_completed": []},
        )
        job.status = JobStatus.running

    job_store.save(job)
    audit.append(
        "os_upgrade_phase_start",
        job_id=job.job_id,
        phase=phase,
        preset=phase_cfg.preset,
    )

    job_dir = output_root / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    phase_dir = job_dir / _SNAPSHOT_DIRS[phase]
    phase_dir.mkdir(parents=True, exist_ok=True)

    check_profile = health_check_profile_for_phase(phase, job_dir=job_dir)
    results, exceptions = _collect_targets(
        targets,
        check_profile,
        connections=connections,
        mock_fixtures=mock_fixtures,
    )

    raw_path = phase_dir / "raw_collection.json"
    raw_path.write_text(
        json.dumps(redact_data([r.model_dump(mode="json") for r in results]), indent=2),
        encoding="utf-8",
    )
    (phase_dir / "exceptions.json").write_text(
        json.dumps(exceptions, indent=2), encoding="utf-8"
    )
    (phase_dir / "checklist.json").write_text(
        json.dumps(
            [
                {
                    "id": item.id,
                    "name": item.name,
                    "layer": item.layer,
                    "criteria": item.criteria,
                }
                for item in phase_cfg.items
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _checksum_manifest(job_dir, phase_dir)

    meta = _read_job_meta(job_dir)
    meta.update(
        {
            "job_type": "os_upgrade_check",
            "job_id": job.job_id,
            "site_name": site_name,
            "target_version": target_version,
            "maintenance_window": maintenance_window,
            "engineer_notes": engineer_notes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "presets": meta.get("presets", {}),
        }
    )
    presets = meta["presets"]
    if isinstance(presets, dict):
        presets[phase] = phase_cfg.preset
    phases_done: list[str] = list(meta.get("phases_completed", []))
    if phase not in phases_done:
        phases_done.append(phase)
    meta["phases_completed"] = phases_done
    _write_job_meta(job_dir, meta)

    job.metadata = {
        **job.metadata,
        "site_name": site_name,
        "target_version": target_version,
        "last_phase": phase,
        "phases_completed": phases_done,
        "preset": phase_cfg.preset,
    }

    high = any(e.get("severity") == "high" for e in exceptions)
    if phase == "pre":
        job.status = JobStatus.failed if high else JobStatus.completed
    else:
        pre_done = "pre" in phases_done
        job.status = (
            JobStatus.failed
            if high or not pre_done
            else JobStatus.completed
        )

    job_store.save(job)
    audit.append(
        "os_upgrade_phase_end",
        job_id=job.job_id,
        phase=phase,
        status=job.status.value,
    )
    return job
