from pathlib import Path

from app.modules.initial_setup.generator import NetworkProfile, generate_initial_setup_artifacts


def test_initial_setup_artifacts(tmp_path: Path) -> None:
    profile = NetworkProfile(
        hostname="lab-bigip-01.example.invalid",
        mgmt_ip="203.0.113.10",
        mgmt_netmask="255.255.255.0",
        gateway="203.0.113.1",
    )
    paths = generate_initial_setup_artifacts(profile, tmp_path)
    assert any(p.name == "tmsh_initial.tcl" for p in paths)
