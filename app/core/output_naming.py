from __future__ import annotations

import re
from datetime import datetime


def sanitize_label(text: str, *, max_len: int = 48) -> str:
    """파일/폴더명용 라벨 정규화."""
    s = re.sub(r'[<>:"/\\|?*]', "-", (text or "").strip())
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._-")
    return s[:max_len] if s else "work"


def make_dated_folder_name(label: str, *, now: datetime | None = None) -> str:
    """예: 20260523-150530_customer-site"""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}_{sanitize_label(label)}"
