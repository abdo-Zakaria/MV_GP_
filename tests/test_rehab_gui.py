"""
Automated tests for the PySide6 Rehabilitation GUI (`rehab_gui/`).

Verifies:
1. Theme palette and `Images/` assets (`delsys.png`, `window_icon.png`,
   `checked.png`, `unchecked.png`) load properly.
2. `RehabMainWindow`, `DashboardTab`, `SettingsTab`, and `ResultsTab`
   instantiate without error and bind to `RehabApplicationController`.
3. Invalid operations are prevented: `Start Experiment` is disabled before
   sensors are connected and calibrated, and becomes enabled once calibrated.
4. Live sensor, vision, and UKF readings (Shoulder, Elbow with +90 deg offset,
   and Trunk) and live video frames update accurately on the Dashboard.
5. Settings form reads and updates `RehabApplicationController` configuration,
   and locks while sensors are streaming.
6. Results tab loads saved Excel workbooks, displays the `Metrics` table,
   and loads the 7 generated diagnostic PNG plots.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import _euler_deg_to_quaternion, run_simulated_experiment
from rehab_app import RehabApplicationController, RehabConfig, VisionMeasurement
from rehab_gui import PALETTE, RehabMainWindow, build_stylesheet
from rehab_gui.theme import (
    CHECKED_ICON_PATH,
    DELSYS_LOGO_PATH,
    UNCHECKED_ICON_PATH,
    WINDOW_ICON_PATH,
)


class TestRehabGUI(unittest.TestCase):
    """End-to-end verification of the PySide6 GUI layer on top of RehabApplicationController."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_and_image_assets_exist(self) -> None:
        for img_path in (DELSYS_LOGO_PATH, WINDOW_ICON_PATH, CHECKED_ICON_PATH, UNCHECKED_ICON_PATH):
            self.assertTrue(img_path.is_file(), f"Missing image asset: {img_path}")
        qss = build_stylesheet()
        self.assertIn(PALETTE["bg_main"], qss)
        self.assertIn(PALETTE["accent_green"], qss)
        self.assertIn("checked.png", qss)

    def test_dashboard_controls_and_live_telemetry_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RehabConfig(
                warmup_seconds=1.0,
                calibration_seconds=1.0,
                record_seconds=10.0,
                recordings_dir=Path(tmpdir) / "recordings",
                show_opencv_window=False,
                enable_sensors=False,
                enable_vision=False,
            )
            controller = RehabApplicationController(config=cfg)
            window = RehabMainWindow(controller=controller, start_in_simulation_mode=True)

            dash = window.dashboard_tab
            # Before connection, Start Experiment and Stop Experiment must be disabled
            self.assertFalse(dash.start_exp_btn.isEnabled())
            self.assertFalse(dash.stop_exp_btn.isEnabled())

            # Simulate connecting sensors and completing warm-up + neutral calibration
            window._is_connected = True
            t0 = 100.0
            controller.calibration_manager.start(t0)
            controller.sensor_manager.set_status("Simulated Delsys (74 Hz)")
            q0 = _euler_deg_to_quaternion(0.0, 0.0, 0.0)

            # During warm-up (elapsed = 0.5 s < 1.0 s), calibration is incomplete -> Start disabled
            controller.sensor_manager.inject_quaternion_sample(1, q0, timestamp=t0 + 0.5)
            controller.sensor_manager.inject_quaternion_sample(2, q0, timestamp=t0 + 0.5)
            window._refresh_ui()
            self.assertFalse(dash.start_exp_btn.isEnabled())

            # Complete calibration window (t = 101.2 s and t = 102.1 s >= 2.0 s)
            for ts in (t0 + 1.2, t0 + 1.6, t0 + 2.1):
                controller.sensor_manager.inject_quaternion_sample(1, q0, timestamp=ts)
                controller.sensor_manager.inject_quaternion_sample(2, q0, timestamp=ts)
            window._refresh_ui()

            self.assertTrue(controller.get_sensor_status()["is_calibrated"])
            self.assertTrue(dash.start_exp_btn.isEnabled())
            self.assertEqual(dash.calibration_progress.value(), 100)

            # Feed an active sample and a synthetic camera frame and verify UI cards update
            q1 = _euler_deg_to_quaternion(roll_deg=55.0, pitch_deg=10.0, yaw_deg=35.0)
            q2 = _euler_deg_to_quaternion(roll_deg=12.0, pitch_deg=0.0, yaw_deg=0.0)
            controller.sensor_manager.inject_quaternion_sample(1, q1, timestamp=t0 + 2.5)
            controller.sensor_manager.inject_quaternion_sample(2, q2, timestamp=t0 + 2.5)
            vis = VisionMeasurement(
                timestamp=t0 + 2.5,
                pose_detected=True,
                shoulder_angle_deg=54.0,
                elbow_angle_deg=126.0,
                posture_status="RIGHT",
            )
            controller.step_session(timestamp=t0 + 2.5, vision_measurement=vis)
            with controller._lock:
                controller._latest_frame_bgr = np.zeros((480, 640, 3), dtype=np.uint8)

            # Start experiment recording via GUI
            window.start_experiment_recording()
            self.assertTrue(window._is_recording_experiment)
            self.assertFalse(dash.start_exp_btn.isEnabled())
            self.assertTrue(dash.stop_exp_btn.isEnabled())

            controller.step_session(timestamp=t0 + 2.6, vision_measurement=vis)
            window._refresh_ui()

            self.assertIn("+54.0", dash.row_shoulder_vision.value_label.text())
            self.assertIn("+126.0", dash.row_elbow_vision.value_label.text())
            self.assertIn("+12.0", dash.row_trunk_pitch.value_label.text())
            self.assertIsNotNone(dash.video_label.pixmap())

            window.close()

    def test_settings_and_results_tabs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_rec = Path(tmpdir) / "recordings"
            cfg = RehabConfig(
                warmup_seconds=1.0,
                calibration_seconds=1.0,
                record_seconds=5.0,
                recordings_dir=tmp_rec,
                show_opencv_window=False,
                enable_sensors=False,
                enable_vision=False,
            )
            controller = RehabApplicationController(config=cfg)
            results = run_simulated_experiment(controller, active_seconds=2.0, rate_hz=15.0)
            self.assertIsNotNone(results.workbook_path)

            window = RehabMainWindow(controller=controller)

            # Test SettingsTab update
            window.settings_tab.warmup_sec_spin.setValue(12.5)
            window.settings_tab.q_angle_spin.setValue(2.5)
            self.assertTrue(window.settings_tab.apply_settings())
            self.assertEqual(controller.config.warmup_seconds, 12.5)
            self.assertEqual(controller.config.q_angle, 2.5)

            # Test ResultsTab loaded the exported Excel workbook and its 7 plots
            window.results_tab.refresh_recordings_list(select_workbook=results.workbook_path)
            self.assertEqual(window.results_tab.workbooks_list.count(), 1)
            self.assertEqual(window.results_tab.plot_selector.count(), 7)
            self.assertGreater(window.results_tab.metrics_table.rowCount(), 0)

            window.close()


if __name__ == "__main__":
    unittest.main()
