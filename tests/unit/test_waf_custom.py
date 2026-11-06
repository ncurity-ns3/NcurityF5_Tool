from app.modules.waf_poc.curlutil import Target
from app.modules.waf_poc.custom_request import (
    LoginPlan,
    accounts_for,
    build_login_call,
    build_main_call,
    cookies_from_response,
)
from app.modules.waf_poc.verdict import RequestResult, classify_response, summary_rows


def _target() -> Target:
    return Target.parse("192.168.41.91", "curl.ncurity.com", "http", 80)


def test_blocked_status_and_block_page() -> None:
    assert classify_response("HTTP/1.1 403\n\n[http 403]", timed_out=False, return_code=0) == (
        "blocked",
        403,
    )
    page = "HTTP/1.1 200\n\nRequest Rejected\nSupport ID: 1\n[http 200]"
    assert classify_response(page, timed_out=False, return_code=0)[0] == "blocked"
    assert classify_response("HTTP/1.1 200\n\nok\n[http 200]", timed_out=False, return_code=0) == (
        "passed",
        200,
    )
    assert classify_response("", timed_out=True, return_code=28) == ("failed", None)


def test_summary_counts_each_category() -> None:
    results = [
        RequestResult("A1 Broken Access Control", "a", "curl", 403, "blocked", ""),
        RequestResult("A1 Broken Access Control", "b", "curl", 200, "passed", ""),
        RequestResult("A3 Injection", "c", "curl", None, "failed", ""),
    ]
    rows = summary_rows(results)
    assert rows[0] == ("A1 Broken Access Control", 2, 1, 1, 0)
    assert rows[1] == ("A3 Injection", 1, 0, 0, 1)
    assert rows[-1] == ("합계", 3, 1, 1, 1)


def test_numbered_accounts_and_attempt_repeat() -> None:
    plan = LoginPlan(
        uri="/login",
        kind="form",
        username="user",
        password="secret",
        use_numbers=True,
        number_from=1,
        number_to=3,
        attempts=2,
        pause_seconds=0,
        user_field="username",
        password_field="password",
        body_template="",
        content_type="",
    )
    assert accounts_for(plan) == [
        ("user1", "secret"),
        ("user1", "secret"),
        ("user2", "secret"),
        ("user2", "secret"),
        ("user3", "secret"),
        ("user3", "secret"),
    ]


def test_get_params_go_on_the_path() -> None:
    call = build_main_call(
        _target(),
        "curl.exe",
        method="GET",
        uri="/app",
        params=[("q", "1"), ("name", "a b")],
        headers=[("User-Agent", "lab")],
        cookies=[("sid", "1")],
        insecure=True,
    )
    assert call.argv[-1] == "http://curl.ncurity.com/app?q=1&name=a+b"
    assert "--data-binary" not in call.argv
    assert "Cookie: sid=1" in call.argv
    assert "curl.ncurity.com:80:192.168.41.91" in call.argv


def test_post_params_go_in_the_body() -> None:
    call = build_main_call(
        _target(),
        "curl.exe",
        method="POST",
        uri="/app",
        params=[("name", "a b")],
        headers=[("User-Agent", "lab")],
        cookies=[],
        insecure=True,
    )
    assert call.argv[-1] == "http://curl.ncurity.com/app"
    assert "name=a+b" in call.argv
    assert "Content-Type: application/x-www-form-urlencoded" in call.argv


def test_login_form_basic_and_body() -> None:
    target = _target()
    form = build_login_call(
        target,
        "curl.exe",
        _plan("form"),
        "user1",
        "pw",
        insecure=False,
    )
    assert "username=user1&password=pw" in form.argv
    basic = build_login_call(target, "curl.exe", _plan("basic"), "user1", "pw", insecure=False)
    assert any(item.startswith("Authorization: Basic ") for item in basic.argv)
    body = build_login_call(target, "curl.exe", _plan("body"), "user1", "pw", insecure=False)
    assert any("user1" in item and "pw" in item for item in body.argv)


def test_set_cookie_is_read_from_response() -> None:
    output = "HTTP/1.1 302\nSet-Cookie: sid=abc; Path=/\nSet-Cookie: theme=dark\n"
    assert cookies_from_response(output) == [("sid", "abc"), ("theme", "dark")]


def _plan(kind: str) -> LoginPlan:
    return LoginPlan(
        uri="/login",
        kind=kind,
        username="user",
        password="pw",
        use_numbers=False,
        number_from=1,
        number_to=1,
        attempts=1,
        pause_seconds=0,
        user_field="username",
        password_field="password",
        body_template='{"username":"{user}","password":"{password}"}',
        content_type="application/json",
    )
