"""Save and optionally restore APM Advanced customization files.

Save always keeps user-logon.css, user-logon.js, and the other Advanced
templates that belong to a macro's Logon Page, Message Box, or Decision Box.
Load writes them only when Web Customizing Load is checked. The new macro
still gets its own customization group; the source group name is not reused.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from typing import Any

from app.modules.vpe_macro.macro_boxes import (
    _PRIVATE_CG,
    _failed,
    _run,
    _safe_name,
    _short_name,
    rename_macro_name,
)

_MAX_FILE = 48_000
_MAX_FILES = 12
# Edited Advanced files. The general_ui tree is only the stock template.
_CUSTOM_ROOT = "/var/sam/www/client/customization"
_UI_ROOT = "/var/sam/www/client/customization-group/general_ui"
_STAGE_ROOT = "/var/tmp/f5tool"
_STAGE_FILE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(?:css|js|inc)$")
_LANG_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$")
_UI_FILE_RE = re.compile(
    r"^/var/sam/www/client/customization-group/general_ui/"
    r"[A-Za-z0-9_.-]{1,80}/"
    r"[A-Za-z0-9_.-]{1,80}/"
    r"[a-z]{2}(?:[-_][a-z]{2})?/"
    r"(?:[A-Za-z0-9_.-]{1,80}/){0,2}"
    r"[A-Za-z0-9_.-]{1,80}\.(?:css|js|inc)$"
)
_DISK_DIR = {
    "logon-page": "logon",
    "message-box": "messagebox",
    "decision-box": "decisionbox",
}
_TEMPLATE_RE = re.compile(
    r"(?m)^\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,80})\s*\{([^{}]*)\}"
)
_CACHE_RE = re.compile(
    r"^/config/filestore/files_d/"
    r"[A-Za-z0-9_-]+_d/"
    r"customization_(?:group|template)_d/"
    r":[A-Za-z0-9_.-]+:[A-Za-z0-9_.:-]{1,220}$"
)


def _file_rejected(body: str) -> bool:
    head = (body or "").lstrip().lower()
    return "\x00" in body or head.startswith("cat:") or head.startswith("bash rejected")


_UNSAFE = set("'\n\x00;&|`$<>\\")
_LIKELY = (
    "user-logon.css",
    "user-logon.js",
    "logon/Common/user-logon.css",
    "logon/Common/user-logon.js",
    "logon/en/user-logon.css",
    "logon/en/user-logon.js",
)


def _tree_file_allowed(path: str, root: str) -> bool:
    text = str(path or "").strip()
    base = root.rstrip("/")
    if not text.startswith(base + "/"):
        return False
    if not text.endswith((".css", ".js", ".inc")):
        return False
    if any(char in text for char in _UNSAFE):
        return False
    parts = [part for part in text.split("/") if part]
    return ".." not in parts and all(len(part) <= 120 for part in parts)


def general_ui_file_allowed(path: str) -> bool:
    """Macro folder under general_ui, then a language folder, then css/js/inc."""
    text = str(path or "").strip()
    if any(char in text for char in _UNSAFE) or ".." in text.split("/"):
        return False
    return _UI_FILE_RE.fullmatch(text) is not None


def www_path_allowed(path: str) -> bool:
    """Edited Advanced files. Only this tree, never a path that can leave it."""
    return _tree_file_allowed(path, _CUSTOM_ROOT)


def cache_child_allowed(path: str) -> bool:
    text = str(path or "").strip()
    if "/customization_group_d/" not in text and "/customization_template_d/" not in text:
        return False
    return _tree_file_allowed(text, "/config/filestore/files_d")


def _storage_root_allowed(path: str) -> bool:
    text = str(path or "").strip().rstrip("/")
    if not text or any(char in text for char in _UNSAFE) or ".." in text.split("/"):
        return False
    if cache_path_allowed(text):
        return True
    base = _CUSTOM_ROOT
    return text.startswith(base + "/") and text.count("/") >= base.count("/") + 2


def group_www_dir(partition: str, group: str) -> str:
    return (
        f"{_CUSTOM_ROOT}/{_safe_name(partition or 'Common')}/"
        f"{_safe_name(_short_name(group))}"
    )


def cache_path_allowed(path: str) -> bool:
    text = str(path or "").strip()
    return ".." not in text and _CACHE_RE.fullmatch(text) is not None


_FILESTORE_RE = re.compile(
    r"^/config/filestore/files_d/"
    r"(?P<part>[A-Za-z0-9_-]+)_d/"
    r"customization_(?P<kind>group|template)_d/"
    r":(?P<partition>[A-Za-z0-9_.-]+):(?P<agent>[A-Za-z0-9_.-]+)::"
    r"(?P<file>[A-Za-z0-9_.-]+\.(?:css|js|inc))_(?P<id>\d+)_(?P<rev>\d+)$"
)


def choose_filestore_files(lines: list[str], agent: str) -> list[tuple[str, str]]:
    """Pick the template file for this agent. A newer revision wins; template beats group."""
    best: dict[str, tuple[tuple[int, int, int], str]] = {}
    for line in lines:
        match = _FILESTORE_RE.fullmatch(line.strip())
        if match is None or match.group("agent") != agent:
            continue
        if not cache_path_allowed(match.group(0)):
            continue
        file_id = int(match.group("id"))
        rev = int(match.group("rev"))
        if file_id == 1 and rev == 1:
            continue
        logical = match.group("file")
        rank = (
            1 if match.group("kind") == "template" else 0,
            file_id,
            rev,
        )
        current = best.get(logical)
        if current is None or rank > current[0]:
            best[logical] = (rank, match.group(0))
    ordered = sorted(best, key=lambda name: (0 if name.startswith("user-logon.") else 1, name))
    return [(best[name][1], name) for name in ordered]


def list_agent_filestore(
    runner: Any,
    *,
    partition: str,
    agent: str,
) -> tuple[list[tuple[str, str]], str]:
    """Find :Partition:Agent::user-logon.css_id_rev in the filestore. Curl only, not SSH."""
    try:
        part = _safe_name(partition or "Common")
        agent = _safe_name(_short_name(agent))
    except ValueError:
        return [], "Logon 파일 이름이 없습니다."
    base = f"/config/filestore/files_d/{part}_d"
    listed = _run(
        runner,
        (
            f"find '{base}/customization_template_d' '{base}/customization_group_d' "
            f"-name ':{part}:{agent}::*'"
        ),
        timeout=8.0,
        max_bytes=65_536,
    )
    lines = [line.strip() for line in (listed or "").splitlines() if line.strip()]
    chosen = choose_filestore_files(lines, agent)
    if chosen:
        return chosen, ""
    hint = next((line for line in lines if not line.startswith("/config/")), "")
    hint = "".join(char for char in hint if char.isprintable())[:80]
    return [], (
        f"Logon 파일 없음 ({agent}, 목록 {len(lines)}줄" + (f": {hint}" if hint else "") + ")"
    )


def list_filestore_containing(
    runner: Any,
    *,
    partition: str,
    token: str,
) -> tuple[list[tuple[str, str]], str]:
    """After create, F5 assigns the revision number. Find that file by the new name."""
    try:
        part = _safe_name(partition or "Common")
        token = _safe_name(token)
    except ValueError:
        return [], "Logon 파일 이름이 없습니다."
    base = f"/config/filestore/files_d/{part}_d"
    chunks: list[str] = []
    for folder in ("customization_template_d", "customization_group_d"):
        for logical in ("user-logon.css", "user-logon.js"):
            chunks.append(
                _run(
                    runner,
                    f"find '{base}/{folder}' -name ':{part}:*{token}*{logical}*'",
                    timeout=8.0,
                    max_bytes=65_536,
                )
            )
    lines = [line.strip() for chunk in chunks for line in chunk.splitlines() if line.strip()]
    best: dict[str, tuple[tuple[int, int, int], str]] = {}
    for line in lines:
        match = _FILESTORE_RE.fullmatch(line)
        if match is None or token not in match.group("agent"):
            continue
        if not cache_path_allowed(match.group(0)):
            continue
        file_id = int(match.group("id"))
        rev = int(match.group("rev"))
        if file_id == 1 and rev == 1:
            continue
        logical = match.group("file")
        rank = (
            1 if match.group("kind") == "template" else 0,
            file_id,
            rev,
        )
        current = best.get(logical)
        if current is None or rank > current[0]:
            best[logical] = (rank, match.group(0))
    if not best:
        return [], f"생성 후 Logon 파일 없음 ({token}, 목록 {len(lines)}줄)"
    ordered = sorted(best, key=lambda name: (0 if name.startswith("user-logon.") else 1, name))
    return [(best[name][1], name) for name in ordered], ""


def group_cache_logon_files(runner: Any, listed: str) -> list[tuple[str, str]]:
    """user-logon.css inside the customization group cache the editor opens."""
    roots: list[str] = []
    for match in re.finditer(r"cache-path\s+(\S+)", listed or ""):
        path = match.group(1).strip().strip('"').rstrip("/")
        if _storage_root_allowed(path):
            roots.append(path)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        listed_files = _run(
            runner,
            (
                f"find '{root}' -name 'user-logon.css'; "
                f"find '{root}' -name 'user-logon.js'"
            ),
            timeout=8.0,
            max_bytes=65_536,
        )
        for line in (listed_files or "").splitlines():
            path = line.strip()
            if not path.startswith(root + "/") or path in seen or not cache_child_allowed(path):
                continue
            logical = path.rsplit("/", 1)[-1]
            if logical not in {"user-logon.css", "user-logon.js"}:
                continue
            seen.add(path)
            found.append((path, logical))
    return found


def read_agent_filestore_files(
    runner: Any,
    *,
    partition: str,
    agent: str,
) -> tuple[list[dict[str, str]], str]:
    chosen, note = list_agent_filestore(runner, partition=partition, agent=agent)
    files: list[dict[str, str]] = []
    for path, logical in chosen:
        if len(files) >= 24:
            break
        text = _cat_file(runner, path)
        if not text.strip():
            continue
        files.append({"name": logical, "relative": logical, "text": text[:_MAX_FILE]})
    if files:
        return files, ""
    return [], note or f"Logon 파일 없음 ({_short_name(agent)})"


def customization_templates(text: str) -> list[dict[str, str]]:
    """Advanced files listed on one customization group."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _TEMPLATE_RE.finditer(text or ""):
        filename = match.group(1)
        if not filename.endswith((".css", ".js", ".inc")) or filename in seen:
            continue
        cache = re.search(r"cache-path\s+(\S+)", match.group(2))
        if cache is None or not cache_path_allowed(cache.group(1)):
            continue
        seen.add(filename)
        found.append({"name": filename, "cache_path": cache.group(1)})
    return found


def _group_target(group_path: str) -> tuple[str, str]:
    text = str(group_path or "").strip()
    parts = [part for part in text.split("/") if part]
    if len(parts) >= 2:
        return _safe_name(parts[0]), _safe_name(parts[-1])
    return "Common", _safe_name(_short_name(text))


def _remember_file(
    files: list[dict[str, str]],
    seen: set[str],
    *,
    name: str,
    relative: str,
    text: str,
) -> None:
    if not name or name in seen or len(files) >= _MAX_FILES or not text.strip():
        return
    seen.add(name)
    files.append({"name": name, "relative": relative, "text": text[:_MAX_FILE]})


def _cat_file(runner: Any, path: str) -> str:
    body = _run(runner, f"cat '{path}'", timeout=8.0, max_bytes=_MAX_FILE + 64)
    if _file_rejected(body):
        return ""
    return body


def _editor_relative(path: str, root: str) -> str:
    relative = path[len(root.rstrip("/")) + 1 :]
    name = relative.rsplit("/", 1)[-1]
    if "/" not in relative and name.startswith("user-logon."):
        return f"logon/Common/{name}"
    return relative


def _take_tree(
    runner: Any,
    root: str,
    *,
    allowed: Callable[[str], bool],
    files: list[dict[str, str]],
    seen: set[str],
) -> list[str]:
    if not _storage_root_allowed(root):
        return []
    listed = _run(
        runner,
        (
            f"find '{root}' -type f -name '*.css' -o -type f -name '*.js' "
            f"-o -type f -name '*.inc'"
        ),
        timeout=8.0,
        max_bytes=65_536,
    )
    lines = [line.strip() for line in (listed or "").splitlines() if line.strip()]
    ranked = sorted(
        lines,
        key=lambda path: (0 if path.endswith(("user-logon.css", "user-logon.js")) else 1, path),
    )
    for path in ranked:
        if not allowed(path) or not path.startswith(root.rstrip("/") + "/"):
            continue
        text = _cat_file(runner, path)
        _remember_file(
            files,
            seen,
            name=path.rsplit("/", 1)[-1],
            relative=_editor_relative(path, root),
            text=text,
        )
    if files:
        return lines
    for relative in _LIKELY:
        path = f"{root.rstrip('/')}/{relative}"
        if not allowed(path):
            continue
        text = _cat_file(runner, path)
        _remember_file(
            files,
            seen,
            name=relative.rsplit("/", 1)[-1],
            relative=relative if "/" in relative else f"logon/Common/{relative}",
            text=text,
        )
    return lines


def read_customization_files(runner: Any, group_path: str) -> list[dict[str, str]]:
    partition, name = _group_target(group_path)
    listed = _run(
        runner,
        f"tmsh -q list apm policy customization-group /{partition}/{name}",
        timeout=8.0,
        max_bytes=65_536,
    )
    if _failed(listed):
        return []
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for spec in customization_templates(listed):
        if len(files) >= _MAX_FILES:
            break
        text = _cat_file(runner, spec["cache_path"])
        relative = spec["name"]
        if spec["name"].startswith("user-logon."):
            relative = f"logon/Common/{spec['name']}"
        _remember_file(files, seen, name=spec["name"], relative=relative, text=text)
    for match in re.finditer(r"(?m)^\s*(?:cache-path|local-path)\s+(\S+)", listed or ""):
        root = match.group(1).strip().strip('"').rstrip("/")
        if not _storage_root_allowed(root):
            continue
        allowed = cache_child_allowed if root.startswith("/config/filestore/") else www_path_allowed
        _take_tree(runner, root, allowed=allowed, files=files, seen=seen)
    return files


def read_www_customization_files(
    runner: Any,
    *,
    partition: str,
    group: str,
) -> tuple[list[dict[str, str]], str]:
    """Read user-logon.css and the other files the editor shows for this group."""
    try:
        root = group_www_dir(partition, group)
    except ValueError:
        return [], "Web Customizing 그룹 이름이 없습니다."
    files: list[dict[str, str]] = []
    lines = _take_tree(
        runner,
        root,
        allowed=www_path_allowed,
        files=files,
        seen=set(),
    )
    if files:
        return files, ""
    hint = next((line for line in lines if not line.startswith(root + "/")), "")
    hint = "".join(char for char in hint if char.isprintable())[:80]
    return [], (
        f"Advanced Customization 파일 0개 ({_short_name(group)}, 목록 {len(lines)}줄"
        + (f": {hint}" if hint else "")
        + ")"
    )


def read_general_ui_files(
    runner: Any,
    *,
    partition: str,
    folders: list[str],
) -> tuple[list[dict[str, str]], str]:
    """Read user-logon.css/js from general_ui/<partition>/<macro>/<lang>/."""
    try:
        part = _safe_name(partition or "Common")
    except ValueError:
        return [], "Web Customizing 파티션 이름이 없습니다."
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    missed: list[str] = []
    for folder in folders:
        try:
            name = _safe_name(_short_name(folder))
        except ValueError:
            continue
        root = f"{_UI_ROOT}/{part}/{name}"
        listed = _run(
            runner,
            (
                f"find '{root}' -type f \\( -name '*.css' -o -name '*.js' "
                f"-o -name '*.inc' \\)"
            ),
            timeout=8.0,
            max_bytes=65_536,
        )
        lines = [line.strip() for line in (listed or "").splitlines() if line.strip()]
        ranked = sorted(
            lines,
            key=lambda path: (
                0 if path.endswith(("user-logon.css", "user-logon.js")) else 1,
                path,
            ),
        )
        found = False
        for path in ranked:
            if not general_ui_file_allowed(path) or not path.startswith(root + "/"):
                continue
            relative = path[len(root) + 1 :]
            if not _LANG_RE.fullmatch(relative.split("/", 1)[0]):
                continue
            if relative in seen or len(files) >= 24:
                continue
            text = _cat_file(runner, path)
            if not text.strip():
                continue
            seen.add(relative)
            found = True
            files.append(
                {
                    "name": relative.rsplit("/", 1)[-1],
                    "relative": relative,
                    "text": text[:_MAX_FILE],
                }
            )
        if found:
            return files, ""
        missed.append(name)
    if files:
        return files, ""
    shown = ", ".join(missed) if missed else "이름 없음"
    return [], f"general_ui/{part} 에 Macro 폴더가 없습니다 ({shown})"


def merge_www_files(agents: list[dict[str, Any]], files: list[dict[str, str]]) -> None:
    """Keep the editor files on the Logon Page agent. Save stores that list."""
    if not files:
        return
    target = next(
        (agent for agent in agents if str(agent.get("type") or "") in _PRIVATE_CG),
        None,
    )
    if target is None:
        return
    current = [
        item for item in (target.get("customization_files") or []) if isinstance(item, dict)
    ]
    order: list[str] = []
    by_name: dict[str, dict[str, str]] = {}
    for item in current:
        key = str(item.get("relative") or item.get("name") or "")
        if key and key not in by_name:
            order.append(key)
            by_name[key] = item
    for item in files:
        key = str(item.get("relative") or item.get("name") or "")
        if not key:
            continue
        if key not in by_name:
            order.append(key)
        by_name[key] = item
    target["customization_files"] = [by_name[key] for key in order]


def attach_customization_files(
    runner: Any,
    agents: list[dict[str, Any]],
    *,
    progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Read Advanced files onto logon, message, and decision agents. Save always does this."""
    notes: list[str] = []
    seen: dict[str, list[dict[str, str]]] = {}
    for agent in agents:
        if str(agent.get("type") or "") not in _PRIVATE_CG:
            continue
        group = str(agent.get("customization_group") or "").strip()
        if not group:
            continue
        if group not in seen:
            try:
                seen[group] = read_customization_files(runner, group)
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                seen[group] = []
                short = _short_name(group)
                notes.append(f"Web Customizing을 읽지 못했습니다 ({short}): {str(exc)[:80]}")
            if seen[group] and progress is not None:
                progress(
                    f"Web Customizing {len(seen[group])}개 저장… ({_short_name(group)})"
                )
        agent["customization_files"] = list(seen[group])
    return notes


def staging_path(group: str, filename: str) -> str:
    """Temp file F5 reads when a template is registered. Not the editor path."""
    group = _safe_name(group)
    if _STAGE_FILE_RE.fullmatch(filename) is None:
        raise ValueError(filename)
    path = f"{_STAGE_ROOT}/{group}__{filename}"
    if any(char in path for char in _UNSAFE) or ".." in path.split("/"):
        raise ValueError(path)
    return path


def template_import_command(
    partition: str,
    group: str,
    staged: list[tuple[str, str]],
    *,
    verb: str,
) -> str:
    """Ask mcpd to copy the temp file and assign the editor's cache-path."""
    if verb not in {"add", "modify"} or not staged:
        raise ValueError(verb)
    partition = _safe_name(partition or "Common")
    group = _safe_name(group)
    inner = " ".join(f"{name} {{ local-path {path} }}" for name, path in staged)
    return (
        f"tmsh modify apm policy customization-group /{partition}/{group} "
        f"{{ templates {verb} {{ {inner} }} }}"
    )


def _short_tmsh(text: str) -> str:
    clean = "".join(char for char in (text or "") if char.isprintable())
    return " ".join(clean.split())[:140]


def _template_exists(listed: str, filename: str) -> bool:
    return re.search(rf"(?m)^\s*{re.escape(filename)}\s*\{{", listed or "") is not None


def customization_write_commands(
    listed_tmsh: str,
    saved_files: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Commands that copy saved Advanced files onto the new group's own files."""
    slots = {
        item["name"]: item["cache_path"] for item in customization_templates(listed_tmsh)
    }
    commands: list[tuple[str, str]] = []
    for saved in saved_files:
        if not isinstance(saved, dict):
            continue
        filename = str(saved.get("name") or "")
        path = slots.get(filename) or ""
        text = str(saved.get("text") or "")
        if not filename or not path or not text.strip() or not cache_path_allowed(path):
            continue
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", payload):
            continue
        commands.append((filename, f"printf '%s' '{payload}' | base64 -d > '{path}'"))
    return commands


def _general_ui_write_commands(
    saved_files: list[dict[str, Any]],
    *,
    partition: str,
    macro_name: str,
) -> list[tuple[str, str]]:
    """Write each language file under general_ui/<partition>/<new macro>/."""
    root = f"{_UI_ROOT}/{partition}/{macro_name}"
    commands: list[tuple[str, str]] = []
    for saved in saved_files:
        if not isinstance(saved, dict):
            continue
        relative = str(saved.get("relative") or "")
        text = str(saved.get("text") or "")
        lang = relative.split("/", 1)[0] if relative else ""
        if not text.strip() or not _LANG_RE.fullmatch(lang):
            continue
        path = f"{root}/{relative}"
        if not general_ui_file_allowed(path) or not path.startswith(root + "/"):
            continue
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", payload):
            continue
        parent = path.rsplit("/", 1)[0]
        commands.append(
            (relative, f"mkdir -p '{parent}' && printf '%s' '{payload}' | base64 -d > '{path}'")
        )
    return commands


def _www_write_commands(
    saved_files: list[dict[str, Any]],
    *,
    partition: str,
    group: str,
    fallback_dir: str,
) -> list[tuple[str, str]]:
    """Write onto the new group's editor directory. Create it if it is not there yet."""
    root = f"{_CUSTOM_ROOT}/{partition}/{group}"
    commands: list[tuple[str, str]] = []
    for saved in saved_files:
        if not isinstance(saved, dict):
            continue
        name = str(saved.get("name") or "")
        relative = str(saved.get("relative") or "")
        if not relative and name and fallback_dir and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            relative = f"{fallback_dir}/Common/{name}"
        text = str(saved.get("text") or "")
        if "/" not in relative or not text.strip():
            continue
        path = f"{root}/{relative}"
        if not www_path_allowed(path) or not path.startswith(root + "/"):
            continue
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", payload):
            continue
        parent = path.rsplit("/", 1)[0]
        commands.append(
            (relative, f"mkdir -p '{parent}' && printf '%s' '{payload}' | base64 -d > '{path}'")
        )
    return commands


def apply_saved_customization(
    runner: Any,
    *,
    partition: str,
    source_name: str,
    actual: str,
    agents: list[dict[str, Any]],
    target_profile: str = "",
    progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Write saved files after create. The revision number exists only then."""

    def _progress(message: str) -> None:
        if progress is not None:
            progress(message)
    partition = _safe_name(partition or "Common")
    source = _short_name(source_name)
    actual = _safe_name(actual)
    written: list[str] = []
    missing: list[str] = []
    had_files = False
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("type") or "") not in _PRIVATE_CG:
            continue
        files = [
            item
            for item in (agent.get("customization_files") or [])
            if isinstance(item, dict) and str(item.get("name") or "")
        ]
        if not files:
            continue
        had_files = True
        placed: set[str] = set()
        new_agent = _safe_name(rename_macro_name(str(agent.get("name") or ""), source, actual))
        group = _safe_name(f"{new_agent}_cg")
        listed = _run(
            runner,
            f"tmsh -q list apm policy customization-group /{partition}/{group}",
            timeout=8.0,
            max_bytes=65_536,
        )
        if not _failed(listed):
            for filename, command in customization_write_commands(listed, files):
                _run(runner, command, timeout=8.0, max_bytes=4_096)
                written.append(filename)
                placed.add(filename)
        staged: list[tuple[str, str]] = []
        for item in files:
            logical = str(item.get("name") or "")
            text = str(item.get("text") or "")
            if not text.strip():
                continue
            try:
                path = staging_path(group, logical)
            except ValueError:
                continue
            payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
            if not re.fullmatch(r"[A-Za-z0-9+/=]+", payload):
                continue
            _run(
                runner,
                (
                    f"mkdir -p '{_STAGE_ROOT}' && "
                    f"printf '%s' '{payload}' | base64 -d > '{path}' && chmod 644 '{path}'"
                ),
                timeout=8.0,
                max_bytes=4_096,
            )
            staged.append((logical, path))
        for logical, path in staged:
            verb = "modify" if _template_exists(listed, logical) else "add"
            _progress(f"편집기에 등록: {logical} ({verb}, {group})")
            result = _run(
                runner,
                template_import_command(partition, group, [(logical, path)], verb=verb),
                timeout=12.0,
                max_bytes=8_192,
            )
            if _failed(result):
                other = "add" if verb == "modify" else "modify"
                _progress(f"{logical} 다시 시도 ({other}): {_short_tmsh(result) or '실패'}")
                result = _run(
                    runner,
                    template_import_command(
                        partition, group, [(logical, path)], verb=other
                    ),
                    timeout=12.0,
                    max_bytes=8_192,
                )
            if _failed(result):
                _progress(f"{logical} 등록 실패: {_short_tmsh(result) or '응답 없음'}")
                continue
            written.append(logical)
            placed.add(logical)
        again = _run(
            runner,
            f"tmsh -q list apm policy customization-group /{partition}/{group}",
            timeout=8.0,
            max_bytes=65_536,
        )
        slots = customization_templates(again if not _failed(again) else "")
        if slots:
            shown = ", ".join(item["cache_path"].rsplit("/", 1)[-1] for item in slots[:4])
            _progress(f"편집기 cache-path: {shown}")
        elif staged and not placed:
            _progress(f"편집기 cache-path 없음 ({group})")
        if staged:
            cleanup = " ".join(f"'{path}'" for _logical, path in staged)
            _run(runner, f"rm -f {cleanup}", timeout=4.0, max_bytes=1_024)
        for relative, command in _general_ui_write_commands(
            files,
            partition=partition,
            macro_name=actual,
        ):
            _run(runner, command, timeout=8.0, max_bytes=4_096)
            written.append(relative)
            placed.add(relative.rsplit("/", 1)[-1])
        for relative, command in _www_write_commands(
            files,
            partition=partition,
            group=group,
            fallback_dir=_DISK_DIR.get(str(agent.get("type") or ""), ""),
        ):
            _run(runner, command, timeout=8.0, max_bytes=4_096)
            written.append(relative)
            placed.add(relative.rsplit("/", 1)[-1])
        for item in files:
            filename = str(item.get("name") or "")
            if filename and filename not in placed:
                missing.append(filename)
    if not had_files:
        return ["Web Customizing Load를 켰지만 저장된 Advanced 파일이 없습니다."]
    notes: list[str] = []
    if written:
        notes.append("Web Customizing 적용: " + ", ".join(dict.fromkeys(written)))
    if missing:
        names = ", ".join(dict.fromkeys(name for name in missing if name))
        notes.append(f"새 그룹에 없어 넣지 못한 Web Customizing: {names}")
    return notes or ["Web Customizing 파일을 새 그룹에 넣지 못했습니다."]
