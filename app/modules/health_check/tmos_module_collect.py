from __future__ import annotations

import re
from typing import Any

from app.core.bigip_client import BigipClient
from app.modules.health_check.apm_parse import (
    apm_license_not_available,
    parse_apm_access_info_total,
    parse_apm_license_available_ccu,
    parse_apm_license_connectivity,
)


def _rest_or_bash(
    client: BigipClient,
    path: str,
    bash_cmd: str,
    *,
    timeout: float = 90.0,
) -> dict[str, Any]:
    rest = client.get_optional(path)
    if not rest.get("_unavailable"):
        return rest
    try:
        stdout = client.run_util_bash(bash_cmd, timeout=timeout)
        text = (stdout or "").strip()
        if text and "syntax error" not in text.lower():
            return {
                "_source": "bash",
                "_bash_cmd": bash_cmd,
                "bash_stdout": text[:8000],
                "list_count": _estimate_tmsh_list_count(text),
            }
    except Exception as exc:  # noqa: BLE001
        rest = dict(rest)
        rest["_bash_error"] = str(exc)[:160]
    return rest


def _estimate_tmsh_list_count(text: str) -> int:
    """Rough count of named objects in tmsh list output."""
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.search(r"\b\{\s*$", s) or (
            not s.startswith("}") and "{" in s and not s.startswith("ltm ")
        ):
            count += 1
    return count


def collect_ltm_data(client: BigipClient) -> dict[str, Any]:
    return {
        "pools": client.get_pool_summary(),
        "virtual_servers": client.get_optional("/tm/ltm/virtual"),
        "nodes": client.get_optional("/tm/ltm/node"),
    }


def _collect_apm_sessions(client: BigipClient) -> dict[str, Any]:
    cmd = "tmsh show apm access-info 2>/dev/null | grep -i Total"
    try:
        stdout = client.run_util_bash(cmd, timeout=60.0)
        text = (stdout or "").strip()
        total = parse_apm_access_info_total(text)
        if total is not None:
            return {
                "_source": "bash",
                "metric": "session_total",
                "value": total,
                "_bash_cmd": cmd,
                "bash_stdout": text[:500],
            }
        if text and "syntax error" not in text.lower():
            return {
                "_source": "bash",
                "metric": "session_total",
                "_bash_cmd": cmd,
                "bash_stdout": text[:500],
                "_parse_error": "Total 줄에서 숫자 미확인",
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "_unavailable": True,
            "_path": "/apm/session-total",
            "_error": str(exc)[:160],
        }
    rest = client.get_optional("/tm/apm/session")
    if not rest.get("_unavailable"):
        items = rest.get("items")
        if isinstance(items, list):
            return {
                **rest,
                "metric": "session_total",
                "value": len(items),
            }
    return {
        "_unavailable": True,
        "_path": "/apm/session-total",
        "_error": "access-info Total 파싱 실패",
    }


def _collect_apm_license(client: BigipClient) -> dict[str, Any]:
    cmd = "tmsh show apm license 2>/dev/null"
    try:
        stdout = client.run_util_bash(cmd, timeout=60.0)
        text = (stdout or "").strip()
        if apm_license_not_available(text):
            return {
                "_unavailable": True,
                "_path": "/apm/license",
                "_error": "APM 미사용 (show apm license N/A)",
            }
        conn_display, conn_total, conn_current = parse_apm_license_connectivity(text)
        available, licensed, in_use = parse_apm_license_available_ccu(text)
        if conn_total is not None:
            detail_parts = [f"Total connectivity sessions {conn_display}"]
            if conn_current is not None:
                detail_parts.append(f"Current {conn_current}")
            return {
                "_source": "bash",
                "metric": "license_ccu",
                "connectivity_total": conn_display,
                "available_ccu": conn_total,
                "licensed_ccu": conn_total,
                "in_use_ccu": conn_current,
                "value": conn_total,
                "_bash_cmd": cmd,
                "detail": ", ".join(detail_parts),
                "bash_stdout": text[:800],
            }
        if available is not None:
            detail_parts: list[str] = []
            if licensed is not None:
                detail_parts.append(f"Licensed CCU {licensed}")
            if in_use is not None:
                detail_parts.append(f"In use {in_use}")
            return {
                "_source": "bash",
                "metric": "license_ccu",
                "available_ccu": available,
                "licensed_ccu": licensed,
                "in_use_ccu": in_use,
                "value": available,
                "_bash_cmd": cmd,
                "detail": ", ".join(detail_parts) or "tmsh show apm license",
                "bash_stdout": text[:800],
            }
        if text:
            return {
                "_source": "bash",
                "metric": "license_ccu",
                "_bash_cmd": cmd,
                "bash_stdout": text[:800],
                "_parse_error": "total connectivity sessions 미확인",
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "_unavailable": True,
            "_path": "/apm/license",
            "_error": str(exc)[:160],
        }
    return {
        "_unavailable": True,
        "_path": "/apm/license",
        "_error": "show apm license — CCU 파싱 실패",
    }


def collect_apm_data(client: BigipClient) -> dict[str, Any]:
    return {
        "access_profiles": _rest_or_bash(
            client,
            "/tm/apm/profile/access",
            "tmsh list apm profile access 2>/dev/null",
        ),
        "sessions": _collect_apm_sessions(client),
        "license": _collect_apm_license(client),
    }


def collect_awaf_data(client: BigipClient) -> dict[str, Any]:
    policies = client.get_optional("/tm/asm/policies")
    if policies.get("_unavailable"):
        policies = _rest_or_bash(
            client,
            "/tm/asm/policy",
            "tmsh list asm policy 2>/dev/null",
        )
    sig = _rest_or_bash(
        client,
        "/tm/asm/signature-update",
        "tmsh show asm signature-update 2>/dev/null",
    )
    return {"policies": policies, "signature_update": sig}
