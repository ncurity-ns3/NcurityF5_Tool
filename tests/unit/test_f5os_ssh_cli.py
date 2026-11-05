from __future__ import annotations

from app.core import f5os_ssh_cli
from app.modules.health_check.f5os_common import (
    parse_f5os_interfaces_summary,
    parse_f5os_show_vlans,
    parse_f5os_system_health_summary_psu,
)


def test_parse_psu_and_vlan_from_user_samples() -> None:
    health = """
psu-1      -     ok         info
"""
    assert parse_f5os_system_health_summary_psu(health) == {"psu-1": "up"}

    vlan = """
VLAN
ID    INTERFACE
-----------------
30    1.0
90    2.0
"""
    rows, in_use = parse_f5os_show_vlans(vlan)
    assert rows == 2
    assert in_use == {"1.0", "2.0"}

    ifaces = """
NAME  TYPE            MTU   ENABLED  STATUS
1.0   ethernetCsmacd  9600  true     UP
2.0   ethernetCsmacd  9600  true     UP
mgmt  ethernetCsmacd  -     true     UP
"""
    ports = parse_f5os_interfaces_summary(ifaces)
    assert ports[0]["name"] == "1.0" and ports[0]["status"] == "up"


def test_run_f5os_admin_cli_is_disabled() -> None:
    out = f5os_ssh_cli.run_f5os_admin_cli(
        "192.168.1.1",
        "secret",
        ["show vlan"],
    )
    assert "_ssh_disabled" in out
    assert f5os_ssh_cli.first_ssh_admin_show("192.168.1.1", "secret", "show vlan") == ""
