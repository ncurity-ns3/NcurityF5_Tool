from __future__ import annotations

from typing import Any

from app.adapters.base import MockableAdapter
from app.core.bigip_client import BigipClient
from app.core.models import ConnectionProfile, DeviceTarget, HealthCheckProfile
from app.modules.health_check.tmos_common_collect import collect_tmos_common


class TmosCollector(MockableAdapter):
    def __init__(
        self,
        target: DeviceTarget,
        *,
        connection: ConnectionProfile | None = None,
        mock_responses: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(connection)
        self.target = target
        self.mock_responses = mock_responses

    def collect(self, profile: HealthCheckProfile):
        label = self.target.label
        host = self.target.host
        sections: dict[str, Any] = {}
        errors: list[str] = []

        if self.mock_responses is not None:
            for category in profile.categories:
                if category in self.mock_responses:
                    sections[category] = self.mock_responses[category]
                else:
                    errors.append(f"missing mock for category: {category}")
            sections["_platform"] = "iseries"
            return self._merge_sections(label, host, sections, errors)

        assert self.connection is not None
        client = BigipClient(self.connection)
        client.authenticate()

        def collect_network() -> dict[str, Any]:
            return {
                "vlans": client.get_vlan_summary(),
                "self_ips": client.get_self_ip_summary(),
                "routes": client.get_route_summary(),
            }

        def collect_common() -> dict[str, Any]:
            ucs_pending = (
                profile.perform_ucs_backup and "common" in profile.categories
            )
            return {
                "tmos": collect_tmos_common(
                    client,
                    ucs_backup_pending=ucs_pending,
                    device_label=self.target.label,
                )
            }

        def collect_ltm() -> dict[str, Any]:
            from app.modules.health_check.tmos_module_collect import collect_ltm_data

            return collect_ltm_data(client)

        def collect_apm() -> dict[str, Any]:
            from app.modules.health_check.tmos_module_collect import collect_apm_data

            return collect_apm_data(client)

        def collect_awaf() -> dict[str, Any]:
            from app.modules.health_check.tmos_module_collect import collect_awaf_data

            return collect_awaf_data(client)

        collectors = {
            "common": collect_common,
            "ltm": collect_ltm,
            "apm": collect_apm,
            "awaf": collect_awaf,
            "failover": client.get_failover_state,
        }

        for category in profile.categories:
            fn = collectors.get(category)
            if fn is None:
                errors.append(f"unsupported category: {category}")
                continue
            try:
                sections[category] = fn()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{category}: {exc}")

        sections["_platform"] = "iseries"
        return self._merge_sections(label, host, sections, errors)
