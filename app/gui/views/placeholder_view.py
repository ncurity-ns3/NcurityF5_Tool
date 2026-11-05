from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.gui.theme import mark_page_subtitle, mark_page_title


class PlaceholderView(QWidget):
    def __init__(self, title_en: str, desc_ko: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(title_en)
        mark_page_title(title)
        layout.addWidget(title)

        card = QFrame()
        card.setProperty("role", "heroCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        desc = QLabel(desc_ko)
        desc.setWordWrap(True)
        mark_page_subtitle(desc)
        card_layout.addWidget(desc)
        layout.addWidget(card)
        layout.addStretch()
