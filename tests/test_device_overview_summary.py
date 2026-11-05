from app.modules.os_upgrade.device_overview import DeviceOverviewReport, _field
from app.modules.os_upgrade.overview_parsers import SelfIpRow, VlanRow


def test_summary_line_ok_fail() -> None:
    report = DeviceOverviewReport("lab", "iSeries/VE")
    report.fields = [
        _field("Platform", "BIG-IP i7600"),
        _field("Hostname", "host.example.com"),
        _field("Serial", ""),
        _field("현 운영 F5OS Version", ""),
        _field("현 운영 Tenant Version", "17.5.1.3-0.0.19"),
        _field("이중화 구성 (HA Config)", "Active"),
    ]
    report.vlan_rows = [
        VlanRow(vlan="ex", interface="1.1", tagging="Tag 100", media="10G")
    ]
    report.self_ip_rows = [SelfIpRow(item="ex_self", value="10.0.0.1/24")]
    line = report.summary_line()
    assert "Platform ✓" in line
    assert "Serial ✗" in line
    assert "VLAN 정보" in line and "✓" in line
    assert "Self IP" in line
    assert "F5OS Version N/A" in line or "현 운영 F5OS Version N/A" in line
