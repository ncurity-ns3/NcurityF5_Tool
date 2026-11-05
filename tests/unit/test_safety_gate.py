import pytest

from app.core.models import OperationClass
from app.core.safety_gate import ChangeModeDisabledError, SafetyGate


def test_write_blocked_when_change_mode_off() -> None:
    gate = SafetyGate(change_mode_enabled=False)
    with pytest.raises(ChangeModeDisabledError):
        gate.assert_allowed(OperationClass.wr)
