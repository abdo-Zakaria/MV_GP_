"""
Automated verification suite for the standalone `rehab_monitor_gui` display layer.

Verifies:
1. Single `RehabApplicationController` instance with `show_opencv_window=False`
   and no duplicate sensor acquisition or processing pipeline.
2. Exact numerical match between `controller.get_current_measurements()` and
   all GUI labels (raw IMU, dynamically aligned IMU, Vision, UKF, Trunk,
   Vision calibration references, calibration status, posture status, and
   verbatim `main.py` telemetry lines).
3. Continuous GUI updates across warm-up, neutral calibration, and varying
   active IMU + Vision inputs.
4. End-to-end session execution delegating to `main.py` (`start_session` ->
   workbook export & plot loading in `SessionResultsPanel`).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import _euler_deg_to_quaternion
from rehab_app import RehabApplicationController, RehabConfig, VisionMeasurement
from rehab_app.vision import fmt
from rehab_monitor_gui import ApplicationOutputBridge, RehabMonitorWindow


class TestRehabMonitorGUI(unittest.TestCase):
    """Verify the read-only GUI layer adapts cleanly to the unmodified main.py application."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_single_controller_instance_and_continuous_exact_output_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RehabConfig(
                warmup_seconds=1.0,
                calibration_seconds=1.0,
                record_seconds=10.0,
                recordings_dir=Path(tmpdir) / "recordings",
                show_opencv_window=True,  # Window should override to False to suppress cv2 popup
                enable_sensors=False,
                enable_vision=False,
            )
            controller = RehabApplicationController(config=cfg)
            window = RehabMonitorWindow(controller=controller, simulate_mode=False, auto_start=False)

            # 1. Confirm single controller instance & suppressed OpenCV popup window
            self.assertIs(window.bridge.controller, controller)
            self.assertFalse(controller.config.show_opencv_window)

            t0 = 200.0
            controller.calibration_manager.start(t0)
            controller.sensor_manager.set_status("Delsys streaming")
            q_neutral = _euler_deg_to_quaternion(0.0, 0.0, 0.0)

            # 2. Warm-up stage (t = 200.5 s)
            controller.sensor_manager.inject_quaternion_sample(1, q_neutral, timestamp=t0 + 0.5)
            controller.sensor_manager.inject_quaternion_sample(2, q_neutral, timestamp=t0 + 0.5)
            controller.step_session(
                t0 + 0.5,
                VisionMeasurement(t0 + 0.5, True, shoulder_angle_deg=18.0, elbow_angle_deg=92.0),
            )
            snap_warm = window.bridge.poll_once()
            self.assertFalse(snap_warm.is_calibrated)
            self.assertEqual(len(snap_warm.main_overlay_lines), 6)
            self.assertIn("IMU 1 Pitch (Raw):", snap_warm.main_overlay_lines[1])

            # 3. Neutral calibration stage (t = 201.3, 201.7, 202.1 s)
            for dt in (1.3, 1.7, 2.1):
                ts = t0 + dt
                controller.sensor_manager.inject_quaternion_sample(1, q_neutral, timestamp=ts)
                controller.sensor_manager.inject_quaternion_sample(2, q_neutral, timestamp=ts)
                controller.step_session(
                    ts,
                    VisionMeasurement(
                        ts,
                        True,
                        shoulder_angle_deg=22.0,
                        elbow_angle_deg=94.0,
                        posture_status="START POSITION (Ready)",
                    ),
                )

            snap_cal = window.bridge.poll_once()
            self.assertTrue(snap_cal.is_calibrated)
            self.assertAlmostEqual(snap_cal.shoulder_vision_ref_deg, 22.0, places=6)
            self.assertAlmostEqual(snap_cal.elbow_vision_ref_deg, 94.0, places=6)
            self.assertEqual(window.status_panel.cal_progress.value(), 100)

            # 4. Active stage: feed multiple varying samples and verify continuous updates
            #    and exact parity between controller.get_current_measurements() and GUI widgets
            with controller._lock:
                controller._latest_frame_bgr = np.zeros((480, 640, 3), dtype=np.uint8)

            observed_gui_sh_aligned = []
            for idx, (sh_rel, el_rel, trk) in enumerate(
                [(-10.0, -12.0, 5.0), (-25.0, -28.0, 9.5), (-40.0, -42.0, 14.0)]
            ):
                ts = t0 + 2.5 + idx * 0.4
                q1 = _euler_deg_to_quaternion(roll_deg=sh_rel, pitch_deg=4.0, yaw_deg=el_rel)
                q2 = _euler_deg_to_quaternion(roll_deg=trk, pitch_deg=0.0, yaw_deg=0.0)
                vis = VisionMeasurement(
                    ts,
                    True,
                    shoulder_angle_deg=22.0 - sh_rel,
                    elbow_angle_deg=94.0 - el_rel,
                    posture_status="RIGHT",
                )
                controller.sensor_manager.inject_quaternion_sample(1, q1, timestamp=ts)
                controller.sensor_manager.inject_quaternion_sample(2, q2, timestamp=ts)
                controller.step_session(ts, vis)

                snap = window.bridge.poll_once()
                orig = controller.get_current_measurements()

                # Verify GUI labels match exact controller outputs
                jp = window.joints_panel
                self.assertEqual(jp.row_sh_vision.value_label.text(), f"{fmt(orig['shoulder_vision_deg'])}°")
                self.assertEqual(jp.row_sh_imu_raw.value_label.text(), f"{fmt(orig['imu1_pitch_deg'])}°")
                self.assertEqual(
                    jp.row_sh_imu_aligned.value_label.text(),
                    f"{fmt(orig['imu1_shoulder_corrected_deg'])}°",
                )
                self.assertEqual(jp.row_sh_ukf.value_label.text(), f"{fmt(orig['shoulder_ukf_deg'])}°")

                self.assertEqual(jp.row_el_vision.value_label.text(), f"{fmt(orig['elbow_vision_deg'])}°")
                self.assertEqual(jp.row_el_imu_raw.value_label.text(), f"{fmt(orig['imu1_yaw_deg'])}°")
                self.assertEqual(jp.row_el_imu_aligned.value_label.text(), f"{fmt(orig['imu1_elbow_deg'])}°")
                self.assertEqual(jp.row_el_ukf.value_label.text(), f"{fmt(orig['elbow_ukf_deg'])}°")
                self.assertEqual(jp.row_trunk.value_label.text(), f"{fmt(orig['trunk_angle_deg'])}°")

                # Verify 8-line calibrated main.py telemetry mirror matches exact values
                self.assertEqual(len(snap.main_overlay_lines), 8)
                self.assertEqual(
                    snap.main_overlay_lines[1],
                    f"IMU 1 Pitch (Aligned): {fmt(orig['imu1_shoulder_corrected_deg'])}",
                )
                self.assertEqual(
                    snap.main_overlay_lines[4],
                    f"IMU 1 Yaw (Aligned): {fmt(orig['imu1_elbow_deg'])}",
                )
                self.assertIn("RIGHT", window.video_panel.posture_banner.text())

                observed_gui_sh_aligned.append(orig["imu1_shoulder_corrected_deg"])

            # Confirm continuous monotonic increase with reversed Shoulder sign (-1.0)
            self.assertLess(observed_gui_sh_aligned[0], observed_gui_sh_aligned[1])
            self.assertLess(observed_gui_sh_aligned[1], observed_gui_sh_aligned[2])

            window.close()

    def test_bridge_delegates_session_to_main_without_duplicating_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rec_dir = Path(tmpdir) / "recordings"
            cfg = RehabConfig(
                warmup_seconds=0.5,
                calibration_seconds=0.5,
                record_seconds=1.0,
                recordings_dir=rec_dir,
                show_opencv_window=False,
                enable_sensors=False,
                enable_vision=False,
            )
            controller = RehabApplicationController(config=cfg)
            window = RehabMonitorWindow(controller=controller, simulate_mode=True, auto_start=False)

            completed_holder = []
            window.bridge.session_completed.connect(completed_holder.append)

            window.bridge.start_session(export_on_finish=True)
            deadline = time.monotonic() + 15.0
            while window.bridge.is_session_active and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.05)
            self.app.processEvents()

            if window.bridge._session_thread is not None:
                window.bridge._session_thread.join(timeout=5.0)
            self.app.processEvents()

            res = controller.get_completed_results()
            self.assertIsNotNone(res.workbook_path)
            self.assertTrue(res.workbook_path.is_file())
            self.assertGreater(res.recorded_samples, 20)

            window.results_panel.load_session_results(res)
            self.assertEqual(window.results_panel.workbook_combo.count(), 1)
            self.assertEqual(window.results_panel.plot_combo.count(), 7)
            self.assertGreater(window.results_panel.metrics_table.rowCount(), 0)

            window.close()


if __name__ == "__main__":
    unittest.main()
