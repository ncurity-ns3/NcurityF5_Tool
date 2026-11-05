from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "authorization",
        "x-f5-auth-token",
        "private-key",
        "private_key",
        "cookie",
    }
)

_TOKEN_RE = re.compile(
    r"(?i)(password|secret|token|authorization)\s*[:=]\s*\S+",
)


def redact_string(text: str) -> str:
    out = _TOKEN_RE.sub(r"\1=[REDACTED]", text)
    if "BEGIN PRIVATE KEY" in out:
        out = "[REDACTED PRIVATE KEY BLOCK]"
    return out


def redact_data(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_KEYS:
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = redact_data(item)
        return cleaned
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value
