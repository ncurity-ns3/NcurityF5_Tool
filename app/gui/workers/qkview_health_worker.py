from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.health_check.qkview_inspect import (
    QkviewInspectError,
    QkviewReport,
    StatusRow,
    inspect_qkview,
    write_qkview_reports,
)


class QkviewHealthWorker(QThread):
    progressed = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str, str, str)
    failed = pyqtSignal(str)

    def __init__(self, sources: list[Path], output_root: Path) -> None:
        super().__init__()
        self.sources = list(sources)
        self.output_root = output_root

    def run(self) -> None:
        try:
            if not self.sources:
                raise QkviewInspectError("QKView 파일을 선택하세요.")
            total = len(self.sources)
            reports: list[QkviewReport] = []
            for index, path in enumerate(self.sources, start=1):
                percent = int((index - 1) * 90 / total)
                self.progressed.emit(percent, f"{index}/{total} {path.name} 분석 중…")
                reports.append(_read_one(path))
                self.progressed.emit(int(index * 90 / total), f"{index}/{total} 분석")
            self.progressed.emit(95, "보고서 작성 중…")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = re.sub(r"[^\w.-]+", "_", self.sources[0].stem)[:40] or "qkview"
            if len(self.sources) > 1:
                stem = f"{stem}_{len(self.sources)}"
            job_dir = self.output_root / f"{stamp}_{stem}"
            html_path = job_dir / "report.html"
            write_qkview_reports(reports, html_path)
            bad = sum(1 for report in reports for row in report.rows if row.result == "X")
            if len(reports) == 1:
                report = reports[0]
                summary = f"{report.hostname} · {report.kind} · 확인 필요 {bad}건"
            else:
                summary = f"{len(reports)}대 · 확인 필요 {bad}건"
            self.finished_ok.emit(str(html_path), str(job_dir), summary)
        except Exception as exc:  # noqa: BLE001 — surface to gui
            self.failed.emit(str(exc))


def _read_one(path: Path) -> QkviewReport:
    try:
        return inspect_qkview(path)
    except Exception as exc:  # noqa: BLE001 — keep the other files
        return QkviewReport(
            path.name,
            path.stem,
            "QKView",
            (StatusRow("qkview", "X", str(exc)),),
            (),
        )
