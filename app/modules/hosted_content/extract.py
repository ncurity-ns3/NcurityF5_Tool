"""Access Webtops Hosted Content from a UCS archive.

The list comes from `apm resource sandbox`. The bytes live under
`/config/filestore/files_d/<partition>_d/sandbox_file_d`, including folders
created inside that directory. QKView does not carry those files.
"""

from __future__ import annotations

import re
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.modules.archive_progress import open_counted_tar

_SKIP = ("diffversion", "/backup/", ".bak", "/trash", "trash-bin")


class HostedContentError(ValueError):
    """The file is not a UCS or does not contain hosted content config."""


@dataclass(frozen=True)
class HostedFile:
    sandbox: str
    name: str
    filename: str
    folder: str
    virtual_path: str
    cache_path: str
    member_name: str
    size: int

    @property
    def present(self) -> bool:
        return bool(self.member_name) and self.size >= 0


@dataclass(frozen=True)
class HostedContentReport:
    source_name: str
    files: tuple[HostedFile, ...]


@dataclass(frozen=True)
class _Member:
    name: str
    size: int


def list_hosted_content(
    path: Path,
    on_percent: Callable[[int], None] | None = None,
) -> HostedContentReport:
    if path.suffix.lower() != ".ucs":
        raise HostedContentError("UCS 파일만 올릴 수 있습니다. QKView는 지원하지 않습니다.")
    if not path.is_file():
        raise HostedContentError(f"파일이 없습니다: {path.name}")
    conf, members = _scan_ucs(path, on_percent=on_percent)
    if not conf.strip():
        raise HostedContentError("UCS 안에서 bigip.conf를 찾지 못했습니다.")
    files = tuple(_match_files(parse_sandbox_files(conf), members))
    return HostedContentReport(source_name=path.name, files=files)


def parse_sandbox_files(conf: str) -> list[HostedFile]:
    found: list[HostedFile] = []
    for sandbox, body in _iter_objects(conf, "apm resource sandbox"):
        base = _field(body, "base-uri") or "/public/share"
        files_body = _inner_block(body, "files")
        if not files_body:
            continue
        for item, item_body in _iter_named_blocks(files_body):
            filename = _field(item_body, "filename") or item
            folder = _field(item_body, "folder") or "/"
            found.append(
                HostedFile(
                    sandbox=_display(sandbox),
                    name=item,
                    filename=filename,
                    folder=folder,
                    virtual_path=_virtual_path(base, folder, filename),
                    cache_path=_field(item_body, "cache-path"),
                    member_name="",
                    size=-1,
                )
            )
    return found


def extract_hosted_files(
    ucs: Path,
    files: list[HostedFile],
    dest: Path,
    on_percent: Callable[[int], None] | None = None,
) -> tuple[list[Path], list[str]]:
    """Copy selected sandbox files into dest. Returns written paths and missing names."""
    if ucs.suffix.lower() != ".ucs":
        raise HostedContentError("UCS 파일만 추출할 수 있습니다.")
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    wanted = {item.member_name: item for item in files if item.member_name}
    written: list[Path] = []
    missing = [item.virtual_path for item in files if not item.member_name]
    try:
        tar, counted = open_counted_tar(ucs, on_percent)
    except (tarfile.TarError, OSError) as exc:
        raise HostedContentError(f"UCS를 열지 못했습니다: {ucs.name}") from exc
    try:
        with tar:
            by_name = {
                member.name.replace("\\", "/"): member
                for member in tar
                if member.isfile()
            }
            total = max(len(wanted), 1)
            for index, (member_name, item) in enumerate(wanted.items(), start=1):
                if on_percent is not None:
                    on_percent(min(95, index * 95 // total))
                member = by_name.get(member_name)
                if member is None:
                    missing.append(item.virtual_path)
                    continue
                target = _destination(root, item)
                extracted = tar.extractfile(member)
                if extracted is None:
                    missing.append(item.virtual_path)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    while True:
                        chunk = extracted.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                written.append(target)
    finally:
        counted.close()
    return written, missing


def format_size(size: int) -> str:
    if size < 0:
        return "없음"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


_ID_SUFFIX = re.compile(r"_\d{6,}$")


def hosted_display_name(name: str, filename: str = "") -> str:
    """File name without the trailing object id."""
    if filename and not _ID_SUFFIX.search(filename):
        return filename
    source = filename or name
    cleaned = _ID_SUFFIX.sub("", source)
    return cleaned or source


def hosted_display_folder(virtual_path: str) -> str:
    """Folder for the table. /public/share is /, and /public/share/JS is /JS."""
    path = virtual_path.strip().replace("\\", "/")
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    share = "/public/share"
    if parent in {"", share}:
        return "/"
    if parent.startswith(share + "/"):
        return parent[len(share):].rstrip("/") or "/"
    parts = [part for part in parent.split("/") if part]
    if len(parts) >= 2 and parts[0] == "public":
        rest = parts[2:]
        return "/" + "/".join(rest) if rest else "/"
    return "/" + "/".join(parts) if parts else "/"


def _scan_ucs(
    path: Path,
    on_percent: Callable[[int], None] | None = None,
) -> tuple[str, list[_Member]]:
    confs: list[tuple[str, str]] = []
    members: list[_Member] = []
    try:
        tar, counted = open_counted_tar(path, on_percent)
    except (tarfile.TarError, OSError) as exc:
        raise HostedContentError(f"UCS를 열지 못했습니다: {path.name}") from exc
    try:
        with tar:
            for member in tar:
                if not member.isfile() or not _safe_name(member.name):
                    continue
                name = member.name.replace("\\", "/")
                if _skipped(name):
                    continue
                if _is_conf(name) and member.size <= 80_000_000:
                    raw = _read_member(tar, member)
                    if raw:
                        confs.append((name, raw.decode("utf-8", errors="replace")))
                    continue
                if _is_sandbox_file(name) and member.size <= 512_000_000:
                    members.append(_Member(name=name, size=member.size))
    finally:
        counted.close()
    return _choose_conf(confs), members


def _match_files(items: list[HostedFile], members: list[_Member]) -> list[HostedFile]:
    matched: list[HostedFile] = []
    for item in items:
        member = _best_member(item, members)
        if member is None:
            matched.append(item)
            continue
        matched.append(
            HostedFile(
                sandbox=item.sandbox,
                name=item.name,
                filename=item.filename,
                folder=item.folder,
                virtual_path=item.virtual_path,
                cache_path=item.cache_path,
                member_name=member.name,
                size=member.size,
            )
        )
    return matched


def _best_member(item: HostedFile, members: list[_Member]) -> _Member | None:
    cache_base = item.cache_path.replace("\\", "/").rsplit("/", 1)[-1]
    pool = [member for member in members if "trash" not in member.name.lower()]
    if not pool:
        pool = list(members)
    if cache_base:
        exact = [member for member in pool if member.name.rsplit("/", 1)[-1] == cache_base]
        if exact:
            return exact[0]
    token = f":{_partition(item.sandbox)}:{item.sandbox}::{item.filename}".lower()
    named = [member for member in pool if token in member.name.lower()]
    if not named:
        needle = f"::{item.name}".lower()
        named = [
            member
            for member in pool
            if needle in member.name.lower() and item.sandbox.lower() in member.name.lower()
        ]
    if not named:
        return None
    return max(named, key=lambda member: _revision(member.name))


def _destination(root: Path, item: HostedFile) -> Path:
    parts = [_safe_part(item.sandbox)]
    folder = item.folder.strip().replace("\\", "/")
    if folder not in {"", "/"}:
        for part in folder.split("/"):
            if part in {"", "."}:
                continue
            parts.append(_safe_part(part))
    parts.append(_safe_part(Path(item.filename).name or item.name))
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root):
        raise HostedContentError(f"경로가 폴더 밖을 가리킵니다: {item.virtual_path}")
    return target


def _safe_part(part: str) -> str:
    text = part.strip().strip('"').replace(":", "_")
    if text in {"", ".", ".."} or "/" in text or "\\" in text:
        raise HostedContentError(f"파일 이름이 올바르지 않습니다: {part}")
    return text


def _virtual_path(base: str, folder: str, filename: str) -> str:
    root = "/" + base.strip().strip('"').strip("/")
    mid = folder.strip().strip('"').strip("/")
    name = filename.strip().strip('"').strip("/")
    if mid:
        return f"{root}/{mid}/{name}"
    return f"{root}/{name}"


def _revision(name: str) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"_(\d+)", name.rsplit("/", 1)[-1])]
    if len(numbers) >= 2:
        return (numbers[-2], numbers[-1])
    if numbers:
        return (numbers[-1], 0)
    return (0, 0)


def _partition(sandbox: str) -> str:
    parts = [part for part in sandbox.split("/") if part]
    if len(parts) >= 2:
        return parts[-2]
    return "Common"


def _display(name: str) -> str:
    parts = [part for part in name.strip().strip('"').split("/") if part]
    if len(parts) >= 2 and parts[-2] == "Common":
        return parts[-1]
    return "/".join(parts) or name


def _field(body: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s+(\S+)", body)
    if match is None:
        return ""
    return match.group(1).strip().strip('"')


def _iter_objects(text: str, keyword: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pattern = re.compile(rf"(?m)^{keyword}\s+(\S+)\s*\{{")
    for match in pattern.finditer(text or ""):
        found.append((match.group(1), _brace_slice(text, match.end() - 1)))
    return found


def _iter_named_blocks(body: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    pattern = re.compile(r"(?m)^\s*([A-Za-z0-9_.-]+)\s*\{")
    for match in pattern.finditer(body or ""):
        found.append((match.group(1), _brace_slice(body, match.end() - 1)))
    return found


def _inner_block(body: str, keyword: str) -> str:
    match = re.search(rf"(?m)^\s*{keyword}\s*\{{", body)
    if match is None:
        return ""
    return _brace_slice(body, match.end() - 1)


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


def _safe_name(name: str) -> bool:
    return ".." not in name.replace("\\", "/").split("/")


def _skipped(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in _SKIP)


def _is_conf(name: str) -> bool:
    base = name.lower().rsplit("/", 1)[-1]
    if base.endswith(".im"):
        base = base[:-3]
    if base.endswith(".gz"):
        base = base[:-3]
    return base in {"bigip.conf", "bigip_user.conf"}


def _is_sandbox_file(name: str) -> bool:
    low = "/" + name.lower().lstrip("/")
    return "/sandbox_file_d/" in low


def _read_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    extracted = tar.extractfile(member)
    if extracted is None:
        return b""
    raw = extracted.read()
    if member.name.lower().endswith((".gz", ".im")) or raw[:2] == b"\x1f\x8b":
        import gzip

        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def _choose_conf(confs: list[tuple[str, str]]) -> str:
    main = ""
    user = ""
    for name, text in confs:
        base = name.lower()
        if "bigip_user.conf" in base and len(text) > len(user):
            user = text
        elif "bigip.conf" in base and "bigip_user.conf" not in base and len(text) > len(main):
            main = text
    return "\n".join(part for part in (main, user) if part.strip())
