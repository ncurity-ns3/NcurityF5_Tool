from __future__ import annotations

from app.modules.os_upgrade.ucs_config_check import (
    parse_cm_device_self,
    parse_ucs_vlan_rows,
)


_HA_PAIR = """
cm device /Common/autoever-vpn-1.com {
    chassis-id "f5-gdru-gwow   "
    hostname autoever-vpn-1.com
    marketing-name "BIG-IP i10800"
    management-ip 10.255.122.40
    platform-id C116
    self-device true
    version 17.5.1.3
}
cm device /Common/autoever-vpn-2.com {
    chassis-id "f5-hixj-zkdq   "
    hostname autoever-vpn-2.com
    management-ip 10.255.122.41
    platform-id C116
    version 17.5.1.3
}
"""

_HA_PAIR_UNIT2 = """
cm device /Common/autoever-vpn-1.com {
    chassis-id "f5-gdru-gwow   "
    hostname autoever-vpn-1.com
    platform-id C116
    version 17.5.1.3
}
cm device /Common/autoever-vpn-2.com {
    chassis-id "f5-hixj-zkdq   "
    hostname autoever-vpn-2.com
    management-ip 10.255.122.41
    platform-id C116
    self-device true
    version 17.5.1.3
}
"""

_VLAN_TRUNK_SAMPLE = """
net trunk ex_tr {
    interfaces {
        2.1
        2.2
    }
}
net trunk ha-tr {
    interfaces {
        1.1
        1.2
    }
}
net trunk in_tr {
    interfaces {
        2.3
        2.4
    }
}
net vlan /Common/ex {
    interfaces {
        ex_tr { }
    }
    tag 100
}
net vlan /Common/ha {
    interfaces {
        ha-tr { }
    }
    tag 300
}
net vlan /Common/in {
    interfaces {
        in_tr { }
    }
    tag 200
}
net vlan /Common/External {
    interfaces {
        1.5 { }
    }
    tag 215
}
"""


def test_cm_device_self_device_unit1() -> None:
    dev = parse_cm_device_self(_HA_PAIR)
    assert dev["hostname"] == "autoever-vpn-1.com"
    assert dev["serial"] == "f5-gdru-gwow"


def test_cm_device_self_device_unit2() -> None:
    dev = parse_cm_device_self(_HA_PAIR_UNIT2)
    assert dev["hostname"] == "autoever-vpn-2.com"
    assert dev["serial"] == "f5-hixj-zkdq"


def test_vlan_trunk_and_direct_interface() -> None:
    rows = parse_ucs_vlan_rows(_VLAN_TRUNK_SAMPLE)
    by_vlan = {r.vlan: r for r in rows}

    ex = by_vlan["/Common/ex"]
    assert ex.interface == "Trunk 사용"
    assert ex.tagging == "100 Untag"
    assert ex.trunk_members == "2.1, 2.2"

    ha = by_vlan["/Common/ha"]
    assert ha.interface == "Trunk 사용"
    assert ha.tagging == "300 Untag"
    assert ha.trunk_members == "1.1, 1.2"

    ext = by_vlan["/Common/External"]
    assert ext.interface == "1.5"
    assert ext.tagging == "215 Untag"
    assert ext.trunk_members == "—"
