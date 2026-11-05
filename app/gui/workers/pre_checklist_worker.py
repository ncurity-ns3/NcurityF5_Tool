from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.models import ConnectionProfile, DeviceTarget
from app.modules.os_upgrade.k7727_versions import find_version_entry, load_k7727_versions
from app.modules.os_upgrade.network_check import is_internet_available
from app.modules.os_upgrade.pre_checklist import PreChecklistReport, collect_pre_checklist

ChecklistPhase = Literal["pre", "post"]


class PreChecklistWorker(QThread):
    """작업 전/후 Check List — 동일 수집 로직."""

    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        targets: list[DeviceTarget],
        connections: list[ConnectionProfile],
        target_version_key: str,
        *,
        phase: ChecklistPhase = "pre",
    ) -> None:
        super().__init__()
        self.targets = targets
        self.connections = connections
        self.target_version_key = target_version_key
        self.phase = phase
        self._phase_label = "작업 후" if phase == "post" else "작업 전"

    def run(self) -> None:
        try:
            target_ver = find_version_entry(
                self.target_version_key, load_k7727_versions()
            )
            if target_ver is None:
                self.failed.emit(f"알 수 없는 버전: {self.target_version_key}")
                return

            self.progress.emit(0, f"{self._phase_label} — 인터넷 연결 확인 (K7727)…")
            online = is_internet_available()
            net_hint = "온라인" if online else "오프라인 — License Check 자동 판정 생략"

            conn_by_label = {c.target.label: c for c in self.connections}
            use_index = len(self.connections) == len(self.targets)
            reports: list[PreChecklistReport] = []
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
                    self.progress.emit(min(99, pct_base + 6), msg)

                self.progress.emit(base_pct, f"[{idx}/{total}] {label} — 수집 시작")

                if use_index:
                    conn = self.connections[idx - 1]
                else:
                    conn = conn_by_label.get(target.label)

                if conn is None:
                    rep = PreChecklistReport(label, target_ver.version)
                    rep.errors.append("연결 프로필 없음")
                    reports.append(rep)
                    continue

                reports.append(
                    collect_pre_checklist(
                        conn,
                        target_ver,
                        internet_available=online,
                        include_license_check=(self.phase == "pre"),
                        on_step=on_step,
                    )
                )

            self.progress.emit(
                99,
                f"완료 — {total}대 ({net_hint})",
            )

            self.progress.emit(100, f"완료 — {total}대")
            self.finished_ok.emit(reports)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
