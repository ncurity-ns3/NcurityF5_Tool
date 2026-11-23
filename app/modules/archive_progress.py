"""Count bytes read from an archive so a progress bar can follow the file."""

from __future__ import annotations

import tarfile
from collections.abc import Callable
from pathlib import Path


class CountingFile:
    def __init__(
        self,
        handle,
        total: int,
        on_percent: Callable[[int], None] | None,
    ) -> None:
        self._handle = handle
        self._total = max(total, 1)
        self._on_percent = on_percent
        self._seen = 0
        self._last = -1

    def read(self, size: int = -1) -> bytes:
        data = self._handle.read(size)
        self._seen += len(data)
        self._report()
        return data

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._handle.seek(offset, whence)

    def tell(self) -> int:
        return self._handle.tell()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._handle.fileno()

    def close(self) -> None:
        self._handle.close()

    def _report(self) -> None:
        if self._on_percent is None:
            return
        percent = min(95, self._seen * 95 // self._total)
        if percent == self._last:
            return
        self._last = percent
        self._on_percent(percent)


def open_counted_tar(
    path: Path,
    on_percent: Callable[[int], None] | None = None,
) -> tuple[tarfile.TarFile, CountingFile]:
    handle = path.open("rb")
    counted = CountingFile(handle, path.stat().st_size, on_percent)
    try:
        archive = tarfile.open(fileobj=counted, mode="r:*")
    except (tarfile.TarError, OSError):
        counted.close()
        raise
    return archive, counted
