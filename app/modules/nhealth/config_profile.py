"""Read provisioned modules from a UCS or QKView."""

from __future__ import annotations

import gzip
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path

from app.modules.nhealth.release_catalog import ReleaseNoteError
from app.modules.os_upgrade.ucs_reader import (
    UcsReadError,
    merge_ucs_config,
    parse_hostname_from_config,
    read_ucs_config_texts,
)

_PROVISION = re.compile(r"sys\s+provision\s+(\w+)\s*\{([^}]*)\}", re.I)
_LEVEL = re.compile(r"\blevel\s+(\w+)", re.I)
_VERSION = re.compile(
    r"Version:\s*(\d+\.\d+\.\d+(?:\.\d+)?)\s+Build:\s*(\d+(?:\.\d+)*)",
    re.I,
)
_PROVISION_MODULE = {
    "ltm": "LTM",
    "asm": "AWAF",
    "gtm": "DNS",
    "apm": "APM",
    "sslo": "SSL-O",
}
_OBJECT_COUNTS = (
    ("LTM", "virtual", re.compile(r"(?m)^ltm\s+virtual\s+")),
    ("LTM", "pool", re.compile(r"(?m)^ltm\s+pool\s+")),
    ("AWAF", "policy", re.compile(r"(?m)^asm\s+policy\s+")),
    ("DNS", "wideip", re.compile(r"(?m)^gtm\s+wideip\s+")),
    ("APM", "access", re.compile(r"(?m)^apm\s+profile\s+access\s+")),
    ("SSL-O", "sslo", re.compile(r"(?m)^sslo\s+\S+")),
)
_MODULES = ("TMOS", "LTM", "AWAF", "DNS", "SSL-O", "APM")
_WANTED = {"bigip.conf", "bigip_base.conf", "version"}


@dataclass(frozen=True)
class ConfigProfile:
    hostname: str
    version: str
    build: str
    modules: tuple[str, ...]
    remarks: tuple[tuple[str, str], ...]
    features: tuple[str, ...] = ()


def read_config_profile(path: Path) -> ConfigProfile:
    if not path.is_file():
        raise ReleaseNoteError("UCS 또는 QKView 파일을 선택하세요.")
    suffix = path.suffix.lower()
    try:
        if suffix == ".ucs":
            texts = read_ucs_config_texts(path)
        elif suffix == ".qkview":
            texts = _read_qkview_texts(path)
        else:
            raise ReleaseNoteError("UCS 또는 QKView 파일만 올릴 수 있습니다.")
    except UcsReadError as exc:
        raise ReleaseNoteError(str(exc)) from exc
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseNoteError(f"파일을 읽지 못했습니다: {path.name}") from exc
    return profile_from_texts(texts)


def profile_from_texts(texts: dict[str, str]) -> ConfigProfile:
    combined = "\n".join(texts.get(key, "") for key in ("bigip_base.conf", "bigip.conf"))
    hostname = parse_hostname_from_config(merge_ucs_config(texts))
    version, build = _version_of(texts.get("VERSION", ""))
    provision = _provision_levels(combined)
    counts = _object_counts(combined)
    modules: list[str] = []
    remarks: list[tuple[str, str]] = []
    if combined.strip():
        modules.append("TMOS")
        remarks.append(("TMOS", "설정 파일을 읽었습니다."))
    for name in _MODULES:
        if name == "TMOS":
            continue
        level = provision.get(name, "")
        objects = counts.get(name, [])
        if level and level != "none":
            detail = f"프로비전 {level}"
            if objects:
                detail = f"{detail} · " + " · ".join(objects)
            modules.append(name)
            remarks.append((name, detail))
        elif objects:
            modules.append(name)
            remarks.append((name, "설정 객체 " + " · ".join(objects)))
    features = detect_features(combined)
    if features:
        remarks.append(("기능", ", ".join(features)))
    return ConfigProfile(
        hostname,
        version,
        build,
        tuple(modules),
        tuple(remarks),
        features,
    )


def _provision_levels(config: str) -> dict[str, str]:
    levels: dict[str, str] = {}
    for match in _PROVISION.finditer(config):
        module = _PROVISION_MODULE.get(match.group(1).lower())
        if not module:
            continue
        level_match = _LEVEL.search(match.group(2))
        levels[module] = level_match.group(1).lower() if level_match else ""
    return levels


def _object_counts(config: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for module, label, pattern in _OBJECT_COUNTS:
        count = len(pattern.findall(config))
        if count:
            grouped.setdefault(module, []).append(f"{label} {count}")
    return grouped


def _version_of(text: str) -> tuple[str, str]:
    match = _VERSION.search(text)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def _read_qkview_texts(path: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    with tarfile.open(path, "r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile() or member.size > 30_000_000:
                continue
            name = member.name.replace("\\", "/")
            if ".." in name.split("/"):
                continue
            key = _member_key(name)
            if key is None or key in texts:
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            payload = extracted.read()
            if payload.startswith(b"\x1f\x8b"):
                try:
                    payload = gzip.decompress(payload)
                except OSError:
                    pass
            texts[key] = payload.decode("utf-8", errors="replace")
    return texts


def _member_key(name: str) -> str | None:
    base = name.rsplit("/", 1)[-1].lower()
    if base.endswith(".im"):
        base = base[:-3]
    if base not in _WANTED and not name.lower().endswith("/version"):
        return None
    if base == "version":
        return "VERSION"
    return base


# Description keyword and the same pattern in bigip.conf. A bug that names a
# feature is kept only when that feature is actually configured.
_FEATURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SAML", re.compile(r"\bsaml\b", re.I)),
    ("OAuth", re.compile(r"\boauth\b|\boidc\b", re.I)),
    ("Kerberos", re.compile(r"\bkerberos\b", re.I)),
    ("RADIUS", re.compile(r"\bradius\b", re.I)),
    ("TACACS", re.compile(r"\btacacs\b", re.I)),
    ("LDAP", re.compile(r"\bldap\b", re.I)),
    ("SSL", re.compile(r"\bssl\b|\btls\b", re.I)),
    ("HTTP/2", re.compile(r"\bhttp\s*/\s*2\b|\bhttp2\b", re.I)),
    ("WebSocket", re.compile(r"\bwebsocket\b", re.I)),
    ("IPsec", re.compile(r"\bipsec\b|\bikev[12]\b", re.I)),
    ("BGP", re.compile(r"\bbgp\b", re.I)),
    ("OSPF", re.compile(r"\bospf\b", re.I)),
    ("DNS", re.compile(r"\bdns\b|\bgtm\b|\bbind\b", re.I)),
    ("ASM", re.compile(r"\basm\b|\badvanced waf\b|\bwaf\b", re.I)),
    ("AFM", re.compile(r"\bafm\b", re.I)),
    ("APM", re.compile(r"\bapm\b", re.I)),
    ("SSL Orchestrator", re.compile(r"\bsslo\b|\bssl orchestrat", re.I)),
    ("iRule", re.compile(r"\birules?\b", re.I)),
    ("OCSP", re.compile(r"\bocsp\b", re.I)),
    ("FIPS", re.compile(r"\bfips\b", re.I)),
    ("CAPTCHA", re.compile(r"\bcaptcha\b", re.I)),
    ("SMTP", re.compile(r"\bsmtp\b", re.I)),
    ("FTP", re.compile(r"\bftp\b", re.I)),
    ("SIP", re.compile(r"\bsip\b", re.I)),
    ("Diameter", re.compile(r"\bdiameter\b", re.I)),
    ("NTLM", re.compile(r"\bntlm\b", re.I)),
    ("DOS", re.compile(r"\bddos\b|\bdos\b", re.I)),
)


def detect_features(config: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in _FEATURE_PATTERNS if pattern.search(config))


def mentioned_features(text: str) -> set[str]:
    return {name for name, pattern in _FEATURE_PATTERNS if pattern.search(text)}


def applies_to_config(text: str, configured: tuple[str, ...] | set[str]) -> bool:
    """Keep a bug when every feature it names is present in the configuration."""
    mentioned = mentioned_features(text)
    if not mentioned:
        return True
    return mentioned <= set(configured)
