"""Hosted Content list and extract from a UCS sandbox filestore."""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHeaderView

from app.gui.main_window import MainWindow
from app.gui.views.hosted_content_view import HostedContentView
from app.modules.hosted_content.extract import (
    HostedContentError,
    HostedContentReport,
    HostedFile,
    extract_hosted_files,
    hosted_display_folder,
    hosted_display_name,
    list_hosted_content,
)

_app = QApplication.instance() or QApplication([])

_CONF = """
apm resource sandbox /Common/hosted-content {
    base-uri /public/share
    files {
        laptop.txt {
            cache-path /config/filestore/files_d/Common_d/sandbox_file_d/\
:Common:hosted-content::laptop.txt_10_1
            content-type text/plain
            filename laptop.txt
            folder /
        }
        guide.pdf {
            cache-path /config/filestore/files_d/Common_d/sandbox_file_d/PDF/\
:Common:hosted-content::guide.pdf_20_2
            content-type application/pdf
            filename guide.pdf
            folder /PDF
        }
        missing.bin {
            filename missing.bin
            folder /bin
        }
    }
}
apm resource sandbox /Common/citrix-client-bundle {
    base-uri /public/citrix
    files {
        old.exe {
            filename old.exe
            folder /client
        }
    }
}
"""


def _ucs(path: Path) -> None:
    files = {
        "config/bigip.conf": _CONF.encode(),
        (
            "config/filestore/files_d/Common_d/sandbox_file_d/"
            ":Common:hosted-content::laptop.txt_10_1"
        ): b"laptop",
        (
            "config/filestore/files_d/Common_d/sandbox_file_d/"
            ":Common:hosted-content::laptop.txt_1_1"
        ): b"old-laptop",
        (
            "config/filestore/files_d/Common_d/sandbox_file_d/PDF/"
            ":Common:hosted-content::guide.pdf_20_2"
        ): b"%PDF-guide",
        (
            "config/filestore/files_d/Common_d/sandbox_file_d/PDF/"
            ":Common:hosted-content::guide.pdf_3_1"
        ): b"old-pdf",
        (
            "config/filestore/files_d/Common_d/sandbox_file_d/client/"
            ":Common:citrix-client-bundle::old.exe_8_1"
        ): b"MZ-exe",
    }
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_list_uses_sandbox_folders_and_the_cache_revision(tmp_path: Path) -> None:
    archive = tmp_path / "lab.ucs"
    _ucs(archive)
    report = list_hosted_content(archive)
    by_name = {item.name: item for item in report.files}
    assert set(by_name) == {"laptop.txt", "guide.pdf", "missing.bin", "old.exe"}

    laptop = by_name["laptop.txt"]
    assert laptop.virtual_path == "/public/share/laptop.txt"
    assert laptop.member_name.endswith("laptop.txt_10_1")
    assert laptop.size == len(b"laptop")

    guide = by_name["guide.pdf"]
    assert guide.virtual_path == "/public/share/PDF/guide.pdf"
    assert "/PDF/" in guide.member_name
    assert guide.member_name.endswith("guide.pdf_20_2")

    missing = by_name["missing.bin"]
    assert missing.present is False
    assert missing.virtual_path == "/public/share/bin/missing.bin"

    exe = by_name["old.exe"]
    assert "/client/" in exe.member_name
    assert exe.sandbox == "citrix-client-bundle"


def test_qkview_is_rejected(tmp_path: Path) -> None:
    qkview = tmp_path / "lab.qkview"
    qkview.write_bytes(b"not a ucs")
    try:
        list_hosted_content(qkview)
    except HostedContentError as exc:
        assert "QKView" in str(exc)
    else:
        raise AssertionError("qkview should be rejected")


def test_extract_keeps_the_hosted_folder(tmp_path: Path) -> None:
    archive = tmp_path / "lab.ucs"
    _ucs(archive)
    report = list_hosted_content(archive)
    dest = tmp_path / "out"
    written, missing = extract_hosted_files(archive, list(report.files), dest)
    saved = {path.relative_to(dest).as_posix(): path.read_bytes() for path in written}
    assert saved["hosted-content/laptop.txt"] == b"laptop"
    assert saved["hosted-content/PDF/guide.pdf"] == b"%PDF-guide"
    assert saved["citrix-client-bundle/client/old.exe"] == b"MZ-exe"
    assert any("missing.bin" in name for name in missing)


def test_display_name_and_folder_drop_internal_ids() -> None:
    assert hosted_display_name(
        "BIGIPEdgeClient.exe_1582726701768",
        "BIGIPEdgeClient.exe_1582726701768",
    ) == "BIGIPEdgeClient.exe"
    assert hosted_display_name("DG_BLOCK.png_1761780003896", "") == "DG_BLOCK.png"
    assert hosted_display_name(
        "DaaS_VDI_Manual.pdf_1761808317167",
        "DaaS_VDI_Manual.pdf",
    ) == "DaaS_VDI_Manual.pdf"
    assert hosted_display_folder("/public/share/1129.html") == "/"
    assert hosted_display_folder("/public/share/JS/app.js") == "/JS"
    assert hosted_display_folder("/public/share/Manual/a.pdf") == "/Manual"
    assert hosted_display_folder("/public/citrix/client/old.exe") == "/client"


def test_host_table_groups_by_folder_and_selects_all() -> None:
    page = HostedContentView()
    page.show_report(
        HostedContentReport(
            source_name="lab.ucs",
            files=(
                _file(
                    "BIGIPEdgeClient.exe_1582726701768",
                    "/public/share/BIGIPEdgeClient.exe_1582726701768",
                    1024,
                ),
                _file(
                    "CSSTEST.css_1654222564081",
                    "/public/share/CSS/CSSTEST.css",
                    2048,
                    "CSSTEST.css",
                ),
                _file("missing.bin", "/public/share/bin/missing.bin", -1, present=False),
            ),
        )
    )
    headers = [page.table.headerItem().text(col) for col in range(page.table.columnCount())]
    assert headers == ["이름", "크기"]
    folders = [page.table.topLevelItem(i).text(0) for i in range(page.table.topLevelItemCount())]
    assert folders == ["/", "/bin", "/CSS"]
    root = page.table.topLevelItem(0)
    assert root.child(0).text(0) == "BIGIPEdgeClient.exe"
    assert root.child(0).text(1) == "1.0 KB"
    css = page.table.topLevelItem(2)
    assert css.child(0).text(0) == "CSSTEST.css"
    page.apply_folder_check(root, False)
    assert page._state(root.child(0)) == Qt.CheckState.Unchecked
    assert page._state(root) == Qt.CheckState.Unchecked
    page.apply_folder_check(root, True)
    assert page._state(root.child(0)) == Qt.CheckState.Checked
    assert page._state(root) == Qt.CheckState.Checked
    missing = page.table.topLevelItem(1).child(0)
    page.select_all_btn.click()
    assert page._state(missing) == Qt.CheckState.Unchecked
    assert page._state(css.child(0)) == Qt.CheckState.Checked
    page.select_none_btn.click()
    assert page._state(root.child(0)) == Qt.CheckState.Unchecked
    mode = page.table.header().sectionResizeMode(1)
    assert mode == QHeaderView.ResizeMode.Interactive
    assert page.table.cursor().shape() == Qt.CursorShape.ArrowCursor
    page.show()
    _app.processEvents()
    page.close()


def _file(
    name: str,
    virtual_path: str,
    size: int,
    filename: str = "",
    *,
    present: bool = True,
) -> HostedFile:
    return HostedFile(
        sandbox="hosted-content",
        name=name,
        filename=filename or name,
        folder="/",
        virtual_path=virtual_path,
        cache_path="",
        member_name="member" if present else "",
        size=size,
    )


def test_host_content_menu_follows_macro_copy() -> None:
    window = MainWindow(Path(__file__).resolve().parents[1])
    labels: list[tuple[str, int]] = []
    for row in range(window.nav.count()):
        item = window.nav.item(row)
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None:
            labels.append((item.text().strip(), int(index)))
    names = [name for name, _index in labels]
    assert names.index("VPE Macro Copy") < names.index("Host Content 추출")
    page = window.stack.widget(dict(labels)["Host Content 추출"])
    assert isinstance(page, HostedContentView)
    window.close()
