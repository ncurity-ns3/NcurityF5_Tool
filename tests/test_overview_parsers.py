from app.modules.os_upgrade.overview_parsers import (
    build_tmos_vlan_table,
    parse_f5os_system_image_version,
    parse_f5os_system_version,
    parse_f5os_version_from_image_state,
    parse_tmos_list_net_route,
    parse_tmos_platform_hw,
    parse_tmos_show_sys_version,
    parse_ve_serial_from_license,
    resolve_tmos_serial,
)


def test_parse_tmos_platform_ve_with_hypervisor() -> None:
    hw = """
Platform
  Name  BIG-IP Virtual Edition
  Hypervisor     VMware Virtual Platform
System Information
"""
    assert "Virtual Edition" in parse_tmos_platform_hw(hw)
    assert "VMware" in parse_tmos_platform_hw(hw)


def test_parse_tmos_platform_iseries() -> None:
    hw = """
Platform
  Name  BIG-IP i7600
  BIOS Revision  OBJ-0645
"""
    assert parse_tmos_platform_hw(hw) == "BIG-IP i7600"


def test_parse_tmos_version_build() -> None:
    text = """
Sys::Version
Main Package
  Product     BIG-IP
  Version     17.5.1.3
  Build       0.0.19
"""
    assert parse_tmos_show_sys_version(text) == "17.5.1.3-0.0.19"


def test_ve_serial_from_license() -> None:
    lic = "Registration key  LJLHM-RRMKX-NGDGO-YRYWJ-AXELXVW"
    assert parse_ve_serial_from_license(lic) == "AXELXVW"


def test_resolve_serial_appliance() -> None:
    hw = "System Information\n  Appliance Serial  f5-xdbf-zynz\n"
    assert resolve_tmos_serial(hw, "") == "f5-xdbf-zynz"


def test_build_tmos_vlan_table_media() -> None:
    vlan = "net vlan ex { tag 100 interfaces { 1.1 { } } }"
    iface = "1.1       up  117.3G   14.7G   42.5M   21.7M      0     0  10000T-FD"
    rows = build_tmos_vlan_table(vlan, iface)
    assert len(rows) == 1
    assert rows[0].vlan == "ex"
    assert rows[0].tagging == "Untag"
    assert rows[0].media == "10000T-FD"


def test_build_tmos_vlan_tagged_stanza() -> None:
    vlan = """
net vlan ju_internal_vlan {
    tag 4093
    interfaces {
        1.3 {
            tagged
        }
    }
}
"""
    rows = build_tmos_vlan_table(vlan, "")
    assert len(rows) == 1
    assert rows[0].interface == "1.3"
    assert rows[0].tagging == "Tag"


def test_parse_tmos_list_net_route() -> None:
    text = """
net route default {
    gw 10.1.10.1
    network 0.0.0.0/0
}
net route /Common/internal {
    gw 10.1.20.1
    network 10.0.0.0/8
}
"""
    rows = parse_tmos_list_net_route(text)
    by_name = {r.name: r.gw for r in rows}
    assert by_name["default"] == "10.1.10.1"
    assert by_name["/Common/internal"] == "10.1.20.1"


def test_parse_f5os_iface_vlan_mode_native_and_trunk() -> None:
    from app.modules.os_upgrade.overview_parsers import parse_f5os_iface_vlan_mode

    cfg = """
interfaces interface 1.0
 ethernet switched-vlan config native-vlan 30
interfaces interface 2.0
 ethernet switched-vlan config trunk-vlans [ 50 ]
"""
    modes = parse_f5os_iface_vlan_mode(cfg)
    assert modes["1.0"] == "Untag"
    assert modes["2.0"] == "Tag"


def test_parse_f5os_system_version_cli_lines() -> None:
    text = """
system version os-version 1.8.0-16036
system version service-version 1.8.0-16036
system version product F5OS-A
"""
    assert parse_f5os_system_version(text) == "1.8.0-16036"


def test_parse_f5os_system_version_user_sample() -> None:
    text = """
system version os-version 1.8.3-23493
system version service-version 1.8.3-23493
system version product F5OS-A
"""
    assert parse_f5os_system_version(text) == "1.8.3-23493"


def test_parse_f5os_version_from_image_state_json() -> None:
    data = {
        "f5-system-image:state": {
            "os": {
                "os": [
                    {"version-os": "1.1.0-0188", "in-use": False},
                    {"version-os": "1.8.3-23493", "in-use": True},
                ]
            },
            "install": {"install-os-version": "1.8.3-23493"},
        }
    }
    assert parse_f5os_version_from_image_state(data) == "1.8.3-23493"


def test_parse_f5os_system_image_active_os() -> None:
    text = """
IN VERSION OS STATUS DATE SIZE USE TYPE
-------------------------------------------------------
1.5.0-5781 ready 2023-08-14 4.55GB false
1.5.1-12283 ready 2023-08-14 926.15MB true
"""
    assert parse_f5os_system_image_version(text) == "1.5.1-12283"
