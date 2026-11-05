from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.models import ConnectionProfile, DeviceTarget
from app.modules.os_upgrade.pre_work import (
    PreWorkReport,
    collect_pre_work,
    run_pre_work_ucs_backups,
)


class PreWorkWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        targets: list[DeviceTarget],
        connections: list[ConnectionProfile],
        workspace: Path,
        *,
        run_ucs_backup: bool = True,
    ) -> None:
        super().__init__()
        self.targets = targets
        self.connections = connections
        self.workspace = workspace
        self.run_ucs_backup = run_ucs_backup

    def run(self) -> None:
        try:
            conn_by_label = {c.target.label: c for c in self.connections}
            use_index = len(self.connections) == len(self.targets)
            reports = []
            total = max(len(self.targets), 1)
            active_connections: list[ConnectionProfile] = []

            for idx, target in enumerate(self.targets, start=1):
                base_pct = int((idx - 1) / total * 70)
                label = target.label

                def on_step(
                    step_name: str,
                    *,
                    device_label: str = label,
                    device_idx: int = idx,
                    pct_base: int = base_pct,
                ) -> None:
                    msg = f"[{device_idx}/{total}] {device_label} — {step_name}"
                    self.progress.emit(min(69, pct_base + 8), msg)

                self.progress.emit(base_pct, f"[{idx}/{total}] {label} — 사전 작업")

                if use_index:
                    conn = self.connections[idx - 1]
                else:
                    conn = conn_by_label.get(target.label)

                if conn is None:
                    rep = PreWorkReport(device_label=label)
                    rep.errors.append("연결 프로필 없음")
                    reports.append(rep)
                    continue

                active_connections.append(conn)
                reports.append(
                    collect_pre_work(
                        conn,
                        self.workspace,
                        on_step=on_step,
                    )
                )

            active_labels = {c.target.label for c in active_connections}
            if active_connections and self.run_ucs_backup:
                ucs_log = self.workspace / "ucs_backup.log"
                self.progress.emit(72, "UCS 백업 (stagger)…")

                def on_ucs(label: str, index: int, count: int, detail: str = "") -> None:
                    pct = 72 + int(index / max(count, 1) * 25)
                    text = f"UCS {index}/{count} — {label}"
                    if detail:
                        text += f" · {detail}"
                    self.progress.emit(min(99, pct), text)

                run_pre_work_ucs_backups(
                    active_connections,
                    ucs_log,
                    on_progress=on_ucs,
                )
                log_rel = "ucs_backup.log"
                for rep in reports:
                    if rep.device_label in active_labels:
                        rep.ucs_status = "실행 완료 (ucs_backup.log 확인)"
                        rep.ucs_log_rel = log_rel
            elif active_connections:
                for rep in reports:
                    if rep.device_label in active_labels:
                        rep.ucs_status = "생략 (UCS 백업 미선택)"

            self.progress.emit(100, f"완료 — {total}대")
            self.finished_ok.emit(reports)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
