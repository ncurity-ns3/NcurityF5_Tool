from __future__ import annotations

from app.modules.health_check.common_eval import evaluate_common
from app.modules.health_check.f5os_common import parse_f5os_overview


def test_evaluate_uptime_pass() -> None:
    tmos = {"uptime": {"bash_stdout": "up 101 days, 3:22", "_source": "bash"}}
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    tmos_rows = [r for r in results if r.item_id == "uptime" and r.layer == "tmos"]
    assert tmos_rows[0].status == "pass"


def test_evaluate_uptime_rseries_tmos_only() -> None:
    tmos = {"uptime": {"bash_stdout": "up 10 days", "_source": "bash"}}
    results = evaluate_common(
        tmos=tmos,
        f5os={"uptime_seconds": 8 * 86400},
        has_f5os_layer=True,
        is_rseries=True,
    )
    layers = {r.layer for r in results if r.item_id == "uptime"}
    assert layers == {"tmos"}


def test_evaluate_uptime_warn_over_one_year() -> None:
    tmos = {"uptime": {"bash_stdout": "up 400 days, 1:00", "_source": "bash"}}
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    uptime = next(r for r in results if r.item_id == "uptime")
    assert uptime.status == "warn"


def test_f5os_temperature_from_fixture() -> None:
    overview = {
        "openconfig-platform:components": {
            "component": [
                {
                    "name": "platform",
                    "state": {
                        "f5-platform:temperature": {
                            "current": "27.0",
                            "average": "26.0",
                            "maximum": "30.0",
                        },
                        "f5-platform:file-systems": {
                            "file-system": [{"used-percent": 50}]
                        },
                    },
                }
            ]
        }
    }
    parsed = parse_f5os_overview(overview)
    assert parsed["max_temperature_c"] == 30.0
    results = evaluate_common(
        tmos={},
        f5os=parsed,
        has_f5os_layer=True,
        is_rseries=True,
    )
    temp = [r for r in results if r.item_id == "temperature" and r.layer == "f5os"]
    assert temp and temp[0].status == "pass"
    assert "avg" in temp[0].value
    assert "Cur/Avg" not in temp[0].value


def test_f5os_power_from_health_summary() -> None:
    f5os = {
        "psu_health": {"psu-1": "up"},
        "psu_health_source": "cli",
    }
    results = evaluate_common(
        tmos={},
        f5os=f5os,
        has_f5os_layer=True,
        is_rseries=True,
    )
    power = next(r for r in results if r.item_id == "power" and r.layer == "f5os")
    assert power.status == "pass"
    assert "psu-1 up" in power.value


def test_f5os_interface_skip_when_vlan_unavailable() -> None:
    f5os = {
        "interface_ports": [
            {"name": "1.0", "status": "up"},
            {"name": "mgmt", "status": "up"},
        ],
        "interface_source": "rest",
        "vlan_unavailable": True,
        "show_vlans_cli_supported": False,
    }
    results = evaluate_common(
        tmos={},
        f5os=f5os,
        has_f5os_layer=True,
        is_rseries=True,
    )
    iface = next(r for r in results if r.item_id == "interface" and r.layer == "f5os")
    assert iface.status == "skip"
    assert "show vlan" in iface.detail


def test_f5os_interface_vlan_in_use_pass() -> None:
    f5os = {
        "vlan_count": 2,
        "vlan_in_use_interfaces": ["1.0", "2.0"],
        "vlan_source": "cli",
        "interface_ports": [
            {"name": "1.0", "status": "up"},
            {"name": "2.0", "status": "up"},
            {"name": "mgmt", "status": "up"},
        ],
        "interface_source": "cli",
    }
    results = evaluate_common(
        tmos={},
        f5os=f5os,
        has_f5os_layer=True,
        is_rseries=True,
    )
    iface = next(r for r in results if r.item_id == "interface" and r.layer == "f5os")
    assert iface.status == "pass"
    assert "2 up" in iface.value
    assert "Up: 1.0, 2.0" in iface.value
    assert "Down: —" in iface.value
    assert "mgmt Up" in iface.value


def test_evaluate_uptime_rseries_no_f5os_row() -> None:
    results = evaluate_common(
        tmos={"uptime": {"bash_stdout": "up 10 days", "_source": "bash"}},
        f5os={"uptime_seconds": 999},
        has_f5os_layer=True,
        is_rseries=True,
    )
    uptime_layers = [r.layer for r in results if r.item_id == "uptime"]
    assert uptime_layers == ["tmos"]


def test_interface_down_fails() -> None:
    tmos = {
        "vlan_list": {"bash_stdout": "interfaces { 1.1 }"},
        "interfaces": {"bash_stdout": "Interface 1.1\nStatus down\n"},
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    iface = next(r for r in results if r.item_id == "interface")
    assert iface.status == "fail"


def test_interface_up_down_counts() -> None:
    tmos = {
        "vlan_list": {"bash_stdout": "interfaces { 1.1 6.1 }"},
        "interfaces": {"bash_stdout": "Interface 1.1\nStatus up\n"},
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    iface = next(r for r in results if r.item_id == "interface")
    assert iface.status == "fail"
    assert "1 up" in iface.value
    assert "1 down" in iface.value
    assert "Up: 1.1" in iface.value
    assert "Down: 6.1" in iface.value
    assert "Up: 1.1" in iface.detail
    assert "Down: 6.1" in iface.detail


def test_new_connections_client_only() -> None:
    tmos = {
        "performance": {
            "bash_stdout": (
                "Total New Connections(/sec)  Current  Average  Max\n"
                "Client Connections                 2        2                             3\n"
                "Server Connections                 9        9                             9\n"
            )
        }
    }
    results = evaluate_common(tmos=tmos, f5os=None, has_f5os_layer=False)
    nc = next(r for r in results if r.item_id == "new_connections")
    assert "Client 2 / 2 / 3" in nc.value
    assert "Server" not in nc.value
