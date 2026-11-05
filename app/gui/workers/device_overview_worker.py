from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.models import ConnectionProfile, DeviceTarget
from app.modules.os_upgrade.device_overview import DeviceOverviewReport, collect_device_overview


class DeviceOverviewWorker(QThread):
    """percent 0–100, message 예: [1/3] lab — Platform"""

    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        targets: list[DeviceTarget],
        connections: list[ConnectionProfile],
    ) -> None:
        super().__init__()
        self.targets = targets
        self.connections = connections

    def run(self) -> None:
        try:
            conn_by_label = {c.target.label: c for c in self.connections}
            use_index = len(self.connections) == len(self.targets)
            reports: list[DeviceOverviewReport] = []
            total = max(len(self.targets), 1)

            for idx, target in enumerate(self.targets, start=1):
                base_pct = int((idx - 1) / total * 100)
                label = target.label

                def on_step(
                    step_name: str,
                    *,
                    device_label: str = label,
                    device_idx: int = idx,
                    device_total: int = total,
                    pct_base: int = base_pct,
                ) -> None:
                    msg = f"[{device_idx}/{device_total}] {device_label} — {step_name}"
                    pct = min(99, pct_base + 8)
                    self.progress.emit(pct, msg)

                self.progress.emit(
                    base_pct,
                    f"[{idx}/{total}] {label} — 수집 시작",
                )

                if use_index:
                    conn = self.connections[idx - 1]
                else:
                    conn = conn_by_label.get(target.label)

                if conn is None:
                    rep = DeviceOverviewReport(
                        device_label=label,
                        platform_kind="?",
                    )
                    rep.errors.append("연결 프로필 없음")
                    reports.append(rep)
                    continue

                reports.append(collect_device_overview(conn, on_step=on_step))

            self.progress.emit(100, f"완료 — {total}대")
            self.finished_ok.emit(reports)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
