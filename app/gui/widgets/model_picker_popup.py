"""Model-specific picker (iSeries / rSeries)."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, pyqtSignal
from PyQt6.QtWidgets import QWidget

from app.gui.device_models import MODEL_ISERIES, MODEL_RSERIES
from app.gui.widgets.choice_picker_popup import ChoicePickerPopup


class ModelPickerPopup(ChoicePickerPopup):
    model_selected = pyqtSignal(str)

    def __init__(
        self,
        anchor: QPoint,
        width: int,
        current: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            anchor,
            width,
            [MODEL_ISERIES, MODEL_RSERIES],
            current,
            parent,
        )
        self.choice_selected.connect(self.model_selected.emit)
