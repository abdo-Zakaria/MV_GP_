"""
Standalone PySide6 GUI layer for the existing `main.py` rehabilitation application.

Acts strictly as a read-only visual interface and lifecycle trigger around a single
`RehabApplicationController` instance without duplicating sensor acquisition,
calibration, quaternion math, dynamic alignment, Vision, or UKF logic.
"""
from rehab_monitor_gui.bridge import ApplicationOutputBridge, TelemetrySnapshot
from rehab_monitor_gui.main_window import RehabMonitorWindow

__all__ = [
    "ApplicationOutputBridge",
    "RehabMonitorWindow",
    "TelemetrySnapshot",
]
