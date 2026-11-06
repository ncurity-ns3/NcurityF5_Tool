from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.waf_poc.catalog import PocCase
from app.modules.waf_poc.curlutil import Target
from app.modules.waf_poc.runner import CurlRunner, SendSummary, run_cases


class WafPocWorker(QThread):
    log_line = pyqtSignal(str)
    run_done = pyqtSignal(object)
    run_failed = pyqtSignal(str)

    def __init__(self, cases: list[PocCase], target: Target) -> None:
        super().__init__()
        self.cases = cases
        self.target = target
        self.runner = CurlRunner()

    def stop_now(self) -> None:
        self.requestInterruption()
        self.runner.stop()

    def run(self) -> None:
        try:
            summary = run_cases(
                self.cases,
                self.target,
                on_text=self.log_line.emit,
                runner=self.runner,
            )
        except (OSError, ValueError) as exc:
            self.run_failed.emit(str(exc))
            return
        if self.isInterruptionRequested() and not summary.stopped:
            summary = SendSummary(sent=summary.sent, failed=summary.failed, stopped=True)
        self.run_done.emit(summary)
