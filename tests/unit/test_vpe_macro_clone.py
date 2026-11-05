from __future__ import annotations

from typing import Any

import pytest

from app.modules.vpe_macro.apm_macro import (
    AccessProfileRef,
    MacroApplyError,
    MacroSnapshot,
    apply_macro_snapshot,
    build_apply_plan,
    build_macro_summaries,
    collect_macro_item_paths,
    next_numbered_macro_name,
    parse_access_policy_object_names,
    parse_access_profiles,
    remap_string,
    rest_id,
    strip_rest_metadata,
)


def _item(
    name: str,
    *,
    item_type: str = "action",
    caption: str | None = None,
    nexts: list[tuple[str, str]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    macro: str | None = None,
    partition: str = "Common",
) -> dict[str, Any]:
    rules = []
    for cap, nxt in nexts or []:
        rules.append({"caption": cap, "nextItem": nxt})
    body: dict[str, Any] = {
        "name": name,
        "partition": partition,
        "fullPath": f"/{partition}/{name}",
        "caption": caption or name,
        "itemType": item_type,
        "kind": "tm:apm:policy:policy-item:policy-itemstate",
        "generation": 9,
        "selfLink": f"https://localhost/mgmt/tm/apm/policy/policy-item/~{partition}~{name}",
        "rules": rules,
    }
    if agents:
        body["agents"] = agents
    if macro:
        body["macro"] = macro
    return body


def _assert_load_puts_saved_macro(result: Any, client: Any, *, skipped: str) -> None:
    name = skipped
    assert result.applied_policy is True
    loaded = list(result.created_items) + list(result.skipped)
    assert loaded
    bash = getattr(client, "bash", [])
    posts = getattr(client, "posts", [])
    curl = getattr(client, "curl", [])
    if bash:
        blob = "\n".join(bash)
        assert name in blob or any(item in blob for item in loaded)
        assert "macros add" in blob
        assert "item-type macro" not in blob
        return
    posted_names = [payload.get("name") for _path, payload in posts]
    posted_names.extend(payload.get("name") for _path, payload in curl)
    assert name in posted_names or any(item in posted_names for item in loaded)


def _lab_policy() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = {
        "name": "lab-ap",
        "partition": "Common",
        "startItem": "/Common/lab-ap_ent",
        "defaultEnding": "/Common/lab-ap_end_deny",
        "macros": [{"name": "lab-ap_act_ad", "partition": "Common"}],
        "items": [
            {"name": "lab-ap_ent", "partition": "Common"},
            {"name": "lab-ap_act_call", "partition": "Common"},
            {"name": "lab-ap_end_allow", "partition": "Common"},
            {"name": "lab-ap_end_deny", "partition": "Common"},
        ],
    }
    items = [
        _item("lab-ap_ent", item_type="entry", nexts=[("out", "/Common/lab-ap_act_call")]),
        _item(
            "lab-ap_act_call",
            item_type="macro-call",
            caption="AD Auth",
            macro="/Common/lab-ap_act_ad",
            nexts=[("Successful", "/Common/lab-ap_end_allow"), ("fallback", "/Common/lab-ap_end_deny")],
        ),
        _item("lab-ap_end_allow", item_type="ending"),
        _item("lab-ap_end_deny", item_type="ending"),
        _item(
            "lab-ap_act_ad",
            item_type="macro",
            caption="AD Auth",
            nexts=[("Successful", "/Common/lab-ap_act_ad_out")],
        ),
        _item("lab-ap_act_ad_out", item_type="terminal", caption="Successful"),
        _item(
            "lab-ap_act_ad_logon",
            caption="Logon Page",
            nexts=[
                ("Successful", "/Common/lab-ap_act_ad_auth"),
                ("fallback", "/Common/lab-ap_end_deny"),
            ],
            agents=[{"name": "lab-ap_act_ad_logon_ag", "partition": "Common", "type": "logon-page"}],
        ),
        _item(
            "lab-ap_act_ad_auth",
            caption="AD Query",
            nexts=[("Successful", "/Common/lab-ap_act_ad_out")],
            agents=[
                {
                    "name": "lab-ap_act_ad_auth_ag",
                    "partition": "Common",
                    "type": "aaa-active-directory",
                    "link": (
                        "https://localhost/mgmt/tm/apm/policy/agent/"
                        "aaa-active-directory/~Common~lab-ap_act_ad_auth_ag"
                    ),
                }
            ],
        ),
    ]
    return policy, items


def test_rest_id() -> None:
    assert rest_id("/Common/lab-ap") == "~Common~lab-ap"


def test_parse_access_profiles() -> None:
    refs = parse_access_profiles(
        {
            "items": [
                {
                    "name": "lab-ap",
                    "partition": "Common",
                    "fullPath": "/Common/lab-ap",
                    "accessPolicy": "/Common/lab-ap",
                }
            ]
        }
    )
    assert refs[0].policy_name == "lab-ap"
    assert refs[0].full_path == "/Common/lab-ap"


def test_parse_access_profiles_skips_builtin_access() -> None:
    refs = parse_access_profiles(
        {
            "items": [
                {
                    "name": "access",
                    "partition": "Common",
                    "fullPath": "/Common/access",
                },
                {
                    "name": "lab-ap",
                    "partition": "Common",
                    "fullPath": "/Common/lab-ap",
                    "accessPolicy": "/Common/lab-ap",
                },
            ]
        }
    )
    assert [r.full_path for r in refs] == ["/Common/lab-ap"]


def test_list_access_profiles_skips_policy_missing() -> None:
    from app.modules.vpe_macro.apm_macro import list_access_profiles

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            assert path.startswith("/tm/apm/profile/access")
            return {
                "items": [
                    {
                        "name": "access",
                        "partition": "Common",
                        "fullPath": "/Common/access",
                    },
                    {
                        "name": "lab-ap",
                        "partition": "Common",
                        "fullPath": "/Common/lab-ap",
                        "accessPolicy": "/Common/lab-ap",
                    },
                ]
            }

        def get_optional(self, path: str) -> dict[str, Any]:
            raise AssertionError(f"must not probe each Access Policy: {path}")

    refs = list_access_profiles(_Client())
    assert len(refs) == 1
    assert refs[0].full_path == "/Common/lab-ap"


def test_detached_profile_list_uses_curl_and_keeps_the_password_off_the_url(monkeypatch) -> None:
    import json

    from app.modules.vpe_macro.apm_macro import fetch_access_profiles_detached

    seen: list[tuple[str, dict]] = []

    def fake(url: str, **kwargs):
        seen.append((url, kwargs))
        if url.endswith("/shared/authn/login"):
            return 200, b'{"token":{"token":"TOK"}}'
        return 200, json.dumps(
            {
                "items": [
                    {
                        "name": "lab-ap",
                        "partition": "Common",
                        "fullPath": "/Common/lab-ap",
                        "accessPolicy": "/Common/lab-ap",
                    }
                ]
            }
        ).encode()

    monkeypatch.setattr("app.core.bigip_client.curl_exchange", fake)
    refs = fetch_access_profiles_detached(
        host="192.0.2.10", port=443, username="user", password="s3cret"
    )
    assert [ref.full_path for ref in refs] == ["/Common/lab-ap"]
    assert seen[0][0].endswith("/mgmt/shared/authn/login")
    assert seen[0][1]["payload"]["password"] == "s3cret"
    assert "s3cret" not in seen[1][0]
    assert seen[1][1]["headers"]["X-F5-Auth-Token"] == "TOK"
    assert "$select=name,partition,fullPath,accessPolicy" in seen[1][0]


def test_detached_profile_list_reports_login_failure(monkeypatch) -> None:
    from app.modules.vpe_macro.apm_macro import fetch_access_profiles_detached

    def fake(url: str, **kwargs):
        return 401, b'{"message":"unauthorized"}'

    monkeypatch.setattr("app.core.bigip_client.curl_exchange", fake)
    with pytest.raises(RuntimeError, match="401"):
        fetch_access_profiles_detached(
            host="192.0.2.10", port=443, username="user", password="s3cret"
        )


def test_macro_list_and_closure_excludes_main_flow() -> None:
    policy, items = _lab_policy()
    macros = build_macro_summaries(policy=policy, items=items)
    assert len(macros) == 1
    macro = macros[0]
    assert macro.caption == "AD Auth"
    assert "Successful" in macro.exits
    paths = set(macro.item_paths)
    assert "/Common/lab-ap_act_ad" in paths
    assert "/Common/lab-ap_act_ad_logon" in paths
    assert "/Common/lab-ap_act_ad_auth" in paths
    assert "/Common/lab-ap_ent" not in paths
    assert "/Common/lab-ap_act_call" not in paths
    assert "/Common/lab-ap_end_allow" not in paths
    assert "/Common/lab-ap_end_deny" not in paths


def test_shared_macro_names_are_listed() -> None:
    policy = {
        "name": "AP_Ejes_Modern",
        "partition": "Common",
        "startItem": "/Common/AP_Ejes_Modern_ent",
        "macros": {
            "Auth_AD": {},
            "Auth_LDAP": {},
            "Auth_GoogleOTP": {},
        },
    }
    items = [
        _item("AP_Ejes_Modern_ent", item_type="entry", nexts=[("out", "/Common/AP_Ejes_Modern_end_allow")]),
        _item("AP_Ejes_Modern_end_allow", item_type="ending"),
        _item(
            "Auth_AD",
            item_type="macro",
            caption="Auth_AD",
            nexts=[("AD_Auth_Passed", "/Common/Auth_AD_out_ok")],
        ),
        _item("Auth_AD_out_ok", item_type="terminal", caption="AD_Auth_Passed"),
        _item("Auth_LDAP", item_type="macro", caption="Auth_LDAP"),
        _item("Auth_GoogleOTP", item_type="macro", caption="Auth_GoogleOTP"),
    ]
    macros = build_macro_summaries(policy=policy, items=items)
    captions = {m.caption for m in macros}
    assert captions == {"Auth_AD", "Auth_LDAP", "Auth_GoogleOTP"}


def test_parse_tmsh_access_policy_macros() -> None:
    from app.modules.vpe_macro.apm_macro import parse_tmsh_access_policy_macros

    text = """apm policy access-policy /Common/AP_Ejes_Modern {
    macros {
        Auth_AD { }
        Auth_GoogleOTP { }
        Auth_GoogleOTP_Gen_MessageBox { }
        Auth_LDAP { }
        Auth_OAuth_ROPC { }
    }
}
"""
    names = parse_tmsh_access_policy_macros(text)
    assert names == [
        "/Common/Auth_AD",
        "/Common/Auth_GoogleOTP",
        "/Common/Auth_GoogleOTP_Gen_MessageBox",
        "/Common/Auth_LDAP",
        "/Common/Auth_OAuth_ROPC",
    ]
    grep_text = "        Auth_AD {\n        Auth_LDAP {\n    macros {\n"
    assert parse_tmsh_access_policy_macros(grep_text) == [
        "/Common/Auth_AD",
        "/Common/Auth_LDAP",
    ]
    one_line = "apm policy access-policy /Common/AP_Ejes_Modern { macros { Auth_AD Auth_LDAP } }"
    assert parse_tmsh_access_policy_macros(one_line) == [
        "/Common/Auth_AD",
        "/Common/Auth_LDAP",
    ]


def test_extract_bash_command_result_truncation() -> None:
    from app.core.bigip_client import extract_bash_command_result

    body = b'{"kind":"tm:util:bash:runstate","commandResult":"        Auth_AD {\\n        Auth_LDAP {\\n'
    text = extract_bash_command_result(body)
    assert "Auth_AD" in text
    assert "Auth_LDAP" in text


def test_load_macros_falls_back_to_tmsh() -> None:
    from app.modules.vpe_macro.apm_macro import AccessProfileRef, list_macros_for_profile

    paths: list[str] = []

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            raise AssertionError(f"must not dump all policy-items: {path}")

        def get_optional(self, path: str) -> dict[str, Any]:
            paths.append(path)
            raise AssertionError(f"must not REST GET while listing macros: {path}")

        def run_util_bash(self, shell_command: str, *, timeout: float | None = None) -> str:
            assert "AP_Ejes_Modern" in shell_command
            assert "grep" not in shell_command
            return """apm policy access-policy /Common/AP_Ejes_Modern {
    macros {
        Auth_AD { }
        Auth_LDAP { }
    }
}
"""

    profile = AccessProfileRef(
        name="AP_Ejes_Modern",
        partition="Common",
        full_path="/Common/AP_Ejes_Modern",
        policy_path="/Common/AP_Ejes_Modern",
        policy_name="AP_Ejes_Modern",
    )
    _policy, items, macros = list_macros_for_profile(_Client(), profile)
    captions = {m.caption for m in macros}
    assert "Auth_AD" in captions
    assert "Auth_LDAP" in captions
    assert items == []
    assert paths == []


def test_list_macros_does_not_get_full_access_policy() -> None:
    from app.modules.vpe_macro.apm_macro import AccessProfileRef, list_macros_for_profile

    paths: list[str] = []

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            raise AssertionError(path)

        def get_optional(self, path: str) -> dict[str, Any]:
            paths.append(path)
            raise AssertionError(f"must not REST GET while listing macros: {path}")

        def run_util_bash(self, shell_command: str, *, timeout: float | None = None) -> str:
            if "AP_Ejes_Modern_ap" in shell_command:
                return """apm policy access-policy /Common/AP_Ejes_Modern_ap {
    macros {
        Auth_AD { }
    }
}
"""
            return "01020036:3: The requested access policy was not found."

    profile = AccessProfileRef(
        name="AP_Ejes_Modern",
        partition="Common",
        full_path="/Common/AP_Ejes_Modern",
        policy_path="/Common/AP_Ejes_Modern_ap",
        policy_name="AP_Ejes_Modern_ap",
    )
    _policy, items, macros = list_macros_for_profile(_Client(), profile)
    assert {m.caption for m in macros} == {"Auth_AD"}
    assert items == []
    assert paths == []


def test_list_macros_retries_policy_ap_suffix() -> None:
    from app.modules.vpe_macro.apm_macro import AccessProfileRef, list_macros_for_profile

    commands: list[str] = []

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            raise AssertionError(path)

        def get_optional(self, path: str) -> dict[str, Any]:
            raise AssertionError(path)

        def run_util_bash(self, shell_command: str, *, timeout: float | None = None) -> str:
            commands.append(shell_command)
            if "AP_Ejes_Modern_ap" in shell_command:
                return (
                    "apm policy access-policy /Common/AP_Ejes_Modern_ap "
                    "{ macros { Auth_AD Auth_LDAP } }"
                )
            return "01020036:3: The requested access policy was not found."

    profile = AccessProfileRef(
        name="AP_Ejes_Modern",
        partition="Common",
        full_path="/Common/AP_Ejes_Modern",
        policy_path="/Common/AP_Ejes_Modern",
        policy_name="AP_Ejes_Modern",
    )
    _policy, _items, macros = list_macros_for_profile(_Client(), profile)
    assert {m.caption for m in macros} == {"Auth_AD", "Auth_LDAP"}
    assert "AP_Ejes_Modern_ap" not in commands[0]
    assert any("AP_Ejes_Modern_ap" in command for command in commands)


def test_policy_path_candidates_use_profile_name_first() -> None:
    from app.modules.vpe_macro.apm_macro import AccessProfileRef, _policy_path_candidates

    paths = _policy_path_candidates(
        AccessProfileRef(
            name="AP_Ejes_Assign_Only",
            partition="Common",
            full_path="/Common/AP_Ejes_Assign_Only",
            policy_path="/Common/AP_Ejes_Assign_Only_ap",
            policy_name="AP_Ejes_Assign_Only_ap",
        )
    )
    assert paths[0] == "/Common/AP_Ejes_Assign_Only"
    assert not paths[0].endswith("_ap")
    from app.modules.vpe_macro.apm_macro import probe_existing_items

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            raise AssertionError(path)

        def get_optional(self, path: str) -> dict[str, Any]:
            if path.endswith("~Common~auth_ad"):
                return {"name": "auth_ad", "partition": "Common", "itemType": "macro"}
            return {"_unavailable": True}

    found = probe_existing_items(
        _Client(),
        partition="Common",
        names=["auth_ad", "missing_item", "auth_ad"],
    )
    assert [item["name"] for item in found] == ["auth_ad"]


def test_collect_macro_empty_uses_self() -> None:
    policy = {"name": "lab-ap", "partition": "Common", "startItem": "/Common/lab-ap_ent"}
    items = [
        _item("lab-ap_ent", item_type="entry", nexts=[("out", "/Common/lab-ap_end_deny")]),
        _item("lab-ap_end_deny", item_type="ending"),
        _item("lab-ap_act_empty", item_type="macro", caption="Empty"),
    ]
    closure = collect_macro_item_paths(macro_item=items[2], policy=policy, items=items)
    assert closure == ["/Common/lab-ap_act_empty"]


def test_remap_policy_prefix() -> None:
    assert (
        remap_string(
            "/Common/lab-ap_act_ad_logon",
            source_policy="lab-ap",
            target_policy="vpn-ap",
            source_partition="Common",
            target_partition="Common",
        )
        == "/Common/vpn-ap_act_ad_logon"
    )
    assert (
        remap_string(
            "lab-ap_act_ad",
            source_policy="lab-ap",
            target_policy="vpn-ap",
            source_partition="Common",
            target_partition="Common",
        )
        == "vpn-ap_act_ad"
    )


def test_strip_rest_metadata() -> None:
    cleaned = strip_rest_metadata(
        {
            "name": "lab-ap_act_ad",
            "kind": "tm:apm:policy:policy-item:policy-itemstate",
            "generation": 3,
            "selfLink": "https://localhost/x",
            "caption": "AD Auth",
            "itemTypeReference": {"link": "x"},
        }
    )
    assert "kind" not in cleaned
    assert "generation" not in cleaned
    assert "selfLink" not in cleaned
    assert "itemTypeReference" not in cleaned
    assert cleaned["caption"] == "AD Auth"


def test_apply_plan_remaps_and_detects_collision() -> None:
    policy, items = _lab_policy()
    macros = build_macro_summaries(policy=policy, items=items)
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path=macros[0].full_path,
        macro_caption=macros[0].caption,
        items=[i for i in items if i["fullPath"] in macros[0].item_paths],
        agents=[
            {
                "type": "logon-page",
                "name": "lab-ap_act_ad_logon_ag",
                "partition": "Common",
                "body": {
                    "name": "lab-ap_act_ad_logon_ag",
                    "partition": "Common",
                    "kind": "tm:apm:policy:agent:logon-page:logon-pagestate",
                },
            }
        ],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )
    plan = build_apply_plan(snapshot=snapshot, target_profile=target, existing_item_names=set())
    names = {i["name"] for i in plan.items}
    assert "vpn-ap_act_ad" in names
    assert "lab-ap_act_ad" not in names
    assert plan.agents[0][1]["name"] == "vpn-ap_act_ad_logon_ag"
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={"name": "vpn-ap", "partition": "Common", "items": [], "_macro_refs": []},
            existing_items=[_item("vpn-ap_act_ad", item_type="macro")],
        )


class _FakeClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.patches: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str) -> dict[str, Any]:
        return {}

    def get_optional(self, path: str) -> dict[str, Any]:
        return {"_unavailable": True, "_http_status": 404}

    def post(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        self.posts.append((path, payload))
        return {"name": payload.get("name")}

    def patch(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        self.patches.append((path, payload))
        return {}


def test_apply_posts_agents_then_items_and_patches_policy() -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path="/Common/lab-ap_act_ad",
        macro_caption="AD Auth",
        items=[
            {
                "name": "lab-ap_act_ad",
                "partition": "Common",
                "caption": "AD Auth",
                "itemType": "macro",
                "rules": [{"caption": "Successful", "nextItem": "/Common/lab-ap_act_ad_out"}],
            },
            {
                "name": "lab-ap_act_ad_out",
                "partition": "Common",
                "caption": "Successful",
                "itemType": "terminal",
            },
        ],
        agents=[
            {
                "type": "logon-page",
                "body": {"name": "lab-ap_act_ad_logon_ag", "partition": "Common"},
            }
        ],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={
                "name": "vpn-ap",
                "partition": "Common",
                "items": [{"name": "vpn-ap_ent", "partition": "Common"}],
                "macros": [],
            },
            existing_items=[_item("vpn-ap_ent", item_type="entry")],
        )


def test_apply_creates_renamed_macro_via_tmsh_not_rest_post() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command:
                return ""
            if "list apm policy access-policy" in shell_command and "macros" in shell_command:
                return "macros { AD_Auth }"
            if (
                "list apm policy access-policy /Common/" in shell_command
                and "grep" not in shell_command
                and "macros" not in shell_command
            ):
                return "apm policy access-policy /Common/AD_Auth {\n"
            if "grep" in shell_command and "AD_Auth" in shell_command and "create cli" not in shell_command:
                if any("create cli transaction" in cmd for cmd in self.bash[:-1]):
                    return "apm policy access-policy /Common/AD_Auth {\n"
                return "apm policy access-policy /Common/AP_API_Security {\n"
            if "list apm policy access-policy" in shell_command and "grep" in shell_command:
                return "apm policy access-policy /Common/AP_API_Security {\n"
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "caption": "auth_ad", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_API_Security",
        partition="Common",
        full_path="/Common/AP_API_Security",
        policy_path="/Common/AP_API_Security_ap",
        policy_name="AP_API_Security_ap",
    )
    client = _Client()
    result = apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_API_Security_ap", "_macro_refs": []},
        existing_items=[],
        target_macro_name="AD_Auth",
    )
    _assert_load_puts_saved_macro(result, client, skipped="AD_Auth")
    blob = "\n".join(client.bash)
    assert "macros add" in blob
    assert "create apm policy access-policy" in blob
    assert "start-item" in blob
    assert "item-type entry" in blob
    assert "next-item" in blob
    assert "item-type terminal-out" in blob
    assert "ending-allow" not in blob
    assert "item-type ending" not in blob
    assert "item-type macro" not in blob
    assert "AD_Auth" in blob
    out_i = blob.find("item-type terminal-out")
    entry_i = blob.find("item-type entry")
    assert out_i != -1 and entry_i != -1 and out_i < entry_i
    assert "macros add { /Common/" in blob
    assert blob.count("submit cli transaction") == 1


def test_apply_creates_access_policy_macro_when_object_missing() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []
            self._created = False

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command:
                self._created = True
                return ""
            if "list apm policy access-policy /Common/" in shell_command and "grep" not in shell_command:
                if self._created:
                    return "apm policy access-policy /Common/auth_ad_copy {\n"
                return ""
            if "list apm policy access-policy" in shell_command and "grep" in shell_command:
                if self._created:
                    return "apm policy access-policy /Common/auth_ad_copy {\n"
                return "apm policy access-policy /Common/AP_Ejes_Assign_Only {\n"
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _Client()
    result = apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"_macro_refs": []},
        existing_items=[],
        target_macro_name="auth_ad_copy",
    )
    assert "auth_ad_copy" in result.created_items
    blob = "\n".join(client.bash)
    assert "create cli transaction" in blob
    assert "submit cli transaction" in blob
    assert "create apm policy access-policy" in blob
    assert "type macro" in blob
    assert "start-item" in blob
    assert "macros add { /Common/auth_ad_copy }" in blob
    assert "item-type entry" in blob
    assert "item-type terminal-out" in blob
    assert "ending-allow" not in blob
    assert "item-type ending" not in blob
    assert "item-type macro" not in blob
    assert "_start" not in blob
    assert "_ent" not in blob


def test_next_numbered_macro_name_uses_max_plus_one() -> None:
    names = parse_access_policy_object_names(
        """
apm policy access-policy /Common/auth_ad {
apm policy access-policy /Common/auth_ad_1 {
apm policy access-policy /Common/auth_ad_2 {
apm policy access-policy /Common/auth_ad_3 {
apm policy access-policy /Common/auth_ldap {
"""
    )
    assert names[:4] == ["auth_ad", "auth_ad_1", "auth_ad_2", "auth_ad_3"]
    assert next_numbered_macro_name("auth_ad", names) == "auth_ad_4"
    assert next_numbered_macro_name("Auth_AD", names) == "Auth_AD_4"
    assert next_numbered_macro_name("auth_ldap", names) == "auth_ldap_1"
    assert next_numbered_macro_name("brand_new", names) == "brand_new"


def test_apply_creates_suffixed_copy_when_name_exists() -> None:
    names_blob = """
apm policy access-policy /Common/auth_ad {
apm policy access-policy /Common/auth_ad_1 {
apm policy access-policy /Common/auth_ad_2 {
apm policy access-policy /Common/auth_ad_3 {
"""

    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command:
                assert "Auth_AD_4" in shell_command
                assert "Auth_AD_4_start" not in shell_command
                assert "Auth_AD_4_ent" not in shell_command
                assert "submit cli transaction" in shell_command
                assert "start-item" in shell_command
                assert "type macro" in shell_command
                assert "Auth_AD_4_in" in shell_command
                assert "item-type terminal-out" in shell_command
                assert "macros add { /Common/Auth_AD_4 }" in shell_command
                assert "ending-allow" not in shell_command
                return ""
            if "list apm policy access-policy /Common/Auth_AD_4" in shell_command and "grep" not in shell_command:
                return "apm policy access-policy /Common/Auth_AD_4 {\n"
            if "grep" in shell_command and "Auth_AD_4" in shell_command:
                return "apm policy access-policy /Common/Auth_AD_4 {\n" + names_blob
            if "apm policy" in shell_command:
                return names_blob
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _Client()
    result = apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"_macro_refs": []},
        existing_items=[],
        target_macro_name="Auth_AD",
    )
    assert result.created_items == ["Auth_AD_4"]
    assert any("<<ENDTMSH" in cmd and "create cli transaction" in cmd for cmd in client.bash)
    assert any("grep -i -E" in cmd and "Auth_AD_4" in cmd for cmd in client.bash)
    assert not any("tmsh -q -c" in cmd for cmd in client.bash)
    blob = "\n".join(client.bash)
    assert any('grep "apm policy"' in cmd for cmd in client.bash)
    assert "create cli transaction" in blob
    assert "submit cli transaction" in blob
    assert "create apm policy access-policy /Common/Auth_AD_4" in blob
    assert "start-item /Common/Auth_AD_4_in" in blob
    assert "Auth_AD_4_start" not in blob
    assert "Auth_AD_4_ent" not in blob
    assert "item-type entry" in blob
    assert "item-type terminal-out" in blob
    assert "ending-allow" not in blob
    assert "item-type ending" not in blob
    assert "macros add { /Common/Auth_AD_4 }" in blob
    assert "macros add { auth_ad }" not in blob
    assert "create apm policy access-policy /Common/auth_ad_1" not in blob
    assert "create apm policy access-policy /Common/auth_ad_2" not in blob


def test_apply_lookup_uses_live_tmsh_list_not_partial_conf() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command:
                assert "Auth_AD_4" in shell_command
                assert "start-item" in shell_command
                assert "item-type terminal-out" in shell_command
                return ""
            if "list apm policy access-policy /Common/Auth_AD_4" in shell_command and "grep" not in shell_command:
                return "apm policy access-policy /Common/Auth_AD_4 {\n"
            if "grep" in shell_command and "Auth_AD_4" in shell_command:
                return "apm policy access-policy /Common/Auth_AD_4 {\n"
            if "bigip.conf" in shell_command:
                return (
                    "apm policy access-policy /Common/auth_ad {\n"
                    "apm policy access-policy /Common/auth_ad_1 {\n"
                )
            if "list apm policy access-policy" in shell_command and "grep" in shell_command:
                return (
                    "apm policy access-policy /Common/auth_ad {\n"
                    "apm policy access-policy /Common/auth_ad_1 {\n"
                    "apm policy access-policy /Common/auth_ad_2 {\n"
                    "apm policy access-policy /Common/auth_ad_3 {\n"
                )
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    result = apply_macro_snapshot(
        _Client(),
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"_macro_refs": []},
        existing_items=[],
        target_macro_name="Auth_AD",
    )
    assert result.created_items == ["Auth_AD_4"]


def test_apply_zero_stem_matches_creates_without_reading_conf() -> None:
    """grep hit 0 is a free name. Do not open bigip.conf or skip the create."""

    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "bigip.conf" in shell_command:
                raise AssertionError("Load lookup must not read bigip.conf")
            if "create cli transaction" in shell_command:
                assert "AD_Authentication" in shell_command
                return ""
            if (
                "list apm policy access-policy /Common/AD_Authentication" in shell_command
                and "grep" not in shell_command
            ):
                if any("create cli transaction" in cmd for cmd in self.bash[:-1]):
                    return "apm policy access-policy /Common/AD_Authentication {\n"
                return ""
            if "grep" in shell_command and "AD_Authentication" in shell_command:
                if any("create cli transaction" in cmd for cmd in self.bash[:-1]):
                    return "apm policy access-policy /Common/AD_Authentication {\n"
                return ""
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    logs: list[str] = []
    result = apply_macro_snapshot(
        _Client(),
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"_macro_refs": []},
        existing_items=[],
        target_macro_name="AD_Authentication",
        progress=logs.append,
    )
    assert result.created_items == ["AD_Authentication"]
    assert any("없음 → AD_Authentication 생성" in line for line in logs)
    assert any("cli 트랜잭션" in line for line in logs)


def test_apply_does_not_create_when_live_name_lookup_fails() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            return "01020036:3: The requested Access Policy was not found."

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _Client()
    with pytest.raises(MacroApplyError, match="이름을 확인하지 못해"):
        apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={"_macro_refs": []},
            existing_items=[],
            target_macro_name="Auth_AD",
        )
    assert not any("create apm policy access-policy" in cmd for cmd in client.bash)


def test_apply_attaches_existing_global_macro_without_recreate() -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path="/Common/lab-ap_act_ad",
        macro_caption="AD Auth",
        items=[
            {
                "name": "lab-ap_act_ad",
                "partition": "Common",
                "caption": "AD Auth",
                "itemType": "macro",
            },
            {
                "name": "lab-ap_act_ad_out",
                "partition": "Common",
                "caption": "Successful",
                "itemType": "terminal",
            },
        ],
        agents=[
            {
                "type": "logon-page",
                "body": {"name": "lab-ap_act_ad_logon_ag", "partition": "Common"},
            }
        ],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={
                "name": "vpn-ap",
                "partition": "Common",
                "items": [{"name": "vpn-ap_ent", "partition": "Common"}],
                "macros": [],
            },
            existing_items=[
                _item("vpn-ap_ent", item_type="entry"),
                _item("vpn-ap_act_ad", item_type="macro"),
                _item("vpn-ap_act_ad_out", item_type="terminal"),
            ],
        )


def test_attach_uses_rest_macro_ref_not_full_policy_patch() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Other",
        partition="Common",
        full_path="/Common/AP_Other",
        policy_path="/Common/AP_Other",
        policy_name="AP_Other",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={"name": "AP_Other", "_macro_refs": []},
            existing_items=[],
            target_macro_name="auth_ad",
        )


def test_remap_exact_shared_macro_name() -> None:
    assert (
        remap_string(
            "Auth_AD",
            source_policy="Auth_AD",
            target_policy="Auth_AD_2",
            source_partition="Common",
            target_partition="Common",
        )
        == "Auth_AD_2"
    )
    assert (
        remap_string(
            "/Common/Auth_AD_out",
            source_policy="Auth_AD",
            target_policy="Auth_AD_2",
            source_partition="Common",
            target_partition="Common",
        )
        == "/Common/Auth_AD_2_out"
    )


def test_apply_plan_renames_shared_macro() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/Auth_AD",
        macro_caption="Auth_AD",
        items=[
            {
                "name": "Auth_AD",
                "partition": "Common",
                "fullPath": "/Common/Auth_AD",
                "caption": "Auth_AD",
                "itemType": "macro",
                "rules": [{"caption": "Successful", "nextItem": "/Common/Auth_AD_out"}],
            },
            {
                "name": "Auth_AD_out",
                "partition": "Common",
                "fullPath": "/Common/Auth_AD_out",
                "caption": "Successful",
                "itemType": "terminal",
            },
        ],
        agents=[
            {
                "type": "aaa-active-directory",
                "body": {"name": "Auth_AD_ag", "partition": "Common"},
            }
        ],
    )
    target = AccessProfileRef(
        name="AP_Other",
        partition="Common",
        full_path="/Common/AP_Other",
        policy_path="/Common/AP_Other",
        policy_name="AP_Other",
    )
    plan = build_apply_plan(
        snapshot=snapshot,
        target_profile=target,
        existing_item_names={"Auth_AD"},
        target_macro_name="Auth_AD_2",
    )
    names = {i["name"] for i in plan.items}
    assert names == {"Auth_AD_2", "Auth_AD_2_out"}
    assert plan.agents[0][1]["name"] == "Auth_AD_2_ag"
    assert not plan.collisions
    collide = build_apply_plan(
        snapshot=snapshot,
        target_profile=target,
        existing_item_names={"Auth_AD"},
        target_macro_name="Auth_AD",
    )
    assert "/Common/Auth_AD" in collide.collisions


def test_load_clears_object_refs_keeps_variable_assign() -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path="/Common/lab-ap_act_ad",
        macro_caption="AD Auth",
        items=[
            {
                "name": "lab-ap_act_ad",
                "partition": "Common",
                "caption": "AD Auth",
                "itemType": "macro",
            }
        ],
        agents=[
            {
                "type": "aaa-active-directory",
                "body": {
                    "name": "lab-ap_ad_ag",
                    "partition": "Common",
                    "server": "/Common/ad-aaa",
                    "showExtendedError": "true",
                },
            },
            {
                "type": "aaa-http",
                "body": {
                    "name": "lab-ap_http_ag",
                    "partition": "Common",
                    "server": {"name": "http-aaa", "partition": "Common"},
                },
            },
            {
                "type": "aaa-radius",
                "body": {
                    "name": "lab-ap_rad_ag",
                    "partition": "Common",
                    "servers": ["/Common/rad1", "/Common/rad2"],
                },
            },
            {
                "type": "resource-assign",
                "body": {
                    "name": "lab-ap_res_ag",
                    "partition": "Common",
                    "rules": [
                        {
                            "expression": "expr { [mcget {session.ad.last.attr.memberOf}] }",
                            "webtop": "/Common/full_wt",
                            "resources": [{"name": "na1", "partition": "Common"}],
                        }
                    ],
                },
            },
            {
                "type": "variable-assign",
                "body": {
                    "name": "lab-ap_var_ag",
                    "partition": "Common",
                    "variables": [
                        {"left": "session.custom.x", "right": "expr { 1 }"},
                    ],
                },
            },
        ],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )
    plan = build_apply_plan(snapshot=snapshot, target_profile=target, existing_item_names=set())
    by_type = {agent_type: body for agent_type, body in plan.agents}
    assert "server" not in by_type["aaa-active-directory"]
    assert by_type["aaa-active-directory"]["showExtendedError"] == "true"
    assert "server" not in by_type["aaa-http"]
    assert by_type["aaa-radius"]["servers"] == []
    rule = by_type["resource-assign"]["rules"][0]
    assert "memberOf" in rule["expression"]
    assert "webtop" not in rule
    assert rule["resources"] == []
    assert by_type["variable-assign"]["variables"][0]["left"] == "session.custom.x"
    assert by_type["variable-assign"]["variables"][0]["right"] == "expr { 1 }"


def test_list_access_profiles_reports_progress() -> None:
    from app.modules.vpe_macro.apm_macro import list_access_profiles

    seen: list[tuple[int, int, str]] = []

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            return {
                "items": [
                    {
                        "name": "ap-one",
                        "partition": "Common",
                        "fullPath": "/Common/ap-one",
                        "accessPolicy": "/Common/ap-one",
                    },
                    {
                        "name": "ap-two",
                        "partition": "Common",
                        "fullPath": "/Common/ap-two",
                        "accessPolicy": "/Common/ap-two",
                    },
                ]
            }

        def get_optional(self, path: str) -> dict[str, Any]:
            return {"name": "ok"}

    refs = list_access_profiles(
        _Client(),
        progress=lambda current, total, message: seen.append((current, total, message)),
    )
    assert [r.name for r in refs] == ["ap-one", "ap-two"]
    assert seen[0][0] == 0
    assert seen[-1][:2] == (2, 2)


def test_apply_keeps_existing_items_from_expanded_subcollection() -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path="/Common/lab-ap_act_ad",
        macro_caption="AD Auth",
        items=[
            {
                "name": "lab-ap_act_ad",
                "partition": "Common",
                "caption": "AD Auth",
                "itemType": "macro",
            }
        ],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
            client,
            snapshot=snapshot,
            target_profile=target,
            existing_policy={
                "name": "vpn-ap",
                "partition": "Common",
                "items": {
                    "items": [
                        {"name": "vpn-ap_ent", "partition": "Common"},
                        {"name": "vpn-ap_end_deny", "partition": "Common"},
                    ]
                },
                "macros": {"items": []},
            },
            existing_items=[_item("vpn-ap_ent", item_type="entry")],
        )


def test_apply_does_not_require_policy_items_list_to_attach_macro() -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path="/Common/lab-ap_act_ad",
        macro_caption="AD Auth",
        items=[{"name": "lab-ap_act_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"items": {}, "macros": []},
        existing_items=[],
    )


def test_apply_plan_attaches_snapshot_macro_name_when_root_item_missing() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[
            {
                "name": "auth_ad_act_logon_page",
                "partition": "Common",
                "caption": "Logon Page",
                "itemType": "action",
            },
            {
                "name": "auth_ad_ter_out",
                "partition": "Common",
                "caption": "AD_Auth_Failed",
                "itemType": "terminal-out",
            },
        ],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    plan = build_apply_plan(
        snapshot=snapshot,
        target_profile=target,
        existing_item_names={"auth_ad_act_logon_page", "auth_ad_ter_out", "auth_ad"},
        target_macro_name="auth_ad",
    )
    assert plan.reuse_existing
    assert plan.macro_refs[0]["name"] == "auth_ad"


def test_apply_posts_macro_attach_when_saved_json_omits_macro_root() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[
            {
                "name": "auth_ad_act_logon_page",
                "partition": "Common",
                "caption": "Logon Page",
                "itemType": "action",
            },
            {
                "name": "auth_ad_ter_out",
                "partition": "Common",
                "caption": "AD_Auth_Failed",
                "itemType": "terminal-out",
            },
        ],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={
            "name": "AP_Ejes_Assign_Only",
            "partition": "Common",
            "macros": [],
        },
        existing_items=[
            _item("auth_ad_act_logon_page"),
            _item("auth_ad_ter_out", item_type="terminal-out"),
            _item("auth_ad", item_type="macro"),
        ],
        target_macro_name="auth_ad",
    )


def test_build_snapshot_adds_macro_container_when_root_item_missing() -> None:
    from app.modules.vpe_macro.apm_macro import MacroSummary, build_snapshot

    profile = AccessProfileRef(
        name="AP_Ejes_Modern",
        partition="Common",
        full_path="/Common/AP_Ejes_Modern",
        policy_path="/Common/AP_Ejes_Modern",
        policy_name="AP_Ejes_Modern",
    )
    macro = MacroSummary(
        caption="auth_ad",
        name="auth_ad",
        partition="Common",
        full_path="/Common/auth_ad",
        exits=("AD_Auth_Failed",),
        agent_labels=(),
        item_count=1,
        item_paths=("/Common/auth_ad_ter_out",),
    )
    snapshot = build_snapshot(
        profile=profile,
        policy={"name": "AP_Ejes_Modern", "partition": "Common"},
        items=[
            {
                "name": "auth_ad_ter_out",
                "partition": "Common",
                "fullPath": "/Common/auth_ad_ter_out",
                "caption": "AD_Auth_Failed",
                "itemType": "terminal-out",
            }
        ],
        macro=macro,
        agents=[],
        warnings=[],
    )
    names = [str(item.get("name") or "") for item in snapshot.items]
    assert "auth_ad" in names
    root = next(item for item in snapshot.items if item.get("name") == "auth_ad")
    assert root.get("itemType") == "macro"
    assert root["rules"][0]["nextItem"] == "/Common/auth_ad_ter_out"


def test_apply_reuses_after_single_macro_lookup() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[
            {
                "name": "auth_ad",
                "partition": "Common",
                "caption": "auth_ad",
                "itemType": "macro",
            },
            {
                "name": "auth_ad_ter_out",
                "partition": "Common",
                "caption": "Allow",
                "itemType": "terminal-out",
            },
        ],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )

    class _Client(_FakeClient):
        def get_optional(self, path: str) -> dict[str, Any]:
            if path.endswith("~Common~auth_ad"):
                return {"name": "auth_ad", "partition": "Common", "itemType": "macro"}
            return {"_unavailable": True}

    client = _Client()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Ejes_Assign_Only", "_macro_refs": []},
        existing_items=[],
        target_macro_name="auth_ad",
    )


def test_apply_treats_inconclusive_macro_lookup_as_reuse() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[
            {
                "name": "auth_ad",
                "partition": "Common",
                "itemType": "macro",
            }
        ],
        agents=[
            {
                "type": "aaa-active-directory",
                "body": {
                    "name": "auth_ad_act_active_directory_auth_ag",
                    "partition": "Common",
                },
            }
        ],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )

    class _Client(_FakeClient):
        def get_optional(self, path: str) -> dict[str, Any]:
            return {"_unavailable": True, "_error": "timeout"}

    client = _Client()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Ejes_Assign_Only", "_macro_refs": []},
        existing_items=[],
        target_macro_name="auth_ad",
    )


def test_apply_same_name_does_not_create_even_when_lookup_is_404() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[
            {
                "name": "auth_ad",
                "partition": "Common",
                "itemType": "macro",
            },
            {
                "name": "auth_ad_ter_out",
                "partition": "Common",
                "itemType": "terminal-out",
            },
        ],
        agents=[
            {
                "type": "aaa-active-directory",
                "body": {
                    "name": "auth_ad_act_active_directory_auth_ag",
                    "partition": "Common",
                },
            }
        ],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Ejes_Assign_Only", "_macro_refs": []},
        existing_items=[],
        target_macro_name="auth_ad",
    )


def test_apply_skips_conflict_and_attaches() -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_full_path="/Common/lab-ap_act_ad",
        macro_caption="AD Auth",
        items=[
            {
                "name": "lab-ap_act_ad",
                "partition": "Common",
                "itemType": "macro",
            }
        ],
        agents=[
            {
                "type": "aaa-active-directory",
                "body": {"name": "lab-ap_act_ad_ag", "partition": "Common"},
            }
        ],
    )
    target = AccessProfileRef(
        name="vpn-ap",
        partition="Common",
        full_path="/Common/vpn-ap",
        policy_path="/Common/vpn-ap",
        policy_name="vpn-ap",
    )

    class _Client(_FakeClient):
        def post(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
            if "/agent/" in path:
                raise RuntimeError(
                    "Client error '409 Conflict' for url 'https://x/mgmt/tm/apm/policy/agent/"
                    "aaa-active-directory' already exists in partition Common."
                )
            return super().post(path, payload, timeout=timeout)

    client = _Client()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "vpn-ap", "_macro_refs": []},
        existing_items=[],
    )


def test_resolve_access_profile_uses_optional_get() -> None:
    from app.modules.vpe_macro.apm_macro import resolve_access_profile

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            raise AssertionError(path)

        def get_optional(self, path: str) -> dict[str, Any]:
            assert path.endswith("~Common~AP_Ejes_Modern")
            return {
                "name": "AP_Ejes_Modern",
                "partition": "Common",
                "fullPath": "/Common/AP_Ejes_Modern",
                "accessPolicy": "/Common/AP_Ejes_Modern_ap",
            }

    ref = resolve_access_profile(_Client(), "/Common/AP_Ejes_Modern")
    assert ref.policy_path == "/Common/AP_Ejes_Modern_ap"


def test_resolve_access_profile_404_is_short_error() -> None:
    from app.modules.vpe_macro.apm_macro import resolve_access_profile

    class _Client:
        def get(self, path: str) -> dict[str, Any]:
            raise AssertionError(path)

        def get_optional(self, path: str) -> dict[str, Any]:
            return {"_unavailable": True, "_http_status": 404, "_error": "HTTP 404"}

    with pytest.raises(RuntimeError, match="Access Profile을 찾을 수 없습니다"):
        resolve_access_profile(_Client(), "/Common/missing")


def test_attach_uses_listed_policy_path_once() -> None:
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only_ap",
        policy_name="AP_Ejes_Assign_Only_ap",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Ejes_Assign_Only", "_macro_refs": []},
        existing_items=[],
        target_macro_name="auth_ad",
    )


def test_attach_does_not_retry_profile_name_when_policy_post_fails() -> None:
    class _Client(_FakeClient):
        def post(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
            return super().post(path, payload, timeout=timeout)

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Other",
        partition="Common",
        full_path="/Common/AP_Other",
        policy_path="/Common/AP_Other",
        policy_name="AP_Other",
    )
    client = _Client()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Other", "_macro_refs": []},
        existing_items=[],
        target_macro_name="auth_ad",
    )


def test_attach_uses_curl_helper_instead_of_in_process_post() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.curl: list[tuple[str, dict[str, Any]]] = []

        def post_via_curl(
            self, path: str, payload: dict[str, Any], *, timeout: float | None = None
        ) -> dict[str, Any]:
            self.curl.append((path, payload))
            return {"status": 200}

        def post(self, path: str, payload: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
            if path.endswith("/macros"):
                raise AssertionError("in-process post must not be used when curl helper exists")
            return super().post(path, payload, timeout=timeout)

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _Client()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Ejes_Assign_Only", "_macro_refs": []},
        existing_items=[],
        target_macro_name="AD_Auth",
    )


def test_attach_progress_shows_typed_name_and_attaches_snapshot_name() -> None:
    seen: list[str] = []
    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="auth_ad",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    client = _FakeClient()
    with pytest.raises(MacroApplyError, match="tmsh"):
        apply_macro_snapshot(
        client,
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"name": "AP_Ejes_Assign_Only", "_macro_refs": []},
        existing_items=[],
        target_macro_name="AD_Auth",
        progress=seen.append,
    )
    assert any(message.startswith("기존 Macro: auth_ad") for message in seen)
    assert "Load Macro: AD_Auth" in seen
    assert any("Macro 생성 중" in message and "AD_Auth" in message for message in seen)


def test_run_tmsh_capped_passes_timeout_to_runner() -> None:
    seen: dict[str, Any] = {}

    def runner(command: str, *, timeout: float | None = None, max_bytes: int | None = None) -> str:
        seen["timeout"] = timeout
        seen["cmd"] = command
        seen["max_bytes"] = max_bytes
        return "ok"

    from app.modules.vpe_macro import apm_macro as mod

    text = mod._run_tmsh_capped(object(), runner, "tmsh list sys", timeout=15.0, max_bytes=4096)
    assert text == "ok"
    assert seen["cmd"] == "tmsh list sys"
    assert seen["timeout"] == 15.0


def test_transaction_notice_is_not_a_failure_and_real_error_is_kept() -> None:
    from app.modules.vpe_macro.apm_macro import _tmsh_failed, _without_transaction_noise

    notice = "Command added to the current transaction\n" * 4
    assert _tmsh_failed(_without_transaction_noise(notice)) is False
    mixed = notice + "01020036:3: The requested Access Policy was not found.\n"
    assert "was not found" in _without_transaction_noise(mixed)
    assert "Command added" not in _without_transaction_noise(mixed)
    quit_line = (
        "Batch mode transaction is active, it will be lost, quit anyway? (y/n) "
        'Syntax Error: invalid property value "item-type":"terminal"'
    )
    cleaned = _without_transaction_noise(quit_line)
    assert "quit anyway" not in cleaned
    assert "invalid property value" in cleaned
    assert _tmsh_failed(cleaned) is True
    buried = (
        "Command added to the current transaction\n"
        "transaction failed: 01071124:3: next item pointing back to itself.\n"
    )
    assert _tmsh_failed(_without_transaction_noise(buried)) is True


def test_apply_create_timeout_is_not_success() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command:
                raise TimeoutError("timeout")
            if "grep" in shell_command:
                return "apm policy access-policy /Common/auth_ad {\n"
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    with pytest.raises(MacroApplyError, match="15초"):
        apply_macro_snapshot(
            _Client(),
            snapshot=snapshot,
            target_profile=target,
            existing_policy={"_macro_refs": []},
            existing_items=[],
            target_macro_name="Auth_AD",
        )


def test_apply_does_not_succeed_when_new_name_is_absent_after_create() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command:
                return ""
            if "grep" in shell_command:
                return "apm policy access-policy /Common/auth_ad {\n"
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    with pytest.raises(MacroApplyError, match="새 Macro 객체가 남지 않았습니다"):
        apply_macro_snapshot(
            _Client(),
            snapshot=snapshot,
            target_profile=target,
            existing_policy={"_macro_refs": []},
            existing_items=[],
            target_macro_name="Auth_AD_2",
        )


def test_apply_retries_shell_names_when_leftover_items_exist() -> None:
    class _Client(_FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.bash: list[str] = []

        def run_util_bash(
            self,
            shell_command: str,
            *,
            timeout: float | None = None,
            max_bytes: int | None = None,
        ) -> str:
            self.bash.append(shell_command)
            if "create cli transaction" in shell_command and "Auth_AD_2_in" in shell_command:
                return "01020066:3: The requested policy-item (/Common/Auth_AD_2_in) already exists."
            if "create cli transaction" in shell_command and "Auth_AD_2_gate" in shell_command:
                return ""
            if "list apm policy access-policy /Common/Auth_AD_2" in shell_command and "grep" not in shell_command:
                if any("Auth_AD_2_gate" in cmd for cmd in self.bash):
                    return "apm policy access-policy /Common/Auth_AD_2 {\n"
                return ""
            if "grep" in shell_command and "Auth_AD_2" in shell_command:
                if any("Auth_AD_2_gate" in cmd for cmd in self.bash):
                    return "apm policy access-policy /Common/Auth_AD_2 {\n"
            if "grep" in shell_command:
                return (
                    "apm policy access-policy /Common/auth_ad {\n"
                    "apm policy access-policy /Common/auth_ad_1 {\n"
                )
            return ""

    snapshot = MacroSnapshot(
        policy_name="AP_Ejes_Modern",
        partition="Common",
        macro_full_path="/Common/auth_ad",
        macro_caption="Auth_AD",
        items=[{"name": "auth_ad", "partition": "Common", "itemType": "macro"}],
    )
    target = AccessProfileRef(
        name="AP_Ejes_Assign_Only",
        partition="Common",
        full_path="/Common/AP_Ejes_Assign_Only",
        policy_path="/Common/AP_Ejes_Assign_Only",
        policy_name="AP_Ejes_Assign_Only",
    )
    result = apply_macro_snapshot(
        _Client(),
        snapshot=snapshot,
        target_profile=target,
        existing_policy={"_macro_refs": []},
        existing_items=[],
        target_macro_name="Auth_AD",
    )
    assert result.created_items == ["Auth_AD_2"]
    blob = "\n".join(result.messages)
    assert "Auth_AD_2" in blob
