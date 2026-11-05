from datetime import date

from app.modules.os_upgrade.k7727_versions import BigIpTargetVersion
from app.modules.os_upgrade.pre_checklist_parsers import (
    evaluate_license_upgrade,
    filter_custom_crontab_lines,
    parse_arp_table,
    parse_ha_failover_check,
    parse_linux_checks,
    parse_ping_result,
    parse_service_check_date,
    parse_vlan_mac_table,
    unique_gateway_ips,
)


def test_parse_service_check_date() -> None:
    text = "Service Check Date                     2026/03/05"
    assert parse_service_check_date(text) == "2026/03/05"


def test_license_upgrade_ok_when_service_newer() -> None:
    target = BigIpTargetVersion("17.5.x", date(2025, 2, 12))
    lic = "Service Check Date 2026/10/10"
    r = evaluate_license_upgrade(lic, target)
    assert r.verdict == "OS Upgrade 가능"


def test_license_upgrade_offline() -> None:
    target = BigIpTargetVersion("21.1.x", date(2026, 4, 15))
    lic = "Service Check Date 2026/10/10"
    r = evaluate_license_upgrade(lic, target, internet_available=False)
    assert r.verdict == "인터넷 사용 불가"
    assert "인터넷" in r.detail


def test_license_upgrade_needs_active_when_service_older() -> None:
    target = BigIpTargetVersion("21.1.x", date(2026, 4, 15))
    lic = "Service Check Date 2025/12/12"
    r = evaluate_license_upgrade(lic, target)
    assert r.verdict == "License Active 필요"


def test_parse_vlan_mac() -> None:
    text = """
-------------------------------------
Net::Vlan: Vlan-Onearm
-------------------------------------
Mac Address (True)  00:0c:29:16:1c:0a
"""
    rows = parse_vlan_mac_table(text)
    assert len(rows) == 1
    assert rows[0].vlan == "Vlan-Onearm"
    assert rows[0].mac == "00:0c:29:16:1c:0a"


def test_parse_arp_table() -> None:
    text = """
Name           Address        HWaddress          Vlan                      Expire-in-sec  Status
10.1.10.199    10.1.10.199    00:0c:29:47:40:e8  /Common/ju_external_vlan  259            resolved
"""
    rows = parse_arp_table(text)
    assert len(rows) == 1
    assert rows[0].address == "10.1.10.199"


def test_unique_gateway_ips() -> None:
    route = """
net route default { gw 10.1.10.1 }
net route int { gw 10.1.20.1 }
net route dup { gw 10.1.10.1 }
"""
    assert unique_gateway_ips(route) == ["10.1.10.1", "10.1.20.1"]


def test_parse_ping_ok() -> None:
    out = "64 bytes from 10.1.10.1: icmp_seq=1 ttl=255 time=1.2 ms\n2 packets transmitted, 2 received, 0% packet loss"
    row = parse_ping_result("10.1.10.1", out)
    assert row.result == "OK"
    assert row.detail == "2회 시도 · 2회 성공"


def test_parse_ping_fail_zero_received() -> None:
    out = """
PING 10.10.10.254 (10.10.10.254) 56(84) bytes of data.
--- 10.10.10.254 ping statistics ---
2 packets transmitted, 0 received, 100% packet loss
"""
    row = parse_ping_result("10.10.10.254", out)
    assert row.result == "FAIL"
    assert row.detail == "2회 시도 · 0회 성공"


def test_parse_ping_fail_korean_timeout() -> None:
    out = """
Ping 10.10.10.10 32바이트 데이터 사용:
요청 시간이 만료되었습니다.

10.10.10.10에 대한 Ping 통계:
    패킷: 보냄 = 1, 받음 = 0, 손실 = 1 (100% 손실),
"""
    row = parse_ping_result("10.10.10.10", out)
    assert row.result == "FAIL"
    assert "0회 성공" in row.detail


def test_parse_ping_ok_korean_replies() -> None:
    out = """
Ping 192.168.10.1 32바이트 데이터 사용:
192.168.10.1의 응답: 바이트=32 시간=3ms TTL=255
192.168.10.1의 응답: 바이트=32 시간=3ms TTL=255

192.168.10.1에 대한 Ping 통계:
    패킷: 보냄 = 2, 받음 = 2, 손실 = 0 (0% 손실),
"""
    row = parse_ping_result("192.168.10.1", out)
    assert row.result == "OK"
    assert row.detail == "2회 시도 · 2회 성공"


def test_parse_ping_summary_from_reply_lines() -> None:
    out = """
PING 192.168.41.1 (192.168.41.1) 56(84) bytes of data.
64 bytes from 192.168.41.1: icmp_seq=1 ttl=255 time=0.811 ms
64 bytes from 192.168.41.1: icmp_seq=2 ttl=255 time=1.13 ms
--- 192.168.41.1 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss
"""
    row = parse_ping_result("192.168.41.1", out)
    assert row.result == "OK"
    assert row.detail == "2회 시도 · 2회 성공"


def test_parse_ha_standalone() -> None:
    r = parse_ha_failover_check("Status: Standalone", "", "")
    assert r.ha_mode == "Standalone"
    assert not r.is_redundant


def test_filter_f5_default_crontab() -> None:
    raw = """
MAILTO=""
1-59/10 * * * * /usr/bin/diskmonitor
0 */4 * * * /usr/bin/diskwearoutstat
05 12 * * * /usr/bin/updatecheck -a
0 2 * * * /shared/scripts/my_backup.sh
"""
    custom = filter_custom_crontab_lines(raw)
    assert len(custom) == 1
    assert "my_backup.sh" in custom[0]


def test_parse_linux_crontab_only_f5_defaults() -> None:
    raw = """
MAILTO=""
1-59/10 * * * * /usr/bin/diskmonitor
2 * * * * /usr/bin/copy_rrd save
"""
    r = parse_linux_checks("", raw, "")
    assert r.crontab_summary == "없음"
    assert not r.crontab_custom_lines


def test_parse_linux_crontab_custom() -> None:
    raw = '0 3 * * * /usr/local/bin/custom.sh\n1-59/10 * * * * /usr/bin/diskmonitor\n'
    r = parse_linux_checks("", raw, "")
    assert r.crontab_summary == "1건"
    assert len(r.crontab_custom_lines) == 1
    assert "custom.sh" in r.crontab_custom_lines[0]


def test_parse_icall_handler_script() -> None:
    from app.modules.os_upgrade.pre_checklist_parsers import parse_icall_entries

    text = """
sys icall handler periodic split_tunnel_fqdn_update_handler {
    interval 3600
}
sys icall script split_tunnel_update_script {
    definition ...
}
"""
    entries = parse_icall_entries(text)
    assert len(entries) == 2
    r = parse_linux_checks(text, "", "")
    assert r.icall_summary == "2건"
    assert not r.script_names


def test_parse_linux_scripts_listed() -> None:
    scripts = "check_ready.sh\nwork_flow.sh\n"
    r = parse_linux_checks("", "", scripts)
    assert r.scripts_summary == "2건"
    assert r.script_names == ("check_ready.sh", "work_flow.sh")
