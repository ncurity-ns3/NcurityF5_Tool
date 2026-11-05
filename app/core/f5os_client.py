from __future__ import annotations

from typing import Any

import httpx

from app.core.redaction import redact_data

YANG_DATA_JSON = "application/yang-data+json"


def format_f5os_summary(data: dict[str, Any]) -> str:
    """human-readable one-line summary for test connection (no raw json dump)."""
    if not data:
        return "platform connected"
    if data.get("ietf-restconf:restconf"):
        return "RESTCONF — platform OK"
    block = data.get("openconfig-platform:components")
    if isinstance(block, dict):
        comps = block.get("component", [])
        if isinstance(comps, list):
            names = [
                str(c.get("name"))
                for c in comps[:5]
                if isinstance(c, dict) and c.get("name")
            ]
            if names:
                return f"platform OK — {', '.join(names)}"
    state = data.get("openconfig-system:system")
    if isinstance(state, dict):
        hostname = state.get("state", {}).get("hostname") if isinstance(state.get("state"), dict) else None
        if hostname:
            return f"platform OK — {hostname}"
    return "platform OK"


class F5osClient:
    """read-only f5os rest client (rseries) — /api or :8888/restconf per F5 docs."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        verify_tls: bool = False,
        timeout: float = 120.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.timeout = timeout
        self._token: str | None = None
        self._use_restconf = port == 8888

    def _base_url(self) -> str:
        return f"https://{self.host}:{self.port}"

    def _api_prefix(self) -> str:
        return "/restconf" if self._use_restconf else "/api"

    def _default_headers(self) -> dict[str, str]:
        headers = {"Content-Type": YANG_DATA_JSON, "Accept": YANG_DATA_JSON}
        if self._token:
            headers["X-Auth-Token"] = self._token
        return headers

    def authenticate(self) -> dict[str, Any]:
        """basic auth to /api (or /restconf) — token returned in X-Auth-Token header."""
        url = f"{self._base_url()}{self._api_prefix()}"
        with httpx.Client(verify=self.verify_tls, timeout=self.timeout) as client:
            response = client.get(
                url,
                auth=(self.username, self.password),
                headers={"Content-Type": YANG_DATA_JSON, "Accept": YANG_DATA_JSON},
            )
            response.raise_for_status()
            token = response.headers.get("x-auth-token") or response.headers.get(
                "X-Auth-Token"
            )
            if not token:
                raise RuntimeError("F5OS: login ok but X-Auth-Token header missing")
            self._token = token
            if response.content:
                return redact_data(response.json())
            return {"status": "authenticated"}

    def get(self, path: str) -> dict[str, Any]:
        if not self._token:
            self.authenticate()
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self._base_url()}{path}"
        with httpx.Client(verify=self.verify_tls, timeout=self.timeout) as client:
            response = client.get(url, headers=self._default_headers())
            response.raise_for_status()
            if not response.content:
                return {}
            return redact_data(response.json())

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._token:
            self.authenticate()
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self._base_url()}{path}"
        with httpx.Client(verify=self.verify_tls, timeout=self.timeout) as client:
            response = client.post(
                url,
                headers=self._default_headers(),
                json=body or {},
            )
            response.raise_for_status()
            if not response.content:
                return {}
            return redact_data(response.json())

    def _extract_cli_text(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if not isinstance(payload, dict):
            return ""
        for key in (
            "output",
            "stdout",
            "result",
            "text",
            "data",
            "f5-cli:output",
            "f5-system-cli:output",
        ):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for value in payload.values():
            text = self._extract_cli_text(value)
            if text:
                return text
        return ""

    def _cli_exec_attempts(self, command: str) -> list[tuple[str, dict[str, Any]]]:
        """RPC paths and bodies for F5OS Management CLI (admin context)."""
        prefix = self._api_prefix()
        inputs: list[dict[str, Any]] = [
            {"command": command},
            {"commands": command},
            {"commands": [command]},
            {"command": command, "context": "admin"},
            {"command": command, "cli-context": "admin"},
            {"command": command, "user": "admin"},
        ]
        attempts: list[tuple[str, dict[str, Any]]] = []
        for path, wrapper in (
            (f"{prefix}/operations/f5-system-cli:exec", "f5-system-cli:input"),
            (f"{prefix}/operations/f5-cli:exec", "f5-cli:input"),
            (f"{prefix}/operations/ietf-netconf:exec-command", "ietf-netconf:input"),
        ):
            for inp in inputs:
                attempts.append((path, {wrapper: inp}))
        return attempts

    def run_show_command(self, command: str) -> str:
        """Run one F5OS show command; returns first non-empty CLI text."""
        return self.run_admin_show_command(command)

    def run_admin_show_command(self, command: str) -> str:
        """
        F5OS Management CLI (same as `su admin` shell). Tries exec RPC variants;
        returns empty when CLI-over-REST is unavailable or command is rejected.
        """
        if not self._token:
            self.authenticate()
        for path, body in self._cli_exec_attempts(command):
            try:
                data = self.post(path, body)
            except httpx.HTTPError:
                continue
            text = self._extract_cli_text(data)
            if text:
                return text
        return ""

    def first_admin_show(self, *commands: str) -> str:
        """Try command aliases; first output wins (e.g. show vlan vs show vlans)."""
        for cmd in commands:
            text = self.run_admin_show_command(cmd)
            if text.strip():
                return text
        return ""

    def _overview_paths(self) -> list[str]:
        prefix = self._api_prefix()
        return [
            f"{prefix}/data/openconfig-system:system/state",
            f"{prefix}/data/openconfig-platform:components",
            prefix,
        ]

    def get_system_overview(self) -> dict[str, Any]:
        auth_body = self.authenticate()
        last_error: Exception | None = None
        for path in self._overview_paths()[1:]:
            try:
                return self.get(path)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (404, 405):
                    continue
                raise
        return auth_body if auth_body else {"error": str(last_error)}

    def get_health(self) -> dict[str, Any]:
        if not self._token:
            self.authenticate()
        prefix = self._api_prefix()
        try:
            return self.get(f"{prefix}/data/openconfig-system:system/state")
        except httpx.HTTPError:
            return {"status": "unknown"}

    def fetch_os_version_rest(self) -> tuple[str, str]:
        """
        F5OS version via HTTPS API only (no SSH).
        Returns (version, source_hint) — source_hint empty on failure.
        """
        from app.modules.os_upgrade.overview_parsers import (
            parse_f5os_system_image_version,
            parse_f5os_system_version,
            parse_f5os_version_from_image_state,
        )

        if not self._token:
            self.authenticate()
        prefix = self._api_prefix()
        for path in (
            f"{prefix}/data/openconfig-system:system/f5-system-image:image/state",
            f"{prefix}/data/openconfig-system:system/f5-system-image:image",
        ):
            try:
                data = self.get(path)
                ver = parse_f5os_version_from_image_state(data)
                if ver:
                    return ver, "REST image/state"
            except httpx.HTTPError:
                continue

        for cmd in (
            "show system version",
            "show system image",
            "show version",
        ):
            text = self.run_admin_show_command(cmd)
            ver = parse_f5os_system_version(text)
            if not ver and cmd == "show system image":
                ver = parse_f5os_system_image_version(text)
            if ver:
                return ver, "REST CLI exec"
        return "", ""

    def fetch_platform_description_rest(self) -> str:
        """Platform model/description from openconfig-platform (no SSH)."""
        from app.modules.health_check.f5os_common import parse_f5os_overview

        try:
            overview = self.get_system_overview()
            block = parse_f5os_overview(overview)
            return str(block.get("platform", "") or "").strip()
        except httpx.HTTPError:
            return ""

    def fetch_f5os_cli_outputs_rest(self) -> dict[str, str]:
        """CLI-over-HTTPS outputs for VLAN merge (no SSH)."""
        outputs: dict[str, str] = {}
        for cmd in (
            "show vlan",
            "show run interfaces",
            "show interfaces interface summary",
            "show components component platform state",
        ):
            text = self.run_admin_show_command(cmd)
            if text.strip():
                outputs[cmd] = text
        return outputs
