from __future__ import annotations
__doc__ = 'Parse APM access policies from TMSH bigip.conf text.'
import re
from typing import Any
SECRET_KEYS = {'password', 'secret', 'private-key', 'client-secret', 'key', 'shared-secret', 'community', 'passphrase'}
class ParseError(Exception):
    pass
def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens = []
    i = 0
    n = len(text)
    while (i < n):
        ch = text[i]
        if (ch in ' \t\r'):
            i = (i + 1)
            continue
        if (ch == '\n'):
            tokens.append(('NL', '\n'))
            i = (i + 1)
            continue
        if (ch == '#'):
            while (i < n) and (text[i] != '\n'):
                i = (i + 1)
                if not (i < n):
                    break
                if (text[i] != '\n'):
                    continue
            continue
        if (ch in '{}'):
            tokens.append((ch, ch))
            i = (i + 1)
            continue
        if (ch == '"') or (ch == '\\' and (i + 1) < n and text[(i + 1)] == '"'):
            escaped = ch == '\\'
            i = i + (2 if escaped else 1)
            buf = []
            while (i < n):
                c = text[i]
                if escaped and c == '\\' and (i + 1) < n and text[(i + 1)] == '"':
                    i = i + 2
                    break
                if (c == '\\') and ((i + 1) < n):
                    buf.append(text[(i + 1)])
                    i = i + 2
                    continue
                if (not escaped) and (c == '"'):
                    i = i + 1
                    break
                buf.append(c)
                i = i + 1
            tokens.append(('STR', ''.join(buf)))
            continue
        j = i
        while (j < n) and (text[j] not in ' \t\r\n{}#"'):
            j = (j + 1)
            if not (j < n):
                break
            if (text[j] not in ' \t\r\n{}#"'):
                continue
        tokens.append(('ID', text[i:j]))
        i = j
        if (i < n):
            continue
    return tokens
class _Reader:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = [(k, v) for (k, v) in tokens if (k != 'NL')]
        self.i = 0
        return
    def peek(self) -> tuple[str, str] | None:
        if (self.i >= len(self.tokens)):
            return
        return self.tokens[self.i]
    def get(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ParseError('unexpected end of config')
        self.i = (self.i + 1)
        return tok
    def skip_until_top_apm(self) -> bool:
        while (self.i < len(self.tokens)):
            tok = self.tokens[self.i]
            if (tok == ('ID', 'apm')):
                return True
            self.i = (self.i + 1)
            if (self.i < len(self.tokens)):
                continue
        return False
def _parse_braces(reader: _Reader) -> Any:
    kind, _ = reader.get()
    if kind != "{":
        raise ParseError("expected {")
    depth = 1
    j = reader.i
    nested = False
    while j < len(reader.tokens) and depth:
        k, _ = reader.tokens[j]
        if k == "{":
            depth += 1
            if depth > 1:
                nested = True
        elif k == "}":
            depth -= 1
        j += 1
    if not nested:
        values = []
        while True:
            tok = reader.peek()
            if tok is None:
                break
            if tok[0] == "}":
                reader.get()
                break
            _k, v = reader.get()
            values.append(v)
        if not values:
            return {}
        if (
            len(values) >= 2
            and len(values) % 2 == 0
            and not str(values[0]).startswith("/")
            and not all(_looks_like_object_name(v) for v in values)
        ):
            return {values[i]: values[i + 1] for i in range(0, len(values), 2)}
        if len(values) == 1:
            return values[0]
        return values
    obj = {}
    unnamed = []
    while True:
        tok = reader.peek()
        if tok is None:
            break
        if tok[0] == "}":
            reader.get()
            break
        if tok[0] == "{":
            unnamed.append(_parse_braces(reader))
            continue
        _k, key = reader.get()
        nxt = reader.peek()
        if nxt and nxt[0] == "{":
            obj[key] = _parse_braces(reader)
        elif nxt is None or nxt[0] == "}":
            obj[key] = True
        else:
            _nk, val = reader.get()
            obj[key] = val
    if unnamed and not obj:
        return unnamed
    if unnamed:
        obj["_items"] = unnamed
    return obj
def _parse_object_after_header(reader: _Reader) -> dict[str, Any]:
    nxt = reader.peek()
    if not nxt or nxt[0] != "{":
        return {}
    body = _parse_braces(reader)
    if isinstance(body, dict):
        return body
    return {"_value": body}
_TOP_LEVEL_PREFIXES = ('apm ', 'ltm ', 'sys ', 'net ', 'wom ', 'analytics ', 'auth ', 'cm ', 'ilx ', 'security ', 'pem ', 'gtm ', 'cli ', 'file ', 'asm ', 'afm ')
def _skip_quoted(text: str, i: int) -> int:
    n = len(text)
    i = (i + 1)
    while (i < n):
        c = text[i]
        if (c == '\\'):
            i = (i + 2)
            continue
        if (c == '"'):
            return (i + 1)
        i = (i + 1)
        if (i < n):
            continue
    return n
def _is_line_comment(text: str, i: int) -> bool:
    prev = (text[(i - 1)] if (i > 0) else '\n')
    return (prev in ' \t\r\n')
def _starts_top_level_object(text: str, i: int) -> bool:
    if (i != 0):
        if (text[(i - 1)] != '\n'):
            return False
    return any((text.startswith(prefix, i) for prefix in _TOP_LEVEL_PREFIXES))
def _skip_brace_block(text: str, i: int) -> int:
    n = len(text)
    depth = 0
    while (i < n):
        if (depth > 0):
            if _starts_top_level_object(text, i):
                return i
        c = text[i]
        # TMSH writes \" inside values. That quote does not open a string,
        # and treating it as one swallows every Access Policy after it.
        if c == '"' and not (i > 0 and text[i - 1] == '\\'):
            i = _skip_quoted(text, i)
            continue
        if (c == '#') and _is_line_comment(text, i):
            while (i < n) and (text[i] != '\n'):
                i = (i + 1)
                if not (i < n):
                    break
                if (text[i] != '\n'):
                    continue
            continue
        if (c == '{') and (i > 0) and (text[(i - 1)] == '%'):
            while (i < n) and (text[i] != '}'):
                i = (i + 1)
                if not (i < n):
                    break
                if (text[i] != '}'):
                    continue
            if (i < n):
                i = (i + 1)
            continue
        if (c == '{'):
            depth = (depth + 1)
        else:
            if (c == '}'):
                depth = (depth - 1)
                i = (i + 1)
                if (depth == 0):
                    return i
                continue
        i = (i + 1)
        if (i < n):
            continue
    return n
def _body_is_needed(header: str) -> bool:
    """Only objects the viewer draws. Customization groups hold HTML and CSS."""
    return header.startswith(
        (
            "apm policy access-policy ",
            "apm policy policy-item ",
            "apm policy agent ",
            "apm profile access ",
            "apm aaa ",
            "apm sso ",
            "apm resource ",
            "ltm virtual ",
        )
    )
def _iter_top_level_objects(text: str):
    n = len(text)
    i = 0
    while i < n:
        if i != 0 and text[i - 1] not in "\n":
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if not text.startswith("apm ", i) and not text.startswith("ltm ", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        brace = text.find("{", i)
        newline = text.find("\n", i)
        if brace == -1 or (newline != -1 and newline < brace):
            i = newline + 1 if newline != -1 else n
            continue
        end = _skip_brace_block(text, brace)
        header = text[i:brace].strip()
        if header.startswith("ltm rule "):
            yield (header, None, brace, end)
        elif _body_is_needed(header):
            yield (header, text[brace:end], brace, end)
        i = end
def _parse_body_text(body: str) -> dict[str, Any]:
    reader = _Reader(_tokenize(body))
    return _parse_object_after_header(reader)
def parse_tmsh_apm_objects(text: str) -> dict[str, list[dict[str, Any]]]:
    access_policies = []
    policy_items = []
    agents = []
    profiles = []
    extra_objects = []
    virtuals = []
    rule_spans = {}
    for (header, body, brace, end) in _iter_top_level_objects(text):
        parts = header.split()
        if header.startswith('ltm rule ') and (len(parts) >= 3):
            rule_spans[parts[2]] = (brace, end)
            continue
        if body is None:
            continue
        try:
            parsed = _parse_body_text(body)
        except ParseError:
            continue
        if header.startswith('apm policy access-policy ') and (len(parts) >= 4):
            parsed['name'] = parts[3]
            access_policies.append(parsed)
            continue
        if header.startswith('apm policy policy-item ') and (len(parts) >= 4):
            parsed['name'] = parts[3]
            policy_items.append(parsed)
            continue
        if header.startswith('apm policy agent ') and (len(parts) >= 5):
            parsed['name'] = parts[4]
            parsed['agent_kind'] = parts[3]
            agents.append(parsed)
            continue
        if header.startswith('apm profile access ') and (len(parts) >= 4):
            parsed['name'] = parts[3]
            profiles.append(parsed)
            continue
        if header.startswith('ltm virtual ') and (len(parts) >= 3):
            parsed['name'] = parts[2]
            virtuals.append(parsed)
            continue
        if not (len(parts) >= 4):
            continue
        if not (parts[0] == 'apm'):
            continue
        if not (parts[1] in frozenset({'aaa', 'sso', 'resource'})):
            continue
        parsed['name'] = parts[-1]
        parsed['object_kind'] = ' '.join(parts[1:-1])
        extra_objects.append(parsed)
    return {'access_policies': _dedupe_named(access_policies), 'policy_items': _dedupe_named(policy_items), 'agents': _dedupe_named(agents), 'profiles': _dedupe_named(profiles), 'objects': _dedupe_named(extra_objects), 'virtuals': _dedupe_named(virtuals), 'rule_spans': rule_spans}
def _dedupe_named(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {}
    for item in items:
        name = item.get('name')
        if name and not (name not in seen):
            pass
            continue
        if not (name):
            continue
        seen[name] = item
    if seen:
        return list(seen.values())
    return items
def _path_refs(obj: Any, objects: dict[str, Any], seen: set[str] | None=None) -> list[dict[str, Any]]:
    if seen is None:
        seen = set()
    found = []
    if isinstance(obj, dict):
        for (key, value) in obj.items():
            if (key in frozenset({'object_kind', 'agent_kind', 'name'})):
                found.extend(_path_refs(value, objects, seen))
                continue
            if isinstance(value, str) and value.startswith('/') and (value in objects) and (value not in seen):
                seen.add(value)
                found.append({'key': key, 'name': value, 'object': objects[value]})
                continue
            found.extend(_path_refs(value, objects, seen))
        return found
    if isinstance(obj, list):
        for item in obj:
            found.extend(_path_refs(item, objects, seen))
    return found
def _last_segment(value: str) -> str:
    return str((value or '')).rsplit('/', 1)[-1]
def _looks_like_object_name(value: str) -> bool:
    text = str(value or '').strip()
    if not text or text.lower() in {'true', 'false', 'enable', 'disable', 'none', 'any'}:
        return False
    if text.startswith('/'):
        return True
    return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', text) and ('_' in text or text[:1].isupper()))
def _same_tmsh_name(left: str, right: str) -> bool:
    a = str((left or ''))
    b = str((right or ''))
    return bool((a and (b and ((a == b) or (_last_segment(a) == _last_segment(b))))))
def _block_names(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        if not (raw.startswith('/')):
            if raw:
                pass
        return [raw]
    if isinstance(raw, list):
        out = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
                continue
            if not (isinstance(item, dict)):
                continue
            out.extend(_block_names(item))
        return out
    if isinstance(raw, dict):
        out = []
        for (key, value) in raw.items():
            if str(key).startswith('_'):
                continue
            out.append(str(key))
            if not (isinstance(value, str)):
                continue
            if not (_looks_like_object_name(value)):
                continue
            out.append(value)
        return out
    return []
def _active_tcl_source(source: str) -> str:
    lines = []
    for line in str((source or '')).splitlines():
        if line.lstrip().startswith('#'):
            continue
        lines.append(line)
    return '\n'.join(lines)
_AGENT_ID_EQ_RE = re.compile('agent_id\\s*\\]\\s+(?:eq|ne|equals|==|!=)\\s+(?:\\"([^\\"]+)\\"|([A-Za-z0-9_.-]+)|\\{([^}]+)\\})')
_AGENT_ID_ACCESS_RE = re.compile('ACCESS::policy\\s+agent_id\\s+([A-Za-z0-9_.-]+)')
_AGENT_ID_EVENT_RE = re.compile('AGENT::event\\s+([A-Za-z0-9_.-]+)')
def _agent_ids_in_rule(source: str) -> set[str]:
    active = _active_tcl_source(source)
    ids = set()
    for match in _AGENT_ID_EQ_RE.finditer(active):
        value = next((group for group in match.groups() if (group)), '')
        if not (value):
            continue
        ids.add(value)
    for match in _AGENT_ID_ACCESS_RE.finditer(active):
        ids.add(match.group(1))
    for match in _AGENT_ID_EVENT_RE.finditer(active):
        ids.add(match.group(1))
    return ids
def _rule_has_agent_id(source: str, agent_id: str) -> bool:
    want = str((agent_id or '')).strip()
    return (bool(want) and (want in _agent_ids_in_rule(source)))
def _index_ltm_rules(objects: dict[str, Any]) -> dict[str, Any]:
    by_id: dict[str, list[str]] = {}
    by_short: dict[str, str] = {}
    rule_count = 0
    for obj in objects.values():
        if not isinstance(obj, dict) or obj.get('object_kind') != 'ltm rule':
            continue
        name = str(obj.get('name') or '')
        if not name:
            continue
        rule_count += 1
        by_short.setdefault(_last_segment(name), name)
        for agent_id in _agent_ids_in_rule(str(obj.get('source') or '')):
            names = by_id.setdefault(agent_id, [])
            if name not in names:
                names.append(name)
    return {'by_id': by_id, 'by_short': by_short, 'rule_count': rule_count}
def _profiles_for_policy(policy_name: str, profiles: list[dict[str, Any]]) -> list[str]:
    names = []
    for profile in profiles:
        ap = profile.get('access_policy') or profile.get('access-policy')
        if _same_tmsh_name(profile.get('name') or '', policy_name) or _same_tmsh_name(ap or '', policy_name):
            names.append(profile['name'])
    return names
def _profile_name_set(profile_names: list[str]) -> set[str]:
    wanted = {_last_segment(n) for n in profile_names if n}
    wanted.update((n for n in profile_names if (n)))
    return wanted
def _virtuals_using_profiles(profile_names: list[str], virtuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = _profile_name_set(profile_names)
    if not (wanted):
        return []
    matched = []
    for vs in virtuals:
        vs_profiles = (vs.get('profiles') or [])
        if not (any((((_last_segment(p) in wanted) or (p in wanted)) for p in vs_profiles))):
            continue
        matched.append(vs)
    return matched
def _virtual_rules_for_profiles(profile_names: list[str], virtuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_rule = {}
    for vs in _virtuals_using_profiles(profile_names, virtuals):
        vs_name = str((vs.get('name') or ''))
        for rule in (vs.get('rules') or []):
            names = by_rule.setdefault(rule, [])
            if not (vs_name):
                continue
            if not (vs_name not in names):
                continue
            names.append(vs_name)
    return [{'name': name, 'virtuals': vs_names} for (name, vs_names) in by_rule.items()]
def _macro_users(policies: list[dict[str, Any]], items: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    users = {}
    for pol in policies:
        owner = str((pol.get('name') or ''))
        if not (owner):
            continue
        for macro in (pol.get('macros') or []):
            if not (isinstance(macro, str)):
                continue
            if not (macro):
                continue
            users.setdefault(macro, set()).add(owner)
        for item_name in (pol.get('items') or []):
            item = (items.get(item_name) or {})
            macro = item.get('macro')
            if not (isinstance(macro, str)):
                continue
            if not (macro):
                continue
            users.setdefault(macro, set()).add(owner)
    return users
def _owning_access_policies(policy_name: str, policies: list[dict[str, Any]], users: dict[str, set[str]]) -> list[str]:
    by_name = {p['name']: p for p in policies}
    current = by_name.get(policy_name)
    if current and current.get('type') != 'macro':
        return [policy_name]
    starts: list[str] = []
    seen: set[str] = set()
    stack = list(users.get(policy_name, ()))
    while stack:
        name = stack.pop()
        if not name or name in seen:
            continue
        seen.add(name)
        pol = by_name.get(name)
        if not pol:
            continue
        if pol.get('type') != 'macro':
            starts.append(name)
        else:
            stack.extend(users.get(name, ()))
    return starts
def _rule_source_from_span(text: str, span: tuple[int, int]) -> str:
    raw = text[span[0]:span[1]].strip()
    if raw.startswith('{'):
        if raw.endswith('}'):
            raw = raw[1:-1].strip()
    return raw
def _materialize_named_rules(text: str, spans: dict[str, tuple[int, int]], wanted: set[str] | None) -> list[dict[str, Any]]:
    if not (spans):
        return []
    if wanted is None:
        names = list(spans)
    else:
        by_short = {_last_segment(name): name for name in spans}
        names = []
        seen = set()
        for want in wanted:
            name = (want if (want in spans) else by_short.get(_last_segment(want)))
            if not (name):
                continue
            if not (name not in seen):
                continue
            seen.add(name)
            names.append(name)
    out = []
    for name in names:
        span = spans.get(name)
        if not (span):
            continue
        out.append({'name': name, 'object_kind': 'ltm rule', 'source': _rule_source_from_span(text, span)})
    return out
def _resolve_rule_object(name: str, objects: dict[str, Any], rule_index: dict[str, Any] | None) -> dict[str, Any] | None:
    obj = objects.get(name)
    if isinstance(obj, dict):
        if (obj.get('object_kind') == 'ltm rule'):
            return obj
    short = _last_segment(name)
    mapped = (rule_index or {}).get('by_short', {}).get(short)
    if mapped:
        obj = objects.get(mapped)
        if isinstance(obj, dict):
            if (obj.get('object_kind') == 'ltm rule'):
                return obj
    for current in objects.values():
        if not (isinstance(current, dict)):
            continue
        if not (current.get('object_kind') == 'ltm rule'):
            continue
        if not (_same_tmsh_name((current.get('name') or ''), name)):
            continue
        return current
    return
def _match_ltm_rules(agent_id: str, objects: dict[str, Any], allowed_rules: list[dict[str, Any]] | None=None, fallback: bool=True, rule_index: dict[str, Any] | None=None) -> list[dict[str, Any]]:
    want = str(agent_id or '').strip()
    if not want:
        return []
    index = rule_index or _index_ltm_rules(objects)

    def pack(name: str, virtuals: list[str] | None=None) -> dict[str, Any] | None:
        obj = _resolve_rule_object(name, objects, index)
        if obj is None or not _rule_has_agent_id(str(obj.get('source') or ''), want):
            return None
        item = dict(obj)
        if virtuals:
            item['virtuals'] = virtuals
        return item

    if allowed_rules is not None:
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in allowed_rules:
            name = str(item.get('name') or '')
            packed = pack(name, list(item.get('virtuals') or []))
            if packed is None:
                continue
            key = str(packed.get('name') or name)
            if key in seen:
                continue
            seen.add(key)
            found.append(packed)
        if found or not fallback:
            return found
    found = []
    seen = set()
    for name in index.get('by_id', {}).get(want) or []:
        packed = pack(name)
        if packed is None:
            continue
        key = str(packed.get('name') or name)
        if key in seen:
            continue
        seen.add(key)
        found.append(packed)
    return found
def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for (k, v) in obj.items():
            if (str(k).lower() in SECRET_KEYS):
                out[k] = '***'
                continue
            out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj
def _normalize_rules(raw: Any) -> list[dict[str, Any]]:
    rules = []
    if not (raw):
        return rules
    entries = (raw if isinstance(raw, list) else raw.get('_items', ([raw] if raw else [])))
    if isinstance(raw, dict):
        if ('_items' not in raw):
            if ('caption' in raw):
                entries = [raw]
    for entry in entries:
        if not (isinstance(entry, dict)):
            continue
        rules.append({'caption': (entry.get('caption') or 'fallback'), 'expression': entry.get('expression'), 'next_item': entry.get('next-item')})
    return rules
def _normalize_agents(raw: Any) -> list[dict[str, str]]:
    out = []
    if not (isinstance(raw, dict)):
        return out
    for (name, body) in raw.items():
        if name.startswith('_'):
            continue
        agent_type = None
        if isinstance(body, dict):
            agent_type = body.get('type')
        out.append({'name': name, 'type': (agent_type or '')})
    return out
def _item_kind(item: dict[str, Any]) -> str:
    item_type = item.get('item_type') or item.get('item-type') or ''
    caption = (item.get('caption') or '').lower()
    agents = item.get('agents') or []
    agent_types = [a.get('type') for a in agents if isinstance(a, dict)]
    if (
        item_type == 'ending'
        or 'ending-allow' in agent_types
        or 'ending-deny' in agent_types
        or 'ending-redirect' in agent_types
    ):
        if 'ending-allow' in agent_types or caption == 'allow':
            return 'ending-allow'
        if 'ending-deny' in agent_types or caption == 'deny':
            return 'ending-deny'
        if 'ending-redirect' in agent_types or caption == 'redirect':
            return 'ending-redirect'
        return 'ending'
    if item_type == 'macro-call' or item.get('macro'):
        return 'macro'
    if item_type == 'terminal-out':
        return 'terminal'
    if item_type == 'action' or agent_types:
        if 'decision-box' in agent_types:
            return 'decision'
        if 'logon-page' in agent_types:
            return 'logon'
        return 'action'
    if caption == 'start':
        return 'start'
    if caption == 'in':
        return 'entry'
    if not agents and item.get('rules'):
        return 'start'
    return item_type or 'node'
def _policies_on_virtuals(profiles: list[dict[str, Any]], virtuals: list[dict[str, Any]], policies: list[dict[str, Any]]) -> list[str]:
    names = []
    seen = set()
    for profile in profiles:
        attached = _virtuals_using_profiles([str((profile.get('name') or '')), str((profile.get('access_policy') or ''))], virtuals)
        if not (attached):
            continue
        policy_name = str((profile.get('access_policy') or (profile.get('name') or '')))
        if not (policy_name):
            continue
        if not (policy_name not in seen):
            continue
        seen.add(policy_name)
        names.append(policy_name)
    if names:
        return names
    return [str(pol['name']) for pol in policies if (pol.get('type') != 'macro') and pol.get('name')]
def _needed_policy_names(start_names: list[str], policies: list[dict[str, Any]], items: dict[str, dict[str, Any]]) -> set[str]:
    by_name = {pol['name']: pol for pol in policies if pol.get('name')}
    needed: set[str] = set()
    stack = list(start_names)
    while stack:
        name = stack.pop()
        if not name or name in needed:
            continue
        needed.add(name)
        pol = by_name.get(name)
        if not pol:
            continue
        for macro in pol.get('macros') or []:
            if isinstance(macro, str):
                stack.append(macro)
        for item_name in pol.get('items') or []:
            item = items.get(item_name) or {}
            macro = item.get('macro')
            if isinstance(macro, str) and macro:
                stack.append(macro)
    return needed
def _build_one_graph(pol: dict[str, Any], items: dict[str, dict[str, Any]], agents: dict[str, Any], objects: dict[str, Any], profiles: list[dict[str, Any]], virtuals: list[dict[str, Any]], policies: list[dict[str, Any]], macro_users: dict[str, set[str]], rule_index: dict[str, Any] | None=None) -> dict[str, Any]:
    nodes = []
    edges = []
    owners = _owning_access_policies(pol['name'], policies, macro_users)
    profile_names = []
    for owner in (owners or [pol['name']]):
        profile_names.extend(_profiles_for_policy(owner, profiles))
    bound_virtuals = _virtuals_using_profiles(profile_names, virtuals)
    for item_name in (pol.get('items') or []):
        item = items.get(item_name)
        if not (item):
            nodes.append({'id': item_name, 'caption': item_name.split('/')[-1], 'kind': 'missing', 'color': 1})
            continue
        node = {'id': item['name'], 'caption': item['caption'], 'kind': item['kind'], 'color': item['color'], 'item_type': item['item_type'], 'macro': item.get('macro'), 'agents': item['agents']}
        agent_details = []
        for ag in item['agents']:
            detail = agents.get(ag['name'])
            if not (detail):
                continue
            agent_details.append(detail)
        node['agent_details'] = agent_details
        node['irules'] = []
        node['references'] = []
        nodes.append(node)
        for rule in item['rules']:
            if not (rule.get('next_item')):
                continue
            edges.append({'from': item['name'], 'to': rule['next_item'], 'caption': rule['caption'], 'expression': rule.get('expression')})
    nodes = _drop_unused_terminals(nodes, edges, pol.get('start_item'))[0]
    edges = _drop_unused_terminals(nodes, edges, pol.get('start_item'))[1]
    return {'name': pol['name'], 'caption': pol['caption'], 'type': pol['type'], 'start_item': pol['start_item'], 'default_ending': pol['default_ending'], 'macros': pol['macros'], 'items': (pol.get('items') or []), 'owners': owners, 'virtuals': [{'name': vs.get('name'), 'destination': vs.get('destination'), 'rules': (vs.get('rules') or [])} for vs in bound_virtuals], 'nodes': nodes, 'edges': edges}
def _policy_stub_graph(pol: dict[str, Any], policies: list[dict[str, Any]], profiles: list[dict[str, Any]], virtuals: list[dict[str, Any]], macro_users: dict[str, set[str]]) -> dict[str, Any]:
    owners = _owning_access_policies(pol['name'], policies, macro_users)
    profile_names = []
    for owner in (owners or [pol['name']]):
        profile_names.extend(_profiles_for_policy(owner, profiles))
    bound_virtuals = _virtuals_using_profiles(profile_names, virtuals)
    return {'name': pol['name'], 'caption': pol['caption'], 'type': pol['type'], 'start_item': pol['start_item'], 'default_ending': pol['default_ending'], 'macros': pol['macros'], 'items': (pol.get('items') or []), 'owners': owners, 'virtuals': [{'name': vs.get('name'), 'destination': vs.get('destination'), 'rules': (vs.get('rules') or [])} for vs in bound_virtuals]}
def materialize_policy_graph(model: dict[str, Any], name: str) -> dict[str, Any] | None:
    policies = (model.get('policies') or [])
    target = next((pol for pol in policies if (pol.get('name') == name)), None)
    if target is None:
        last = str((name or '')).rsplit('/', 1)[-1]
        target = next((pol for pol in policies if (str((pol.get('name') or '')).endswith(('/' + last)))), None)
    if target is None:
        return
    if target.get('nodes') is not None:
        return target
    items = (model.get('_items') or {})
    agents = (model.get('_agents') or {})
    objects = (model.get('objects') or {})
    profiles = (model.get('profiles') or [])
    virtuals = (model.get('virtuals') or [])
    built = _build_one_graph(target, items, agents, objects, profiles, virtuals, policies, _macro_users(policies, items))
    target.update(built)
    return target
def _drop_unused_terminals(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], start_item: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Hide terminal boxes that no branch in the policy actually reaches."""
    incoming = {edge['to'] for edge in edges}
    keep_ids = {
        node['id']
        for node in nodes
        if node['id'] == start_item
        or node.get('kind') in {'start', 'entry'}
        or node.get('kind') != 'terminal'
        or node['id'] in incoming
    }
    nodes = [node for node in nodes if node['id'] in keep_ids]
    edges = [edge for edge in edges if edge['from'] in keep_ids and edge['to'] in keep_ids]
    return (nodes, edges)
def parse_apm_config(text: str) -> dict[str, Any]:
    raw = parse_tmsh_apm_objects(text)
    items = {}
    for item in raw['policy_items']:
        name = item['name']
        agents = _normalize_agents(item.get('agents'))
        normalized = {'name': name, 'caption': (item.get('caption') or name.split('/')[-1]), 'color': (int(item['color']) if str(item.get('color', '')).isdigit() else 1), 'item_type': (item.get('item-type') or ''), 'macro': item.get('macro'), 'agents': agents, 'rules': _normalize_rules(item.get('rules'))}
        normalized['kind'] = _item_kind(normalized)
        items[name] = normalized
    agents = {a['name']: _redact(a) for a in raw['agents']}
    objects = {o['name']: _redact(o) for o in (raw.get('objects') or [])}
    virtuals = []
    for vs in (raw.get('virtuals') or []):
        virtuals.append({'name': vs.get('name'), 'destination': vs.get('destination'), 'profiles': _block_names(vs.get('profiles')), 'rules': _block_names(vs.get('rules'))})
    policies = []
    for pol in raw['access_policies']:
        item_map = (pol.get('items') or {})
        item_names = ([k for k in item_map.keys() if not (k.startswith('_'))] if isinstance(item_map, dict) else _as_list(item_map))
        macros = _as_list(pol.get('macros'))
        policies.append({'name': pol['name'], 'caption': (pol.get('caption') or pol['name'].split('/')[-1]), 'type': (pol.get('type') or 'access-policy'), 'start_item': pol.get('start-item'), 'default_ending': pol.get('default-ending'), 'items': item_names, 'macros': macros})
    profiles = []
    for prof in raw['profiles']:
        profiles.append({'name': prof['name'], 'access_policy': prof.get('access-policy'), 'type': prof.get('type'), 'default_language': prof.get('default-language'), 'inactivity_timeout': prof.get('inactivity-timeout')})
    policy_by_name = {p['name']: p for p in policies}
    macro_users = _macro_users(policies, items)
    vs_starts = _policies_on_virtuals(profiles, virtuals, policies)
    _collected = set()
    for vs in virtuals:
        for name in (vs.get('rules') or []):
            _collected.add(name)
    wanted_rules = _collected
    for rule in _materialize_named_rules(text, (raw.get('rule_spans') or {}), (None if not (virtuals) else wanted_rules)):
        objects[rule['name']] = _redact(rule)
    graphs = []
    for pol in policies:
        graphs.append(_build_one_graph(pol, items, agents, objects, profiles, virtuals, policies, macro_users))
    for prof in profiles:
        prof['virtuals'] = [{'name': vs.get('name'), 'destination': vs.get('destination'), 'rules': (vs.get('rules') or [])} for vs in _virtuals_using_profiles([(prof.get('name') or ''), (prof.get('access_policy') or '')], virtuals)]
    if vs_starts:
        return {'summary': {'profiles': len(profiles), 'policies': len(policies), 'macros': sum((1 for p in policies if (p['type'] == 'macro'))), 'items': len(items), 'agents': len(agents)}, 'profiles': profiles, 'policies': graphs, 'objects': objects, 'virtuals': virtuals, 'policy_index': {name: i for (i, name) in enumerate(policy_by_name)}, '_items': items, '_agents': agents, 'preferred_policy': vs_starts[0]}
    return {'summary': {'profiles': len(profiles), 'policies': len(policies), 'macros': sum((1 for p in policies if (p['type'] == 'macro'))), 'items': len(items), 'agents': len(agents)}, 'profiles': profiles, 'policies': graphs, 'objects': objects, 'virtuals': virtuals, 'policy_index': {name: i for (i, name) in enumerate(policy_by_name)}, '_items': items, '_agents': agents, 'preferred_policy': None}
