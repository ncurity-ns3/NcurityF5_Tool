from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import SecretStr

from app.core.bigip_client import BigipClient
from app.core.f5os_client import F5osClient, format_f5os_summary
from app.core.models import ConnectionProfile, DeviceTarget, PlatformKind
from app.gui.device_models import MODEL_RSERIES, normalize_device_model
from app.gui.widgets.multi_device_entry import DeviceRowData

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ConnectionTestStep:
    device_label: str
    stack_label: str  # F5OS | TMOS
    host: str
    port: int
    username: str
    password: str
    platform: PlatformKind


@dataclass
class ConnectionTestPlan:
    mode: str  # single | multiple
    device_count: int
    steps: list[ConnectionTestStep] = field(default_factory=list)


@dataclass(frozen=True)
class LiveSessionRegistration:
    host: str
    port: int
    username: str
    scope: str  # tmos | f5os


@dataclass
class ConnectionTestOutcome:
    ok_all: bool
    summary: str
    lines: list[str]
    sessions: list[LiveSessionRegistration] = field(default_factory=list)
    blocked: bool = False  # validation failed before any network call
    block_message: str = ""


def _device_target_for_test(
    *,
    host: str,
    port: int,
    platform: PlatformKind,
    f5os_host: str = "",
    f5os_port: int = 443,
) -> DeviceTarget:
    return DeviceTarget(
        label="test",
        platform=platform,
        host=host,
        port=port,
        f5os_host=f5os_host if platform == PlatformKind.rseries else "",
        f5os_port=f5os_port,
        verify_tls=False,
    )


def _run_tmos_step(step: ConnectionTestStep) -> tuple[bool, str, LiveSessionRegistration | None]:
    profile = ConnectionProfile(
        target=_device_target_for_test(host=step.host, port=step.port, platform=step.platform),
        username=step.username,
        password=SecretStr(step.password),
    )
    client = BigipClient(profile)
    client.authenticate()
    detail = client.connection_summary()
    mode = f" ({client.auth_mode_label()})" if client.auth_mode_label() != "token" else ""
    return (
        True,
        f"{detail}{mode}",
        LiveSessionRegistration(step.host, step.port, step.username, "tmos"),
    )


def _run_f5os_step(step: ConnectionTestStep) -> tuple[bool, str, LiveSessionRegistration | None]:
    client = F5osClient(
        step.host, step.port, step.username, step.password, verify_tls=False
    )
    overview = client.get_system_overview()
    return (
        True,
        format_f5os_summary(overview),
        LiveSessionRegistration(step.host, step.port, step.username, "f5os"),
    )


def _tmos_fail_hint(exc: Exception, platform: PlatformKind) -> str:
    if "401" in str(exc) and platform == PlatformKind.rseries:
        return " (tenant 계정 — F5OS platform 비밀번호와 다를 수 있음)"
    if "401" in str(exc):
        return (
            " (TMOS tenant — iSeries와 IP/계정이 다름. "
            "tenant Web UI 로그인 ID/PW 확인)"
        )
    return ""


def _f5os_fail_hint(exc: Exception) -> str:
    if "404" in str(exc):
        return " (F5OS: /api 경로 확인, 포트 8888이면 Port=8888)"
    if "401" in str(exc):
        return " (F5OS: platform 계정 확인)"
    return ""


def build_single_plan(
    *,
    platform: PlatformKind,
    label: str,
    f5os_host: str,
    f5os_port: int,
    f5os_user: str,
    f5os_pass: str,
    tmos_host: str,
    tmos_port: int,
    tmos_user: str,
    tmos_pass: str,
) -> ConnectionTestOutcome | ConnectionTestPlan:
    steps: list[ConnectionTestStep] = []
    if platform == PlatformKind.rseries:
        if not f5os_host:
            return ConnectionTestOutcome(
                blocked=True,
                block_message="F5OS MGMT IP를 입력하세요.",
                ok_all=False,
                summary="",
                lines=[],
            )
        if not f5os_pass:
            return ConnectionTestOutcome(
                blocked=True,
                block_message="F5OS 비밀번호를 입력하세요.",
                ok_all=False,
                summary="",
                lines=[],
            )
        steps.append(
            ConnectionTestStep(
                device_label=label,
                stack_label="F5OS",
                host=f5os_host,
                port=f5os_port,
                username=f5os_user,
                password=f5os_pass,
                platform=platform,
            )
        )
    if platform == PlatformKind.iseries or tmos_host:
        if not tmos_host and platform == PlatformKind.iseries:
            return ConnectionTestOutcome(
                blocked=True,
                block_message="TMOS MGMT IP를 입력하세요.",
                ok_all=False,
                summary="",
                lines=[],
            )
        if tmos_host:
            if not tmos_pass:
                return ConnectionTestOutcome(
                    blocked=True,
                    block_message="TMOS 비밀번호를 입력하세요.",
                    ok_all=False,
                    summary="",
                    lines=[],
                )
            steps.append(
                ConnectionTestStep(
                    device_label=label,
                    stack_label="TMOS",
                    host=tmos_host,
                    port=tmos_port,
                    username=tmos_user,
                    password=tmos_pass,
                    platform=platform,
                )
            )
    return ConnectionTestPlan(mode="single", device_count=1, steps=steps)


def build_multiple_plan(
    devices: list[DeviceRowData],
    *,
    per_device_auth: bool,
    common_tmos_user: str,
    common_tmos_pass: str,
    common_f5os_user: str,
    common_f5os_pass: str,
) -> ConnectionTestOutcome | ConnectionTestPlan:
    if not devices:
        return ConnectionTestOutcome(
            blocked=True,
            block_message="장비 목록이 비어 있습니다.",
            ok_all=False,
            summary="",
            lines=[],
        )

    steps: list[ConnectionTestStep] = []
    for idx, data in enumerate(devices):
        label = data.label.strip() or f"device-{idx + 1}"
        platform = (
            PlatformKind.rseries
            if normalize_device_model(data.model) == MODEL_RSERIES
            else PlatformKind.iseries
        )
        if per_device_auth:
            tmos_user, tmos_pass = data.tmos_user, data.tmos_pass
            f5os_user, f5os_pass = data.f5os_user, data.f5os_pass
        else:
            tmos_user = common_tmos_user
            tmos_pass = common_tmos_pass
            f5os_user = common_f5os_user
            f5os_pass = common_f5os_pass

        if platform == PlatformKind.rseries:
            if not data.f5os_host:
                steps.append(
                    ConnectionTestStep(
                        device_label=label,
                        stack_label="F5OS_SKIP",
                        host="",
                        port=0,
                        username="",
                        password="",
                        platform=platform,
                    )
                )
            elif not f5os_pass:
                steps.append(
                    ConnectionTestStep(
                        device_label=label,
                        stack_label="F5OS_SKIP_PW",
                        host=data.f5os_host,
                        port=data.f5os_port,
                        username=f5os_user,
                        password="",
                        platform=platform,
                    )
                )
            else:
                steps.append(
                    ConnectionTestStep(
                        device_label=label,
                        stack_label="F5OS",
                        host=data.f5os_host,
                        port=data.f5os_port,
                        username=f5os_user,
                        password=f5os_pass,
                        platform=platform,
                    )
                )
        if platform == PlatformKind.iseries or data.tmos_host:
            if not data.tmos_host:
                steps.append(
                    ConnectionTestStep(
                        device_label=label,
                        stack_label="TMOS_SKIP",
                        host="",
                        port=0,
                        username="",
                        password="",
                        platform=platform,
                    )
                )
            elif not tmos_pass:
                steps.append(
                    ConnectionTestStep(
                        device_label=label,
                        stack_label="TMOS_SKIP_PW",
                        host=data.tmos_host,
                        port=data.tmos_port,
                        username=tmos_user,
                        password="",
                        platform=platform,
                    )
                )
            else:
                steps.append(
                    ConnectionTestStep(
                        device_label=label,
                        stack_label="TMOS",
                        host=data.tmos_host,
                        port=data.tmos_port,
                        username=tmos_user,
                        password=tmos_pass,
                        platform=platform,
                    )
                )

    return ConnectionTestPlan(mode="multiple", device_count=len(devices), steps=steps)


def run_connection_tests_with_skips(
    plan: ConnectionTestPlan,
    *,
    on_progress: ProgressCallback | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ConnectionTestOutcome:
    """Run plan, handling SKIP pseudo-steps without network I/O."""
    lines: list[str] = []
    sessions: list[LiveSessionRegistration] = []
    ok_all = True
    real_steps = [s for s in plan.steps if s.stack_label in ("F5OS", "TMOS")]
    total = len(real_steps)
    real_idx = 0
    current_device = ""

    for step in plan.steps:
        label = step.device_label
        prefix = f"[{label}] " if plan.mode == "multiple" else ""

        if plan.mode == "multiple" and label != current_device:
            current_device = label
            lines.append(f"── [{label}] ──")

        if step.stack_label == "F5OS_SKIP":
            lines.append(f"{prefix}F5OS: SKIP (MGMT IP 없음)")
            ok_all = False
            continue
        if step.stack_label == "F5OS_SKIP_PW":
            lines.append(f"{prefix}F5OS: SKIP (비밀번호 없음)")
            ok_all = False
            continue
        if step.stack_label == "TMOS_SKIP":
            lines.append(f"{prefix}TMOS: SKIP (MGMT IP 없음)")
            ok_all = False
            continue
        if step.stack_label == "TMOS_SKIP_PW":
            lines.append(f"{prefix}TMOS: SKIP (비밀번호 없음)")
            ok_all = False
            continue

        real_idx += 1
        prog_msg = f"{label} — {step.stack_label} {step.host}"
        if on_progress:
            on_progress(real_idx, total, prog_msg)

        if should_stop and should_stop():
            lines.append(f"{prefix}중단됨 (사용자 Disconnect)")
            return ConnectionTestOutcome(
                ok_all=False,
                summary="연결 테스트 중단",
                lines=lines,
                sessions=sessions,
            )

        try:
            if step.stack_label == "F5OS":
                ok, detail, reg = _run_f5os_step(step)
            else:
                ok, detail, reg = _run_tmos_step(step)
            lines.append(
                f"{prefix}{step.stack_label} {step.host}: "
                f"{'OK' if ok else 'FAIL'} — {detail}"
            )
            ok_all = ok_all and ok
            if reg:
                sessions.append(reg)
        except Exception as exc:  # noqa: BLE001
            ok_all = False
            hint = (
                _f5os_fail_hint(exc)
                if step.stack_label == "F5OS"
                else _tmos_fail_hint(exc, step.platform)
            )
            lines.append(f"{prefix}{step.stack_label} FAIL — {exc}{hint}")

    if plan.mode == "multiple":
        summary = f"연결 테스트 — {plan.device_count}대" + (
            " (전체 성공)" if ok_all else " (일부 실패)"
        )
    else:
        summary = "연결 성공" if ok_all else "연결 실패"
    return ConnectionTestOutcome(ok_all=ok_all, summary=summary, lines=lines, sessions=sessions)
