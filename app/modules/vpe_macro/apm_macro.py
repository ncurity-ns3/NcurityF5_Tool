from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.core.redaction import redact_data
from app.modules.vpe_macro.macro_boxes import (
    collect_macro_boxes,
    saved_macro_cleanup_command,
    saved_macro_transaction,
    snapshot_flow_items,
)

SNAPSHOT_FORMAT = "ncurity-apm-macro-v1"

_REST_META_KEYS = frozenset(
    {
        "kind",
        "generation",
        "selfLink",
        "fullPath",
        "isSubcollection",
        "nestedStats",
        "apiRawValues",
    }
)

_PATH_RE = re.compile(r"^/[^/\s]+/[^/\s]+")
_AGENT_LINK_RE = re.compile(
    r"/tm/apm/policy/agent/([^/~]+)/~([^~]+)~([^/?]+)",
    re.IGNORECASE,
)
_KIND_AGENT_RE = re.compile(
    r"^tm:apm:policy:agent:([^:]+):",
    re.IGNORECASE,
)

_EXTERNAL_KEYS = frozenset(
    {
        "server",
        "servers",
        "aaa",
        "aaaServer",
        "webtop",
        "webtops",
        "resources",
        "resource",
        "pool",
        "ssoConfig",
        "ssoConfiguration",
        "customizationGroup",
        "domainController",
        "activeDirectory",
        "ldap",
        "radius",
        "ocsp",
        "crl",
    }
)

# Device objects selected inside agents — Load as none. Text/expressions stay.
_OBJECT_REF_KEYS = _EXTERNAL_KEYS | frozenset(
    {
        "aaaServers",
        "httpServer",
        "httpAuth",
        "webtopSection",
        "webtopSections",
        "webtopLink",
        "webtopLinks",
        "resourceItems",
        "resourceAssignItems",
        "acl",
        "acls",
        "networkAccess",
        "portalAccess",
        "appTunnel",
        "remoteDesktop",
        "saml",
        "oauth",
        "caBundle",
        "sslProfile",
        "filter",
        "directory",
        "pools",
        "leasepool",
        "ipv4Leasepool",
        "ipv6Leasepool",
    }
)

_KEEP_TEXT_KEYS = frozenset(
    {
        "expression",
        "expr",
        "customExpression",
        "tcl",
        "variables",
        "variable",
        "left",
        "right",
        "unsecure",
        "caption",
        "name",
        "partition",
        "type",
        "subtype",
        "nextItem",
        "itemType",
        "priority",
        "syntax",
        "sessionVar",
    }
)

_KEEP_FULL_AGENT_TYPES = frozenset(
    {
        "variable-assign",
        "empty",
    }
)


class ApmRestClient(Protocol):
    def get(self, path: str) -> dict[str, Any]: ...

    def get_optional(self, path: str) -> dict[str, Any]: ...

    def post(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]: ...

    def patch(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]: ...

    def run_util_bash(self, shell_command: str, *, timeout: float | None = None) -> str: ...


@dataclass(frozen=True)
class AccessProfileRef:
    name: str
    partition: str
    full_path: str
    policy_path: str
    policy_name: str


@dataclass(frozen=True)
class MacroSummary:
    caption: str
    name: str
    partition: str
    full_path: str
    exits: tuple[str, ...]
    agent_labels: tuple[str, ...]
    item_count: int
    item_paths: tuple[str, ...]


@dataclass
class AgentRecord:
    agent_type: str
    name: str
    partition: str
    full_path: str
    body: dict[str, Any]


@dataclass
class MacroSnapshot:
    format: str = SNAPSHOT_FORMAT
    saved_at: str = ""
    source_host: str = ""
    source_hostname: str = ""
    access_profile: str = ""
    access_policy: str = ""
    policy_name: str = ""
    partition: str = "Common"
    macro_full_path: str = ""
    macro_caption: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    agents: list[dict[str, Any]] = field(default_factory=list)
    external_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return redact_data(
            {
                "format": self.format,
                "saved_at": self.saved_at,
                "source": {
                    "host": self.source_host,
                    "hostname": self.source_hostname,
                    "access_profile": self.access_profile,
                    "access_policy": self.access_policy,
                    "macro_name": self.macro_full_path,
                    "macro_caption": self.macro_caption,
                },
                "policy_name": self.policy_name,
                "partition": self.partition,
                "macro_full_path": self.macro_full_path,
                "macro_caption": self.macro_caption,
                "items": self.items,
                "agents": self.agents,
                "external_refs": self.external_refs,
                "warnings": self.warnings,
            }
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroSnapshot:
        if not isinstance(data, dict):
            raise ValueError("Macro 파일이 객체가 아닙니다.")
        fmt = str(data.get("format") or "")
        if fmt and fmt != SNAPSHOT_FORMAT:
            raise ValueError(f"지원하지 않는 Macro 파일 형식: {fmt}")
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        agents = data.get("agents") if isinstance(data.get("agents"), list) else []
        refs = data.get("external_refs") if isinstance(data.get("external_refs"), list) else []
        warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        return cls(
            format=SNAPSHOT_FORMAT,
            saved_at=str(data.get("saved_at") or ""),
            source_host=str(source.get("host") or ""),
            source_hostname=str(source.get("hostname") or ""),
            access_profile=str(
                data.get("access_profile") or source.get("access_profile") or ""
            ),
            access_policy=str(
                data.get("access_policy") or source.get("access_policy") or ""
            ),
            policy_name=str(data.get("policy_name") or ""),
            partition=str(data.get("partition") or "Common"),
            macro_full_path=str(
                data.get("macro_full_path") or source.get("macro_name") or ""
            ),
            macro_caption=str(
                data.get("macro_caption") or source.get("macro_caption") or ""
            ),
            items=[i for i in items if isinstance(i, dict)],
            agents=[a for a in agents if isinstance(a, dict)],
            external_refs=[str(r) for r in refs],
            warnings=[str(w) for w in warnings],
        )


@dataclass
class ApplyPlan:
    target_profile: str
    target_policy: str
    target_policy_name: str
    target_partition: str
    agents: list[tuple[str, dict[str, Any]]]
    items: list[dict[str, Any]]
    item_refs: list[dict[str, Any]]
    macro_refs: list[dict[str, Any]]
    collisions: list[str]
    missing_external: list[str]
    warnings: list[str]
    reuse_existing: bool = False


@dataclass
class ApplyResult:
    created_agents: list[str]
    created_items: list[str]
    skipped: list[str]
    applied_policy: bool
    generation_incremented: bool
    messages: list[str]


class MacroApplyError(RuntimeError):
    pass


def rest_id(full_path: str) -> str:
    text = (full_path or "").strip()
    if text.startswith("~"):
        return text.split("?", 1)[0]
    parts = [p for p in text.strip("/").split("/") if p]
    return "~" + "~".join(parts)


def item_full_path(obj: dict[str, Any]) -> str:
    full = obj.get("fullPath")
    if isinstance(full, str) and full.startswith("/"):
        return full
    partition = str(obj.get("partition") or obj.get("tmPartition") or "Common")
    name = str(obj.get("name") or "")
    if not name:
        return ""
    if name.startswith("/"):
        return name
    return f"/{partition}/{name}"


def split_full_path(full_path: str) -> tuple[str, str]:
    text = (full_path or "").strip()
    if text.startswith("~"):
        parts = [p for p in text.split("~") if p]
        if len(parts) >= 2:
            return parts[0], parts[-1]
        return "Common", parts[-1] if parts else ""
    parts = [p for p in text.strip("/").split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    if parts:
        return "Common", parts[0]
    return "Common", ""


def collection_items(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or body.get("_unavailable"):
        return []
    items = body.get("items")
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    return []


def is_macro_item(item: dict[str, Any]) -> bool:
    raw = item.get("itemType") or item.get("item-type") or ""
    return str(raw).lower() == "macro"


_TERMINAL_ITEM_TYPES = frozenset({"terminal", "terminal-out"})


def _is_terminal_item(item: dict[str, Any]) -> bool:
    raw = str(item.get("itemType") or item.get("item-type") or "").lower()
    return raw in _TERMINAL_ITEM_TYPES


def _is_nested_prefix_child(macro_name: str, item_name: str) -> bool:
    prefix = f"{macro_name}_"
    if not item_name.startswith(prefix):
        return False
    return bool(re.match(r"^\d+_", item_name[len(prefix) :]))


def belongs_to_policy(item: dict[str, Any], policy_name: str) -> bool:
    name = str(item.get("name") or "")
    return name == policy_name or name.startswith(f"{policy_name}_")


def next_item_paths(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    partition = str(item.get("partition") or item.get("tmPartition") or "Common")
    rules = item.get("rules") or []
    if not isinstance(rules, list):
        return out
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        nxt = rule.get("nextItem") or rule.get("next-item")
        if isinstance(nxt, str) and nxt.strip():
            out.append(_normalize_ref(nxt, partition))
    return out


def _linked_item_paths(item: dict[str, Any]) -> list[str]:
    partition = str(item.get("partition") or item.get("tmPartition") or "Common")
    paths = list(next_item_paths(item))
    macro_ref = item.get("macro")
    if isinstance(macro_ref, str) and macro_ref.strip():
        paths.append(_normalize_ref(macro_ref, partition))
    elif isinstance(macro_ref, dict):
        path = item_full_path(macro_ref)
        if path:
            paths.append(path)
    return paths


def _entry_candidate_paths(macro_path: str) -> list[str]:
    partition, name = split_full_path(macro_path)
    if not name:
        return []
    return [
        f"/{partition}/{name}_ent_in",
        f"/{partition}/{name}_ent",
        f"/{partition}/{name}_in",
    ]


def rule_captions(item: dict[str, Any]) -> list[str]:
    rules = item.get("rules") or []
    if not isinstance(rules, list):
        return []
    captions: list[str] = []
    for rule in rules:
        if isinstance(rule, dict):
            cap = str(rule.get("caption") or "").strip()
            captions.append(cap or "(unnamed)")
    return captions


def strip_rest_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in _REST_META_KEYS or key.endswith("Reference"):
                continue
            cleaned[key] = strip_rest_metadata(item)
        return cleaned
    if isinstance(value, list):
        return [strip_rest_metadata(item) for item in value]
    return value


def remap_string(
    text: str,
    *,
    source_policy: str,
    target_policy: str,
    source_partition: str,
    target_partition: str,
) -> str:
    if not text:
        return text
    if source_policy == target_policy and source_partition == target_partition:
        return text

    def _prefix_once(value: str, src: str, dst: str) -> str | None:
        if value == src or value.startswith(src + "_"):
            return dst + value[len(src) :]
        return None

    for src, dst in (
        (f"/{source_partition}/{source_policy}", f"/{target_partition}/{target_policy}"),
        (f"~{source_partition}~{source_policy}", f"~{target_partition}~{target_policy}"),
        (source_policy, target_policy),
    ):
        hit = _prefix_once(text, src, dst)
        if hit is not None:
            return hit
    out = text.replace(
        f"/{source_partition}/{source_policy}_",
        f"/{target_partition}/{target_policy}_",
    )
    return out.replace(
        f"~{source_partition}~{source_policy}_",
        f"~{target_partition}~{target_policy}_",
    )


def remap_value(
    value: Any,
    *,
    source_policy: str,
    target_policy: str,
    source_partition: str,
    target_partition: str,
) -> Any:
    if isinstance(value, dict):
        return {
            key: remap_value(
                item,
                source_policy=source_policy,
                target_policy=target_policy,
                source_partition=source_partition,
                target_partition=target_partition,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            remap_value(
                item,
                source_policy=source_policy,
                target_policy=target_policy,
                source_partition=source_partition,
                target_partition=target_partition,
            )
            for item in value
        ]
    if isinstance(value, str):
        return remap_string(
            value,
            source_policy=source_policy,
            target_policy=target_policy,
            source_partition=source_partition,
            target_partition=target_partition,
        )
    return value


def policy_path_from_profile(profile: dict[str, Any]) -> str:
    access_policy = profile.get("accessPolicy") or profile.get("access-policy")
    partition = str(profile.get("partition") or profile.get("tmPartition") or "Common")
    if isinstance(access_policy, str) and access_policy.strip():
        text = access_policy.strip()
        if text.startswith("/"):
            return text
        return f"/{partition}/{text}"
    if isinstance(access_policy, dict):
        path = item_full_path(access_policy)
        if path:
            return path
    ref = profile.get("accessPolicyReference")
    if isinstance(ref, dict):
        link = str(ref.get("link") or "")
        marker = "/access-policy/"
        if marker in link:
            encoded = link.split(marker, 1)[1].split("?", 1)[0]
            part, name = split_full_path(encoded)
            if name:
                return f"/{part}/{name}"
    return item_full_path(profile)


def is_builtin_access_profile(ref: AccessProfileRef) -> bool:
    """Parent template `/Common/access` has no Access Policy object."""
    return ref.name.lower() == "access"


def parse_access_profiles(
    body: dict[str, Any], *, include_builtin: bool = False
) -> list[AccessProfileRef]:
    refs: list[AccessProfileRef] = []
    for item in collection_items(body):
        full = item_full_path(item)
        if not full:
            continue
        partition, name = split_full_path(full)
        policy_path = policy_path_from_profile(item)
        _ppart, policy_name = split_full_path(policy_path)
        refs.append(
            AccessProfileRef(
                name=name,
                partition=partition,
                full_path=full,
                policy_path=policy_path or full,
                policy_name=policy_name or name,
            )
        )
    if not include_builtin:
        refs = [r for r in refs if not is_builtin_access_profile(r)]
    refs.sort(key=lambda r: r.full_path.lower())
    return refs


def _normalize_ref(raw: str, partition: str) -> str:
    text = raw.strip()
    if text.startswith("/"):
        return text
    if text.startswith("~"):
        part, name = split_full_path(text)
        return f"/{part}/{name}"
    if "/" in text:
        return f"/{text.lstrip('/')}"
    return f"/{partition}/{text}"


def _items_by_path(
    items: list[dict[str, Any]], policy_name: str | None = None
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in items:
        if policy_name and not belongs_to_policy(item, policy_name):
            continue
        path = item_full_path(item)
        if path:
            mapping[path] = item
    return mapping


def _items_by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get("name") or "")
        if name:
            mapping[name] = item
    return mapping


def collect_main_flow_paths(
    items_by_path: dict[str, dict[str, Any]],
    start_item: str | None,
) -> set[str]:
    if not start_item:
        return set()
    seen: set[str] = set()
    stack = [start_item]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        item = items_by_path.get(current)
        if item is None:
            continue
        seen.add(current)
        if is_macro_item(item):
            continue
        stack.extend(next_item_paths(item))
    return seen


def collect_macro_item_paths(
    *,
    macro_item: dict[str, Any],
    policy: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[str]:
    items_by_path = _items_by_path(items)
    macro_path = item_full_path(macro_item)
    if macro_path and macro_path not in items_by_path:
        items_by_path[macro_path] = macro_item
    start = policy.get("startItem") or policy.get("start-item")
    start_path = _normalize_ref(str(start), str(policy.get("partition") or "Common")) if start else ""
    main_flow = collect_main_flow_paths(items_by_path, start_path or None)

    leftover = set(items_by_path) - main_flow
    leftover.add(macro_path)
    outs = [p for p in next_item_paths(macro_item) if p in leftover]

    reverse: dict[str, set[str]] = defaultdict(set)
    for path, item in items_by_path.items():
        if path not in leftover:
            continue
        for nxt in next_item_paths(item):
            reverse[nxt].add(path)

    collected: set[str] = {macro_path, *outs}
    stack = list(outs)
    while stack:
        current = stack.pop()
        for pred in reverse.get(current, ()):
            if pred in collected or pred in main_flow:
                continue
            if pred not in leftover:
                continue
            collected.add(pred)
            stack.append(pred)

    prefix = f"{macro_item.get('name')}_"
    for path, item in items_by_path.items():
        name = str(item.get("name") or "")
        if name.startswith(prefix) and path in leftover:
            collected.add(path)

    return sorted(p for p in collected if p in items_by_path)


def _macros_from_policy_field(policy: dict[str, Any]) -> list[str]:
    partition = str(policy.get("partition") or "Common")
    found: list[str] = []

    def add_name(name: str) -> None:
        text = name.strip().strip("{}")
        if not text:
            return
        found.append(_normalize_ref(text, partition))

    def consume(raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, str):
            for part in raw.replace(",", " ").split():
                add_name(part)
            return
        if isinstance(raw, list):
            for entry in raw:
                consume(entry)
            return
        if not isinstance(raw, dict) or raw.get("_unavailable"):
            return
        nested = raw.get("items")
        if isinstance(nested, list):
            consume(nested)
            return
        if raw.get("name"):
            path = item_full_path(raw)
            if path:
                found.append(path)
                return
        skip_keys = _REST_META_KEYS | {
            "link",
            "isSubcollection",
            "partition",
            "priority",
            "nestedStats",
        }
        for key, val in raw.items():
            if key.endswith("Reference"):
                consume(val)
                continue
            if key in skip_keys:
                continue
            add_name(str(key))

    consume(policy.get("macros"))
    consume(policy.get("macrosReference"))
    consume(policy.get("_macro_refs"))
    unique: list[str] = []
    seen: set[str] = set()
    for path in found:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


_TMSH_MACRO_NOISE = frozenset(
    {"apm", "policy", "access-policy", "macros", "items", "rules"}
)
_MACRO_TOKEN_RE = re.compile(r"[^\s{}]+")


def parse_tmsh_access_policy_macros(text: str, partition: str = "Common") -> list[str]:
    """Parse `tmsh list apm policy access-policy <name> macros` (block or one-line)."""
    if not text:
        return []
    names: list[str] = []
    seen: set[str] = set()
    in_macros = False

    def add(name: str) -> None:
        token = name.strip().strip(",")
        if not token or token in _TMSH_MACRO_NOISE:
            return
        if token.startswith("/"):
            _part, bare = split_full_path(token)
            if not bare or bare in _TMSH_MACRO_NOISE:
                return
            path = token
        else:
            if not re.fullmatch(r"[\w.-]+", token):
                return
            path = f"/{partition}/{token}"
        if path in seen:
            return
        seen.add(path)
        names.append(path)

    def add_tokens(fragment: str) -> None:
        for token in _MACRO_TOKEN_RE.findall(fragment or ""):
            add(token)

    for line in text.splitlines():
        stripped = line.strip()
        macros_match = re.search(r"\bmacros\s*\{(.*)$", line)
        if macros_match:
            in_macros = True
            rest = macros_match.group(1)
            add_tokens(rest)
            if "}" in rest:
                break
            continue
        if in_macros:
            if stripped == "}":
                break
            add_tokens(line)
            continue
        match = re.match(r"^\s*(?:/[\w.-]+/)?([\w.-]+)\s*\{", line)
        if match and not re.search(r"\baccess-policy\b", line):
            add(match.group(1))
    return names


def _resolve_item(
    path: str, by_path: dict[str, dict[str, Any]], by_name: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    item = by_path.get(path)
    if item is not None:
        return item
    _part, name = split_full_path(path)
    if name:
        return by_name.get(name)
    return None


def build_macro_summaries(
    *,
    policy: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[MacroSummary]:
    policy_name = str(policy.get("name") or "")
    by_path = {item_full_path(i): i for i in items if item_full_path(i)}
    by_name = _items_by_name(items)

    macros: dict[str, dict[str, Any]] = {}
    for path in _macros_from_policy_field(policy):
        item = _resolve_item(path, by_path, by_name)
        if item is not None:
            macros[item_full_path(item) or path] = item
            continue
        _part, name = split_full_path(path)
        macros[path] = {
            "name": name or path,
            "partition": _part,
            "fullPath": path,
            "caption": name or path,
            "itemType": "macro",
            "rules": [],
        }
    for item in items:
        if not is_macro_item(item):
            continue
        path = item_full_path(item)
        if not path:
            continue
        if belongs_to_policy(item, policy_name) or path in macros:
            macros[path] = item

    summaries: list[MacroSummary] = []
    for path, item in macros.items():
        closure = collect_macro_item_paths(macro_item=item, policy=policy, items=items)
        agent_labels: list[str] = []
        for cpath in closure:
            child = by_path.get(cpath)
            if child is None:
                continue
            agent_labels.extend(_agent_labels(child))
        summaries.append(
            MacroSummary(
                caption=str(item.get("caption") or item.get("name") or path),
                name=str(item.get("name") or ""),
                partition=str(item.get("partition") or "Common"),
                full_path=path,
                exits=tuple(rule_captions(item)),
                agent_labels=tuple(dict.fromkeys(agent_labels)),
                item_count=max(len(closure), 1),
                item_paths=tuple(closure) if closure else (path,),
            )
        )
    summaries.sort(key=lambda m: (m.caption.lower(), m.full_path.lower()))
    return summaries


def _agent_labels(item: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    agents = item.get("agents") or []
    if not isinstance(agents, list):
        return labels
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        type_name = str(agent.get("type") or "").strip()
        name = str(agent.get("name") or "").strip()
        if type_name and name:
            labels.append(f"{type_name}:{name}")
        elif name:
            labels.append(name)
        elif type_name:
            labels.append(type_name)
    return labels


def parse_agent_ref(agent: dict[str, Any], default_partition: str) -> tuple[str, str, str] | None:
    """Return (agent_type, partition, name) if resolvable."""
    name = str(agent.get("name") or "").strip()
    partition = str(agent.get("partition") or default_partition or "Common")
    type_name = str(agent.get("type") or "").strip()
    link = str(agent.get("link") or agent.get("selfLink") or "")
    match = _AGENT_LINK_RE.search(link)
    if match:
        type_name = type_name or match.group(1)
        partition = match.group(2)
        name = name or match.group(3)
    if type_name.lower() in {"", "ending-section"}:
        type_name = ""
    if not name:
        return None
    return type_name, partition, name


def agent_type_from_body(body: dict[str, Any]) -> str:
    kind = str(body.get("kind") or "")
    match = _KIND_AGENT_RE.match(kind)
    if match:
        return match.group(1)
    link = str(body.get("selfLink") or "")
    found = _AGENT_LINK_RE.search(link)
    if found:
        return found.group(1)
    return str(body.get("type") or "")


def extract_external_refs(
    *,
    agents: list[dict[str, Any]],
    items: list[dict[str, Any]],
    created_paths: set[str],
) -> list[str]:
    found: list[str] = []

    def walk(value: Any, *, parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, parent_key=str(key))
            return
        if isinstance(value, list):
            for item in value:
                walk(item, parent_key=parent_key)
            return
        if not isinstance(value, str):
            return
        if not _PATH_RE.match(value):
            return
        if value in created_paths:
            return
        if parent_key in _EXTERNAL_KEYS or parent_key.endswith("Name") or _PATH_RE.match(value):
            if parent_key in {"name", "fullPath", "nextItem", "macro"}:
                return
            if parent_key in _EXTERNAL_KEYS or parent_key in {
                "server",
                "customizationGroup",
                "ssoConfig",
            }:
                found.append(value)

    for agent in agents:
        body = agent.get("body") if isinstance(agent, dict) else None
        if isinstance(body, dict):
            walk(body)
        elif isinstance(agent, dict):
            walk(agent)
    for item in items:
        walk(item, parent_key="")
    unique = []
    seen: set[str] = set()
    for path in found:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def fetch_access_profiles_detached(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    progress: Callable[[int, int, str], None] | None = None,
    timeout: float = 20.0,
) -> list[AccessProfileRef]:
    """Login and list Access Profiles in curl.exe, outside this process."""

    def _report(current: int, total: int, message: str) -> None:
        if progress is not None:
            progress(current, total, message)

    _report(0, 1, "로그인 중…")
    token = _detached_login(host, port, username, password, timeout=min(timeout, 12.0))
    _report(0, 1, "Access Profile 목록 조회 중…")
    body = _detached_profile_collection(host, port, token, timeout=timeout)
    refs = parse_access_profiles(body)
    if not refs:
        raise RuntimeError(
            "Access Policy가 있는 Access Profile이 없습니다. "
            "기본 프로필(/Common/access)은 Access Policy가 없어 제외합니다."
        )
    total = len(refs)
    for index, ref in enumerate(refs, start=1):
        _report(index, total, ref.full_path)
    return refs


def _detached_login(host: str, port: int, username: str, password: str, *, timeout: float) -> str:
    from app.core.bigip_client import curl_exchange

    url = f"https://{host}:{int(port)}/mgmt/shared/authn/login"
    payloads = (
        {"username": username, "password": password, "loginProviderName": "tmos"},
        {"username": username, "password": password},
    )
    last_status = 0
    for payload in payloads:
        status, raw = curl_exchange(
            url, method="POST", timeout=timeout, payload=payload, max_bytes=65_536
        )
        last_status = status
        if status == 401:
            continue
        if status != 200:
            raise RuntimeError(f"로그인 실패 (HTTP {status}).")
        token = _token_from_login(raw)
        if token:
            return token
    if last_status == 401:
        raise RuntimeError("로그인 실패 (401). ID/Password를 확인하세요.")
    raise RuntimeError("TMOS 로그인에 실패했습니다.")


def _token_from_login(raw: bytes) -> str:
    try:
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return ""
    if not isinstance(body, dict):
        return ""
    token_obj = body.get("token")
    if isinstance(token_obj, dict):
        return str(token_obj.get("token") or "")
    return ""


def _detached_profile_collection(
    host: str, port: int, token: str, *, timeout: float
) -> dict[str, Any]:
    from app.core.bigip_client import curl_exchange

    base = f"https://{host}:{int(port)}/mgmt/tm/apm/profile/access"
    headers = {"X-F5-Auth-Token": token}
    status, raw = curl_exchange(
        base + "?$select=name,partition,fullPath,accessPolicy",
        method="GET",
        timeout=timeout,
        headers=headers,
        max_bytes=1_500_000,
    )
    if status == 400:
        status, raw = curl_exchange(
            base, method="GET", timeout=timeout, headers=headers, max_bytes=1_500_000
        )
    if status != 200:
        raise RuntimeError(f"Access Profile 목록 조회 실패 (HTTP {status}).")
    try:
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Access Profile 목록 응답을 읽지 못했습니다.") from exc
    if not isinstance(body, dict):
        raise RuntimeError("Access Profile 목록 응답이 비어 있습니다.")
    return body


def _get_access_profile_collection(client: ApmRestClient) -> dict[str, Any]:
    """Name and policy path only. The full profile document can stall the device."""
    selected = "/tm/apm/profile/access?$select=name,partition,fullPath,accessPolicy"
    try:
        body = client.get(selected)
    except Exception:
        body = None
    if isinstance(body, dict) and collection_items(body):
        return body
    return client.get("/tm/apm/profile/access")


def list_access_profiles(
    client: ApmRestClient,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[AccessProfileRef]:
    def _report(current: int, total: int, message: str) -> None:
        if progress is not None:
            progress(current, total, message)

    _report(0, 1, "Access Profile 목록 조회 중…")
    body = _get_access_profile_collection(client)
    refs = parse_access_profiles(body)
    if not refs:
        raise RuntimeError(
            "Access Policy가 있는 Access Profile이 없습니다. "
            "기본 프로필(/Common/access)은 Access Policy가 없어 제외합니다."
        )
    total = len(refs)
    for index, ref in enumerate(refs, start=1):
        _report(index, total, ref.full_path)
    return refs


def resolve_access_profile(client: ApmRestClient, profile_path: str) -> AccessProfileRef:
    """Resolve one Access Profile without loading the Access Policy / VPE body."""
    path = (profile_path or "").strip()
    if not path:
        raise RuntimeError("Access Profile 경로가 비어 있습니다.")
    getter = getattr(client, "get_optional", None)
    body = getter(f"/tm/apm/profile/access/{rest_id(path)}") if callable(getter) else client.get(
        f"/tm/apm/profile/access/{rest_id(path)}"
    )
    if not isinstance(body, dict) or body.get("_unavailable") or body.get("_http_status") == 404:
        raise RuntimeError(f"Access Profile을 찾을 수 없습니다: {path}")
    refs = parse_access_profiles({"items": [body]}, include_builtin=True)
    if not refs:
        raise RuntimeError(f"Access Profile을 찾을 수 없습니다: {path}")
    return refs[0]


_ITEM_WALK_LIMIT = 250


def _fetch_policy_item(client: ApmRestClient, path: str) -> dict[str, Any] | None:
    if not path:
        return None
    body = client.get_optional(f"/tm/apm/policy/policy-item/{rest_id(path)}")
    if isinstance(body, dict) and not body.get("_unavailable") and body.get("name"):
        return body
    return None


def _policy_item_presence(client: ApmRestClient, path: str) -> str:
    """Return exists / missing / unknown. unknown means do not recreate."""
    if not path:
        return "unknown"
    body = client.get_optional(f"/tm/apm/policy/policy-item/{rest_id(path)}")
    if not isinstance(body, dict) or not body:
        return "unknown"
    if not body.get("_unavailable") and body.get("name"):
        return "exists"
    if body.get("_http_status") == 404:
        return "missing"
    return "unknown"


def _already_exists_error(exc: BaseException) -> bool:
    text = str(exc)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        text = f"{text} {cause}"
    lowered = text.lower()
    return "already exists" in lowered or "409 conflict" in lowered or "'409" in lowered


def fetch_item_graph(
    client: ApmRestClient,
    seed_paths: list[str],
    *,
    progress: Callable[[str], None] | None = None,
    limit: int = _ITEM_WALK_LIMIT,
    skip_prefixes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch only the linked policy-items. Never dump the device-wide collection."""
    skip = [p for p in (skip_prefixes or []) if p]
    by_path: dict[str, dict[str, Any]] = {}
    queued: list[str] = []
    seen: set[str] = set()

    def _is_skipped(path: str) -> bool:
        _part, name = split_full_path(path)
        return any(name == prefix or name.startswith(prefix + "_") for prefix in skip)

    def _enqueue(path: str) -> None:
        text = (path or "").strip()
        if not text or text in seen or _is_skipped(text):
            return
        seen.add(text)
        queued.append(text)

    for path in seed_paths:
        _enqueue(path)
        for extra in _entry_candidate_paths(path):
            _enqueue(extra)

    while queued and len(by_path) < limit:
        path = queued.pop(0)
        body = _fetch_policy_item(client, path)
        if body is None:
            continue
        full = item_full_path(body) or path
        if full in by_path:
            continue
        by_path[full] = body
        for linked in _linked_item_paths(body):
            _enqueue(linked)
        if is_macro_item(body):
            for extra in _entry_candidate_paths(full):
                _enqueue(extra)
    return list(by_path.values())


def _policy_path_candidates(profile: AccessProfileRef) -> list[str]:
    """tmsh access-policy 이름. Access Profile 이름을 먼저 쓰고, REST의 ..._ap 는 나중."""
    part = profile.partition or "Common"
    name = (profile.name or "").strip()
    ordered = [f"/{part}/{name}" if name else ""]
    rest_path = (profile.policy_path or "").strip()
    if rest_path:
        ordered.append(rest_path)
    policy_name = (profile.policy_name or "").strip()
    if policy_name:
        ordered.append(
            policy_name if policy_name.startswith("/") else f"/{part}/{policy_name}"
        )
    if name and not name.endswith("_ap"):
        ordered.append(f"/{part}/{name}_ap")
    unique: list[str] = []
    for path in ordered:
        if path and path not in unique:
            unique.append(path)
    return unique


def _tmsh_access_policy_missing(text: str) -> bool:
    compact = " ".join((text or "").lower().split())
    return "was not found" in compact or "not found" in compact


def _run_tmsh_macros(runner: Any, policy_path: str) -> str:
    """Names only, and only the first 8KB. A full policy render stalls mcpd and exits the GUI."""
    command = (
        f"tmsh -q list apm policy access-policy {policy_path} macros | head -c 8000"
    )
    try:
        return runner(command, timeout=8.0, max_bytes=8_192)
    except TypeError:
        return runner(command, timeout=8.0)


def _tmsh_list_policy_macros(
    client: ApmRestClient,
    profile: AccessProfileRef,
    progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Macro names only. REST GET of access-policy or /macros can dump the whole VPE."""
    runner = getattr(client, "run_util_bash", None)
    if not callable(runner):
        if progress is not None:
            progress("tmsh(util/bash)를 사용할 수 없습니다.")
        return []
    last_preview = ""
    if progress is not None:
        progress(f"대상 Access Policy Macro 목록 확인 중… ({profile.name})")
    for path in _policy_path_candidates(profile):
        try:
            text = _run_tmsh_macros(runner, path)
        except TimeoutError as exc:
            raise MacroApplyError(
                f"{profile.name} Macro 목록이 8초 안에 오지 않았습니다. "
                "앱은 종료하지 않습니다. 장비 tmsh가 응답한 뒤 다시 선택하세요."
            ) from exc
        except Exception as exc:  # noqa: BLE001 — listing must not kill the GUI
            low = str(exc).lower()
            if "timeout" in low or "timed out" in low:
                raise MacroApplyError(
                    f"{profile.name} Macro 목록이 8초 안에 오지 않았습니다. "
                    "앱은 종료하지 않습니다. 장비 tmsh가 응답한 뒤 다시 선택하세요."
                ) from exc
            last_preview = str(exc)[:180]
            continue
        if _tmsh_access_policy_missing(text):
            last_preview = " ".join((text or "").split())[:180]
            continue
        names = parse_tmsh_access_policy_macros(text, partition=profile.partition)
        if names:
            if progress is not None:
                progress(f"Macro 이름 {len(names)}개")
            return names
        last_preview = " ".join((text or "").split())[:180] or "(빈 응답)"
    if progress is not None and last_preview:
        progress("연결된 Macro가 없거나 Access Policy 경로를 확인하지 못했습니다.")
    return []


def load_access_policy(
    client: ApmRestClient,
    profile: AccessProfileRef,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Load macro names via tmsh. Never GET the access-policy REST object."""
    return {
        "name": profile.policy_name,
        "partition": profile.partition,
        "fullPath": profile.policy_path,
        "_macro_refs": _tmsh_list_policy_macros(client, profile, progress=progress),
    }


def probe_existing_items(
    client: ApmRestClient,
    *,
    partition: str,
    names: list[str],
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    total = len(unique)
    for index, name in enumerate(unique, start=1):
        if progress is not None:
            progress(f"기존 객체 확인 {index}/{total}  {name}")
        path = name if name.startswith("/") else f"/{partition}/{name}"
        body = _fetch_policy_item(client, path)
        if body is not None:
            found.append(body)
    return found


def load_policy_and_items(
    client: ApmRestClient,
    profile: AccessProfileRef,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = load_access_policy(client, profile)
    macro_paths = _macros_from_policy_field(policy)
    seeds = list(macro_paths)
    items = fetch_item_graph(
        client,
        seeds,
        progress=progress,
        skip_prefixes=[profile.policy_name, profile.name],
    )
    by_path = {item_full_path(i): i for i in items if item_full_path(i)}
    by_name = _items_by_name(items)
    for path in macro_paths:
        existing = _resolve_item(path, by_path, by_name)
        if existing is not None and is_macro_item(existing):
            continue
        fetched = _fetch_policy_item(client, path)
        if fetched is None:
            continue
        items.append(fetched)
        fetched_path = item_full_path(fetched)
        if fetched_path:
            by_path[fetched_path] = fetched
        if fetched.get("name"):
            by_name[str(fetched["name"])] = fetched
    return policy, items


def list_macros_for_profile(
    client: ApmRestClient,
    profile: AccessProfileRef,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[MacroSummary]]:
    """List attached macro names. Do not GET policy-items or walk the VPE graph."""
    if progress is not None:
        progress("tmsh로 Macro 이름 조회 중…")
    policy = load_access_policy(client, profile, progress=progress)
    macros = build_macro_summaries(policy=policy, items=[])
    return policy, [], macros


def _agent_get_path(agent_type: str, partition: str, name: str) -> str:
    return f"/tm/apm/policy/agent/{agent_type}/{rest_id(f'/{partition}/{name}')}"


def fetch_agents_for_items(
    client: ApmRestClient, items: list[dict[str, Any]]
) -> tuple[list[AgentRecord], list[str]]:
    records: list[AgentRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for item in items:
        partition = str(item.get("partition") or "Common")
        agents = item.get("agents") or []
        if not isinstance(agents, list):
            continue
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            parsed = parse_agent_ref(agent, partition)
            if parsed is None:
                continue
            agent_type, apart, aname = parsed
            key = f"{agent_type}:{apart}:{aname}"
            if key in seen:
                continue
            seen.add(key)
            if not agent_type:
                warnings.append(f"agent type 없음: /{apart}/{aname}")
                continue
            body = client.get_optional(_agent_get_path(agent_type, apart, aname))
            if body.get("_unavailable"):
                warnings.append(
                    f"agent 조회 실패 ({agent_type} /{apart}/{aname}): "
                    f"{body.get('_error', 'unavailable')}"
                )
                continue
            resolved_type = agent_type_from_body(body) or agent_type
            records.append(
                AgentRecord(
                    agent_type=resolved_type,
                    name=str(body.get("name") or aname),
                    partition=str(body.get("partition") or apart),
                    full_path=item_full_path(body) or f"/{apart}/{aname}",
                    body=body,
                )
            )
    return records, warnings


def build_snapshot(
    *,
    profile: AccessProfileRef,
    policy: dict[str, Any],
    items: list[dict[str, Any]],
    macro: MacroSummary,
    agents: list[AgentRecord],
    warnings: list[str],
    source_host: str = "",
    source_hostname: str = "",
) -> MacroSnapshot:
    by_path = {item_full_path(i): i for i in items if item_full_path(i)}
    paths = list(macro.item_paths)
    if macro.full_path and macro.full_path not in paths:
        paths.insert(0, macro.full_path)
    selected_items = [strip_rest_metadata(by_path[p]) for p in paths if p in by_path]
    if macro.full_path and not any(is_macro_item(item) for item in selected_items):
        _part, name = split_full_path(macro.full_path)
        selected_items.insert(
            0,
            synthesize_macro_container(
                name=name or macro.name,
                partition=_part or macro.partition or "Common",
                caption=macro.caption or name,
                items=selected_items,
            ),
        )
    agent_payloads = []
    created_paths = {item_full_path(i) for i in selected_items}
    for agent in agents:
        created_paths.add(agent.full_path)
        agent_payloads.append(
            {
                "type": agent.agent_type,
                "name": agent.name,
                "partition": agent.partition,
                "full_path": agent.full_path,
                "body": strip_rest_metadata(agent.body),
            }
        )
    refs = extract_external_refs(
        agents=agent_payloads,
        items=selected_items,
        created_paths=created_paths,
    )
    return MacroSnapshot(
        saved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_host=source_host,
        source_hostname=source_hostname,
        access_profile=profile.full_path,
        access_policy=profile.policy_path,
        policy_name=profile.policy_name,
        partition=profile.partition,
        macro_full_path=macro.full_path,
        macro_caption=macro.caption,
        items=selected_items,
        agents=agent_payloads,
        external_refs=refs,
        warnings=list(warnings),
    )


def _snapshot_from_tmsh_boxes(
    *,
    profile: AccessProfileRef,
    policy: dict[str, Any],
    macro: MacroSummary,
    boxes: dict[str, Any],
    source_host: str,
    source_hostname: str,
) -> MacroSnapshot:
    partition = macro.partition or profile.partition or "Common"
    container = {
        "name": macro.name,
        "partition": partition,
        "fullPath": macro.full_path,
        "caption": str(boxes.get("caption") or macro.caption or macro.name),
        "itemType": "macro",
        "startItem": (
            f"/{partition}/{boxes['start_item']}" if boxes.get("start_item") else ""
        ),
        "defaultEnding": (
            f"/{partition}/{boxes['default_ending']}" if boxes.get("default_ending") else ""
        ),
    }
    flow = list(boxes.get("items") or [])
    selected = [container, *flow]
    rich = MacroSummary(
        caption=str(container["caption"]),
        name=macro.name,
        partition=partition,
        full_path=macro.full_path,
        exits=macro.exits,
        agent_labels=tuple(
            str(ref.get("type") or "")
            for item in flow
            for ref in (item.get("agents") or [])
            if isinstance(ref, dict)
        ),
        item_count=len(selected),
        item_paths=tuple(item_full_path(item) for item in selected if item_full_path(item)),
    )
    records = [
        AgentRecord(
            agent_type=str(agent.get("type") or ""),
            name=str(agent.get("name") or ""),
            partition=str(agent.get("partition") or partition),
            full_path=str(agent.get("full_path") or ""),
            body=agent.get("body") if isinstance(agent.get("body"), dict) else {},
        )
        for agent in (boxes.get("agents") or [])
        if isinstance(agent, dict)
    ]
    return build_snapshot(
        profile=profile,
        policy=policy,
        items=selected,
        macro=rich,
        agents=records,
        warnings=[
            "서버, 커스터마이즈 그룹, 리소스, SMTP 이름은 저장하지 않습니다."
        ],
        source_host=source_host,
        source_hostname=source_hostname,
    )


def export_macro_snapshot(
    client: ApmRestClient,
    *,
    profile: AccessProfileRef,
    policy: dict[str, Any],
    items: list[dict[str, Any]],
    macro: MacroSummary,
    source_host: str = "",
    source_hostname: str = "",
    progress: Callable[[str], None] | None = None,
) -> MacroSnapshot:
    runner = getattr(client, "run_util_bash", None)
    if callable(runner) and macro.full_path:
        try:
            boxes = collect_macro_boxes(
                runner, macro.full_path, progress=progress
            )
        except TimeoutError as exc:
            raise MacroApplyError(
                "Macro 박스가 12초 안에 오지 않았습니다. "
                "앱은 종료하지 않습니다. 장비 tmsh가 응답한 뒤 다시 Save 하세요."
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise MacroApplyError(str(exc)[:240]) from exc
        return _snapshot_from_tmsh_boxes(
            profile=profile,
            policy=policy,
            macro=macro,
            boxes=boxes,
            source_host=source_host,
            source_hostname=source_hostname,
        )
    seeds: list[str] = []
    if macro.full_path:
        seeds.append(macro.full_path)
    for path in macro.item_paths:
        if path not in seeds:
            seeds.append(path)
    graph = fetch_item_graph(
        client,
        seeds,
        skip_prefixes=[profile.policy_name, profile.name],
    )
    by_path = {item_full_path(item): item for item in graph if item_full_path(item)}
    for item in items:
        path = item_full_path(item)
        if path and path not in by_path:
            graph.append(item)
            by_path[path] = item
    macro_item = by_path.get(macro.full_path)
    if macro_item is None and macro.full_path:
        fetched = _fetch_policy_item(client, macro.full_path)
        if fetched is not None:
            graph.append(fetched)
            by_path[item_full_path(fetched) or macro.full_path] = fetched
            macro_item = fetched
    if macro_item is not None:
        closure = collect_macro_item_paths(
            macro_item=macro_item, policy=policy, items=graph
        )
        rich = MacroSummary(
            caption=macro.caption,
            name=macro.name,
            partition=macro.partition,
            full_path=macro.full_path,
            exits=macro.exits or tuple(rule_captions(macro_item)),
            agent_labels=macro.agent_labels,
            item_count=max(len(closure), 1),
            item_paths=tuple(closure) if closure else (macro.full_path,),
        )
        selected = [by_path[p] for p in rich.item_paths if p in by_path]
    else:
        rich = macro
        selected = [by_path[p] for p in macro.item_paths if p in by_path]
    agents, warnings = fetch_agents_for_items(client, selected)
    return build_snapshot(
        profile=profile,
        policy=policy,
        items=graph,
        macro=rich,
        agents=agents,
        warnings=warnings,
        source_host=source_host,
        source_hostname=source_hostname,
    )


def _ref_entry(full_path: str, *, is_macro: bool = False) -> dict[str, Any]:
    partition, name = split_full_path(full_path)
    entry = {"name": name, "partition": partition, "priority": 0}
    return entry


def _normalize_policy_refs(raw: Any, default_partition: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if not path or path in seen:
            return
        seen.add(path)
        refs.append(_ref_entry(path))

    if isinstance(raw, dict):
        if raw.get("_unavailable"):
            return refs
        if raw.get("name"):
            add(item_full_path(raw))
            return refs
        raw = raw.get("items") or raw.get("Items") or []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, str):
                add(_normalize_ref(entry, default_partition))
            elif isinstance(entry, dict):
                add(item_full_path(entry))
    elif isinstance(raw, str) and raw.strip():
        add(_normalize_ref(raw, default_partition))
    return refs


def object_exists(client: ApmRestClient, path: str) -> bool:
    body = client.get_optional(path)
    return isinstance(body, dict) and not body.get("_unavailable")


def _clear_object_refs_dict(body: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in body.items():
        if key in _KEEP_TEXT_KEYS:
            cleaned[key] = value
            continue
        if key in _OBJECT_REF_KEYS:
            if isinstance(value, list):
                cleaned[key] = []
            continue
        if isinstance(value, dict):
            cleaned[key] = _clear_object_refs_dict(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _clear_object_refs_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def sanitize_agent_object_refs(agent_type: str, body: dict[str, Any]) -> dict[str, Any]:
    """Drop AAA/resource object selections on Load; keep Variable Assign text."""
    if (agent_type or "").strip().lower() in _KEEP_FULL_AGENT_TYPES:
        return body
    return _clear_object_refs_dict(body)


def snapshot_macro_name(snapshot: MacroSnapshot) -> str:
    _part, name = split_full_path(snapshot.macro_full_path)
    if name:
        return name
    return str(snapshot.macro_caption or "").strip()


def snapshot_display_name(snapshot: MacroSnapshot) -> str:
    """VPE caption (Auth_AD). CLI 객체 이름(auth_ad)보다 GUI 이름을 우선한다."""
    caption = str(snapshot.macro_caption or "").strip()
    if caption:
        return caption
    return snapshot_macro_name(snapshot)


def planned_macro_name(
    snapshot: MacroSnapshot,
    *,
    wanted_macro: str = "",
    remapped_items: list[dict[str, Any]] | None = None,
) -> str:
    wanted = (wanted_macro or "").strip()
    if wanted:
        return wanted
    for item in remapped_items or []:
        if is_macro_item(item) and item.get("name"):
            return str(item["name"])
    return snapshot_macro_name(snapshot)


def synthesize_macro_container(
    *,
    name: str,
    partition: str,
    caption: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a missing itemType=macro object from terminals already in the snapshot."""
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not _is_terminal_item(item):
            continue
        item_name = str(item.get("name") or "")
        if item_name == name or _is_nested_prefix_child(name, item_name):
            continue
        if item_name and not item_name.startswith(f"{name}_"):
            continue
        path = item_full_path(item)
        if not path or path in seen:
            continue
        seen.add(path)
        rules.append(
            {
                "caption": str(item.get("caption") or item_name or "out"),
                "nextItem": path,
            }
        )
    body: dict[str, Any] = {
        "name": name,
        "partition": partition,
        "caption": caption or name,
        "itemType": "macro",
    }
    if rules:
        body["rules"] = rules
    return body


def compact_policy_item_for_create(item: dict[str, Any]) -> dict[str, Any]:
    """Small create body. Full policy-item POST/PATCH can stall mcpd and kill the GUI."""
    name = str(item.get("name") or "")
    body: dict[str, Any] = {
        "name": name,
        "partition": str(item.get("partition") or "Common"),
        "caption": str(item.get("caption") or name),
        "itemType": str(item.get("itemType") or "macro"),
    }
    rules = item.get("rules")
    if isinstance(rules, list):
        compact: list[dict[str, str]] = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            compact.append(
                {
                    "caption": str(rule.get("caption") or "")[:80],
                    "nextItem": str(rule.get("nextItem") or ""),
                }
            )
            if len(compact) >= 12:
                break
        if compact:
            body["rules"] = compact
    return body


def _tmsh_quote(text: str) -> str:
    cleaned = (
        str(text or "")
        .replace("\\", "")
        .replace('"', "")
        .replace("'", "")
        .replace("{", "")
        .replace("}", "")
        .replace("\n", " ")
    )
    return cleaned[:80]


def _tmsh_create_policy_item(client: ApmRestClient, item: dict[str, Any]) -> str:
    runner = getattr(client, "run_util_bash", None)
    if not callable(runner):
        raise MacroApplyError("tmsh로 policy-item을 만들 수 없습니다.")
    compact = compact_policy_item_for_create(item)
    name = str(compact.get("name") or "")
    partition = str(compact.get("partition") or "Common")
    caption = _tmsh_quote(str(compact.get("caption") or name))
    item_type = str(compact.get("itemType") or "").replace("_", "-").lower()
    path = f"/{partition}/{name}"
    props = f"caption {caption}"
    # tmsh item-type is only action|ending|entry. REST "macro" is not a tmsh value.
    if item_type in {"action", "ending", "entry"}:
        props = f"{props} item-type {item_type}"
    command = f"tmsh -q create apm policy policy-item {path} {props}"
    try:
        text = runner(command, timeout=12.0, max_bytes=8192)
    except TypeError:
        text = runner(command, timeout=12.0)
    preview = str(text or "")
    low = preview.lower()
    if "already exists" in low or _already_exists_error(RuntimeError(preview)):
        return "exists"
    if preview.strip() and (
        low.startswith("error")
        or preview.startswith("0102")
        or "syntax error" in low
    ):
        raise RuntimeError(preview[:200])
    return "created"


def _post_policy_item(client: ApmRestClient, item: dict[str, Any]) -> str:
    payload = compact_policy_item_for_create(item)
    try:
        client.post(
            "/tm/apm/policy/policy-item",
            payload,
            timeout=12.0,
            max_bytes=8192,
        )
    except TypeError:
        client.post("/tm/apm/policy/policy-item", payload, timeout=12.0)
    return "posted"


def create_policy_item(
    client: ApmRestClient,
    item: dict[str, Any],
    progress: Callable[[str], None] | None = None,
) -> str:
    """Create via quiet tmsh. REST POST of policy-item can hang mcpd and exit the exe."""
    name = str(item.get("name") or "?")
    runner = getattr(client, "run_util_bash", None)
    if callable(runner):
        if progress is not None:
            progress(f"tmsh로 policy-item 생성  {name}")
        try:
            return _tmsh_create_policy_item(client, item)
        except Exception as exc:  # noqa: BLE001
            low = str(exc).lower()
            if "timeout" in low or "timed out" in low:
                raise MacroApplyError(
                    f"policy-item 생성 시간 초과 ({name}). 잠시 후 다시 Load 하세요."
                ) from exc
            raise MacroApplyError(f"policy-item 생성 실패 ({name}): {exc}") from exc
    if progress is not None:
        progress(f"policy-item 생성  {name}")
    try:
        return _post_policy_item(client, item)
    except Exception as exc:  # noqa: BLE001
        if _already_exists_error(exc):
            return "exists"
        raise MacroApplyError(f"policy-item 생성 실패 ({name}): {exc}") from exc


def build_apply_plan(
    *,
    snapshot: MacroSnapshot,
    target_profile: AccessProfileRef,
    existing_item_names: set[str],
    missing_external: list[str] | None = None,
    target_macro_name: str | None = None,
) -> ApplyPlan:
    if not snapshot.items:
        raise MacroApplyError("스냅샷에 policy-item이 없습니다.")
    source_policy = snapshot.policy_name
    source_partition = snapshot.partition or "Common"
    target_policy = target_profile.policy_name
    target_partition = target_profile.partition
    if not source_policy:
        raise MacroApplyError("스냅샷에 원본 Access Policy 이름이 없습니다.")
    wanted_macro = (target_macro_name or "").strip()
    source_macro = snapshot_macro_name(snapshot)

    def _remap_obj(value: Any) -> Any:
        remapped = value
        if wanted_macro and source_macro and wanted_macro != source_macro:
            remapped = remap_value(
                remapped,
                source_policy=source_macro,
                target_policy=wanted_macro,
                source_partition=source_partition,
                target_partition=target_partition,
            )
        return remap_value(
            remapped,
            source_policy=source_policy,
            target_policy=target_policy,
            source_partition=source_partition,
            target_partition=target_partition,
        )

    remapped_agents: list[tuple[str, dict[str, Any]]] = []
    for agent in snapshot.agents:
        agent_type = str(agent.get("type") or "")
        body = agent.get("body") if isinstance(agent.get("body"), dict) else {}
        cleaned = strip_rest_metadata(body)
        remapped = _remap_obj(cleaned)
        if not isinstance(remapped, dict):
            continue
        remapped["partition"] = target_partition
        remapped = sanitize_agent_object_refs(agent_type, remapped)
        remapped_agents.append((agent_type, remapped))

    remapped_items: list[dict[str, Any]] = []
    for item in snapshot.items:
        remapped = _remap_obj(strip_rest_metadata(item))
        if not isinstance(remapped, dict):
            continue
        remapped["partition"] = target_partition
        if wanted_macro and is_macro_item(remapped):
            remapped["caption"] = wanted_macro
            remapped["name"] = wanted_macro
            remapped.pop("fullPath", None)
        remapped_items.append(remapped)

    planned_names = [str(i.get("name") or "") for i in remapped_items if i.get("name")]
    colliding_names = [name for name in planned_names if name in existing_item_names]
    reuse_existing = bool(planned_names) and len(colliding_names) == len(planned_names)
    collisions = (
        []
        if reuse_existing
        else [f"/{target_partition}/{name}" for name in colliding_names]
    )

    item_refs = [_ref_entry(item_full_path(i)) for i in remapped_items]
    attach_name = planned_macro_name(
        snapshot, wanted_macro=wanted_macro, remapped_items=remapped_items
    )
    macro_refs: list[dict[str, Any]] = []
    for item in remapped_items:
        if is_macro_item(item):
            macro_refs.append(_ref_entry(item_full_path(item), is_macro=True))
    if attach_name:
        macro_refs = _merge_refs(
            macro_refs,
            [_ref_entry(f"/{target_partition}/{attach_name}", is_macro=True)],
        )
    if not macro_refs:
        raise MacroApplyError(
            "스냅샷에 연결할 Macro 이름이 없습니다. Macro 파일을 다시 저장하세요."
        )

    warnings = list(snapshot.warnings)
    warnings.append(
        "같은 이름 Macro가 있으면 목록에서 마지막 번호를 찾아 다음 번호로 만듭니다. "
        "원본 Access Profile의 Macro는 그대로 둡니다."
    )

    return ApplyPlan(
        target_profile=target_profile.full_path,
        target_policy=target_profile.policy_path,
        target_policy_name=target_policy,
        target_partition=target_partition,
        agents=remapped_agents,
        items=remapped_items,
        item_refs=item_refs,
        macro_refs=macro_refs,
        collisions=collisions,
        missing_external=list(missing_external or []),
        warnings=warnings,
        reuse_existing=reuse_existing,
    )


def _merge_refs(existing: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(existing)
    seen = {f"{r.get('partition')}/{r.get('name')}" for r in existing}
    for ref in extra:
        key = f"{ref.get('partition')}/{ref.get('name')}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    return merged


def _compact_ref(ref: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(ref.get("name") or ""),
        "partition": str(ref.get("partition") or "Common"),
    }


def _ref_key(ref: dict[str, Any]) -> str:
    return f"{ref.get('partition')}/{ref.get('name')}"


def fetch_policy_macro_refs(
    client: ApmRestClient,
    target_profile: AccessProfileRef,
    existing_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    refs = _normalize_policy_refs(existing_policy.get("macros"), target_profile.partition)
    extra = [_ref_entry(path) for path in _macros_from_policy_field(existing_policy)]
    refs = _merge_refs(refs, extra)
    if refs or "_macro_refs" in existing_policy:
        return refs
    tmsh_refs = [_ref_entry(path) for path in _tmsh_list_policy_macros(client, target_profile)]
    return _merge_refs(refs, tmsh_refs)


def _tmsh_add_policy_macros(
    client: ApmRestClient,
    target_profile: AccessProfileRef,
    names: list[str],
) -> None:
    runner = getattr(client, "run_util_bash", None)
    if not callable(runner):
        raise MacroApplyError("tmsh로 Macro를 연결할 수 없습니다.")
    joined = " ".join(names)
    last_error: Exception | None = None
    for path in _policy_path_candidates(target_profile):
        command = (
            f"tmsh -q modify apm policy access-policy {path} "
            f"macros add {{ {joined} }}"
        )
        try:
            try:
                text = runner(command, timeout=15.0, max_bytes=8192)
            except TypeError:
                text = runner(command, timeout=15.0)
            if _tmsh_access_policy_missing(str(text or "")):
                last_error = RuntimeError(f"Access Policy를 찾을 수 없습니다: {path}")
                continue
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    if last_error is not None:
        raise MacroApplyError(str(last_error)) from last_error
    raise MacroApplyError("tmsh로 Macro를 연결할 수 없습니다.")


def _increment_access_profile(client: ApmRestClient, profile: AccessProfileRef) -> bool:
    runner = getattr(client, "run_util_bash", None)
    if callable(runner):
        command = (
            f"tmsh -q modify apm profile access {profile.full_path} "
            "generation-action increment"
        )
        try:
            runner(command, timeout=20.0, max_bytes=8192)
        except TypeError:
            runner(command, timeout=20.0)
        return True
    try:
        client.patch(
            f"/tm/apm/profile/access/{rest_id(profile.full_path)}",
            {"generationAction": "increment"},
            timeout=20.0,
            max_bytes=8192,
        )
    except TypeError:
        client.patch(
            f"/tm/apm/profile/access/{rest_id(profile.full_path)}",
            {"generationAction": "increment"},
            timeout=20.0,
        )
    return True


def _rest_attach_path(profile: AccessProfileRef) -> str:
    """REST access-policy path from listing. Do not also POST a second _ap name."""
    rest_path = (profile.policy_path or "").strip()
    if rest_path:
        return rest_path
    part = profile.partition or "Common"
    name = (profile.name or "").strip()
    return f"/{part}/{name}" if name else ""


def _post_macro_ref(client: ApmRestClient, url: str, payload: dict[str, str]) -> None:
    """Real devices use curl in another process. Test doubles keep client.post."""
    helper = getattr(client, "post_via_curl", None)
    if callable(helper):
        helper(url, payload, timeout=5.0)
        return
    try:
        client.post(url, payload, timeout=4.0, max_bytes=2048, discard_body=True)
    except TypeError:
        try:
            client.post(url, payload, timeout=4.0, max_bytes=2048)
        except TypeError:
            client.post(url, payload, timeout=4.0)


def attach_macros_to_policy(
    client: ApmRestClient,
    *,
    target_profile: AccessProfileRef,
    macro_refs: list[dict[str, Any]],
    existing_macro_refs: list[dict[str, Any]],
    progress: Callable[[str], None] | None = None,
    display_name: str | None = None,
) -> str:
    """Add macro refs. Never PATCH the full access-policy object. Never retry extra paths."""
    existing_keys = {_ref_key(ref) for ref in existing_macro_refs}
    to_add = [ref for ref in macro_refs if _ref_key(ref) not in existing_keys and ref.get("name")]
    if not to_add:
        return "already"

    def _progress(message: str) -> None:
        if progress is not None:
            progress(message)

    path = _rest_attach_path(target_profile)
    if not path:
        raise MacroApplyError("Access Policy 경로가 없습니다.")
    rid = rest_id(path)
    url = f"/tm/apm/policy/access-policy/{rid}/macros"
    shown = (display_name or "").strip()
    try:
        for payload in (_compact_ref(ref) for ref in to_add):
            actual = payload["name"]
            if shown and shown != actual:
                _progress(f"Load Macro 연결 중… {shown} (객체 {actual}) → {path}")
            else:
                _progress(f"Load Macro 연결 중… {actual} → {path}")
            _post_macro_ref(client, url, payload)
    except MacroApplyError:
        raise
    except Exception as post_exc:  # noqa: BLE001
        raise MacroApplyError(
            f"Access Policy Macro 연결 실패: {str(post_exc)[:200]}"
        ) from post_exc
    if getattr(client, "post_via_curl", None):
        return "detached"
    return "posted"


_LIVE_ACCESS_POLICY_NAMES_CMD = (
    'tmsh -q list apm policy access-policy | grep "apm policy"'
)


def _run_tmsh(runner: Any, command: str, *, timeout: float = 12.0, max_bytes: int = 4096) -> str:
    try:
        return str(runner(command, timeout=timeout, max_bytes=max_bytes) or "")
    except TypeError:
        try:
            return str(runner(command, timeout=timeout) or "")
        except RuntimeError as exc:
            return str(exc)
    except RuntimeError as exc:
        return str(exc)


def _run_tmsh_capped(
    client: ApmRestClient,
    runner: Any,
    command: str,
    *,
    timeout: float,
    max_bytes: int = 4096,
) -> str:
    """Run tmsh with a timeout. Extra threads plus curl can exit the frozen GUI."""
    del client
    return _run_tmsh(runner, command, timeout=timeout, max_bytes=max_bytes)


_QUIT_PROMPT_RE = re.compile(
    r"batch mode transaction is active, it will be lost, quit anyway\?\s*\(y/n\)\s*",
    re.IGNORECASE,
)


def _without_transaction_noise(text: str) -> str:
    """Drop tmsh's per-command notice so the real submit result remains."""
    notice = "command added to the current transaction"
    kept: list[str] = []
    for line in (text or "").splitlines():
        cleaned = _QUIT_PROMPT_RE.sub("", line).strip()
        low = " ".join(cleaned.lower().split())
        if not low or low == notice or low == notice + ".":
            continue
        kept.append(cleaned)
    return "\n".join(kept).strip()


def _tmsh_error_excerpt(text: str, limit: int = 500) -> str:
    body = " ".join(_without_transaction_noise(text).split())
    if not body:
        return "장비 응답 없음"
    if len(body) <= limit:
        return body
    return body[-limit:]


def _tmsh_failed(text: str) -> bool:
    compact = " ".join((text or "").lower().split())
    if not compact:
        return False
    if "01071130" in compact or "nonexistent access policy item" in compact:
        return True
    if "0107" in compact or "transaction failed" in compact:
        return True
    if "already exists" in compact:
        return False
    return (
        compact.startswith("error")
        or compact.startswith("0102")
        or compact.startswith("0107")
        or "bash rejected" in compact
        or "syntax error" in compact
        or "was not found" in compact
        or "not found" in compact
        or "nonexistent access policy item" in compact
        or "interactive mode" in compact
        or "batch mode" in compact
    )


def _tmsh_create_or_ok(runner: Any, command: str, *, label: str) -> str:
    text = _run_tmsh(runner, command)
    if _tmsh_failed(text) and "already exists" not in (text or "").lower():
        raise MacroApplyError(f"{label}: {text[:200]}")
    return text


def _tmsh_attach_macro_name(
    runner: Any,
    target_profile: AccessProfileRef,
    name: str,
) -> tuple[str, str]:
    last_err = ""
    for path in _policy_path_candidates(target_profile):
        add_cmd = (
            f"tmsh -q modify apm policy access-policy {path} "
            f"macros add {{ {name} }}"
        )
        added = _run_tmsh(runner, add_cmd)
        if _tmsh_access_policy_missing(added):
            last_err = (added or last_err)[:180]
            continue
        if _tmsh_failed(added) and "already exists" not in (added or "").lower():
            last_err = (added or last_err)[:180]
            if "was not found" in (added or "").lower() or "not found" in (added or "").lower():
                return "", added or last_err
            continue
        return path, added
    return "", last_err


def parse_access_policy_object_names(text: str) -> list[str]:
    """Parse `apm policy access-policy /Common/auth_ad {` lines from tmsh/grep."""
    names: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"apm policy access-policy\s+(\S+)", text or "", re.I):
        token = match.group(1).rstrip("{").strip().strip(",")
        if not token:
            continue
        _part, name = split_full_path(token if "/" in token else f"/Common/{token}")
        bare = name or token.rsplit("/", 1)[-1]
        if not bare or bare in _TMSH_MACRO_NOISE:
            continue
        key = bare.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(bare)
    return names


def next_numbered_macro_name(wanted: str, existing_names: list[str]) -> str:
    """If auth_ad / auth_ad_1 / _2 / _3 exist, return auth_ad_4. Lookup max suffix first."""
    wanted_name = wanted.strip()
    if not wanted_name:
        return wanted_name
    numbered = _suffixes_for_macro_stem(wanted_name, existing_names)
    if not numbered:
        return wanted_name
    return f"{wanted_name}_{max(numbered) + 1}"


def _suffixes_for_macro_stem(stem: str, existing_names: list[str]) -> list[int]:
    stem_l = stem.strip().lower()
    found: list[int] = []
    if not stem_l:
        return found
    pattern = re.compile(re.escape(stem_l) + r"(?:_(\d+))?$")
    for raw in existing_names:
        name = (split_full_path(raw)[1] or raw).strip()
        match = pattern.fullmatch(name.lower())
        if not match:
            continue
        found.append(int(match.group(1)) if match.group(1) else 0)
    return found


def _macro_family_names(wanted: str, existing_names: list[str]) -> list[str]:
    stem_l = wanted.strip().lower()
    if not stem_l:
        return []
    pattern = re.compile(re.escape(stem_l) + r"(?:_(\d+))?$")
    found: list[str] = []
    for raw in existing_names:
        name = (split_full_path(raw)[1] or raw).strip()
        if name and pattern.fullmatch(name.lower()):
            found.append(name)
    return found


def _list_access_policy_names(
    client: ApmRestClient,
    progress: Callable[[str], None] | None = None,
    stem: str = "",
) -> list[str]:
    """Live name lookup via `tmsh list | grep`. Never read bigip.conf or the full policy collection.

    When *stem* is set (Load Macro), grep only that family. An empty result means the
    name is free. A full REST or conf dump stalls mcpd on this device.
    """

    def _progress(message: str) -> None:
        if progress is not None:
            progress(message)

    runner = getattr(client, "run_util_bash", None)
    if not callable(runner):
        return []

    merged: list[str] = []
    seen: set[str] = set()
    stem_l = (stem or "").strip().lower()

    def _add(names: list[str]) -> None:
        for name in names:
            key = name.lower()
            if not name or key in seen:
                continue
            if stem_l:
                # Keep stem and stem_N only (auth_ad, auth_ad_1, …).
                if key != stem_l and not key.startswith(stem_l + "_"):
                    continue
            seen.add(key)
            merged.append(name)

    if stem_l:
        # Escape for shell single quotes via existing helper if present.
        safe = stem_l.replace("'", "'\"'\"'")
        live_cmd = (
            'tmsh -q list apm policy access-policy | grep "apm policy" '
            f"| grep -i '{safe}'"
        )
        _progress(f'tmsh list … | grep "{stem}" (번호 Lookup)')
    else:
        live_cmd = _LIVE_ACCESS_POLICY_NAMES_CMD
        _progress('tmsh list apm policy access-policy | grep "apm policy"')

    live_text = _run_tmsh_capped(
        client,
        runner,
        live_cmd,
        timeout=20.0 if stem_l else 25.0,
        max_bytes=131072 if stem_l else 262144,
    )
    if _tmsh_failed(live_text):
        raise MacroApplyError(
            "tmsh list로 Access Policy 이름을 확인하지 못해 Macro를 만들지 않습니다. "
            f"{(live_text or '')[:160]}"
        )
    _add(parse_access_policy_object_names(live_text))
    _progress(
        f"Access Policy 이름 {len(merged)}개"
        + (f" ({stem} 계열)" if stem_l else " (장비 목록)")
    )
    # Empty stem grep means that name is free. Do not open bigip.conf.
    if stem_l or merged:
        return merged
    raise MacroApplyError(
        "tmsh list로 Access Policy 이름을 확인하지 못해 Macro를 만들지 않습니다. "
        '장비에서 tmsh list apm policy access-policy | grep "apm policy" 를 확인하세요.'
    )


# Item suffixes from earlier creates (_ent, _start, _end) are left on the device.
# A new shell uses a different pair so those leftovers are not created again.
_MACRO_SHELL_PAIRS: tuple[tuple[str, str], ...] = (("in", "out"), ("gate", "done"))


def _tmsh_name_token(name: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]", "", (name or "").strip())
    if not token or token != (name or "").strip():
        raise MacroApplyError(f"Macro 이름에 사용할 수 없는 문자가 있습니다: {name}")
    return token[:80]


def _tmsh_heredoc(script: str) -> str:
    # tmsh -c is batch mode and rejects cli transaction. Stdin is interactive mode.
    return f"tmsh <<ENDTMSH\n{script}\nENDTMSH"


def _tmsh_macro_transaction_command(
    *,
    part: str,
    actual: str,
    caption: str,
    target_profile: AccessProfileRef,
    in_suffix: str,
    out_suffix: str,
) -> str:
    """One interactive tmsh transaction.

    On this TMOS a Successful end is item-type terminal-out and has no agent.
    item-type terminal is rejected, and an ending item needs ending-allow,
    which cannot be created before the macro is attached. An entry needs
    exactly one rule, and that rule cannot point at itself or at another
    entry. macros add must use the full path or the macro is not referenced
    (01071930).
    """
    actual = _tmsh_name_token(actual)
    in_name = _tmsh_name_token(f"{actual}_{in_suffix}")
    out_name = _tmsh_name_token(f"{actual}_{out_suffix}")
    in_path = f"/{part}/{in_name}"
    out_path = f"/{part}/{out_name}"
    item_path = f"/{part}/{actual}"
    cap = _tmsh_quote(caption or actual)
    target = _policy_path_candidates(target_profile)[0]
    script = "\n".join(
        [
            "create cli transaction",
            (
                f"create apm policy policy-item {out_path} "
                f"{{ caption Successful color 1 item-type terminal-out }}"
            ),
            (
                f"create apm policy policy-item {in_path} "
                f"{{ caption Start color 1 item-type entry "
                f"rules {{ {{ caption fallback next-item {out_path} }} }} }}"
            ),
            (
                f"create apm policy access-policy {item_path} "
                f"{{ type macro caption {cap} default-ending {out_path} "
                f"start-item {in_path} items add {{ {in_name} {{ }} {out_name} {{ }} }} }}"
            ),
            f"modify apm policy access-policy {target} macros add {{ {item_path} }}",
            "submit cli transaction",
        ]
    )
    return _tmsh_heredoc(script)


def _already_exists_text(text: str) -> bool:
    return "already exists" in (text or "").lower()


def _exists_error_is_child_object(text: str) -> bool:
    low = (text or "").lower()
    return any(
        token in low
        for token in (
            "policy-item",
            "ending-allow",
            "agent",
            "_ent",
            "_start",
            "_end",
            "_in",
            "_out",
            "_gate",
            "_done",
        )
    )


def _access_policy_name_visible(client: ApmRestClient, runner: Any, name: str) -> bool:
    """Confirm the new name. This device lists `access-policy NAME {` without /Common/."""
    safe = _tmsh_name_token(name).replace('"', "").replace("'", "")
    command = (
        'tmsh -q list apm policy access-policy | grep "apm policy" '
        f"| grep -i -E 'access-policy (/[^ ]+/)?{safe}( |$)'"
    )
    text = _run_tmsh_capped(client, runner, command, timeout=8.0, max_bytes=4096)
    low = (text or "").lower()
    if "was not found" in low or "not found" in low:
        return False
    if _tmsh_failed(text):
        raise MacroApplyError(
            f"{name} 생성 여부를 확인하지 못했습니다. 성공으로 보지 않습니다. {(text or '')[:160]}"
        )
    return safe.lower() in low


def _tmsh_create_macro_on_profile(
    client: ApmRestClient,
    target_profile: AccessProfileRef,
    name: str,
    caption: str,
    progress: Callable[[str], None] | None = None,
    script_for: Callable[[str, str], str] | None = None,
    cleanup_for: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    """Create a new numbered copy. Never add an existing name to the target AP."""
    runner = getattr(client, "run_util_bash", None)
    if not callable(runner):
        raise MacroApplyError(
            "tmsh로 Macro를 만들 수 없습니다. policy-item REST 생성은 이 장비에서 mcpd가 멈춥니다."
        )
    part = target_profile.partition or "Common"
    existing = _list_access_policy_names(client, progress=progress, stem=name)
    used = list(existing)
    family = _macro_family_names(name, used)
    actual = next_numbered_macro_name(name, used)
    if progress is not None:
        if family:
            shown = family if len(family) <= 8 else [*family[:3], "…", *family[-3:]]
            progress(
                f"이름 Lookup: {', '.join(shown)} → 마지막 다음 {actual} 생성 (원본 유지)"
            )
        else:
            progress(f"이름 Lookup: {caption or name} 없음 → {actual} 생성")
    cap = _tmsh_quote(caption or name)
    created = ""
    pair_index = 0
    bumped = False
    target_path = _policy_path_candidates(target_profile)[0]

    def _discard(which: str, in_name: str, out_name: str) -> None:
        """A failed load must not leave a macro someone could use later."""
        if progress is not None:
            progress(f"{which} 생성을 실패로 보고, 방금 만든 객체는 지웁니다.")
        if cleanup_for is not None:
            command = cleanup_for(which)
        else:
            command = " ; ".join(
                [
                    (
                        f"tmsh modify apm policy access-policy {target_path} "
                        f"macros delete {{ /{part}/{which} }}"
                    ),
                    f"tmsh delete apm policy access-policy /{part}/{which}",
                    f"tmsh delete apm policy policy-item /{part}/{in_name}",
                    f"tmsh delete apm policy policy-item /{part}/{out_name}",
                ]
            )
        try:
            _run_tmsh_capped(client, runner, command, timeout=12.0, max_bytes=4096)
        except (TimeoutError, OSError, RuntimeError):
            if progress is not None:
                progress(f"{which} 삭제 확인이 끝나지 않았습니다. VPE에서 남았는지 보세요.")

    for _attempt in range(3):
        actual = _tmsh_name_token(next_numbered_macro_name(name, used))
        in_suffix, out_suffix = _MACRO_SHELL_PAIRS[min(pair_index, len(_MACRO_SHELL_PAIRS) - 1)]
        in_name = _tmsh_name_token(f"{actual}_{in_suffix}")
        out_name = _tmsh_name_token(f"{actual}_{out_suffix}")
        if script_for is not None:
            command = script_for(actual, cap)
            create_timeout = 20.0
            create_bytes = 16_384
        else:
            command = _tmsh_macro_transaction_command(
                part=part,
                actual=actual,
                caption=cap,
                target_profile=target_profile,
                in_suffix=in_suffix,
                out_suffix=out_suffix,
            )
            create_timeout = 15.0
            create_bytes = 8192
        if progress is not None:
            if script_for is not None:
                progress(f"Macro 생성 {actual} (저장된 박스, cli 트랜잭션 1회, 최대 20초)…")
            else:
                progress(f"Macro 생성 {actual} (cli 트랜잭션 1회, 최대 15초)…")
        try:
            created = _run_tmsh_capped(
                client,
                runner,
                command,
                timeout=create_timeout,
                max_bytes=create_bytes,
            )
        except TimeoutError as exc:
            _discard(actual, in_name, out_name)
            raise MacroApplyError(
                f"{actual} 생성이 {int(create_timeout)}초 안에 끝나지 않았습니다. "
                "만든 객체는 지우도록 했습니다. 원본 Macro는 변경하지 않았습니다. "
                f'장비에서 tmsh list apm policy access-policy | grep -i {actual} '
                "로 생겼는지 확인하세요. 목록에 없으면 생성되지 않은 것입니다."
            ) from exc
        if script_for is not None and _already_exists_text(created):
            if bumped:
                raise MacroApplyError(
                    f"{actual} 또는 그 안쪽 항목이 이미 있어 새 Macro를 만들지 못했습니다. "
                    f"{created[:180]}"
                )
            bumped = True
            used.append(actual)
            if progress is not None:
                progress(f"{actual} 이미 있음 → 다음 번호")
            continue
        if _already_exists_text(created) and _exists_error_is_child_object(created):
            pair_index += 1
            if pair_index >= len(_MACRO_SHELL_PAIRS):
                raise MacroApplyError(
                    f"잔여 객체 때문에 {actual}을 만들지 못했습니다 "
                    f"(_ent, _start, _in 등). {created[:180]}"
                )
            nxt_in, _nxt_out = _MACRO_SHELL_PAIRS[pair_index]
            if progress is not None:
                progress(f"잔여 항목이 있어 {actual} 항목 이름을 _{nxt_in} 로 바꿉니다.")
            continue
        if _already_exists_text(created):
            if bumped:
                raise MacroApplyError(
                    f"{actual} 이(가) 이미 있어 새 Macro를 만들지 못했습니다. {created[:180]}"
                )
            bumped = True
            used.append(actual)
            if progress is not None:
                progress(f"{actual} 이미 있음 → 다음 번호")
            continue
        outcome = _without_transaction_noise(created)
        if _tmsh_failed(outcome):
            excerpt = _tmsh_error_excerpt(created)
            if progress is not None:
                progress(f"생성 응답: {excerpt[:300]}")
            _discard(actual, in_name, out_name)
            raise MacroApplyError(
                f"Macro 객체 생성 실패 ({actual}). 만든 객체는 지웠습니다: {excerpt}"
            )
        break
    else:
        raise MacroApplyError(f"비어 있는 Macro 이름을 찾지 못했습니다 ({name}).")
    if progress is not None:
        reply = " ".join((created or "").split())
        progress(f"생성 응답: {reply[:160] or '빈 응답'}")
        progress(f"생성 확인: {actual} (객체 1개, 8초)")
    try:
        visible = _access_policy_name_visible(client, runner, actual)
    except (TimeoutError, OSError, RuntimeError) as exc:
        raise MacroApplyError(
            f"{actual} 생성 명령을 보냈지만 목록 확인이 끝나지 않았습니다. "
            "성공으로 보지 않습니다. VPE에서 직접 확인하세요."
        ) from exc
    if not visible:
        reply = _tmsh_error_excerpt(created)
        _discard(actual, in_name, out_name)
        raise MacroApplyError(
            f"{actual} 생성 명령은 보냈지만 장비에 새 Macro 객체가 남지 않았습니다. "
            "일부만 남은 매크로는 지웠습니다. 성공으로 보지 않습니다. "
            f"장비 응답: {reply}"
        )
    return "created+attached", actual


def apply_macro_snapshot(
    client: ApmRestClient,
    *,
    snapshot: MacroSnapshot,
    target_profile: AccessProfileRef,
    existing_policy: dict[str, Any],
    existing_items: list[dict[str, Any]],
    check_external: bool = False,
    target_macro_name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> ApplyResult:
    del existing_policy, existing_items, check_external

    def _progress(message: str) -> None:
        if progress is not None:
            progress(message)

    source_name = snapshot_macro_name(snapshot)
    if not source_name:
        raise MacroApplyError("스냅샷에 연결할 Macro 이름이 없습니다.")
    display_name = snapshot_display_name(snapshot)
    load_name = (target_macro_name or "").strip() or display_name or source_name
    flow = snapshot_flow_items(snapshot.items)
    _progress(f"기존 Macro: {display_name} (객체 {source_name})")
    script_for = None
    cleanup_for = None
    if flow:
        target_path = _policy_path_candidates(target_profile)[0]
        saved_items = list(snapshot.items)
        saved_agents = list(snapshot.agents)

        def script_for(actual: str, cap: str) -> str:
            return saved_macro_transaction(
                partition=target_profile.partition or "Common",
                actual=actual,
                caption=cap,
                target_policy_path=target_path,
                source_name=source_name,
                items=saved_items,
                agents=saved_agents,
                start_item="",
                default_ending="",
            )

        def cleanup_for(actual: str) -> str:
            return saved_macro_cleanup_command(
                partition=target_profile.partition or "Common",
                actual=actual,
                target_policy_path=target_path,
                source_name=source_name,
                items=saved_items,
                agents=saved_agents,
            )

        _progress(
            f"저장된 박스 {len(flow)}개로 새 Macro를 만듭니다. "
            "서버, 그룹, 리소스 이름은 넣지 않습니다."
        )
    else:
        _progress("새 Macro를 만듭니다. Start와 Successful Ending을 넣고, 원본은 바꾸지 않습니다.")
    _progress(f"Load Macro: {load_name}")
    _progress(f"Macro 생성 중… {load_name} → {target_profile.full_path}")
    try:
        mode, actual_name = _tmsh_create_macro_on_profile(
            client,
            target_profile,
            load_name,
            caption=load_name,
            progress=_progress,
            script_for=script_for,
            cleanup_for=cleanup_for,
        )
    except MacroApplyError:
        raise
    except Exception as exc:  # noqa: BLE001
        low = str(exc).lower()
        if isinstance(exc, TimeoutError) or "timeout" in low or "timed out" in low:
            raise MacroApplyError(
                f"Macro 생성 응답이 없습니다 ({load_name}). 성공으로 보지 않습니다. "
                "대상 Access Profile VPE에 새 Macro가 보이는지 확인하세요."
            ) from exc
        raise MacroApplyError(f"Macro 생성 실패 ({load_name}): {str(exc)[:200]}") from exc
    _progress(f"Macro {actual_name} 이(가) 장비 목록에 있습니다.")
    mode = f"{mode}; verified"
    suffix_note = (
        f"이름이 있어 {actual_name}으로 새로 만들었습니다. 원본 {load_name}은 변경하지 않습니다."
        if actual_name != load_name
        else f"Macro {actual_name}을(를) {target_profile.full_path}에 만들었습니다."
    )
    messages = [
        suffix_note,
        f"결과: {mode}",
        "대상 Access Profile VPE Macro 목록에서 확인하세요.",
    ]
    return ApplyResult(
        created_agents=[],
        created_items=[actual_name],
        skipped=[],
        applied_policy=True,
        generation_incremented=False,
        messages=messages + list(snapshot.warnings),
    )


def find_profile(refs: list[AccessProfileRef], full_path: str) -> AccessProfileRef | None:
    for ref in refs:
        if ref.full_path == full_path:
            return ref
    return None
