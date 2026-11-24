"""Fetch and parse F5 BIG-IP Fixes and Known Issues pages.

Versions are exact releases such as 17.1.3.6. Train labels like 17.1.x are rejected.
A bug is Fixed or Known only when that page lists it.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path

import httpx


class ReleaseNoteError(ValueError):
    """The search is missing a version, a bug, or a readable archive."""

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:\.\d+)?$")
_BUILD_RE = re.compile(
    r"Version:\s*(\d+\.\d+\.\d+(?:\.\d+)?)\s*(?:<[^>]+>\s*)*Build:\s*(\d+(?:\.\d+)*)",
    re.I,
)
_ID_RE = re.compile(r"(?:BT|ID)?\s*(\d{4,})", re.I)
_K_RE = re.compile(r"\bK\d{5,}\b", re.I)
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.I)
_SECTION_RE = re.compile(
    r"(fixes|issues|fixed in this release|vulnerability|functional change)",
    re.I,
)

MODULE_HINTS: dict[str, tuple[str, ...]] = {
    "TMOS": ("tmos",),
    "LTM": ("local traffic", "ltm"),
    "AWAF": ("application security", "advanced waf", "awaf", "asm"),
    "DNS": ("global traffic", "gtm", "dns"),
    "SSL-O": ("ssl orchestrator", "ssl-o", "sslo"),
    "APM": ("access policy", "apm"),
}

_BRANCHES = (
    (21, 1),
    (21, 0),
    (17, 5),
    (17, 1),
    (17, 0),
    (16, 1),
    (16, 0),
    (15, 1),
    (15, 0),
    (14, 1),
)


@dataclass(frozen=True)
class ReleaseVersion:
    version: str
    build: str = ""

    @property
    def label(self) -> str:
        if self.build:
            return f"{self.version} (Build {self.build})"
        return self.version


@dataclass(frozen=True)
class ReleaseItem:
    bug_id: str
    links: str
    description: str
    fixed_versions: str
    section: str
    module: str
    kind: str
    cve: str = ""
    severity: str = ""

    @property
    def keys(self) -> set[str]:
        return id_keys(f"{self.bug_id} {self.links}")


@dataclass(frozen=True)
class ReleaseNotes:
    version: str
    build: str
    url: str
    items: tuple[ReleaseItem, ...]
    source: str


def version_sort_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def parse_version_text(text: str) -> str:
    cleaned = re.sub(r"\(.*?\)", "", text or "").strip()
    if not _VERSION_RE.fullmatch(cleaned):
        raise ReleaseNoteError(
            "버전은 17.1.3.6 처럼 실제 릴리즈 번호로 선택하세요. 17.1.x 는 사용할 수 없습니다."
        )
    return cleaned


def supplement_url(version: str) -> str:
    exact = parse_version_text(version)
    dashed = exact.replace(".", "-")
    return (
        "https://techdocs.f5.com/kb/en-us/products/big-ip_ltm/"
        f"releasenotes/related/relnote-supplement-bigip-{dashed}.html"
    )


def id_keys(text: str) -> set[str]:
    keys = {match.group(1) for match in _ID_RE.finditer(text or "")}
    keys.update(match.group(0).upper() for match in _K_RE.finditer(text or ""))
    return keys


def shipped_catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "bigip_release_versions.json"


def load_release_catalog(path: Path | None = None) -> list[ReleaseVersion]:
    catalog = path or shipped_catalog_path()
    if not catalog.is_file():
        return []
    try:
        raw = json.loads(catalog.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    found: list[ReleaseVersion] = []
    for item in raw.get("versions", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        try:
            version = parse_version_text(str(item.get("version", "")))
        except ReleaseNoteError:
            continue
        build = str(item.get("build", "")).strip()
        found.append(ReleaseVersion(version, build))
    found.sort(key=lambda entry: version_sort_key(entry.version), reverse=True)
    return found


def save_release_catalog(path: Path, versions: list[ReleaseVersion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(versions, key=lambda entry: version_sort_key(entry.version), reverse=True)
    payload = {
        "source": "https://techdocs.f5.com/kb/en-us/products/big-ip_ltm/releasenotes/related/",
        "versions": [{"version": entry.version, "build": entry.build} for entry in ordered],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _NotesParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading = ""
        self.sections: list[tuple[str, list[list[str]]]] = []
        self._mark = False
        self._mark_buf: list[str] = []
        self._in_table = False
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self._rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"strong", "b"}:
            self._mark = True
            self._mark_buf = []
        elif tag == "table":
            self._in_table = True
            self._rows = []
        elif tag == "tr" and self._in_table:
            self._row = []
        elif tag == "td" and self._in_table:
            self._in_cell = True
            self._cell = []
        elif tag == "br" and self._in_cell:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"strong", "b"} and self._mark:
            text = " ".join("".join(self._mark_buf).split())
            if _is_section_title(text):
                self.heading = text
            self._mark = False
        elif tag == "td" and self._in_cell:
            self._row.append(" ".join("".join(self._cell).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_table and self._row:
            self._rows.append(self._row)
            self._row = []
        elif tag == "table" and self._in_table:
            self.sections.append((self.heading, self._rows))
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._mark:
            self._mark_buf.append(data)
        if self._in_cell:
            self._cell.append(data)


def _is_section_title(text: str) -> bool:
    if not text or len(text) > 90 or text.endswith(":"):
        return False
    if "blue background" in text.lower():
        return False
    return _SECTION_RE.search(text) is not None


def _module_of(heading: str) -> str:
    low = heading.lower()
    for name, hints in MODULE_HINTS.items():
        if any(hint in low for hint in hints):
            return name
    return ""


def _kind_of(heading: str) -> str:
    low = heading.lower()
    if "vulnerab" in low:
        return "vulnerability"
    if "known" in low or re.search(r"\bissues\b", low):
        return "known"
    return "fixed"


def _column(header: list[str], *names: str) -> int | None:
    for index, cell in enumerate(header):
        low = cell.lower()
        if any(name in low for name in names):
            return index
    return None


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def parse_release_html(html: str, *, version: str, url: str, source: str) -> ReleaseNotes:
    exact = parse_version_text(version)
    parser = _NotesParser()
    parser.feed(html)
    items: list[ReleaseItem] = []
    seen: set[tuple[str, str, str]] = set()
    for heading, rows in parser.sections:
        if len(rows) < 2:
            continue
        header = rows[0]
        id_index = _column(header, "id number", "id")
        if id_index is None:
            continue
        link_index = _column(header, "link")
        desc_index = _column(header, "description")
        fixed_index = _column(header, "fixed")
        cve_index = _column(header, "cve")
        severity_index = _column(header, "severity")
        module = _module_of(heading)
        kind = _kind_of(heading)
        for row in rows[1:]:
            bug_id = _cell(row, id_index)
            if not id_keys(bug_id):
                continue
            description = _cell(row, desc_index)
            links = _cell(row, link_index)
            cve = _cell(row, cve_index)
            if not cve:
                cve = " ".join(_CVE_RE.findall(f"{description} {links}"))
            root = sorted(id_keys(bug_id))[0]
            key = (kind, module, root)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                ReleaseItem(
                    bug_id=bug_id,
                    links=links,
                    description=description,
                    fixed_versions=_cell(row, fixed_index),
                    section=heading,
                    module=module,
                    kind=kind,
                    cve=cve,
                    severity=_cell(row, severity_index),
                )
            )
    build_match = _BUILD_RE.search(html)
    build = build_match.group(2) if build_match else ""
    return ReleaseNotes(exact, build, url, tuple(items), source)


def load_release_notes(
    version: str,
    cache_dir: Path,
    on_percent: Callable[[int], None] | None = None,
    *,
    prefer_cache: bool = False,
) -> ReleaseNotes:
    exact = parse_version_text(version)
    url = supplement_url(exact)
    cache = cache_dir / f"{exact}.html"
    if prefer_cache and cache.is_file():
        cached = cache.read_text(encoding="utf-8", errors="replace")
        if "ID Number" in cached and "404 Page not found" not in cached[:8192]:
            if on_percent is not None:
                on_percent(100)
            return parse_release_html(cached, version=exact, url=url, source="cache")
    try:
        text = _download_notes(url, on_percent)
        if "ID Number" not in text:
            raise ReleaseNoteError(f"{exact} Release Note 형식을 읽지 못했습니다.")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
        return parse_release_html(text, version=exact, url=url, source="techdocs")
    except ReleaseNoteError:
        raise
    except Exception as exc:
        if cache.is_file():
            cached = cache.read_text(encoding="utf-8")
            return parse_release_html(cached, version=exact, url=url, source="cache")
        raise ReleaseNoteError(f"{exact} Release Note를 가져오지 못했습니다.") from exc


def _download_notes(url: str, on_percent: Callable[[int], None] | None) -> str:
    timeout = httpx.Timeout(60.0, connect=15.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            chunks: list[bytes] = []
            read = 0
            for chunk in response.iter_bytes(65536):
                chunks.append(chunk)
                read += len(chunk)
                if on_percent is not None and total > 0:
                    on_percent(min(90, int(read * 90 / total)))
    return b"".join(chunks).decode("utf-8", errors="replace")


def item_matches_module(item: ReleaseItem, module: str) -> bool:
    if item.module == module:
        return True
    blob = f"{item.section} {item.description} {item.links} {item.cve}".lower()
    return any(hint in blob for hint in MODULE_HINTS.get(module, ()))


def items_for_modules(notes: ReleaseNotes, modules: list[str]) -> list[ReleaseItem]:
    chosen = [name for name in MODULE_HINTS if name in modules]
    return [item for item in notes.items if any(item_matches_module(item, name) for name in chosen)]


def _probe_version(client: httpx.Client, version: str) -> ReleaseVersion | None:
    url = supplement_url(version)
    try:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                return None
            chunk = next(response.iter_bytes(65536), b"")
    except Exception:
        return None
    text = chunk.decode("utf-8", errors="replace")
    if "404 Page not found" in text:
        return None
    if "ID Number" not in text and "Build:" not in text:
        return None
    match = _BUILD_RE.search(text)
    build = match.group(2) if match else ""
    return ReleaseVersion(version, build)


def _scan_branch(client: httpx.Client, major: int, minor: int) -> list[ReleaseVersion]:
    found: list[ReleaseVersion] = []

    def take(version: str) -> bool:
        hit = _probe_version(client, version)
        if hit is None:
            return False
        found.append(hit)
        return True

    take(f"{major}.{minor}.0")
    misses = 0
    for patch in range(1, 21):
        if take(f"{major}.{minor}.0.{patch}"):
            misses = 0
        else:
            misses += 1
            if misses >= 3:
                break
    misses = 0
    for release in range(1, 16):
        base = f"{major}.{minor}.{release}"
        if not take(base):
            misses += 1
            if misses >= 3:
                break
            continue
        misses = 0
        hotfixes = 0
        for patch in range(1, 21):
            if take(f"{base}.{patch}"):
                hotfixes = 0
            else:
                hotfixes += 1
                if hotfixes >= 3:
                    break
    return found


def discover_release_versions(
    on_progress: Callable[[int, str], None] | None = None,
) -> list[ReleaseVersion]:
    """Probe techdocs for exact BIG-IP releases. Missing pages are skipped."""
    found: list[ReleaseVersion] = []
    total = len(_BRANCHES)

    def scan(branch: tuple[int, int]) -> list[ReleaseVersion]:
        major, minor = branch
        timeout = httpx.Timeout(20.0, connect=10.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            return _scan_branch(client, major, minor)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, branch_hits in enumerate(pool.map(scan, _BRANCHES), start=1):
            found.extend(branch_hits)
            if on_progress is not None:
                percent = min(95, int(index * 90 / total))
                major, minor = _BRANCHES[index - 1]
                on_progress(percent, f"{major}.{minor} Release Note 확인 중…")
    unique = {entry.version: entry for entry in found}
    return sorted(unique.values(), key=lambda entry: version_sort_key(entry.version), reverse=True)


_SEVERITY_RE = re.compile(
    r"\b([1-5])\s*-\s*(Blocking|Critical|Major|Minor|Cosmetic)\b",
    re.I,
)
_BUG_ROOT_RE = re.compile(r"^\s*(\d{4,})")
_META_SEVERITY_RE = re.compile(
    r"""<meta\b[^>]*\bname=["']severity["'][^>]*\bcontent=["']([^"']+)["']"""
    r"""|<meta\b[^>]*\bcontent=["']([^"']+)["'][^>]*\bname=["']severity["']""",
    re.I,
)
_SEVERITY_WORKERS = 16


def severity_rank(text: str) -> int | None:
    match = _SEVERITY_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1))


def at_least_severity(item: ReleaseItem, max_rank: int | None) -> bool:
    """1-Blocking is the most severe. max_rank 3 keeps Blocking, Critical, and Major."""
    if max_rank is None:
        return True
    rank = severity_rank(item.severity)
    return rank is not None and rank <= max_rank


def severity_label(max_rank: int | None) -> str:
    labels = {
        1: "1-Blocking 이상",
        2: "2-Critical 이상",
        3: "3-Major 이상",
        4: "4-Minor 이상",
        5: "5-Cosmetic 이상",
    }
    return labels.get(max_rank or 0, "")


def _bug_root(bug_id: str) -> str:
    match = _BUG_ROOT_RE.match(bug_id or "")
    return match.group(1) if match else ""


def severity_from_bug_page(html: str) -> str:
    match = _META_SEVERITY_RE.search(html or "")
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip()


def _read_cached_severity(cache: Path) -> str | None:
    if not cache.is_file():
        return None
    return cache.read_text(encoding="utf-8").strip()


def _fetch_severity(client: httpx.Client, root: str, cache_dir: Path) -> str:
    url = f"https://cdn.f5.com/product/bugtracker/ID{root}.html"
    for attempt in (1, 2):
        try:
            response = client.get(url)
        except Exception:
            if attempt == 1:
                continue
            return ""
        if response.status_code == 429 and attempt == 1:
            time.sleep(0.4)
            continue
        if response.status_code != 200:
            return ""
        value = severity_from_bug_page(response.text)
        (cache_dir / f"{root}.txt").write_text(value, encoding="utf-8")
        return value
    return ""


def fill_missing_severity(
    items: list[ReleaseItem],
    cache_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[ReleaseItem]:
    """Fill Severity from the public bug tracker when the release note omits it."""
    pending = [(index, _bug_root(item.bug_id)) for index, item in enumerate(items)]
    pending = [
        (index, root)
        for index, root in pending
        if root and not items[index].severity.strip()
    ]
    if not pending:
        return list(items)
    cache_dir.mkdir(parents=True, exist_ok=True)
    unique = list(dict.fromkeys(root for _index, root in pending))
    found: dict[str, str] = {}
    missing: list[str] = []
    for root in unique:
        cached = _read_cached_severity(cache_dir / f"{root}.txt")
        if cached is None:
            missing.append(root)
        else:
            found[root] = cached
    total = len(unique)
    done = len(found)
    if on_progress is not None and done:
        on_progress(done, total)
    if missing:
        timeout = httpx.Timeout(8.0, connect=4.0)
        limits = httpx.Limits(
            max_connections=_SEVERITY_WORKERS,
            max_keepalive_connections=_SEVERITY_WORKERS,
        )
        with httpx.Client(timeout=timeout, follow_redirects=True, limits=limits) as client:
            def _lookup(root: str) -> tuple[str, str]:
                return root, _fetch_severity(client, root, cache_dir)

            with ThreadPoolExecutor(max_workers=_SEVERITY_WORKERS) as pool:
                futures = [pool.submit(_lookup, root) for root in missing]
                for finished in as_completed(futures):
                    root, value = finished.result()
                    found[root] = value
                    done += 1
                    if on_progress is not None and (done == total or done % 16 == 0):
                        on_progress(done, total)
    updated = list(items)
    for index, root in pending:
        value = found.get(root, "")
        if value:
            updated[index] = replace(updated[index], severity=value)
    return updated
