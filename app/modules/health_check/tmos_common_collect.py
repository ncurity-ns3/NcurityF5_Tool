from __future__ import annotations

import re
import threading
import time

_ucs_log_lock = threading.Lock()
from datetime import date, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

import httpx

UCS_SAVE_BASH_SYNC_TIMEOUT = 180.0
UCS_POLL_MAX = 1200.0
UCS_REST_POST_TIMEOUT = 120.0
UCS_REST_DISK_WAIT = 45.0
# VE/rSeries에서 POST /tm/sys/ucs 가 400인 경우가 많아 tmsh save만 사용
UCS_TRY_REST_FIRST = False

from app.core.bigip_client import BigipClient
from app.core.models import ConnectionProfile
from app.core.safety_gate import SafetyGate

# 정기점검 표 우측 TMOS 명령 → iControl POST /mgmt/tm/util/bash
_BASH_COMMANDS: dict[str, str] = {
    "uptime": "uptime",
    "hardware": "tmsh show sys hardware",
    "vlan_list": "tmsh list net vlan",
    "interfaces": "tmsh show net interface",
    "ntp": "ntpq -np 2>/dev/null",
    "clock": "date; echo '---F5TOOL_CLOCK---'; clock",
    "disk": "df -h",
    "services": "tmsh show sys service",
    "performance": "tmsh show sys performance",
    "certs": (
        "tmsh run /sys crypto check-cert 2>/dev/null "
        "| grep -e expire | grep -v ca-bundle"
    ),
    "failover": (
        "tmsh show sys failover 2>/dev/null; "
        "echo '---F5TOOL_HA---'; "
        "tmsh show cm failover-status 2>/dev/null"
    ),
}


def _collection_meta(client: BigipClient) -> dict[str, str]:
    host = client.profile.target.host
    hostname = ""
    try:
        info = client.get_system_info()
        if isinstance(info, dict):
            hostname = str(info.get("hostname", "") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return {
        "tmos_host": host,
        "hostname": hostname.split(".")[0] if hostname else "",
    }


def collect_tmos_common(
    client: BigipClient,
    *,
    ucs_backup_pending: bool = False,
    device_label: str = "",
) -> dict[str, Any]:
    """Bash-first collection; REST only supplements NTP server count when needed."""
    out: dict[str, Any] = {"_meta": _collection_meta(client)}

    if ucs_backup_pending:
        meta = out.get("_meta") if isinstance(out.get("_meta"), dict) else {}
        out["backup_action"] = _deferred_backup_action(
            str(meta.get("hostname", "")),
            device_label=device_label,
        )
    else:
        out["backup_action"] = {
            "performed": False,
            "skipped": True,
            "detail": "«점검 시 UCS 백업 수행» 미체크 — 정상",
        }

    for key, cmd in _BASH_COMMANDS.items():
        try:
            timeout = 300.0 if key == "certs" else None
            stdout = client.run_util_bash(cmd, timeout=timeout)
            text = (stdout or "").strip()
            if not text or "syntax error" in text.lower():
                out[key] = {
                    "_unavailable": True,
                    "_bash_cmd": cmd,
                    "_bash_error": text[:300] or "empty commandResult",
                }
            else:
                out[key] = {"bash_stdout": text, "_source": "bash", "_bash_cmd": cmd}
        except Exception as exc:  # noqa: BLE001
            out[key] = {
                "_unavailable": True,
                "_bash_cmd": cmd,
                "_bash_error": str(exc)[:300],
            }

    # NTP: enrich from REST if bash did not list servers
    ntp_block = out.get("ntp", {})
    if isinstance(ntp_block, dict) and ntp_block.get("_unavailable"):
        rest_ntp = client.get_optional("/tm/sys/ntp")
        if not rest_ntp.get("_unavailable"):
            out["ntp_rest"] = rest_ntp

    return out


def _sanitize_hostname(name: str) -> str:
    host = str(name or "").split(".")[0].strip()
    host = re.sub(r"[^a-zA-Z0-9_-]+", "_", host)[:40]
    return host


_BAD_UCS_HOSTS = frozenset({"", "bigip", "localhost", "local"})


def _resolve_ucs_hostname(
    client: BigipClient,
    *,
    hostname_hint: str,
    device_label: str = "",
) -> str:
    """Prefer collected hostname; never save as localhost if avoidable."""
    host = _sanitize_hostname(hostname_hint)
    if host.lower() in _BAD_UCS_HOSTS:
        host = _hostname_for_backup(client)
    if host.lower() in _BAD_UCS_HOSTS:
        host = _sanitize_hostname(device_label)
    if host.lower() in _BAD_UCS_HOSTS:
        host = "bigip"
    return host


def _wait_ucs_on_disk(
    client: BigipClient,
    stamp: str,
    host: str,
    *,
    max_wait: float = 300.0,
    interval: float = 15.0,
    ucs_log_path: str | None = None,
    label: str = "",
    host_ip: str = "",
    on_tick: Callable[[str], None] | None = None,
) -> str:
    """UCS save can return HTTP 500 while gzip still runs — poll for the file."""
    start = time.time()
    deadline = start + max_wait
    last_beat = start
    while time.time() < deadline:
        found = _probe_ucs_on_disk(client, stamp, host)
        if found:
            return found
        now = time.time()
        if now - last_beat >= 30.0:
            elapsed = int(now - start)
            mins, secs = divmod(elapsed, 60)
            stamp_txt = f"{mins}분 {secs}초" if mins else f"{secs}초"
            _append_ucs_log(
                ucs_log_path,
                f"[{label}@{host_ip}] /var/local/ucs 대기 중… ({stamp_txt})",
            )
            if on_tick:
                on_tick(f"파일 대기 {stamp_txt}")
            last_beat = now
        time.sleep(interval)
    return ""


def _hostname_for_backup(client: BigipClient) -> str:
    try:
        gs = client.get_system_info()
        host = _sanitize_hostname(str(gs.get("hostname", "")))
        return host or "bigip"
    except Exception:  # noqa: BLE001
        return "bigip"


def _ucs_basename(stamp: str, host: str) -> str:
    return f"{stamp}-{_sanitize_hostname(host) or 'bigip'}.ucs"


def _ucs_cleanup_command(stamp: str, host: str) -> str:
    """Remove only the target UCS archive (tmsh — no shell rm)."""
    safe = _sanitize_hostname(host) or "bigip"
    basename = _ucs_basename(stamp, safe)
    return f"tmsh delete sys ucs {basename}"


def _ucs_save_command(stamp: str, host: str) -> str:
    """tmsh save sys ucs YYYYMMDD-HOSTNAME — 단일 명령만 (rm glob 시 util/bash 400 방지)."""
    safe = _sanitize_hostname(host)
    if safe and safe != "bigip":
        return f"tmsh save sys ucs {stamp}-{safe}"
    return (
        "H=$(tmsh list /sys global-settings hostname one-line 2>/dev/null | "
        "awk 'NF{print $NF; exit}'); "
        "H=${H%%.*}; "
        "H=$(echo \"$H\" | tr -cd '[:alnum:]_-' | cut -c1-40); "
        "test -n \"$H\" || H=bigip; "
        f"tmsh save sys ucs {stamp}-${{H}}"
    )


def _bash_http_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = (exc.response.text or "")[:200]
    except Exception:  # noqa: BLE001
        body = ""
    return f"HTTP {exc.response.status_code}{(': ' + body) if body else ''}"


def _find_ucs_in_stdout(stdout: str, stamp: str, host: str) -> str:
    expect = _ucs_basename(stamp, host)
    if expect in stdout:
        return expect
    m = re.search(rf"({re.escape(stamp)}[-_][\w.-]+\.ucs)", stdout, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(\d{8}[-_][\w.-]+\.ucs)", stdout, re.I)
    return m.group(1) if m else ""


def _probe_ucs_on_disk(client: BigipClient, stamp: str, host: str) -> str:
    """After util/bash 500, check whether save sys ucs actually completed."""
    safe = _sanitize_hostname(host) or "bigip"
    probe = (
        f"ls -1 /var/local/ucs/{stamp}-{safe}.ucs 2>/dev/null; "
        f"ls -1t /var/local/ucs/{stamp}-*.ucs 2>/dev/null | head -1"
    )
    try:
        out = client.run_util_bash(probe, timeout=60.0)
        for line in out.splitlines():
            line = line.strip()
            if line.endswith(".ucs") and stamp in line:
                return line.rsplit("/", 1)[-1]
    except Exception:  # noqa: BLE001
        pass
    return ""


def _run_ucs_bash(
    client: BigipClient, cmd: str, *, timeout: float = 300.0, retries: int = 3
) -> str:
    """util/bash — 400/5xx 시 짧은 대기 후 재시도 (이전 bash·UCS 경합 완화)."""
    retry_codes = {400, 429, 500, 502, 503, 504}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return client.run_util_bash(cmd, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in retry_codes and attempt < retries - 1:
                time.sleep(3.0 * (attempt + 1))
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2.0)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("UCS bash failed")


def _run_ucs_bash_with_progress(
    client: BigipClient,
    cmd: str,
    *,
    timeout: float,
    ucs_log_path: str | None,
    label: str,
    host_ip: str,
    on_tick: Callable[[str], None] | None = None,
    log_label: str = "UCS",
) -> str:
    """Long-running bash — heartbeat log + GUI tick every 30s."""
    stop = threading.Event()
    start = time.time()

    def _beat() -> None:
        while not stop.wait(30.0):
            elapsed = int(time.time() - start)
            mins, secs = divmod(elapsed, 60)
            stamp = f"{mins}분 {secs}초" if mins else f"{secs}초"
            _append_ucs_log(
                ucs_log_path,
                f"[{label}@{host_ip}] {log_label} 진행 중… ({stamp} 경과)",
            )
            if on_tick:
                on_tick(f"저장 중 {stamp}")

    beat_thread = threading.Thread(target=_beat, name="ucs-bash-heartbeat", daemon=True)
    beat_thread.start()
    try:
        return _run_ucs_bash(client, cmd, timeout=timeout)
    finally:
        stop.set()
        beat_thread.join(timeout=2.0)


def _append_ucs_log(log_path: str | None, line: str) -> None:
    if not log_path:
        return
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _ucs_log_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line.rstrip() + "\n")
                fh.flush()
    except OSError:
        pass


def _deferred_backup_action(
    hostname_hint: str, *, device_label: str = ""
) -> dict[str, Any]:
    host = _sanitize_hostname(hostname_hint)
    if host.lower() in _BAD_UCS_HOSTS:
        host = _sanitize_hostname(device_label)
    if host.lower() in _BAD_UCS_HOSTS:
        host = "bigip"
    stamp = date.today().strftime("%Y%m%d")
    expected = _ucs_basename(stamp, host)
    return {
        "performed": False,
        "scheduled": True,
        "filename": expected,
        "detail": "전체 점검·리포트 완료 후 백그라운드 UCS 예정 (ucs_backup.log)",
    }


def _ucs_backup_worker(
    connection: ConnectionProfile,
    *,
    ucs_log_path: str | None,
    device_label: str,
    hostname_hint: str,
    on_tick: Callable[[str], None] | None = None,
) -> None:
    label = device_label or connection.target.label
    host_ip = connection.target.host
    stamp = date.today().strftime("%Y%m%d")
    started = datetime.now().isoformat(timespec="seconds")
    _append_ucs_log(
        ucs_log_path,
        f"[{started}] {label}@{host_ip} UCS deferred start",
    )
    try:
        bg_client = BigipClient(connection)
        bg_client.authenticate()
        _append_ucs_log(ucs_log_path, f"[{label}@{host_ip}] UCS authenticated")
        host = _resolve_ucs_hostname(
            bg_client, hostname_hint=hostname_hint, device_label=label
        )
        expected = _ucs_basename(stamp, host)
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] UCS target file: {expected}",
        )
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] UCS save start (REST→background bash→"
            f"disk poll, 장비당 최대 {int(UCS_POLL_MAX // 60)}분)",
        )
        result = _run_ucs_backup(
            bg_client,
            hostname_hint=host,
            device_label=label,
            ucs_log_path=ucs_log_path,
            label=label,
            host_ip=host_ip,
            on_tick=on_tick,
        )
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] UCS save returned ok={result.get('ok')} "
            f"method={result.get('method', '?')}",
        )
        status = "OK" if result.get("ok") else "FAIL"
        fname = result.get("filename", expected)
        extra = ""
        on_disk = _probe_ucs_on_disk(bg_client, stamp, host)
        if not on_disk and status == "OK":
            on_disk = _wait_ucs_on_disk(bg_client, stamp, host, max_wait=90.0, interval=15.0)
        elif not on_disk:
            on_disk = _probe_ucs_on_disk(bg_client, stamp, host)
        if on_disk:
            status = "OK"
            fname = on_disk
        elif status == "OK":
            status = "FAIL"
            extra = "save 응답은 성공이나 /var/local/ucs 에 파일 없음"
        else:
            extra = str(
                result.get("error")
                or result.get("detail")
                or result.get("method")
                or ""
            )
        method = str(result.get("method") or "?")
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] UCS {status} ({method}): {fname}"
            + (f" — {str(extra)[:160]}" if extra else ""),
        )
    except Exception as exc:  # noqa: BLE001
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] UCS FAIL: {str(exc)[:200]}",
        )


def _ucs_result_from_disk(
    client: BigipClient,
    stamp: str,
    host: str,
    expected: str,
    *,
    method: str,
    detail: str,
    command: str = "",
    max_disk_wait: float = 180.0,
    ucs_log_path: str | None = None,
    label: str = "",
    host_ip: str = "",
    on_tick: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    saved = _probe_ucs_on_disk(client, stamp, host)
    if not saved:
        saved = _wait_ucs_on_disk(
            client,
            stamp,
            host,
            max_wait=max_disk_wait,
            ucs_log_path=ucs_log_path,
            label=label,
            host_ip=host_ip,
            on_tick=on_tick,
        )
    ok = bool(saved)
    return {
        "performed": True,
        "ok": ok,
        "filename": saved or expected,
        "command": command,
        "method": method,
        "detail": detail if ok else f"{detail} — 파일 미확인",
    }


def _log_ha_hint(
    client: BigipClient,
    *,
    ucs_log_path: str | None,
    label: str,
    host_ip: str,
) -> None:
    try:
        out = client.run_util_bash(
            "tmsh show cm failover-status 2>/dev/null | head -25",
            timeout=45.0,
        )
        low = out.lower()
        if "standby" in low or "force offline" in low:
            snippet = " ".join(out.split())[:120]
            _append_ucs_log(
                ucs_log_path,
                f"[{label}@{host_ip}] HA 상태: {snippet}",
            )
    except Exception:  # noqa: BLE001
        pass


def _run_ucs_save_rest(
    client: BigipClient,
    *,
    stamp: str,
    host: str,
    expected: str,
    ucs_log_path: str | None = None,
    label: str = "",
    host_ip: str = "",
    on_tick: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """POST /tm/sys/ucs — quick probe only; 실패 시 tmsh save로 넘김 (rSeries 400 등)."""
    disk_kw = {
        "ucs_log_path": ucs_log_path,
        "label": label,
        "host_ip": host_ip,
        "on_tick": on_tick,
        "max_disk_wait": UCS_REST_DISK_WAIT,
    }
    try:
        client.save_sys_ucs(expected, timeout=UCS_REST_POST_TIMEOUT)
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] REST POST 수락 — 디스크 확인 "
            f"(최대 {int(UCS_REST_DISK_WAIT)}초)",
        )
        result = _ucs_result_from_disk(
            client,
            stamp,
            host,
            expected,
            method="rest",
            detail="POST /tm/sys/ucs command=save",
            **disk_kw,
        )
        if not result.get("ok"):
            result["detail"] = (
                f"{result.get('detail', '')} — tmsh save(sys ucs)로 재시도 예정"
            )
        return result
    except httpx.HTTPStatusError as exc:
        detail = _bash_http_detail(exc)
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] REST 실패 ({detail}) — tmsh save로 진행",
        )
        return {
            "performed": True,
            "ok": False,
            "filename": expected,
            "method": "rest",
            "error": detail[:300],
        }
    except Exception as exc:  # noqa: BLE001
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] REST 예외: {str(exc)[:120]} — tmsh save로 진행",
        )
        return {
            "performed": True,
            "ok": False,
            "filename": expected,
            "method": "rest",
            "error": str(exc)[:300],
        }


def _run_ucs_save_async_bash(
    client: BigipClient,
    *,
    stamp: str,
    host: str,
    expected: str,
    ucs_log_path: str | None = None,
    label: str = "",
    host_ip: str = "",
) -> dict[str, Any]:
    """Fire tmsh save in background — util/bash returns quickly; poll disk after."""
    safe = _sanitize_hostname(host) or "bigip"
    basename = _ucs_basename(stamp, safe)
    _log_ha_hint(client, ucs_log_path=ucs_log_path, label=label, host_ip=host_ip)
    try:
        del_cmd = _ucs_cleanup_command(stamp, host)
        _append_ucs_log(
            ucs_log_path,
            f"[{label}@{host_ip}] UCS cleanup: {del_cmd}",
        )
        _run_ucs_bash(client, del_cmd, timeout=45.0, retries=1)
    except Exception:  # noqa: BLE001
        pass
    cmd = (
        f"nohup tmsh save sys ucs {basename} "
        f">/var/tmp/f5tool-ucs-save.log 2>&1 & sleep 1; "
        "echo F5TOOL_UCS_BG_STARTED"
    )
    _append_ucs_log(
        ucs_log_path,
        f"[{label}@{host_ip}] UCS background tmsh save ({basename})",
    )
    try:
        out = _run_ucs_bash(client, cmd, timeout=90.0, retries=2)
        started = "F5TOOL_UCS_BG_STARTED" in out
        return {
            "performed": True,
            "started": started,
            "ok": False,
            "filename": expected,
            "command": cmd,
            "method": "bash-bg",
            "detail": out[:300],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "performed": True,
            "started": False,
            "ok": False,
            "filename": expected,
            "method": "bash-bg",
            "error": str(exc)[:300],
        }


def _run_ucs_save_bash(
    client: BigipClient,
    *,
    stamp: str,
    host: str,
    expected: str,
    ucs_log_path: str | None = None,
    label: str = "",
    host_ip: str = "",
    on_tick: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    cleanup = _ucs_cleanup_command(stamp, host)
    cmd = _ucs_save_command(stamp, host)
    try:
        try:
            _run_ucs_bash(client, cleanup, timeout=60.0, retries=2)
        except Exception:  # noqa: BLE001
            pass
        stdout = _run_ucs_bash_with_progress(
            client,
            cmd,
            timeout=UCS_SAVE_BASH_SYNC_TIMEOUT,
            ucs_log_path=ucs_log_path,
            label=label,
            host_ip=host_ip,
            on_tick=on_tick,
            log_label="tmsh save sys ucs",
        )
        low = stdout.lower()
        ok = "error" not in low and "fail" not in low and "denied" not in low
        saved = _find_ucs_in_stdout(stdout, stamp, host)
        if not saved:
            saved = _probe_ucs_on_disk(client, stamp, host) or _wait_ucs_on_disk(
                client, stamp, host
            )
        return {
            "performed": True,
            "ok": ok or bool(saved),
            "filename": saved or expected,
            "command": cmd,
            "method": "bash",
            "detail": "util/bash tmsh save sys ucs",
            "stdout": stdout[:2000],
        }
    except httpx.HTTPStatusError as exc:
        result = _ucs_result_from_disk(
            client,
            stamp,
            host,
            expected,
            method="bash",
            detail=f"bash HTTP {exc.response.status_code}",
            command=cmd,
        )
        if result.get("ok"):
            return result
        return {
            "performed": True,
            "ok": False,
            "filename": expected,
            "command": cmd,
            "method": "bash",
            "error": _bash_http_detail(exc)[:300],
        }
    except Exception as exc:  # noqa: BLE001
        result = _ucs_result_from_disk(
            client,
            stamp,
            host,
            expected,
            method="bash",
            detail=f"bash 예외: {str(exc)[:80]}",
            command=cmd,
        )
        if result.get("ok"):
            return result
        return {
            "performed": True,
            "ok": False,
            "filename": expected,
            "command": cmd,
            "method": "bash",
            "error": str(exc)[:300],
        }


def _run_ucs_backup(
    client: BigipClient,
    *,
    hostname_hint: str = "",
    device_label: str = "",
    ucs_log_path: str | None = None,
    label: str = "",
    host_ip: str = "",
    on_tick: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    client.safety_gate = SafetyGate(change_mode_enabled=True)
    host = _resolve_ucs_hostname(
        client, hostname_hint=hostname_hint, device_label=device_label
    )
    stamp = date.today().strftime("%Y%m%d")
    expected = _ucs_basename(stamp, host)
    lbl = label or device_label
    poll_kw = {
        "ucs_log_path": ucs_log_path,
        "label": lbl,
        "host_ip": host_ip,
        "on_tick": on_tick,
    }

    def ulog(msg: str) -> None:
        _append_ucs_log(ucs_log_path, f"[{lbl}@{host_ip}] {msg}")

    rest_result: dict[str, Any] | None = None
    if UCS_TRY_REST_FIRST:
        ulog("UCS: REST POST /tm/sys/ucs save 시도")
        rest_result = _run_ucs_save_rest(
            client,
            stamp=stamp,
            host=host,
            expected=expected,
            **poll_kw,
        )
        if rest_result and rest_result.get("ok"):
            return rest_result
        if rest_result and rest_result.get("error"):
            ulog(f"REST 미완료: {str(rest_result.get('error'))[:160]}")
    else:
        ulog("UCS: tmsh save (REST 생략 — util/bash background)")

    ulog("UCS: background tmsh save (util/bash 즉시 반환)")
    async_result = _run_ucs_save_async_bash(
        client,
        stamp=stamp,
        host=host,
        expected=expected,
        ucs_log_path=ucs_log_path,
        label=lbl,
        host_ip=host_ip,
    )
    if async_result.get("started"):
        saved = _wait_ucs_on_disk(
            client, stamp, host, max_wait=UCS_POLL_MAX, **poll_kw
        )
        if saved:
            return {
                "performed": True,
                "ok": True,
                "filename": saved,
                "method": "bash-bg",
                "detail": "nohup tmsh save + disk 확인",
            }

    ulog(
        f"UCS: sync bash fallback (최대 {int(UCS_SAVE_BASH_SYNC_TIMEOUT // 60)}분)"
    )
    bash_result = _run_ucs_save_bash(
        client,
        stamp=stamp,
        host=host,
        expected=expected,
        ucs_log_path=ucs_log_path,
        label=lbl,
        host_ip=host_ip,
        on_tick=on_tick,
    )
    if bash_result.get("ok"):
        return bash_result
    if rest_result and rest_result.get("performed"):
        return rest_result
    return bash_result
