from app.modules.os_upgrade.device_group import (
    choose_device_group_names,
    device_group_names_from_config,
    device_group_names_from_rest,
)
from app.modules.os_upgrade.device_overview import DeviceOverviewReport
from app.modules.os_upgrade.overview_report import render_overview_html
from app.modules.os_upgrade.pre_checklist import PreChecklistReport
from app.modules.os_upgrade.pre_checklist_report import render_pre_checklist_html

_CONF = """
cm device-group /Common/device_trust_group {
    type sync-only
}
cm device-group /Common/sync-failover-group {
    auto-sync enabled
    type sync-failover
}
"""


def test_sync_failover_name_is_kept_and_trust_group_is_skipped() -> None:
    assert device_group_names_from_config(_CONF) == "sync-failover-group"
    assert choose_device_group_names([("device_trust_group", "sync-only")]) == "없음"
    assert (
        choose_device_group_names([("site-dg", "sync-only"), ("other", "sync-only")])
        == "site-dg, other"
    )


def test_rest_items_use_the_failover_name() -> None:
    body = {
        "items": [
            {"name": "device_trust_group", "type": "sync-only"},
            {"name": "failover-group", "type": "sync-failover"},
        ]
    }
    assert device_group_names_from_rest(body) == "failover-group"


def test_reports_place_device_group_under_route() -> None:
    overview = DeviceOverviewReport("lab", "iSeries/VE")
    overview.device_group_name = "failover-group"
    overview_html = render_overview_html([overview], title="장비 개요")
    route_at = overview_html.index(">Route<")
    group_at = overview_html.index(">Device Group<")
    assert route_at < group_at
    assert "failover-group" in overview_html

    checklist = PreChecklistReport("lab", "17.1.1")
    checklist.device_group_name = "failover-group"
    checklist_html = render_pre_checklist_html([checklist], title="작업 전 Check List")
    gateway_at = checklist_html.index("Gateway 통신")
    group_at = checklist_html.index("Device Group")
    ha_at = checklist_html.index("이중화 / Failover")
    assert gateway_at < group_at < ha_at
    assert "failover-group" in checklist_html

    post_html = render_pre_checklist_html(
        [checklist],
        title="작업 후 Check List",
        include_license_check=True,
    )
    assert post_html.index("OS upgrade 가능 여부") < post_html.index("Device Group")
    assert post_html.index("Gateway 통신") < post_html.index("Device Group") < post_html.index(
        "이중화 / Failover"
    )
