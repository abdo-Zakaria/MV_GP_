"""
Standalone entry point for the Rehabilitation Monitor GUI.

Runs a single `RehabApplicationController` instance with `show_opencv_window=False`
and displays all live camera frames, sensor states, calibration references,
raw & aligned IMU angles, UKF outputs, and recording info inside the PySide6 GUI.

Usage:
    python gui_main.py
    python gui_main.py --simulate --warmup 5 --calibration 3
    python main.py --gui
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from rehab_app import RehabApplicationController, RehabConfig
from rehab_monitor_gui import RehabMonitorWindow


def parse_gui_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rehabilitation Monitor GUI (Display Interface for main.py)"
    )
    parser.add_argument("--duration", type=float, default=3000.0, help="Maximum recording duration in seconds.")
    parser.add_argument("--warmup", type=float, default=30.0, help="Stationary warm-up time in seconds.")
    parser.add_argument("--calibration", type=float, default=5.0, help="Neutral calibration window in seconds.")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index.")
    parser.add_argument("--no-sensors", action="store_true", help="Disable Delsys sensor connection.")
    parser.add_argument("--no-vision", action="store_true", help="Disable camera/MediaPipe vision worker.")
    parser.add_argument("--simulate", action="store_true", help="Enable main.py simulation mode.")
    parser.add_argument("--auto-start", action="store_true", help="Automatically start the session when the GUI opens.")
    return parser.parse_args(argv)


def launch_gui(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_gui_args(argv)

    config = RehabConfig(
        record_seconds=args.duration,
        warmup_seconds=args.warmup,
        calibration_seconds=args.calibration,
        camera_index=args.camera_index,
        show_opencv_window=False,
        enable_sensors=not (args.no_sensors or args.simulate),
        enable_vision=not args.no_vision,
    )
    controller = RehabApplicationController(config=config)

    app = QApplication.instance() or QApplication(sys.argv)
    window = RehabMonitorWindow(
        controller=controller,
        simulate_mode=args.simulate,
        auto_start=args.auto_start,
    )
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(launch_gui())
