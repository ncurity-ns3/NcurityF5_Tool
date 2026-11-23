"""Web Customizing is saved with a macro and applied only when Load asks for it."""

from __future__ import annotations

import base64
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.gui.dialogs.apply_macro_dialog import LoadMacroDialog
from app.modules.vpe_macro.apm_macro import AccessProfileRef, MacroSnapshot
from app.modules.vpe_macro.customization import (
    apply_saved_customization,
    cache_path_allowed,
    customization_templates,
    customization_write_commands,
    read_www_customization_files,
    www_path_allowed,
)

_app = QApplication.instance() or QApplication([])

_GROUP = (
    "/config/filestore/files_d/Common_d/customization_group_d/"
    ":Common:auth_ad_act_logon_page_ag_1_1"
)
_CSS_PATH = (
    "/config/filestore/files_d/Common_d/customization_template_d/"
    ":Common:auth_ad_act_logon_page_ag::user-logon.css_11_2"
)
_JS_PATH = (
    "/config/filestore/files_d/Common_d/customization_template_d/"
    ":Common:auth_ad_act_logon_page_ag::user-logon.js_12_1"
)
_OLD = f"""
apm policy customization-group /Common/auth_ad_act_logon_page_ag {{
    cache-path {_GROUP}
    templates {{
        user-logon.css {{
            cache-path {_CSS_PATH}
            name /Common/auth_ad_act_logon_page_ag:user-logon.css
        }}
        user-logon.js {{
            cache-path {_JS_PATH}
            name /Common/auth_ad_act_logon_page_ag:user-logon.js
        }}
        note.txt {{
            cache-path /tmp/evil
        }}
    }}
}}
"""

_NEW = _OLD.replace("auth_ad_act_logon_page_ag", "Auth_AD_2_act_logon_page_ag")


def test_advanced_files_are_listed_and_unsafe_paths_are_dropped() -> None:
    specs = customization_templates(_OLD)
    assert [item["name"] for item in specs] == ["user-logon.css", "user-logon.js"]
    assert cache_path_allowed("/tmp/evil") is False
    escaped = (
        "/config/filestore/files_d/Common_d/customization_template_d/"
        ":Common:../../etc/passwd"
    )
    assert cache_path_allowed(escaped) is False


def test_write_uses_the_new_group_file_and_hides_css_metacharacters() -> None:
    css = ".apmui-header { content: `x`; width: $y; }"
    commands = customization_write_commands(
        _NEW,
        [{"name": "user-logon.css", "text": css}],
    )
    assert len(commands) == 1
    filename, command = commands[0]
    assert filename == "user-logon.css"
    assert "Auth_AD_2_act_logon_page_ag::user-logon.css" in command
    assert "auth_ad_act_logon_page_ag::" not in command
    assert "`" not in command
    assert "$y" not in command
    payload = re.search(r"printf '%s' '([^']+)'", command)
    assert payload is not None
    assert base64.b64decode(payload.group(1)).decode() == css


def test_apply_writes_only_when_the_new_group_has_the_file() -> None:
    calls: list[str] = []

    def runner(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        calls.append(command)
        if command.startswith("tmsh -q list"):
            return _NEW
        return ""

    notes = apply_saved_customization(
        runner,
        partition="Common",
        source_name="auth_ad",
        actual="Auth_AD_2",
        agents=[
            {
                "type": "logon-page",
                "name": "auth_ad_act_logon_page_ag",
                "customization_files": [
                    {"name": "user-logon.css", "text": ".apmui-header { height: 0; }"}
                ],
            }
        ],
    )
    assert any("user-logon.css" in note for note in notes)
    assert any(call.startswith("printf ") and "Auth_AD_2_" in call for call in calls)
    assert all("auth_ad_act_logon_page_ag::" not in call for call in calls)


_WWW_SOURCE = (
    "/var/sam/www/client/customization/Common/"
    "auth_ad_act_logon_page_ag/logon/Common/user-logon.css"
)
_WWW_TARGET = (
    "/var/sam/www/client/customization/Common/"
    "Auth_AD_2_act_logon_page_ag_cg/logon/Common/user-logon.css"
)


def test_caption_parser_keeps_the_vpe_name() -> None:
    from app.modules.vpe_macro.apm_macro import parse_access_policy_captions

    text = """
apm policy access-policy /Common/AP_HD_Capital_CSH-auth_1factor_1_1 {
    caption Auth_1Factor
}
apm policy access-policy onefactor_deny_logging {
    caption "OneFactor_Deny_Logging"
}
"""
    assert parse_access_policy_captions(text) == {
        "AP_HD_Capital_CSH-auth_1factor_1_1": "Auth_1Factor",
        "onefactor_deny_logging": "OneFactor_Deny_Logging",
    }


def test_group_cache_directory_keeps_user_logon_files() -> None:
    cache = (
        "/config/filestore/files_d/Common_d/customization_group_d/"
        ":Common:auth_ad_act_logon_page_ag_11_1"
    )
    css_path = f"{cache}/user-logon.css"
    listed = f"""
apm policy customization-group /Common/auth_ad_act_logon_page_ag {{
    cache-path {cache}
    customization-type logon
}}
"""

    def runner(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        if command.startswith("tmsh "):
            return listed
        if command.startswith("find ") and cache in command:
            return css_path + "\n"
        if command == f"cat '{css_path}'":
            return ".apmui-header { height: 6px; }"
        return ""

    from app.modules.vpe_macro.customization import read_customization_files

    saved = read_customization_files(runner, "/Common/auth_ad_act_logon_page_ag")
    assert saved == [
        {
            "name": "user-logon.css",
            "relative": "logon/Common/user-logon.css",
            "text": ".apmui-header { height: 6px; }",
        }
    ]


def test_filestore_name_maps_logon_files_and_load_writes_the_new_agent() -> None:
    from app.modules.vpe_macro.customization import (
        cache_path_allowed,
        read_agent_filestore_files,
    )

    agent = "AP_HD_Capital_CSH-auth_1factor_act_logon_page_ag_1_1"
    css = (
        "/config/filestore/files_d/Common_d/customization_template_d/"
        f":Common:{agent}::user-logon.css_157190_1"
    )
    older = css.replace("_157190_1", "_100_1")
    js = (
        "/config/filestore/files_d/Common_d/customization_template_d/"
        f":Common:{agent}::user-logon.js_157193_9"
    )
    other = (
        "/config/filestore/files_d/Common_d/customization_group_d/"
        ":Common:other_agent::user-logon.css_1_1"
    )
    assert cache_path_allowed(css) is True

    def reader(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        if command.startswith("find ") and agent in command:
            return "\n".join((older, css, js, other, "/tmp/user-logon.css"))
        if command == f"cat '{css}'":
            return "/* css */"
        if command == f"cat '{js}'":
            return "/* js */"
        return ""

    saved, note = read_agent_filestore_files(reader, partition="Common", agent=agent)
    assert note == ""
    assert [(item["name"], item["text"]) for item in saved] == [
        ("user-logon.css", "/* css */"),
        ("user-logon.js", "/* js */"),
    ]

    calls: list[str] = []

    def writer(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        calls.append(command)
        return ""

    notes = apply_saved_customization(
        writer,
        partition="Common",
        source_name="auth_ad",
        actual="Auth_AD_2",
        agents=[
            {
                "type": "logon-page",
                "name": "auth_ad_act_logon_page_ag",
                "customization_files": [{"name": "user-logon.css", "text": "/* css */"}],
            }
        ],
    )
    assert any("user-logon.css" in note for note in notes)
    assert any(
        "templates add" in call
        and "local-path /var/tmp/f5tool/" in call
        and "user-logon.css" in call
        for call in calls
    )
    assert all(agent not in call for call in calls)
    assert all("_1_1" not in call for call in calls)


def test_load_registers_the_file_on_the_new_group() -> None:
    calls: list[str] = []
    logs: list[str] = []
    lists = {"n": 0}

    def writer(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        calls.append(command)
        if command.startswith("tmsh -q list"):
            lists["n"] += 1
            if lists["n"] >= 2:
                return _NEW
        return ""

    notes = apply_saved_customization(
        writer,
        partition="Common",
        source_name="auth_ad",
        actual="Auth_AD_2",
        agents=[
            {
                "type": "logon-page",
                "name": "auth_ad_act_logon_page_ag",
                "customization_files": [{"name": "user-logon.css", "text": "/* css */"}],
            }
        ],
        progress=logs.append,
    )
    assert any("편집기에 등록: user-logon.css (add" in line for line in logs)
    assert any("편집기 cache-path:" in line and "user-logon.css_" in line for line in logs)
    assert any("user-logon.css" in note for note in notes)
    assert any("local-path /var/tmp/f5tool/" in call for call in calls)
    assert all("_1_1" not in call for call in calls)


def test_general_ui_keeps_each_language_and_load_writes_the_new_macro() -> None:
    from app.modules.vpe_macro.customization import (
        general_ui_file_allowed,
        read_general_ui_files,
    )

    ko = (
        "/var/sam/www/client/customization-group/general_ui/Common/"
        "Auth_1Factor/ko/user-logon.css"
    )
    en = (
        "/var/sam/www/client/customization-group/general_ui/Common/"
        "Auth_1Factor/en/user-logon.js"
    )
    assert general_ui_file_allowed(ko) is True
    assert general_ui_file_allowed("/tmp/user-logon.css") is False
    assert general_ui_file_allowed(ko.replace("/ko/", "/../")) is False

    def reader(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        if command.startswith("find ") and "Auth_1Factor" in command:
            return ko + "\n" + en + "\n/tmp/user-logon.css\n"
        if command == f"cat '{ko}'":
            return "/* ko */"
        if command == f"cat '{en}'":
            return "/* en */"
        return "find: missing"

    saved, note = read_general_ui_files(
        reader,
        partition="Common",
        folders=["Auth_1Factor", "AP_HD_Capital_CSH-auth_1factor_1_1"],
    )
    assert note == ""
    assert {item["relative"]: item["text"] for item in saved} == {
        "ko/user-logon.css": "/* ko */",
        "en/user-logon.js": "/* en */",
    }

    calls: list[str] = []

    def writer(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        calls.append(command)
        return ""

    notes = apply_saved_customization(
        writer,
        partition="Common",
        source_name="AP_HD_Capital_CSH-auth_1factor_1_1",
        actual="Auth_1Factor",
        agents=[
            {
                "type": "logon-page",
                "name": "AP_HD_Capital_CSH-auth_1factor_act_logon_page_ag_1_1",
                "customization_files": saved,
            }
        ],
    )
    dest = (
        "/var/sam/www/client/customization-group/general_ui/Common/"
        "Auth_1Factor/ko/user-logon.css"
    )
    assert any("ko/user-logon.css" in note for note in notes)
    assert any(dest in call and call.startswith("mkdir ") for call in calls)
    assert all("AP_HD_Capital_CSH-auth_1factor_1_1" not in call for call in calls)


def test_editor_tree_outside_the_profile_is_rejected() -> None:
    assert www_path_allowed(_WWW_SOURCE) is True
    assert www_path_allowed("/tmp/user-logon.css") is False
    assert www_path_allowed(
        "/var/sam/www/client/customization-group/general_ui/Common/AP/user-logon.css"
    ) is False
    assert www_path_allowed(_WWW_SOURCE.replace("/logon/", "/../")) is False


def test_save_reads_the_editor_tree_and_load_writes_the_new_profile() -> None:
    css = ".apmui-header { height: 40px; }"

    def reader(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        if command.startswith("find "):
            return _WWW_SOURCE + "\n/tmp/user-logon.css\n"
        if command == f"cat '{_WWW_SOURCE}'":
            return css
        return ""

    saved, note = read_www_customization_files(
        reader,
        partition="Common",
        group="auth_ad_act_logon_page_ag",
    )
    assert note == ""
    assert saved == [
        {
            "name": "user-logon.css",
            "relative": "logon/Common/user-logon.css",
            "text": css,
        }
    ]

    calls: list[str] = []

    def writer(command: str, timeout: float = 0, max_bytes: int = 0) -> str:
        del timeout, max_bytes
        calls.append(command)
        return ""

    notes = apply_saved_customization(
        writer,
        partition="Common",
        source_name="auth_ad",
        actual="Auth_AD_2",
        agents=[
            {
                "type": "logon-page",
                "name": "auth_ad_act_logon_page_ag",
                "customization_files": saved,
            }
        ],
    )
    assert any("user-logon.css" in note for note in notes)
    assert any(_WWW_TARGET in call and call.startswith("mkdir ") for call in calls)
    assert all(_WWW_SOURCE not in call for call in calls)


def test_load_dialog_puts_web_customizing_above_the_consent() -> None:
    snapshot = MacroSnapshot(
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        agents=[
            {
                "type": "logon-page",
                "name": "auth_ad_act_logon_page_ag",
                "customization_files": [{"name": "user-logon.css", "text": ".a{}"}],
            }
        ],
    )
    profile = AccessProfileRef(
        name="AP",
        partition="Common",
        full_path="/Common/AP",
        policy_path="/Common/AP",
        policy_name="AP",
    )
    dialog = LoadMacroDialog(
        snapshot=snapshot,
        profiles=[profile],
        this_device_connected=True,
        this_host="10.0.0.1",
        this_port=443,
        this_username="admin",
        this_password="secret",
    )
    dialog.show()
    _app.processEvents()
    assert dialog.customizing.text() == "Web Customizing Load"
    assert dialog.customizing.isChecked() is False
    assert dialog.customizing.y() < dialog.confirm.y()
    button = dialog._buttons.button(dialog._buttons.StandardButton.Ok)
    assert button is not None
    dialog.profile_combo.blockSignals(True)
    dialog.profile_combo.setCurrentIndex(1)
    dialog.profile_combo.blockSignals(False)
    dialog.macro_name_edit.setText("Auth_AD")
    dialog._plan = True
    assert button.isEnabled() is False
    dialog.confirm.setChecked(True)
    _app.processEvents()
    assert button.isEnabled() is True
    dialog.customizing.blockSignals(True)
    dialog.customizing.setChecked(True)
    dialog.customizing.blockSignals(False)
    dialog._refresh_enabled()
    assert button.isEnabled() is True
    dialog.confirm.setChecked(False)
    _app.processEvents()
    assert button.isEnabled() is False
    dialog.close()
