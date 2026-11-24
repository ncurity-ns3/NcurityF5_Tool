"""Build Qkview, log tarball, core, and UCS files on the connected BIG-IP."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_CORE_PATH = re.compile(r"^/(?:var/core|shared/core)/[A-Za-z0-9._/-]+$")
_MKU_COMMAND = "f5mku -K 2>&1"
_CORE_LIST_COMMAND = "find /var/core /shared/core -type f 2>/dev/null"
_QKVIEW_DIR = "/var/tmp/qkviews"
_FILE_DIRS = {"/var/tmp", _QKVIEW_DIR, "/var/local/ucs"}


@dataclass(frozen=True)
class Artifact:
    name: str
    status: str
    path: str


def file_host(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", name or "").strip("._")
    return cleaned[:80]


def file_stem(stamp: str, hostname: str) -> str:
    host = file_host(hostname) or "device"
    return f"{stamp}-{host}"


def planned_commands(
    stem: str,
    *,
    qkview: bool,
    logs: bool,
    ucs: bool,
) -> list[tuple[str, str, str]]:
    """(label, remote file name, bash command). UCS also schedules f5mku -K."""
    planned: list[tuple[str, str, str]] = []
    if qkview:
        name = f"{stem}.qkview"
        command = f"mkdir -p {_QKVIEW_DIR} && qkview -f {_QKVIEW_DIR}/{name}"
        planned.append(("Qkview", name, command))
    if logs:
        name = f"{stem}-log-tar.gz"
        command = f"mkdir -p {_QKVIEW_DIR} && tar czf {_QKVIEW_DIR}/{name} /var/log"
        planned.append(("Log Tarball", name, command))
    if ucs:
        name = f"{stem}.ucs"
        planned.append(("UCS", name, f"tmsh save sys ucs {name}"))
        planned.append(("MKU", f"{stem}.mku-K.txt", _MKU_COMMAND))
    return planned


def remove_command(remote_name: str, source_dir: str) -> str:
    if source_dir not in _FILE_DIRS or not remote_name_ok(remote_name):
        raise ValueError("지울 파일 경로가 올바르지 않습니다.")
    return f"rm -f {source_dir}/{remote_name}"


def present_command(remote_name: str, source_dir: str) -> str:
    source = f"{source_dir}/{remote_name}"
    return f"if test -s {source}; then echo OK; else echo MISSING; fi"


def publish_shared_copy(remote_name: str, source_dir: str) -> str:
    if source_dir not in _FILE_DIRS or not remote_name_ok(remote_name):
        raise ValueError("지울 파일 경로가 올바르지 않습니다.")
    source = f"{source_dir}/{remote_name}"
    shared = f"/shared/images/{remote_name}"
    return f"cp -f {source} {shared} && chmod 644 {shared}"


def parse_core_paths(text: str) -> list[str]:
    found: list[str] = []
    for line in (text or "").splitlines():
        path = line.strip()
        if _CORE_PATH.fullmatch(path) and path not in found:
            found.append(path)
    return found


def collect_artifacts(
    client,
    dest: Path,
    *,
    label: str,
    stamp: str,
    qkview: bool,
    logs: bool,
    cores: bool,
    ucs: bool,
    on_progress=None,
) -> list[Artifact]:
    dest.mkdir(parents=True, exist_ok=True)
    stem = file_stem(stamp, _hostname(client) or label)
    steps = planned_commands(stem, qkview=qkview, logs=logs, ucs=ucs)
    if cores:
        steps.append(("Core File Check", "", _CORE_LIST_COMMAND))
    results: list[Artifact] = []
    total = max(len(steps), 1)
    for index, (name, remote_name, command) in enumerate(steps, start=1):
        if on_progress is not None:
            on_progress(int(100 * (index - 1) / total), f"{name} 생성 중")
        if name == "MKU":
            results.append(_save_mku(client, dest, remote_name))
            continue
        if name == "Core File Check":
            results.append(_check_cores(client))
            continue
        results.append(_make_and_download(client, dest, name, remote_name, command))
    if on_progress is not None:
        on_progress(100, "완료")
    return results


def _usable_host(text: str) -> str:
    line = ""
    for raw in (text or "").splitlines():
        item = raw.strip()
        if item:
            line = item
            break
    if not line or any(mark in line for mark in ("<", " ", "=", "/")):
        return ""
    if line.lower() in {"ok", "localhost"}:
        return ""
    return file_host(line)


def _hostname(client) -> str:
    runner = getattr(client, "run_util_bash", None)
    if runner is not None:
        try:
            shell_name = _usable_host(runner('printf %s "$HOSTNAME"', timeout=20.0))
        except Exception:  # noqa: BLE001
            shell_name = ""
        if shell_name:
            return shell_name
    getter = getattr(client, "get_system_info", None)
    if getter is None:
        return ""
    try:
        info = getter()
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(info, dict):
        return str(info.get("hostname") or "")
    return ""


def _delete_ucs(client, remote_name: str) -> None:
    try:
        client.run_util_bash(f"tmsh delete sys ucs {remote_name}", timeout=60.0)
    except Exception:  # noqa: BLE001
        return


def _wait_ucs(client, remote_name: str, timeout: float) -> str:
    """Start tmsh in the background. A direct save often returns an HTML error page."""
    log = f"/var/tmp/ncurity-{remote_name}.log"
    launch = (
        f"rm -f {log}; nohup tmsh save sys ucs {remote_name} >{log} 2>&1 & echo STARTED"
    )
    try:
        client.run_util_bash(launch, timeout=60.0)
    except Exception as exc:  # noqa: BLE001
        return str(exc)[:160]
    deadline = time.time() + timeout
    while time.time() < deadline:
        present = client.run_util_bash(
            present_command(remote_name, "/var/local/ucs"),
            timeout=30.0,
        )
        if "MISSING" not in (present or ""):
            size = _file_size(client, f"/var/local/ucs/{remote_name}")
            if size <= 0:
                return ""
            time.sleep(2)
            if _file_size(client, f"/var/local/ucs/{remote_name}") == size:
                return ""
        else:
            time.sleep(3)
    try:
        note = client.run_util_bash(f"tail -c 300 {log}", timeout=30.0)
    except Exception:  # noqa: BLE001
        note = ""
    text = " ".join((note or "").split())
    if not text or "<html" in text.lower():
        return "tmsh save sys ucs 가 파일을 만들지 못했습니다."
    return text[:160]


def _file_size(client, path: str) -> int:
    text = client.run_util_bash(f"stat -c %s {path}", timeout=30.0)
    token = (text or "").strip().split()[0] if text else ""
    return int(token) if token.isdigit() else 0


def _listing(client, path: str) -> str:
    try:
        text = client.run_util_bash(f"ls -l {path}", timeout=30.0)
    except Exception:  # noqa: BLE001
        return ""
    return " ".join((text or "").split())[:120]


def _try_endpoints(
    client,
    remote_name: str,
    local: Path,
    timeout: float,
    endpoints: tuple[str, ...],
    size: int,
) -> str:
    seen: list[str] = []
    for endpoint in endpoints:
        try:
            client.download_var_tmp_file(
                remote_name,
                local,
                timeout=timeout,
                endpoint=endpoint,
                total_size=size,
            )
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "찾지 못했습니다" not in text:
                raise
            seen.append(f"{endpoint}: {text}")
            continue
        return ""
    return " | ".join(seen)


def _make_and_download(client, dest: Path, name: str, remote_name: str, command: str) -> Artifact:
    timeout = 2400.0 if name == "Qkview" else 1200.0
    source_dir = "/var/local/ucs" if name == "UCS" else _QKVIEW_DIR
    source = f"{source_dir}/{remote_name}"
    local = dest / remote_name
    try:
        if source_dir == _QKVIEW_DIR:
            client.run_util_bash(remove_command(remote_name, "/var/tmp"), timeout=60.0)
        client.run_util_bash(remove_command(remote_name, source_dir), timeout=60.0)
        if name == "UCS":
            _delete_ucs(client, remote_name)
            note = _wait_ucs(client, remote_name, timeout)
            if note:
                detail = f"{source} 파일이 없습니다. {note}".strip()
                return Artifact(name, "실패", detail[:220])
        else:
            client.run_util_bash(command, timeout=timeout)
            present = client.run_util_bash(present_command(remote_name, source_dir), timeout=60.0)
            if "MISSING" in (present or ""):
                return Artifact(name, "실패", f"{source} 파일이 없습니다.")
        client.run_util_bash(f"chmod 644 {source}", timeout=30.0)
        endpoints = ("ucs-downloads",) if name == "UCS" else ("qkview-autodeploy",)
        missed = _try_endpoints(
            client,
            remote_name,
            local,
            timeout,
            endpoints,
            _file_size(client, source),
        )
        if not missed:
            problem = _archive_problem(name, local)
            if problem:
                return Artifact(name, "실패", problem)
            return Artifact(name, "받음", str(local))
        if source_dir != _QKVIEW_DIR:
            listing = _listing(client, source)
            detail = f"장비에서 파일을 찾지 못했습니다. ({missed}) {listing}"
            return Artifact(name, "실패", detail[:220])
        client.run_util_bash(publish_shared_copy(remote_name, source_dir), timeout=timeout)
        try:
            missed = _try_endpoints(
                client,
                remote_name,
                local,
                timeout,
                ("image-downloads",),
                _file_size(client, source),
            )
        finally:
            client.run_util_bash(f"rm -f /shared/images/{remote_name}", timeout=60.0)
        if not missed:
            problem = _archive_problem(name, local)
            if problem:
                return Artifact(name, "실패", problem)
            return Artifact(name, "받음", str(local))
        listing = _listing(client, source)
        tried = "qkview-autodeploy, image-downloads"
        detail = f"장비에서 파일을 찾지 못했습니다. ({tried}) {listing}"
        return Artifact(name, "실패", detail[:220])
    except Exception as exc:  # noqa: BLE001
        return Artifact(name, "실패", str(exc)[:220])


def _archive_problem(name: str, path: Path) -> str:
    try:
        size = path.stat().st_size
        if size < 64:
            return ""
        with path.open("rb") as handle:
            head = handle.read(4)
            handle.seek(max(0, size - 66000))
            tail = handle.read()
    except OSError:
        return ""
    if name == "Qkview" and head == b"PK\x03\x04" and b"PK\x05\x06" not in tail:
        return "Qkview 압축이 끝까지 받아지지 않았습니다."
    if name == "Log Tarball" and head != b"\x1f\x8b":
        return "로그 압축이 끝까지 받아지지 않았습니다."
    return ""


def _save_mku(client, dest: Path, filename: str) -> Artifact:
    local = dest / filename
    try:
        body = client.run_util_bash(_MKU_COMMAND, timeout=120.0)
    except Exception as exc:  # noqa: BLE001
        return Artifact("MKU", "실패", str(exc)[:180])
    local.write_text(body or "", encoding="utf-8")
    if not (body or "").strip():
        return Artifact("MKU", "출력 없음", str(local))
    return Artifact("MKU", "저장됨", str(local))


def _check_cores(client) -> Artifact:
    try:
        listing = client.run_util_bash(_CORE_LIST_COMMAND, timeout=60.0)
    except Exception as exc:  # noqa: BLE001
        return Artifact("Core File Check", "실패", str(exc)[:180])
    paths = parse_core_paths(listing)
    if not paths:
        return Artifact("Core File Check", "없음", "")
    return Artifact("Core File Check", "있음", "\n".join(paths))


def remote_name_ok(name: str) -> bool:
    return bool(_SAFE_NAME.fullmatch(name or ""))
