from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.ssl_cert.inspect import SslSourceError, inspect_archive


class SslCertWorker(QThread):
    progressed = pyqtSignal(int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            self.finished_ok.emit(inspect_archive(self.path, on_percent=self.progressed.emit))
        except SslSourceError as exc:
            self.failed.emit(str(exc))
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc)[:300])
