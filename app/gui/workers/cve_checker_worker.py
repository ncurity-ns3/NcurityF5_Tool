"""Background CVE lookup. The thread stays owned by the view."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.modules.nhealth.cve_lookup import CveHit, CveLookupError, lookup_k_cves, write_cve_report


@dataclass(frozen=True)
class CveSearchResult:
    headline: str
    hits: tuple[CveHit, ...]
    report_path: Path


class CveCheckerWorker(QThread):
    progressed = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        cache_dir: Path,
        report_dir: Path,
        version: str,
        pasted: str = "",
    ) -> None:
        super().__init__()
        self.cache_dir = cache_dir
        self.report_dir = report_dir
        self.version = version
        self.pasted = pasted

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._result())
        except CveLookupError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))

    def _result(self) -> CveSearchResult:
        self.progressed.emit(8, "K 문서를 확인하는 중…")
        hits = lookup_k_cves(
            self.version,
            self.pasted,
            self.cache_dir.parent / "f5_articles",
            on_progress=self._tick,
            nvd_cache=self.cache_dir.parent / "cve_cache",
            on_nvd=self._nvd,
        )
        heading = self._heading(self.version, hits)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.report_dir / f"{stamp}_cve.html"
        write_cve_report(path, heading, hits)
        self.progressed.emit(100, "완료")
        return CveSearchResult(heading, tuple(hits), path)

    def _heading(self, version: str, hits: list[CveHit]) -> str:
        fixed = sum(1 for hit in hits if hit.status.endswith(" Fixed"))
        affected = sum(1 for hit in hits if hit.status == "해당됨")
        scope = "선택한 CVE" if self.pasted.strip() else "K 문서 CVE"
        return f"{version} · {scope} {len(hits)}건 · Fixed {fixed} · 해당 {affected}"

    def _tick(self, done: int, total: int) -> None:
        span = 10 + int(30 * done / max(total, 1))
        self.progressed.emit(min(40, span), f"K 문서 확인 {done}/{total}")

    def _nvd(self, done: int, total: int) -> None:
        span = 40 + int(55 * done / max(total, 1))
        self.progressed.emit(min(95, span), f"NVD Severity 확인 {done}/{total}")
