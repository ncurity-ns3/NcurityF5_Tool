"""Troubleshooting collect uses the connected device and shared form values."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel

from app.gui.connection_draft import ConnectionDraft
from app.gui.main_window import MainWindow
from app.gui.views.troubleshooting_view import TroubleshootingView
from app.gui.widgets.device_connection_panel import DeviceConnectionPanel
from app.modules.troubleshooting.collect import (
    Artifact,
    collect_artifacts,
    file_stem,
    parse_core_paths,
    planned_commands,
)

_app = QApplication.instance() or QApplication([])
_ROOT = Path(__file__).resolve().parents[1]


class _Device:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.downloads: list[str] = []
        self.endpoints: list[str] = []

    def run_util_bash(self, command: str, timeout: float | None = None) -> str:
        self.commands.append(command)
        if command.startswith("find "):
            return "/var/core/tmm.core\n/etc/passwd\n../secret\n"
        if command.startswith("f5mku"):
            return "0123456789abcdef"
        return "ok"

    def get_system_info(self) -> dict[str, str]:
        return {"hostname": "3Team-VE.com"}

    def download_var_tmp_file(
        self,
        name: str,
        dest: Path,
        timeout: float = 1800.0,
        endpoint: str = "qkview-downloads",
        total_size: int = 0,
    ) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"file")
        self.downloads.append(name)
        self.endpoints.append(endpoint)


def test_download_header_reports_http_status_and_size() -> None:
    from app.core.bigip_client import _download_failure, _header_span, _header_status, _header_total

    text = "HTTP/1.1 200 OK\r\nContent-Range: 0-99/4321\r\n"
    assert _header_status(text) == 200
    assert _header_total(text) == 4321
    assert _header_span("Content-Range: bytes 512-1023/4096") == (512, 4096)
    assert _download_failure(404) == "장비에서 파일을 찾지 못했습니다."
    body = b'{"code":404,"message":"Public URI path not registered"}'
    detail = _download_failure(404, body)
    assert "찾지 못했습니다" in detail
    assert "Public URI path not registered" in detail


def test_save_location_sits_on_the_same_line_as_its_path() -> None:
    view = TroubleshootingView(_ROOT)
    view.resize(980, 720)
    view.show()
    _app.processEvents()
    place = next(label for label in view.findChildren(QLabel) if label.text() == "저장 위치")
    item = next(label for label in view.findChildren(QLabel) if label.text() == "항목")
    place_y = place.mapTo(view, place.rect().center()).y()
    path_y = view.folder_label.mapTo(view, view.folder_label.rect().center()).y()
    item_y = item.mapTo(view, item.rect().center()).y()
    check_y = view.qkview.mapTo(view, view.qkview.rect().center()).y()
    assert abs(place_y - path_y) <= 2
    assert abs(item_y - check_y) <= 2
    view.close()


def test_ucs_plan_includes_f5mku_and_cores_stay_on_device_paths() -> None:
    assert file_stem("261124", "3Team-VE.com") == "261124-3Team-VE.com"
    planned = planned_commands("261124-3Team-VE.com", qkview=True, logs=True, ucs=True)
    commands = [item[2] for item in planned]
    assert any("qkview -f /var/tmp/qkviews/" in command for command in commands)
    assert any("tar czf /var/tmp/qkviews/" in command for command in commands)
    assert "tmsh save sys ucs 261124-3Team-VE.com.ucs" in commands
    assert "f5mku -K 2>&1" in commands
    assert "261124-3Team-VE.com-log-tar.gz" in [item[1] for item in planned]
    assert "261124-3Team-VE.com.mku-K.txt" in [item[1] for item in planned]
    without = planned_commands("261124-3Team-VE.com", qkview=True, logs=False, ucs=False)
    assert all("f5mku" not in command for _name, _file, command in without)
    assert parse_core_paths("/var/core/tmm.core\n/tmp/x\n") == ["/var/core/tmm.core"]


def test_collect_downloads_selected_files_and_hides_mku_from_status(tmp_path: Path) -> None:
    device = _Device()
    rows = collect_artifacts(
        device,
        tmp_path,
        label="lab",
        stamp="261124",
        qkview=True,
        logs=True,
        cores=True,
        ucs=True,
    )
    by_name = {row.name: row for row in rows}
    assert by_name["Qkview"].status == "받음"
    assert by_name["Log Tarball"].status == "받음"
    assert by_name["UCS"].status == "받음"
    assert by_name["MKU"].status == "저장됨"
    assert "0123456789abcdef" not in by_name["MKU"].status
    mku = tmp_path / "261124-3Team-VE.com.mku-K.txt"
    assert mku.read_text(encoding="utf-8") == "0123456789abcdef"
    assert by_name["Core File Check"].status == "있음"
    assert "/var/core/tmm.core" in by_name["Core File Check"].path
    assert "passwd" not in " ".join(device.downloads)
    joined = "\n".join(device.commands)
    assert "/shared/images/" not in joined
    assert "ln -f" not in joined
    assert "rm -f /var/tmp/261124-3Team-VE.com.qkview" in joined
    assert "rm -f /var/tmp/qkviews/261124-3Team-VE.com.qkview" in joined
    assert "rm -f /var/tmp/qkviews/261124-3Team-VE.com-log-tar.gz" in joined
    assert "rm -f /var/local/ucs/261124-3Team-VE.com.ucs" in joined
    assert joined.index("rm -f /var/tmp/qkviews/261124-3Team-VE.com.qkview") < joined.index(
        "qkview -f /var/tmp/qkviews/261124-3Team-VE.com.qkview"
    )
    assert "test -s /var/tmp/qkviews/261124-3Team-VE.com.qkview" in joined
    assert "test -s /var/tmp/qkviews/261124-3Team-VE.com-log-tar.gz" in joined
    assert "test -s /var/local/ucs/261124-3Team-VE.com.ucs" in joined
    assert device.endpoints == ["qkview-autodeploy", "qkview-autodeploy", "ucs-downloads"]
    assert device.downloads == [
        "261124-3Team-VE.com.qkview",
        "261124-3Team-VE.com-log-tar.gz",
        "261124-3Team-VE.com.ucs",
    ]


def test_var_tmp_file_falls_back_to_shared_images(tmp_path: Path) -> None:
    class _MissUntilImages(_Device):
        def download_var_tmp_file(
            self,
            name: str,
            dest: Path,
            timeout: float = 1800.0,
            endpoint: str = "qkview-downloads",
            total_size: int = 0,
        ) -> None:
            self.endpoints.append(endpoint)
            if endpoint != "image-downloads":
                raise RuntimeError("장비에서 파일을 찾지 못했습니다.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"file")
            self.downloads.append(name)

    device = _MissUntilImages()
    rows = collect_artifacts(
        device,
        tmp_path,
        label="lab",
        stamp="261124",
        qkview=False,
        logs=True,
        cores=False,
        ucs=False,
    )
    assert rows[0].status == "받음"
    assert device.endpoints == ["qkview-autodeploy", "image-downloads"]
    joined = "\n".join(device.commands)
    assert "cp -f /var/tmp/qkviews/261124-3Team-VE.com-log-tar.gz /shared/images/" in joined
    assert "rm -f /shared/images/261124-3Team-VE.com-log-tar.gz" in joined
    assert device.downloads == ["261124-3Team-VE.com-log-tar.gz"]


def test_new_collect_clears_the_previous_result_table() -> None:
    view = TroubleshootingView(_ROOT)
    view._fill(
        [
            Artifact("Qkview", "받음", "261124-3Team-VE.com.qkview"),
            Artifact("UCS", "실패", "X-F5-Auth-Token has expired."),
        ]
    )
    view.status.setText("완료 2건")
    view._clear_results()
    assert view.table.rowCount() == 0
    assert view.status.text() == ""
    view.close()


def test_troubleshooting_page_defaults_and_sits_above_delivery(tmp_path: Path) -> None:
    view = TroubleshootingView(_ROOT)
    assert view.findChild(QLabel).text() == "트러블슈팅 자료 수집"
    checked = {box.text(): box.isChecked() for box in view.findChildren(QCheckBox)}
    assert checked["Qkview"] is True
    assert checked["Log Tarball"] is True
    assert checked["Core File Check"] is False
    assert checked["UCS"] is False
    assert view.progress.minimum() == 0
    assert view.progress.maximum() == 100
    window = MainWindow(_ROOT)
    names = []
    try:
        for row in range(window.nav.count()):
            item = window.nav.item(row)
            if item.data(1) is None and item.text().strip() in {"Device Check"}:
                continue
            names.append(item.text().strip())
        assert names.index("SSL 인증서 확인") < names.index("트러블슈팅 자료 수집")
        assert names.index("트러블슈팅 자료 수집") < names.index("납품확인서 작성")
        assert "이슈 분석자료 수집" not in names
    finally:
        window.close()
        view.close()


def test_connected_form_fills_an_empty_panel(tmp_path: Path) -> None:
    ConnectionDraft.instance().clear()
    try:
        first = DeviceConnectionPanel(tmp_path / "a")
        second = DeviceConnectionPanel(tmp_path / "b")
        first.host_edit.setText("10.1.1.10")
        first.port_spin.setValue(8443)
        first.user_edit.setText("ops")
        first.pass_edit.setText("secret-value")
        first.label_edit.setText("edge-01")
        first.publish_connected_form()
        assert second.host_edit.text() == "10.1.1.10"
        assert second.port_spin.value() == 8443
        assert second.user_edit.text() == "ops"
        assert second.pass_edit.text() == "secret-value"
        assert second.label_edit.text() == "edge-01"
        second.host_edit.setText("10.9.9.9")
        first.host_edit.setText("10.2.2.2")
        first.publish_connected_form()
        assert second.host_edit.text() == "10.9.9.9"
    finally:
        ConnectionDraft.instance().clear()
