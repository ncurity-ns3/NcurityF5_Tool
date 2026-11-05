from typing import Any
import os
import subprocess

import pytest
from pydantic import SecretStr

from app.core.bigip_client import BigipClient, curl_post_detach
from app.core.models import ConnectionProfile, DeviceTarget
from app.core.safety_gate import ChangeModeDisabledError, SafetyGate


def test_post_blocked() -> None:
    profile = ConnectionProfile(
        target=DeviceTarget(label="lab", host="203.0.113.10"),
        username="admin",
        password=SecretStr("x"),
    )
    client = BigipClient(profile, safety_gate=SafetyGate(False))
    with pytest.raises(ChangeModeDisabledError):
        client.post("/tm/ltm/pool", {"name": "t"})


def test_patch_and_put_blocked() -> None:
    profile = ConnectionProfile(
        target=DeviceTarget(label="lab", host="203.0.113.10"),
        username="admin",
        password=SecretStr("x"),
    )
    client = BigipClient(profile, safety_gate=SafetyGate(False))
    with pytest.raises(ChangeModeDisabledError):
        client.patch("/tm/apm/profile/access/~Common~lab", {"generationAction": "increment"})
    with pytest.raises(ChangeModeDisabledError):
        client.put("/tm/apm/policy/policy-item/~Common~lab", {"name": "lab"})


def test_post_via_curl_blocked() -> None:
    profile = ConnectionProfile(
        target=DeviceTarget(label="lab", host="203.0.113.10"),
        username="admin",
        password=SecretStr("x"),
    )
    client = BigipClient(profile, safety_gate=SafetyGate(False))
    with pytest.raises(ChangeModeDisabledError):
        client.post_via_curl("/tm/apm/policy/access-policy/~Common~lab/macros", {"name": "auth_ad"})


def test_curl_post_detach_returns_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None):
            started.append({"target": target, "args": args, "daemon": daemon})

        def start(self) -> None:
            started.append("start")

        def join(self, timeout: float | None = None) -> None:
            raise AssertionError("GUI must not join the curl thread")

    monkeypatch.setattr("app.core.bigip_client.shutil.which", lambda name: r"C:\Windows\System32\curl.exe")
    monkeypatch.setattr("app.core.bigip_client.threading.Thread", _Thread)
    curl_post_detach(
        "https://203.0.113.10/mgmt/tm/apm/policy/access-policy/~Common~p/macros",
        token="tok",
        payload={"name": "auth_ad", "partition": "Common"},
    )
    assert started[-1] == "start"
    assert started[0]["daemon"] is True


def test_spawn_curl_post_uses_file_body_not_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Proc:
        def wait(self, timeout: float | None = None) -> int:
            raise AssertionError("curl must not be waited on")

    def fake_popen(cmd: list[str], **kwargs: Any) -> _Proc:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr("app.core.bigip_client.subprocess.Popen", fake_popen)
    monkeypatch.setattr("app.core.bigip_client.time.sleep", lambda seconds: None)
    from app.core.bigip_client import _spawn_curl_post

    _spawn_curl_post(
        r"C:\Windows\System32\curl.exe",
        "https://203.0.113.10/mgmt/tm/apm/policy/access-policy/~Common~p/macros",
        "tok",
        {"name": "auth_ad", "partition": "Common"},
        True,
    )
    cmd = seen["cmd"]
    assert "--data-binary" in cmd
    data = cmd[cmd.index("--data-binary") + 1]
    assert data.startswith("@")
    assert seen["kwargs"]["stdin"] is not None
    assert seen["kwargs"].get("capture_output") is None
    flags = int(seen["kwargs"].get("creationflags") or 0)
    assert flags & int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)) == 0


def test_curl_util_bash_timeout_does_not_kill_process(monkeypatch: pytest.MonkeyPatch) -> None:
    killed = {"called": False}

    class _Proc:
        returncode = None

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="curl", timeout=timeout or 0)

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            killed["called"] = True

    monkeypatch.setattr("app.core.bigip_client.shutil.which", lambda name: r"C:\Windows\System32\curl.exe")
    monkeypatch.setattr("app.core.bigip_client.subprocess.Popen", lambda *args, **kwargs: _Proc())
    from app.core.bigip_client import curl_util_bash

    with pytest.raises(TimeoutError):
        curl_util_bash(
            "https://203.0.113.10/mgmt/tm/util/bash",
            token="tok",
            shell_command="tmsh -q list sys version",
            timeout=15.0,
        )
    assert killed["called"] is False


def test_curl_util_bash_starts_curl_with_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name != "nt":
        return
    seen: dict[str, Any] = {}

    class _Proc:
        returncode = 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            raise AssertionError("starter must not be killed")

    def fake_popen(cmd: list[str], **kwargs: Any) -> _Proc:
        seen["cmd"] = cmd
        seen["flags"] = int(kwargs.get("creationflags") or 0)
        ps1 = cmd[-1]
        script = open(ps1, encoding="utf-8").read()
        assert "ShowWindow = 0" in script
        assert "Win32_Process" in script
        assert "cmd.exe" not in script.lower()
        base = ps1[: -len(".ps1")]
        line = open(base + ".line", encoding="utf-8").read().lower()
        assert "curl.exe" in line
        assert "cmd.exe" not in line
        with open(base + ".pid", "w", encoding="utf-8") as stream:
            stream.write("4242\n")
        with open(base + ".done", "w", encoding="utf-8") as stream:
            stream.write("0\n")
        with open(base + ".out", "wb") as stream:
            stream.write(b'{"commandResult":"ok"}')
        return _Proc()

    monkeypatch.setattr("app.core.bigip_client.shutil.which", lambda name: r"C:\Windows\System32\curl.exe")
    monkeypatch.setattr("app.core.bigip_client.subprocess.Popen", fake_popen)
    from app.core.bigip_client import curl_util_bash

    text = curl_util_bash(
        "https://203.0.113.10/mgmt/tm/util/bash",
        token="tok",
        shell_command="tmsh -q list sys version",
        timeout=8.0,
    )
    assert text == "ok"
    assert seen["cmd"][0].lower().endswith("powershell.exe")
    assert seen["flags"] & 0x08000000 != 0
    assert seen["flags"] & 0x00000200 == 0


def test_curl_exchange_keeps_password_out_of_the_command_line(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake(cmd: list[str], **kwargs: Any) -> tuple[int, bytes]:
        seen["cmd"] = cmd
        with open(kwargs["body_path"], encoding="utf-8") as stream:
            seen["body"] = stream.read()
        header = cmd[cmd.index("-D") + 1]
        with open(header, "wb") as stream:
            stream.write(b"HTTP/1.1 200 OK\r\n\r\n")
        return 0, b'{"token":{"token":"T"}}'

    monkeypatch.setattr("app.core.bigip_client._find_curl", lambda: r"C:\Windows\System32\curl.exe")
    monkeypatch.setattr("app.core.bigip_client._curl_outside_gui", fake)
    from app.core.bigip_client import curl_exchange

    status, raw = curl_exchange(
        "https://192.0.2.10/mgmt/shared/authn/login",
        method="POST",
        payload={"username": "user", "password": "s3cret"},
    )
    assert status == 200
    assert b"T" in raw
    joined = " ".join(seen["cmd"])
    assert "s3cret" not in joined
    assert "s3cret" in seen["body"]
    assert "--max-filesize" in seen["cmd"]


def test_gui_safe_subprocess_flags_do_not_use_new_process_group() -> None:
    from app.core.bigip_client import _subprocess_gui_safe_flags

    flags = _subprocess_gui_safe_flags()
    if os.name == "nt":
        assert flags & int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)) == 0
        assert flags & 0x08000000 != 0
        assert flags & 0x00000008 == 0
    else:
        assert flags == 0
