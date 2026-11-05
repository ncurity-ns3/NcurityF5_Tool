from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.widgets.multi_device_entry import DeviceRowData, MultiDeviceEntryWidget


class MultiDeviceListPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMinimumHeight(220)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(12)
        self._layout.setContentsMargins(4, 4, 4, 8)
        self._layout.addStretch()
        self._scroll.setWidget(self._container)
        self._entries: list[MultiDeviceEntryWidget] = []

    def entries(self) -> list[MultiDeviceEntryWidget]:
        return list(self._entries)

    def add_entry(self, data: DeviceRowData | None = None) -> MultiDeviceEntryWidget:
        entry = MultiDeviceEntryWidget()
        if data is not None:
            entry.load_data(data)
        insert_at = max(0, self._layout.count() - 1)
        self._layout.insertWidget(insert_at, entry)
        self._entries.append(entry)
        return entry

    def remove_checked(self) -> int:
        removed = 0
        keep: list[MultiDeviceEntryWidget] = []
        for entry in self._entries:
            if entry.isChecked():
                self._layout.removeWidget(entry)
                entry.deleteLater()
                removed += 1
            else:
                keep.append(entry)
        self._entries = keep
        return removed

    def selected_entry(self) -> MultiDeviceEntryWidget | None:
        checked = [e for e in self._entries if e.isChecked()]
        if len(checked) == 1:
            return checked[0]
        return self._entries[0] if self._entries else None

    def clear_all(self) -> None:
        for entry in self._entries:
            self._layout.removeWidget(entry)
            entry.deleteLater()
        self._entries.clear()

    def snapshot(self) -> list[DeviceRowData]:
        return [e.to_data() for e in self._entries]

    def restore(self, rows: list[DeviceRowData], *, per_device_auth: bool) -> None:
        self.clear_all()
        for row in rows:
            entry = self.add_entry(row)
            entry.set_per_device_auth(per_device_auth)
        if not rows:
            self.add_entry()

    def set_per_device_auth(self, enabled: bool) -> None:
        for entry in self._entries:
            entry.set_per_device_auth(enabled)

    def any_rseries(self) -> bool:
        from app.core.models import PlatformKind

        return any(e.platform() == PlatformKind.rseries for e in self._entries)
