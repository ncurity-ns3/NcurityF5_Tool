import json

from app.modules.os_upgrade.overview_paths import new_job_workspace, report_path


def test_new_job_workspace_dated_label(tmp_path) -> None:
    ws, folder = new_job_workspace(
        tmp_path,
        "Customer A",
        folder_name="20260523-120000_customer-a",
    )
    assert ws == tmp_path / "20260523-120000_customer-a"
    meta = json.loads((ws / "job_meta.json").read_text(encoding="utf-8"))
    assert meta["label"] == "Customer_A"
    assert meta["folder"] == "20260523-120000_customer-a"
    assert report_path(ws, "device_overview") == ws / "device_overview.html"
    assert report_path(ws, "pre_checklist") == ws / "pre_checklist.html"
