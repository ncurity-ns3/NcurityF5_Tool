from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

import httpx

from app.core.models import ConnectionProfile, OperationClass
from app.core.redaction import redact_data, redact_string
from app.core.safety_gate import SafetyGate

_BASH_DEFAULT_MAX_BYTES = 1_048_576
_CREATE_NO_WINDOW = 0x08000000
_CREATE_BREAKAWAY_FROM_JOB = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)


def _subprocess_gui_safe_flags() -> int:
    """Run curl with no console window.

    CREATE_NO_WINDOW never creates a console, so no CMD window appears.
    Do not use CREATE_NEW_PROCESS_GROUP: signalling that group has closed the GUI.
    """
    if os.name != "nt":
        return 0
    return int(_CREATE_NO_WINDOW) | int(_CREATE_BREAKAWAY_FROM_JOB)


def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def _popen_detached(cmd: list[str]) -> subprocess.Popen[bytes]:
    """Start curl outside the GUI process group. A child fault must not exit the exe."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "startupinfo": _hidden_startupinfo(),
        "creationflags": _subprocess_gui_safe_flags(),
    }
    try:
        return subprocess.Popen(cmd, **kwargs)
    except OSError:
        if os.name != "nt":
            raise
        kwargs["creationflags"] = int(_CREATE_NO_WINDOW)
        return subprocess.Popen(cmd, **kwargs)


def _httpx_read_timeout(read_seconds: float) -> httpx.Timeout:
    """Explicit read cap — avoids util/bash POST hanging with no TMOS activity."""
    return httpx.Timeout(connect=15.0, read=read_seconds, write=15.0, pool=15.0)


def _read_response_capped(response: httpx.Response, max_bytes: int | None) -> bytes:
    if max_bytes is None:
        return response.read()
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=4_096):
        if not chunk:
            continue
        remaining = max_bytes - total
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    return raw


def _find_curl() -> str | None:
    found = shutil.which("curl.exe") or shutil.which("curl")
    if found:
        return found
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidate = os.path.join(windir, "System32", "curl.exe")
    if os.path.isfile(candidate):
        return candidate
    return None


def curl_post_detach(
    url: str,
    *,
    token: str,
    payload: dict[str, Any],
    insecure: bool = True,
) -> None:
    """Return immediately. curl is started on a daemon thread so the GUI never waits."""
    curl = _find_curl()
    if not curl:
        raise RuntimeError("curl를 찾을 수 없어 Access Policy 연결을 중단했습니다.")
    worker = threading.Thread(
        target=_spawn_curl_post,
        args=(curl, url, token, payload, insecure),
        daemon=True,
    )
    worker.start()


def _spawn_curl_post(
    curl: str,
    url: str,
    token: str,
    payload: dict[str, Any],
    insecure: bool,
) -> None:
    handle, body_path = tempfile.mkstemp(prefix="ncurity_attach_", suffix=".json")
    os.close(handle)
    try:
        with open(body_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"))
        cmd = [
            curl,
            "-sS",
            "-o",
            os.devnull,
            "--max-time",
            "8",
            "-X",
            "POST",
            "-H",
            f"X-F5-Auth-Token: {token}",
            "-H",
            "Content-Type: application/json",
            "-H",
            "Connection: close",
            "--data-binary",
            f"@{body_path}",
            url,
        ]
        if insecure:
            cmd.insert(2, "-k")
        _popen_detached(cmd)
        time.sleep(20)
    except Exception:
        return
    finally:
        try:
            os.remove(body_path)
        except OSError:
            pass


def _win_quote(text: str) -> str:
    return '"' + str(text).replace('"', "") + '"'


def _ps_literal(path: str) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _wait_done_file(
    done_path: str, timeout: float, starter: subprocess.Popen[bytes] | None = None
) -> int:
    """Read an exit code written by the helper. Do not open or wait on curl."""
    deadline = time.time() + max(float(timeout), 1.0)
    while time.time() < deadline:
        text = ""
        try:
            with open(done_path, encoding="ascii", errors="replace") as stream:
                text = stream.read().strip()
        except OSError:
            text = ""
        if text:
            token = text.split()[0]
            try:
                return int(token)
            except ValueError:
                return 0
        if starter is not None:
            code = starter.poll()
            if code not in (None, 0):
                raise RuntimeError(f"curl를 시작하지 못했습니다 ({code}).")
        time.sleep(0.25)
    raise TimeoutError(f"timeout: tmsh 응답이 없습니다 ({timeout:.0f}초)")


def _curl_outside_gui(
    cmd: list[str],
    *,
    timeout: float,
    out_path: str,
    body_path: str,
    max_bytes: int | None,
) -> tuple[int, bytes]:
    """Start curl.exe with no console, parented by WMI, not by this GUI."""
    line_path = body_path + ".line"
    ps1_path = body_path + ".ps1"
    pid_path = body_path + ".pid"
    done_path = body_path + ".done"
    seconds = max(1, int(timeout) + 2)
    command_line = " ".join(_win_quote(part) for part in cmd)
    with open(line_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(command_line)
    with open(ps1_path, "w", encoding="utf-8", newline="\r\n") as stream:
        stream.write(
            f"$line = (Get-Content -LiteralPath {_ps_literal(line_path)} -Raw).Trim()\r\n"
            "$startup = ([wmiclass]'Win32_ProcessStartup').CreateInstance()\r\n"
            "$startup.ShowWindow = 0\r\n"
            "$created = ([wmiclass]'Win32_Process').Create($line, $null, $startup)\r\n"
            f"Set-Content -LiteralPath {_ps_literal(pid_path)} -Value $created.ProcessId\r\n"
            "if ($created.ReturnValue -ne 0) {\r\n"
            f"  Set-Content -LiteralPath {_ps_literal(done_path)} -Value 2\r\n"
            "  exit 2\r\n"
            "}\r\n"
            f"$limit = (Get-Date).AddSeconds({seconds})\r\n"
            "$code = 259\r\n"
            "try { $proc = Get-Process -Id $created.ProcessId -ErrorAction Stop } catch { $proc = $null }\r\n"
            "if ($null -eq $proc) {\r\n"
            "  $code = 0\r\n"
            "} else {\r\n"
            "  $remaining = [int](($limit - (Get-Date)).TotalMilliseconds)\r\n"
            "  if ($remaining -lt 200) { $remaining = 200 }\r\n"
            "  $waited = $false\r\n"
            "  try { $waited = $proc.WaitForExit($remaining) } catch { $waited = $false }\r\n"
            "  if ($waited) {\r\n"
            "    try { $code = [int]$proc.ExitCode } catch { $code = 0 }\r\n"
            "  } else {\r\n"
            "    while ((Get-Date) -lt $limit) {\r\n"
            "      $still = Get-Process -Id $created.ProcessId -ErrorAction SilentlyContinue\r\n"
            "      if (-not $still) { $code = 0; break }\r\n"
            "      Start-Sleep -Milliseconds 300\r\n"
            "    }\r\n"
            "  }\r\n"
            "}\r\n"
            f"Set-Content -LiteralPath {_ps_literal(done_path)} -Value $code\r\n"
        )
    powershell = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    starter = subprocess.Popen(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps1_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=_hidden_startupinfo(),
        creationflags=int(_CREATE_NO_WINDOW) if os.name == "nt" else 0,
    )
    completed = 1
    raw = b""
    try:
        completed = _wait_done_file(done_path, timeout + 5.0, starter)
        if completed in (2, 259):
            raise TimeoutError(f"timeout: tmsh 응답이 없습니다 ({timeout:.0f}초)")
        try:
            with open(out_path, "rb") as stream:
                raw = stream.read(max_bytes if max_bytes else _BASH_DEFAULT_MAX_BYTES)
        except OSError:
            raw = b""
    finally:
        try:
            starter.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        for path in (line_path, ps1_path, pid_path, done_path, body_path, out_path):
            try:
                os.remove(path)
            except OSError:
                pass
    return completed, raw


def _http_status_from_dump(header_path: str) -> int:
    try:
        with open(header_path, "rb") as stream:
            line = stream.readline()
    except OSError:
        return 0
    parts = line.decode("ascii", errors="replace").split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def curl_exchange(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    max_bytes: int = 1_500_000,
) -> tuple[int, bytes]:
    """HTTP through curl.exe. The GUI process only reads the result file."""
    curl = _find_curl()
    if not curl:
        raise RuntimeError("curl를 찾을 수 없습니다.")
    handle, body_path = tempfile.mkstemp(prefix="ncurity_http_", suffix=".json")
    os.close(handle)
    out_path = body_path + ".out"
    header_path = body_path + ".hdr"
    cap = timeout if timeout and timeout > 0 else 20.0
    cmd = [
        curl,
        "-sS",
        "-k",
        "-o",
        out_path,
        "-D",
        header_path,
        "--max-time",
        str(max(1, int(cap))),
        "--max-filesize",
        str(max(1024, int(max_bytes))),
        "-X",
        method.upper(),
        "-H",
        "Connection: close",
    ]
    for key, value in (headers or {}).items():
        cmd.extend(["-H", f"{key}: {value}"])
    if payload is not None:
        with open(body_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"))
        cmd.extend(["-H", "Content-Type: application/json", "--data-binary", f"@{body_path}"])
    cmd.append(url)
    try:
        if os.name == "nt":
            code, raw = _curl_outside_gui(
                cmd,
                timeout=cap,
                out_path=out_path,
                body_path=body_path,
                max_bytes=max_bytes,
            )
        else:
            proc = _popen_detached(cmd)
            try:
                proc.wait(timeout=cap + 3.0)
            except subprocess.TimeoutExpired:
                raise TimeoutError("연결 시간 초과. MGMT IP/Port를 확인하세요.") from None
            code = int(proc.returncode or 0)
            try:
                with open(out_path, "rb") as stream:
                    raw = stream.read(max_bytes)
            except OSError:
                raw = b""
        status = _http_status_from_dump(header_path)
        if code == 63:
            raise RuntimeError("Access Profile 응답이 커서 읽기를 중단했습니다.")
        if code not in (0, None) and not raw:
            raise TimeoutError("연결 시간 초과. MGMT IP/Port를 확인하세요.")
        return status, raw
    except TimeoutError:
        raise TimeoutError("연결 시간 초과. MGMT IP/Port를 확인하세요.") from None
    finally:
        for path in (header_path, body_path, out_path):
            try:
                os.remove(path)
            except OSError:
                pass


def curl_util_bash(
    url: str,
    *,
    token: str,
    shell_command: str,
    timeout: float,
    insecure: bool = True,
    basic: tuple[str, str] | None = None,
    max_bytes: int | None = None,
) -> str:
    """Run /tm/util/bash in a separate curl process. Do not kill curl — that can exit the GUI."""
    curl = _find_curl()
    if not curl:
        raise RuntimeError("curl를 찾을 수 없어 tmsh를 실행하지 않습니다.")
    escaped = shell_command.replace("'", "'\"'\"'")
    payload = {"command": "run", "utilCmdArgs": f"-c '{escaped}'"}
    handle, body_path = tempfile.mkstemp(prefix="ncurity_bash_", suffix=".json")
    os.close(handle)
    out_path = f"{body_path}.out"
    cap = timeout if timeout and timeout > 0 else 15.0
    cmd = [
        curl,
        "-sS",
        "-o",
        out_path,
        "--max-time",
        str(max(1, int(cap))),
    ]
    if insecure:
        cmd.append("-k")
    cmd.extend(["-X", "POST"])
    if basic:
        cmd.extend(["-u", f"{basic[0]}:{basic[1]}"])
    elif token:
        cmd.extend(["-H", f"X-F5-Auth-Token: {token}"])
    cmd.extend(
        [
            "-H",
            "Content-Type: application/json",
            "-H",
            "Connection: close",
            "--data-binary",
            f"@{body_path}",
            url,
        ]
    )
    proc: subprocess.Popen[bytes] | None = None
    outside = os.name == "nt"
    try:
        with open(body_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"))
        if outside:
            completed_code, raw = _curl_outside_gui(
                cmd,
                timeout=cap,
                out_path=out_path,
                body_path=body_path,
                max_bytes=max_bytes,
            )
        else:
            proc = _popen_detached(cmd)
            try:
                proc.wait(timeout=cap + 3.0)
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"timeout: tmsh 응답이 없습니다 ({cap:.0f}초)") from None
            completed_code = proc.returncode
            raw = b""
            try:
                with open(out_path, "rb") as stream:
                    raw = stream.read(max_bytes if max_bytes else _BASH_DEFAULT_MAX_BYTES)
            except OSError:
                raw = b""
    except TimeoutError:
        raise
    except OSError as exc:
        raise RuntimeError(f"curl 실행 실패: {exc}") from exc
    finally:
        if not outside:
            still_running = proc is not None and proc.poll() is None
            if not still_running:
                for path in (body_path, out_path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
    if completed_code not in (0, None) and not raw:
        raise TimeoutError(f"timeout: curl 종료 ({completed_code})")
    return extract_bash_command_result(raw)


def extract_bash_command_result(raw: bytes) -> str:
    """Pull commandResult without json.loads of an oversized/truncated body."""
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        body = None
    if isinstance(body, dict):
        result = body.get("commandResult", "")
        return result.strip() if isinstance(result, str) else str(result).strip()
    marker = '"commandResult"'
    start = text.find(marker)
    if start < 0:
        return text.strip()
    colon = text.find(":", start + len(marker))
    if colon < 0:
        return text.strip()
    rest = text[colon + 1 :].lstrip()
    if not rest.startswith('"'):
        return rest.strip().rstrip("}").strip()
    out: list[str] = []
    escaped = False
    for char in rest[1:]:
        if escaped:
            out.append("\n" if char == "n" else char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            break
        out.append(char)
    return "".join(out).strip()


class BigipClient:
    """read-only icontrol rest client (subset) with safety gate on writes."""

    def __init__(
        self,
        profile: ConnectionProfile,
        *,
        safety_gate: SafetyGate | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.profile = profile
        self.safety_gate = safety_gate or SafetyGate()
        self.timeout = timeout
        self._token: str | None = None
        self._use_basic_auth = False
        self._basic_probe_body: dict[str, Any] = {}
        self._tx_id: str | None = None
        self._http: httpx.Client | None = None

    def _session(self) -> httpx.Client:
        if self._http is None or self._http.is_closed:
            self._http = httpx.Client(
                verify=self.profile.target.verify_tls,
                timeout=_httpx_read_timeout(float(self.timeout)),
            )
        return self._http

    def _close_session(self) -> None:
        http = self._http
        self._http = None
        if http is None:
            return
        try:
            http.close()
        except Exception:
            pass

    def _base_url(self) -> str:
        target = self.profile.target
        return f"https://{target.host}:{target.port}/mgmt"

    def _auth_headers(self) -> dict[str, str]:
        if self._token and not self._use_basic_auth:
            return {"x-f5-auth-token": self._token}
        return {}

    def _http_auth(self) -> tuple[str, str] | None:
        if self._use_basic_auth:
            return (
                self.profile.username,
                self.profile.password.get_secret_value(),
            )
        return None

    def _probe_basic_auth(self) -> bool:
        """some tenants allow read-only GET with basic auth when token login returns 401."""
        url = f"{self._base_url()}/tm/sys/version"
        response = self._session().get(
            url,
            auth=(self.profile.username, self.profile.password.get_secret_value()),
            timeout=_httpx_read_timeout(float(self.timeout)),
        )
        if response.status_code == 200:
            self._use_basic_auth = True
            self._token = "basic-auth"
            self._basic_probe_body = redact_data(response.json())
            return True
        return False

    def authenticate(self) -> None:
        self._use_basic_auth = False
        self._basic_probe_body = {}
        url = f"{self._base_url()}/shared/authn/login"
        password = self.profile.password.get_secret_value()
        payloads = [
            {
                "username": self.profile.username,
                "password": password,
                "loginProviderName": "tmos",
            },
            {"username": self.profile.username, "password": password},
            {
                "username": self.profile.username,
                "password": password,
                "loginProviderName": "local",
            },
        ]
        headers = {"Content-Type": "application/json"}
        last_error: httpx.Response | None = None
        client = self._session()
        timeout = _httpx_read_timeout(float(self.timeout))
        for payload in payloads:
            response = client.post(url, json=payload, headers=headers, timeout=timeout)
            if response.status_code == 401:
                last_error = response
                continue
            response.raise_for_status()
            body = response.json()
            self._token = body.get("token", {}).get("token")
            if self._token:
                return
        if self._probe_basic_auth():
            return
        if last_error is not None:
            last_error.raise_for_status()
        raise RuntimeError("TMOS: login failed (no token, basic auth probe failed)")

    def get(self, path: str) -> dict[str, Any]:
        if not self._token:
            self.authenticate()
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self._base_url()}{path}"
        response = self._session().get(
            url,
            headers=self._auth_headers(),
            auth=self._http_auth(),
            timeout=_httpx_read_timeout(float(self.timeout)),
        )
        response.raise_for_status()
        return redact_data(response.json())

    def auth_mode_label(self) -> str:
        return "basic auth" if self._use_basic_auth else "token"

    def connection_summary(self) -> str:
        """short label after successful authenticate (for gui)."""
        if self._use_basic_auth:
            entry = self._basic_probe_body.get("entry", self._basic_probe_body)
            if isinstance(entry, str):
                return entry[:80]
            if isinstance(entry, list) and entry:
                return str(entry[0])[:80]
            return "basic auth OK"
        info = self.get_system_info()
        return str(
            info.get("hostname") or info.get("version") or info.get("marketingName", "OK")
        )[:80]

    def close(self) -> None:
        self._close_session()

    def _write_headers(self, *, include_transaction: bool = True) -> dict[str, str]:
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        if include_transaction and self._tx_id:
            headers["X-F5-REST-Coordination-Id"] = str(self._tx_id)
        else:
            headers["Connection"] = "close"
        return headers

    @staticmethod
    def _parse_json_bytes(raw: bytes) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            body = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            return {}
        if isinstance(body, dict):
            return redact_data(body)
        return {}

    @staticmethod
    def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
        if not response.content:
            return {}
        try:
            body = response.json()
        except ValueError:
            return {}
        if isinstance(body, dict):
            return redact_data(body)
        return {}

    def _write(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
        include_transaction: bool = True,
        max_bytes: int = 16_384,
        discard_body: bool = False,
    ) -> dict[str, Any]:
        self.safety_gate.assert_allowed(OperationClass.wr)
        if not self._token:
            self.authenticate()
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self._base_url()}{path}"
        read_s = float(timeout if timeout is not None else self.timeout)
        req_timeout = _httpx_read_timeout(read_s)
        raw = b""
        try:
            with self._session().stream(
                method.upper(),
                url,
                json=payload,
                headers=self._write_headers(include_transaction=include_transaction),
                auth=self._http_auth(),
                timeout=req_timeout,
            ) as response:
                try:
                    if response.status_code >= 400:
                        _read_response_capped(response, 2048)
                        response.raise_for_status()
                    if not discard_body:
                        raw = _read_response_capped(response, max_bytes)
                finally:
                    try:
                        response.close()
                    except Exception:
                        pass
        except httpx.HTTPStatusError:
            raise
        except (httpx.HTTPError, OSError):
            if not raw:
                raise
        finally:
            if not self._tx_id:
                self._close_session()
        return self._parse_json_bytes(raw)

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
        max_bytes: int = 8_192,
        discard_body: bool = False,
    ) -> dict[str, Any]:
        return self._write(
            "post",
            path,
            payload,
            timeout=timeout,
            max_bytes=max_bytes,
            discard_body=discard_body,
        )

    def post_via_curl(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Access-policy writes can dump the VPE. curl is a separate process so the GUI cannot die."""
        self.safety_gate.assert_allowed(OperationClass.wr)
        if not self._token:
            self.authenticate()
        if not path.startswith("/"):
            path = f"/{path}"
        curl_post_detach(
            f"{self._base_url()}{path}",
            token=str(self._token),
            payload=payload,
            insecure=not bool(self.profile.target.verify_tls),
        )
        return {"status": "detached"}

    def patch(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
        max_bytes: int = 8_192,
        discard_body: bool = False,
    ) -> dict[str, Any]:
        return self._write(
            "patch",
            path,
            payload,
            timeout=timeout,
            max_bytes=max_bytes,
            discard_body=discard_body,
        )

    def put(
        self, path: str, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        return self._write("put", path, payload, timeout=timeout)

    def begin_transaction(self) -> str:
        body = self._write("post", "/tm/transaction", {}, include_transaction=False)
        tx_id = body.get("transId") or body.get("transid")
        if tx_id is None:
            raise RuntimeError("TMOS: transaction id missing")
        self._tx_id = str(tx_id)
        return self._tx_id

    def commit_transaction(self, *, timeout: float = 120.0) -> dict[str, Any]:
        if not self._tx_id:
            raise RuntimeError("TMOS: no active transaction")
        tx_id = self._tx_id
        body = self._write(
            "patch",
            f"/tm/transaction/{tx_id}",
            {"state": "VALIDATING"},
            timeout=timeout,
            include_transaction=False,
        )
        self._tx_id = None
        return body

    def cancel_transaction(self) -> None:
        tx_id = self._tx_id
        self._tx_id = None
        if not tx_id:
            return
        try:
            self._write(
                "patch",
                f"/tm/transaction/{tx_id}",
                {"state": "CANCELLED"},
                include_transaction=False,
            )
        except httpx.HTTPError:
            pass

    def save_sys_ucs(self, filename: str, *, timeout: float = 180.0) -> dict[str, Any]:
        """POST /tm/sys/ucs — command save (device may finish after HTTP returns)."""
        name = filename.rsplit("/", 1)[-1]
        return self.post(
            "/tm/sys/ucs",
            {"command": "save", "name": name},
            timeout=timeout,
        )

    def get_system_info(self) -> dict[str, Any]:
        return self.get("/tm/sys/global-settings")

    def get_failover_state(self) -> dict[str, Any]:
        try:
            return self.get("/tm/cm/failover-status")
        except httpx.HTTPError:
            return {"status": "unknown"}

    def get_vlan_summary(self) -> dict[str, Any]:
        return self.get("/tm/net/vlan")

    def get_self_ip_summary(self) -> dict[str, Any]:
        return self.get("/tm/net/self")

    def get_route_summary(self) -> dict[str, Any]:
        return self.get("/tm/net/route")

    def get_pool_summary(self) -> dict[str, Any]:
        return self.get("/tm/ltm/pool")

    def get_optional(self, path: str) -> dict[str, Any]:
        """Best-effort GET; returns empty dict or {_unavailable: true} on HTTP errors."""
        if not self._token:
            self.authenticate()
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self._base_url()}{path}"
        try:
            response = self._session().get(
                url,
                headers=self._auth_headers(),
                auth=self._http_auth(),
                timeout=_httpx_read_timeout(float(self.timeout)),
            )
            if response.status_code in (400, 401, 403, 404, 405):
                return {
                    "_unavailable": True,
                    "_path": path,
                    "_error": f"HTTP {response.status_code}",
                    "_http_status": response.status_code,
                }
            response.raise_for_status()
            if not response.content:
                return {}
            return redact_data(response.json())
        except (httpx.HTTPError, OSError) as exc:
            return {"_unavailable": True, "_path": path, "_error": str(exc)[:200]}

    def collect_common_tmos_rest(self) -> dict[str, Any]:
        """REST equivalents for 정기점검 Common TMOS checks."""
        paths = {
            "uptime": "/tm/sys/uptime",
            "hardware": "/tm/sys/hardware",
            "interfaces": "/tm/net/interface",
            "ntp": "/tm/sys/ntp",
            "clock": "/tm/sys/clock",
            "disk": "/tm/sys/disk",
            "filesystem": "/tm/sys/filesystem",
            "services": "/tm/sys/service",
            "performance": "/tm/sys/performance",
            "certs": "/tm/sys/crypto/cert",
            "ucs": "/tm/sys/ucs",
        }
        return {key: self.get_optional(path) for key, path in paths.items()}

    def run_util_bash(
        self,
        shell_command: str,
        *,
        timeout: float | None = None,
        max_bytes: int | None = _BASH_DEFAULT_MAX_BYTES,
    ) -> str:
        """Run tmsh via a separate curl process. Never httpx — hung mcpd kills the frozen exe."""
        if not self._token:
            self.authenticate()
        read_s = float(timeout if timeout is not None else min(float(self.timeout), 30.0))
        if not _find_curl():
            raise RuntimeError(
                "curl.exe를 찾을 수 없어 tmsh를 실행하지 않습니다. "
                "GUI 프로세스에서 직접 호출하면 장비가 멈출 때 앱이 종료됩니다."
            )
        text = curl_util_bash(
            f"{self._base_url()}/tm/util/bash",
            token=str(self._token or ""),
            shell_command=shell_command,
            timeout=read_s,
            insecure=not bool(self.profile.target.verify_tls),
            basic=self._http_auth(),
            max_bytes=max_bytes,
        )
        text = redact_string(text)
        if text.lower().startswith("error") or "0107" in text[:20]:
            raise RuntimeError(f"bash rejected: {text[:200]}")
        return text
