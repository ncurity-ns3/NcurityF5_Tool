"""Multiple device Model cell opens a select list and applies the choice."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.gui.widgets.multi_device_table import COL_MODEL, MultiDeviceTablePanel

_app = QApplication.instance() or QApplication([])


def test_model_cell_opens_select_and_switches_to_rseries() -> None:
    panel = MultiDeviceTablePanel()
    panel.add_device()
    panel.resize(900, 280)
    panel.show()
    _app.processEvents()

    rect = panel.table.visualItemRect(panel.table.item(0, COL_MODEL))
    QTest.mouseClick(panel.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    _app.processEvents()

    popup = panel._model_popup
    assert popup is not None and popup.isVisible()
    matches = popup._list.findItems("rSeries", Qt.MatchFlag.MatchExactly)
    assert matches
    row_rect = popup._list.visualItemRect(matches[0])
    QTest.mouseClick(popup._list.viewport(), Qt.MouseButton.LeftButton, pos=row_rect.center())
    _app.processEvents()

    assert panel.table.rowCount() == 2
    assert panel.table.item(0, COL_MODEL).text() == "rSeries"
    assert panel.table.rowSpan(0, COL_MODEL) == 2
