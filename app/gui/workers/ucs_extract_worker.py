from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.os_upgrade.ucs_extract import (
    UcsBatchExtractResult,
    extract_ucs_batch,
    new_ucs_batch_workspace,
    write_ucs_batch_outputs,
)


class UcsExtractWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object, str)  # UcsBatchExtractResult, workspace str
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        ucs_paths: list[Path],
        output_root: Path,
        site_name: str = "",
        labels: list[str] | None = None,
        auto_unit_labels: bool = True,
        target_version: str = "",
    ) -> None:
        super().__init__()
        self.ucs_paths = ucs_paths
        self.output_root = output_root
        self.site_name = site_name
        self.labels = labels
        self.auto_unit_labels = auto_unit_labels
        self.target_version = target_version.strip() or None

    def run(self) -> None:
        try:
            total = len(self.ucs_paths)
            if total == 0:
                self.failed.emit("UCS 파일이 없습니다.")
                return

            self.progress.emit(0, f"UCS 분석 준비 ({total}개)…")
            batch = extract_ucs_batch(
                self.ucs_paths,
                labels=self.labels,
                auto_unit_labels=self.auto_unit_labels,
                target_version=self.target_version,
            )

            if not batch.units:
                msgs = [f"{f.get('file')}: {f.get('message')}" for f in batch.failures]
                self.failed.emit("; ".join(msgs) or "추출된 장비가 없습니다.")
                return

            self.progress.emit(90, "리포트 작성…")
            workspace = new_ucs_batch_workspace(
                self.output_root, self.site_name or f"{total}units"
            )
            write_ucs_batch_outputs(workspace, batch, site_name=self.site_name)
            self.progress.emit(100, "완료")
            self.finished_ok.emit(batch, str(workspace))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
