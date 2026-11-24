"""Collect troubleshooting files from the connected BIG-IP. The view owns the thread."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.bigip_client import BigipClient
from app.core.models import ConnectionProfile
from app.modules.troubleshooting.collect import Artifact, collect_artifacts


class TroubleshootingWorker(QThread):
    progressed = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        connections: list[ConnectionProfile],
        dest: Path,
        *,
        qkview: bool,
        logs: bool,
        cores: bool,
        ucs: bool,
    ) -> None:
        super().__init__()
        self.connections = connections
        self.dest = dest
        self.qkview = qkview
        self.logs = logs
        self.cores = cores
        self.ucs = ucs

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._result())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc)[:300])

    def _result(self) -> list[Artifact]:
        if not self.connections:
            raise RuntimeError("연결된 장비가 없습니다.")
        stamp = datetime.now().strftime("%y%m%d")
        saved: list[Artifact] = []
        total = len(self.connections)
        for index, connection in enumerate(self.connections):
            label = connection.target.label or connection.target.host
            folder = self.dest / _folder_name(label) if total > 1 else self.dest
            self.progressed.emit(int(100 * index / total), f"{label} 확인 중")

            def tick(percent: int, message: str, base: int = index) -> None:
                overall = int((base + percent / 100) / total * 100)
                self.progressed.emit(min(99, overall), message)

            client = BigipClient(connection, timeout=2400.0)
            client.authenticate()
            saved.extend(
                collect_artifacts(
                    client,
                    folder,
                    label=label,
                    stamp=stamp,
                    qkview=self.qkview,
                    logs=self.logs,
                    cores=self.cores,
                    ucs=self.ucs,
                    on_progress=tick,
                )
            )
        self.progressed.emit(100, "완료")
        return saved


def _folder_name(label: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in label).strip("._")
    return cleaned[:40] or "device"
