from app.modules.os_upgrade.overview_parsers import (
    build_self_ip_rows,
    build_tmos_vlan_table,
    parse_net_self_list,
)


def test_parse_net_self_by_vlan() -> None:
    text = """
net self ex_self {
    address 58.87.56.8
    netmask 255.255.255.0
    vlan ju_external_vlan
}
net self in_float {
    address 10.31.5.70
    netmask 255.255.255.0
    vlan ju_internal_vlan
    floating enabled
}
"""
    by_vlan = parse_net_self_list(text)
    assert "ju_external_vlan" in by_vlan
    assert by_vlan["ju_external_vlan"][0][0] == "58.87.56.8"
    assert by_vlan["ju_internal_vlan"][0][0] == "10.31.5.70"


def test_build_vlan_table_without_ip_columns() -> None:
    vlan = """
net vlan ju_external_vlan {
    tag 4094
    interfaces { 1.2 { } }
}
"""
    iface = "1.2       up  0  0  0  0  0  0  10000T-FD"
    rows = build_tmos_vlan_table(vlan, iface)
    assert len(rows) == 1
    assert rows[0].vlan == "ju_external_vlan"
    assert rows[0].interface == "1.2"
    assert rows[0].tagging == "Untag"
    assert rows[0].media == "10000T-FD"
    assert not hasattr(rows[0], "ip")


def test_build_self_ip_rows_uses_self_names() -> None:
    self_text = """
net self ex_self {
    address 58.87.56.8
    netmask 255.255.255.0
    vlan ju_external_vlan
}
net self in_float {
    address 10.31.5.70
    netmask 255.255.255.0
    vlan ju_internal_vlan
    floating enabled
}
"""
    rows = build_self_ip_rows(self_text)
    by_name = {r.item: r for r in rows}
    assert "ex_self" in by_name
    assert "in_float" in by_name
    assert by_name["ex_self"].value == "58.87.56.8/24"
    assert by_name["in_float"].value == "10.31.5.70/24"
    assert "floating" in by_name["in_float"].remark
    assert "ju_external_vlan" in by_name["ex_self"].remark
