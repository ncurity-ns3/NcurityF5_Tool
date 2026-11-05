from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.output_naming import sanitize_label
from app.modules.os_upgrade.ucs_config_check import UcsConfigCheckResult, analyze_ucs_config_texts
from app.modules.os_upgrade.ucs_check_report import write_ucs_check_html
from app.modules.os_upgrade.ucs_reader import UcsReadError, read_ucs_config_texts


def default_unit_label(index: int) -> str:
    """목록 순서 기준 호기 라벨 (1호기, 2호기, …)."""
    return f"{index + 1}호기"


def display_unit_label(unit_label: str, hostname: str) -> str:
    host = (hostname or "").strip()
    if host and host not in unit_label:
        return host
    return unit_label


def labels_for_ucs_paths(
    paths: list[Path],
    *,
    custom_labels: list[str] | None = None,
    auto_unit_labels: bool = True,
) -> list[str]:
    if custom_labels and len(custom_labels) == len(paths):
        return [lb.strip() or default_unit_label(i) for i, lb in enumerate(custom_labels)]
    if auto_unit_labels:
        return [default_unit_label(i) for i in range(len(paths))]
    return [p.stem or default_unit_label(i) for i, p in enumerate(paths)]


@dataclass
class UcsBatchExtractResult:
    units: list["UcsExtractResult"] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        return [u.summary_line() for u in self.units]


@dataclass
class UcsExtractResult:
    device_label: str
    source_file: str
    source_path: str = ""
    unit_label: str = ""
    check: UcsConfigCheckResult = field(default_factory=UcsConfigCheckResult)
    config_files_found: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def hostname(self) -> str:
        return self.check.hostname

    def summary_line(self) -> str:
        return self.check.brief_summary_line()


def extract_ucs(
    ucs_path: Path,
    *,
    device_label: str = "",
    unit_label: str = "",
    target_version: str | None = None,
) -> UcsExtractResult:
    unit = unit_label.strip() or device_label.strip() or ucs_path.name
    result = UcsExtractResult(
        device_label=unit,
        unit_label=unit,
        source_file=ucs_path.name,
        source_path=str(ucs_path.resolve()),
    )

    try:
        texts = read_ucs_config_texts(ucs_path)
    except UcsReadError as exc:
        result.errors.append(str(exc))
        return result

    result.config_files_found = sorted(
        k for k in texts if k.endswith(".conf") or k.endswith(".license") or k == "VERSION"
    )
    result.check = analyze_ucs_config_texts(texts, target_version=target_version)
    result.errors.extend(result.check.errors)
    result.device_label = display_unit_label(unit, result.check.hostname)
    return result


def extract_ucs_batch(
    ucs_paths: list[Path],
    *,
    labels: list[str] | None = None,
    auto_unit_labels: bool = True,
    target_version: str | None = None,
) -> UcsBatchExtractResult:
    batch = UcsBatchExtractResult()
    if not ucs_paths:
        return batch
    unit_labels = labels_for_ucs_paths(
        ucs_paths, custom_labels=labels, auto_unit_labels=auto_unit_labels
    )
    for path, unit in zip(ucs_paths, unit_labels):
        try:
            batch.units.append(
                extract_ucs(
                    path,
                    unit_label=unit,
                    device_label=unit,
                    target_version=target_version,
                )
            )
        except Exception as exc:  # noqa: BLE001
            batch.failures.append({"file": path.name, "message": str(exc)})
    return batch


def _serialize_ucs(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, list):
        return [_serialize_ucs(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize_ucs(v) for k, v in obj.items()}
    return obj


def write_ucs_extract_outputs(
    workspace: Path,
    extracted: UcsExtractResult,
    *,
    ucs_source: Path | None = None,
) -> Path:
    batch = UcsBatchExtractResult(units=[extracted])
    if ucs_source:
        batch.failures = []
    return write_ucs_batch_outputs(workspace, batch)


def write_ucs_batch_outputs(
    workspace: Path,
    batch: UcsBatchExtractResult,
    *,
    site_name: str = "",
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)

    def _source_for(unit: UcsExtractResult) -> Path | None:
        if unit.source_path:
            p = Path(unit.source_path)
            if p.is_file():
                return p
        return None

    meta = {
        "site_name": site_name,
        "unit_count": len(batch.units),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "units": [
            {
                "unit_label": u.unit_label or u.device_label,
                "device_label": u.device_label,
                "source_ucs": str(_source_for(u) or u.source_file),
                "hostname": u.hostname,
            }
            for u in batch.units
        ],
        "failures": batch.failures,
    }
    (workspace / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    payload = {
        "units": [_serialize_ucs(u) for u in batch.units],
        "failures": batch.failures,
    }
    (workspace / "extracted.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    units_dir = workspace / "units"
    units_dir.mkdir(exist_ok=True)
    for unit in batch.units:
        safe = sanitize_label(unit.unit_label or unit.device_label) or "unit"
        unit_dir = units_dir / safe
        unit_dir.mkdir(exist_ok=True)
        (unit_dir / "extracted.json").write_text(
            json.dumps(_serialize_ucs(unit), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        src = _source_for(unit)
        if src:
            (unit_dir / "source.path.txt").write_text(str(src), encoding="utf-8")

    title = "UCS 점검"
    if site_name:
        title += f" — {site_name}"
    if batch.units:
        title += f" ({len(batch.units)}대)"

    html_path = workspace / "report.html"
    write_ucs_check_html(html_path, [u.check for u in batch.units], title=title)
    return html_path


def new_ucs_workspace(output_root: Path, ucs_path: Path) -> Path:
    return new_ucs_batch_workspace(output_root, ucs_path.stem)


def new_ucs_batch_workspace(output_root: Path, site_name: str = "") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = sanitize_label(site_name) or "ucs"
    ws = output_root / f"ucs_{stamp}_{safe}"
    ws.mkdir(parents=True, exist_ok=True)
    return ws
