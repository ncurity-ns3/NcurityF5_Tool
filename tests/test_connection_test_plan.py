from app.core.models import PlatformKind
from app.gui.connection_test import (
    ConnectionTestOutcome,
    build_multiple_plan,
    build_single_plan,
)
from app.gui.widgets.multi_device_entry import DeviceRowData


def test_single_plan_blocks_missing_tmos_ip() -> None:
    result = build_single_plan(
        platform=PlatformKind.iseries,
        label="lab",
        f5os_host="",
        f5os_port=443,
        f5os_user="admin",
        f5os_pass="",
        tmos_host="",
        tmos_port=443,
        tmos_user="admin",
        tmos_pass="x",
    )
    assert isinstance(result, ConnectionTestOutcome)
    assert result.blocked
    assert "TMOS" in result.block_message


def test_multiple_plan_counts_devices() -> None:
    result = build_multiple_plan(
        [
            DeviceRowData(
                model="iSeries or VE",
                label="a",
                tmos_host="10.0.0.1",
                tmos_port=443,
                tmos_user="admin",
                tmos_pass="secret",
            )
        ],
        per_device_auth=True,
        common_tmos_user="admin",
        common_tmos_pass="",
        common_f5os_user="admin",
        common_f5os_pass="",
    )
    assert result.device_count == 1
    assert len(result.steps) == 1
    assert result.steps[0].stack_label == "TMOS"
