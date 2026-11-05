from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.audit import AuditLogger
from app.core.job_store import JobStore
from app.core.models import ConnectionProfile, DeviceTarget, JobRecord
from app.modules.os_upgrade.collector import PhaseLiteral, run_os_upgrade_snapshot


class OsUpgradeCheckWorker(QThread):
    finished_ok = pyqtSignal(object, str)  # JobRecord, job_dir str
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        output_root: Path,
        data_dir: Path,
        phase: PhaseLiteral,
        site_name: str,
        target_version: str,
        maintenance_window: str,
        engineer_notes: str,
        targets: list[DeviceTarget],
        connections: list[ConnectionProfile] | None,
        job_id: str | None = None,
        operator: str | None = None,
        mock_fixtures: dict[str, dict] | None = None,
    ) -> None:
        super().__init__()
        self.output_root = output_root
        self.data_dir = data_dir
        self.phase = phase
        self.site_name = site_name
        self.target_version = target_version
        self.maintenance_window = maintenance_window
        self.engineer_notes = engineer_notes
        self.targets = targets
        self.connections = connections
        self.job_id = job_id
        self.operator = operator
        self.mock_fixtures = mock_fixtures

    def run(self) -> None:
        try:
            job_store = JobStore(self.data_dir / "jobs.db")
            audit = AuditLogger(self.data_dir / "audit")
            job = run_os_upgrade_snapshot(
                job_store=job_store,
                audit=audit,
                output_root=self.output_root,
                phase=self.phase,
                site_name=self.site_name,
                target_version=self.target_version,
                maintenance_window=self.maintenance_window,
                engineer_notes=self.engineer_notes,
                targets=self.targets,
                connections=self.connections,
                mock_fixtures=self.mock_fixtures,
                operator=self.operator,
                job_id=self.job_id,
            )
            job_dir = self.output_root / job.job_id
            self.finished_ok.emit(job, str(job_dir))
        except Exception as exc:  # noqa: BLE001 — surface to gui
            self.failed.emit(str(exc))
