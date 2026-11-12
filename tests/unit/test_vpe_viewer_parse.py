"""Large UCS text must not fail the whole viewer on one broken object."""

from app.modules.vpe_viewer.parser import _skip_brace_block, parse_apm_config

_POLICY = """
apm policy access-policy /Common/AP {
    caption AP
    default-ending /Common/deny
    items {
        /Common/start
    }
    start-item /Common/start
    type access-policy
}
apm policy policy-item /Common/start {
    caption Start
    color 1
    item-type entry
    rules {
        fallback {
            caption fallback
            next-item /Common/deny
        }
    }
}
"""


def test_css_in_customization_group_does_not_drop_the_policy() -> None:
    text = (
        """
apm policy customization-group /Common/cg {
    type logon
    source {
<style>
body { color: red;
</style>
    }
}
"""
        + _POLICY
    )
    model = parse_apm_config(text)
    names = [policy["name"] for policy in model["policies"]]
    assert "/Common/AP" in names
    assert model["summary"]["items"] == 1


def test_unclosed_virtual_still_keeps_the_access_policy() -> None:
    text = (
        """
ltm virtual /Common/vs {
    destination 10.1.1.1:443
    profiles {
        /Common/http { }
"""
        + _POLICY
    )
    model = parse_apm_config(text)
    names = [policy["name"] for policy in model["policies"]]
    assert "/Common/AP" in names


def test_escaped_quotes_do_not_swallow_the_next_access_policy() -> None:
    text = '''apm aaa http /Common/demo {
    custom-body "{
	\\"site\\":\\"x\\"
}"
    success-match-value \\"result\\":\\"true\\"
}
apm policy access-policy /Common/next {
    start-item /Common/x
}
'''
    brace = text.find("{")
    rest = text[_skip_brace_block(text, brace) :]
    assert "apm policy access-policy /Common/next" in rest
    model = parse_apm_config(
        text
        + """
apm aaa http /Common/http_vPortal {
    auth-type form-based
    form-method get
    success-match-value \\"OK\\"
}
"""
    )
    assert any(policy["name"] == "/Common/next" for policy in model["policies"])
    assert model["objects"]["/Common/http_vPortal"]["success-match-value"] == "OK"


def test_unused_terminal_is_left_off_the_graph() -> None:
    text = """
apm policy access-policy /Common/AP {
    items {
        /Common/start { }
        /Common/allow { }
        /Common/unused { }
    }
    start-item /Common/start
    type access-policy
}
apm policy policy-item /Common/start {
    caption Start
    item-type entry
    rules {
        fallback {
            caption fallback
            next-item /Common/allow
        }
    }
}
apm policy policy-item /Common/allow {
    caption Allow
    item-type ending
}
apm policy policy-item /Common/unused {
    caption Deny
    item-type terminal-out
}
"""
    model = parse_apm_config(text)
    policy = next(item for item in model["policies"] if item["name"] == "/Common/AP")
    ids = {node["id"] for node in policy["nodes"]}
    assert "/Common/allow" in ids
    assert "/Common/unused" not in ids
