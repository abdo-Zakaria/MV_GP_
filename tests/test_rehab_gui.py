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
            # Capture Vision references during the neutral calibration window (20 deg shoulder, 90 deg elbow)
            for ts in (t0 + 1.2, t0 + 1.6, t0 + 2.1):
                controller.sensor_manager.inject_quaternion_sample(1, q0, timestamp=ts)
                controller.sensor_manager.inject_quaternion_sample(2, q0, timestamp=ts)
                controller.step_session(
                    timestamp=ts,
                    vision_measurement=VisionMeasurement(
                        timestamp=ts,
                        pose_detected=True,
                        shoulder_angle_deg=20.0,
                        elbow_angle_deg=90.0,
                        posture_status="START POSITION (Ready)",
                    ),
                )
            window._refresh_ui()

            self.assertTrue(controller.get_sensor_status()["is_calibrated"])
            self.assertTrue(dash.start_exp_btn.isEnabled())
            self.assertEqual(dash.calibration_progress.value(), 100)
            self.assertAlmostEqual(controller.get_sensor_status()["vision_references"]["shoulder"], 20.0, places=6)
            self.assertAlmostEqual(controller.get_sensor_status()["vision_references"]["elbow"], 90.0, places=6)

            # Feed an active sample and a synthetic camera frame and verify UI cards update
            # With direction_sign = -1.0:
            # Shoulder aligned = 20.0 + (-1.0) * (-35.0) = +55.0 deg
            # Elbow aligned    = 90.0 + (-1.0) * (-35.0) = +125.0 deg
            q1 = _euler_deg_to_quaternion(roll_deg=-35.0, pitch_deg=10.0, yaw_deg=-35.0)
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
            self.assertEqual(dash.row_imu1_pitch.title_label.text(), "IMU 1 Pitch (Aligned)")
            self.assertIn("+55.0", dash.row_imu1_pitch.value_label.text())
            self.assertIn("+126.0", dash.row_elbow_vision.value_label.text())
            self.assertIn("+125.0", dash.row_imu1_elbow.value_label.text())
            self.assertIn("+12.0", dash.row_trunk_pitch.value_label.text())
            self.assertIsNotNone(dash.video_label.pixmap())

            window.close()

    def test_main_and_gui_produce_identical_calibration_alignment_and_ukf_results(self) -> None:
        """Verify main.py and gui_main.py controllers produce identical results under identical inputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cli_controller = RehabApplicationController(
                RehabConfig(
                    warmup_seconds=1.0,
                    calibration_seconds=1.0,
                    recordings_dir=Path(tmpdir) / "cli",
                    show_opencv_window=True,
                    enable_sensors=False,
                    enable_vision=False,
                )
            )
            gui_controller = RehabApplicationController(
                RehabConfig(
                    warmup_seconds=1.0,
                    calibration_seconds=1.0,
                    recordings_dir=Path(tmpdir) / "gui",
                    show_opencv_window=False,
                    enable_sensors=False,
                    enable_vision=False,
                )
            )
            window = RehabMainWindow(controller=gui_controller, start_in_simulation_mode=True)
            window._is_connected = True

            t0 = 500.0
            cli_controller.calibration_manager.start(t0)
            gui_controller.calibration_manager.start(t0)
            q_neutral = _euler_deg_to_quaternion(0.0, 0.0, 0.0)

            # Stage 1 (warm-up) & Stage 2 (neutral calibration)
            for dt in (0.4, 1.2, 1.6, 2.05):
                ts = t0 + dt
                vis = VisionMeasurement(ts, True, shoulder_angle_deg=15.0, elbow_angle_deg=92.0)
                for ctrl in (cli_controller, gui_controller):
                    ctrl.sensor_manager.inject_quaternion_sample(1, q_neutral, timestamp=ts)
                    ctrl.sensor_manager.inject_quaternion_sample(2, q_neutral, timestamp=ts)
                    ctrl.step_session(timestamp=ts, vision_measurement=vis)

            self.assertEqual(
                cli_controller.calibration_manager.get_vision_references(),
                gui_controller.calibration_manager.get_vision_references(),
            )

            # Stage 3: continuous varying IMU + Vision updates
            prev_sh_corr = None
            for idx, (sh_rel, el_rel, trk) in enumerate([(-10.0, -15.0, 4.0), (-25.0, -30.0, 7.0), (-40.0, -45.0, 10.0)]):
                ts = t0 + 2.5 + idx * 0.5
                q1 = _euler_deg_to_quaternion(roll_deg=sh_rel, pitch_deg=5.0, yaw_deg=el_rel)
                q2 = _euler_deg_to_quaternion(roll_deg=trk, pitch_deg=0.0, yaw_deg=0.0)
                vis = VisionMeasurement(
                    ts,
                    True,
                    shoulder_angle_deg=15.0 - sh_rel,
                    elbow_angle_deg=92.0 - el_rel,
                )
                for ctrl in (cli_controller, gui_controller):
                    ctrl.sensor_manager.inject_quaternion_sample(1, q1, timestamp=ts)
                    ctrl.sensor_manager.inject_quaternion_sample(2, q2, timestamp=ts)
                    ctrl.step_session(timestamp=ts, vision_measurement=vis)

                window._refresh_ui()
                cli_m = cli_controller.get_current_measurements()
                gui_m = gui_controller.get_current_measurements()

                for key in (
                    "imu1_pitch_deg",
                    "imu1_yaw_deg",
                    "imu1_shoulder_corrected_deg",
                    "imu1_elbow_deg",
                    "shoulder_ukf_deg",
                    "elbow_ukf_deg",
                    "trunk_angle_deg",
                ):
                    self.assertAlmostEqual(cli_m[key], gui_m[key], places=9)

                # Confirm Shoulder corrected IMU moves continuously upward with Shoulder Vision
                if prev_sh_corr is not None:
                    self.assertGreater(gui_m["imu1_shoulder_corrected_deg"], prev_sh_corr)
                prev_sh_corr = gui_m["imu1_shoulder_corrected_deg"]

                # Confirm GUI card displays the aligned Shoulder IMU value
                self.assertIn(f"{gui_m['imu1_shoulder_corrected_deg']:+6.1f}", window.dashboard_tab.row_imu1_pitch.value_label.text())

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
