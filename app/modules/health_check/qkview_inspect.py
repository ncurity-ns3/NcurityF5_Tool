"""QKView status table and 30-day line charts.

The checks follow the desktop scripts state 2.py, state-f5os.py, and performance.py.
Charts use the hourly RRD (`pdp_per_row` 60) and keep the latest 30 days.
"""

from __future__ import annotations

import gzip
import html
import re
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from app.modules.ssl_cert.inspect import _first_not_after

_SERIES = {
    "Data Plane": "#0260EA",
    "Control Plane": "#64748B",
    "TMM": "#0260EA",
    "Other": "#94A3B8",
    "Swap": "#B45309",
    "Service": "#0260EA",
    "In": "#0A6E31",
    "Out": "#64748B",
    "Client": "#0260EA",
    "Server": "#0A6E31",
    "Requests": "#0260EA",
    "Resolutions": "#0A6E31",
    "Return to DNS": "#64748B",
    "A": "#0260EA",
    "AAAA": "#0A6E31",
    "CNAME": "#B45309",
}


class QkviewInspectError(ValueError):
    """The file is not a readable QKView."""


@dataclass(frozen=True)
class StatusRow:
    name: str
    result: str
    comment: str


@dataclass(frozen=True)
class Chart:
    title: str
    ylabel: str
    series: tuple[tuple[str, tuple[float, ...]], ...]
    timestamps: tuple[int, ...]
    y_max: float | None = None
    bits: bool = False


@dataclass(frozen=True)
class QkviewReport:
    source_name: str
    hostname: str
    kind: str
    rows: tuple[StatusRow, ...]
    charts: tuple[Chart, ...]


def inspect_qkview(path: Path) -> QkviewReport:
    if path.suffix.lower() != ".qkview":
        raise QkviewInspectError("QKView 파일만 올릴 수 있습니다.")
    if not path.is_file():
        raise QkviewInspectError(f"파일이 없습니다: {path.name}")
    try:
        archive = tarfile.open(path, mode="r:*")
    except (tarfile.TarError, OSError) as exc:
        raise QkviewInspectError(f"QKView를 열지 못했습니다: {path.name}") from exc
    with archive:
        blobs, tmos, f5os = _read_needed(archive)
        if tmos:
            rows = _tmos_rows(blobs)
            kind = "TMOS"
        elif f5os:
            rows = _f5os_rows(archive)
            kind = "F5OS"
        else:
            raise QkviewInspectError("QKView에서 상태 정보를 찾지 못했습니다.")
        charts = tuple(_charts(blobs))
    hostname = _hostname(blobs.get("config/bigip_base.conf", b"")) or path.stem
    if b"Z100" in blobs.get("proc_module.xml", b""):
        hostname = f"{hostname} (VE)"
    return QkviewReport(path.name, hostname, kind, tuple(rows), charts)


def write_qkview_html(report: QkviewReport, dest: Path) -> None:
    write_qkview_reports([report], dest)


def write_qkview_reports(reports: list[QkviewReport], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_html(reports), encoding="utf-8")


def _read_needed(archive: tarfile.TarFile) -> tuple[dict[str, bytes], bool, bool]:
    wanted = {
        "proc_module.xml",
        "stat_module.xml",
        "gtm_module.xml",
        "config/bigip_base.conf",
        "config/httpd/conf/ssl.crt/server.crt",
        "var/tmp/qkview-rrd/planestat.xml.gz",
        "var/tmp/qkview-rrd/memory.xml.gz",
        "var/tmp/qkview-rrd/throughput.xml.gz",
        "var/tmp/qkview-rrd/connections.xml.gz",
        "var/tmp/qkview-rrd/gtm.xml.gz",
    }
    found: dict[str, bytes] = {}
    tmos = False
    f5os = False
    for member in archive.getmembers():
        if not member.isfile():
            continue
        name = member.name.replace("\\", "/")
        if name.endswith("subpackages/system_manager.tar.gz"):
            f5os = True
        key = next((item for item in wanted if name.endswith(item)), "")
        if key in {"proc_module.xml", "stat_module.xml"}:
            tmos = True
        if not key or key in found:
            continue
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        found[key] = extracted.read()
    return found, tmos, f5os


def _hostname(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    match = re.search(r"hostname\s+(\S+)", text)
    return match.group(1) if match else ""


def _xml(raw: bytes) -> ElementTree.Element | None:
    if raw[:2] == b"\x1f\x8b" or raw[:3] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return None
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError:
        text = re.sub(r"[^\x09\x0a\x0d\x20-\x7e]", "", text)
        try:
            return ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return None


def _tmos_rows(blobs: dict[str, bytes]) -> list[StatusRow]:
    proc = _xml(blobs.get("proc_module.xml", b""))
    stat = _xml(blobs.get("stat_module.xml", b""))
    gtm = _xml(blobs.get("gtm_module.xml", b""))
    rows = [_uptime(proc), _sync(proc), _ntp(proc), _core(proc)]
    if _iseries(blobs.get("proc_module.xml", b"")):
        rows.append(_interfaces(proc))
    rows.extend(_hardware(stat))
    rows.append(_certificate(blobs.get("config/httpd/conf/ssl.crt/server.crt", b"")))
    if gtm is not None:
        rows.append(_iquery(gtm))
    return rows


def _uptime(root: ElementTree.Element | None) -> StatusRow:
    text = root.findtext(".//uptime_t/f_uptime") if root is not None else None
    try:
        seconds = float((text or "").strip())
        days = int(seconds // 86400)
        comment = f"{days} days"
    except (TypeError, ValueError):
        comment = "No Data"
    return StatusRow("Uptime", "-", comment)


def _sync(root: ElementTree.Element | None) -> StatusRow:
    value = _command(root, "/usr/bin/tmsh -a show cm sync-status")
    if "Color    green" in value and "Status   In Sync" in value:
        return StatusRow("설정 동기화", "O", _short(value))
    if not value:
        return StatusRow("설정 동기화", "X", "No Data")
    return StatusRow("설정 동기화", "X", _short(value))


def _ntp(root: ElementTree.Element | None) -> StatusRow:
    value = _command(root, "/usr/sbin/ntpq -pn")
    lines = [line for line in value.splitlines() if line.strip()]
    if len(lines) <= 2:
        return StatusRow("ntp 상태", "X", "No NTP data available" if value else "No Data")
    for line in lines[2:]:
        parts = line.split()
        if len(parts) >= 6 and _safe_int(parts[4]) > _safe_int(parts[5]):
            return StatusRow("ntp 상태", "X", _short(value))
    return StatusRow("ntp 상태", "O", _short(value))


def _core(root: ElementTree.Element | None) -> StatusRow:
    if root is None:
        return StatusRow("core file", "X", "No Data")
    for node in root.findall(".//file"):
        if node.get("filepath") == "/var/core" and node.get("name") not in {".", "..", None}:
            when = node.findtext("local_modify_date") or ""
            return StatusRow("core file", "X", f"{node.get('name')} {when}".strip())
    return StatusRow("core file", "O", "No Data")


def _interfaces(root: ElementTree.Element | None) -> StatusRow:
    names: set[str] = set()
    if root is not None:
        for command in root.findall(".//command"):
            cmdline = (command.get("cmdline") or "").lower()
            if not re.search(r"\bshow\s+net\s+interface\b", cmdline):
                continue
            text = "\n".join(piece.text or "" for piece in command.findall(".//value"))
            current = ""
            for line in text.splitlines():
                detail = re.search(r"Net::Interface\s*:\s*(\S+)", line, re.I)
                if detail:
                    current = detail.group(1)
                    continue
                state = re.match(r"^\s*Status\s*[: ]\s*(UP|DOWN)\b", line, re.I)
                if current and state:
                    if state.group(1).upper() == "UP":
                        names.add(current)
                    current = ""
    if not names:
        return StatusRow("인터페이스 상태", "X", "UP 인터페이스 없음")
    ordered = ", ".join(sorted(names))
    return StatusRow("인터페이스 상태", "O", f"UP 물리 포트 ({len(names)}): {ordered}")


def _hardware(root: ElementTree.Element | None) -> list[StatusRow]:
    power: dict[str, str] = {}
    fans: dict[str, str] = {}
    temps: dict[str, str] = {}
    if root is not None:
        for obj in root.findall(".//object"):
            name = obj.get("name") or ""
            value = obj.findtext("status") or "No Data"
            if name.startswith("pwr"):
                power[name] = value
            if name.startswith("fan"):
                fans[name] = value
        for obj in root.findall(".//chassis_temperature_status_stat/object"):
            temps[obj.get("name") or "temp"] = obj.findtext("temperature") or "No Data"
    return [
        _flag_row("파워 상태", power, "1", "No Power Data"),
        _flag_row("팬 상태", fans, "1", "No Fan Data"),
        _temp_row(temps),
    ]


def _flag_row(name: str, values: dict[str, str], ok: str, empty: str) -> StatusRow:
    if not values:
        return StatusRow(name, "-", empty)
    comment = ", ".join(f"{key}: {value}" for key, value in values.items())
    result = "O" if all(value == ok for value in values.values()) else "X"
    return StatusRow(name, result, comment)


def _temp_row(values: dict[str, str]) -> StatusRow:
    if not values:
        return StatusRow("온도", "-", "No Temperature Data")
    comment = ", ".join(f"{key}: {value}" for key, value in values.items())
    hot = False
    for value in values.values():
        try:
            hot = hot or float(value) >= 40
        except ValueError:
            continue
    return StatusRow("온도", "X" if hot else "O", comment)


def _certificate(raw: bytes) -> StatusRow:
    if not raw:
        return StatusRow("인증서 만료 상태", "X", "No Data")
    expires = _first_not_after(raw)
    if expires is None:
        return StatusRow("인증서 만료 상태", "X", "확인 불가")
    day = expires.date()
    today = datetime.now(UTC).date()
    if day > today:
        return StatusRow("인증서 만료 상태", "O", f"만료일: {day}, {(day - today).days}일 남음")
    return StatusRow("인증서 만료 상태", "X", f"만료일: {day}, 만료됨")


def _iquery(root: ElementTree.Element) -> StatusRow:
    value = _command(root, "/usr/bin/tmsh -q show gtm iquery")
    connected = sum(1 for line in value.splitlines() if "State" in line and "connected" in line)
    if not value:
        return StatusRow("iquery 상태", "X", "No Data")
    result = "O" if connected else "X"
    return StatusRow("iquery 상태", result, _short(f"connected 상태: {connected}\n{value}"))


_ISERIES = (
    "C115", "C116", "C117", "C118", "C119", "C123", "C124", "C125", "C126", "D116", "D120",
)
_SHOW_INTERFACE_DIR = "55c2e1ee9bd01d9da4dfe2a8d5d29b63"


def _iseries(raw: bytes) -> bool:
    text = raw.decode("utf-8", "replace").upper()
    return any(code in text for code in _ISERIES)


def _command(root: ElementTree.Element | None, cmdline: str) -> str:
    if root is None:
        return ""
    for command in root.findall(".//command"):
        if command.get("cmdline") == cmdline:
            return "\n".join(piece.text or "" for piece in command.findall(".//value")).strip()
    return ""


def _safe_int(value: str) -> int:
    match = re.match(r"(\d+)", value)
    return int(match.group(1)) if match else 0


def _short(text: str, limit: int = 500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _package_member(archive: tarfile.TarFile, package: str) -> tarfile.TarInfo | None:
    suffix = f"/subpackages/{package}.tar.gz"
    return next(
        (
            item
            for item in archive.getmembers()
            if item.isfile() and item.name.replace("\\", "/").endswith(suffix)
        ),
        None,
    )


def _f5os_rows(archive: tarfile.TarFile) -> list[StatusRow]:
    components, interface = _nested_package(archive)
    rows = [
        StatusRow(name, result, _short(comment))
        for name, (result, comment) in _f5os_components(components).items()
    ]
    cores = _nested_cores(archive)
    if cores is None:
        rows.append(StatusRow("코어파일", "X", "확인 실패"))
    elif cores:
        rows.append(StatusRow("코어파일", "X", _short("\n".join(cores))))
    else:
        rows.append(StatusRow("코어파일", "O", "no data"))
    ups = [name for name, state in _f5os_interfaces(interface).items() if state.get("oper") == "UP"]
    comment = ", ".join(ups) if ups else "No UP Interface"
    rows.append(StatusRow("인터페이스 상태", "O" if ups else "X", _short(comment)))
    return rows


def _nested_package(archive: tarfile.TarFile) -> tuple[str, str]:
    member = _package_member(archive, "system_manager")
    if member is None:
        return "", ""
    source = archive.extractfile(member)
    if source is None:
        return "", ""
    components = interface = ""
    preferred = False
    try:
        nested = tarfile.open(fileobj=source, mode="r|gz")
    except (tarfile.TarError, OSError):
        return "", ""
    with nested:
        for item in nested:
            path = PurePosixPath(item.name)
            if not item.isfile() or path.name != "out":
                continue
            stream = nested.extractfile(item)
            if stream is None:
                continue
            content = stream.read().decode("utf-8", "replace")
            if not components and "# show components" in content:
                components = content
            fixed = path.parent.name == _SHOW_INTERFACE_DIR
            head = "\n".join(content.splitlines()[:20])
            matches = re.search(r"#\s*show\s+interfaces?\b", head, re.I)
            if fixed or (not preferred and not interface and matches):
                interface, preferred = content, fixed
    return components, interface


def _nested_cores(archive: tarfile.TarFile) -> list[str] | None:
    member = _package_member(archive, "cores")
    if member is None:
        return []
    source = archive.extractfile(member)
    if source is None:
        return None
    names: list[str] = []
    kst = timezone(timedelta(hours=9))
    try:
        nested = tarfile.open(fileobj=source, mode="r|gz")
    except (tarfile.TarError, OSError):
        return None
    with nested:
        for item in nested:
            path = PurePosixPath(item.name)
            if not item.isfile() or path.parts[:2] != ("qkview", "filesystem"):
                continue
            try:
                when = datetime.fromtimestamp(item.mtime, kst).strftime("%Y-%m-%d %H:%M:%S KST")
            except (ValueError, OverflowError, OSError, TypeError):
                when = "확인 불가"
            names.append(f"{path.relative_to('qkview/filesystem')} | 수정일: {when}")
    return sorted(set(names))


def _f5os_components(content: str) -> dict[str, tuple[str, str]]:
    psus: dict[str, tuple[str, float]] = {}
    fans: dict[str, int] = {}
    temps: dict[str, float | None] = dict.fromkeys(("current", "average", "minimum", "maximum"))
    current = ""
    for line in content.splitlines():
        line = line.strip()
        match = re.match(r"components component (\S+)", line)
        if match:
            current = match.group(1) if re.fullmatch(r"psu-\d+", match.group(1)) else ""
        power = re.search(r"psu-stats psu-(power|voltage)-in ([\d.]+)", line)
        if current and power:
            psus[current] = (power.group(1), float(power.group(2)))
        fan = re.search(r"fantray fan-stats fan-(\d+)-speed (\d+)", line)
        if fan:
            fans[f"fan-{fan.group(1)}"] = int(fan.group(2))
        temp = re.search(r"state temperature (current|average|minimum|maximum) ([\d.]+)", line)
        if temp:
            temps[temp.group(1)] = float(temp.group(2))
    power_ok = bool(psus) and all(
        value >= (250 if kind == "power" else 200) for kind, value in psus.values()
    )
    power_text = ", ".join(
        f"{name}: {value}{'W' if kind == 'power' else 'V'}" for name, (kind, value) in psus.items()
    ) or "No Data"
    fan_ok = bool(fans) and all(value >= 16000 for value in fans.values())
    fan_text = ", ".join(f"{name}: {fans[name]}" for name in sorted(fans)) or "No Data"
    numbers = list(temps.values())
    temp_ok = all(value is not None and 20 <= value <= 40 for value in numbers)
    temp_text = "No Data" if any(value is None for value in numbers) else ", ".join(
        f"{name}: {value}" for name, value in temps.items()
    )
    return {
        "파워 상태": ("O" if power_ok else "X", power_text),
        "팬 상태": ("O" if fan_ok else "X", fan_text),
        "온도": ("O" if temp_ok else "X", temp_text),
    }


def _normalize_status(value: str) -> str:
    value = value.strip().strip(";{}[]()\"'").upper()
    aliases = {
        "ENABLED": "UP",
        "ENABLE": "UP",
        "TRUE": "UP",
        "DISABLED": "DOWN",
        "DISABLE": "DOWN",
        "FALSE": "DOWN",
        "LOWERLAYERDOWN": "DOWN",
        "NOTPRESENT": "DOWN",
    }
    return aliases.get(value, value)


def _f5os_interfaces(content: str) -> dict[str, dict[str, str]]:
    interfaces: dict[str, dict[str, str]] = {}
    lines = content.splitlines()

    def ensure(name: str) -> str:
        name = name.strip().strip(";{}[]()\"'")
        if not name or name.lower() in {"name", "interface", "interfaces"}:
            return ""
        interfaces.setdefault(name, {"admin": "N/A", "oper": "N/A"})
        return name

    header_index = None
    admin_col = oper_col = 0
    for index, raw in enumerate(lines):
        lowered = [part.lower().replace("_", "-") for part in raw.split()]
        if "admin-status" in lowered and "oper-status" in lowered:
            header_index = index
            admin_col = lowered.index("admin-status")
            oper_col = lowered.index("oper-status")
            break
    if header_index is not None:
        for raw in lines[header_index + 1 :]:
            cols = raw.split()
            if len(cols) <= max(admin_col, oper_col) or set(raw.strip()) <= {"-", "+", "|"}:
                continue
            name = ensure(cols[0].strip("|"))
            if name:
                interfaces[name]["admin"] = _normalize_status(cols[admin_col].strip("|"))
                interfaces[name]["oper"] = _normalize_status(cols[oper_col].strip("|"))
    current = ""
    for index, raw in enumerate(lines):
        if index == header_index:
            continue
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        block = re.match(
            r"(?:interfaces?\s+)?interface(?:\s+(?:config|state))?\s+(?:name\s+)?([^\s{}]+)",
            line,
            re.I,
        )
        if block:
            current = ensure(block.group(1))
        named = re.search(r"\b(?:interface-)?name\s+([^\s{};]+)", line, re.I)
        if named and ("interface" in line.lower() or not current):
            current = ensure(named.group(1))
        target = block.group(1) if block else current
        if target not in interfaces:
            continue
        admin = re.search(r"\badmin(?:istrative)?[-_ ]status\s*[:=]?\s*([^\s{};]+)", line, re.I)
        oper = re.search(r"\boper(?:ational)?[-_ ]status\s*[:=]?\s*([^\s{};]+)", line, re.I)
        if admin:
            interfaces[target]["admin"] = _normalize_status(admin.group(1))
        if oper:
            interfaces[target]["oper"] = _normalize_status(oper.group(1))
    return interfaces


def _charts(blobs: dict[str, bytes]) -> list[Chart]:
    charts: list[Chart] = []
    cpu, cpu_ts = _rrd(
        blobs.get("var/tmp/qkview-rrd/planestat.xml.gz", b""),
        (("Data Plane", 0), ("Control Plane", 1)),
        minimum=2,
    )
    charts.append(Chart("CPU 사용률", "사용률 %", cpu, cpu_ts, 100))
    memory, memory_ts = _memory(blobs.get("var/tmp/qkview-rrd/memory.xml.gz", b""))
    charts.append(Chart("메모리 사용률", "사용률 %", memory, memory_ts, 100))
    if "gtm_module.xml" in blobs:
        requests, request_ts = _rrd(
            blobs.get("var/tmp/qkview-rrd/gtm.xml.gz", b""),
            (("Requests", 0), ("Resolutions", 1), ("Return to DNS", 3)),
            minimum=7,
        )
        charts.append(Chart("DNS 요청", "Requests", requests, request_ts))
        kinds, kind_ts = _rrd(
            blobs.get("var/tmp/qkview-rrd/gtm.xml.gz", b""),
            (("A", 4), ("AAAA", 5), ("CNAME", 6)),
            minimum=7,
        )
        charts.append(Chart("DNS 종류", "Requests", kinds, kind_ts))
    else:
        throughput, throughput_ts = _rrd(
            blobs.get("var/tmp/qkview-rrd/throughput.xml.gz", b""),
            (("Service", 0), ("In", 19), ("Out", 20)),
            minimum=24,
            scale=8,
        )
        charts.append(Chart("처리량", "bps", throughput, throughput_ts, bits=True))
        connections, connection_ts = _rrd(
            blobs.get("var/tmp/qkview-rrd/connections.xml.gz", b""),
            (("Client", 8), ("Server", 9)),
            minimum=17,
        )
        charts.append(Chart("연결 수", "Connections", connections, connection_ts))
    return [chart for chart in charts if chart.timestamps]


def _memory(raw: bytes) -> tuple[tuple[tuple[str, tuple[float, ...]], ...], tuple[int, ...]]:
    root = _xml(raw)
    if root is None:
        return (), ()
    rows = _hourly_rows(root)
    if rows is None:
        return (), ()
    step, last, database = rows
    series = {"TMM": [], "Other": [], "Swap": []}
    stamps: list[int] = []
    for index, values in enumerate(database):
        if len(values) < 19:
            continue
        series["TMM"].append(_ratio(values[6], values[5]))
        series["Other"].append(_ratio(values[8], values[7]))
        series["Swap"].append(_ratio(values[16], values[15]))
        stamps.append(last - step * 60 * (len(database) - 1 - index))
    packed = tuple((name, tuple(values)) for name, values in series.items())
    return _window(packed, tuple(stamps))


def _rrd(
    raw: bytes,
    columns: tuple[tuple[str, int], ...],
    *,
    minimum: int,
    scale: float = 1,
) -> tuple[tuple[tuple[str, tuple[float, ...]], ...], tuple[int, ...]]:
    root = _xml(raw)
    if root is None:
        return (), ()
    rows = _hourly_rows(root)
    if rows is None:
        return (), ()
    step, last, database = rows
    series = {name: [] for name, _index in columns}
    stamps: list[int] = []
    for index, values in enumerate(database):
        if len(values) < minimum:
            continue
        for name, column in columns:
            series[name].append(values[column] * scale)
        stamps.append(last - step * 60 * (len(database) - 1 - index))
    packed = tuple((name, tuple(values)) for name, values in series.items())
    return _window(packed, tuple(stamps))


def _hourly_rows(root: ElementTree.Element) -> tuple[int, int, list[list[float]]] | None:
    try:
        step = int(root.findtext("step") or "0")
        last = int(root.findtext("lastupdate") or "0")
    except ValueError:
        return None
    chosen = None
    for rra in root.findall(".//rra"):
        if (rra.findtext("pdp_per_row") or "").strip() == "60":
            chosen = rra
            break
    if chosen is None or step <= 0:
        return None
    database: list[list[float]] = []
    for row in chosen.findall(".//database/row"):
        numbers: list[float] = []
        for item in row.findall("v"):
            try:
                numbers.append(float(item.text or "nan"))
            except ValueError:
                numbers.append(float("nan"))
        database.append(numbers)
    return step, last, database


def _ratio(used: float, total: float) -> float:
    if total == 0:
        return 0.0
    return used / total * 100


def _window(
    series: tuple[tuple[str, tuple[float, ...]], ...],
    stamps: tuple[int, ...],
) -> tuple[tuple[tuple[str, tuple[float, ...]], ...], tuple[int, ...]]:
    if not stamps:
        return (), ()
    end = max(stamps)
    start = end - 30 * 24 * 60 * 60
    keep = [index for index, stamp in enumerate(stamps) if start <= stamp <= end]
    if len(keep) > 120:
        stride = max(1, len(keep) // 120)
        keep = keep[::stride]
    trimmed = tuple(stamps[index] for index in keep)
    packed = tuple(
        (name, tuple(values[index] for index in keep if index < len(values)))
        for name, values in series
    )
    width = min([len(trimmed), *[len(values) for _name, values in packed]] or [0])
    if width == 0:
        return (), ()
    return tuple((name, values[:width]) for name, values in packed), trimmed[:width]


def _status_table(rows: tuple[StatusRow, ...]) -> str:
    body = "\n".join(_status_row(row) for row in rows)
    return (
        "<table><tr><th>항목</th><th>결과</th><th>비고</th></tr>"
        f"{body}</table>"
    )


def _chart_block(charts: tuple[Chart, ...]) -> str:
    drawn = "\n".join(_chart_svg(chart) for chart in charts)
    if not drawn.strip():
        return "<p class='empty'>30일 그래프 데이터가 없습니다.</p>"
    return drawn


def _device_block(report: QkviewReport, body: str) -> str:
    heading = html.escape(f"{report.hostname} · {report.kind}")
    source = html.escape(report.source_name)
    return f"<h2>{heading}</h2><p class='sub'>{source}</p>{body}"


def _html(reports: list[QkviewReport]) -> str:
    if len(reports) == 1:
        report = reports[0]
        title = html.escape(f"{report.hostname} · {report.kind}")
        source = html.escape(report.source_name)
        status = _status_table(report.rows)
        graphs = _chart_block(report.charts)
    else:
        title = html.escape(f"QKView 점검 · {len(reports)}대")
        source = html.escape(f"{len(reports)}개 파일")
        status = "\n".join(_device_block(item, _status_table(item.rows)) for item in reports)
        graphs = "\n".join(_device_block(item, _chart_block(item.charts)) for item in reports)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>{title}</title>
<style>
body {{ margin: 0; background: #F7F9FC; color: #1A2332;
  font-family: "Malgun Gothic", "Segoe UI", sans-serif; }}
header {{ padding: 20px 28px 8px; }}
h1 {{ margin: 0; font-size: 20px; font-weight: 650; }}
h2 {{ margin: 18px 0 8px; font-size: 15px; font-weight: 650; }}
.sub {{ margin: 6px 0 8px; color: #64748B; font-size: 13px; }}
.tabs {{ display: flex; gap: 8px; padding: 12px 28px 0; }}
.tabs label {{ padding: 8px 14px; border: 1px solid #E2E8F0; border-bottom: none;
  border-radius: 8px 8px 0 0; background: #fff; color: #64748B; cursor: pointer; }}
#tab-status:checked ~ .tabs label[for="tab-status"],
#tab-graph:checked ~ .tabs label[for="tab-graph"] {{
  color: #0260EA; font-weight: 650; }}
input.tab {{ display: none; }}
.panel {{ display: block; margin: 0 28px 28px; background: #fff;
  border: 1px solid #E2E8F0; border-radius: 0 12px 12px 12px; padding: 16px; }}
#tab-status:checked ~ #graph, #tab-graph:checked ~ #status {{ display: none; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; background: #F1F5F9; padding: 8px 10px; }}
td {{ padding: 8px 10px; border-top: 1px solid #E2E8F0; vertical-align: top;
  white-space: pre-wrap; }}
.ok {{ color: #0A6E31; font-weight: 650; }}
.bad {{ color: #B42318; font-weight: 650; }}
.na {{ color: #64748B; }}
.chart {{ margin: 0 0 18px; }}
.chart h2 {{ margin: 0 0 8px; font-size: 14px; font-weight: 650; }}
.empty {{ color: #64748B; }}
</style></head><body>
<input class="tab" type="radio" name="tab" id="tab-status" checked>
<input class="tab" type="radio" name="tab" id="tab-graph">
<header><h1>{title}</h1><p class="sub">{source}</p></header>
<div class="tabs">
<label for="tab-status">상태점검</label>
<label for="tab-graph">성능 그래프</label>
</div>
<section class="panel" id="status">{status}</section>
<section class="panel" id="graph">{graphs}</section>
</body></html>"""


def _status_row(row: StatusRow) -> str:
    kind = {"O": "ok", "X": "bad"}.get(row.result, "na")
    return (
        f"<tr><td>{html.escape(row.name)}</td>"
        f"<td class='{kind}'>{html.escape(row.result)}</td>"
        f"<td>{html.escape(row.comment)}</td></tr>"
    )


def _chart_svg(chart: Chart) -> str:
    width, height = 760, 220
    left, right, top, bottom = 52, 16, 16, 28
    plot_w = width - left - right
    plot_h = height - top - bottom
    stamps = chart.timestamps
    if len(stamps) < 2:
        return ""
    values = [point for _name, series in chart.series for point in series if point == point]
    if not values:
        return ""
    y_max = chart.y_max if chart.y_max is not None else max(values) or 1
    if y_max <= 0:
        y_max = 1
    start, end = stamps[0], stamps[-1]
    span = max(end - start, 1)

    def x_of(stamp: int) -> float:
        return left + (stamp - start) / span * plot_w

    def y_of(value: float) -> float:
        return top + (1 - min(max(value, 0), y_max) / y_max) * plot_h

    grid = []
    for step in range(5):
        y = top + plot_h * step / 4
        label = _axis_label(y_max * (1 - step / 4), chart.bits)
        grid.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width - right}' y2='{y:.1f}' stroke='#E2E8F0'/>"
            f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end' "
            f"font-size='11' fill='#64748B'>{label}</text>"
        )
    lines = []
    legend = []
    for name, series in chart.series:
        color = _SERIES.get(name, "#0260EA")
        points = " ".join(
            f"{x_of(stamp):.1f},{y_of(value):.1f}"
            for stamp, value in zip(stamps, series, strict=False)
            if value == value
        )
        lines.append(
            f"<polyline fill='none' stroke='{color}' stroke-width='1.6' points='{points}'/>"
        )
        legend.append(f"<span style='color:{color}'>{html.escape(name)}</span>")
    start_label = datetime.fromtimestamp(start).strftime("%m-%d")
    end_label = datetime.fromtimestamp(end).strftime("%m-%d")
    svg = (
        f"<svg viewBox='0 0 {width} {height}' width='100%' role='img'>"
        f"{''.join(grid)}{''.join(lines)}"
        f"<text x='{left}' y='{height - 6}' font-size='11' fill='#64748B'>{start_label}</text>"
        f"<text x='{width - right}' y='{height - 6}' text-anchor='end' "
        f"font-size='11' fill='#64748B'>{end_label}</text>"
        "</svg>"
    )
    return (
        f"<div class='chart'><h2>{html.escape(chart.title)}</h2>{svg}"
        f"<p class='sub'>{' · '.join(legend)}</p></div>"
    )


def _axis_label(value: float, bits: bool) -> str:
    unit = ""
    number = value
    for name in ("", "K", "M", "G", "T"):
        unit = name
        if number < 1000:
            break
        number /= 1000
    suffix = "b" if bits and unit else ""
    if unit:
        return f"{number:.1f}{unit}{suffix}"
    return f"{number:.0f}"
