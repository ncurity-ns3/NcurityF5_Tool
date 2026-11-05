from pathlib import Path

from app.core.redaction import redact_data
from app.modules.vpe_macro.apm_macro import MacroSnapshot
from app.modules.vpe_macro.store import MacroSnapshotStore


def test_store_roundtrip_redacts_password(tmp_path: Path) -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_caption="AD Auth",
        macro_full_path="/Common/lab-ap_act_ad",
        access_profile="/Common/lab-ap",
        source_host="203.0.113.10",
        items=[
            {
                "name": "lab-ap_act_ad",
                "caption": "AD Auth",
                "itemType": "macro",
                "password": "should-not-remain",
            }
        ],
        agents=[
            {
                "type": "logon-page",
                "body": {"name": "lab-ap_act_ad_logon_ag", "password": "secret"},
            }
        ],
    )
    store = MacroSnapshotStore(tmp_path)
    path = store.save(snapshot, "AD Auth")
    loaded = store.load(path)
    text = path.read_text(encoding="utf-8")
    assert "should-not-remain" not in text
    assert "secret" not in text
    assert loaded.items[0]["password"] == "[REDACTED]"
    assert loaded.agents[0]["body"]["password"] == "[REDACTED]"
    listed = store.list_saved()
    assert listed[0].caption == "AD Auth"


def test_store_save_to_path(tmp_path: Path) -> None:
    snapshot = MacroSnapshot(
        policy_name="lab-ap",
        partition="Common",
        macro_caption="Auth_AD",
        macro_full_path="/Common/Auth_AD",
        items=[{"name": "Auth_AD", "itemType": "macro"}],
    )
    store = MacroSnapshotStore(tmp_path)
    dest = tmp_path / "custom" / "Auth_AD.json"
    path = store.save_to_path(snapshot, dest)
    assert path == dest
    loaded = store.load(path)
    assert loaded.macro_caption == "Auth_AD"
    assert loaded.items[0]["name"] == "Auth_AD"


def test_snapshot_from_dict_ignores_unknown_format_payload_shape() -> None:
    data = redact_data(
        {
            "format": "ncurity-apm-macro-v1",
            "policy_name": "lab-ap",
            "items": [{"name": "x"}],
            "agents": [],
        }
    )
    snap = MacroSnapshot.from_dict(data)
    assert snap.policy_name == "lab-ap"
    assert snap.items[0]["name"] == "x"
