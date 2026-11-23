"""QKView regular inspection: status rows, line charts, and the mode chooser."""

from __future__ import annotations

import gzip
import io
import os
import tarfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QApplication

from app.gui.views.health_check_view import HealthCheckView
from app.gui.widgets.ncurity_checkbox import NcurityCheckBox
from app.modules.health_check.qkview_inspect import (
    QkviewReport,
    StatusRow,
    inspect_qkview,
    write_qkview_html,
    write_qkview_reports,
)

_app = QApplication.instance() or QApplication([])

_PROC = """<module>
<item name="Platform_ID">Z100</item>
<uptime_t><f_uptime>172800</f_uptime></uptime_t>
<command cmdline="/usr/bin/tmsh -a show cm sync-status">
<value>Color    green
Status   In Sync</value>
</command>
<command cmdline="/usr/sbin/ntpq -pn">
<value>     remote           refid
==============================================================================
*time.example    .GPS.  1 u  10 64 377
</value>
</command>
</module>
"""

_STAT = """<stats>
<object name="pwr1"><status>1</status></object>
<object name="fan1"><status>1</status></object>
<chassis_temperature_status_stat>
<object name="temp1"><temperature>30</temperature></object>
</chassis_temperature_status_stat>
</stats>
"""

_CONF = "sys global-settings { hostname bigip.example }\n"

_RRD = """<rrd><step>300</step><lastupdate>1700000000</lastupdate>
<rra><pdp_per_row>60</pdp_per_row><database>
<row><v>10</v><v>20</v></row>
<row><v>30</v><v>40</v></row>
</database></rra></rrd>
"""

_F5OS = """# show components
components component psu-1
psu-stats psu-power-in 300
fantray fan-stats fan-1-speed 17000
state temperature current 25
state temperature average 26
state temperature minimum 22
state temperature maximum 30
# show interfaces
interface 1/1
 oper-status UP
"""


def _add(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _tmos_qkview(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        _add(archive, "qkview/proc_module.xml", _PROC.encode())
        _add(archive, "qkview/stat_module.xml", _STAT.encode())
        _add(archive, "qkview/config/bigip_base.conf", _CONF.encode())
        _add(
            archive,
            "qkview/var/tmp/qkview-rrd/planestat.xml.gz",
            gzip.compress(_RRD.encode()),
        )


def test_tmos_status_and_line_chart(tmp_path: Path) -> None:
    source = tmp_path / "lab.qkview"
    _tmos_qkview(source)
    report = inspect_qkview(source)
    assert report.kind == "TMOS"
    assert report.hostname == "bigip.example (VE)"
    by_name = {row.name: row for row in report.rows}
    assert by_name["Uptime"].comment == "2 days"
    assert by_name["설정 동기화"].result == "O"
    assert by_name["ntp 상태"].result == "O"
    assert by_name["파워 상태"].result == "O"
    assert by_name["온도"].result == "O"
    chart = next(item for item in report.charts if item.title == "CPU 사용률")
    assert chart.series[0][0] == "Data Plane"
    assert chart.series[0][1] == (10.0, 30.0)
    dest = tmp_path / "report.html"
    write_qkview_html(report, dest)
    text = dest.read_text(encoding="utf-8")
    assert "상태점검" in text
    assert "성능 그래프" in text
    assert "polyline" in text
    assert "#0260EA" in text


def test_f5os_component_rows(tmp_path: Path) -> None:
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w:gz") as package:
        _add(package, "show/out", _F5OS.encode())
    source = tmp_path / "rseries.qkview"
    with tarfile.open(source, "w:gz") as archive:
        _add(archive, "bundle/subpackages/system_manager.tar.gz", nested.getvalue())
    report = inspect_qkview(source)
    assert report.kind == "F5OS"
    by_name = {row.name: row for row in report.rows}
    assert by_name["파워 상태"].result == "O"
    assert by_name["팬 상태"].result == "O"
    assert by_name["온도"].result == "O"
    assert by_name["인터페이스 상태"].result == "O"
    assert "1/1" in by_name["인터페이스 상태"].comment
    assert by_name["코어파일"].result == "O"


def test_health_view_qkview_mode(tmp_path: Path) -> None:
    view = HealthCheckView(tmp_path)
    view.show()
    _app.processEvents()
    assert view.mode_device_radio.text() == "1. 실제 장비 접속 후 점검하기"
    assert view.mode_qkview_radio.text() == "2. QKView로 점검하기"
    assert view.mode_stack.currentIndex() == 0
    view.mode_qkview_radio.setChecked(True)
    _app.processEvents()
    assert view.mode_stack.currentIndex() == 1
    assert view.qk_report_btn.text() == "Open Report Window"
    assert view.qk_folder_btn.text() == "폴더 열기"
    view.close()


def test_qkview_list_adds_many_and_removes(tmp_path: Path) -> None:
    one = tmp_path / "one.qkview"
    two = tmp_path / "two.qkview"
    one.write_bytes(b"a")
    two.write_bytes(b"b")
    view = HealthCheckView(tmp_path)
    view.show()
    _app.processEvents()
    view.mode_qkview_radio.setChecked(True)
    view._add_qkviews([two, one, one, tmp_path / "note.txt"])
    assert [path.name for path in view._qk_paths] == ["one.qkview", "two.qkview"]
    boxes = view.qk_files_box.findChildren(NcurityCheckBox)
    assert [box.text() for box in boxes] == ["one.qkview", "two.qkview"]
    view.qk_select_all_btn.click()
    assert all(box.isChecked() for box in boxes)
    view.qk_clear_btn.click()
    assert not any(box.isChecked() for box in boxes)
    boxes[0].setChecked(True)
    view.qk_remove_btn.click()
    assert [path.name for path in view._qk_paths] == ["two.qkview"]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(one)), QUrl.fromLocalFile(str(two))])
    view.dropEvent(
        QDropEvent(
            QPointF(12, 12),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert [path.name for path in view._qk_paths] == ["one.qkview", "two.qkview"]
    view.close()


def test_report_lists_each_qkview(tmp_path: Path) -> None:
    reports = [
        QkviewReport("a.qkview", "a.example", "TMOS", (StatusRow("Uptime", "-", "1 days"),), ()),
        QkviewReport("b.qkview", "b.example", "TMOS", (StatusRow("Uptime", "-", "2 days"),), ()),
    ]
    dest = tmp_path / "report.html"
    write_qkview_reports(reports, dest)
    text = dest.read_text(encoding="utf-8")
    assert "QKView 점검 · 2대" in text
    assert "a.example" in text
    assert "b.example" in text
    assert "상태점검" in text
    assert "성능 그래프" in text
