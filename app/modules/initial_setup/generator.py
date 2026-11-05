from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class NetworkProfile(BaseModel):
    hostname: str
    mgmt_ip: str
    mgmt_netmask: str
    gateway: str
    dns_servers: list[str] = Field(default_factory=list)
    ntp_servers: list[str] = Field(default_factory=list)
    vlans: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("hostname")
    @classmethod
    def hostname_lower(cls, value: str) -> str:
        return value.lower()


def generate_initial_setup_artifacts(
    profile: NetworkProfile,
    output_dir: Path,
    *,
    platform_type: str = "tmos_ve",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, content in [
        ("setup_design.md", _render_design_md(profile, platform_type)),
        ("tmsh_initial.tcl", _render_tmsh(profile)),
        ("validation_checklist.md", _render_checklist(profile)),
        ("deployment_profile.yaml", yaml.safe_dump(profile.model_dump(), sort_keys=False)),
    ]:
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)

    return written


def _render_design_md(profile: NetworkProfile, platform_type: str) -> str:
    return f"""# initial setup design

platform: {platform_type}
hostname: {profile.hostname}
mgmt: {profile.mgmt_ip}/{profile.mgmt_netmask}
gateway: {profile.gateway}
"""


def _render_tmsh(profile: NetworkProfile) -> str:
    lines = [f"sys global-settings hostname {profile.hostname}"]
    for vlan in profile.vlans:
        lines.append(f"net vlan {vlan.get('name', 'vlan1')} {{ tag {vlan.get('tag', 0)} }}")
    return "\n".join(lines) + "\n"


def _render_checklist(profile: NetworkProfile) -> str:
    return f"# validation checklist\n\n- [ ] hostname {profile.hostname}\n"
