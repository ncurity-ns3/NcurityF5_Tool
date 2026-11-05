"""Read a macro's boxes with small tmsh lists, and create them without bound objects.

Save keeps the graph (Logon Page, AD Auth, endings, expressions, query text).
Names of objects that must already exist — AAA server, customization group,
webtop, resource, SMTP — are left out. Load creates those properties as none.
A logon page cannot be created with an empty customization group on this TMOS,
so Load creates a new group that belongs to the new macro only.
"""

from __future__ import annotations

import re
from typing import Any, Callable

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BLOCK_PROP_KEYS = frozenset(
    {
        "priority",
        "type",
        "caption",
        "color",
        "expression",
        "next-item",
        "item-type",
        "start-item",
        "default-ending",
        "items",
        "agents",
        "rules",
        "query-filter",
        "query-attrname",
        "server",
        "customization-group",
        "smtp-config",
    }
)
_SPLIT = "---NCURITY---"

# tmsh property names whose value is an already-created device object.
_REF_NORM = frozenset(
    {
        "server",
        "servers",
        "customizationgroup",
        "aaaserver",
        "httpserver",
        "smtpconfig",
        "smtpserver",
        "pool",
        "pools",
        "webtop",
        "webtops",
        "webtoplink",
        "webtopsection",
        "ssoconfig",
        "ssoconfiguration",
        "acl",
        "acls",
        "networkaccess",
        "portalaccess",
        "apptunnel",
        "remotedesktop",
        "saml",
        "oauth",
        "cabundle",
        "sslprofile",
        "leasepool",
        "ipv4leasepool",
        "ipv6leasepool",
        "resource",
        "resources",
        "radiusserver",
        "domaincontroller",
        "ocsp",
        "crl",
        "activedirectory",
        "ldap",
        "directory",
    }
)

_AAA_AGENT_TYPES = frozenset(
    {
        "aaa-active-directory",
        "aaa-ldap",
        "aaa-radius",
        "aaa-securid",
        "aaa-http",
        "aaa-ocsp",
        "aaa-crldp",
        "aaa-kerberos",
        "aaa-sam",
        "aaa-tacacsplus",
    }
)

# These agents reject an empty customization group (01071199). The new group
# is created with the new macro and is not the source macro's group.
_PRIVATE_CG = {
    "logon-page": "logon",
    "message-box": "message-box",
    "decision-box": "decision-box",
}

_SMTP_AGENT_TYPES = frozenset({"email", "smtp"})


def _norm_key(key: str) -> str:
    return re.sub(r"[-_]", "", str(key or "")).lower()


def is_object_ref_key(key: str) -> bool:
    return _norm_key(key) in _REF_NORM


def strip_object_refs(value: Any) -> Any:
    """Drop bound object names. Keep captions, expressions, and query text."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if is_object_ref_key(str(key)):
                continue
            cleaned[str(key)] = strip_object_refs(item)
        return cleaned
    if isinstance(value, list):
        return [strip_object_refs(item) for item in value]
    return value


def _tmsh_tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#":
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        if ch == '"':
            i += 1
            buf: list[str] = []
            while i < length:
                if text[i] == "\\" and i + 1 < length:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                buf.append(text[i])
                i += 1
            tokens.append(("str", "".join(buf)))
            continue
        if ch in "{}":
            tokens.append(("brace", ch))
            i += 1
            continue
        start = i
        while i < length and not text[i].isspace() and text[i] not in "{}":
            i += 1
        tokens.append(("word", text[start:i]))
    return tokens


def _parse_block(tokens: list[tuple[str, str]], index: int) -> tuple[Any, int]:
    items: list[Any] = []
    while index < len(tokens) and tokens[index] != ("brace", "}"):
        if tokens[index] == ("brace", "{"):
            block, index = _parse_block(tokens, index + 1)
            items.append(block)
            continue
        key = tokens[index][1]
        index += 1
        if index >= len(tokens) or tokens[index] == ("brace", "}"):
            items.append(key)
            break
        if tokens[index] == ("brace", "{"):
            value, index = _parse_block(tokens, index + 1)
        else:
            value = tokens[index][1]
            index += 1
        items.append((key, value))
    if index < len(tokens) and tokens[index] == ("brace", "}"):
        index += 1
    if items and all(isinstance(item, tuple) for item in items):
        merged: dict[str, Any] = {}
        for key, value in items:
            if key in merged:
                prev = merged[key]
                if not isinstance(prev, list):
                    merged[key] = [prev]
                merged[key].append(value)
            else:
                merged[key] = value
        # `{ cn sAMAccountName }` is a word list. `{ caption fallback }` is properties.
        if all(isinstance(value, str) for value in merged.values()) and not any(
            str(key) in _BLOCK_PROP_KEYS for key in merged
        ):
            flat: list[str] = []
            for key, value in items:
                flat.append(str(key))
                flat.append(str(value))
            return flat, index
        return merged, index
    if items and all(isinstance(item, str) for item in items):
        return items, index
    if items and all(isinstance(item, dict) for item in items):
        return items, index
    return items, index


def parse_tmsh_object(text: str) -> dict[str, Any] | None:
    """Parse one `tmsh list` object. Returns kind, name, agent_type, and body."""
    tokens = _tmsh_tokenize(text or "")
    brace = next((i for i, token in enumerate(tokens) if token == ("brace", "{")), -1)
    if brace < 0:
        return None
    words = [token[1] for token in tokens[:brace] if token[0] in {"word", "str"}]
    if len(words) < 4 or words[0] != "apm" or words[1] != "policy":
        return None
    body, _index = _parse_block(tokens, brace + 1)
    if not isinstance(body, dict):
        body = {}
    kind = words[2]
    if kind == "agent" and len(words) >= 5:
        return {
            "kind": "agent",
            "agent_type": words[3],
            "name": words[4],
            "body": body,
        }
    return {"kind": kind, "name": words[-1], "agent_type": "", "body": body}


def _short_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rstrip("/").split("/")[-1]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_rule_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _safe_name(name: str) -> str:
    token = str(name or "").strip()
    if not token or not _NAME_RE.fullmatch(token):
        raise ValueError(f"이름에 사용할 수 없는 문자가 있습니다: {name}")
    return token[:80]


def rename_macro_name(name: str, source: str, actual: str) -> str:
    short = _short_name(name)
    if not short:
        return ""
    if short == source:
        return actual
    prefix = f"{source}_"
    if source and short.startswith(prefix):
        return f"{actual}{short[len(source):]}"
    return short


def _item_type_from_body(body: dict[str, Any], *, is_start: bool) -> str:
    raw = str(body.get("item-type") or body.get("itemType") or "").replace("_", "-").lower()
    if raw == "terminal":
        return "terminal-out"
    if raw in {"terminal-out", "entry", "action"}:
        return raw
    if is_start:
        return "entry"
    if body.get("agents"):
        return "action"
    return "action"


def _agents_from_body(body: dict[str, Any], partition: str) -> list[dict[str, str]]:
    raw = body.get("agents")
    if not isinstance(raw, dict):
        return []
    found: list[dict[str, str]] = []
    for name, spec in raw.items():
        spec_body = spec if isinstance(spec, dict) else {}
        agent_type = str(spec_body.get("type") or "").strip()
        if not name or not agent_type:
            continue
        found.append(
            {
                "name": str(name),
                "type": agent_type,
                "partition": partition,
            }
        )
    return found


def _rules_from_body(body: dict[str, Any], partition: str) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []
    for rule in _as_rule_list(body.get("rules")):
        nxt = _short_name(str(rule.get("next-item") or rule.get("nextItem") or ""))
        rules.append(
            {
                "caption": str(rule.get("caption") or "fallback"),
                "expression": str(rule.get("expression") or ""),
                "nextItem": f"/{partition}/{nxt}" if nxt else "",
            }
        )
    return rules


def policy_item_record(parsed: dict[str, Any], *, partition: str, is_start: bool) -> dict[str, Any]:
    body = _as_dict(parsed.get("body"))
    name = str(parsed.get("name") or "")
    color = body.get("color") or 1
    return {
        "name": name,
        "partition": partition,
        "fullPath": f"/{partition}/{name}",
        "caption": str(body.get("caption") or name),
        "color": color,
        "itemType": _item_type_from_body(body, is_start=is_start),
        "agents": _agents_from_body(body, partition),
        "rules": _rules_from_body(body, partition),
    }


def agent_record(parsed: dict[str, Any], *, partition: str) -> dict[str, Any]:
    name = str(parsed.get("name") or "")
    agent_type = str(parsed.get("agent_type") or "")
    body = strip_object_refs(_as_dict(parsed.get("body")))
    return {
        "type": agent_type,
        "name": name,
        "partition": partition,
        "full_path": f"/{partition}/{name}",
        "body": body,
    }


def _run(runner: Any, command: str, *, timeout: float, max_bytes: int) -> str:
    try:
        return str(runner(command, timeout=timeout, max_bytes=max_bytes) or "")
    except TypeError:
        return str(runner(command, timeout=timeout) or "")


def _failed(text: str) -> bool:
    compact = " ".join((text or "").lower().split())
    if not compact:
        return False
    return (
        "syntax error" in compact
        or "was not found" in compact
        or compact.startswith("0102")
        or compact.startswith("0107")
        or "timed out" in compact
        or "timeout" in compact
    )


def collect_macro_boxes(
    runner: Any,
    macro_path: str,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """List one macro's items and agents. Does not list the parent Access Policy."""
    partition, macro_name = "Common", ""
    text = str(macro_path or "").strip()
    if text.startswith("/"):
        parts = [part for part in text.split("/") if part]
        if len(parts) >= 2:
            partition, macro_name = parts[0], parts[-1]
        elif parts:
            macro_name = parts[-1]
    else:
        macro_name = text
    macro_name = _safe_name(macro_name)
    policy_path = f"/{partition}/{macro_name}"

    def _progress(message: str) -> None:
        if progress is not None:
            progress(message)

    _progress(f"Macro 박스 읽는 중… ({macro_name})")
    header = _run(
        runner,
        (
            "tmsh -q list apm policy access-policy "
            f"{policy_path} start-item default-ending type caption items"
        ),
        timeout=8.0,
        max_bytes=16_384,
    )
    if _failed(header):
        raise RuntimeError(
            f"{macro_name} 박스 목록을 읽지 못했습니다. {(header or '')[:180]}"
        )
    parsed = parse_tmsh_object(header)
    if parsed is None:
        raise RuntimeError(f"{macro_name} Macro 구성을 읽지 못했습니다.")
    body = _as_dict(parsed.get("body"))
    if str(body.get("type") or "").lower() not in {"", "macro"}:
        raise RuntimeError(
            f"{macro_name} 은(는) Macro가 아니라서 안쪽 박스를 저장하지 않습니다."
        )
    items_raw = body.get("items")
    item_names: list[str] = []
    if isinstance(items_raw, dict):
        item_names = [str(name) for name in items_raw if str(name).strip()]
    if len(item_names) > 40:
        raise RuntimeError(
            f"{macro_name} 박스가 {len(item_names)}개라 한 번에 저장하지 않습니다."
        )
    start = _short_name(str(body.get("start-item") or ""))
    default_ending = _short_name(str(body.get("default-ending") or ""))
    caption = str(body.get("caption") or macro_name)
    if not item_names:
        return {
            "items": [],
            "agents": [],
            "start_item": "",
            "default_ending": "",
            "caption": caption,
        }

    _progress(f"Policy Item {len(item_names)}개 읽는 중…")
    item_cmd = " ; ".join(
        f"echo {_SPLIT}; tmsh -q list apm policy policy-item {_safe_name(name)}"
        for name in item_names
    )
    item_text = _run(runner, item_cmd, timeout=12.0, max_bytes=65_536)
    items: list[dict[str, Any]] = []
    agent_refs: list[dict[str, str]] = []
    for chunk in item_text.split(_SPLIT):
        obj = parse_tmsh_object(chunk)
        if obj is None or obj.get("kind") != "policy-item":
            continue
        record = policy_item_record(
            obj,
            partition=partition,
            is_start=_short_name(str(obj.get("name") or "")) == start,
        )
        items.append(record)
        agent_refs.extend(record["agents"])
    if not items:
        raise RuntimeError(f"{macro_name} 안쪽 박스를 읽지 못했습니다. {(item_text or '')[:180]}")

    agents: list[dict[str, Any]] = []
    if agent_refs:
        _progress(f"Agent {len(agent_refs)}개 읽는 중…")
        agent_cmd = " ; ".join(
            "echo "
            + _SPLIT
            + "; tmsh -q list apm policy agent "
            + _safe_name(ref["type"])
            + " "
            + _safe_name(ref["name"])
            for ref in agent_refs
        )
        agent_text = _run(runner, agent_cmd, timeout=12.0, max_bytes=65_536)
        for chunk in agent_text.split(_SPLIT):
            obj = parse_tmsh_object(chunk)
            if obj is None or obj.get("kind") != "agent":
                continue
            agents.append(agent_record(obj, partition=partition))
    return {
        "items": items,
        "agents": agents,
        "start_item": start,
        "default_ending": default_ending,
        "caption": caption,
    }


def snapshot_flow_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flow: list[dict[str, Any]] = []
    for item in items:
        raw = str(item.get("itemType") or item.get("item-type") or "").lower()
        if raw == "macro":
            continue
        if raw in {"entry", "action", "terminal-out", "terminal"} or item.get("rules") or item.get("agents"):
            flow.append(item)
    return flow


def _macro_container(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if str(item.get("itemType") or "").lower() == "macro":
            return item
    return None


def _quote_word(text: str) -> str:
    cleaned = (
        str(text or "")
        .replace("\\", "")
        .replace('"', "")
        .replace("'", "")
        .replace("\n", " ")
        .strip()
    )
    if not cleaned:
        return '""'
    if _NAME_RE.fullmatch(cleaned):
        return cleaned
    return f'"{cleaned[:80]}"'


def _quote_expr(text: str) -> str:
    cleaned = str(text or "").replace('"', "").replace("\n", " ").strip()
    return f'"{cleaned}"'


def _ordered_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = list(items)
    ordered: list[dict[str, Any]] = []
    names = {_short_name(str(item.get("name") or "")) for item in items}

    def _nexts(item: dict[str, Any]) -> list[str]:
        found: list[str] = []
        for rule in item.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            nxt = _short_name(str(rule.get("nextItem") or rule.get("next-item") or ""))
            if nxt in names:
                found.append(nxt)
        return found

    for _guard in range(len(pending) + 1):
        if not pending:
            break
        placed = {
            _short_name(str(item.get("name") or "")) for item in ordered
        }
        moved = [
            item
            for item in pending
            if all(nxt in placed for nxt in _nexts(item))
        ]
        if not moved:
            ordered.extend(pending)
            break
        for item in moved:
            ordered.append(item)
            pending.remove(item)
    return ordered


def _agent_lines(
    *,
    partition: str,
    source: str,
    actual: str,
    item_agents: list[dict[str, Any]],
    saved_agents: list[dict[str, Any]],
) -> list[str]:
    by_name = {_short_name(str(agent.get("name") or "")): agent for agent in saved_agents}
    lines: list[str] = []
    seen: set[str] = set()
    for ref in item_agents:
        source_name = _short_name(str(ref.get("name") or ""))
        agent_type = str(ref.get("type") or ref.get("agentType") or "").strip()
        if not source_name or not agent_type or source_name in seen:
            continue
        seen.add(source_name)
        new_name = _safe_name(rename_macro_name(source_name, source, actual))
        saved = by_name.get(source_name) or {}
        body = strip_object_refs(saved.get("body") if isinstance(saved.get("body"), dict) else {})
        if not agent_type:
            agent_type = str(saved.get("type") or "")
        agent_type = _safe_name(agent_type)
        props: list[str] = []
        if agent_type in _PRIVATE_CG:
            cg_name = _safe_name(f"{new_name}_cg")
            cg_type = _PRIVATE_CG[agent_type]
            lines.append(
                "create apm policy customization-group "
                f"/{partition}/{cg_name} type {cg_type} source modern"
            )
            props.append(f"customization-group /{partition}/{cg_name}")
        if agent_type in _AAA_AGENT_TYPES:
            props.append("server none")
        if agent_type in _SMTP_AGENT_TYPES:
            props.append("smtp-config none")
        agent_kind = str(body.get("type") or "")
        if agent_kind and _NAME_RE.fullmatch(agent_kind):
            props.append(f"type {agent_kind}")
        query_filter = str(body.get("query-filter") or body.get("queryFilter") or "")
        if query_filter:
            props.append(f"query-filter {_quote_expr(query_filter)}")
        attrs = body.get("query-attrname") or body.get("queryAttrname") or []
        if isinstance(attrs, list) and attrs:
            words = [str(attr) for attr in attrs if _NAME_RE.fullmatch(str(attr))]
            if words:
                props.append("query-attrname add { " + " ".join(words) + " }")
        rules = _as_rule_list(body.get("rules"))
        if rules:
            rendered = []
            for rule in rules:
                bits: list[str] = []
                if rule.get("caption"):
                    bits.append(f"caption {_quote_word(str(rule.get('caption')))}")
                expr = str(rule.get("expression") or "")
                if expr:
                    bits.append(f"expression {_quote_expr(expr)}")
                if bits:
                    rendered.append("{ " + " ".join(bits) + " }")
            if rendered:
                props.append("rules { " + " ".join(rendered) + " }")
        lines.append(
            f"create apm policy agent {agent_type} /{partition}/{new_name} "
            f"{{ {' '.join(props)} }}"
        )
    return lines


def _item_line(
    item: dict[str, Any],
    *,
    partition: str,
    source: str,
    actual: str,
) -> str:
    source_name = _short_name(str(item.get("name") or ""))
    new_name = _safe_name(rename_macro_name(source_name, source, actual))
    item_type = str(item.get("itemType") or "action").replace("_", "-").lower()
    if item_type == "terminal":
        item_type = "terminal-out"
    caption = _quote_word(str(item.get("caption") or new_name))
    color = str(item.get("color") or "1")
    if not color.isdigit():
        color = "1"
    props = [f"caption {caption}", f"color {color}", f"item-type {item_type}"]
    if item_type == "action":
        bits: list[str] = []
        for ref in item.get("agents") or []:
            if not isinstance(ref, dict):
                continue
            agent_name = _safe_name(
                rename_macro_name(str(ref.get("name") or ""), source, actual)
            )
            agent_type = _safe_name(str(ref.get("type") or ref.get("agentType") or ""))
            bits.append(f"{agent_name} {{ type {agent_type} }}")
        if bits:
            props.append("agents add { " + " ".join(bits) + " }")
    if item_type != "terminal-out":
        rendered: list[str] = []
        for rule in item.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            nxt = rename_macro_name(
                str(rule.get("nextItem") or rule.get("next-item") or ""),
                source,
                actual,
            )
            if not nxt:
                continue
            bits = [f"caption {_quote_word(str(rule.get('caption') or 'fallback'))}"]
            expr = str(rule.get("expression") or "")
            if expr:
                bits.append(f"expression {_quote_expr(expr)}")
            bits.append(f"next-item /{partition}/{_safe_name(nxt)}")
            rendered.append("{ " + " ".join(bits) + " }")
        if rendered:
            props.append("rules { " + " ".join(rendered) + " }")
    return (
        f"create apm policy policy-item /{partition}/{new_name} "
        f"{{ {' '.join(props)} }}"
    )


def _owned_by_new_macro(name: str, actual: str) -> bool:
    """Only objects created for this load. Never the source macro's boxes."""
    short = _short_name(name)
    return short == actual or short.startswith(f"{actual}_")


def saved_macro_cleanup_command(
    *,
    partition: str,
    actual: str,
    target_policy_path: str,
    source_name: str,
    items: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> str:
    """Delete only the macro this load just tried to create."""
    actual = _safe_name(actual)
    source = _short_name(source_name)
    target = target_policy_path.strip() or f"/{partition}/{actual}"
    lines = [
        f"tmsh modify apm policy access-policy {target} macros delete {{ /{partition}/{actual} }}",
        f"tmsh delete apm policy access-policy /{partition}/{actual}",
    ]
    flow = snapshot_flow_items(items)
    item_agents: list[dict[str, Any]] = []
    for item in flow:
        new_item = rename_macro_name(str(item.get("name") or ""), source, actual)
        if _owned_by_new_macro(new_item, actual):
            lines.append(
                f"tmsh delete apm policy policy-item /{partition}/{_safe_name(new_item)}"
            )
        for ref in item.get("agents") or []:
            if isinstance(ref, dict):
                item_agents.append(ref)
    seen: set[str] = set()
    for ref in item_agents:
        source_agent = _short_name(str(ref.get("name") or ""))
        if not source_agent or source_agent in seen:
            continue
        seen.add(source_agent)
        new_agent = rename_macro_name(source_agent, source, actual)
        if not _owned_by_new_macro(new_agent, actual):
            continue
        agent_type = str(ref.get("type") or ref.get("agentType") or "").strip()
        if not agent_type:
            continue
        agent_type = _safe_name(agent_type)
        new_agent = _safe_name(new_agent)
        lines.append(
            f"tmsh delete apm policy agent {agent_type} /{partition}/{new_agent}"
        )
        if agent_type in _PRIVATE_CG:
            lines.append(
                "tmsh delete apm policy customization-group "
                f"/{partition}/{_safe_name(new_agent + '_cg')}"
            )
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        new_agent = rename_macro_name(str(agent.get("name") or ""), source, actual)
        agent_type = str(agent.get("type") or "").strip()
        if not agent_type or not _owned_by_new_macro(new_agent, actual):
            continue
        agent_type = _safe_name(agent_type)
        new_agent = _safe_name(new_agent)
        line = f"tmsh delete apm policy agent {agent_type} /{partition}/{new_agent}"
        if line not in lines:
            lines.append(line)
    return " ; ".join(lines)


def saved_macro_transaction(
    *,
    partition: str,
    actual: str,
    caption: str,
    target_policy_path: str,
    source_name: str,
    items: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    start_item: str,
    default_ending: str,
) -> str:
    """One interactive tmsh transaction for the saved boxes."""
    actual = _safe_name(actual)
    source = _short_name(source_name)
    flow = snapshot_flow_items(items)
    container = _macro_container(items)
    if not start_item and container is not None:
        start_item = _short_name(str(container.get("startItem") or ""))
    if not default_ending and container is not None:
        default_ending = _short_name(str(container.get("defaultEnding") or ""))
    item_agents: list[dict[str, Any]] = []
    for item in flow:
        for ref in item.get("agents") or []:
            if isinstance(ref, dict):
                item_agents.append(ref)
    lines = ["create cli transaction"]
    lines.extend(
        _agent_lines(
            partition=partition,
            source=source,
            actual=actual,
            item_agents=item_agents,
            saved_agents=agents,
        )
    )
    ordered = _ordered_items(flow)
    for item in ordered:
        lines.append(
            _item_line(item, partition=partition, source=source, actual=actual)
        )
    start_name = _safe_name(rename_macro_name(start_item, source, actual))
    end_name = _safe_name(rename_macro_name(default_ending, source, actual))
    item_add = " ".join(
        f"{_safe_name(rename_macro_name(str(item.get('name') or ''), source, actual))} {{ }}"
        for item in ordered
    )
    cap = _quote_word(caption or actual)
    lines.append(
        f"create apm policy access-policy /{partition}/{actual} "
        f"{{ type macro caption {cap} default-ending /{partition}/{end_name} "
        f"start-item /{partition}/{start_name} items add {{ {item_add} }} }}"
    )
    target = target_policy_path.strip() or f"/{partition}/{actual}"
    lines.append(
        f"modify apm policy access-policy {target} macros add {{ /{partition}/{actual} }}"
    )
    lines.append("submit cli transaction")
    return "tmsh <<ENDTMSH\n" + "\n".join(lines) + "\nENDTMSH"
