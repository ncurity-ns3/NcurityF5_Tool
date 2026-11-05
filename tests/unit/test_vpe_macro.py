from pathlib import Path

from app.modules.vpe_macro.generator import VpeMacroRequest, generate_vpe_macro_artifacts


def test_vpe_macro_ad(tmp_path: Path) -> None:
    req = VpeMacroRequest(auth_method="ad", group_mappings={"lab-group-01": "webtop"})
    paths = generate_vpe_macro_artifacts(req, tmp_path)
    assert (tmp_path / "apply_commands.txt").exists()
