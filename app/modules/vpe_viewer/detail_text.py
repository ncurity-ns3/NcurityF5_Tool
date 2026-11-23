"""Plain-text fields and iRule code cards for the VPE detail pane."""

from __future__ import annotations

import html
from typing import Any

_LABELS = {
    "agent_kind": "에이전트 종류",
    "object_kind": "객체 종류",
    "auth-type": "인증 방식",
    "form-method": "폼 방식",
    "form-action": "폼 주소",
    "content-type": "Content Type",
    "custom-body": "Custom Body",
    "headers": "Headers",
    "value": "값",
    "name": "이름",
    "follow-redirect": "리다이렉트 횟수",
    "timeout": "연결 시간 제한",
    "request-timeout": "요청 시간 제한",
    "start-uri": "시작 URI",
    "form-username": "사용자 필드",
    "form-password": "비밀번호 필드",
    "success-match-type": "성공 판정",
    "success-match-value": "성공 값",
    "domain": "도메인",
    "admin-name": "관리자 이름",
    "admin-password": "관리자 비밀번호",
    "server": "서버",
    "retries": "재시도",
    "secret": "시크릿",
    "nas-ip-address": "NAS IP",
    "service-type": "서비스 타입",
    "max-logon-attempt": "최대 로그온 시도",
    "id": "이벤트",
    "type": "종류",
    "macro": "매크로",
}

_SKIP = frozenset({"name", "_items", "_value", "source"})
_BLOCK_KEYS = frozenset({"custom-body", "headers", "form-action"})
_CODE_KEYS = frozenset({"custom-body"})


def field_label(key: str) -> str:
    return _LABELS.get(key, str(key).replace("-", " "))


def format_fields(obj: Any, *, skip_kind: bool = False, indent: int = 4) -> list[str]:
    """Flatten a tmsh object. Nested blocks stay indented under their label."""
    skip = set(_SKIP)
    if skip_kind:
        skip.add("object_kind")
    return _lines(obj, skip, indent)


def reference_lines(ref: dict[str, Any]) -> list[str]:
    obj = ref.get("object") if isinstance(ref.get("object"), dict) else {}
    name = str(ref.get("name") or obj.get("name") or "")
    title = name.rsplit("/", 1)[-1] or name
    kind = str(obj.get("object_kind") or "")
    head = f"- {title}"
    if kind:
        head += f"  ({kind})"
    lines = [head]
    key = str(ref.get("key") or "")
    if key:
        lines.append(f"    연결  {field_label(key)}")
    lines.extend(format_fields(obj, skip_kind=True, indent=4))
    return lines


def section_card(title: str, lines: list[str]) -> str:
    """Boxed block for a branch rule or an AAA object, separate from the prose."""
    body = _lines_html(lines)
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;">'
        '<tr><td style="background-color:#F4F7FB; padding:10px 12px;">'
        "<div style=\"font-family:'Malgun Gothic'; font-size:12px; font-weight:700; "
        f'color:#0260EA;">{html.escape(title)}</div>'
        "<div style=\"font-family:'Malgun Gothic'; font-size:13px; color:#1A2332; "
        f'margin-top:6px;">{body}</div>'
        "</td></tr></table>"
    )


def object_section_html(
    title: str,
    obj: dict[str, Any],
    *,
    lead: list[tuple[str, str]] | None = None,
    skip_kind: bool = False,
) -> str:
    """One object card. Short settings are rows; long or nested ones are inner boxes."""
    skip = set(_SKIP)
    if skip_kind:
        skip.add("object_kind")
    body = _fields_html(obj, lead or [], skip) or '<div style="color:#5C6B7A;">—</div>'
    return _shell(title, body)


def detail_document_html(
    text: str,
    codes: list[tuple[str, str]],
    cards: list[tuple[str, list[str]]] | None = None,
    sections: list[str] | None = None,
) -> str:
    prose = html.escape(text).replace("\n", "<br>")
    parts = [
        "<div style=\"font-family:'Malgun Gothic'; font-size:14px; color:#1A2332;\">"
        f"{prose}</div>"
    ]
    for title, lines in cards or []:
        parts.append(section_card(title, lines))
    for fragment in sections or []:
        parts.append(fragment)
    for title, source in codes:
        parts.append(_code_card(title, source))
    return "".join(parts)


def _shell(title: str, body: str) -> str:
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;">'
        '<tr><td style="background-color:#F4F7FB; padding:10px 12px;">'
        "<div style=\"font-family:'Malgun Gothic'; font-size:12px; font-weight:700; "
        f'color:#0260EA;">{html.escape(title)}</div>'
        f"{body}</td></tr></table>"
    )


def _fields_html(obj: dict[str, Any], lead: list[tuple[str, str]], skip: set[str]) -> str:
    chunks: list[str] = []
    rows: list[tuple[str, str]] = list(lead)
    for key, item in obj.items():
        name = str(key)
        if name in skip or name.startswith("_") or item in (None, ""):
            continue
        label = field_label(name)
        if _is_block(name, item):
            _flush_rows(chunks, rows)
            rows = []
            chunks.append(_block_html(label, item, code=_is_code(name, item)))
        else:
            rows.append((label, _scalar(item)))
    _flush_rows(chunks, rows)
    return "".join(chunks)


def _flush_rows(chunks: list[str], rows: list[tuple[str, str]]) -> None:
    table = _row_table(rows)
    if table:
        chunks.append(table)


def _row_table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    body: list[str] = []
    for index, (label, value) in enumerate(rows):
        bg = "#FFFFFF" if index % 2 == 0 else "#E7EEF6"
        body.append(
            "<tr>"
            f'<td width="118" style="background-color:{bg}; padding:6px 8px; '
            f'color:#5C6B7A;">{html.escape(label)}</td>'
            f'<td style="background-color:{bg}; padding:6px 8px; color:#1A2332;">'
            f"{html.escape(value)}</td></tr>"
        )
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;">'
        + "".join(body)
        + "</table>"
    )


def _block_html(label: str, item: Any, *, code: bool) -> str:
    inner = _block_body(item, code=code)
    if not inner:
        return ""
    return (
        '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;">'
        '<tr><td style="background-color:#FFFFFF; padding:8px 10px;">'
        "<div style=\"font-family:'Malgun Gothic'; font-size:12px; font-weight:700; "
        f'color:#334155;">{html.escape(label)}</div>'
        f'<div style="margin-top:4px;">{inner}</div>'
        "</td></tr></table>"
    )


def _block_body(item: Any, *, code: bool) -> str:
    if isinstance(item, dict):
        chunks: list[str] = []
        rows: list[tuple[str, str]] = []
        for key, value in item.items():
            name = str(key)
            if name in _SKIP or name.startswith("_") or value in (None, ""):
                continue
            label = field_label(name)
            if isinstance(value, dict):
                _flush_rows(chunks, rows)
                rows = []
                nested = _block_body(value, code=False)
                if nested:
                    heading = (
                        "<div style=\"font-family:'Malgun Gothic'; font-size:12px; "
                        "font-weight:700; color:#334155; margin-top:6px;\">"
                        f"{html.escape(label)}</div>"
                    )
                    chunks.append(heading + nested)
            elif _is_block(name, value):
                _flush_rows(chunks, rows)
                rows = []
                chunks.append(_block_html(label, value, code=_is_code(name, value)))
            else:
                rows.append((label, _scalar(value)))
        _flush_rows(chunks, rows)
        return "".join(chunks)
    if isinstance(item, list):
        text = "\n".join(_scalar(piece) for piece in item if piece not in (None, ""))
        return _text_html(text, code=code)
    return _text_html(_scalar(item), code=code)


def _is_block(key: str, item: Any) -> bool:
    if isinstance(item, (dict, list)):
        return True
    if key in _BLOCK_KEYS:
        return True
    text = _scalar(item)
    return "\n" in text or len(text) > 64


def _is_code(key: str, item: Any) -> bool:
    if key in _CODE_KEYS:
        return True
    return isinstance(item, str) and "\n" in item and ("{" in item or "%{" in item)


def _text_html(text: str, *, code: bool) -> str:
    rendered: list[str] = []
    for line in text.splitlines() or [""]:
        piece = html.escape(line)
        if code:
            piece = piece.replace(" ", "&nbsp;")
        rendered.append(piece or "&nbsp;")
    family = "Consolas,monospace" if code else "'Malgun Gothic'"
    return (
        f'<div style="font-family:{family}; font-size:13px; color:#1A2332;">'
        + "<br>".join(rendered)
        + "</div>"
    )


def _lines_html(lines: list[str]) -> str:
    rendered: list[str] = []
    for line in lines:
        pieces = line.splitlines() or [""]
        for piece in pieces:
            rendered.append(html.escape(piece).replace(" ", "&nbsp;") or "&nbsp;")
    return "<br>".join(rendered)


def _code_card(title: str, source: str) -> str:
    rendered: list[str] = []
    raw_lines = str(source or "").splitlines() or [""]
    for line in raw_lines:
        rendered.append(html.escape(line).replace(" ", "&nbsp;"))
    body = "<br>".join(rendered)
    return (
        '<table width="100%" cellspacing="0" cellpadding="0"><tr><td '
        'style="background-color:#F4F7FB; padding:10px 12px;">'
        "<div style=\"font-family:'Malgun Gothic'; font-size:12px; "
        f'font-weight:700; color:#334155;">{html.escape(title)}</div>'
        '<div style="font-family:Consolas,monospace; font-size:13px; color:#1E293B;">'
        f"{body}</div></td></tr></table>"
    )


def _scalar(value: Any) -> str:
    if value is True:
        return "예"
    if value is False:
        return "아니오"
    return str(value)


def _lines(value: Any, skip: set[str], indent: int) -> list[str]:
    if not isinstance(value, dict):
        return []
    rows: list[str] = []
    pad = " " * indent
    for key, item in value.items():
        name = str(key)
        if name in skip or name.startswith("_"):
            continue
        label = field_label(name)
        if isinstance(item, dict):
            nested = _lines(item, skip, indent + 4)
            if nested:
                rows.append(f"{pad}{label}")
                rows.extend(nested)
            continue
        if isinstance(item, list):
            shown = ", ".join(_scalar(piece) for piece in item if piece not in (None, ""))
            if shown:
                rows.append(f"{pad}{label}: {shown}")
            continue
        if item in (None, ""):
            continue
        rows.append(f"{pad}{label}: {_scalar(item)}")
    return rows
