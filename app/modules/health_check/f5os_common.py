from __future__ import annotations

import re
from typing import Any

from app.core.f5os_client import F5osClient
from app.modules.health_check.tmos_bash_parse import CamValues


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_f5os_uptime_text(text: str) -> float | None:
    """F5OS show system uptime: \"1w, 1d, 2h, 5m, 45s\"."""
    if not text:
        return None
    total = 0.0
    units = {
        "w": 604800,
        "d": 86400,
        "h": 3600,
        "m": 60,
        "s": 1,
    }
    for m in re.finditer(r"(\d+)\s*([wdhms])\b", text, re.I):
        total += int(m.group(1)) * units.get(m.group(2).lower(), 0)
    return total if total > 0 else None


def _uptime_from_payload(payload: dict[str, Any]) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("uptime", "up-time", "upTime"):
        raw = payload.get(key)
        if isinstance(raw, str):
            sec = parse_f5os_uptime_text(raw)
            if sec:
                return sec
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
    state = payload.get("state")
    if isinstance(state, dict):
        return _uptime_from_payload(state)
    return None


def parse_f5os_overview(overview: dict[str, Any]) -> dict[str, Any]:
    """HW metrics from openconfig-platform components."""
    if not isinstance(overview, dict):
        return {}
    temps: list[float] = []
    temp_cam: CamValues | None = None
    disk_areas: list[dict[str, Any]] = []
    psu_units: list[dict[str, Any]] = []
    platform_desc = ""

    block = overview.get("openconfig-platform:components")
    if not isinstance(block, dict):
        return {}
    components = block.get("component", [])
    if not isinstance(components, list):
        return {}

    for comp in components:
        if not isinstance(comp, dict):
            continue
        state = comp.get("state") if isinstance(comp.get("state"), dict) else {}
        name = str(comp.get("name", ""))
        if name == "platform" and isinstance(state, dict):
            platform_desc = str(state.get("description", ""))
            temp_block = state.get("f5-platform:temperature")
            if isinstance(temp_block, dict):
                cur = _to_float(temp_block.get("current"))
                avg = _to_float(temp_block.get("average"))
                mx = _to_float(temp_block.get("maximum"))
                if cur is not None and avg is not None and mx is not None:
                    temp_cam = CamValues(
                        current=str(cur),
                        average=str(avg),
                        maximum=str(mx),
                    )
                for key in ("current", "maximum", "average"):
                    val = _to_float(temp_block.get(key))
                    if val is not None and -20 <= val <= 100:
                        temps.append(val)
            fs_block = state.get("f5-platform:file-systems")
            if isinstance(fs_block, dict):
                for fs in fs_block.get("file-system", []) or []:
                    if isinstance(fs, dict):
                        area = str(fs.get("area", fs.get("category", "?")))
                        pct = _to_float(fs.get("used-percent"))
                        if pct is not None:
                            disk_areas.append({"area": area, "percent": pct})
        if isinstance(state, dict) and name.startswith("psu"):
            psu_stats = state.get("f5-fan-psu-stats:psu-stats")
            if not isinstance(psu_stats, dict):
                psu_stats = state.get("psu-stats")
            st = _psu_status_from_component_state(state, psu_stats if isinstance(psu_stats, dict) else None)
            if st:
                psu_units.append(
                    {
                        "name": name,
                        "status": st,
                        "ok": st == "up",
                    }
                )

    temp_avg: float | None = _to_float(temp_cam.average) if temp_cam else None
    if temp_avg is None:
        for comp in components:
            if not isinstance(comp, dict) or comp.get("name") != "platform":
                continue
            st = comp.get("state") if isinstance(comp.get("state"), dict) else {}
            tb = st.get("f5-platform:temperature") if isinstance(st, dict) else None
            if isinstance(tb, dict):
                temp_avg = _to_float(tb.get("average"))
                break

    return {
        "platform": platform_desc,
        "temperatures_c": temps,
        "temperature_avg_c": temp_avg,
        "max_temperature_c": max(temps) if temps else None,
        "temperature_cam": temp_cam,
        "disk_areas": disk_areas,
        "psu_units": psu_units,
        "psu_components": [p["name"] for p in psu_units],
        "psu_ok": all(p.get("ok") for p in psu_units) if psu_units else False,
    }


def _temperature_from_block(
    temp_block: dict[str, Any],
) -> tuple[CamValues | None, float | None, float | None]:
    if not isinstance(temp_block, dict):
        return None, None, None
    cur = _to_float(temp_block.get("current"))
    avg = _to_float(temp_block.get("average"))
    mx = _to_float(temp_block.get("maximum"))
    temps = [v for v in (cur, avg, mx) if v is not None and -20 <= v <= 100]
    cam = None
    if cur is not None and avg is not None and mx is not None:
        cam = CamValues(current=str(cur), average=str(avg), maximum=str(mx))
    return cam, avg, (max(temps) if temps else None)


_IFACE_NAME = re.compile(r"^(\d+\.\d+|mgmt|[A-Za-z][\w.-]*)$", re.I)


def _psu_status_from_component_state(
    state: dict[str, Any],
    psu_stats: dict[str, Any] | None = None,
) -> str | None:
    """Map openconfig-platform PSU component state → up/down."""
    if not isinstance(state, dict):
        return None
    if state.get("empty") is True:
        return "down"
    health = str(state.get("health", state.get("oper-status", ""))).lower()
    if health in ("ok", "up", "good"):
        return "up"
    if health in ("fail", "critical", "down", "error", "not-ok", "not ok"):
        return "down"
    stats = psu_stats if isinstance(psu_stats, dict) else {}
    pin = _to_float(stats.get("psu-power-in"))
    if pin is not None and pin > 0:
        return "up"
    if pin is not None:
        return "down"
    if state.get("empty") is False:
        return "up"
    return None


def _component_state_from_get(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    comp = body.get("openconfig-platform:component")
    if isinstance(comp, dict):
        st = comp.get("state")
        return st if isinstance(st, dict) else comp
    block = body.get("openconfig-platform:components")
    if isinstance(block, dict):
        items = block.get("component", [])
        if isinstance(items, list) and items and isinstance(items[0], dict):
            st = items[0].get("state")
            return st if isinstance(st, dict) else items[0]
    st = body.get("state")
    return st if isinstance(st, dict) else body


def collect_psu_health_rest(client: F5osClient, prefix: str, overview: dict[str, Any]) -> dict[str, str]:
    """PSU up/down via openconfig-platform (same REST path family as temperature)."""
    found: dict[str, str] = {}
    block = overview.get("openconfig-platform:components")
    if isinstance(block, dict):
        components = block.get("component", [])
        if isinstance(components, list):
            for comp in components:
                if not isinstance(comp, dict):
                    continue
                name = str(comp.get("name", "")).lower()
                if not name.startswith("psu"):
                    continue
                state = comp.get("state") if isinstance(comp.get("state"), dict) else {}
                st = _psu_status_from_component_state(state)
                if st:
                    found[name] = st

    for idx in range(1, 5):
        comp_name = f"psu-{idx}"
        if comp_name in found:
            continue
        for sub in ("", "/state"):
            path = f"{prefix}/data/openconfig-platform:components/component={comp_name}{sub}"
            try:
                body = client.get(path)
                state = _component_state_from_get(body)
                st = _psu_status_from_component_state(state)
                if st:
                    found[comp_name] = st
                    break
            except Exception:  # noqa: BLE001
                continue

    for path in (
        f"{prefix}/data/openconfig-platform:components",
        f"{prefix}/data/openconfig-system:system/health",
    ):
        try:
            body = client.get(path)
            found.update(_parse_psu_health_from_json(body))
        except Exception:  # noqa: BLE001
            continue
    return found


def _parse_psu_health_from_json(node: Any) -> dict[str, str]:
    """Walk JSON for psu-N nodes with health ok/down."""
    out: dict[str, str] = {}

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            name = str(obj.get("name", "")).lower()
            if name.startswith("psu-"):
                st = _psu_status_from_component_state(obj.get("state", obj))
                if st:
                    out[name] = st
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(node)
    return out


def parse_f5os_show_vlans(text: str) -> tuple[int, set[str]]:
    """F5OS admin CLI `show vlan` / `show vlans` — VLAN rows and bound interface names."""
    in_use: set[str] = set()
    vlan_rows = 0
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^-+$", s):
            in_table = True
            continue
        if "VLAN" in s.upper() and "INTERFACE" in s.upper():
            continue
        if not in_table:
            continue
        row = re.match(r"^(\d+)\s+(\S+)", s)
        if row:
            vlan_rows += 1
            if _IFACE_NAME.match(row.group(2)):
                in_use.add(row.group(2))
            continue
        token = s.split()[0]
        if _IFACE_NAME.match(token):
            in_use.add(token)
    return vlan_rows, in_use


def parse_f5os_interfaces_summary(text: str) -> list[dict[str, str]]:
    """F5OS admin CLI `show interfaces interface summary` (or legacy summary)."""
    ports: list[dict[str, str]] = []
    name_idx = 0
    status_idx: int | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("---"):
            continue
        parts = s.split()
        if not parts:
            continue
        upper = [p.upper() for p in parts]
        if "NAME" in upper:
            name_idx = upper.index("NAME")
            if "STATUS" in upper:
                status_idx = upper.index("STATUS")
            elif "OPER" in upper and "STATUS" in upper[upper.index("OPER") :]:
                status_idx = upper.index("OPER") + 1
            continue
        if status_idx is None or len(parts) <= status_idx:
            if _IFACE_NAME.match(parts[0]) and len(parts) >= 5:
                name, status = parts[0], parts[4]
            else:
                continue
        else:
            if len(parts) <= name_idx:
                continue
            name, status = parts[name_idx], parts[status_idx]
        if not _IFACE_NAME.match(name):
            continue
        oper = status.upper()
        if oper == "UP":
            st = "up"
        elif oper == "DOWN":
            st = "down"
        else:
            st = status.lower()
        ports.append({"name": name, "status": st})
    return ports


def parse_f5os_system_health_summary_psu(text: str) -> dict[str, str]:
    """`show system health summary` — lines containing psu-N and health ok/up."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        m = re.search(r"\b(psu-\d+)\b", line, re.I)
        if not m:
            continue
        key = m.group(1).lower()
        low = line.lower()
        if re.search(r"\bok\b", low) or re.search(r"\bup\b", low):
            found[key] = "up"
        elif re.search(r"\b(down|fail|critical|error|not\s+ok)\b", low):
            found[key] = "down"
        elif key not in found:
            found[key] = "down"
    if found:
        return dict(sorted(found.items()))
    return {f"psu-{i}": "down" for i in (1, 2)}


def format_f5os_psu_value(states: dict[str, str]) -> str:
    return " | ".join(f"{name} {st}" for name, st in sorted(states.items()))


def parse_f5os_vlan_count(body: dict[str, Any]) -> int:
    block = body.get("openconfig-vlan:vlans")
    if not isinstance(block, dict):
        block = body
    vlans = block.get("vlan", [])
    if not isinstance(vlans, list):
        return 0
    return sum(1 for v in vlans if isinstance(v, dict))


def parse_f5os_vlan_in_use_from_vlans(body: dict[str, Any]) -> set[str]:
    """openconfig-vlan REST — VLAN→interface (show vlan equivalent)."""
    block = body.get("openconfig-vlan:vlans")
    if not isinstance(block, dict):
        block = body
    vlans = block.get("vlan", [])
    if not isinstance(vlans, list):
        return set()
    in_use: set[str] = set()

    def _add_iface(name: str | None) -> None:
        if name and _IFACE_NAME.match(name) and name != "mgmt":
            in_use.add(name)

    def _iface_from_member(node: Any) -> str | None:
        if not isinstance(node, dict):
            return None
        for key in ("interface", "interface-ref", "name"):
            val = node.get(key)
            if isinstance(val, str) and val.strip() and val != "mgmt":
                return val.strip()
            if isinstance(val, dict):
                name = val.get("interface") or val.get("name")
                if isinstance(name, str) and name.strip() and name != "mgmt":
                    return name.strip()
        return None

    for vlan in vlans:
        if not isinstance(vlan, dict):
            continue
        cfg = vlan.get("config") if isinstance(vlan.get("config"), dict) else {}
        for key in ("interface", "bind-interface", "interface-ref"):
            val = vlan.get(key) or cfg.get(key)
            if isinstance(val, str):
                _add_iface(val.strip())
            elif isinstance(val, dict):
                _add_iface(str(val.get("interface") or val.get("name") or "").strip() or None)
        members = vlan.get("members") or vlan.get("openconfig-vlan:members")
        if isinstance(members, dict):
            for member in members.get("member", []) or []:
                _add_iface(_iface_from_member(member))
    return in_use


def parse_f5os_vlan_in_use_from_interfaces(body: dict[str, Any]) -> set[str]:
    """Fallback when `show vlans` text is unavailable — L2-assigned interfaces."""
    block = body.get("openconfig-interfaces:interfaces")
    if not isinstance(block, dict):
        block = body
    ifaces = block.get("interface", [])
    if not isinstance(ifaces, list):
        return set()
    in_use: set[str] = set()

    def _has_vlan_cfg(node: Any) -> bool:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("native-vlan", "trunk-vlans", "interface-mode") and val:
                    return True
                if "vlan" in key.lower() and val:
                    if key == "vlan-id" and val in (0, "0"):
                        continue
                    return True
                if _has_vlan_cfg(val):
                    return True
        elif isinstance(node, list):
            return any(_has_vlan_cfg(item) for item in node)
        return False

    for iface in ifaces:
        if not isinstance(iface, dict):
            continue
        name = str(iface.get("name", "")).strip()
        if not name or name == "mgmt":
            continue
        if _has_vlan_cfg(iface):
            in_use.add(name)
    return in_use


def check_f5os_vlan_interfaces_up(
    in_use: set[str],
    ports: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    oper = {str(p["name"]).lower(): p.get("status", "") for p in ports if p.get("name")}
    up_list: list[str] = []
    down_list: list[str] = []
    for name in sorted(in_use):
        key = name.lower()
        if oper.get(key) == "up":
            up_list.append(name)
        else:
            down_list.append(name)
    return up_list, down_list


def parse_f5os_interfaces(body: dict[str, Any]) -> list[dict[str, str]]:
    """openconfig-interfaces REST (show interfaces summary equivalent)."""
    block = body.get("openconfig-interfaces:interfaces")
    if not isinstance(block, dict):
        block = body
    ifaces = block.get("interface", [])
    if not isinstance(ifaces, list):
        return []
    ports: list[dict[str, str]] = []
    for iface in ifaces:
        if not isinstance(iface, dict):
            continue
        name = str(iface.get("name", "")).strip()
        if not name:
            continue
        state = iface.get("state") if isinstance(iface.get("state"), dict) else {}
        oper = str(
            state.get("oper-status", state.get("oper_status", state.get("admin-status", "")))
        ).lower()
        if oper in ("up", "active"):
            status = "up"
        elif oper in ("down", "inactive", "not-present"):
            status = "down"
        else:
            status = oper or "unknown"
        ports.append({"name": name, "status": status})
    return ports


def parse_f5os_system_state(health: dict[str, Any]) -> dict[str, Any]:
    """Clock / hostname from openconfig-system state."""
    if not isinstance(health, dict):
        return {}
    state = health.get("openconfig-system:state")
    if not isinstance(state, dict):
        state = health
    out: dict[str, Any] = {}
    if state.get("hostname"):
        out["hostname"] = state["hostname"]
    if state.get("current-datetime"):
        out["clock"] = str(state["current-datetime"])
    sec = _uptime_from_payload(state)
    if sec:
        out["uptime_seconds"] = sec
    return out


def collect_f5os_platform(
    client: F5osClient,
    overview: dict[str, Any],
    health: dict[str, Any],
    *,
    platform_host: str | None = None,
    admin_user: str | None = None,
    admin_password: str | None = None,
) -> dict[str, Any]:
    """rSeries F5OS: uptime, power, temp, disk (+ optional NTP/interfaces)."""
    data: dict[str, Any] = {}
    _ = (platform_host, admin_user, admin_password)
    data.update(parse_f5os_overview(overview))
    data.update(parse_f5os_system_state(health))

    if not data.get("uptime_seconds"):
        for path in (
            f"{client._api_prefix()}/data/openconfig-system:system/uptime",
            f"{client._api_prefix()}/data/openconfig-system:system/state",
        ):
            try:
                body = client.get(path)
                sec = _uptime_from_payload(body)
                if sec:
                    data["uptime_seconds"] = sec
                    break
                block = body.get("openconfig-system:state") or body.get("state")
                if isinstance(block, dict):
                    sec = _uptime_from_payload(block)
                    if sec:
                        data["uptime_seconds"] = sec
                        break
            except Exception:  # noqa: BLE001
                continue

    prefix = client._api_prefix()
    if not data.get("temperature_cam"):
        try:
            body = client.get(
                f"{prefix}/data/openconfig-platform:components/"
                "component=platform/state/f5-platform:temperature"
            )
            tb = body.get("f5-platform:temperature")
            if not isinstance(tb, dict):
                inner = body.get("openconfig-platform:components", {})
                if isinstance(inner, dict):
                    comp = inner.get("component", [])
                    if isinstance(comp, list) and comp:
                        st = comp[0].get("state", {}) if isinstance(comp[0], dict) else {}
                        tb = st.get("f5-platform:temperature") if isinstance(st, dict) else None
            if isinstance(tb, dict):
                cam, avg, mx = _temperature_from_block(tb)
                if cam:
                    data["temperature_cam"] = cam
                if avg is not None:
                    data["temperature_avg_c"] = avg
                if mx is not None:
                    data["max_temperature_c"] = mx
                    data.setdefault("temperatures_c", []).append(mx)
        except Exception:  # noqa: BLE001
            pass

    if data.get("temperature_avg_c") is None and data.get("temperature_cam"):
        data["temperature_avg_c"] = _to_float(data["temperature_cam"].average)

    notes: list[str] = []
    psu_rest = collect_psu_health_rest(client, prefix, overview)
    if psu_rest:
        data["psu_health"] = psu_rest
        data["psu_health_source"] = "rest"
        notes.append(f"PSU REST: {', '.join(sorted(psu_rest.keys()))}")
    else:
        notes.append("PSU REST: none")

    ifaces_body: dict[str, Any] | None = None
    vlans_body: dict[str, Any] | None = None
    try:
        ifaces_body = client.get(f"{prefix}/data/openconfig-interfaces:interfaces")
        ports = parse_f5os_interfaces(ifaces_body)
        if ports:
            data["interface_ports"] = ports
            data["interface_source"] = "rest"
            notes.append(f"interfaces REST: {len(ports)} ports")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"interfaces REST: {str(exc)[:60]}")

    try:
        vlans_body = client.get(f"{prefix}/data/openconfig-vlan:vlans")
        in_use = parse_f5os_vlan_in_use_from_vlans(vlans_body)
        if in_use:
            data["vlan_in_use_interfaces"] = sorted(in_use)
            data["vlan_source"] = "rest-vlans"
            notes.append(f"vlan REST: {', '.join(sorted(in_use))}")
        count = parse_f5os_vlan_count(vlans_body)
        if count:
            data["vlan_count"] = count
    except Exception as exc:  # noqa: BLE001
        notes.append(f"vlan REST: {str(exc)[:60]}")

    if not data.get("vlan_in_use_interfaces") and ifaces_body:
        in_use_if = parse_f5os_vlan_in_use_from_interfaces(ifaces_body)
        if in_use_if:
            data["vlan_in_use_interfaces"] = sorted(in_use_if)
            data["vlan_source"] = "rest-interfaces"
            notes.append(f"vlan REST(ifaces): {', '.join(sorted(in_use_if))}")

    health_summary = client.first_admin_show("show system health summary")
    if health_summary:
        psu_health = parse_f5os_system_health_summary_psu(health_summary)
        if psu_health:
            data["psu_health"] = psu_health
            data["psu_health_source"] = "rest-cli"
            notes.append(f"PSU CLI: {', '.join(sorted(psu_health.keys()))}")

    show_vlan_text = client.first_admin_show("show vlan", "show vlans")
    show_if = client.first_admin_show(
        "show interfaces interface summary",
        "show interfaces summary",
        "show interfaces interface state summary",
    )

    if show_vlan_text:
        vlan_rows, in_use = parse_f5os_show_vlans(show_vlan_text)
        if in_use:
            data["vlan_count"] = vlan_rows
            data["vlan_in_use_interfaces"] = sorted(in_use)
            data["vlan_source"] = "rest-cli"
            notes.append(f"vlan CLI: {', '.join(sorted(in_use))}")
    if show_if:
        ports = parse_f5os_interfaces_summary(show_if)
        if ports:
            data["interface_ports"] = ports
            data["interface_source"] = "rest-cli"
            notes.append(f"interfaces CLI: {len(ports)} ports")

    if data.get("interface_ports") and not data.get("vlan_in_use_interfaces"):
        data["vlan_unavailable"] = True
        if not show_vlan_text:
            data["show_vlans_cli_supported"] = False

    data["collect_notes"] = notes
    return data
