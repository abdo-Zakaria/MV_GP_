"""
PySide6 Graphical User Interface package for the Active Upper Limb
Rehabilitation application.
"""
from rehab_gui.dashboard_tab import DashboardTab
from rehab_gui.main_window import RehabMainWindow
from rehab_gui.results_tab import ResultsTab
from rehab_gui.settings_tab import SettingsTab
from rehab_gui.theme import PALETTE, build_stylesheet

__all__ = [
    "DashboardTab",
    "PALETTE",
    "RehabMainWindow",
    "ResultsTab",
    "SettingsTab",
    "build_stylesheet",
]
