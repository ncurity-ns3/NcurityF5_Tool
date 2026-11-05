from __future__ import annotations

from app.modules.health_check.common_eval import evaluate_common
from app.modules.health_check.tmos_common_collect import _ucs_cleanup_command
from app.modules.health_check.tmos_bash_parse import (
    check_vlan_interfaces_up,
    compare_system_clock,
    format_tmos_psu_value,
    format_uptime_display,
    parse_df_paths,
    parse_inlet_temperature_c,
    parse_ntpq_np,
    format_ssl_cert_detail,
    parse_ha_status,
    parse_ssl_cert_check_stdout,
    parse_ssl_cert_expired_list,
    parse_ssl_cert_will_expire_list,
    parse_sys_performance,
    parse_sys_service,
    parse_tmos_psu_status,
    parse_uptime_stdout,
    split_clock_bash,
)

PERF_SAMPLE = """
Sys::Performance Connections
---------------------------------------------------------------------------
Active Connections           Current  Average  Max(since 05/21/26 08:28:24)
---------------------------------------------------------------------------
Connections                        0        0                             0

---------------------------------------------------------------------------
Total New Connections(/sec)  Current  Average  Max(since 05/21/26 08:28:24)
---------------------------------------------------------------------------
Client Connections                 0        0                             0
Server Connections                 0        0                             0

Sys::Performance CPU Usage(%)  Current  Average  Max
---------------------------------------------------------------------------
Utilization                        5        4                            12

Memory Used(%)       Current  Average  Max(since 05/21/26 10:28:44)
---------------------------------------------------------------------------
TMM Memory Used           34       34                            34
Other Memory Used         92       91                            93
"""

PERF_THROUGHPUT_BITS = """
Sys::Performance Throughput(bits)
---------------------------------------------------------------------------
Throughput(bits)(bits/sec)     Current  Average  Max(since 05/21/26 10:11:06)
---------------------------------------------------------------------------
Service                          23.3K    24.2K                         71.5K
In                                2.0M     5.2M                        899.8M
Out                              22.4K    22.5K                         77.5K
"""

CERT_SAMPLE = """
CN=foo expired on May 29 12:00:00 2021 GMT
CN=bar will expire on Jun 12 23:59:59 2026 GMT
"""

DF_SAMPLE = """
Filesystem      Size  Used Avail Use% Mounted on
/dev/md1 50G 29G 21G 59% /var
/dev/md2 200G 67G 133G 67% /shared
/dev/foo 10G 10G 0 100% /var/usm
"""


PSU_HW = """
Appliance Power Supply Status
  Index  Status       Current
  1      up           AC
  2      not-present  NA
"""

INLET_HW = """
Inlet Temperature Status
  Index  Lo Limit(C)  Temp(degC)  Hi Limit(C)  Location
  1      0            25          45           Chassis Inlet 2
"""


def test_parse_tmos_psu_table() -> None:
    psus = parse_tmos_psu_status(PSU_HW)
    assert format_tmos_psu_value(psus) == "PSU1 Up / PSU2 Down"


def test_parse_inlet_temperature() -> None:
    assert parse_inlet_temperature_c(INLET_HW) == 25.0


def test_compare_clock_kst() -> None:
    date = "Thu May 21 14:16:55 KST 2026"
    clock = "Sys::Clock\nClock .... Thu May 21 14:16:55 KST 2026\n"
    ok, _, detail = compare_system_clock(date, clock)
    assert ok is True
    assert "parse 실패" not in detail


def test_compare_clock_kst_date_only_line() -> None:
    """rSeries: clock 없이 date 한 줄만 있을 때 pass."""
    ok, summary, detail = compare_system_clock("Thu May 21 15:40:34 KST 2026", "")
    assert ok is True
    assert "2026" in summary
    assert "parse 실패" not in detail


def test_parse_uptime_days() -> None:
    assert parse_uptime_stdout("up 101 days, 3:22") == 101 * 86400


def test_parse_uptime_rejects_zero() -> None:
    assert parse_uptime_stdout("up 0 min") is None
    assert parse_uptime_stdout("up 0 days") is None


def test_format_uptime_hours() -> None:
    assert format_uptime_display(9 * 3600) == "9.0 hours"


def test_parse_df_exact_mount_only() -> None:
    paths = parse_df_paths(DF_SAMPLE)
    assert paths["/var"] == 59.0
    assert paths["/shared"] == 67.0


def test_parse_sys_service_running() -> None:
    text = "tmm   running\nbigd  running\nmcpd  running\n"
    found = parse_sys_service(text)
    assert found["tmm"] == "running"


def test_parse_performance_tmm_memory() -> None:
    perf = parse_sys_performance(PERF_SAMPLE)
    assert perf["memory"].display() == "34 / 34 / 34"


def test_parse_performance_throughput_service() -> None:
    perf = parse_sys_performance(PERF_THROUGHPUT_BITS)
    assert perf["throughput"].display() == "23.3K / 24.2K / 71.5K"


def test_parse_ntpq_synced() -> None:
    text = (
        "     remote           refid      st t when poll reach   delay   offset  jitter\n"
        "=============================================================================\n"
        "*10.1.1.1          .GPS.            1 u   45  64  377    0.1   -0.2    0.3\n"
    )
    assert parse_ntpq_np(text)["is_synced"] is True


def test_parse_ntpq_not_synced() -> None:
    text = (
        "     remote           refid      st t when poll reach   delay   offset  jitter\n"
        " 10.1.1.1          .INIT.           16 u    - 1024    0    0.0    0.0    0.0\n"
    )
    assert parse_ntpq_np(text)["is_synced"] is False


def test_vlan_interface_missing_is_down() -> None:
    vlan = "ltm vlan External { interfaces { 1.1 6.1 } }"
    iface = "Interface 1.1\nStatus up\n"
    up, down = check_vlan_interfaces_up(vlan, iface)
    assert "1.1" in up
    assert "6.1" in down


def test_eval_ntp_warn_when_not_synced() -> None:
    tmos = {
        "ntp": {
            "bash_stdout": (
                " remote refid\n"
                " 10.0.0.1 .INIT. 16 u - 1024 0 0.0 0.0 0.0\n"
            )
        }
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    ntp = next(r for r in results if r.item_id == "ntp")
    assert ntp.status == "warn"


def test_eval_virtual_edition_temperature_pass() -> None:
    tmos = {
        "hardware": {
            "bash_stdout": "Marketing Name BIG-IP Virtual Edition\n",
            "_source": "bash",
        }
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    temp = next(r for r in results if r.item_id == "temperature")
    assert temp.status == "pass"
    assert "Virtual Edition" in temp.value


def test_ssl_expired_and_will_expire_detail_lists() -> None:
    text = (
        "CN=*.navercorp.com expired on Mar 11 23:59:59 2026 GMT\n"
        "CN=*.airport.co.kr in file /Common/x will expire on Jun  6 2026 GMT\n"
    )
    detail = format_ssl_cert_detail(text)
    assert "만료:" in detail and "navercorp" in detail
    assert "만료예정:" in detail and "x" in detail
    assert parse_ssl_cert_expired_list(text) == ["*.navercorp.com"]


def test_ssl_expired_same_cn_different_files() -> None:
    lines = [
        "CN=*.airport.co.kr in file /Common/cert-a.crt expired on Jan  1 2025 GMT",
        "CN=*.airport.co.kr in file /Common/cert-b.crt expired on Feb  1 2025 GMT",
        "CN=*.airportnoise.kr in file /Common/noise.crt expired on Mar  1 2025 GMT",
    ]
    text = "\n".join(lines) + "\n"
    assert parse_ssl_cert_check_stdout(text)["expired"] == 3
    labels = parse_ssl_cert_expired_list(text)
    assert len(labels) == 3
    assert labels == ["cert-a.crt", "cert-b.crt", "noise.crt"]


def test_ssl_airport_lab_sample_11_expired() -> None:
    """SSL_O_1 현장 check-cert 샘플 — 만료 11 / 만료예정 1."""
    text = """
CN=*.airport.co.kr,O=KAC in file /Common/20Y_star.airpot.co.kr.crt expired on May 29 12:00:00 2021 GMT
CN=*.airport.co.kr,O=KAC in file /Common/21Y_star.airpot.co.kr.crt expired on May 30 23:59:59 2022 GMT
CN=*.airport.co.kr,O=KAC in file /Common/22Y_star.airpot.co.kr.crt expired on Jun  2 23:59:59 2023 GMT
CN=*.airport.co.kr,O=KAC in file /Common/23Y_star.airport.co.kr.crt expired on Jun  7 23:59:59 2024 GMT
CN=*.airport.co.kr,O=KAC in file /Common/24Y_star.airport.co.kr.crt expired on Jun  8 23:59:59 2025 GMT
CN=*.airport.co.kr,O=KAC in file /Common/25Y_star.airport.co.kr.crt will expire on Jun 12 23:59:59 2026 GMT
CN=*.airportnoise.kr in file /Common/airportnoise1_cert.crt expired on Feb 27 12:00:00 2021 GMT
CN=*.airportnoise.kr in file /Common/airportnoise_21Y.crt expired on Feb 27 23:59:59 2022 GMT
CN=*.airportnoise.kr in file /Common/airportnoise_22Y.crt expired on Mar 12 23:59:59 2023 GMT
CN=*.airportnoise.kr in file /Common/airportnoise_23Y.crt expired on Mar 12 23:59:59 2024 GMT
CN=*.airportnoise.kr in file /Common/airportnoise_24Y.crt expired on Mar 12 23:59:59 2025 GMT
CN=*.airportnoise.kr in file /Common/airportnoise_25Y.crt expired on Mar 25 23:59:59 2026 GMT
"""
    counts = parse_ssl_cert_check_stdout(text)
    assert counts == {"expired": 11, "will_expire": 1}
    expired = parse_ssl_cert_expired_list(text)
    assert len(expired) == 11
    assert "20Y_star.airpot.co.kr.crt" in expired
    assert "airportnoise_25Y.crt" in expired
    will = parse_ssl_cert_will_expire_list(text)
    assert will == ["25Y_star.airport.co.kr.crt"]
    detail = format_ssl_cert_detail(text)
    assert "만료:" in detail and "20Y_star.airpot.co.kr.crt" in detail
    assert "만료예정:" in detail and "25Y_star.airport.co.kr.crt" in detail


def test_ssl_expired_line_not_counted_as_will_expire() -> None:
    text = (
        "CN=*.navercorp.com,O=NAVER Corp. in file /Common/25Y_PSA "
        "expired on Mar 11 23:59:59 2026 GMT\n"
    )
    counts = parse_ssl_cert_check_stdout(text)
    assert counts == {"expired": 1, "will_expire": 0}


def test_eval_ssl_pass_with_expired_and_will_expire() -> None:
    text = (
        "CN=foo expired on Feb 21 2021 GMT\n"
        "CN=bar in file /Common/ca-bundle.crt will expire on Jun  6 2026 GMT\n"
    )
    results = evaluate_common(
        tmos={
            "_meta": {"tmos_host": "192.168.1.10", "hostname": "bigip1"},
            "certs": {"bash_stdout": text},
        },
        f5os=None,
        has_f5os_layer=False,
    )
    ssl = next(r for r in results if r.item_id == "ssl_cert")
    assert ssl.status == "pass"
    assert ssl.value == "만료 1 | 만료예정 1"
    assert "192.168" not in ssl.value
    assert "만료:" in ssl.detail and "foo" in ssl.detail
    assert "ca-bundle.crt" in ssl.detail
    counts = parse_ssl_cert_check_stdout(text)
    assert counts["expired"] == 1
    assert counts["will_expire"] == 1


def test_compare_clock_bash_date_and_clock() -> None:
    bash = "Thu May 21 14:16:55 KST 2026\n---F5TOOL_CLOCK---\nThu May 21 14:16:55 KST 2026\n"
    date_part, clock_part = split_clock_bash(bash)
    ok, _, detail = compare_system_clock(date_part, clock_part)
    assert ok is True
    assert "parse 실패" not in detail


def test_policy_backup_performed_success() -> None:
    tmos = {
        "backup_action": {"performed": True, "ok": True, "filename": "260520_lab.ucs"},
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    backup = next(r for r in results if r.item_id == "policy_backup")
    assert backup.status == "success"


def test_parse_ha_status_values() -> None:
    assert parse_ha_status("Status: ACTIVE")[0] == "Active"
    assert parse_ha_status("Status: STANDBY")[0] == "Standby"
    assert parse_ha_status("Status: STANDALONE")[0] == "Standalone"
    assert parse_ha_status("Status: FORCED-OFFLINE")[0] == "Force Offline"
    assert parse_ha_status("BIG-IP local failover Status: Active")[0] == "Active"


def test_eval_ha_status_force_offline_fail() -> None:
    tmos = {
        "failover": {
            "bash_stdout": "Status: FORCED-OFFLINE",
            "_source": "bash",
        },
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    ha = next(r for r in results if r.item_id == "ha_status")
    assert ha.value == "Force Offline"
    assert ha.status == "fail"


def test_ucs_cleanup_only_target_file() -> None:
    cmd = _ucs_cleanup_command("20260521", "SSL_O_1")
    assert cmd == "tmsh delete sys ucs 20260521-SSL_O_1.ucs"
    assert "*.ucs" not in cmd
    assert "find " not in cmd
    assert "rm " not in cmd


def test_policy_backup_deferred_scheduled_pass() -> None:
    tmos = {
        "backup_action": {
            "performed": False,
            "scheduled": True,
            "filename": "20260521-bigip1.ucs",
        },
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    backup = next(r for r in results if r.item_id == "policy_backup")
    assert backup.status == "pass"
    assert "백그라운드" in backup.value
    assert "ucs_backup.log" in backup.detail
