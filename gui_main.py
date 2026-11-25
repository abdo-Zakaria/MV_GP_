"""
Entry point to launch the Active Upper Limb Rehabilitation GUI.

Usage:
- Standard launch (ready for real Delsys hardware or toggleable simulation):
      python gui_main.py
- Launch with simulated Delsys mode pre-selected and fast warm-up/calibration:
      python gui_main.py --simulate --warmup 3 --calibration 2
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
from rehab_gui import RehabMainWindow


def parse_gui_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Active Upper Limb Rehabilitation GUI (MediaPipe + Delsys Trigno + UKF)"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Pre-select Simulated Delsys Sensors mode in the GUI.",
    )
    parser.add_argument(
        "--warmup",
        type=float,
        default=30.0,
        help="Initial stationary warm-up time in seconds (default: 30.0).",
    )
    parser.add_argument(
        "--calibration",
        type=float,
        default=5.0,
        help="Initial neutral calibration window in seconds (default: 5.0).",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="Initial OpenCV camera index (default: 0).",
    )
    return parser.parse_args(argv)


def launch_gui(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_gui_args(argv)
    config = RehabConfig(
        warmup_seconds=args.warmup,
        calibration_seconds=args.calibration,
        camera_index=args.camera_index,
        show_opencv_window=False,
    )
    controller = RehabApplicationController(config=config)

    app = QApplication.instance() or QApplication(sys.argv)
    window = RehabMainWindow(
        controller=controller,
        start_in_simulation_mode=args.simulate,
    )
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(launch_gui())
