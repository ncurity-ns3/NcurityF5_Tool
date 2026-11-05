from __future__ import annotations

import concurrent.futures
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

UCS_DEVICE_WALL_TIMEOUT = 1500.0
# staggered: 장비마다 시작만 간격 — save는 겹쳐도 됨 (동시 3대 gzip 피크 완화)
# sequential: 1대 끝난 뒤 다음
# parallel: 동시 시작 (비권장)
UcsBatchMode = Literal["staggered", "sequential", "parallel"]
UCS_BATCH_MODE: UcsBatchMode = "staggered"
UCS_STAGGER_START_SEC = 1.0
UCS_SLEEP_AFTER_DEVICE_SEC = 5.0
UCS_MAX_PARALLEL = 0  # 0 = job 수만큼

from app.core.models import ConnectionProfile
from app.modules.health_check.tmos_common_collect import (
    _append_ucs_log,
    _ucs_backup_worker,
)


def build_ucs_backup_jobs(
    *,
    targets: list,
    results: list,
    connections: list[ConnectionProfile] | None,
    conn_by_label: dict[str, ConnectionProfile],
    use_index: bool,
    mock_fixtures: dict[str, dict] | None,
) -> list[dict[str, Any]]:
    result_by_label: dict[str, Any] = {}
    for r in results:
        if isinstance(r, dict):
            result_by_label[str(r.get("device_label", ""))] = r
        else:
            result_by_label[str(getattr(r, "device_label", ""))] = r
    jobs: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    for idx, target in enumerate(targets):
        if mock_fixtures and target.label in mock_fixtures:
            continue
        if use_index and connections:
            connection = connections[idx]
        else:
            connection = conn_by_label.get(target.label)
        if connection is None:
            continue
        host_ip = (connection.target.host or "").strip()
        if host_ip and host_ip in seen_hosts:
            continue
        if host_ip:
            seen_hosts.add(host_ip)
        hostname = ""
        res = result_by_label.get(target.label)
        if res is not None:
            if isinstance(res, dict):
                data = res.get("data") if isinstance(res.get("data"), dict) else {}
            else:
                data = getattr(res, "data", {}) or {}
            common = data.get("common") if isinstance(data.get("common"), dict) else {}
            tmos = common.get("tmos") if isinstance(common.get("tmos"), dict) else {}
            meta = tmos.get("_meta") if isinstance(tmos.get("_meta"), dict) else {}
            hostname = str(meta.get("hostname", "") or "")
        jobs.append(
            {
                "connection": connection,
                "ucs_log_path": None,
                "device_label": target.label,
                "hostname_hint": hostname,
            }
        )
    return jobs


def _run_one_ucs_job(
    idx: int,
    job: dict[str, Any],
    ucs_log_path: str,
    total: int,
    *,
    on_tick: Callable[[str], None] | None,
) -> None:
    label = str(job.get("device_label", ""))
    payload = {**job, "ucs_log_path": ucs_log_path, "on_tick": on_tick}
    _append_ucs_log(
        ucs_log_path,
        f"[{datetime.now().isoformat(timespec='seconds')}] {label} UCS start ({idx}/{total})",
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_ucs_backup_worker, **payload)
        try:
            fut.result(timeout=UCS_DEVICE_WALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            _append_ucs_log(
                ucs_log_path,
                f"[{label}] UCS FAIL: 장비당 최대 대기 "
                f"({int(UCS_DEVICE_WALL_TIMEOUT // 60)}분) 초과",
            )


def run_ucs_backup_batch(
    jobs: list[dict[str, Any]],
    ucs_log_path: str,
    *,
    on_progress: Callable[[str, int, int, str], None] | None = None,
    mode: UcsBatchMode = UCS_BATCH_MODE,
    stagger_start_sec: float = UCS_STAGGER_START_SEC,
    sleep_after_device_sec: float = UCS_SLEEP_AFTER_DEVICE_SEC,
    max_parallel: int = UCS_MAX_PARALLEL,
) -> None:
    if not jobs:
        _append_ucs_log(ucs_log_path, f"[{datetime.now().isoformat(timespec='seconds')}] UCS: no jobs")
        return
    total = len(jobs)
    if total == 1:
        batch_mode: UcsBatchMode = "sequential"
    elif mode == "parallel":
        batch_mode = "parallel"
    elif mode == "sequential":
        batch_mode = "sequential"
    else:
        batch_mode = "staggered"

    workers = total if max_parallel <= 0 else min(max_parallel, total)
    extra = ""
    if batch_mode == "staggered":
        extra = f", stagger={int(stagger_start_sec)}s"
    _append_ucs_log(
        ucs_log_path,
        f"[{datetime.now().isoformat(timespec='seconds')}] UCS batch start "
        f"({total} device(s), {batch_mode}{extra})",
    )

    progress_lock = threading.Lock()
    state: dict[str, Any] = {"done": 0, "active": {}}

    def emit_progress() -> None:
        if not on_progress:
            return
        with progress_lock:
            done = int(state["done"])
            active: dict[str, str] = state["active"]
            if active:
                label, detail = next(iter(active.items()))
                text = f"UCS {done}/{total} 완료 · {label}"
                if detail:
                    text += f" · {detail}"
            else:
                text = f"UCS {done}/{total} 완료"
            on_progress(text, min(done + 1, total), total, "")

    def make_on_tick(job_label: str) -> Callable[[str], None]:
        def on_tick(msg: str) -> None:
            with progress_lock:
                state["active"][job_label] = msg
            emit_progress()

        return on_tick

    def run_job(idx: int, job: dict[str, Any]) -> None:
        label = str(job.get("device_label", ""))
        try:
            _run_one_ucs_job(idx, job, ucs_log_path, total, on_tick=make_on_tick(label))
        finally:
            with progress_lock:
                state["active"].pop(label, None)
                state["done"] = int(state["done"]) + 1
            emit_progress()

    if batch_mode == "staggered":
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs: list[concurrent.futures.Future[None]] = []
            for idx, job in enumerate(jobs, start=1):
                label = str(job.get("device_label", ""))
                if on_progress:
                    on_progress(
                        f"UCS 시작 {idx}/{total} — {label}",
                        idx,
                        total,
                        "",
                    )
                futs.append(pool.submit(run_job, idx, job))
                if idx < total:
                    _append_ucs_log(
                        ucs_log_path,
                        f"[{datetime.now().isoformat(timespec='seconds')}] "
                        f"다음 UCS 시작 전 {int(stagger_start_sec)}초 대기",
                    )
                    time.sleep(stagger_start_sec)
            concurrent.futures.wait(futs)
    elif batch_mode == "parallel":
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [
                pool.submit(run_job, idx, job) for idx, job in enumerate(jobs, start=1)
            ]
            concurrent.futures.wait(futs)
    else:
        for idx, job in enumerate(jobs, start=1):
            label = str(job.get("device_label", ""))
            if on_progress:
                on_progress(f"UCS 백업 {idx}/{total} — {label}", idx, total, "시작")
            run_job(idx, job)
            if idx < total and sleep_after_device_sec > 0:
                _append_ucs_log(
                    ucs_log_path,
                    f"[{datetime.now().isoformat(timespec='seconds')}] "
                    f"다음 장비 UCS 전 {int(sleep_after_device_sec)}초 대기",
                )
                time.sleep(sleep_after_device_sec)

    _append_ucs_log(
        ucs_log_path,
        f"[{datetime.now().isoformat(timespec='seconds')}] UCS batch end "
        f"({total} device(s), {batch_mode})",
    )
