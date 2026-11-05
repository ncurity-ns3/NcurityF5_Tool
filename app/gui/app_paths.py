from __future__ import annotations

import os
from pathlib import Path


def local_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "f5tool"
    return Path.home() / ".f5tool"
