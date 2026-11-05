from __future__ import annotations

from app.modules.health_check.f5os_common import (
    check_f5os_vlan_interfaces_up,
    collect_psu_health_rest,
    format_f5os_psu_value,
    parse_f5os_interfaces,
    parse_f5os_interfaces_summary,
    parse_f5os_overview,
    parse_f5os_show_vlans,
    parse_f5os_system_health_summary_psu,
    parse_f5os_uptime_text,
    parse_f5os_vlan_in_use_from_interfaces,
    parse_f5os_vlan_in_use_from_vlans,
)
from app.modules.health_check.f5os_detect import (
    has_f5os_platform_data,
    is_rseries_device,
)


def test_parse_f5os_uptime_weeks_days() -> None:
    sec = parse_f5os_uptime_text("1w, 1d, 2h, 5m, 45s")
    assert sec == 7 * 86400 + 86400 + 2 * 3600 + 5 * 60 + 45


def test_parse_f5os_overview_psu_and_disk() -> None:
    overview = {
        "openconfig-platform:components": {
            "component": [
                {
                    "name": "platform",
                    "state": {
                        "f5-platform:temperature": {
                            "current": "27",
                            "average": "26",
                            "maximum": "30",
                        },
                        "f5-platform:file-systems": {
                            "file-system": [
                                {"area": "platform/sysroot", "used-percent": 15}
                            ]
                        },
                    },
                },
                {
                    "name": "psu-1",
                    "state": {
                        "f5-fan-psu-stats:psu-stats": {"psu-power-in": "60.0"}
                    },
                },
            ]
        }
    }
    data = parse_f5os_overview(overview)
    assert data["psu_ok"] is True
    assert data["disk_areas"][0]["percent"] == 15
    assert data["temperature_avg_c"] == 26.0


def test_parse_f5os_show_vlans_and_summary() -> None:
    vlans = """
VLAN
ID    INTERFACE
-----------------
30    1.0
90    2.0
"""
    rows, in_use = parse_f5os_show_vlans(vlans)
    assert rows == 2
    assert in_use == {"1.0", "2.0"}

    summary = """
NAME  TYPE            MTU   ENABLED  STATUS
-------------------------------------------------------------------------------
1.0   ethernetCsmacd  9600  true     UP
2.0   ethernetCsmacd  9600  true     UP
3.0   ethernetCsmacd  9600  false    DOWN
mgmt  ethernetCsmacd  -     true     UP
"""
    ports = parse_f5os_interfaces_summary(summary)
    data_ports = [p for p in ports if p["name"] != "mgmt"]
    up, down = check_f5os_vlan_interfaces_up(in_use, data_ports)
    assert down == []
    assert up == ["1.0", "2.0"]


def test_parse_f5os_health_summary_psu() -> None:
    text = """
COMPONENT        COMPONENT  COMPONENT  ATTRIBUTE  ATTRIBUTE
NAME       NAME  HEALTH     SEVERITY   NAME
psu-1      -     ok         info
"""
    states = parse_f5os_system_health_summary_psu(text)
    assert states == {"psu-1": "up"}
    assert format_f5os_psu_value(states) == "psu-1 up"


def test_parse_f5os_show_vlan_singular() -> None:
    text = """
VLAN
ID    INTERFACE
-----------------
30    1.0
90    2.0
"""
    rows, in_use = parse_f5os_show_vlans(text)
    assert rows == 2
    assert in_use == {"1.0", "2.0"}


def test_parse_vlan_rest_config_interface() -> None:
    body = {
        "openconfig-vlan:vlans": {
            "vlan": [
                {"vlan-id": 30, "config": {"vlan-id": 30}, "interface": "1.0"},
                {"vlan-id": 90, "config": {"vlan-id": 90, "interface": "2.0"}},
            ]
        }
    }
    assert parse_f5os_vlan_in_use_from_vlans(body) == {"1.0", "2.0"}


def test_collect_psu_health_from_overview_state() -> None:
    overview = {
        "openconfig-platform:components": {
            "component": [
                {
                    "name": "psu-1",
                    "state": {"health": "ok", "empty": False},
                }
            ]
        }
    }
    psu = collect_psu_health_rest(
        type("C", (), {"get": lambda self, p: {}})(),  # type: ignore[arg-type]
        "/api",
        overview,
    )
    assert psu.get("psu-1") == "up"


def test_parse_f5os_vlan_in_use_rest_fallbacks() -> None:
    ifaces = {
        "openconfig-interfaces:interfaces": {
            "interface": [
                {
                    "name": "1.0",
                    "ethernet": {
                        "openconfig-vlan:switched-vlan": {
                            "config": {"native-vlan": 30},
                        }
                    },
                },
                {"name": "mgmt", "state": {"oper-status": "UP"}},
            ]
        }
    }
    assert parse_f5os_vlan_in_use_from_interfaces(ifaces) == {"1.0"}

    vlans = {
        "openconfig-vlan:vlans": {
            "vlan": [
                {
                    "vlan-id": 30,
                    "members": {"member": [{"interface": "2.0"}]},
                }
            ]
        }
    }
    assert parse_f5os_vlan_in_use_from_vlans(vlans) == {"2.0"}


def test_parse_f5os_interfaces() -> None:
    body = {
        "openconfig-interfaces:interfaces": {
            "interface": [
                {"name": "1.0", "state": {"oper-status": "UP"}},
                {"name": "2.0", "state": {"oper-status": "DOWN"}},
            ]
        }
    }
    ports = parse_f5os_interfaces(body)
    assert len(ports) == 2
    assert ports[0]["status"] == "up"


def test_has_f5os_platform_data() -> None:
    assert is_rseries_device({"f5os": {"overview": {}}})
    assert not has_f5os_platform_data({"f5os": {"overview": {}}})
    assert has_f5os_platform_data(
        {"_platform": "rseries", "common": {"f5os": {"uptime_seconds": 1}}}
    )
    assert not has_f5os_platform_data({"common": {"tmos": {}}})
