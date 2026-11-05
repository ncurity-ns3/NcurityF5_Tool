from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class VpeMacroRequest(BaseModel):
    auth_method: Literal["ad", "radius", "oauth", "saml"]
    resource_model: Literal["by_group", "by_account"] = "by_group"
    mfa_methods: list[str] = Field(default_factory=list)
    irule_required: bool = False
    group_mappings: dict[str, str] = Field(default_factory=dict)


def generate_vpe_macro_artifacts(request: VpeMacroRequest, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    mapping = [
        ("vpe_design.md", f"# vpe design\n\nauth: {request.auth_method}\n"),
        ("macro_config_template.yaml", yaml.safe_dump(_template_body(request), sort_keys=False)),
        ("apply_commands.txt", _render_commands(request)),
        ("verification_procedure.md", _render_verification(request)),
    ]
    for name, content in mapping:
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)

    if request.irule_required:
        path = output_dir / "irule_template.tcl"
        path.write_text("# skeleton irule\n", encoding="utf-8")
        written.append(path)

    return written


def _template_body(request: VpeMacroRequest) -> dict:
    return {
        "auth": {"method": request.auth_method},
        "resource": {"model": request.resource_model, "mappings": request.group_mappings},
        "mfa": request.mfa_methods,
    }


def _render_commands(request: VpeMacroRequest) -> str:
    lines = [f"# auth: {request.auth_method}"]
    if request.auth_method == "ad":
        lines.append("tmsh create apm aaa active-directory lab-ad-profile { }")
    return "\n".join(lines) + "\n"


def _render_verification(request: VpeMacroRequest) -> str:
    return f"# verify {request.auth_method} / {request.resource_model}\n"
