"""Send rewritten curl commands without a shell."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass

from app.modules.waf_poc.catalog import PocCase
from app.modules.waf_poc.curlutil import Target, build_curl_argv

_CREATE_NO_WINDOW = 0x08000000
_OUTPUT_LIMIT = 4000


@dataclass(frozen=True)
class SendSummary:
    sent: int
    failed: int
    stopped: bool


class CurlRunner:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run_one(self, argv: list[str]) -> tuple[int, str, bool]:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        with self._lock:
            self._proc = proc
        timed_out = False
        try:
            out, err = proc.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            out, err = proc.communicate()
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
        text = _trim((out or b"").decode("utf-8", "replace"))
        err_text = _trim((err or b"").decode("utf-8", "replace"))
        if timed_out:
            text = (text + "\n시간 초과 (20초)").strip()
        if err_text:
            text = (text + "\n" + err_text).strip()
        code = proc.returncode if proc.returncode is not None else 1
        return code, text, timed_out


def find_curl() -> str:
    for name in ("curl.exe", "curl"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError("curl을 찾지 못했습니다. Windows에 포함된 curl이 필요합니다.")


def run_cases(
    cases: list[PocCase],
    target: Target,
    on_text: Callable[[str], None],
    runner: CurlRunner | None = None,
) -> SendSummary:
    active = runner or CurlRunner()
    jobs: list[tuple[PocCase, str]] = []
    for case in cases:
        for command in case.commands():
            jobs.append((case, command))
    total = len(jobs)
    on_text(
        f"대상 {target.origin}  →  {target.ip}:{target.port}\n"
        f"항목 {len(cases)}개, 요청 {total}건\n"
    )
    curl_bin = find_curl()
    sent = 0
    failed = 0
    for index, (case, command) in enumerate(jobs, start=1):
        if active.stopped:
            on_text("\n전송을 중지했습니다.")
            return SendSummary(sent=sent, failed=failed, stopped=True)
        rewritten, argv = build_curl_argv(command, target, curl_bin)
        on_text(f"[{index}/{total}] {case.group} · {case.title}\n{rewritten}\n")
        code, output, timed_out = active.run_one(argv)
        if active.stopped:
            on_text(output + "\n\n전송을 중지했습니다.")
            return SendSummary(sent=sent, failed=failed, stopped=True)
        sent += 1
        if code != 0 or timed_out:
            failed += 1
        if output:
            on_text(output + "\n")
        else:
            on_text(f"(응답 본문 없음, curl 종료 코드 {code})\n")
    on_text(f"\n완료. 전송 {sent}건, 연결 실패 {failed}건")
    return SendSummary(sent=sent, failed=failed, stopped=False)


def _trim(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    if len(cleaned) <= _OUTPUT_LIMIT:
        return cleaned
    return cleaned[:_OUTPUT_LIMIT] + f"\n... ({len(cleaned) - _OUTPUT_LIMIT}자 생략)"
