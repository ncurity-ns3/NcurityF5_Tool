"""Named bug lists and release-note verdicts.

Fixed and Known come only from a parsed Fixes and Known Issues page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.modules.nhealth.config_profile import ConfigProfile, applies_to_config
from app.modules.nhealth.release_catalog import (
    ReleaseItem,
    ReleaseNoteError,
    ReleaseNotes,
    id_keys,
    item_matches_module,
)

MODULES = ("TMOS", "LTM", "AWAF", "DNS", "SSL-O", "APM")


@dataclass(frozen=True)
class WatchedBug:
    bug_id: str
    title: str


@dataclass(frozen=True)
class BugList:
    name: str
    bugs: tuple[WatchedBug, ...]


@dataclass(frozen=True)
class BugCheck:
    bug_id: str
    title: str
    verdict: str
    state: str
    note: str
    description: str = ""
    section: str = ""
    fixed_versions: str = ""


@dataclass(frozen=True)
class IssueRow:
    source: str
    module: str
    item: str
    state: str
    note: str


def load_bug_lists(path: Path) -> list[BugList]:
    if not path.is_file():
        legacy = path.with_name("watched_bugs.json")
        if legacy.is_file():
            return _lists_from_raw(
                json.loads(legacy.read_text(encoding="utf-8")),
                legacy_name="기본",
            )
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(raw, list):
        return _lists_from_raw(raw, legacy_name="기본")
    if not isinstance(raw, dict):
        return []
    lists: list[BugList] = []
    for item in raw.get("lists", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        lists.append(BugList(name, tuple(_bugs_from_raw(item.get("bugs", [])))))
    lists.sort(key=lambda entry: entry.name.casefold())
    return lists


def save_bug_lists(path: Path, lists: list[BugList]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lists": [
            {
                "name": entry.name,
                "bugs": [{"bug_id": bug.bug_id, "title": bug.title} for bug in entry.bugs],
            }
            for entry in lists
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_bug_list(lists: list[BugList], name: str) -> list[BugList]:
    canonical = _require_name(name)
    if _find(lists, canonical) is not None:
        return lists
    copied = [*lists, BugList(canonical, ())]
    copied.sort(key=lambda entry: entry.name.casefold())
    return copied


def upsert_named_bug(
    lists: list[BugList],
    name: str,
    bug_id: str,
    title: str,
) -> list[BugList]:
    canonical = _canonical(lists, _require_name(name))
    bug = _clean_bug(bug_id, title)
    current = _find(lists, canonical)
    bugs = list(current.bugs) if current else []
    bugs = [item for item in bugs if item.bug_id.casefold() != bug.bug_id.casefold()]
    bugs.append(bug)
    bugs.sort(key=lambda item: item.bug_id.casefold())
    return _replace(lists, canonical, tuple(bugs))


def replace_bug_list(
    lists: list[BugList],
    name: str,
    bugs: list[WatchedBug],
) -> list[BugList]:
    canonical = _canonical(lists, _require_name(name))
    unique: list[WatchedBug] = []
    for bug in bugs:
        unique = [item for item in unique if item.bug_id.casefold() != bug.bug_id.casefold()]
        unique.append(bug)
    unique.sort(key=lambda item: item.bug_id.casefold())
    return _replace(lists, canonical, tuple(unique))


def remove_named_bugs(lists: list[BugList], name: str, bug_ids: set[str]) -> list[BugList]:
    current = _find(lists, name)
    if current is None:
        return lists
    drop = {bug_id.casefold() for bug_id in bug_ids}
    kept = tuple(bug for bug in current.bugs if bug.bug_id.casefold() not in drop)
    return _replace(lists, current.name, kept)


def delete_bug_list(lists: list[BugList], name: str) -> list[BugList]:
    return [entry for entry in lists if entry.name.casefold() != name.strip().casefold()]


def bugs_for(lists: list[BugList], name: str) -> list[WatchedBug]:
    current = _find(lists, name)
    return list(current.bugs) if current else []


def check_watched_bugs(notes: ReleaseNotes, bugs: list[WatchedBug]) -> list[BugCheck]:
    if not bugs:
        raise ReleaseNoteError("선택한 목록에 버그가 없습니다.")
    checks: list[BugCheck] = []
    for bug in bugs:
        keys = id_keys(bug.bug_id)
        if not keys:
            checks.append(
                BugCheck(bug.bug_id, bug.title, "확인 불가", "—", "Bug ID 형식을 읽지 못했습니다.")
            )
            continue
        matches = [item for item in notes.items if keys & item.keys]
        fixed = [item for item in matches if item.kind != "known"]
        known = [item for item in matches if item.kind == "known"]
        if fixed:
            item = fixed[0]
            checks.append(
                BugCheck(
                    bug.bug_id,
                    bug.title or item.description,
                    "Fixed",
                    "Fixed",
                    _short_note(item),
                    item.description,
                    item.section,
                    item.fixed_versions,
                )
            )
        elif known:
            item = known[0]
            checks.append(
                BugCheck(
                    bug.bug_id,
                    bug.title or item.description,
                    "유효",
                    "Known",
                    _short_note(item),
                    item.description,
                    item.section,
                    item.fixed_versions,
                )
            )
        else:
            checks.append(
                BugCheck(
                    bug.bug_id,
                    bug.title,
                    "미포함",
                    "—",
                    f"{notes.version} Release Note에 없습니다.",
                )
            )
    return checks


def advanced_issue_report(
    notes: ReleaseNotes,
    profile: ConfigProfile,
    items: list[ReleaseItem] | None = None,
    note: str = "",
) -> list[IssueRow]:
    version = profile.version or "확인 불가"
    rows = [
        IssueRow(
            "설정",
            "장비 버전",
            version,
            profile.build or "—",
            profile.hostname or "—",
        )
    ]
    if not profile.modules:
        rows.append(
            IssueRow(
                "설정",
                "—",
                "모듈",
                "확인 불가",
                "프로비전된 모듈을 찾지 못했습니다.",
            )
        )
        return rows
    for name, remark in profile.remarks:
        rows.append(IssueRow("설정", name, remark, "사용", notes.version))
    pool = items if items is not None else _config_items(notes, profile)
    rows.extend(basic_issue_report(notes, list(profile.modules), pool, note))
    return rows


def basic_issue_report(
    notes: ReleaseNotes,
    modules: list[str],
    items: list[ReleaseItem] | None = None,
    note: str = "",
) -> list[IssueRow]:
    chosen = [name for name in MODULES if name in modules]
    if not chosen:
        raise ReleaseNoteError("모듈을 하나 이상 선택하세요.")
    pool = items if items is not None else module_items(notes, chosen)
    return [_module_row(notes, name, pool, note) for name in chosen]


def module_items(notes: ReleaseNotes, modules: list[str]) -> list[ReleaseItem]:
    chosen = [name for name in MODULES if name in modules]
    return [item for item in notes.items if any(item_matches_module(item, name) for name in chosen)]


def _config_items(notes: ReleaseNotes, profile: ConfigProfile) -> list[ReleaseItem]:
    return [
        item
        for item in module_items(notes, list(profile.modules))
        if applies_to_config(f"{item.description} {item.cve}", profile.features)
    ]


def _module_row(
    notes: ReleaseNotes,
    module: str,
    pool: list[ReleaseItem],
    note: str,
) -> IssueRow:
    matched = [item for item in pool if item_matches_module(item, module)]
    fixed = sum(item.kind == "fixed" for item in matched)
    known = sum(item.kind == "known" for item in matched)
    vuln = sum(item.kind == "vulnerability" or bool(item.cve) for item in matched)
    detail = notes.version if not note else f"{notes.version} · {note}"
    return IssueRow(
        "Release Note",
        module,
        f"Fixed {fixed} · Known {known} · 취약점 {vuln}",
        "정리됨",
        detail,
    )


def _short_note(item: ReleaseItem) -> str:
    parts = [item.section]
    if item.fixed_versions:
        parts.append(item.fixed_versions)
    elif item.description:
        parts.append(item.description)
    return " · ".join(part for part in parts if part)


def _require_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ReleaseNoteError("목록 이름을 입력하세요.")
    return cleaned


def _clean_bug(bug_id: str, title: str) -> WatchedBug:
    bug_id = bug_id.strip()
    if not bug_id:
        raise ReleaseNoteError("Bug ID를 입력하세요.")
    return WatchedBug(bug_id, title.strip())


def _find(lists: list[BugList], name: str) -> BugList | None:
    folded = name.strip().casefold()
    for entry in lists:
        if entry.name.casefold() == folded:
            return entry
    return None


def _canonical(lists: list[BugList], name: str) -> str:
    current = _find(lists, name)
    return current.name if current else name


def _replace(lists: list[BugList], name: str, bugs: tuple[WatchedBug, ...]) -> list[BugList]:
    folded = name.casefold()
    replaced = [entry for entry in lists if entry.name.casefold() != folded]
    replaced.append(BugList(name, bugs))
    replaced.sort(key=lambda entry: entry.name.casefold())
    return replaced


def _bugs_from_raw(raw: object) -> list[WatchedBug]:
    bugs: list[WatchedBug] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        bug_id = str(item.get("bug_id", "")).strip()
        title = str(item.get("title", "")).strip()
        if bug_id:
            bugs.append(WatchedBug(bug_id, title))
    bugs.sort(key=lambda bug: bug.bug_id.casefold())
    return bugs


def _lists_from_raw(raw: object, *, legacy_name: str) -> list[BugList]:
    bugs = _bugs_from_raw(raw)
    if not bugs:
        return []
    return [BugList(legacy_name, tuple(bugs))]
