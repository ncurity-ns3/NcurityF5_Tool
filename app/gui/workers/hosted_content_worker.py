from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.hosted_content.extract import (
    HostedContentError,
    HostedFile,
    extract_hosted_files,
    list_hosted_content,
)


class HostedListWorker(QThread):
    progressed = pyqtSignal(int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            self.finished_ok.emit(list_hosted_content(self.path, on_percent=self.progressed.emit))
        except HostedContentError as exc:
            self.failed.emit(str(exc))
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc)[:300])


class HostedExtractWorker(QThread):
    progressed = pyqtSignal(int)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, ucs: Path, files: list[HostedFile], dest: Path) -> None:
        super().__init__()
        self.ucs = ucs
        self.files = files
        self.dest = dest

    def run(self) -> None:
        try:
            written, missing = extract_hosted_files(
                self.ucs,
                self.files,
                self.dest,
                on_percent=self.progressed.emit,
            )
            self.finished_ok.emit((written, missing, str(self.dest)))
        except HostedContentError as exc:
            self.failed.emit(str(exc))
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc)[:300])
