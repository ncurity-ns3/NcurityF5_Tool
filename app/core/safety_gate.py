from __future__ import annotations

from app.core.models import OperationClass


class ChangeModeDisabledError(PermissionError):
    pass


class SafetyGate:
    """central policy: write/destructive ops require change mode."""

    def __init__(self, change_mode_enabled: bool = False) -> None:
        self.change_mode_enabled = change_mode_enabled

    def assert_allowed(self, operation: OperationClass) -> None:
        if operation in (OperationClass.ro, OperationClass.gen):
            return
        if operation == OperationClass.pre:
            return
        if not self.change_mode_enabled:
            raise ChangeModeDisabledError(
                f"operation {operation.value} blocked: change mode is disabled"
            )

    def require_approval_artifacts(
        self,
        *,
        has_preview: bool,
        has_diff: bool,
        has_rollback: bool,
    ) -> None:
        if not (has_preview and has_diff and has_rollback):
            raise PermissionError(
                "apply blocked: preview, diff, and rollback artifacts are all required"
            )
