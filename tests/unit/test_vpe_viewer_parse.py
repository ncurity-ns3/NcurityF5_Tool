"""Large UCS text must not fail the whole viewer on one broken object."""

from app.modules.vpe_viewer.parser import parse_apm_config

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
