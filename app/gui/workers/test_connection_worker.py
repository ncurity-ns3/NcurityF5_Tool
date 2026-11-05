from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.gui.connection_test import (
    ConnectionTestOutcome,
    ConnectionTestPlan,
    run_connection_tests_with_skips,
)


class TestConnectionWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished_ok = pyqtSignal(object)  # ConnectionTestOutcome

    def __init__(self, plan: ConnectionTestPlan) -> None:
        super().__init__()
        self.plan = plan

    def run(self) -> None:
        def on_progress(current: int, total: int, message: str) -> None:
            self.progress.emit(current, total, message)

        outcome = run_connection_tests_with_skips(
            self.plan,
            on_progress=on_progress,
            should_stop=self.isInterruptionRequested,
        )
        self.finished_ok.emit(outcome)
