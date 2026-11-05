from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.models import CollectionResult, ConnectionProfile, HealthCheckProfile


class DeviceAdapter(ABC):
    @abstractmethod
    def collect(self, profile: HealthCheckProfile) -> CollectionResult:
        raise NotImplementedError


class MockableAdapter(DeviceAdapter):
    def __init__(self, connection: ConnectionProfile | None = None) -> None:
        self.connection = connection

    @abstractmethod
    def collect(self, profile: HealthCheckProfile) -> CollectionResult:
        raise NotImplementedError

    def _merge_sections(
        self,
        label: str,
        host: str,
        sections: dict[str, Any],
        errors: list[str],
    ) -> CollectionResult:
        from datetime import datetime, timezone

        from app.core.models import CollectionResult

        return CollectionResult(
            device_label=label,
            host=host,
            collected_at=datetime.now(timezone.utc),
            data=sections,
            errors=errors,
        )
