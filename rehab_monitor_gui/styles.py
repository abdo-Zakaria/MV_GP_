"""
Visual styling and asset paths for the Rehabilitation Monitor GUI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
IMAGES_DIR: Path = PROJECT_ROOT / "Images"
DELSYS_LOGO_PATH: Path = IMAGES_DIR / "delsys.png"
WINDOW_ICON_PATH: Path = IMAGES_DIR / "window_icon.png"

COLORS: Dict[str, str] = {
    "bg_app": "#0F172A",
    "bg_surface": "#1E293B",
    "bg_card": "#162032",
    "bg_video": "#090D16",
    "border": "#334155",
    "border_accent": "#38BDF8",
    "text_primary": "#F8FAFC",
    "text_secondary": "#94A3B8",
    "text_muted": "#64748B",
    "accent_blue": "#38BDF8",
    "accent_teal": "#2DD4BF",
    "ok": "#22C55E",
    "warn": "#F59E0B",
    "danger": "#EF4444",
    "btn_primary": "#0284C7",
    "btn_primary_hover": "#0369A1",
    "btn_danger": "#DC2626",
    "btn_danger_hover": "#B91C1C",
    "btn_neutral": "#334155",
    "btn_neutral_hover": "#475569",
}


def build_app_stylesheet() -> str:
    """Return the application QSS stylesheet."""
    c = COLORS
    return f"""
    QMainWindow, QWidget {{
        background-color: {c['bg_app']};
        color: {c['text_primary']};
        font-family: "Segoe UI", "Inter", Arial, sans-serif;
        font-size: 10pt;
    }}
    QFrame#topBar {{
        background-color: {c['bg_surface']};
        border-bottom: 1px solid {c['border']};
    }}
    QFrame#sectionCard {{
        background-color: {c['bg_surface']};
        border: 1px solid {c['border']};
        border-radius: 8px;
    }}
    QFrame#subCard {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border']};
        border-radius: 6px;
    }}
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 6px;
        background-color: {c['bg_app']};
    }}
    QTabBar::tab {{
        background-color: {c['bg_surface']};
        color: {c['text_secondary']};
        border: 1px solid {c['border']};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 8px 18px;
        margin-right: 4px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {c['bg_card']};
        color: {c['accent_blue']};
        border-color: {c['accent_blue']};
    }}
    QPushButton {{
        background-color: {c['btn_neutral']};
        color: {c['text_primary']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 7px 14px;
        font-weight: 600;
    }}
    QPushButton:hover:enabled {{
        background-color: {c['btn_neutral_hover']};
    }}
    QPushButton:disabled {{
        background-color: #1E2536;
        color: {c['text_muted']};
        border-color: #263044;
    }}
    QPushButton[variant="primary"] {{
        background-color: {c['btn_primary']};
        border-color: {c['accent_blue']};
    }}
    QPushButton[variant="primary"]:hover:enabled {{
        background-color: {c['btn_primary_hover']};
    }}
    QPushButton[variant="danger"] {{
        background-color: {c['btn_danger']};
        border-color: {c['danger']};
    }}
    QPushButton[variant="danger"]:hover:enabled {{
        background-color: {c['btn_danger_hover']};
    }}
    QProgressBar {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border']};
        border-radius: 5px;
        text-align: center;
        color: {c['text_primary']};
        font-weight: 600;
        min-height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {c['accent_blue']};
        border-radius: 4px;
    }}
    QCheckBox {{
        spacing: 7px;
        color: {c['text_primary']};
        font-weight: 500;
    }}
    QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {c['bg_card']};
        color: {c['text_primary']};
        border: 1px solid {c['border']};
        border-radius: 5px;
        padding: 4px 8px;
    }}
    QTableWidget {{
        background-color: {c['bg_card']};
        gridline-color: {c['border']};
        border: 1px solid {c['border']};
        border-radius: 6px;
    }}
    QHeaderView::section {{
        background-color: {c['bg_surface']};
        color: {c['accent_blue']};
        border: 1px solid {c['border']};
        padding: 5px 8px;
        font-weight: bold;
    }}
    QScrollArea {{
        border: none;
        background-color: transparent;
    }}
    """
