from __future__ import annotations

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from app.modules.os_upgrade.ucs_extract import (
    extract_ucs,
    extract_ucs_batch,
    write_ucs_batch_outputs,
    write_ucs_extract_outputs,
)
from app.modules.os_upgrade.ucs_reader import UcsReadError, read_ucs_config_texts


_SAMPLE_BASE = """
cm device /Common/bigip1 {
    platform-id C115
    self-device true
    marketing-name "BIG-IP i10800"
    hostname site-bigip01.example.com
    chassis-id f5-gdru-gwow
    version 17.1.2.1
    management-ip 10.255.122.40
}

net vlan internal {
    interfaces {
        1.1 { untagged }
    }
}
net self internal_self {
    address 10.0.1.10
    netmask 255.255.255.0
    vlan internal
}
"""

_SAMPLE_CONF = """
net route default {
    gw 10.0.1.1
    network default
}

ltm pool pool_web { }
ltm virtual vs_web { destination 10.0.1.20:443 }
"""

_SAMPLE_LICENSE = """
Service Check Date   : 2026-04-15
"""


def _write_minimal_ucs(path: Path, *, hostname: str = "site-bigip01.example.com") -> None:
    base = _SAMPLE_BASE.replace("site-bigip01.example.com", hostname)
    with tarfile.open(path, "w:gz") as tar:
        for name, content in (
            ("config/bigip_base.conf", base),
            ("config/bigip.conf", _SAMPLE_CONF),
            ("config/bigip.license", _SAMPLE_LICENSE),
        ):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _write_ucs_with_im_members(path: Path, *, hostname: str = "site-bigip01.example.com") -> None:
    """대용량 UCS — config/*.conf.im (gzip) 형태."""
    base = _SAMPLE_BASE.replace("site-bigip01.example.com", hostname)
    with tarfile.open(path, "w:gz") as tar:
        for arc_name, content, compress in (
            ("config/bigip_base.conf.im", base, True),
            ("config/bigip.conf.im", _SAMPLE_CONF, True),
            ("config/bigip.license", _SAMPLE_LICENSE, False),
        ):
            data = content.encode("utf-8")
            if compress:
                data = gzip.compress(data)
            info = tarfile.TarInfo(name=arc_name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_read_ucs_and_extract(tmp_path: Path) -> None:
    ucs = tmp_path / "lab.ucs"
    _write_minimal_ucs(ucs)

    texts = read_ucs_config_texts(ucs)
    assert "bigip_base.conf" in texts
    assert "bigip.conf" in texts

    result = extract_ucs(ucs, device_label="lab-01", target_version="21.1.x")
    assert result.hostname == "site-bigip01.example.com"
    assert result.check.hostname == "site-bigip01.example.com"
    rows = {r.label: r.value for r in result.check.rows}
    assert rows["Platform"] == "BIG-IP i10800"
    assert rows["Serial Number"] == "f5-gdru-gwow"
    assert rows["TMOS Version"] == "17.1.2.1"
    assert rows["TMOS MGMT-IP"] == "10.255.122.40"
    assert len(result.check.vlan_rows) >= 1
    assert len(result.check.self_ip_rows) >= 1
    assert any(r.gw == "10.0.1.1" for r in result.check.route_rows)
    assert result.check.license_check is not None


def test_ucs_im_members_inside_archive(tmp_path: Path) -> None:
    ucs = tmp_path / "large.ucs"
    _write_ucs_with_im_members(ucs)
    texts = read_ucs_config_texts(ucs)
    assert "cm device" in texts["bigip_base.conf"]
    result = extract_ucs(ucs, target_version="21.1.x")
    assert result.hostname == "site-bigip01.example.com"
    assert result.check.rows[0].label == "Platform"


def test_invalid_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "not_ucs.txt"
    bad.write_text("hello", encoding="utf-8")
    with pytest.raises(UcsReadError):
        read_ucs_config_texts(bad)

    folder = tmp_path / "config_only"
    folder.mkdir()
    with pytest.raises(UcsReadError):
        read_ucs_config_texts(folder)


def test_write_outputs(tmp_path: Path) -> None:
    ucs = tmp_path / "site.ucs"
    _write_minimal_ucs(ucs)
    extracted = extract_ucs(ucs, unit_label="1호기", target_version="21.1.x")
    ws = tmp_path / "out"
    html = write_ucs_extract_outputs(ws, extracted)
    assert html.is_file()
    assert (ws / "extracted.json").is_file()
    payload = json.loads((ws / "extracted.json").read_text(encoding="utf-8"))
    assert payload["units"][0]["check"]["hostname"] == "site-bigip01.example.com"
    assert (ws / "units" / "1호기" / "extracted.json").is_file()
    report = (ws / "report.html").read_text(encoding="utf-8")
    assert "Platform" in report
    assert "bigip_base.conf" not in report


def test_batch_two_units(tmp_path: Path) -> None:
    from app.modules.os_upgrade.ucs_reader import peek_ucs_hostname

    ucs1 = tmp_path / "host1.ucs"
    ucs2 = tmp_path / "host2.ucs"
    _write_minimal_ucs(ucs1, hostname="bigip01.example.com")
    _write_minimal_ucs(ucs2, hostname="bigip02.example.com")

    assert peek_ucs_hostname(ucs1) == "bigip01.example.com"
    labels = [peek_ucs_hostname(ucs1), peek_ucs_hostname(ucs2)]

    batch = extract_ucs_batch(
        [ucs1, ucs2], labels=labels, auto_unit_labels=False, target_version="21.1.x"
    )
    assert len(batch.units) == 2
    assert batch.units[0].hostname == "bigip01.example.com"
    assert batch.units[1].hostname == "bigip02.example.com"

    ws = tmp_path / "batch_out"
    write_ucs_batch_outputs(ws, batch, site_name="lab")
    html = (ws / "report.html").read_text(encoding="utf-8")
    assert "bigip01.example.com" in html
    assert "bigip02.example.com" in html
    assert "OS Upgrade 가능 여부" in html
