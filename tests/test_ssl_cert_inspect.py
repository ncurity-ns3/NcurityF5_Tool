"""In-use SSL certificates from a UCS/QKView-style config and PEM."""

from __future__ import annotations

import base64
import io
import os
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.gui.views.ssl_cert_view import SslCertView
from app.modules.ssl_cert.inspect import inspect_archive, inspect_config

_app = QApplication.instance() or QApplication([])
_TODAY = date(2026, 11, 20)

_CONF = """
sys global-settings {
    hostname lab-bigip.example.com
}
sys file ssl-cert /Common/www.crt {
    cache-path /config/filestore/files_d/Common_d/certificate_d/:Common:www.crt_10_1
}
sys file ssl-cert /Common/old.crt {
    cache-path /config/filestore/files_d/Common_d/certificate_d/:Common:old.crt_4_2
}
ltm profile client-ssl /Common/www_clientssl {
    cert /Common/www.crt
    chain /Common/ca-bundle.crt
    key /Common/www.key
    cert-key-chain {
        www {
            cert /Common/www.crt
            key /Common/www.key
        }
    }
}
ltm profile server-ssl /Common/pool_serverssl {
    cert /Common/server.crt
    key /Common/server.key
}
ltm profile client-ssl /Common/unused_clientssl {
    cert /Common/old.crt
    key /Common/old.key
}
ltm virtual /Common/vs_www {
    destination 10.0.0.1:443
    profiles {
        /Common/www_clientssl {
            context clientside
        }
        /Common/pool_serverssl {
            context serverside
        }
        /Common/tcp { }
    }
}
ltm virtual /Common/vs_www_2 {
    profiles {
        www_clientssl { }
    }
}
"""


def _tlv(tag: int, body: bytes) -> bytes:
    length = len(body)
    if length < 128:
        prefix = bytes([length])
    elif length < 256:
        prefix = bytes([0x81, length])
    else:
        prefix = bytes([0x82, length >> 8, length & 0xFF])
    return bytes([tag]) + prefix + body


def _pem(not_before: datetime, not_after: datetime) -> bytes:
    def utc(moment: datetime) -> bytes:
        return _tlv(0x17, moment.strftime("%y%m%d%H%M%SZ").encode())

    tbs = _tlv(
        0x30,
        _tlv(0xA0, _tlv(0x02, b"\x02"))
        + _tlv(0x02, b"\x01")
        + _tlv(0x30, b"")
        + _tlv(0x30, b"")
        + _tlv(0x30, utc(not_before) + utc(not_after))
        + _tlv(0x30, b"")
        + _tlv(0x30, b""),
    )
    der = _tlv(0x30, tbs + _tlv(0x30, b"") + _tlv(0x03, b"\x00"))
    body = base64.encodebytes(der).decode().strip()
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----\n".encode()


def _files() -> list[tuple[str, bytes]]:
    live = _pem(
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
    )
    soon = _pem(
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 12, 10, tzinfo=UTC),
    )
    expired = _pem(
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    )
    return [
        ("config/filestore/files_d/Common_d/certificate_d/:Common:www.crt_10_1", live),
        ("config/filestore/files_d/Common_d/certificate_d/:Common:www.crt_1_1", soon),
        ("config/filestore/files_d/Common_d/certificate_d/:Common:old.crt_4_2", expired),
        ("config/ssl/ssl.crt/server.crt", soon),
    ]


def test_in_use_certs_show_profile_virtual_and_expiry() -> None:
    report = inspect_config(_CONF, _files(), today=_TODAY)
    by_profile = {row.profile: row for row in report.rows}
    assert report.hostname == "lab-bigip.example.com"
    assert set(by_profile) == {"www_clientssl", "pool_serverssl", "unused_clientssl"}

    www = by_profile["www_clientssl"]
    assert www.cert == "www.crt"
    assert www.side == "Client SSL"
    assert www.virtuals == ("vs_www", "vs_www_2")
    assert www.expiry_text == "2026-12-01 (11일 남음)"
    assert www.expiry_kind == "soon"

    server = by_profile["pool_serverssl"]
    assert server.virtuals == ("vs_www",)
    assert server.side == "Server SSL"
    assert "20일 남음" in server.expiry_text

    unused = by_profile["unused_clientssl"]
    assert unused.virtuals == ()
    assert unused.expiry_text == "만료됨 (2024-03-01)"
    assert report.rows[0].expiry_kind == "expired"


def test_archive_reads_conf_and_the_newer_cert(tmp_path: Path) -> None:
    archive = tmp_path / "lab.ucs"
    with tarfile.open(archive, "w:gz") as tar:
        conf = _CONF.encode()
        info = tarfile.TarInfo("config/bigip.conf")
        info.size = len(conf)
        tar.addfile(info, io.BytesIO(conf))
        for name, data in _files():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))

    report = inspect_archive(archive, today=_TODAY)
    www = next(row for row in report.rows if row.profile == "www_clientssl")
    assert www.expiry_text == "2026-12-01 (11일 남음)"
    assert report.source_name == "lab.ucs"


def test_ssl_menu_is_the_third_device_check_page() -> None:
    window = MainWindow(Path(__file__).resolve().parents[1])
    labels: list[tuple[str, int]] = []
    for row in range(window.nav.count()):
        item = window.nav.item(row)
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None:
            labels.append((item.text().strip(), int(index)))
    names = [name for name, _index in labels]
    assert names.index("OS 업그레이드 간 점검") < names.index("SSL 인증서 확인")
    assert names.index("SSL 인증서 확인") < names.index("납품확인서 작성")
    page = window.stack.widget(dict(labels)["SSL 인증서 확인"])
    assert isinstance(page, SslCertView)

    report = inspect_config(_CONF, _files(), today=_TODAY)
    page.show_report(report)
    assert page.table.rowCount() == 3
    headers = [
        page.table.horizontalHeaderItem(col).text() for col in range(page.table.columnCount())
    ]
    status = page.table.item(0, 0).text()
    virtual = page.table.item(0, 3).text()
    expiry = page.table.item(0, 4).text()
    assert "구분" not in headers
    assert status == "만료됨"
    assert virtual == "없음"
    assert expiry.startswith("만료됨")
    status_label = page.table.cellWidget(0, 0)
    assert status_label is not None
    assert "#FDECEC" not in status_label.styleSheet()
    assert status_label.text() == "만료됨"
    assert "만료" in page.summary.text()
    assert page.stat_total.text() == "3"
    assert page.stat_soon.text() == "2"
    assert page.stat_expired.text() == "1"
    assert page.stat_expired_off.text() == "1"
    assert page.stat_expired_on.text() == "0"
    cert = page.table.cellWidget(0, 1)
    assert cert is not None
    flags = cert.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    window.close()
