from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.bigip_client import BigipClient
from app.core.models import ConnectionProfile
from app.core.output_naming import sanitize_label
from app.modules.health_check.apm_parse import parse_apm_access_info_total
from app.modules.health_check.ucs_backup import run_ucs_backup_batch
from app.modules.os_upgrade.pre_checklist_parsers import (
    LinuxCheckResult,
    parse_icall_entries,
    parse_linux_checks,
)

CONFIG_SYNC_NOTICE = (
    "작업 전 Config Sync를 Manual Sync로 변경 후 작업을 진행 해 주세요"
)

StepCallback = Callable[[str], None]


@dataclass(frozen=True)
class BackupFileResult:
    label: str
    filename: str
    path: str
    ok: bool
    detail: str = ""


@dataclass
class PreWorkReport:
    device_label: str
    session_total: str = "—"
    session_raw: str = ""
    linux_backups: list[BackupFileResult] = field(default_factory=list)
    f5mku_file: str = ""
    f5mku_ok: bool = False
    f5mku_detail: str = ""
    ucs_status: str = "—"
    ucs_log_rel: str = ""
    errors: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        ok_linux = sum(1 for b in self.linux_backups if b.ok)
        parts = [
            f"Session {self.session_total}",
            f"Linux 백업 {ok_linux}/{len(self.linux_backups)}",
            "f5mku OK" if self.f5mku_ok else "f5mku —",
            f"UCS {self.ucs_status}",
        ]
        return " | ".join(parts)


def _backup_filename(name: str) -> str:
    base = sanitize_label(name.replace("/", "_")) or "backup"
    if base.lower().endswith(".txt"):
        return base
    return f"{base}.txt"


def _device_backup_dir(workspace: Path, device_label: str) -> Path:
    d = workspace / "backups" / sanitize_label(device_label)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_backup_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", errors="replace")


def _fetch_file_via_cat(client: BigipClient, paths: list[str]) -> str:
    for p in paths:
        cmd = f"cat {shlex.quote(p)} 2>/dev/null"
        out = client.run_util_bash(cmd, timeout=60.0)
        low = (out or "").lower()
        if out.strip() and "no such file" not in low and "cannot open" not in low:
            return out
    return ""


def _backup_icall_via_tmsh_list(client: BigipClient, kind: str, name: str) -> str:
    """icall handler/script — cat 불가, tmsh list 로 정의 백업."""
    return client.run_util_bash(
        f"tmsh list sys icall {kind} {shlex.quote(name)} 2>/dev/null",
        timeout=90.0,
    )


def _collect_apm_session_total(client: BigipClient) -> tuple[str, str]:
    raw = client.run_util_bash(
        "tmsh show apm access-info 2>/dev/null | grep -i Total",
        timeout=60.0,
    )
    total = parse_apm_access_info_total(raw)
    if total is not None:
        return str(total), raw.strip()
    if not raw.strip():
        return "— (APM 미사용 또는 출력 없음)", raw.strip()
    return raw.strip()[:120], raw.strip()


def _backup_linux_items(
    client: BigipClient,
    backup_dir: Path,
    linux: LinuxCheckResult,
    *,
    on_step: StepCallback | None,
) -> list[BackupFileResult]:
    results: list[BackupFileResult] = []

    for entry in linux.icall_entries:
        if entry.kind.lower() != "script":
            continue
        if on_step:
            on_step(f"백업 icall script {entry.name}")
        fname = _backup_filename(entry.name)
        out_path = backup_dir / fname
        body = _backup_icall_via_tmsh_list(client, "script", entry.name)
        if not body.strip():
            continue
        _write_backup_file(out_path, body)
        results.append(
            BackupFileResult(
                label=f"icall script: {entry.name}",
                filename=fname,
                path=str(out_path),
                ok=True,
                detail="tmsh list",
            )
        )

    for script in linux.script_names:
        if on_step:
            on_step(f"백업 script {script}")
        fname = _backup_filename(script)
        out_path = backup_dir / fname
        body = _fetch_file_via_cat(client, [f"/var/tmp/{script.strip()}"])
        if not body.strip():
            continue
        _write_backup_file(out_path, body)
        results.append(
            BackupFileResult(
                label=f"script: {script}",
                filename=fname,
                path=str(out_path),
                ok=True,
                detail="cat",
            )
        )

    if on_step:
        on_step("백업 crontab")
    cron_fname = "crontab.txt"
    cron_path = backup_dir / cron_fname
    cron_body = client.run_util_bash("crontab -l 2>&1", timeout=30.0)
    _write_backup_file(cron_path, cron_body)
    results.append(
        BackupFileResult(
            label="crontab (전체)",
            filename=cron_fname,
            path=str(cron_path),
            ok=bool(cron_body.strip()),
            detail="저장됨",
        )
    )
    return results


def _backup_f5mku(client: BigipClient, backup_dir: Path) -> BackupFileResult:
    fname = "f5mku-K.txt"
    out_path = backup_dir / fname
    body = client.run_util_bash("f5mku -K 2>&1", timeout=120.0)
    ok = bool(body.strip())
    _write_backup_file(out_path, body or "")
    return BackupFileResult(
        label="f5mku -K",
        filename=fname,
        path=str(out_path),
        ok=ok,
        detail="저장됨" if ok else "출력 없음",
    )


def collect_pre_work(
    connection: ConnectionProfile,
    workspace: Path,
    *,
    on_step: StepCallback | None = None,
) -> PreWorkReport:
    def step(msg: str) -> None:
        if on_step:
            on_step(msg)

    label = connection.target.label
    report = PreWorkReport(device_label=label)
    backup_dir = _device_backup_dir(workspace, label)

    client = BigipClient(connection)
    client.authenticate()

    try:
        step("APM Session (Total)")
        report.session_total, report.session_raw = _collect_apm_session_total(client)

        step("Linux 항목 백업")
        icall_text = client.run_util_bash("tmsh list sys icall 2>/dev/null")
        crontab_text = client.run_util_bash("crontab -l 2>&1")
        scripts_ls = client.run_util_bash(
            "ls /var/tmp 2>/dev/null | grep '\\.sh' || true"
        )
        linux = parse_linux_checks(icall_text, crontab_text, scripts_ls)
        report.linux_backups = _backup_linux_items(
            client, backup_dir, linux, on_step=on_step
        )

        step("f5mku -K")
        f5 = _backup_f5mku(client, backup_dir)
        report.f5mku_file = f5.filename
        report.f5mku_ok = f5.ok
        report.f5mku_detail = f5.detail
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc)[:300])

    return report


def run_pre_work_ucs_backups(
    connections: list[ConnectionProfile],
    ucs_log_path: Path,
    *,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, str]:
    """정기점검과 동일 stagger UCS — 장비 label → 상태 요약."""
    jobs: list[dict] = []
    for conn in connections:
        hostname = ""
        try:
            client = BigipClient(conn)
            client.authenticate()
            gs = client.get_system_info()
            hostname = str(gs.get("hostname", "") or "").strip()
        except Exception:  # noqa: BLE001
            pass
        jobs.append(
            {
                "connection": conn,
                "ucs_log_path": str(ucs_log_path),
                "device_label": conn.target.label,
                "hostname_hint": hostname,
            }
        )
    ucs_log_path.parent.mkdir(parents=True, exist_ok=True)
    run_ucs_backup_batch(jobs, str(ucs_log_path), on_progress=on_progress)
    return {j["device_label"]: "백그라운드 완료 (ucs_backup.log 확인)" for j in jobs}
