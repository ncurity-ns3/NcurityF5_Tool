"""Ncurity brand theme — white-first, blue accents (26Y PPT palette)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QScrollBar, QWidget

# ppt/theme/theme1.xml
BRAND_ACCENT_LIGHT = "#25B6FF"
BRAND_ACCENT = "#0093F2"
BRAND_PRIMARY = "#0260EA"
BRAND_NAVY = "#0032DF"

BG_APP = "#F7F9FC"
BG_SURFACE = "#FFFFFF"
BG_SIDEBAR = "#FFFFFF"
BORDER = "#E2E8F0"
BORDER_STRONG = "#94A3B8"
BORDER_FOCUS = "#B8D4F0"
TEXT = "#1A2332"
TEXT_MUTED = "#64748B"
NAV_SELECTED_BG = "#EDF5FF"
NAV_HOVER_BG = "#F4F8FC"
SPIN_BTN_BG = "#F1F5F9"

def font_families_for_platform() -> list[str]:
    """고객 PC에 Pretendard 등이 없을 수 있어 맑은 고딕 우선."""
    return ["Malgun Gothic", "Segoe UI", "sans-serif"]


FONT_FAMILIES = font_families_for_platform()
FONT_FAMILY_CSS = ", ".join(f'"{f}"' for f in FONT_FAMILIES)

_ASSET_CACHE: dict[str, str] = {}


def _resource_path(name: str) -> Path:
    from app.runtime.paths import bundle_root, install_dir, is_frozen

    candidates: list[Path] = []
    if is_frozen():
        root = bundle_root()
        if root is not None:
            candidates.append(root / "app" / "resources" / name)
        inst = install_dir()
        if inst is not None:
            candidates.append(inst / "_internal" / "app" / "resources" / name)
    candidates.append(Path(__file__).resolve().parent.parent / "resources" / name)
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


def _qss_url(path: Path) -> str:
    """Quoted absolute path for Qt stylesheet url() (spaces in Program Files)."""
    if not path.is_file():
        return ""
    return f'"{path.resolve().as_posix()}"'


def _ensure_checkbox_pngs() -> tuple[str, str]:
    checked_name = "checkbox_checked.png"
    unchecked_name = "checkbox_unchecked.png"
    if checked_name in _ASSET_CACHE and unchecked_name in _ASSET_CACHE:
        return _ASSET_CACHE[checked_name], _ASSET_CACHE[unchecked_name]

    checked_p = _resource_path(checked_name)
    unchecked_p = _resource_path(unchecked_name)
    if not checked_p.is_file() or not unchecked_p.is_file():
        try:
            from PIL import Image, ImageDraw

            checked_p.parent.mkdir(parents=True, exist_ok=True)
            if not checked_p.is_file():
                img = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                d.rounded_rectangle((0, 0, 21, 21), radius=4, fill=(2, 96, 234, 255))
                d.line([(5, 11), (9, 15), (17, 7)], fill=(255, 255, 255, 255), width=2)
                img.save(checked_p)
            if not unchecked_p.is_file():
                img = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                d.rounded_rectangle((0, 0, 21, 21), radius=4, fill=(255, 255, 255, 255))
                d.rounded_rectangle((0, 0, 21, 21), radius=4, outline=(100, 116, 139, 255), width=2)
                img.save(unchecked_p)
        except ImportError:
            return "", ""

    checked_url = _qss_url(checked_p)
    unchecked_url = _qss_url(unchecked_p)
    _ASSET_CACHE[checked_name] = checked_url
    _ASSET_CACHE[unchecked_name] = unchecked_url
    return checked_url, unchecked_url


def apply_ncurity_theme(app: QApplication) -> None:
    from PyQt6.QtCore import Qt

    # Propagate global QSS to scroll bars inside tables / scroll areas (Windows).
    attr = getattr(Qt.ApplicationAttribute, "AA_UseStyleSheetPropagationInWidgetStyles", None)
    if attr is not None:
        QApplication.setAttribute(attr, True)

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality
    )
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setFont(font)

    try:
        from PyQt6.QtWidgets import QStyleFactory

        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)
        else:
            app.setStyle("Fusion")
    except Exception:  # noqa: BLE001
        pass

    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG_APP))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(BG_SURFACE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F1F5F9"))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(BG_SURFACE))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(NAV_SELECTED_BG))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(BRAND_PRIMARY))
    pal.setColor(QPalette.ColorRole.Link, QColor(BRAND_PRIMARY))
    app.setPalette(pal)
    app.setStyleSheet(_build_stylesheet())


def mark_page_title(label: QWidget) -> None:
    label.setProperty("role", "pageTitle")


def mark_page_subtitle(label: QWidget) -> None:
    label.setProperty("role", "pageSubtitle")


def mark_mode_choice_radio(radio: QWidget) -> None:
    """점검 방식 등 주요 라디오 — 가독성·브랜드 블루 선택 표시."""
    radio.setProperty("role", "modeChoiceRadio")
    _repolish(radio)


def mark_primary_button(btn: QWidget) -> None:
    btn.setProperty("role", "primaryButton")
    _repolish(btn)


def mark_secondary_button(btn: QWidget) -> None:
    btn.setProperty("role", "secondaryButton")


def mark_step_card(widget: QWidget) -> None:
    widget.setProperty("role", "stepCard")


def mark_model_pick_item(btn: QWidget) -> None:
    btn.setProperty("role", "modelPickItem")
    _repolish(btn)


def mark_device_card(group: QWidget) -> None:
    group.setProperty("role", "deviceCard")
    _repolish(group)


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def mark_device_table_shell(frame: QWidget) -> None:
    frame.setObjectName("deviceTableShell")
    _repolish(frame)


def ncurity_scrollbar_stylesheet() -> str:
    """Per-widget QSS — reliable on Windows where global QScrollBar rules are ignored."""
    return f"""
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 6px 2px 6px 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {BORDER_FOCUS}, stop:1 #DCEBFC);
    border-radius: 5px;
    min-height: 40px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {BRAND_ACCENT};
}}
QScrollBar::handle:vertical:pressed {{
    background: {BRAND_PRIMARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0; width: 0; max-height: 0; border: none; background: none;
}}
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {{
    height: 0; width: 0; border: none; background: none; image: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 6px 2px 6px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {BORDER_FOCUS}, stop:1 #DCEBFC);
    border-radius: 5px;
    min-width: 40px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {BRAND_ACCENT};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {BRAND_PRIMARY};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    height: 0; width: 0; max-width: 0; border: none; background: none;
}}
QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {{
    height: 0; width: 0; border: none; background: none; image: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""


def apply_ncurity_scrollbar(bar: QScrollBar) -> None:
    bar.setStyleSheet(ncurity_scrollbar_stylesheet())


def polish_widget_scrollbars(root: QWidget) -> None:
    """Apply Ncurity scrollbar QSS directly (needed for QTableWidget on Windows)."""
    for bar in root.findChildren(QScrollBar):
        apply_ncurity_scrollbar(bar)


def apply_device_table_style(table: QWidget) -> None:
    """Multiple device list — visible grid, zebra rows, readable text."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QAbstractItemView, QFrame, QTableWidget

    if not isinstance(table, QTableWidget):
        return
    table.setProperty("role", "deviceGrid")
    table.setShowGrid(True)
    table.setFrameShape(QFrame.Shape.NoFrame)
    table.setWordWrap(False)
    table.setAlternatingRowColors(False)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    hdr = table.horizontalHeader()
    hdr.setHighlightSections(False)
    hdr.setDefaultAlignment(
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    )
    hdr.setStretchLastSection(True)
    hdr.setMinimumSectionSize(56)
    hdr_font = QFont()
    hdr_font.setPointSize(10)
    hdr_font.setWeight(QFont.Weight.DemiBold)
    hdr.setFont(hdr_font)
    cell_font = QFont()
    cell_font.setPointSize(10)
    table.setFont(cell_font)
    try:
        from PyQt6.QtWidgets import QStyleFactory

        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            table.setStyle(fusion)
    except Exception:  # noqa: BLE001
        pass
    polish_widget_scrollbars(table)
    _repolish(table)


def _build_stylesheet() -> str:
    chevron = _qss_url(_resource_path("combobox_chevron.png"))
    chevron_arrow = ""
    if chevron:
        chevron_arrow = f"""
    image: url({chevron});
    width: 14px;
    height: 14px;
    margin: 0 10px 0 0;"""
    else:
        chevron_arrow = f"""
    image: none;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 7px solid {BRAND_PRIMARY};
    width: 0px;
    height: 0px;
    margin: 0 12px 0 0;"""

    spin_combo_styles = f"""
QSpinBox[formControl="portSpin"] {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 0px;
    max-height: 32px;
    selection-background-color: {NAV_SELECTED_BG};
    selection-color: {BRAND_PRIMARY};
}}
QSpinBox[formControl="portSpin"]:focus {{
    border: 1px solid {BRAND_ACCENT};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 0px;
    height: 0px;
    border: none;
    margin: 0;
}}
QComboBox {{
    combobox-popup: 0;
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 2px 6px;
    padding-right: 24px;
    min-height: 0px;
    color: {TEXT};
}}
QComboBox[formControl="formCombo"] {{
    padding: 4px 12px;
    padding-right: 32px;
    min-height: 36px;
    max-height: 36px;
    font-family: {FONT_FAMILY_CSS};
    font-size: 10pt;
    border-radius: 8px;
}}
QComboBox[formControl="tableCombo"] {{
    padding: 1px 4px;
    padding-right: 20px;
    min-height: 0px;
    max-height: 24px;
    font-size: 12px;
    border-radius: 4px;
    color: {TEXT};
}}
QComboBox[formControl="tableCombo"] QAbstractItemView {{
    background-color: {BG_SURFACE};
    color: {TEXT};
    selection-background-color: {BRAND_PRIMARY};
    selection-color: #FFFFFF;
}}
QComboBox:hover {{
    border-color: {BORDER_FOCUS};
}}
QComboBox:focus {{
    border: 1px solid {BRAND_ACCENT};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border-left: 1px solid {BORDER};
    background-color: {NAV_SELECTED_BG};
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}}
QComboBox[formControl="formCombo"]::drop-down {{
    width: 28px;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}}
QComboBox[formControl="tableCombo"]::drop-down {{
    width: 18px;
}}
QComboBox::drop-down:hover {{
    background-color: #DCEBFC;
}}
QComboBox::down-arrow {{{chevron_arrow}
}}
QComboBox QAbstractItemView {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 4px;
    color: {TEXT};
    selection-background-color: {BRAND_PRIMARY};
    selection-color: #FFFFFF;
    outline: none;
}}
QFrame#modelPickerPopup {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton[role="modelPickItem"] {{
    background-color: transparent;
    color: {TEXT};
    border: none;
    border-radius: 8px;
    padding: 10px 12px;
    text-align: center;
    font-weight: 500;
}}
QPushButton[role="modelPickItem"]:hover {{
    background-color: {NAV_HOVER_BG};
}}
QPushButton[role="modelPickItem"][selected="true"] {{
    background-color: {NAV_SELECTED_BG};
    color: {BRAND_PRIMARY};
    font-weight: 600;
}}
"""

    return f"""
QMainWindow {{
    background-color: {BG_APP};
}}
QWidget#contentHost {{
    background-color: {BG_APP};
}}
QFrame#navFrame {{
    background-color: {BG_SIDEBAR};
    border: none;
    border-right: 1px solid {BORDER};
}}
QFrame#navHeader {{
    background-color: {BG_SIDEBAR};
    border: none;
    border-bottom: 1px solid {BORDER};
}}
QListWidget#navList {{
    background-color: {BG_SIDEBAR};
    border: none;
    outline: none;
    padding: 8px 8px;
    color: {TEXT};
    font-size: 13px;
}}
QListWidget#navList::item {{
    padding: 10px 12px;
    border-radius: 8px;
    margin: 2px 0;
    color: {TEXT_MUTED};
}}
QListWidget#navList::item:selected {{
    background-color: {NAV_SELECTED_BG};
    color: {BRAND_PRIMARY};
    font-weight: 600;
    border-left: 3px solid {BRAND_ACCENT};
    padding-left: 9px;
}}
QListWidget#navList::item:hover:!selected {{
    background-color: {NAV_HOVER_BG};
    color: {TEXT};
}}
QListWidget#navList::item:disabled {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
    padding: 14px 8px 2px 8px;
    background: transparent;
}}
QStatusBar {{
    background-color: {BG_SURFACE};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    padding: 2px 8px;
    font-size: 11px;
}}
QMenuBar {{
    background-color: {BG_SURFACE};
    border-bottom: 1px solid {BORDER};
    padding: 2px 6px;
}}
QMenuBar::item:selected {{
    background-color: {NAV_HOVER_BG};
    border-radius: 4px;
}}
QGroupBox {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    color: {TEXT};
}}
QGroupBox[role="deviceCard"] {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_FOCUS};
    border-radius: 12px;
    margin-top: 18px;
    padding: 14px 14px 12px 14px;
}}
QGroupBox[role="deviceCard"]::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: {BRAND_PRIMARY};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {BRAND_PRIMARY};
}}
QLabel[role="pageTitle"] {{
    font-family: {FONT_FAMILY_CSS};
    font-size: 20px;
    font-weight: 700;
    color: {TEXT};
    padding: 4px 0 2px 0;
}}
QLabel[role="pageSubtitle"] {{
    font-family: {FONT_FAMILY_CSS};
    color: {TEXT_MUTED};
    font-size: 12px;
    padding-bottom: 8px;
}}
QLabel[role="muted"] {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QLabel[role="stepTitle"] {{
    font-weight: 600;
    color: {TEXT};
    font-size: 12px;
}}
QLabel[role="infoTitle"] {{
    font-weight: 700;
    color: {BRAND_PRIMARY};
    font-size: 13px;
}}
QFrame[role="stepCard"] {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    border-top: 2px solid {BRAND_ACCENT};
}}
QFrame[role="heroCard"] {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame[role="infoCard"] {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_FOCUS};
    border-radius: 10px;
}}
QPushButton {{
    background-color: {BG_SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    min-height: 20px;
    font-weight: 500;
}}
QPushButton:hover {{
    border-color: {BRAND_ACCENT};
    color: {BRAND_PRIMARY};
    background-color: {NAV_HOVER_BG};
}}
QPushButton:pressed {{
    background-color: #E8EEF4;
}}
QPushButton:disabled {{
    color: #94A3B8;
    border-color: #E2E8F0;
    background-color: #F8FAFC;
}}
QPushButton[role="primaryButton"] {{
    background-color: {BRAND_PRIMARY};
    color: #FFFFFF;
    border: 1px solid {BRAND_PRIMARY};
    font-weight: 600;
}}
QPushButton[role="primaryButton"]:hover {{
    background-color: {BRAND_ACCENT};
    border-color: {BRAND_ACCENT};
    color: #FFFFFF;
}}
QPushButton[role="primaryButton"]:pressed {{
    background-color: {BRAND_NAVY};
}}
QPushButton[role="primaryButton"]:disabled {{
    background-color: #CBD5E1;
    border-color: #CBD5E1;
    color: #F8FAFC;
}}
QPushButton[role="secondaryButton"] {{
    background-color: {BG_SURFACE};
    color: {BRAND_PRIMARY};
    border: 1px solid {BORDER_FOCUS};
    font-weight: 600;
}}
QPushButton[role="secondaryButton"]:hover {{
    background-color: {NAV_SELECTED_BG};
    border-color: {BRAND_ACCENT};
}}
QPushButton[role="secondaryButton"]:disabled {{
    background-color: #F8FAFC;
    color: #94A3B8;
    border-color: #E2E8F0;
}}
QLineEdit {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 18px;
    selection-background-color: {NAV_SELECTED_BG};
    selection-color: {BRAND_PRIMARY};
}}
QLineEdit[formControl="tableLine"] {{
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 0px;
    max-height: 26px;
    font-size: 13px;
}}
QLineEdit:focus {{
    border: 1px solid {BRAND_ACCENT};
}}
QLineEdit[formControl="tableLine"]:focus {{
    border: 1px solid {BRAND_ACCENT};
}}
{spin_combo_styles}
QTextEdit {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
    font-family: "Consolas", "Malgun Gothic", monospace;
    font-size: 11px;
}}
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: #F1F5F9;
    text-align: center;
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {BRAND_ACCENT};
    border-radius: 5px;
}}
NcurityCheckBox {{
    background: transparent;
    spacing: 12px;
    color: {TEXT};
}}
QCheckBox, QRadioButton {{
    font-family: {FONT_FAMILY_CSS};
    spacing: 10px;
    color: {TEXT};
}}
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid {BORDER_STRONG};
    background-color: {BG_SURFACE};
}}
QRadioButton::indicator:hover {{
    border-color: {BRAND_ACCENT};
}}
QRadioButton::indicator:checked {{
    background-color: {BRAND_PRIMARY};
    border: 2px solid {BRAND_PRIMARY};
}}
QRadioButton[role="modeChoiceRadio"] {{
    font-weight: 500;
    spacing: 10px;
    padding: 2px 4px 2px 0;
    color: {TEXT};
}}
QRadioButton[role="modeChoiceRadio"]::indicator {{
    width: 20px;
    height: 20px;
    border-radius: 10px;
}}
QRadioButton[role="modeChoiceRadio"]::indicator:checked {{
    background-color: {BRAND_PRIMARY};
    border: 2px solid {BRAND_PRIMARY};
}}
QRadioButton[role="modeChoiceRadio"]::indicator:hover {{
    border-color: {BRAND_ACCENT};
}}
QFrame#deviceTableShell {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 0px;
}}
QTableWidget[role="deviceGrid"] {{
    background-color: {BG_SURFACE};
    gridline-color: #E2E8F0;
    border: none;
    border-radius: 0px;
    color: {TEXT};
    font-size: 13px;
    outline: none;
    selection-background-color: transparent;
}}
QTableWidget[role="deviceGrid"]::item {{
    padding: 6px 10px;
    color: {TEXT};
    border: none;
}}
QTableWidget[role="deviceGrid"]::item:selected {{
    background-color: transparent;
    color: {TEXT};
}}
QTableWidget[role="deviceGrid"]::item:hover {{
    background-color: transparent;
}}
QTableWidget[role="deviceGrid"]::item:focus {{
    outline: none;
    border: none;
}}
QTableWidget[role="deviceGrid"] QHeaderView::section {{
    background-color: #F1F5F9;
    color: {TEXT};
    font-size: 12px;
    font-weight: 600;
    padding: 10px 12px;
    border: none;
    border-right: 1px solid #E2E8F0;
    border-bottom: 2px solid #CBD5E1;
}}
QTableWidget[role="deviceGrid"] QHeaderView::section:first {{
    border-top-left-radius: 0px;
}}
QTableWidget[role="deviceGrid"] QHeaderView::section:last {{
    border-right: none;
}}
QTableWidget[role="deviceGrid"] QTableCornerButton::section {{
    border: none;
    background-color: #F1F5F9;
}}
QMenu {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 4px;
}}
QMenu::item {{
    padding: 8px 28px 8px 14px;
    border-radius: 6px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background-color: {NAV_SELECTED_BG};
    color: {BRAND_PRIMARY};
}}
QMenu::indicator {{
    width: 16px;
    height: 16px;
    margin-left: 6px;
}}
QScrollArea {{
    border: none;
    background-color: transparent;
}}
/* Modern scrollbars — thin pill thumb, no arrow buttons (Fusion + Windows) */
QScrollBar:vertical,
QAbstractScrollArea QScrollBar:vertical,
QScrollArea QScrollBar:vertical,
QTableWidget QScrollBar:vertical,
QListWidget QScrollBar:vertical,
QTextEdit QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 0;
    border: none;
}}
QScrollBar::handle:vertical,
QAbstractScrollArea QScrollBar::handle:vertical,
QScrollArea QScrollBar::handle:vertical,
QTableWidget QScrollBar::handle:vertical,
QListWidget QScrollBar::handle:vertical,
QTextEdit QScrollBar::handle:vertical {{
    background-color: #CBD5E1;
    border-radius: 5px;
    min-height: 36px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover,
QAbstractScrollArea QScrollBar::handle:vertical:hover,
QScrollArea QScrollBar::handle:vertical:hover,
QTableWidget QScrollBar::handle:vertical:hover,
QListWidget QScrollBar::handle:vertical:hover,
QTextEdit QScrollBar::handle:vertical:hover {{
    background-color: {BRAND_ACCENT};
}}
QScrollBar::handle:vertical:pressed,
QTableWidget QScrollBar::handle:vertical:pressed {{
    background-color: {BRAND_PRIMARY};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QAbstractScrollArea QScrollBar::add-line:vertical,
QAbstractScrollArea QScrollBar::sub-line:vertical {{
    height: 0px;
    width: 0px;
    max-height: 0px;
    min-height: 0px;
    border: none;
    background: none;
    margin: 0px;
    subcontrol-origin: margin;
}}
QScrollBar::sub-line:vertical {{
    subcontrol-position: top;
}}
QScrollBar::add-line:vertical {{
    subcontrol-position: bottom;
}}
QScrollBar::up-arrow:vertical,
QScrollBar::down-arrow:vertical,
QAbstractScrollArea QScrollBar::up-arrow:vertical,
QAbstractScrollArea QScrollBar::down-arrow:vertical {{
    width: 0px;
    height: 0px;
    max-width: 0px;
    max-height: 0px;
    border: none;
    background: none;
    image: none;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QAbstractScrollArea QScrollBar::add-page:vertical,
QAbstractScrollArea QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal,
QAbstractScrollArea QScrollBar:horizontal,
QScrollArea QScrollBar:horizontal,
QTableWidget QScrollBar:horizontal,
QListWidget QScrollBar:horizontal,
QTextEdit QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 4px 2px 4px;
    border: none;
}}
QScrollBar::handle:horizontal,
QAbstractScrollArea QScrollBar::handle:horizontal,
QTableWidget QScrollBar::handle:horizontal {{
    background-color: #CBD5E1;
    border-radius: 5px;
    min-width: 36px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover,
QTableWidget QScrollBar::handle:horizontal:hover {{
    background-color: {BRAND_ACCENT};
}}
QScrollBar::handle:horizontal:pressed,
QTableWidget QScrollBar::handle:horizontal:pressed {{
    background-color: {BRAND_PRIMARY};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QAbstractScrollArea QScrollBar::add-line:horizontal,
QAbstractScrollArea QScrollBar::sub-line:horizontal {{
    height: 0px;
    width: 0px;
    max-width: 0px;
    max-height: 0px;
    border: none;
    background: none;
    margin: 0px;
    subcontrol-origin: margin;
}}
QScrollBar::sub-line:horizontal {{
    subcontrol-position: left;
}}
QScrollBar::add-line:horizontal {{
    subcontrol-position: right;
}}
QScrollBar::left-arrow:horizontal,
QScrollBar::right-arrow:horizontal,
QAbstractScrollArea QScrollBar::left-arrow:horizontal,
QAbstractScrollArea QScrollBar::right-arrow:horizontal {{
    width: 0px;
    height: 0px;
    max-width: 0px;
    max-height: 0px;
    border: none;
    background: none;
    image: none;
}}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""


_STYLESHEET = _build_stylesheet()
