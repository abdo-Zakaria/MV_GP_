"""
Unit and mock-based integration tests for the optimized rehabilitation application.

Verifies:
1. Exact mathematical equivalence with rehab_vision_delsys_ukf_Final.py
   (quaternions, Euler angles, warm-up + neutral calibration, deadband,
   axis mapping, AngleUKF predictions/updates, elbow +90 deg offset before UKF,
   unfused trunk angle, and MediaPipe angle calculations).
2. Sensor mode discovery ('OR 16 bits (74 Hz)') and quaternion channel GUID mapping.
3. Four-sheet Excel workbook generation (`RawData`, `ProcessedData`, `Metrics`, `Settings`)
   with exact columns, missing-data preservation, and post-experiment plot generation.
4. Controller API for headless execution and future GUI integration (including settings read/update).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import rehab_vision_delsys_ukf_Final as legacy
from rehab_app import (
    PROCESSED_COLUMNS,
    RAW_COLUMNS,
    AngleUKF,
    CalibrationManager,
    JointFusionPipeline,
    PoseVisionProcessor,
    RehabApplicationController,
    RehabConfig,
    angle_residual,
    average_quaternions,
    calculate_angle,
    deadband,
    find_or_mode,
    find_quaternion_channels,
    fuse_elbow_angle,
    fuse_shoulder_angle,
    normalize,
    q_conjugate,
    q_multiply,
    quaternion_to_euler,
    vision_angle,
    wrap_deg,
)
from main import _euler_deg_to_quaternion, run_simulated_experiment


@dataclass
class DummyLandmark:
    x: float
    y: float
    z: float
    visibility: float = 0.99


@dataclass
class DummyChannel:
    name: str
    guid: str


@dataclass
class DummySensor:
    name: str
    channels: list


class DummyBase:
    def __init__(self, modes):
        self._modes = modes

    def getSampleModes(self, index: int):
        return self._modes


class TestMathematicalEquivalence(unittest.TestCase):
    """Ensure 100% mathematical parity with rehab_vision_delsys_ukf_Final.py."""

    def test_quaternion_and_angle_helpers(self):
        q1, q2 = (0.8, -0.2, 0.4, 0.1), (0.7, 0.3, -0.1, 0.5)
        self.assertEqual(normalize(q1), legacy.normalize(q1))
        self.assertIsNone(normalize((0.0, 0.0, 0.0, 0.0)))

        n1, n2 = normalize(q1), normalize(q2)
        self.assertEqual(q_conjugate(n1), legacy.q_conjugate(n1))
        self.assertEqual(q_multiply(n1, n2), legacy.q_multiply(n1, n2))
        np.testing.assert_allclose(
            average_quaternions([n1, n2, tuple(-v for v in n1)]),
            legacy.average_quaternions([n1, n2, tuple(-v for v in n1)]),
            rtol=1e-12, atol=1e-12,
        )
        self.assertEqual(quaternion_to_euler(n1), legacy.quaternion_to_euler(n1))

        for deg in (-370.0, -180.0, -2.0, -1.9, 0.0, 1.9, 2.0, 2.1, 180.0, 545.5):
            self.assertAlmostEqual(wrap_deg(deg), legacy.wrap_deg(deg), places=12)
            self.assertAlmostEqual(deadband(deg), legacy.deadband(deg), places=12)
            self.assertAlmostEqual(angle_residual(deg, 25.0), legacy.angle_residual(deg, 25.0), places=12)

    def test_vision_angle_and_smoothing_parity(self):
        p1 = DummyLandmark(0.2, 0.3, 0.0, 0.9)
        p2 = DummyLandmark(0.5, 0.5, 0.0, 0.8)
        p3 = DummyLandmark(0.7, 0.2, 0.0, 0.95)
        self.assertAlmostEqual(
            calculate_angle((10, 20), (30, 50), (70, 25)),
            legacy.calculate_angle((10, 20), (30, 50), (70, 25)),
            places=12,
        )
        self.assertAlmostEqual(vision_angle(p1, p2, p3, 640, 480), legacy.vision_angle(p1, p2, p3, 640, 480), places=12)
        self.assertIsNone(vision_angle(DummyLandmark(0.2, 0.3, 0.0, 0.4), p2, p3, 640, 480))

        processor = PoseVisionProcessor(landmark_alpha=0.3)
        lms = [DummyLandmark(0.5, 0.5, 0.0, 0.95) for _ in range(33)]
        lms[11] = DummyLandmark(0.6, 0.3, 0.01, 0.95)
        lms[12] = DummyLandmark(0.4, 0.3, 0.02, 0.95)
        lms[14] = DummyLandmark(0.4, 0.5, -0.05, 0.95)
        lms[16] = DummyLandmark(0.55, 0.5, -0.05, 0.95)
        lms[24] = DummyLandmark(0.4, 0.7, 0.02, 0.95)

        meas = processor.evaluate_landmarks(lms, width=640, height=480, timestamp=1.0)
        self.assertTrue(meas.pose_detected)
        self.assertAlmostEqual(meas.elbow_angle_deg, 90.0, places=5)
        self.assertAlmostEqual(meas.shoulder_angle_deg, 0.0, places=5)

    def test_ukf_and_fusion_exact_parity(self):
        legacy_sh, legacy_el = legacy.initialize_shoulder_ukf(), legacy.initialize_elbow_ukf()
        new_sh, new_el = AngleUKF(), AngleUKF()

        for idx, t in enumerate(np.linspace(10.0, 20.0, 50)):
            imu_pitch = 45.0 + 15.0 * math.sin(idx * 0.2)
            imu_yaw = 20.0 + 10.0 * math.cos(idx * 0.15)
            vis_sh = 46.5 + 14.0 * math.sin(idx * 0.2) if idx % 3 != 0 else None
            vis_el = 111.0 + 10.0 * math.cos(idx * 0.15) if idx % 4 != 0 else None

            self.assertAlmostEqual(
                legacy.fuse_shoulder_angle(legacy_sh, imu_pitch, vis_sh, t),
                fuse_shoulder_angle(new_sh, imu_pitch, vis_sh, t),
                places=12,
            )
            self.assertAlmostEqual(
                legacy.fuse_elbow_angle(legacy_el, imu_yaw, vis_el, t),
                fuse_elbow_angle(new_el, imu_yaw, vis_el, t),
                places=12,
            )
            np.testing.assert_allclose(legacy_sh.x, new_sh.x, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(legacy_sh.P, new_sh.P, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(legacy_el.x, new_el.x, rtol=1e-12, atol=1e-12)
            np.testing.assert_allclose(legacy_el.P, new_el.P, rtol=1e-12, atol=1e-12)

    def test_elbow_90_offset_and_trunk_unfused(self):
        res = JointFusionPipeline().step(1.0, 30.0, 15.0, 12.5, None, None)
        self.assertAlmostEqual(res.shoulder_ukf_deg, 30.0, places=9)
        self.assertAlmostEqual(res.imu1_elbow_deg, 105.0, places=9)
        self.assertAlmostEqual(res.elbow_ukf_deg, 105.0, places=9)
        self.assertAlmostEqual(res.trunk_angle_deg, 12.5, places=9)

    def test_calibration_warmup_neutral_and_axis_mapping(self):
        cal = CalibrationManager(warmup_seconds=30.0, calibration_seconds=5.0, zero_deadband_deg=2.0)
        cal.start(100.0)
        q_neutral = _euler_deg_to_quaternion(0.0, 0.0, 0.0)

        self.assertEqual(cal.process_quaternion(1, q_neutral, 115.0).phase, "warmup")
        self.assertEqual(cal.process_quaternion(1, q_neutral, 132.0).phase, "calibrating")
        self.assertTrue(cal.process_quaternion(1, q_neutral, 135.1).is_calibrated)

        r_act = cal.process_quaternion(1, _euler_deg_to_quaternion(40.0, 25.0, -35.0), 136.0)
        self.assertTrue(r_act.is_calibrated)
        self.assertEqual(r_act.phase, "active")
        self.assertAlmostEqual(r_act.imu_pitch_deg, r_act.mathematical_roll_deg, places=9)
        self.assertAlmostEqual(r_act.imu_yaw_deg, r_act.mathematical_yaw_deg, places=9)


class TestSensorsAndRecordingAndAnalysis(unittest.TestCase):
    """Test sensor mode/channel helpers, Excel recording, analysis, and controller API."""

    def test_sensor_mode_and_channel_helpers(self):
        base = DummyBase(["EMG raw", "OR 16 bits (74 Hz)", "ACC 16 bits"])
        self.assertEqual(find_or_mode(base, 0), "OR 16 bits (74 Hz)")

        sensor = DummySensor(
            name="Trigno Avanti",
            channels=[
                DummyChannel("Orientation W", "GUID-W"),
                DummyChannel("Orientation X", "GUID-X"),
                DummyChannel("Orientation Y", "GUID-Y"),
                DummyChannel("Orientation Z", "GUID-Z"),
                DummyChannel("Orientation Accuracy", "GUID-ACC"),
            ],
        )
        ch_map, acc = find_quaternion_channels(sensor)
        self.assertEqual(ch_map, {"w": "guid-w", "x": "guid-x", "y": "guid-y", "z": "guid-z"})
        self.assertEqual(acc, "guid-acc")

    def test_simulated_experiment_recording_and_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_recordings = Path(tmpdir) / "recordings"
            controller = RehabApplicationController(
                RehabConfig(
                    record_seconds=10.0,
                    warmup_seconds=2.0,
                    calibration_seconds=1.0,
                    recordings_dir=tmp_recordings,
                    enable_sensors=False,
                    enable_vision=False,
                )
            )
            # Test reading and updating controller settings
            controller.update_settings(warmup_seconds=1.0)
            self.assertEqual(controller.get_settings()["warmup_seconds"], 1.0)

            results = run_simulated_experiment(controller, active_seconds=3.0, rate_hz=20.0)
            self.assertIsNotNone(results.workbook_path)
            self.assertTrue(results.workbook_path.is_file())
            self.assertGreater(results.recorded_samples, 50)

            with pd.ExcelFile(results.workbook_path) as xl:
                for required_sheet in ("RawData", "ProcessedData", "Metrics", "Settings"):
                    self.assertIn(required_sheet, xl.sheet_names)

            raw_df = pd.read_excel(results.workbook_path, sheet_name="RawData")
            proc_df = pd.read_excel(results.workbook_path, sheet_name="ProcessedData")
            metrics_df = pd.read_excel(results.workbook_path, sheet_name="Metrics")
            settings_df = pd.read_excel(results.workbook_path, sheet_name="Settings")

            self.assertEqual(tuple(raw_df.columns), RAW_COLUMNS)
            self.assertEqual(tuple(proc_df.columns), PROCESSED_COLUMNS)
            self.assertEqual(len(raw_df), results.recorded_samples)
            self.assertEqual(len(proc_df), results.recorded_samples)
            self.assertGreater(len(metrics_df), 0)
            self.assertGreater(len(settings_df), 0)
            self.assertTrue(proc_df["shoulder_vision_deg"].isna().any())
            self.assertTrue(proc_df["shoulder_k_imu_angle"].notna().any())
            self.assertTrue(proc_df["elbow_k_imu_angle"].notna().any())

            expected_plots = {
                "shoulder_angles", "elbow_angles", "trunk_angle",
                "shoulder_differences", "elbow_differences",
                "kalman_gains", "ukf_consistency_distributions",
            }
            self.assertEqual(set(results.analysis_result.generated_plots.keys()), expected_plots)
            for plot_path in results.analysis_result.generated_plots.values():
                self.assertTrue(plot_path.is_file())
                self.assertGreater(plot_path.stat().st_size, 1000)

            measurements = controller.get_current_measurements()
            for key in ("shoulder_ukf_deg", "elbow_ukf_deg", "trunk_angle_deg"):
                self.assertIn(key, measurements)
            self.assertTrue(controller.get_sensor_status()["is_calibrated"])


if __name__ == "__main__":
    unittest.main()
