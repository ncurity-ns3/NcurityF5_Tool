from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.adapters.tmos_collector import TmosCollector
from app.core.models import ConnectionProfile, DeviceTarget, HealthCheckProfile, PlatformKind
from pydantic import SecretStr


def test_tmos_collector_runs_collect_not_empty_stub() -> None:
    """Regression: return must be inside mock-only branch."""
    target = DeviceTarget(label="lab", platform=PlatformKind.iseries, host="10.0.0.1")
    profile_conn = ConnectionProfile(
        target=target, username="admin", password=SecretStr("x")
    )
    collector = TmosCollector(target, connection=profile_conn)
    check = HealthCheckProfile(categories=["common"])

    fake_tmos = {"uptime": {"bash_stdout": "up 1 days", "_source": "bash"}}
    with patch.object(collector, "mock_responses", None):
        with patch("app.adapters.tmos_collector.BigipClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_client.authenticate.return_value = None
            with patch(
                "app.adapters.tmos_collector.collect_tmos_common",
                return_value=fake_tmos,
            ):
                result = collector.collect(check)

    assert result.data.get("_platform") == "iseries"
    common = result.data.get("common")
    assert isinstance(common, dict)
    assert common.get("tmos") == fake_tmos
