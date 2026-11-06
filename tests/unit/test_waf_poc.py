from app.modules.waf_poc.catalog import YEARS, cases_for_year
from app.modules.waf_poc.curlutil import Target, build_curl_argv, rewrite_curl_line, split_bash

_LINE = (
    'curl -k --resolve curl.ncurity.com:80:192.168.41.91 '
    '"http://curl.ncurity.com/bWAPP/login.php?id=1"'
)


def test_years_list_2017_and_2021() -> None:
    assert YEARS == (2017, 2021, 2025)
    assert cases_for_year(2025) == ()
    older = cases_for_year(2017)
    newer = cases_for_year(2021)
    assert [case.case_id for case in older][:3] == ["2017-01", "2017-02", "2017-03"]
    assert older[-1].case_id == "2017-15"
    assert {case.group for case in newer} >= {
        "A1 Broken Access Control",
        "A3 Injection",
        "A4 Insecure Design",
        "A5 Security Misconfiguration",
        "A8 Software and Data Integrity",
        "A10 Server-Side Request Forgery",
    }
    assert "a3-11" in {case.case_id for case in newer}
    for case in (*older, *newer):
        commands = case.commands()
        assert commands
        assert all(command.startswith("curl ") for command in commands)


def test_rewrite_2017_resolve_address() -> None:
    line = (
        'curl -k --resolve curl.ncurity.com:80:192.168.41.52 '
        '"http://curl.ncurity.com/bWAPP/login.php?id=1"'
    )
    target = Target.parse("10.0.0.8", "lab.example", "http", 80)
    rewritten = rewrite_curl_line(line, target)
    assert "lab.example:80:10.0.0.8" in rewritten
    assert "192.168.41.52" not in rewritten
    assert "curl.ncurity.com" not in rewritten


def test_rewrite_http_https_and_custom_port() -> None:
    http = Target.parse("10.0.0.8", "lab.example", "http", 80)
    rewritten = rewrite_curl_line(_LINE, http)
    assert "lab.example:80:10.0.0.8" in rewritten
    assert "http://lab.example/bWAPP" in rewritten
    assert "curl.ncurity.com" not in rewritten

    https = Target.parse("10.0.0.8", "lab.example", "https", 443)
    secure = rewrite_curl_line(_LINE, https)
    assert "lab.example:443:10.0.0.8" in secure
    assert "https://lab.example/bWAPP" in secure

    custom = Target.parse("10.1.2.3", "lab.example.com", "https", 8443)
    other = rewrite_curl_line(_LINE, custom)
    assert "lab.example.com:8443:10.1.2.3" in other
    assert "https://lab.example.com:8443/bWAPP" in other


def test_payload_address_is_not_replaced() -> None:
    case = next(case for case in cases_for_year(2021) if case.case_id == "a3-05")
    target = Target.parse("10.9.8.7", "waf.example", "http", 80)
    rewritten = [rewrite_curl_line(line, target) for line in case.commands()]
    joined = "\n".join(rewritten)
    assert "192.168.41.91" not in joined
    assert "192.168.1.212" in joined
    assert "curl.ncurity.com" not in joined


def test_split_keeps_bash_backslash_and_ampersand() -> None:
    case = next(case for case in cases_for_year(2021) if case.case_id == "a3-07")
    target = Target.parse("192.168.41.91", "curl.ncurity.com", "http", 80)
    _shown, argv = build_curl_argv(case.commands()[0], target, "curl.exe")
    url = next(arg for arg in argv if arg.startswith("http"))
    assert r"\[" in url

    amp_case = next(case for case in cases_for_year(2021) if case.case_id == "a3-06")
    _shown, amp_argv = build_curl_argv(amp_case.commands()[1], target, "curl.exe")
    assert "&" not in amp_argv
    assert any("&" in arg for arg in amp_argv)
    assert amp_argv[0] == "curl.exe"
    assert "--max-time" in amp_argv


def test_split_bash_rejects_open_quote() -> None:
    try:
        split_bash('curl "http://example')
    except ValueError as exc:
        assert "따옴표" in str(exc)
    else:
        raise AssertionError("open quote should fail")


def test_target_rejects_shell_metacharacters() -> None:
    try:
        Target.parse("192.168.41.91", "curl.ncurity.com;id", "http", 80)
    except ValueError as exc:
        assert "Host" in str(exc)
    else:
        raise AssertionError("host should be rejected")
