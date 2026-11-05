from pathlib import Path

from app.modules.os_upgrade.checklist import config_path_for_phase, load_phase_config


def test_pre_config_loads_from_yaml() -> None:
    cfg = load_phase_config("pre")
    assert cfg.phase == "pre"
    assert cfg.preset == "os_upgrade_pre"
    assert "common" in cfg.categories
    assert "ltm" in cfg.categories
    assert cfg.perform_ucs_backup is True
    ids = {item.id for item in cfg.items}
    assert "sys_version" in ids
    assert "ha_status" in ids


def test_post_config_ucs_disabled() -> None:
    cfg = load_phase_config("post")
    assert cfg.phase == "post"
    assert cfg.perform_ucs_backup is False
    ids = {item.id for item in cfg.items}
    assert "target_version" in ids


def test_config_files_exist() -> None:
    pre = config_path_for_phase("pre")
    post = config_path_for_phase("post")
    assert pre.is_file()
    assert post.is_file()
    assert pre.name == "os_upgrade_pre.yaml"
    assert post.name == "os_upgrade_post.yaml"
