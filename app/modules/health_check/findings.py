from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.health_check.common_eval import evaluate_common, results_to_findings
from app.modules.health_check.f5os_detect import f5os_collection_attempted, is_rseries_device


def _pool_findings(label: str, ltm: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    items = ltm.get("items") if isinstance(ltm, dict) else []
    if not isinstance(items, list):
        return findings
    for pool in items:
        if not isinstance(pool, dict):
            continue
        state = str(pool.get("availabilityState", "")).lower()
        if state and state not in ("available", "unknown"):
            name = pool.get("name", "pool")
            findings.append(f"{label}: pool unavailable — {name} ({state})")
    return findings


def _network_findings(label: str, network: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if not isinstance(network, dict):
        return findings
    for section in ("vlans", "self_ips"):
        block = network.get(section)
        if not isinstance(block, dict):
            continue
        items = block.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", section)
            if item.get("enabled") is False:
                findings.append(f"{label}: {section} disabled — {name}")
            oper = str(item.get("operStatus", item.get("status", ""))).lower()
            if oper in ("down", "disconnected", "failed"):
                findings.append(f"{label}: interface down — {name}")
    return findings


def _system_findings(label: str, system: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if not isinstance(system, dict):
        return findings
    cpu = system.get("cpuUsage") or system.get("cpu")
    if isinstance(cpu, (int, float)) and cpu >= 80:
        findings.append(f"{label}: high cpu usage — {cpu}%")
    return findings


def findings_from_device_record(device: dict[str, Any]) -> list[str]:
    label = str(device.get("device_label", "device"))
    data = device.get("data") if isinstance(device.get("data"), dict) else {}
    findings: list[str] = []
    for err in device.get("errors") or []:
        findings.append(f"{label}: {err}")
    common = data.get("common")
    if isinstance(common, dict):
        results = evaluate_common(
            tmos=common.get("tmos") if isinstance(common.get("tmos"), dict) else None,
            f5os=common.get("f5os") if isinstance(common.get("f5os"), dict) else None,
            is_rseries=is_rseries_device(data),
            f5os_attempted=f5os_collection_attempted(data),
        )
        findings.extend(results_to_findings(label, results))
    ltm = data.get("ltm", {})
    if isinstance(ltm, dict):
        pools = ltm.get("pools", ltm)
        findings.extend(_pool_findings(label, pools if isinstance(pools, dict) else {}))
    f5os = data.get("f5os")
    if isinstance(f5os, dict):
        health = f5os.get("health")
        if isinstance(health, dict):
            status = str(health.get("status", "")).lower()
            if status and status not in ("ok", "healthy", "up"):
                findings.append(f"{label}: f5os health — {status}")
    return findings


def summarize_job_dir(job_dir: Path) -> tuple[bool, int, list[str]]:
    """Return (healthy, unhealthy_count, all_findings)."""
    findings: list[str] = []
    exc_path = job_dir / "exceptions.json"
    if exc_path.is_file():
        try:
            for exc in json.loads(exc_path.read_text(encoding="utf-8")):
                if isinstance(exc, dict):
                    device = exc.get("device", "?")
                    msg = exc.get("message", "issue")
                    findings.append(f"{device}: {msg}")
        except json.JSONDecodeError:
            findings.append("exceptions.json parse error")

    raw_path = job_dir / "raw_collection.json"
    if raw_path.is_file():
        try:
            devices = json.loads(raw_path.read_text(encoding="utf-8"))
            if isinstance(devices, list):
                for device in devices:
                    if isinstance(device, dict):
                        findings.extend(findings_from_device_record(device))
        except json.JSONDecodeError:
            findings.append("raw_collection.json parse error")

    # de-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for f in findings:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return len(unique) == 0, len(unique), unique
