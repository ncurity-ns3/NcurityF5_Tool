"""Build one lab request, or a short login sequence, as curl arguments."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from app.modules.waf_poc.curlutil import Target

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$")
_COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}$")
_MAX_ACCOUNTS = 20
_MAX_ATTEMPTS = 20
_SET_COOKIE = re.compile(r"(?im)^set-cookie:\s*([^=;\s]+)=([^;\r\n]*)")


@dataclass(frozen=True)
class LoginPlan:
    uri: str
    kind: str
    username: str
    password: str
    use_numbers: bool
    number_from: int
    number_to: int
    attempts: int
    pause_seconds: int
    user_field: str
    password_field: str
    body_template: str
    content_type: str


@dataclass(frozen=True)
class PreparedCall:
    label: str
    argv: list[str]


def accounts_for(plan: LoginPlan) -> list[tuple[str, str]]:
    if plan.attempts < 1 or plan.attempts > _MAX_ATTEMPTS:
        raise ValueError(f"시도 횟수는 1부터 {_MAX_ATTEMPTS}까지입니다.")
    if plan.pause_seconds < 0 or plan.pause_seconds > 10:
        raise ValueError("간격은 0초부터 10초까지입니다.")
    names = _account_names(plan)
    if len(names) > _MAX_ACCOUNTS:
        raise ValueError(f"계정은 한 번에 {_MAX_ACCOUNTS}개까지입니다.")
    return [(name, plan.password) for name in names for _ in range(plan.attempts)]


def build_main_call(
    target: Target,
    curl_bin: str,
    *,
    method: str,
    uri: str,
    query: list[tuple[str, str]],
    body_mode: str,
    body_fields: list[tuple[str, str]],
    raw_body: str,
    headers: list[tuple[str, str]],
    cookies: list[tuple[str, str]],
    insecure: bool,
) -> PreparedCall:
    verb = method.strip().upper()
    if verb not in _METHODS:
        raise ValueError("Method를 확인해 주세요.")
    path = _path(uri)
    pairs = _clean_pairs(query, "파라미터")
    url = target.origin + path
    if pairs:
        url = f"{url}?{urlencode(pairs)}"
    extra = list(headers)
    data: str | None = None
    if verb in _BODY_METHODS and body_mode == "raw":
        _reject_break(raw_body, "본문")
        data = raw_body
    elif verb in _BODY_METHODS and body_mode == "form":
        fields = _clean_pairs(body_fields, "파라미터")
        if fields:
            data = urlencode(fields)
            extra = _ensure_content_type(extra, "application/x-www-form-urlencoded")
    return PreparedCall(
        "요청",
        _argv(
            target,
            curl_bin,
            method=verb,
            url=url,
            headers=extra,
            cookies=cookies,
            data=data,
            insecure=insecure,
        ),
    )


def build_login_call(
    target: Target,
    curl_bin: str,
    plan: LoginPlan,
    username: str,
    password: str,
    *,
    insecure: bool,
) -> PreparedCall:
    path = _path(plan.uri)
    url = target.origin + path
    _reject_break(username, "계정")
    _reject_break(password, "비밀번호")
    headers: list[tuple[str, str]] = []
    data: str | None = None
    if plan.kind == "basic":
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        headers.append(("Authorization", f"Basic {token}"))
    elif plan.kind == "form":
        user_field = _field_name(plan.user_field, "계정 필드")
        pass_field = _field_name(plan.password_field, "비밀번호 필드")
        data = urlencode([(user_field, username), (pass_field, password)])
        headers.append(("Content-Type", "application/x-www-form-urlencoded"))
    elif plan.kind == "body":
        _reject_break(plan.body_template, "본문")
        _reject_break(plan.content_type, "Content-Type")
        data = plan.body_template.replace("{user}", username).replace("{password}", password)
        if plan.content_type.strip():
            headers.append(("Content-Type", plan.content_type.strip()))
    else:
        raise ValueError("인증 방식을 확인해 주세요.")
    verb = "GET" if plan.kind == "basic" else "POST"
    return PreparedCall(
        f"로그인 {username}",
        _argv(
            target,
            curl_bin,
            method=verb,
            url=url,
            headers=headers,
            cookies=[],
            data=data,
            insecure=insecure,
        ),
    )


def cookies_from_response(output: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for name, value in _SET_COOKIE.findall(output or ""):
        if _COOKIE_NAME.fullmatch(name):
            found.append((name, value.strip()))
    return found


def _account_names(plan: LoginPlan) -> list[str]:
    _reject_break(plan.username, "계정")
    if not plan.use_numbers:
        if not plan.username.strip():
            raise ValueError("계정을 입력해 주세요.")
        return [plan.username.strip()]
    if plan.number_from < 1 or plan.number_to > 100 or plan.number_from > plan.number_to:
        raise ValueError("계정 번호는 1부터 100까지, 시작이 끝보다 크면 안 됩니다.")
    start = plan.number_from
    stop = plan.number_to + 1
    return [f"{plan.username.strip()}{number}" for number in range(start, stop)]


def _argv(
    target: Target,
    curl_bin: str,
    *,
    method: str,
    url: str,
    headers: list[tuple[str, str]],
    cookies: list[tuple[str, str]],
    data: str | None,
    insecure: bool,
) -> list[str]:
    argv = [
        curl_bin,
        "--path-as-is",
        "--max-time",
        "20",
        "--connect-timeout",
        "8",
        "-sS",
        "-i",
        "-w",
        "\n[http %{http_code}]\n",
        "--resolve",
        f"{target.host}:{target.port}:{target.resolve_address}",
        "-X",
        method,
        "-H",
        f"Host: {target.authority}",
    ]
    if insecure:
        argv.append("-k")
    for name, value in _clean_headers(headers):
        argv.extend(["-H", f"{name}: {value}"])
    cookie_pairs = _clean_pairs(cookies, "쿠키")
    if cookie_pairs:
        cookie = "; ".join(f"{name}={value}" for name, value in cookie_pairs)
        argv.extend(["-H", f"Cookie: {cookie}"])
    if data is not None:
        argv.extend(["--data-binary", data])
    argv.append(url)
    return argv


def _path(uri: str) -> str:
    text = uri.strip() or "/"
    _reject_break(text, "URI")
    if text.startswith(("http://", "https://")) or not text.startswith("/"):
        raise ValueError("URI는 / 로 시작하는 경로만 사용할 수 있습니다.")
    if any(char.isspace() for char in text):
        raise ValueError("URI에 공백을 넣을 수 없습니다.")
    return text


def _clean_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    for name, value in headers:
        item_name = name.strip()
        item_value = value.strip()
        if not item_name and not item_value:
            continue
        if _HEADER_NAME.fullmatch(item_name) is None:
            raise ValueError(f"헤더 이름을 확인해 주세요: {item_name}")
        _reject_break(item_value, "헤더 값")
        if item_name.lower() == "host":
            continue
        cleaned.append((item_name, item_value))
    return cleaned


def _ensure_content_type(headers: list[tuple[str, str]], value: str) -> list[tuple[str, str]]:
    if any(name.lower() == "content-type" for name, _value in headers):
        return headers
    return [*headers, ("Content-Type", value)]


def _clean_pairs(pairs: list[tuple[str, str]], label: str) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    for name, value in pairs:
        item_name = name.strip()
        item_value = value.strip()
        if not item_name and not item_value:
            continue
        if not item_name:
            raise ValueError(f"{label} 이름을 입력해 주세요.")
        _reject_break(item_name, label)
        _reject_break(item_value, label)
        cleaned.append((item_name, item_value))
    return cleaned


def _field_name(name: str, label: str) -> str:
    text = name.strip()
    if not text or any(char.isspace() for char in text):
        raise ValueError(f"{label} 이름을 확인해 주세요.")
    _reject_break(text, label)
    return text


def _reject_break(value: str, label: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{label}에 줄바꿈을 넣을 수 없습니다.")
