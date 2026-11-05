from __future__ import annotations

from typing import Any

from app.adapters.rseries_collector import RseriesCollector
from app.adapters.tmos_collector import TmosCollector
from app.core.models import ConnectionProfile, DeviceTarget, HealthCheckProfile, PlatformKind


def create_collector(
    target: DeviceTarget,
    *,
    connection: ConnectionProfile | None,
    mock_responses: dict[str, Any] | None,
) -> TmosCollector | RseriesCollector:
    if target.platform == PlatformKind.rseries:
        return RseriesCollector(
            target,
            connection=connection if target.host.strip() else None,
            f5os_connection=connection if target.f5os_host.strip() else None,
            mock_responses=mock_responses,
        )
    return TmosCollector(target, connection=connection, mock_responses=mock_responses)


def collect_device(
    target: DeviceTarget,
    check_profile: HealthCheckProfile,
    *,
    connection: ConnectionProfile | None,
    mock_responses: dict[str, Any] | None,
):
    collector = create_collector(target, connection=connection, mock_responses=mock_responses)
    return collector.collect(check_profile)
