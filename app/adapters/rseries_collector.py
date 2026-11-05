from __future__ import annotations

from typing import Any

from app.adapters.tmos_collector import TmosCollector
from app.core.f5os_client import F5osClient
from app.core.models import ConnectionProfile, DeviceTarget, HealthCheckProfile, PlatformKind
from app.modules.health_check.f5os_common import collect_f5os_platform


class RseriesCollector(TmosCollector):
    """rseries: f5os platform collect + optional tmos tenant collect via parent."""

    def __init__(
        self,
        target: DeviceTarget,
        *,
        connection: ConnectionProfile | None = None,
        f5os_connection: ConnectionProfile | None = None,
        mock_responses: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(target, connection=connection, mock_responses=mock_responses)
        self.f5os_connection = f5os_connection

    def collect(self, profile: HealthCheckProfile):
        label = self.target.label
        host = self.target.host or self.target.f5os_host
        sections: dict[str, Any] = {}
        errors: list[str] = []

        if self.mock_responses is not None:
            for key in ("f5os", "common", "ltm", "apm", "awaf", "failover"):
                if key in self.mock_responses:
                    sections[key] = self.mock_responses[key]
            sections["_platform"] = "rseries"
            return self._merge_sections(label, host, sections, errors)

        f5os_host = self.target.f5os_host.strip()
        if f5os_host and self.f5os_connection is not None:
            user = self.f5os_connection.f5os_username or self.f5os_connection.username
            pw = self.f5os_connection.f5os_password or self.f5os_connection.password
            client = F5osClient(
                f5os_host,
                self.target.f5os_port,
                user,
                pw.get_secret_value(),
                verify_tls=self.target.verify_tls,
            )
            try:
                overview = client.get_system_overview()
                health = client.get_health()
                sections["f5os"] = {
                    "overview": overview,
                    "health": health,
                }
                if "common" in profile.categories:
                    common = sections.setdefault("common", {})
                    if not isinstance(common, dict):
                        common = {}
                        sections["common"] = common
                    common["f5os"] = collect_f5os_platform(
                        client,
                        overview,
                        health,
                        platform_host=f5os_host,
                        admin_user=user,
                        admin_password=pw.get_secret_value(),
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"f5os: {exc}")
        elif f5os_host:
            errors.append("f5os: no credentials")

        if self.target.host.strip() and self.connection is not None:
            tmos_result = super().collect(profile)
            for key, value in tmos_result.data.items():
                if key == "f5os":
                    continue
                if key == "common" and isinstance(value, dict):
                    common = sections.setdefault("common", {})
                    if not isinstance(common, dict):
                        common = {}
                        sections["common"] = common
                    tmos_block = value.get("tmos")
                    if isinstance(tmos_block, dict):
                        common["tmos"] = tmos_block
                    continue
                sections[key] = value
            errors.extend(tmos_result.errors)
        elif not f5os_host:
            errors.append("rseries: f5os mgmt ip or tmos mgmt ip required")

        sections["_platform"] = "rseries"
        return self._merge_sections(label, host, sections, errors)
