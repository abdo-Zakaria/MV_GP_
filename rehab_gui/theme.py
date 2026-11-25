"""
Visual theme, color palette, and asset paths for the Rehabilitation GUI.

The color palette is built directly from the existing `Images/` assets
(`delsys.png`, `window_icon.png`, `checked.png`, `unchecked.png`,
`centro_trigger_config.png`) and the existing Delsys UI stylesheets:
- Deep Delsys Navy background (`#1F253D`)
- Elevated Slate panels and cards (`#28304D`, `#323B5C`, `#4A5063`)
- Delsys Emerald Green primary actions (`#3D885C`, `#62B56F`)
- Soft Sky Blue active tab selection (`#CFE8FF` with `#1F253D` text)
- Crisp White primary text (`#FFFFFF`) and Cool Silver secondary labels (`#C2C9DF`)
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from rehab_app.config import PROJECT_ROOT

IMAGES_DIR: Path = PROJECT_ROOT / "Images"
DELSYS_LOGO_PATH: Path = IMAGES_DIR / "delsys.png"
WINDOW_ICON_PATH: Path = IMAGES_DIR / "window_icon.png"
CHECKED_ICON_PATH: Path = IMAGES_DIR / "checked.png"
UNCHECKED_ICON_PATH: Path = IMAGES_DIR / "unchecked.png"
CENTRO_TRIGGER_IMAGE_PATH: Path = IMAGES_DIR / "centro_trigger_config.png"

# Central Color Palette (modify here to adjust the application theme)
PALETTE: Dict[str, str] = {
    "bg_main": "#1F253D",          # Primary window background (from StartWindow/CollectDataWindow)
    "bg_header": "#181D31",        # Top header bar background
    "bg_panel": "#28304D",         # Section panel background
    "bg_card": "#323B5C",          # Telemetry card background
    "bg_input": "#4A5063",         # Input fields and list boxes (from CollectDataWindow)
    "border": "#485273",           # Subtle panel and card border
    "accent_green": "#3D885C",     # Delsys primary action button green
    "accent_green_hover": "#489E6C",
    "accent_green_pressed": "#35734F",
    "status_ok": "#62B56F",        # Active / calibrated sage green (from centro_trigger_config.png)
    "status_warn": "#E0A83B",      # Warm-up / calibrating amber
    "status_error": "#D9534F",     # Error / stop coral red
    "tab_selected_bg": "#CFE8FF",  # Active tab background (from CollectDataWindow)
    "tab_selected_border": "#9CC9F5",
    "tab_hover_bg": "#D9EEFF",
    "text_primary": "#FFFFFF",     # Primary text
    "text_secondary": "#C2C9DF",   # Secondary / caption text
    "text_muted": "#8E97B4",       # Disabled / placeholder text
}


def build_stylesheet() -> str:
    """
    Build the global Qt stylesheet for the rehabilitation application using
    PALETTE colors and absolute paths to the checkbox icons in `Images/`.
    """
    checked_url = CHECKED_ICON_PATH.as_posix()
    unchecked_url = UNCHECKED_ICON_PATH.as_posix()
    p = PALETTE

    return f"""
    QMainWindow, QWidget {{
        background-color: {p['bg_main']};
        color: {p['text_primary']};
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 10.5pt;
    }}

    QFrame#headerBar {{
        background-color: {p['bg_header']};
        border-bottom: 1px solid {p['border']};
    }}

    QFrame#panelCard {{
        background-color: {p['bg_panel']};
        border: 1px solid {p['border']};
        border-radius: 8px;
    }}

    QFrame#metricCard {{
        background-color: {p['bg_card']};
        border: 1px solid {p['border']};
        border-radius: 7px;
    }}

    QGroupBox {{
        background-color: {p['bg_panel']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        margin-top: 14px;
        padding: 14px 12px 12px 12px;
        font-weight: bold;
        font-size: 11pt;
        color: {p['tab_selected_bg']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 6px;
    }}

    QTabWidget::pane {{
        border: 1px solid {p['border']};
        border-radius: 6px;
        background-color: {p['bg_main']};
        top: -1px;
    }}
    QTabBar::tab {{
        color: {p['text_primary']};
        background: {p['bg_panel']};
        padding: 8px 18px;
        margin-right: 4px;
        border: 1px solid {p['border']};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-weight: 600;
        font-size: 10.5pt;
    }}
    QTabBar::tab:selected {{
        color: {p['bg_main']};
        background: {p['tab_selected_bg']};
        border-color: {p['tab_selected_border']};
    }}
    QTabBar::tab:hover:!selected {{
        background: {p['tab_hover_bg']};
        color: {p['bg_main']};
    }}

    QPushButton {{
        background-color: {p['bg_card']};
        color: {p['text_primary']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: 600;
        font-size: 10.5pt;
    }}
    QPushButton:hover:enabled {{
        background-color: {p['bg_input']};
        border-color: {p['tab_selected_border']};
    }}
    QPushButton:pressed:enabled {{
        background-color: {p['bg_panel']};
    }}
    QPushButton:disabled {{
        background-color: #252B43;
        color: {p['text_muted']};
        border: 1px solid #353D5B;
    }}

    QPushButton[role="primary"] {{
        background-color: {p['accent_green']};
        color: {p['text_primary']};
        border: none;
    }}
    QPushButton[role="primary"]:hover:enabled {{
        background-color: {p['accent_green_hover']};
    }}
    QPushButton[role="primary"]:pressed:enabled {{
        background-color: {p['accent_green_pressed']};
    }}
    QPushButton[role="primary"]:disabled {{
        background-color: #293838;
        color: {p['text_muted']};
    }}

    QPushButton[role="danger"] {{
        background-color: {p['status_error']};
        color: {p['text_primary']};
        border: none;
    }}
    QPushButton[role="danger"]:hover:enabled {{
        background-color: #E2625E;
    }}
    QPushButton[role="danger"]:disabled {{
        background-color: #3A2A38;
        color: {p['text_muted']};
    }}

    QCheckBox {{
        spacing: 8px;
        color: {p['text_primary']};
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
    }}
    QCheckBox::indicator:unchecked {{
        image: url({unchecked_url});
    }}
    QCheckBox::indicator:checked {{
        image: url({checked_url});
    }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {p['bg_input']};
        color: {p['text_primary']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        padding: 5px 8px;
        min-height: 24px;
    }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        background-color: #262C44;
        color: {p['text_muted']};
    }}
    QComboBox QAbstractItemView {{
        background-color: {p['bg_panel']};
        color: {p['text_primary']};
        selection-background-color: {p['accent_green']};
        selection-color: {p['text_primary']};
        border: 1px solid {p['border']};
    }}

    QListWidget, QTableWidget {{
        background-color: {p['bg_input']};
        color: {p['text_primary']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        gridline-color: {p['border']};
        outline: 0px;
    }}
    QListWidget::item {{
        padding: 7px 10px;
        border-bottom: 1px solid #3C4359;
    }}
    QListWidget::item:selected {{
        background-color: {p['bg_card']};
        color: {p['text_primary']};
        border-left: 3px solid {p['accent_green']};
    }}
    QHeaderView::section {{
        background-color: {p['bg_panel']};
        color: {p['tab_selected_bg']};
        padding: 6px 8px;
        border: 1px solid {p['border']};
        font-weight: bold;
    }}

    QProgressBar {{
        background-color: {p['bg_input']};
        color: {p['text_primary']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        text-align: center;
        font-weight: bold;
        min-height: 22px;
    }}
    QProgressBar::chunk {{
        background-color: {p['accent_green']};
        border-radius: 4px;
    }}

    QLabel {{
        background: transparent;
        color: {p['text_primary']};
    }}
    """
