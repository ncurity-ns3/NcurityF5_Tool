from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.health_check.ucs_backup import run_ucs_backup_batch


class UcsBackupWorker(QThread):
    """Runs UCS saves on a Qt thread so work is not cut off by daemon threading."""

    progress = pyqtSignal(str)
    finished_all = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, jobs: list[dict[str, Any]], ucs_log_path: str) -> None:
        super().__init__()
        self.jobs = jobs
        self.ucs_log_path = ucs_log_path

    def run(self) -> None:
        try:
            total = len(self.jobs)

            def on_progress(label: str, index: int, count: int, detail: str = "") -> None:
                text = f"UCS 백업 {index}/{count} — {label}"
                if detail:
                    text += f" · {detail}"
                self.progress.emit(text)

            run_ucs_backup_batch(
                self.jobs,
                self.ucs_log_path,
                on_progress=on_progress,
            )
            self.finished_all.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
