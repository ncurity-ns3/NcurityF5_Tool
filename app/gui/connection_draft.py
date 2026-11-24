"""In-memory copy of the device form filled by the last successful connection."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class ConnectionForm:
    platform: str = ""
    label: str = ""
    host: str = ""
    port: int = 443
    f5os_host: str = ""
    f5os_port: int = 443
    username: str = ""
    password: str = ""
    f5os_username: str = ""
    f5os_password: str = ""
    source: int = 0
    active: bool = False


class ConnectionDraft(QObject):
    changed = pyqtSignal()
    _instance: ConnectionDraft | None = None

    def __init__(self) -> None:
        super().__init__()
        self.form = ConnectionForm()

    @classmethod
    def instance(cls) -> ConnectionDraft:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def publish(self, form: ConnectionForm) -> None:
        form.active = bool(form.host.strip())
        self.form = form
        if form.active:
            self.changed.emit()

    def clear(self) -> None:
        self.form = ConnectionForm()
