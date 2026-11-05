from __future__ import annotations

import gzip
import re
import tarfile
from pathlib import Path

_CONFIG_FILES = frozenset(
    {
        "bigip.conf",
        "bigip_base.conf",
        "bigip_user.conf",
        "bigip_script.conf",
        "bigip.license",
    }
)


class UcsReadError(Exception):
    """UCS 아카이브를 열거나 설정을 읽지 못함."""


def _safe_member_path(name: str) -> bool:
    normalized = name.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/"):
        return False
    return True


def _decode_config(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _decompress_member_payload(member_name: str, payload: bytes) -> bytes:
    lower = member_name.lower()
    if lower.endswith(".im") or lower.endswith(".gz"):
        try:
            return gzip.decompress(payload)
        except OSError:
            pass
    if len(payload) >= 2 and payload[0:1] == b"\x1f" and payload[1:2] == b"\x8b":
        try:
            return gzip.decompress(payload)
        except OSError:
            pass
    return payload


def _config_key_from_member_path(norm: str) -> str | None:
    base_lower = norm.rsplit("/", 1)[-1].lower()
    if base_lower.endswith(".im"):
        base_lower = base_lower[:-3]
    if base_lower in _CONFIG_FILES:
        return base_lower
    if base_lower == "version" or norm.lower().endswith("/version"):
        return "VERSION"
    return None


def _merge_text(texts: dict[str, str], key: str, chunk: str) -> None:
    chunk = chunk.strip()
    if not chunk:
        return
    prev = texts.get(key, "")
    if not prev or len(chunk) > len(prev):
        texts[key] = chunk


def _read_tar_archive(path: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    last_err: Exception | None = None
    for mode in ("r:gz", "r:", "r:*"):
        try:
            with tarfile.open(path, mode) as tar:
                for member in tar.getmembers():
                    if not member.isfile() or not _safe_member_path(member.name):
                        continue
                    norm = member.name.replace("\\", "/")
                    key = _config_key_from_member_path(norm)
                    if not key:
                        continue
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    payload = _decompress_member_payload(norm, extracted.read())
                    if payload:
                        _merge_text(texts, key, _decode_config(payload))
            if texts:
                return texts
        except (tarfile.TarError, OSError) as exc:
            last_err = exc
    raise UcsReadError(
        f"UCS 안에서 config(bigip*.conf / *.im)를 찾지 못했습니다: {path.name}"
    ) from last_err


def read_ucs_config_texts(path: Path) -> dict[str, str]:
    """UCS(.ucs) 아카이브 내부 /config — plain .conf 와 gzip .im 모두 읽습니다."""
    if not path.exists():
        raise UcsReadError(f"경로가 없습니다: {path}")
    if not path.is_file():
        raise UcsReadError(f"UCS 파일만 지원합니다: {path.name}")
    if path.suffix.lower() != ".ucs":
        raise UcsReadError(f".ucs 파일만 지원합니다: {path.name}")
    return _read_tar_archive(path)


def read_ucs_member_texts(path: Path) -> dict[str, str]:
    """하위 호환 — config 텍스트 맵 반환."""
    return read_ucs_config_texts(path)


def merge_ucs_config(texts: dict[str, str]) -> str:
    parts: list[str] = []
    for key in ("bigip_base.conf", "bigip.conf", "bigip_user.conf", "bigip_script.conf"):
        block = texts.get(key, "").strip()
        if block:
            parts.append(block)
    return "\n\n".join(parts)


def parse_hostname_from_config(config: str) -> str:
    m = re.search(
        r"sys\s+global-settings\s*\{[^}]*\bhostname\s+(\S+)",
        config,
        re.I | re.S,
    )
    if m:
        return m.group(1).strip().strip('"')
    m = re.search(r"\bhostname\s+(\S+)", config, re.I)
    return m.group(1).strip().strip('"') if m else ""


def peek_ucs_hostname(path: Path) -> str:
    try:
        from app.modules.os_upgrade.ucs_config_check import parse_cm_device_self

        texts = read_ucs_config_texts(path)
        base = texts.get("bigip_base.conf", "")
        if base:
            dev = parse_cm_device_self(base)
            host = (dev.get("hostname") or "").strip()
            if host:
                return host
        return parse_hostname_from_config(merge_ucs_config(texts))
    except UcsReadError:
        return ""
