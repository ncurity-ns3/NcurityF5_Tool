"""
F5OS port-22 SSH is intentionally disabled.

Customer environments often block direct SSH; use ``F5osClient`` HTTPS REST and
CLI-over-REST (``run_admin_show_command``) instead. TMOS remains on BigipClient
bash/util API (not SSH).
"""

from __future__ import annotations

_DISABLED_NOTE = (
    "F5OS SSH (port 22) is disabled; use F5osClient REST / CLI exec over HTTPS."
)


def run_f5os_admin_cli(
    host: str,
    admin_password: str,
    commands: list[str],
    *,
    admin_user: str = "admin",
    ssh_port: int = 22,
    timeout: float = 90.0,
    ssh_users: tuple[str, ...] = ("admin", "root"),
) -> dict[str, str]:
    """No-op — SSH collection is not used."""
    _ = (host, admin_password, commands, admin_user, ssh_port, timeout, ssh_users)
    return {"_ssh_disabled": _DISABLED_NOTE}


def first_ssh_admin_show(
    host: str,
    admin_password: str,
    *commands: str,
    admin_user: str = "admin",
    ssh_port: int = 22,
    timeout: float = 90.0,
) -> str:
    """No-op — SSH collection is not used."""
    _ = (host, admin_password, commands, admin_user, ssh_port, timeout)
    return ""
