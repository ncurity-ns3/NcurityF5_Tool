from __future__ import annotations

import json
from pathlib import Path

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
    ReportContext,
)
from app.core.redaction import redact_data
from app.core.output_naming import make_dated_folder_name
from app.output.html_renderer import render_html_report
from app.output.md_renderer import render_md_report
from app.output.xlsx_renderer import render_xlsx_report


def run_health_check_job(
    *,
    job_store: JobStore,
    audit: AuditLogger,
    output_root: Path,
    site_name: str,
    period: str,
    engineer_notes: str,
    targets: list[DeviceTarget],
    check_profile: HealthCheckProfile,
    connections: list[ConnectionProfile] | None = None,
    mock_fixtures: dict[str, dict] | None = None,
    operator: str | None = None,
) -> JobRecord:
    job = JobRecord(
        module="health_check",
        mode=ExecutionMode.collect,
        operator=operator,
        output_dir=str(output_root),
    )
    job.status = JobStatus.running
    job_store.save(job)
    audit.append("job_start", job_id=job.job_id, module=job.module, mode=job.mode.value)

    folder_name = make_dated_folder_name(site_name)
    job_dir = output_root / folder_name
    job_dir.mkdir(parents=True, exist_ok=True)
    job.output_dir = str(job_dir)
    check_profile = check_profile.model_copy(
        update={"ucs_log_path": str(job_dir / "ucs_backup.log")}
    )

    results: list[CollectionResult] = []
    exceptions: list[dict] = []
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

    raw_path = job_dir / "raw_collection.json"
    raw_path.write_text(
        json.dumps(redact_data([r.model_dump(mode="json") for r in results]), indent=2),
        encoding="utf-8",
    )

    context = ReportContext(
        job_id=job.job_id,
        site_name=site_name,
        period=period,
        engineer_notes=engineer_notes,
        devices=results,
        exceptions=exceptions,
    )

    render_html_report(context, job_dir / "report.html")
    render_xlsx_report(context, job_dir / "report.xlsx")
    render_md_report(context, job_dir / "report.md")
    (job_dir / "exceptions.json").write_text(json.dumps(exceptions, indent=2), encoding="utf-8")

    job.status = (
        JobStatus.completed
        if not any(e["severity"] == "high" for e in exceptions)
        else JobStatus.failed
    )
    job_store.save(job)
    audit.append("job_end", job_id=job.job_id, status=job.status.value)
    return job
