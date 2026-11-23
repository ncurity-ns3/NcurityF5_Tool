"""SSL profiles that reference a certificate, the virtuals that use them, and expiry.

UCS and QKView both carry bigip.conf plus the certificate PEM under the
filestore. The leaf certificate on a client-ssl or server-ssl profile is
in use even when no virtual server has that profile yet.
"""

from __future__ import annotations

import gzip
import re
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.modules.archive_progress import open_counted_tar

_CONF_NAMES = {"bigip.conf", "bigip_user.conf"}
_SKIP = ("diffversion", "/backup/", ".bak", "/var/log/")
_CERT_REF = re.compile(r"(?m)(?:^|\s)cert\s+(\S+)")


@dataclass(frozen=True)
class SslCertRow:
    cert: str
    profile: str
    side: str
    virtuals: tuple[str, ...]
    expiry_kind: str
    expiry_text: str


@dataclass(frozen=True)
class SslCertReport:
    source_name: str
    hostname: str
    rows: tuple[SslCertRow, ...]

    @property
    def expired_count(self) -> int:
        return sum(1 for row in self.rows if row.expiry_kind == "expired")

    @property
    def soon_count(self) -> int:
        return sum(1 for row in self.rows if row.expiry_kind == "soon")

    @property
    def unknown_count(self) -> int:
        return sum(1 for row in self.rows if row.expiry_kind == "unknown")

    @property
    def unbound_count(self) -> int:
        return sum(1 for row in self.rows if not row.virtuals)

    @property
    def expired_on_virtual_count(self) -> int:
        return sum(1 for row in self.rows if row.expiry_kind == "expired" and row.virtuals)

    @property
    def expired_off_virtual_count(self) -> int:
        return sum(1 for row in self.rows if row.expiry_kind == "expired" and not row.virtuals)


class SslSourceError(ValueError):
    """The archive did not contain a readable bigip.conf."""


def inspect_archive(
    path: Path,
    *,
    today: date | None = None,
    on_percent: Callable[[int], None] | None = None,
) -> SslCertReport:
    conf, certs = read_archive(path, on_percent=on_percent)
    report = inspect_config(conf, certs, today=today or date.today())
    hostname = report.hostname or path.stem
    return SslCertReport(source_name=path.name, hostname=hostname, rows=report.rows)


def inspect_config(
    conf: str,
    cert_files: list[tuple[str, bytes]],
    *,
    today: date | None = None,
) -> SslCertReport:
    today = today or date.today()
    cache = _cert_cache_paths(conf)
    profiles = _ssl_profiles(conf)
    virtuals = _virtual_profiles(conf)
    rows: list[SslCertRow] = []
    seen: set[tuple[str, str, str]] = set()
    for profile, side, cert_name in profiles:
        key = (cert_name, profile, side)
        if key in seen:
            continue
        seen.add(key)
        pem = _pem_for(cert_name, cache.get(cert_name, ""), cert_files)
        expires = _first_not_after(pem) if pem else None
        kind, text = _expiry_label(expires, today)
        rows.append(
            SslCertRow(
                cert=_display(cert_name),
                profile=_display(profile),
                side=side,
                virtuals=tuple(_display(name) for name in virtuals.get(_norm(profile), ())),
                expiry_kind=kind,
                expiry_text=text,
            )
        )
    rows.sort(
        key=lambda row: (
            _kind_rank(row.expiry_kind),
            row.expiry_text,
            row.cert,
            row.profile,
        )
    )
    return SslCertReport(source_name="", hostname=_hostname(conf), rows=tuple(rows))


def read_archive(
    path: Path,
    on_percent: Callable[[int], None] | None = None,
) -> tuple[str, list[tuple[str, bytes]]]:
    if not path.is_file():
        raise SslSourceError(f"파일이 없습니다: {path.name}")
    confs: list[tuple[str, str]] = []
    certs: list[tuple[str, bytes]] = []
    try:
        tar, counted = open_counted_tar(path, on_percent)
    except (tarfile.TarError, OSError) as exc:
        raise SslSourceError(f"UCS/QKView를 열지 못했습니다: {path.name}") from exc
    try:
        with tar:
            for member in tar:
                if not member.isfile() or not _safe_name(member.name):
                    continue
                name = member.name.replace("\\", "/")
                if _skipped(name):
                    continue
                if _is_conf_name(name) and member.size <= 80_000_000:
                    raw = _member_bytes(tar, member)
                    if raw:
                        confs.append((name, _decode(raw)))
                    continue
                if _is_cert_name(name, member.size):
                    raw = _member_bytes(tar, member)
                    if raw and _looks_like_cert(raw):
                        certs.append((name, raw))
    finally:
        counted.close()
    conf = _choose_conf(confs)
    if not conf.strip():
        raise SslSourceError("UCS/QKView 안에서 bigip.conf를 찾지 못했습니다.")
    return conf, certs


def _ssl_profiles(conf: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for keyword, side in (
        ("ltm profile client-ssl", "Client SSL"),
        ("ltm profile server-ssl", "Server SSL"),
    ):
        for name, body in _iter_objects(conf, keyword):
            for cert in _cert_names(body):
                found.append((name, side, cert))
    return found


def _cert_names(body: str) -> list[str]:
    names: list[str] = []
    for match in _CERT_REF.finditer(body):
        cert = match.group(1).strip().strip('"').strip("{}")
        if not cert or cert.lower() == "none" or cert in names:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_./:-]+", cert):
            continue
        names.append(cert)
    return names


def _virtual_profiles(conf: str) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {}
    for name, body in _iter_objects(conf, "ltm virtual"):
        block = _inner_block(body, "profiles")
        if not block:
            continue
        for profile in re.findall(r"(?m)^\s*(\S+)\s*\{", block):
            if profile in {"context", "clientside", "serverside"}:
                continue
            mapping.setdefault(_norm(profile), [])
            if name not in mapping[_norm(profile)]:
                mapping[_norm(profile)].append(name)
    return {key: tuple(values) for key, values in mapping.items()}


def _cert_cache_paths(conf: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    for name, body in _iter_objects(conf, "sys file ssl-cert"):
        match = re.search(r"cache-path\s+(\S+)", body)
        if match:
            paths[name] = match.group(1).strip().strip('"')
    return paths


def _pem_for(cert_name: str, cache_path: str, files: list[tuple[str, bytes]]) -> bytes | None:
    short = cert_name.rsplit("/", 1)[-1]
    partition = "Common"
    parts = [part for part in cert_name.split("/") if part]
    if len(parts) >= 2:
        partition = parts[-2]
    token = f":{partition}:{short}".lower()
    cache_base = cache_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    best: bytes | None = None
    best_rank = (-1, -1)
    for name, data in files:
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        low = base.lower()
        if cache_base and low == cache_base:
            return data
        if low == short.lower() or token in low:
            rank = _file_revision(low)
            if rank >= best_rank:
                best = data
                best_rank = rank
    return best


def _file_revision(name: str) -> tuple[int, int]:
    match = re.search(r"_(\d+)_(\d+)$", name)
    if match is None:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def _expiry_label(expires: datetime | None, today: date) -> tuple[str, str]:
    if expires is None:
        return "unknown", "확인 불가"
    exp_day = expires.astimezone(UTC).date()
    if exp_day < today:
        return "expired", f"만료됨 ({exp_day:%Y-%m-%d})"
    days = (exp_day - today).days
    kind = "soon" if days <= 30 else "ok"
    return kind, f"{exp_day:%Y-%m-%d} ({days}일 남음)"


def _kind_rank(kind: str) -> int:
    return {"expired": 0, "soon": 1, "unknown": 2, "ok": 3}.get(kind, 4)


def _first_not_after(raw: bytes) -> datetime | None:
    for der in _der_certs(raw):
        try:
            return _not_after(der)
        except (ValueError, IndexError, UnicodeError):
            continue
    return None


def _der_certs(raw: bytes) -> list[bytes]:
    text = raw.decode("ascii", errors="ignore")
    chunks = re.findall(
        r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----",
        text,
        flags=re.S,
    )
    if not chunks:
        return [raw] if raw.startswith(b"\x30") else []
    import base64

    ders: list[bytes] = []
    for chunk in chunks:
        try:
            ders.append(base64.b64decode("".join(chunk.split())))
        except ValueError:
            continue
    return ders


def _not_after(der: bytes) -> datetime:
    children = _elements(_sequence_body(der))
    fields = _elements(children[0][1])
    index = 1 if fields and fields[0][0] == 0xA0 else 0
    times = _elements(fields[index + 3][1])
    tag, when = times[1]
    return _parse_time(tag, when)


def _sequence_body(data: bytes) -> bytes:
    if not data or data[0] != 0x30:
        raise ValueError("sequence")
    length, start = _read_len(data, 1)
    return data[start : start + length]


def _elements(data: bytes) -> list[tuple[int, bytes]]:
    items: list[tuple[int, bytes]] = []
    index = 0
    while index < len(data):
        tag = data[index]
        length, start = _read_len(data, index + 1)
        items.append((tag, data[start : start + length]))
        index = start + length
    return items


def _read_len(data: bytes, index: int) -> tuple[int, int]:
    first = data[index]
    if first < 0x80:
        return first, index + 1
    count = first & 0x7F
    if count == 0 or count > 3:
        raise ValueError("length")
    end = index + 1 + count
    return int.from_bytes(data[index + 1 : end], "big"), end


def _parse_time(tag: int, body: bytes) -> datetime:
    text = body.decode("ascii").strip().rstrip("Z")
    if tag == 0x17:
        year = int(text[0:2])
        year += 2000 if year < 50 else 1900
        month, day = int(text[2:4]), int(text[4:6])
        hour, minute, second = int(text[6:8]), int(text[8:10]), int(text[10:12])
    elif tag == 0x18:
        year = int(text[0:4])
        month, day = int(text[4:6]), int(text[6:8])
        hour, minute, second = int(text[8:10]), int(text[10:12]), int(text[12:14])
    else:
        raise ValueError("time")
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _iter_objects(text: str, keyword: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pattern = re.compile(rf"(?m)^{keyword}\s+(\S+)\s*\{{")
    for match in pattern.finditer(text):
        found.append((match.group(1), _brace_slice(text, match.end() - 1)))
    return found


def _brace_slice(text: str, open_index: int) -> str:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : index + 1]
    return text[open_index:]


def _inner_block(body: str, keyword: str) -> str:
    match = re.search(rf"\b{keyword}\s*\{{", body)
    if match is None:
        return ""
    return _brace_slice(body, match.end() - 1)


def _hostname(conf: str) -> str:
    match = re.search(r"(?m)^sys\s+global-settings\s*\{", conf)
    if match is None:
        return ""
    body = _brace_slice(conf, match.end() - 1)
    found = re.search(r"\bhostname\s+(\S+)", body)
    if found is None:
        return ""
    return found.group(1).strip().strip('"')


def _display(name: str) -> str:
    parts = [part for part in name.strip().strip('"').split("/") if part]
    if len(parts) >= 2 and parts[-2] == "Common":
        return parts[-1]
    return "/".join(parts) or name


def _norm(name: str) -> str:
    return name.strip().strip('"').rsplit("/", 1)[-1]


def _safe_name(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return ".." not in parts


def _skipped(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in _SKIP)


def _is_conf_name(name: str) -> bool:
    base = name.lower().rsplit("/", 1)[-1]
    if base.endswith(".im"):
        base = base[:-3]
    if base.endswith(".gz"):
        base = base[:-3]
    return base in _CONF_NAMES


def _is_cert_name(name: str, size: int) -> bool:
    if size <= 0 or size > 512_000:
        return False
    low = name.lower()
    base = low.rsplit("/", 1)[-1]
    return "certificate_d/" in low or "/ssl.crt/" in low or base.endswith((".crt", ".cer"))


def _looks_like_cert(raw: bytes) -> bool:
    return b"BEGIN CERTIFICATE" in raw or raw.startswith(b"\x30")


def _member_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = tar.extractfile(member)
    if extracted is None:
        return b""
    raw = extracted.read()
    lower = member.name.lower()
    if lower.endswith((".gz", ".im")) or raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _choose_conf(confs: list[tuple[str, str]]) -> str:
    main = ""
    user = ""
    for name, text in confs:
        base = name.lower().rsplit("/", 1)[-1]
        if "bigip_user.conf" in base and len(text) > len(user):
            user = text
        elif "bigip.conf" in base and "bigip_user.conf" not in base and len(text) > len(main):
            main = text
    return "\n".join(part for part in (main, user) if part.strip())
