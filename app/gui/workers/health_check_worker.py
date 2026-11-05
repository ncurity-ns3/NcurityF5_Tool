from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.audit import AuditLogger
from app.core.job_store import JobStore
from app.core.models import ConnectionProfile, DeviceTarget, HealthCheckProfile, JobRecord
from app.modules.health_check.collector import run_health_check_job


class HealthCheckWorker(QThread):
    finished_ok = pyqtSignal(object, str)  # JobRecord, output_dir str
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        project_root: Path,
        output_root: Path,
        data_dir: Path,
        site_name: str,
        period: str,
        notes: str,
        targets: list[DeviceTarget],
        categories: list[str],
        perform_ucs_backup: bool,
        connections: list[ConnectionProfile] | None,
        mock_fixtures: dict[str, dict] | None,
        operator: str | None,
    ) -> None:
        super().__init__()
        self.project_root = project_root
        self.output_root = output_root
        self.data_dir = data_dir
        self.site_name = site_name
        self.period = period
        self.notes = notes
        self.targets = targets
        self.categories = categories
        self.perform_ucs_backup = perform_ucs_backup
        self.connections = connections
        self.mock_fixtures = mock_fixtures
        self.operator = operator

    def run(self) -> None:
        try:
            job_store = JobStore(self.data_dir / "jobs.db")
            audit = AuditLogger(self.data_dir / "audit")
            job = run_health_check_job(
                job_store=job_store,
                audit=audit,
                output_root=self.output_root,
                site_name=self.site_name,
                period=self.period,
                engineer_notes=self.notes,
                targets=self.targets,
                check_profile=HealthCheckProfile(
                    categories=self.categories,
                    perform_ucs_backup=self.perform_ucs_backup,
                ),
                connections=self.connections,
                mock_fixtures=self.mock_fixtures,
                operator=self.operator,
            )
            out = job.output_dir or str(self.output_root)
            self.finished_ok.emit(job, out)
        except Exception as exc:  # noqa: BLE001 — surface to gui
            self.failed.emit(str(exc))
