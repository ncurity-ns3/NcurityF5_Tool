from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SessionEntry:
    host: str
    port: int
    username: str
    token: str
    verified_at: datetime


class SessionManager:
    """in-memory icontrol session per host:port (no disk)."""

    _instance: SessionManager | None = None

    def __init__(self) -> None:
        self._sessions: dict[str, SessionEntry] = {}

    @classmethod
    def instance(cls) -> SessionManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _key(host: str, port: int, *, scope: str = "tmos") -> str:
        return f"{scope}:{host}:{port}"

    def get(self, host: str, port: int, *, scope: str = "tmos") -> SessionEntry | None:
        return self._sessions.get(self._key(host, port, scope=scope))

    def set(
        self,
        host: str,
        port: int,
        username: str,
        token: str,
        *,
        scope: str = "tmos",
    ) -> SessionEntry:
        entry = SessionEntry(
            host=host,
            port=port,
            username=username,
            token=token,
            verified_at=datetime.now(timezone.utc),
        )
        self._sessions[self._key(host, port, scope=scope)] = entry
        return entry

    def clear(self, host: str, port: int, *, scope: str = "tmos") -> None:
        self._sessions.pop(self._key(host, port, scope=scope), None)

    def clear_all(self) -> None:
        self._sessions.clear()

    def status_text(self, host: str, port: int, *, scope: str = "tmos") -> str:
        entry = self.get(host, port, scope=scope)
        if entry is None:
            return ""
        label = "F5OS" if scope == "f5os" else "TMOS"
        return (
            f"{label} {host}:{port} — {entry.username} "
            "(세션 유지, 앱 종료 시 삭제)"
        )
