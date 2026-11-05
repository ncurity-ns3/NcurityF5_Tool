from __future__ import annotations

from app.modules.vpe_macro.apm_macro import (
    AccessProfileRef,
    MacroSnapshot,
    MacroSummary,
    apply_macro_snapshot,
    export_macro_snapshot,
)
from app.modules.vpe_macro.macro_boxes import (
    parse_tmsh_object,
    saved_macro_cleanup_command,
    saved_macro_transaction,
    strip_object_refs,
)

_HEADER = """
apm policy access-policy auth_ad {
    caption Auth_AD
    default-ending auth_ad_ter_out
    items {
        auth_ad_ent_in { priority 0 }
        auth_ad_act_logon_page { priority 0 }
        auth_ad_act_ad_auth { priority 0 }
        auth_ad_act_ad_query { priority 0 }
        auth_ad_ter_passed { priority 0 }
        auth_ad_ter_out { priority 0 }
    }
    start-item auth_ad_ent_in
    type macro
}
"""

_LOGON_ITEM = """
apm policy policy-item auth_ad_act_logon_page {
    agents {
        auth_ad_act_logon_page_ag { type logon-page }
    }
    caption "Logon Page_AD"
    color 1
    item-type action
    rules {
        { caption fallback next-item auth_ad_act_ad_auth }
    }
}
"""

_AUTH_ITEM = """
apm policy policy-item auth_ad_act_ad_auth {
    agents {
        auth_ad_act_ad_auth_ag { type aaa-active-directory }
    }
    caption "AD Auth"
    color 1
    item-type action
    rules {
        {
            caption Successful
            expression "expr {[mcget {session.ad.last.authresult}] == 1}"
            next-item auth_ad_act_ad_query
        }
        { caption fallback next-item auth_ad_ter_out }
    }
}
"""

_QUERY_ITEM = """
apm policy policy-item auth_ad_act_ad_query {
    agents {
        auth_ad_act_ad_query_ag { type aaa-active-directory }
    }
    caption "AD Query"
    color 1
    item-type action
    rules {
        { caption fallback next-item auth_ad_ter_passed }
    }
}
"""

_ENTRY = """
apm policy policy-item auth_ad_ent_in {
    caption In
    color 1
    rules {
        { caption fallback next-item auth_ad_act_logon_page }
    }
}
"""

_PASSED = """
apm policy policy-item auth_ad_ter_passed {
    caption AD_Auth_Passed
    color 1
    item-type terminal-out
}
"""

_FAILED = """
apm policy policy-item auth_ad_ter_out {
    caption AD_Auth_Failed
    color 2
    item-type terminal-out
}
"""

_LOGON_AGENT = """
apm policy agent logon-page auth_ad_act_logon_page_ag {
    customization-group auth_ad_act_logon_page_ag
}
"""

_AUTH_AGENT = """
apm policy agent aaa-active-directory auth_ad_act_ad_auth_ag {
    server AD_Ncurity
    type auth
}
"""

_QUERY_AGENT = """
apm policy agent aaa-active-directory auth_ad_act_ad_query_ag {
    query-attrname { cn sAMAccountName }
    query-filter "(sAmAccountName=%{session.logon.last.username})"
    server AD_Ncurity
    type query
}
"""

_ITEMS = "\n".join(
    [
        "---NCURITY---",
        _ENTRY,
        "---NCURITY---",
        _LOGON_ITEM,
        "---NCURITY---",
        _AUTH_ITEM,
        "---NCURITY---",
        _QUERY_ITEM,
        "---NCURITY---",
        _PASSED,
        "---NCURITY---",
        _FAILED,
    ]
)
_AGENTS = "\n".join(
    [
        "---NCURITY---",
        _LOGON_AGENT,
        "---NCURITY---",
        _AUTH_AGENT,
        "---NCURITY---",
        _QUERY_AGENT,
    ]
)


def test_parse_keeps_expression_and_strips_server() -> None:
    item = parse_tmsh_object(_AUTH_ITEM)
    assert item is not None
    rule = item["body"]["rules"][0]
    assert "session.ad.last.authresult" in rule["expression"]
    agent = parse_tmsh_object(_QUERY_AGENT)
    assert agent is not None
    cleaned = strip_object_refs(agent["body"])
    assert "server" not in cleaned
    assert cleaned["query-attrname"] == ["cn", "sAMAccountName"]
    assert "session.logon.last.username" in cleaned["query-filter"]
    logon = parse_tmsh_object(_LOGON_AGENT)
    assert logon is not None
    assert "customization-group" not in strip_object_refs(logon["body"])


class _ExportClient:
    def run_util_bash(self, shell_command: str, *, timeout: float | None = None, max_bytes: int | None = None) -> str:
        if "start-item" in shell_command:
            return _HEADER
        if "policy-item" in shell_command:
            return _ITEMS
        if "policy agent" in shell_command:
            return _AGENTS
        return ""


def test_export_saves_boxes_without_bound_object_names() -> None:
    macro = MacroSummary(
        caption="Auth_AD",
        name="auth_ad",
        partition="Common",
        full_path="/Common/auth_ad",
        exits=(),
        agent_labels=(),
        item_count=1,
        item_paths=("/Common/auth_ad",),
    )
    profile = AccessProfileRef(
        name="AP_Ejes_Modern",
        partition="Common",
        full_path="/Common/AP_Ejes_Modern",
        policy_path="/Common/AP_Ejes_Modern",
        policy_name="AP_Ejes_Modern",
    )
    snapshot = export_macro_snapshot(
        _ExportClient(),  # type: ignore[arg-type]
        profile=profile,
        policy={"name": "AP_Ejes_Modern"},
        items=[],
        macro=macro,
    )
    names = [item.get("name") for item in snapshot.items]
    assert "auth_ad_act_logon_page" in names
    assert "auth_ad_act_ad_auth" in names
    assert "auth_ad_act_ad_query" in names
    assert "auth_ad_ter_passed" in names
    blob = str(snapshot.to_dict())
    assert "AD_Ncurity" not in blob
    assert "auth_ad_act_logon_page_ag" in blob
    assert "customization-group" not in blob
    assert "session.logon.last.username" in blob


class _ApplyClient:
    def __init__(self) -> None:
        self.bash: list[str] = []

    def run_util_bash(self, shell_command: str, *, timeout: float | None = None, max_bytes: int | None = None) -> str:
        self.bash.append(shell_command)
        if "create cli transaction" in shell_command:
            return ""
        if "grep -i -E" in shell_command and "auth_ad_1" in shell_command:
            return "apm policy access-policy auth_ad_1 {\n"
        if "grep" in shell_command:
            return "apm policy access-policy /Common/auth_ad {\n"
        return ""


def test_load_creates_boxes_with_server_none() -> None:
    snapshot = export_macro_snapshot(
        _ExportClient(),  # type: ignore[arg-type]
        profile=AccessProfileRef(
            name="AP_Ejes_Modern",
            partition="Common",
            full_path="/Common/AP_Ejes_Modern",
            policy_path="/Common/AP_Ejes_Modern",
            policy_name="AP_Ejes_Modern",
        ),
        policy={"name": "AP_Ejes_Modern"},
        items=[],
        macro=MacroSummary(
            caption="auth_ad",
            name="auth_ad",
            partition="Common",
            full_path="/Common/auth_ad",
            exits=(),
            agent_labels=(),
            item_count=1,
            item_paths=("/Common/auth_ad",),
        ),
    )
    client = _ApplyClient()
    result = apply_macro_snapshot(
        client,  # type: ignore[arg-type]
        snapshot=snapshot,
        target_profile=AccessProfileRef(
            name="AP_Ejes_Assign_Only",
            partition="Common",
            full_path="/Common/AP_Ejes_Assign_Only",
            policy_path="/Common/AP_Ejes_Assign_Only",
            policy_name="AP_Ejes_Assign_Only",
        ),
        existing_policy={},
        existing_items=[],
        target_macro_name="auth_ad",
    )
    blob = "\n".join(client.bash)
    assert result.created_items == ["auth_ad_1"]
    assert blob.count("submit cli transaction") == 1
    assert "create apm policy agent logon-page /Common/auth_ad_1_act_logon_page_ag" in blob
    assert "create apm policy agent aaa-active-directory /Common/auth_ad_1_act_ad_auth_ag" in blob
    assert "server none" in blob
    assert "AD_Ncurity" not in blob
    assert "auth_ad_act_logon_page_ag" not in blob or "auth_ad_2_act_logon_page_ag" in blob
    assert "customization-group /Common/auth_ad_act_logon_page_ag" not in blob
    assert "source modern" in blob
    assert 'query-filter "(sAmAccountName=%{session.logon.last.username})"' in blob
    assert "session.ad.last.authresult" in blob
    assert "item-type terminal-out" in blob
    assert "macros add { /Common/auth_ad_1 }" in blob
    assert "macros add { /Common/auth_ad }" not in blob
    assert "ending-allow" not in blob


def test_cleanup_removes_only_the_new_macro() -> None:
    command = saved_macro_cleanup_command(
        partition="Common",
        actual="Auth_AD_2",
        target_policy_path="/Common/AP_Ejes_Assign_Only",
        source_name="auth_ad",
        items=[
            {"name": "auth_ad_ent_in", "itemType": "entry"},
            {"name": "auth_ad_act_logon_page", "itemType": "action", "agents": [
                {"name": "auth_ad_act_logon_page_ag", "type": "logon-page"}
            ]},
            {"name": "auth_ad_ter_out", "itemType": "terminal-out"},
        ],
        agents=[],
    )
    assert "delete apm policy access-policy /Common/Auth_AD_2" in command
    assert "policy-item /Common/Auth_AD_2_ent_in" in command
    assert "agent logon-page /Common/Auth_AD_2_act_logon_page_ag" in command
    assert "customization-group /Common/Auth_AD_2_act_logon_page_ag_cg" in command
    assert "policy-item /Common/auth_ad_ent_in" not in command
    assert "access-policy /Common/auth_ad;" not in command
    assert "macros delete { /Common/auth_ad }" not in command


def test_transaction_quotes_expression() -> None:
    script = saved_macro_transaction(
        partition="Common",
        actual="auth_ad_2",
        caption="auth_ad_2",
        target_policy_path="/Common/AP_Ejes_Assign_Only",
        source_name="auth_ad",
        items=[
            {
                "name": "auth_ad",
                "itemType": "macro",
                "startItem": "/Common/auth_ad_ent_in",
                "defaultEnding": "/Common/auth_ad_ter_out",
            },
            {
                "name": "auth_ad_ent_in",
                "caption": "In",
                "color": 1,
                "itemType": "entry",
                "rules": [{"caption": "fallback", "nextItem": "/Common/auth_ad_act_ad_auth"}],
            },
            {
                "name": "auth_ad_act_ad_auth",
                "caption": "AD Auth",
                "color": 1,
                "itemType": "action",
                "agents": [{"name": "auth_ad_act_ad_auth_ag", "type": "aaa-active-directory"}],
                "rules": [
                    {
                        "caption": "Successful",
                        "expression": "expr {[mcget {session.ad.last.authresult}] == 1}",
                        "nextItem": "/Common/auth_ad_ter_out",
                    }
                ],
            },
            {
                "name": "auth_ad_ter_out",
                "caption": "AD_Auth_Failed",
                "color": 2,
                "itemType": "terminal-out",
            },
        ],
        agents=[
            {
                "type": "aaa-active-directory",
                "name": "auth_ad_act_ad_auth_ag",
                "body": {"type": "auth", "server": "AD_Ncurity"},
            }
        ],
        start_item="",
        default_ending="",
    )
    assert "server none" in script
    assert "AD_Ncurity" not in script
    assert 'expression "expr {[mcget {session.ad.last.authresult}] == 1}"' in script
    assert "item-type terminal-out" in script
    assert script.index("item-type terminal-out") < script.index("item-type entry")
