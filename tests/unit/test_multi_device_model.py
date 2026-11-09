"""Multiple device Model cell opens a select list and applies the choice."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QStyleOptionViewItem

from app.gui.widgets.multi_device_table import COL_MODEL, COL_PASS, COL_USER, MultiDeviceTablePanel

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


def test_user_and_password_editors_stay_inside_the_row() -> None:
    panel = MultiDeviceTablePanel()
    panel.set_per_device_auth(True)
    panel.add_device()
    panel.resize(980, 320)
    panel.show()
    _app.processEvents()

    assert panel.table.cellWidget(0, COL_PASS) is None
    assert panel.table.cellWidget(0, COL_USER) is None

    user_item = panel.table.item(0, COL_USER)
    cell = panel.table.visualItemRect(user_item)
    panel.table.editItem(user_item)
    _app.processEvents()
    editor = panel.table.viewport().findChild(QLineEdit)
    assert editor is not None
    box = editor.geometry()
    assert box.height() <= cell.height()
    assert box.top() >= cell.top()
    assert box.bottom() <= cell.bottom()

    panel.table.closePersistentEditor(user_item)
    index = panel.table.model().index(0, COL_PASS)
    option = QStyleOptionViewItem()
    option.rect = panel.table.visualItemRect(panel.table.item(0, COL_PASS))
    delegate = panel.table.itemDelegate()
    password_edit = delegate.createEditor(panel.table.viewport(), option, index)
    delegate.updateEditorGeometry(password_edit, option, index)
    password_edit.setText("secret")
    delegate.setModelData(password_edit, panel.table.model(), index)
    assert panel.snapshot()[0].tmos_pass == "secret"
    assert "secret" not in panel.table.item(0, COL_PASS).text()
    assert password_edit.height() <= option.rect.height()
