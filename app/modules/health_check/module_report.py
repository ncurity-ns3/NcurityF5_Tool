from __future__ import annotations

from typing import Any

from app.core.models import CollectionResult

_MODULE_LABELS = {
    "ltm": "LTM",
    "apm": "APM",
    "awaf": "AWAF",
}

_LTM_ROWS = (
    ("pools", "Pool"),
    ("virtual_servers", "Virtual Server"),
    ("nodes", "Node"),
)

_APM_ROWS = (
    ("access_profiles", "Access Profile"),
    ("sessions", "Session"),
    ("license", "License"),
)

_AWAF_ROWS = (
    ("policies", "ASM Policy"),
    ("signature_update", "Signature Update"),
)


def _http_unavailable_detail(block: dict[str, Any]) -> str:
    err = str(block.get("_error") or "").strip()
    path = str(block.get("_path") or "")
    code = block.get("_http_status")
    if code == 400 or (err and "400" in err):
        return "HTTP 400 — APM/AWAF 미프로비저닝·라이선스 없음·REST 미지원"
    if code == 404 or (err and "404" in err):
        return f"HTTP 404 — 엔드포인트 없음 ({path})" if path else "HTTP 404"
    if code in (401, 403) or (err and ("401" in err or "403" in err)):
        return f"HTTP 권한 오류 — {err[:80]}" if err else f"HTTP {code}"
    if err:
        return err[:120]
    if path:
        return f"조회 불가 ({path})"
    return "unavailable"


def _summarize_apm_sessions(block: Any) -> tuple[str, str]:
    if isinstance(block, dict) and block.get("metric") == "session_total":
        val = block.get("value")
        if isinstance(val, int):
            return str(val), "show apm access-info | grep Total"
        err = block.get("_parse_error") or block.get("_error")
        if err:
            return "—", str(err)[:120]
        raw = str(block.get("bash_stdout") or "")[:100]
        return "—", raw or "Total 미확인"
    return _summarize_rest_block(block)


def _summarize_apm_license(block: Any) -> tuple[str, str]:
    if isinstance(block, dict) and block.get("metric") == "license_ccu":
        conn = block.get("connectivity_total")
        if conn:
            detail = str(block.get("detail") or "tmsh show apm license")
            return f"{conn} CCU", detail[:120]
        avail = block.get("available_ccu")
        if avail is not None:
            detail = str(block.get("detail") or "tmsh show apm license")
            return f"{avail} CCU", detail[:120]
        err = block.get("_parse_error") or block.get("_error")
        if err:
            return "—", str(err)[:120]
        raw = str(block.get("bash_stdout") or "")[:100]
        return "—", raw or "Available CCU 미확인"
    return _summarize_rest_block(block)


def _summarize_rest_block(block: Any) -> tuple[str, str]:
    if not isinstance(block, dict):
        return "—", "데이터 없음"
    if block.get("_source") == "bash":
        count = block.get("list_count")
        cmd = str(block.get("_bash_cmd") or "tmsh")[:80]
        if isinstance(count, int) and count >= 0:
            return str(count), f"bash fallback ({cmd})"
        text = str(block.get("bash_stdout") or "").strip()
        if text:
            return "OK", text[:100]
        bash_err = block.get("_bash_error")
        if bash_err:
            return "—", str(bash_err)[:120]
        return "—", "bash 출력 없음"
    if block.get("_unavailable"):
        return "—", _http_unavailable_detail(block)
    items = block.get("items")
    if isinstance(items, list):
        n = len(items)
        if n == 0:
            return "0", "항목 없음 (객체 없음)"
        return str(n), f"{n}개 REST 항목"
    if block.get("kind") or block.get("selfLink"):
        return "1", "단일 REST 객체"
    return "—", "items 배열 없음"


_APM_SUMMARIZERS: dict[str, Any] = {
    "sessions": _summarize_apm_sessions,
    "license": _summarize_apm_license,
}


def _module_rows(
    data: dict[str, Any],
    spec: tuple[tuple[str, str], ...],
    *,
    summarizers: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, label in spec:
        block = data.get(key)
        fn = (summarizers or {}).get(key)
        if fn:
            value, detail = fn(block)
        else:
            value, detail = _summarize_rest_block(block)
        rows.append({"object": label, "value": value, "detail": detail})
    return rows


def build_module_summary_for_device(data: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    if isinstance(data.get("ltm"), dict):
        out["ltm"] = _module_rows(data["ltm"], _LTM_ROWS)
    if isinstance(data.get("apm"), dict):
        out["apm"] = _module_rows(data["apm"], _APM_ROWS, summarizers=_APM_SUMMARIZERS)
    if isinstance(data.get("awaf"), dict):
        out["awaf"] = _module_rows(data["awaf"], _AWAF_ROWS)
    return out


def build_module_summary_by_device(
    devices: list[CollectionResult],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    by_label: dict[str, dict[str, list[dict[str, str]]]] = {}
    for device in devices:
        data = device.data if isinstance(device.data, dict) else {}
        summary = build_module_summary_for_device(data)
        if summary:
            by_label[device.device_label] = summary
    return by_label


def module_section_title(module_key: str) -> str:
    return _MODULE_LABELS.get(module_key, module_key.upper())
