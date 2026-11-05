from __future__ import annotations

import re
from typing import Any

from app.modules.health_check.checklist_common import (
    CheckResult,
    ChecklistItemDef,
    load_checklist_defs,
)
from app.modules.health_check.f5os_detect import (
    f5os_collection_attempted,
    f5os_metrics_collected,
)
from app.modules.health_check.tmos_bash_parse import (
    CamValues,
    check_vlan_interfaces_up,
    compare_system_clock,
    format_uptime_display,
    is_virtual_edition_hardware,
    parse_df_paths,
    parse_ntpq_np,
    format_ssl_cert_detail,
    parse_ha_status,
    parse_ssl_cert_check_stdout,
    parse_sys_hardware_temp,
    parse_sys_performance,
    parse_sys_service,
    format_tmos_psu_value,
    parse_inlet_temperature_c,
    parse_tmos_psu_status,
    parse_tmos_psu_up_down,
    parse_uptime_stdout,
    split_clock_bash,
)
from app.modules.health_check.f5os_common import (
    check_f5os_vlan_interfaces_up,
    format_f5os_psu_value,
)


def _items_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("_unavailable"):
        return []
    items = payload.get("items")
    return items if isinstance(items, list) else []


def _dig_float(data: Any, *keys: str) -> float | None:
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                val = _dig_float(data[key])
                if val is not None:
                    return val
        for value in data.values():
            val = _dig_float(value)
            if val is not None:
                return val
    elif isinstance(data, (int, float)):
        return float(data)
    elif isinstance(data, str):
        m = re.search(r"[\d.]+", data)
        if m:
            try:
                return float(m.group())
            except ValueError:
                return None
    return None


def _result(
    item: ChecklistItemDef,
    *,
    status: str,
    value: str,
    detail: str = "",
    layer: str | None = None,
) -> CheckResult:
    return CheckResult(
        item_id=item.id,
        name=item.name,
        layer=layer or item.layer,
        status=status,
        value=value,
        criteria=item.criteria,
        detail=detail,
    )


def _skip(item: ChecklistItemDef, reason: str, layer: str | None = None) -> CheckResult:
    return _result(item, status="skip", value="—", detail=reason, layer=layer)


def _bash_stdout(tmos: dict[str, Any], key: str) -> str:
    block = tmos.get(key, {})
    if isinstance(block, dict):
        return str(block.get("bash_stdout", ""))
    return ""


def _tmos_meta(tmos: dict[str, Any]) -> dict[str, str]:
    meta = tmos.get("_meta")
    return meta if isinstance(meta, dict) else {}


def _tmos_identity(tmos: dict[str, Any]) -> str:
    meta = _tmos_meta(tmos)
    host = meta.get("tmos_host", "")
    name = meta.get("hostname", "")
    if name and host:
        return f"{name}@{host}"
    return str(name or host or "?")


def _bash_error(tmos: dict[str, Any], key: str) -> str:
    block = tmos.get(key, {})
    if isinstance(block, dict):
        return str(block.get("_bash_error", ""))
    return ""


def _needs_tmos_for_item(item: ChecklistItemDef, is_rseries: bool) -> bool:
    if item.layer == "tmos":
        return True
    if item.layer == "f5os":
        return False
    if is_rseries and item.id in ("power", "temperature", "interface"):
        return False
    return True


def evaluate_common(
    *,
    tmos: dict[str, Any] | None,
    f5os: dict[str, Any] | None,
    has_f5os_layer: bool = False,
    is_rseries: bool = False,
    f5os_attempted: bool = False,
) -> list[CheckResult]:
    defs = load_checklist_defs()
    tmos = tmos if isinstance(tmos, dict) else {}
    f5os = f5os if isinstance(f5os, dict) else {}
    has_f5 = bool(is_rseries and f5os_metrics_collected(f5os))
    if is_rseries:
        has_f5os_layer = f5os_attempted or has_f5
    results: list[CheckResult] = []

    for item in defs:
        if _needs_tmos_for_item(item, is_rseries) and not tmos:
            results.append(_skip(item, "TMOS 미수집", layer="tmos"))
            continue
        if item.layer == "f5os" and not has_f5os_layer:
            results.append(_skip(item, "F5OS 미해당 (iSeries)", layer="f5os"))
            continue
        fn = _EVALUATORS.get(item.id)
        if fn is None:
            results.append(_skip(item, "evaluator 없음"))
            continue
        results.extend(fn(item, tmos, f5os, has_f5, is_rseries))
    return results


def _eval_uptime(
    item: ChecklistItemDef,
    tmos: dict,
    f5os: dict,
    has_f5: bool,
    is_rseries: bool,
) -> list[CheckResult]:
    out: list[CheckResult] = []
    bash = _bash_stdout(tmos, "uptime")
    seconds = parse_uptime_stdout(bash) if bash else None
    if seconds is None or seconds < 300:
        err = _bash_error(tmos, "uptime")
        out.append(
            _skip(
                item,
                f"TMOS uptime bash 실패{(': ' + err[:120]) if err else ''}",
                layer="tmos",
            )
        )
    else:
        st = "warn" if seconds > 365 * 86400 else "pass"
        out.append(
            _result(
                item,
                status=st,
                value=format_uptime_display(seconds),
                layer="tmos",
                detail="tenant TMOS — bash uptime",
            )
        )
    return out if out else [_skip(item, "uptime 미수집")]


def _power_up_down_value(up: int, down: int) -> str:
    return f"{up} up / {down} down"


def _join_interface_names(names: list[str]) -> str:
    return ", ".join(names) if names else "—"


def _format_vlan_interface_status(
    up_list: list[str],
    down_list: list[str],
    *,
    vlan_count: int | None = None,
) -> tuple[str, str]:
    """Value/detail with separate Up vs Down interface name lists."""
    up_names = _join_interface_names(up_list)
    down_names = _join_interface_names(down_list)
    head = f"{len(up_list)} up / {len(down_list)} down"
    if vlan_count is not None:
        head = f"VLAN {vlan_count} · {head}"
    value = f"{head} | Up: {up_names} | Down: {down_names}"
    detail = f"Up: {up_names} | Down: {down_names}"
    return value, detail


def _mgmt_status_label(
    ports: list[dict[str, str]] | None = None,
    *,
    tmos_if_bash: str = "",
) -> tuple[str, str]:
    """Returns (status up|down|unknown, display label)."""
    if ports:
        for p in ports:
            if str(p.get("name", "")).lower() == "mgmt":
                st = str(p.get("status", "")).lower()
                label = "Up" if st == "up" else "Down" if st == "down" else st.capitalize()
                return st or "unknown", label
    if tmos_if_bash:
        from app.modules.health_check.tmos_bash_parse import parse_net_interface_status

        oper = parse_net_interface_status(tmos_if_bash)
        st = oper.get("mgmt", "unknown")
        label = "Up" if st == "up" else "Down" if st == "down" else st.capitalize()
        return st, label
    return "unknown", "?"


def _append_mgmt_to_interface(value: str, mgmt_label: str) -> str:
    return f"{value} | mgmt {mgmt_label}"


def _eval_power(
    item: ChecklistItemDef, tmos: dict, f5os: dict, has_f5: bool, is_rseries: bool
) -> list[CheckResult]:
    if is_rseries:
        if has_f5 and f5os:
            psu_health = f5os.get("psu_health")
            if isinstance(psu_health, dict) and psu_health:
                down_n = sum(1 for st in psu_health.values() if st != "up")
                return [
                    _result(
                        item,
                        status="fail" if down_n else "pass",
                        value=f"F5OS {format_f5os_psu_value(psu_health)}",
                        detail="show system health summary",
                        layer="f5os",
                    )
                ]
            psu_units = f5os.get("psu_units") or []
            if psu_units:
                parts = []
                for p in psu_units:
                    name = str(p.get("name", "psu")).lower()
                    st = "up" if p.get("ok") else "down"
                    parts.append(f"{name} {st}")
                down_n = sum(1 for p in psu_units if not p.get("ok"))
                return [
                    _result(
                        item,
                        status="fail" if down_n else "pass",
                        value=f"F5OS {' | '.join(parts)}",
                        detail="openconfig-platform PSU",
                        layer="f5os",
                    )
                ]
            notes = f5os.get("collect_notes") or []
            hint = "; ".join(notes[:3]) if isinstance(notes, list) else ""
            return [
                _skip(
                    item,
                    "F5OS PSU 미수집 — REST platform PSU·HTTPS CLI exec "
                    f"`show system health summary`{(' — ' + hint) if hint else ''}",
                    layer="f5os",
                )
            ]
        return [_skip(item, "F5OS 미수집 — F5OS IP/계정 확인", layer="f5os")]
    bash = _bash_stdout(tmos, "hardware")
    if bash and is_virtual_edition_hardware(bash):
        return [
            _result(
                item,
                status="pass",
                value="Virtual Edition — 전원 N/A",
                layer="tmos",
                detail="VM에는 PSU 없음",
            )
        ]
    if bash:
        psus = parse_tmos_psu_status(bash)
        if psus:
            down_n = sum(1 for _, st in psus if st != "up")
            return [
                _result(
                    item,
                    status="fail" if down_n else "pass",
                    value=f"TMOS {format_tmos_psu_value(psus)}",
                    layer="tmos",
                    detail="tmsh show sys hardware",
                )
            ]
        up_n, down_n = parse_tmos_psu_up_down(bash)
        if up_n or down_n:
            return [
                _result(
                    item,
                    status="fail" if down_n else "pass",
                    value=f"TMOS {_power_up_down_value(up_n, down_n)}",
                    layer="tmos",
                    detail="tmsh show sys hardware",
                )
            ]
    if tmos.get("hardware", {}).get("_unavailable") and not bash:
        return [_skip(item, "TMOS hardware bash 실패", layer="tmos")]
    return [_skip(item, "PSU 정보 파싱 실패 (show sys hardware)", layer="tmos")]


def _eval_temperature(
    item: ChecklistItemDef, tmos: dict, f5os: dict, has_f5: bool, is_rseries: bool
) -> list[CheckResult]:
    if is_rseries:
        if has_f5 and f5os:
            avg_t = f5os.get("temperature_avg_c")
            if avg_t is None and isinstance(f5os.get("temperature_cam"), CamValues):
                try:
                    avg_t = float(str(f5os["temperature_cam"].average))
                except ValueError:
                    avg_t = None
            if avg_t is not None and avg_t >= 10:
                st = "pass" if avg_t < 48 else "fail"
                return [
                    _result(
                        item,
                        status=st,
                        value=f"{avg_t:.1f}°C (avg)",
                        layer="f5os",
                        detail="F5OS platform temperature (average)",
                    )
                ]
        return [
            _skip(
                item,
                "F5OS 온도 미수집 (F5OS REST / platform state)",
                layer="f5os",
            )
        ]
    bash = _bash_stdout(tmos, "hardware")
    if is_virtual_edition_hardware(bash):
        return [
            _result(
                item,
                status="pass",
                value="Virtual Edition — 온도 N/A",
                layer="tmos",
                detail="VM에는 온도 센서 없음",
            )
        ]
    if bash:
        inlet = parse_inlet_temperature_c(bash)
        temp_c = inlet if inlet is not None else parse_sys_hardware_temp(bash)
        if temp_c is not None:
            st = "pass" if temp_c < 48 else "fail"
            return [
                _result(
                    item,
                    status=st,
                    value=f"{temp_c:.1f}°C",
                    layer="tmos",
                    detail="tmsh show sys hardware — Inlet Temp(degC)",
                )
            ]
    err = _bash_error(tmos, "hardware")
    return [_skip(item, f"온도 bash 실패{(': ' + err[:80]) if err else ''}", layer="tmos")]


def _eval_f5os_interfaces(item: ChecklistItemDef, f5os: dict) -> list[CheckResult]:
    ports = f5os.get("interface_ports") or []
    in_use_raw = f5os.get("vlan_in_use_interfaces")
    in_use = set(in_use_raw) if isinstance(in_use_raw, list) else set()
    vlan_count = f5os.get("vlan_count")
    if_source = f5os.get("interface_source", "rest")
    vlan_source = f5os.get("vlan_source", "rest")

    if not ports:
        return [
            _skip(
                item,
                "F5OS interface 미수집 (show interfaces summary / REST)",
                layer="f5os",
            )
        ]

    _, mgmt_label = _mgmt_status_label(ports)
    data_ports = [p for p in ports if str(p.get("name", "")).lower() != "mgmt"]

    if not in_use:
        if f5os.get("vlan_unavailable"):
            notes = f5os.get("collect_notes") or []
            hint = "; ".join(notes[:4]) if isinstance(notes, list) else ""
            detail = (
                "VLAN→IF 매핑 미수집 (REST vlan·HTTPS CLI show vlan) — "
                "인터페이스 목록만 있음 (항목 skip)"
            )
            if hint:
                detail += f" — {hint[:200]}"
        else:
            detail = "show vlans 미수집 — F5OS admin CLI 또는 VLAN REST 확인"
        return [_skip(item, detail, layer="f5os")]

    up_list, down_list = check_f5os_vlan_interfaces_up(in_use, data_ports or ports)
    value, if_detail = _format_vlan_interface_status(
        up_list, down_list, vlan_count=vlan_count
    )
    detail = (
        f"{if_detail} | show vlans ({vlan_source}) → "
        f"{', '.join(sorted(in_use))[:120]}; summary ({if_source}) | mgmt {mgmt_label}"
    )
    value = _append_mgmt_to_interface(value, mgmt_label)
    st = "fail" if down_list else ("pass" if up_list else "fail")
    if mgmt_label == "Down":
        st = "fail"
    return [_result(item, status=st, value=value, detail=detail, layer="f5os")]


def _eval_interface(
    item: ChecklistItemDef, tmos: dict, f5os: dict, has_f5: bool, is_rseries: bool
) -> list[CheckResult]:
    if is_rseries:
        if has_f5 and f5os:
            return _eval_f5os_interfaces(item, f5os)
        return [_skip(item, "F5OS interface 미수집 — F5OS IP/계정 확인", layer="f5os")]
    vlan_bash = _bash_stdout(tmos, "vlan_list")
    if_bash = _bash_stdout(tmos, "interfaces")
    if not vlan_bash or not if_bash:
        err = _bash_error(tmos, "vlan_list") or _bash_error(tmos, "interfaces")
        return [_skip(item, f"interface bash 실패{(': ' + err[:120]) if err else ''}")]
    up_list, down_list = check_vlan_interfaces_up(vlan_bash, if_bash)
    _, mgmt_label = _mgmt_status_label(tmos_if_bash=if_bash)
    value, if_detail = _format_vlan_interface_status(up_list, down_list)
    detail = f"{if_detail} | VLAN 사용 IF (tmsh list net vlan) | mgmt {mgmt_label}"
    value = _append_mgmt_to_interface(value, mgmt_label)
    st = "fail" if down_list else ("pass" if up_list else "fail")
    if mgmt_label == "Down":
        st = "fail"
    if not up_list and not down_list:
        return [
            _result(
                item,
                status="fail",
                value=_append_mgmt_to_interface("VLAN 사용 IF 없음", mgmt_label),
                detail="tmsh list net vlan 결과 확인",
                layer="tmos",
            )
        ]
    return [
        _result(item, status=st, value=value, detail=detail, layer="tmos")
    ]


def _eval_ntp(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    bash = _bash_stdout(tmos, "ntp")
    if bash:
        parsed = parse_ntpq_np(bash)
        if parsed["peers"]:
            if parsed["is_synced"]:
                peer = parsed["synced"][0]
                return [
                    _result(
                        item,
                        status="pass",
                        value=f"sync *{peer}",
                        layer="tmos",
                        detail="ntpq -np",
                    )
                ]
            return [
                _result(
                    item,
                    status="warn",
                    value=f"미동기 ({len(parsed['peers'])} peers)",
                    layer="tmos",
                    detail="ntpq -np — * 동기 peer 없음",
                )
            ]
        if "ntp server" in bash.lower() or "time-active" in bash.lower():
            return [
                _result(
                    item,
                    status="warn",
                    value="NTP 설정만 확인 (ntpq 없음)",
                    layer="tmos",
                    detail="ntpq -np 출력 없음 — tmsh list sys ntp?",
                )
            ]
        return [
            _result(
                item,
                status="warn",
                value="NTP peer 없음",
                layer="tmos",
                detail="ntpq -np",
            )
        ]
    err = _bash_error(tmos, "ntp")
    return [_skip(item, f"ntpq -np 실패{(': ' + err[:80]) if err else ''}", layer="tmos")]


def _eval_clock(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    bash = _bash_stdout(tmos, "clock")
    if bash.strip():
        date_part, clock_part = split_clock_bash(bash)
        if clock_part:
            ok, summary, drift = compare_system_clock(date_part, clock_part)
            if ok:
                return [
                    _result(
                        item,
                        status="pass",
                        value=summary[:80],
                        detail=drift,
                        layer="tmos",
                    )
                ]
            return [
                _result(
                    item,
                    status="fail",
                    value=summary[:80],
                    detail=drift,
                    layer="tmos",
                )
            ]
        return [_result(item, status="pass", value=date_part[:80], layer="tmos")]
    raw = tmos.get("clock", {})
    if raw.get("_unavailable"):
        return [_skip(item, "date / clock bash 실패")]
    val = str(raw.get("fullDate", raw.get("dateTime", raw.get("localTime", "OK"))))[:80]
    return [_result(item, status="pass", value=val, layer="tmos")]


def _eval_disk(
    item: ChecklistItemDef, tmos: dict, f5os: dict, has_f5: bool, is_rseries: bool
) -> list[CheckResult]:
    out: list[CheckResult] = []
    if not is_rseries and has_f5 and f5os:
        areas = f5os.get("disk_areas") or []
        if areas:
            parts: list[str] = []
            worst = 0.0
            for row in areas:
                if not isinstance(row, dict):
                    continue
                area = str(row.get("area", "?"))[:40]
                pct = float(row.get("percent", 0))
                parts.append(f"{area} {pct:.0f}%")
                worst = max(worst, pct)
            st = "pass" if worst < 80 else "fail"
            out.append(
                _result(
                    item,
                    status=st,
                    value="; ".join(parts[:4]),
                    detail="F5OS platform/tenant filesystems",
                    layer="f5os",
                )
            )
        else:
            out.append(_skip(item, "F5OS disk areas 없음", layer="f5os"))
    bash = _bash_stdout(tmos, "disk")
    if bash:
        paths = parse_df_paths(bash, ("/var", "/shared"))
        if not paths:
            out.append(_skip(item, "/var·/shared df 없음", layer="tmos"))
        else:
            parts: list[str] = []
            worst = 0.0
            for mount, pct in paths.items():
                parts.append(f"{mount} {pct:.0f}%")
                worst = max(worst, pct)
            st = "pass" if worst < 80 else "fail"
            out.append(
                _result(
                    item,
                    status=st,
                    value="; ".join(parts),
                    detail="Current/Avg/Max — df /var, /shared only",
                    layer="tmos",
                )
            )
    elif not out:
        err = _bash_error(tmos, "disk")
        out.append(_skip(item, f"disk bash 실패{(': ' + err[:120]) if err else ''}", layer="tmos"))
    return out if out else [_skip(item, "disk metrics unavailable")]


def _eval_daemons(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    bash = _bash_stdout(tmos, "services")
    if bash:
        found = parse_sys_service(bash)
        required = ("tmm", "bigd", "mcpd")
        missing = [r for r in required if r not in found]
        bad = [f"{k}={v}" for k, v in found.items() if str(v).lower() not in ("running", "run")]
        if missing:
            return [
                _result(
                    item,
                    status="fail",
                    value=f"missing: {', '.join(missing)} (bash)",
                    layer="tmos",
                )
            ]
        if bad:
            return [
                _result(
                    item,
                    status="fail",
                    value="; ".join(bad) + " (bash)",
                    layer="tmos",
                )
            ]
        return [
            _result(
                item,
                status="pass",
                value="tmm, bigd, mcpd (bash)",
                layer="tmos",
            )
        ]
    err = _bash_error(tmos, "services")
    return [
        _skip(
            item,
            f"services bash 실패{(': ' + err[:120]) if err else ''}",
            layer="tmos",
        )
    ]


def _parse_performance(tmos: dict) -> dict[str, Any]:
    bash = _bash_stdout(tmos, "performance")
    if bash:
        return parse_sys_performance(bash)
    return {}


def _cam_status(cam: CamValues, *, threshold: float | None = None) -> str:
    if threshold is None:
        return "pass"
    try:
        mx = float(str(cam.maximum).rstrip("%KMG"))
        return "warn" if mx >= threshold else "pass"
    except ValueError:
        return "pass"


def _eval_cpu(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    perf = _parse_performance(tmos)
    if not _bash_stdout(tmos, "performance"):
        return [
            _skip(
                item,
                f"performance bash 실패: {_bash_error(tmos, 'performance')[:80]}",
                layer="tmos",
            )
        ]
    cam = perf.get("cpu")
    if not isinstance(cam, CamValues):
        return [_skip(item, "CPU 블록 파싱 실패 (Sys::Performance CPU)", layer="tmos")]
    st = _cam_status(cam, threshold=80)
    return [
        _result(
            item,
            status=st,
            value=f"Cur/Avg/Max {cam.display()} %",
            detail="tmsh show sys performance",
            layer="tmos",
        )
    ]


def _eval_memory(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    perf = _parse_performance(tmos)
    if not _bash_stdout(tmos, "performance"):
        return [
            _skip(
                item,
                f"performance bash 실패: {_bash_error(tmos, 'performance')[:80]}",
                layer="tmos",
            )
        ]
    cam = perf.get("memory")
    if not isinstance(cam, CamValues):
        return [_skip(item, "Memory(TMM) 블록 파싱 실패", layer="tmos")]
    st = _cam_status(cam, threshold=80)
    return [
        _result(
            item,
            status=st,
            value=f"Cur/Avg/Max {cam.display()} %",
            detail="Sys::Performance Memory Used(%) — TMM Memory Used",
            layer="tmos",
        )
    ]


def _eval_concurrent_connections(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    perf = _parse_performance(tmos)
    if not _bash_stdout(tmos, "performance"):
        return [
            _skip(
                item,
                f"performance bash 실패: {_bash_error(tmos, 'performance')[:80]}",
                layer="tmos",
            )
        ]
    cam = perf.get("active_connections")
    if not isinstance(cam, CamValues):
        return [_skip(item, "Active Connections 파싱 실패", layer="tmos")]
    return [
        _result(
            item,
            status="pass",
            value=f"Cur/Avg/Max {cam.display()}",
            detail="Sys::Performance Connections → Active Connections",
            layer="tmos",
        )
    ]


def _eval_new_connections(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    perf = _parse_performance(tmos)
    if not _bash_stdout(tmos, "performance"):
        return [_skip(item, f"performance bash 실패: {_bash_error(tmos, 'performance')[:80]}")]
    client = perf.get("client_connections")
    if not isinstance(client, CamValues):
        return [_skip(item, "Client Connections(/sec) 파싱 실패", layer="tmos")]
    return [
        _result(
            item,
            status="pass",
            value=f"Client {client.display()}",
            detail="Total New Connections(/sec) — Client only",
            layer="tmos",
        )
    ]


def _eval_throughput(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    perf = _parse_performance(tmos)
    if not _bash_stdout(tmos, "performance"):
        return [_skip(item, f"performance bash 실패: {_bash_error(tmos, 'performance')[:80]}")]
    cam = perf.get("throughput")
    if not isinstance(cam, CamValues):
        return [_skip(item, "Throughput(bits) Service 파싱 실패", layer="tmos")]
    return [
        _result(
            item,
            status="pass",
            value=f"Bits/sec {cam.display()}",
            detail="Sys::Performance Throughput(bits) — Service",
            layer="tmos",
        )
    ]


def _eval_ssl_cert(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    bash = _bash_stdout(tmos, "certs")
    if bash:
        counts = parse_ssl_cert_check_stdout(bash)
        expired = counts["expired"]
        will_expire = counts["will_expire"]
        detail = format_ssl_cert_detail(bash)
        return [
            _result(
                item,
                status="pass",
                value=f"만료 {expired} | 만료예정 {will_expire}",
                detail=detail,
                layer="tmos",
            )
        ]
    raw = tmos.get("certs", {})
    if raw.get("_unavailable"):
        err = _bash_error(tmos, "certs")
        return [
            _skip(
                item,
                f"check-cert bash 실패{(': ' + err[:80]) if err else ''}",
                layer="tmos",
            )
        ]
    return [_skip(item, "check-cert bash 출력 없음", layer="tmos")]


def _eval_ha_status(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    bash = _bash_stdout(tmos, "failover")
    if bash:
        status, detail = parse_ha_status(bash)
        if status == "Unknown":
            return [
                _result(
                    item,
                    status="skip",
                    value="Unknown",
                    detail=detail,
                    layer="tmos",
                )
            ]
        result_status = "fail" if status == "Force Offline" else "pass"
        return [
            _result(
                item,
                status=result_status,
                value=status,
                detail=detail,
                layer="tmos",
            )
        ]
    err = _bash_error(tmos, "failover")
    return [
        _skip(
            item,
            f"HA bash 실패{(': ' + err[:80]) if err else ''}",
            layer="tmos",
        )
    ]


def _eval_policy_backup(
    item: ChecklistItemDef, tmos: dict, _f5: dict, _hf: bool, is_rseries: bool
) -> list[CheckResult]:
    action = tmos.get("backup_action", {})
    if isinstance(action, dict):
        if action.get("skipped"):
            return [
                _result(
                    item,
                    status="pass",
                    value="백업 옵션 미선택",
                    detail=str(
                        action.get("detail", "«점검 시 UCS 백업 수행» 미체크 — 정상")
                    ),
                    layer="tmos",
                )
            ]
        if action.get("scheduled"):
            fname = str(action.get("filename") or "ucs")
            return [
                _result(
                    item,
                    status="pass",
                    value="점검 후 백그라운드 예정",
                    detail=(
                        f"예상 파일: {fname}. "
                        "점검·리포트 완료 뒤 save 시작 — ucs_backup.log 참고"
                    )[:200],
                    layer="tmos",
                )
            ]
        if action.get("performed"):
            if action.get("background"):
                fname = str(action.get("filename") or "ucs")
                return [
                    _result(
                        item,
                        status="pass",
                        value="백그라운드 수행 중",
                        detail=(
                            f"예상 파일: {fname}. "
                            "완료/실패는 job 폴더 ucs_backup.log 참고"
                        )[:200],
                        layer="tmos",
                    )
                ]
            if action.get("ok"):
                detail = str(action.get("detail") or "tmsh save sys ucs")
                return [
                    _result(
                        item,
                        status="success",
                        value=f"save 완료: {action.get('filename', 'ucs')}",
                        detail=detail[:200],
                        layer="tmos",
                    )
                ]
            return [
                _result(
                    item,
                    status="fail",
                    value="save 실패",
                    detail=str(
                        action.get("error", action.get("detail", action.get("stdout", "")))
                    )[:200],
                    layer="tmos",
                )
            ]
    return [
        _result(
            item,
            status="pass",
            value="백업 옵션 미선택",
            detail="«점검 시 UCS 백업 수행» 미체크",
            layer="tmos",
        )
    ]


_EVALUATORS = {
    "uptime": _eval_uptime,
    "power": _eval_power,
    "temperature": _eval_temperature,
    "interface": _eval_interface,
    "ntp": _eval_ntp,
    "clock": _eval_clock,
    "disk": _eval_disk,
    "daemons": _eval_daemons,
    "cpu": _eval_cpu,
    "memory": _eval_memory,
    "concurrent_connections": _eval_concurrent_connections,
    "new_connections": _eval_new_connections,
    "throughput": _eval_throughput,
    "ssl_cert": _eval_ssl_cert,
    "ha_status": _eval_ha_status,
    "policy_backup": _eval_policy_backup,
}


def results_to_findings(label: str, results: list[CheckResult]) -> list[str]:
    findings: list[str] = []
    for r in results:
        if r.status == "fail":
            findings.append(f"{label}: [{r.layer}] {r.name} — FAIL ({r.value}) {r.detail}".strip())
        elif r.status == "warn":
            findings.append(f"{label}: [{r.layer}] {r.name} — WARN ({r.value}) {r.detail}".strip())
    return findings
