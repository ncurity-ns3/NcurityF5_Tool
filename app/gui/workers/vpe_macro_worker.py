from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from PyQt6.QtCore import QThread, pyqtSignal
from pydantic import SecretStr

from app.core.bigip_client import BigipClient
from app.core.models import ConnectionProfile, DeviceTarget, PlatformKind
from app.core.safety_gate import SafetyGate
from app.modules.vpe_macro.apm_macro import (
    AccessProfileRef,
    ApplyResult,
    MacroApplyError,
    MacroSnapshot,
    MacroSummary,
    apply_macro_snapshot,
    export_macro_snapshot,
    fetch_access_profiles_detached,
    list_macros_for_profile,
    resolve_access_profile,
)

VpeMacroAction = Literal["login", "load_macros", "export", "apply"]


@dataclass
class VpeMacroJob:
    action: VpeMacroAction
    host: str
    port: int
    username: str
    password: str
    profile_path: str = ""
    macro_path: str = ""
    snapshot: MacroSnapshot | None = None
    target_profile_path: str = ""
    target_macro_name: str = ""
    source_hostname: str = ""
    target_profile: AccessProfileRef | None = None


@dataclass
class VpeMacroResult:
    action: VpeMacroAction
    hostname: str = ""
    auth_mode: str = ""
    profiles: list[AccessProfileRef] = field(default_factory=list)
    selected_profile: AccessProfileRef | None = None
    policy: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    macros: list[MacroSummary] = field(default_factory=list)
    snapshot: MacroSnapshot | None = None
    apply_result: ApplyResult | None = None


def _format_http_error(exc: BaseException) -> str:
    if isinstance(exc, MacroApplyError) and exc.__cause__ is not None:
        inner = _format_http_error(exc.__cause__)
        text = str(exc).strip()
        if inner and inner not in text:
            return f"{text} ({inner})"
        return text
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = (exc.response.text or "")[:180].strip()
        if status == 401:
            return "로그인 실패 (401). ID/Password를 확인하세요."
        if status == 404:
            return (
                "대상을 찾을 수 없습니다 (404). "
                "Access Profile 또는 Access Policy 경로를 확인하세요."
            )
        if status in (400, 404):
            low = detail.lower()
            if "not provisioned" in low or "not licensed" in low:
                return f"APM이 프로비저닝되어 있지 않습니다. ({status}) {detail}"
            return f"APM API 오류 ({status}). {detail}"
        return f"HTTP {status}: {detail or exc.__class__.__name__}"
    if isinstance(exc, httpx.ConnectError):
        return f"연결 실패: {exc}"
    if isinstance(exc, httpx.TimeoutException):
        return "연결 시간 초과. MGMT IP/Port를 확인하세요."
    return str(exc)


def _client(job: VpeMacroJob, *, change_mode: bool = False, timeout: float = 120.0) -> BigipClient:
    profile = ConnectionProfile(
        target=DeviceTarget(
            label="vpe-macro",
            platform=PlatformKind.iseries,
            host=job.host,
            port=job.port,
            verify_tls=False,
        ),
        username=job.username,
        password=SecretStr(job.password),
    )
    return BigipClient(
        profile,
        safety_gate=SafetyGate(change_mode_enabled=change_mode),
        timeout=timeout,
    )


class VpeMacroWorker(QThread):
    progress = pyqtSignal(str)
    percent = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job: VpeMacroJob) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            if self.job.action == "login":
                self.finished_ok.emit(self._login())
            elif self.job.action == "load_macros":
                self.finished_ok.emit(self._load_macros())
            elif self.job.action == "export":
                self.finished_ok.emit(self._export())
            elif self.job.action == "apply":
                self.finished_ok.emit(self._apply())
            else:
                raise RuntimeError(f"unknown action: {self.job.action}")
        except Exception as exc:  # noqa: BLE001 — surface to gui
            self.failed.emit(_format_http_error(exc)[:900])
        except BaseException as exc:  # noqa: BLE001
            self.failed.emit(f"예기치 않은 오류: {exc}"[:400])

    def _login(self) -> VpeMacroResult:
        def _on_progress(current: int, total: int, message: str) -> None:
            self.progress.emit(message)
            self.percent.emit(current, total, message)

        profiles = fetch_access_profiles_detached(
            host=self.job.host,
            port=self.job.port,
            username=self.job.username,
            password=self.job.password,
            progress=_on_progress,
        )
        hostname = (self.job.host or "").strip()
        total = max(len(profiles), 1)
        self.percent.emit(total, total, "Access Profile Loading 완료")
        return VpeMacroResult(
            action="login",
            hostname=hostname,
            auth_mode="token",
            profiles=profiles,
        )

    def _load_macros(self) -> VpeMacroResult:
        client = _client(self.job)
        client.authenticate()
        selected = self.job.target_profile
        if selected is None:
            self.progress.emit("대상 Access Profile 확인 중…")
            selected = resolve_access_profile(client, self.job.profile_path)
        else:
            self.progress.emit(f"대상 Access Profile: {selected.full_path}")
        self.progress.emit(f"Macro 조회 중… ({selected.name})")
        policy, items, macros = list_macros_for_profile(
            client, selected, progress=self.progress.emit
        )
        self.progress.emit(f"Macro {len(macros)}개")
        return VpeMacroResult(
            action="load_macros",
            hostname=self.job.source_hostname,
            profiles=[],
            selected_profile=selected,
            policy=policy,
            items=items,
            macros=macros,
        )

    def _export(self) -> VpeMacroResult:
        loaded = self._load_macros()
        if loaded.selected_profile is None:
            raise RuntimeError("Access Profile이 선택되지 않았습니다.")
        macro = next((m for m in loaded.macros if m.full_path == self.job.macro_path), None)
        if macro is None:
            raise RuntimeError(f"Macro를 찾을 수 없습니다: {self.job.macro_path}")
        self.progress.emit(f"Macro 상세 수집 중… ({macro.caption})")
        client = _client(self.job)
        client.authenticate()
        snapshot = export_macro_snapshot(
            client,
            profile=loaded.selected_profile,
            policy=loaded.policy,
            items=loaded.items,
            macro=macro,
            source_host=self.job.host,
            source_hostname=self.job.source_hostname or loaded.hostname,
            progress=self.progress.emit,
        )
        loaded.action = "export"
        loaded.snapshot = snapshot
        return loaded

    def _apply(self) -> VpeMacroResult:
        snapshot = self.job.snapshot
        if snapshot is None:
            raise RuntimeError("적용할 Macro 스냅샷이 없습니다.")
        self.progress.emit("Load 준비 중…")
        client = _client(self.job, change_mode=True)
        self.progress.emit("로그인 중…")
        client.authenticate()
        target = self.job.target_profile
        if target is None:
            self.progress.emit("대상 Access Profile 확인 중…")
            target = resolve_access_profile(client, self.job.target_profile_path)
        else:
            self.progress.emit(f"대상 Access Profile: {target.full_path}")
        # Load 중에는 대상 Policy를 tmsh list 하지 않는다. macros 조회가 VPE를 덤프해 프로세스가 죽는다.
        self.progress.emit(f"Macro 적용 중… → {target.name}")
        result = apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={
                "name": target.name,
                "partition": target.partition,
                "fullPath": target.full_path,
                "_macro_refs": [],
            },
            existing_items=[],
            target_macro_name=self.job.target_macro_name or None,
            progress=self.progress.emit,
        )
        return VpeMacroResult(
            action="apply",
            hostname=self.job.source_hostname,
            profiles=[],
            selected_profile=target,
            apply_result=result,
            snapshot=snapshot,
        )
