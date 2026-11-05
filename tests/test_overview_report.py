from app.modules.os_upgrade.device_overview import DeviceOverviewReport, _field
from app.modules.os_upgrade.overview_parsers import SelfIpRow, VlanRow
from app.modules.os_upgrade.overview_report import render_overview_html


def test_render_overview_html_contains_table() -> None:
    report = DeviceOverviewReport(device_label="lab-01", platform_kind="iSeries/VE")
    report.fields = [
        _field("Platform", "BIG-IP i10800"),
        _field("Hostname", "autoever-vpn-1.com"),
        _field("현 운영 F5OS Version", ""),
        _field("TMOS MGMT-IP", "10.255.122.40", "서브넷 : 255.255.255.0"),
    ]
    report.vlan_rows = [
        VlanRow(
            vlan="ju_external_vlan",
            interface="1.2",
            tagging="Tag 4094",
            media="10000T-FD",
        )
    ]
    report.self_ip_rows = [
        SelfIpRow(
            item="ju_external_self",
            value="10.1.10.240/24",
            remark="vlan ju_external_vlan",
        ),
    ]
    html = render_overview_html([report], title="장비 개요")
    assert "장비 개요" in html
    assert "lab-01" in html
    assert "BIG-IP i10800" in html
    assert "VLAN 정보 (VLAN Info)" in html
    assert "ju_external_vlan" in html
    assert "ju_external_self" in html
    assert "10.1.10.240/24" in html
    assert "table.grid" in html
    assert html.count("<table class=\"main\">") == 1
    assert "<h3>" not in html
