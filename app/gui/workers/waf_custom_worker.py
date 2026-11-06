from __future__ import annotations

import time

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.waf_poc.curlutil import Target
from app.modules.waf_poc.custom_request import (
    LoginPlan,
    PreparedCall,
    accounts_for,
    build_login_call,
    build_main_call,
    cookies_from_response,
)
from app.modules.waf_poc.runner import CurlRunner, find_curl
from app.modules.waf_poc.verdict import classify_response


class WafCustomWorker(QThread):
    log_line = pyqtSignal(str)
    run_done = pyqtSignal(str)
    run_failed = pyqtSignal(str)

    def __init__(
        self,
        target: Target,
        *,
        method: str,
        uri: str,
        params: list[tuple[str, str]],
        headers: list[tuple[str, str]],
        cookies: list[tuple[str, str]],
        insecure: bool,
        login: LoginPlan | None,
        login_only: bool,
        carry_cookies: bool,
    ) -> None:
        super().__init__()
        self.target = target
        self.method = method
        self.uri = uri
        self.params = params
        self.headers = headers
        self.cookies = cookies
        self.insecure = insecure
        self.login = login
        self.login_only = login_only
        self.carry_cookies = carry_cookies
        self.runner = CurlRunner()
        self._last_cookies: list[tuple[str, str]] = []

    def stop_now(self) -> None:
        self.requestInterruption()
        self.runner.stop()

    def run(self) -> None:
        try:
            curl_bin = find_curl()
            cookies = list(self.cookies)
            if self.login is not None:
                jobs = accounts_for(self.login)
                for index, (username, password) in enumerate(jobs, start=1):
                    if self.isInterruptionRequested():
                        self.log_line.emit("전송을 중지했습니다.")
                        self.run_done.emit("중지")
                        return
                    call = build_login_call(
                        self.target,
                        curl_bin,
                        self.login,
                        username,
                        password,
                        insecure=self.insecure,
                    )
                    self._send(call, f"{index}/{len(jobs)}")
                    if self.carry_cookies:
                        cookies = _merge(cookies, self._last_cookies)
                    self._pause(self.login.pause_seconds)
            if self.login_only:
                self.run_done.emit("로그인 완료")
                return
            call = build_main_call(
                self.target,
                curl_bin,
                method=self.method,
                uri=self.uri,
                params=self.params,
                headers=self.headers,
                cookies=cookies,
                insecure=self.insecure,
            )
            self._send(call, "")
        except (OSError, ValueError) as exc:
            self.run_failed.emit(str(exc))
            return
        self.run_done.emit("완료")

    def _send(self, call: PreparedCall, prefix: str) -> None:
        code, output, timed_out = self.runner.run_one(call.argv)
        outcome, http_code = classify_response(output, timed_out=timed_out, return_code=code)
        labels = {"blocked": "차단", "passed": "통과", "failed": "실패"}
        shown = "-" if http_code is None else str(http_code)
        head = f"{prefix} {call.label}".strip()
        self.log_line.emit(f"{head}  →  HTTP {shown}  {labels.get(outcome, outcome)}")
        if output:
            self.log_line.emit(output)
        self._last_cookies = cookies_from_response(output)

    def _pause(self, seconds: int) -> None:
        for _ in range(max(seconds, 0) * 10):
            if self.isInterruptionRequested():
                return
            time.sleep(0.1)


def _merge(base: list[tuple[str, str]], extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    merged = dict(base)
    merged.update(dict(extra))
    return list(merged.items())
