from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.output_naming import make_dated_folder_name, sanitize_label

# 작업 키 → HTML 파일명 (같은 라벨 폴더에 단계별로 저장)
ACTION_REPORT_FILES: dict[str, str] = {
    "device_overview": "device_overview.html",
    "pre_checklist": "pre_checklist.html",
    "pre_work": "pre_work.html",
    "post_checklist": "post_checklist.html",
}

# 작업 전/후 Check List — 동일 항목, 하위 폴더만 구분
CHECKLIST_OUTPUT_DIRS: dict[str, str] = {
    "pre_checklist": "pre_checklist",
    "post_checklist": "post_checklist",
}


def new_job_workspace(
    root: Path,
    label: str,
    *,
    folder_name: str | None = None,
) -> tuple[Path, str]:
    """
    output/os_upgrade/<YYYYMMDD-HHMMSS_label>/
    HTML: device_overview.html, pre_checklist/pre_checklist.html,
    post_checklist/post_checklist.html, pre_work.html …
    """
    fname = folder_name or make_dated_folder_name(label)
    ws = root / fname
    ws.mkdir(parents=True, exist_ok=True)
    meta = {
        "folder": fname,
        "label": sanitize_label(label),
        "module": "os_upgrade",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reports": ACTION_REPORT_FILES,
    }
    (ws / "job_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return ws, fname


def new_workspace(root: Path, label: str = "work") -> Path:
    """하위 호환."""
    ws, _ = new_job_workspace(root, label)
    return ws


def report_path(workspace: Path, action: str) -> Path:
    filename = ACTION_REPORT_FILES.get(action, f"{action}.html")
    sub = CHECKLIST_OUTPUT_DIRS.get(action)
    if sub:
        path = workspace / sub / filename
    else:
        path = workspace / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
