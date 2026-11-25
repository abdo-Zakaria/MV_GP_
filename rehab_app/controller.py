"""
Application and session controller coordinating all rehabilitation modules.

Connects:
1. `CalibrationManager` (rehab_app/calibration.py)
2. `DelsysSensorManager` (rehab_app/sensors.py)
3. `PoseVisionProcessor` (rehab_app/vision.py)
4. `JointFusionPipeline` (rehab_app/fusion.py)
5. `SessionRecorder` (rehab_app/recording.py)
6. `SessionAnalyzer` (rehab_app/analysis.py)

Provides a clean API for CLI execution and future GUI integration:
- `start_experiment()` / `stop_experiment()`
- `reset_session()` / `reset_calibration()`
- `get_current_measurements()` / `get_sensor_status()`
- `get_completed_results()`
- `get_settings()` / `update_settings(**kwargs)`
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional

import cv2

from rehab_app.analysis import AnalysisResult, SessionAnalyzer
from rehab_app.calibration import CalibrationManager
from rehab_app.config import RehabConfig
from rehab_app.fusion import AngleUKF, JointFusionPipeline
from rehab_app.recording import SessionRecorder
from rehab_app.sensors import DelsysSensorManager
from rehab_app.vision import PoseVisionProcessor, VisionMeasurement, draw_overlay, fmt

logger = logging.getLogger(__name__)


@dataclass
class SessionResults:
    """Holds the saved Excel workbook path and analysis results after an experiment stops."""
    workbook_path: Optional[Path]
    analysis_result: Optional[AnalysisResult]
    recorded_samples: int


class RehabApplicationController:
    """
    Main application controller managing the experiment lifecycle, background
    threads, live webcam window, Excel recording, and post-experiment analysis.
    """

    def __init__(self, config: Optional[RehabConfig] = None) -> None:
        self.config = config if config is not None else RehabConfig()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._vision_thread: Optional[threading.Thread] = None
        self._is_running: bool = False
        self._vision_status: str = "Idle"
        self._latest_measurements: Optional[Dict[str, Any]] = None
        self._latest_frame_bgr: Optional[Any] = None
        self._latest_workbook_path: Optional[Path] = None
        self._latest_analysis_result: Optional[AnalysisResult] = None
        self._init_subsystems()

    def _make_ukf(self) -> AngleUKF:
        """Create an AngleUKF configured with the current RehabConfig parameters."""
        c = self.config
        return AngleUKF(
            q_angle=c.q_angle,
            q_velocity=c.q_velocity,
            r_imu=c.r_imu,
            r_vision=c.r_vision,
            initial_p_angle=c.initial_p_angle,
            initial_p_velocity=c.initial_p_velocity,
            ukf_alpha=c.ukf_alpha,
            ukf_beta=c.ukf_beta,
            ukf_kappa=c.ukf_kappa,
            max_predict_dt=c.max_predict_dt,
            min_process_noise_dt=c.min_process_noise_dt,
        )

    def _init_subsystems(self) -> None:
        """Instantiate all modular subsystems from `self.config`."""
        c = self.config
        self.calibration_manager = CalibrationManager(
            warmup_seconds=c.warmup_seconds,
            calibration_seconds=c.calibration_seconds,
            zero_deadband_deg=c.zero_deadband_deg,
        )
        self.sensor_manager = DelsysSensorManager(
            calibration_manager=self.calibration_manager,
            sensor1_index=c.sensor1_index,
            sensor2_index=c.sensor2_index,
            sensor_stale_seconds=c.sensor_stale_seconds,
            record_seconds=c.record_seconds,
        )
        self.vision_processor = PoseVisionProcessor(
            model_asset_path=c.model_asset_path,
            visibility_min=c.visibility_min,
            shoulder_z_tolerance=c.shoulder_z_tolerance,
            landmark_alpha=c.landmark_alpha,
            min_confidence=c.min_pose_confidence,
            flip_horizontal=c.flip_camera_horizontal,
        )
        self.fusion_pipeline = JointFusionPipeline(
            shoulder_ukf=self._make_ukf(),
            elbow_ukf=self._make_ukf(),
            elbow_imu_offset_deg=c.elbow_imu_offset_deg,
        )
        self.recorder = SessionRecorder(config=c)
        self.analyzer = SessionAnalyzer()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def get_settings(self) -> Dict[str, Any]:
        """Return current configuration settings as a dictionary."""
        return self.config.to_settings_dict()

    def update_settings(self, **kwargs: Any) -> RehabConfig:
        """Update configuration parameters when no experiment is actively running."""
        if self.is_running:
            raise RuntimeError("Cannot update configuration settings while an experiment is running.")
        for key, value in kwargs.items():
            if not hasattr(self.config, key):
                raise AttributeError(f"Unknown configuration setting: {key}")
            setattr(self.config, key, value)
        self.config.__post_init__()
        self._init_subsystems()
        return self.config

    def start_experiment(self) -> None:
        """Start Delsys sensor polling and camera/fusion processing in background threads."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._latest_workbook_path = None
            self._latest_analysis_result = None
            self._latest_measurements = None

        self.recorder.reset()
        self.fusion_pipeline.reset()
        self.vision_processor.reset_state()

        if self.config.enable_sensors:
            self.sensor_manager.start_worker()
        else:
            self.sensor_manager.set_status(sensor="Sensors disabled")

        if self.config.enable_vision:
            self._vision_thread = threading.Thread(
                target=self._vision_and_fusion_worker,
                name="RehabVisionFusionWorker",
                daemon=True,
            )
            self._vision_thread.start()
        else:
            with self._lock:
                self._vision_status = "Vision disabled"

    def stop_experiment(
        self,
        export_recording: bool = True,
        run_analysis: Optional[bool] = None,
    ) -> SessionResults:
        """
        Stop background worker threads, export the recorded session to an Excel
        workbook in `recordings/`, and run post-experiment analysis and plotting.
        """
        self._stop_event.set()
        self.sensor_manager.stop_worker(timeout=5.0)
        if self._vision_thread is not None and self._vision_thread.is_alive():
            if threading.current_thread() is not self._vision_thread:
                self._vision_thread.join(timeout=5.0)
        self._vision_thread = None

        with self._lock:
            self._is_running = False

        should_analyze = (
            self.config.auto_analyze_on_stop if run_analysis is None else bool(run_analysis)
        )
        workbook_path: Optional[Path] = None
        analysis_result: Optional[AnalysisResult] = None

        if export_recording:
            workbook_path = self.recorder.export_to_excel(
                calibration_manager=self.calibration_manager,
                sensor_metadata=self.sensor_manager.get_sensor_metadata(),
            )
            with self._lock:
                self._latest_workbook_path = workbook_path
            if should_analyze and workbook_path is not None:
                analysis_result = self.analyzer.analyze_workbook(
                    workbook_path, update_workbook_metrics=False
                )
                with self._lock:
                    self._latest_analysis_result = analysis_result

        logger.info("Experiment stopped (samples recorded: %d).", self.recorder.sample_count)
        return SessionResults(workbook_path, analysis_result, self.recorder.sample_count)

    def reset_calibration(self, new_start_timestamp: Optional[float] = None) -> None:
        """Reset warm-up/neutral calibration state and clear UKF states."""
        ts = time.monotonic() if new_start_timestamp is None else float(new_start_timestamp)
        self.calibration_manager.reset(new_start_timestamp=ts)
        self.sensor_manager.reset_state()
        self.fusion_pipeline.reset()

    def reset_session(self) -> None:
        """Reset calibration, sensor readings, vision smoothing, UKF states, and recorder buffer."""
        self.calibration_manager.reset(new_start_timestamp=None)
        self.sensor_manager.reset_state()
        self.vision_processor.reset_state()
        self.fusion_pipeline.reset()
        self.recorder.reset()
        with self._lock:
            self._latest_measurements = None
            self._latest_frame_bgr = None
            self._latest_workbook_path = None
            self._latest_analysis_result = None
            self._vision_status = "Idle"
        logger.info("Session state completely reset.")

    def get_latest_frame(self) -> Optional[Any]:
        """Return a copy of the latest BGR camera frame annotated with MediaPipe landmarks."""
        with self._lock:
            return None if self._latest_frame_bgr is None else self._latest_frame_bgr.copy()

    def step_session(self, timestamp: float, vision_measurement: VisionMeasurement) -> Dict[str, Any]:
        """
        Run one synchronized fusion and recording step at `timestamp`:
        1. Read latest non-stale calibrated angles from Sensor 1 and Sensor 2.
        2. Fuse IMU and Vision angles in `self.fusion_pipeline.step()`.
        3. Record raw and processed values in `self.recorder.record_step()`.
        """
        s1 = self.sensor_manager.get_reading_snapshot(1, now=timestamp)
        s2 = self.sensor_manager.get_reading_snapshot(2, now=timestamp)

        fusion_res = self.fusion_pipeline.step(
            timestamp=timestamp,
            imu1_pitch=s1.pitch if s1.ready else None,
            imu1_yaw=s1.yaw if s1.ready else None,
            imu2_pitch=s2.pitch if s2.ready else None,
            shoulder_vision=vision_measurement.shoulder_angle_deg,
            elbow_vision=vision_measurement.elbow_angle_deg,
        )
        status_dict = self.sensor_manager.get_status()
        proc_row = self.recorder.record_step(
            timestamp=timestamp,
            sensor1=s1,
            sensor2=s2,
            vision=vision_measurement,
            fusion=fusion_res,
            sensor_status=status_dict["sensor"],
            calibration_status=status_dict["calibration"],
        )
        snapshot = dict(proc_row)
        snapshot["timestamp"] = proc_row["timestamp_monotonic_s"]
        snapshot["sensor_status"] = status_dict["sensor"]
        snapshot["calibration_status"] = status_dict["calibration"]
        with self._lock:
            self._latest_measurements = snapshot
        return snapshot

    def get_sensor_status(self) -> Dict[str, Any]:
        """Return current sensor, calibration, vision, and recording status."""
        base_status = self.sensor_manager.get_status()
        with self._lock:
            vis_status, running = self._vision_status, self._is_running
        return {
            "is_running": running,
            "sensor": base_status["sensor"],
            "calibration": base_status["calibration"],
            "is_calibrated": self.calibration_manager.is_fully_calibrated,
            "vision": vis_status,
            "recorded_samples": self.recorder.sample_count,
            "sensors_metadata": self.sensor_manager.get_sensor_metadata(),
        }

    def get_current_measurements(self) -> Dict[str, Any]:
        """Return the latest sensor, vision, and UKF fused angle measurements."""
        with self._lock:
            if self._latest_measurements is not None:
                return dict(self._latest_measurements)
        now = time.monotonic()
        p1 = self.sensor_manager.get_sensor(1, "pitch", now=now)
        y1 = self.sensor_manager.get_sensor(1, "yaw", now=now)
        p2 = self.sensor_manager.get_sensor(2, "pitch", now=now)
        return {
            "timestamp": None,
            "elapsed_s": 0.0,
            "imu1_pitch_deg": p1,
            "imu1_yaw_deg": y1,
            "imu1_elbow_deg": (y1 + self.config.elbow_imu_offset_deg) if y1 is not None else None,
            "imu2_pitch_trunk_deg": p2,
            "shoulder_vision_deg": None,
            "elbow_vision_deg": None,
            "shoulder_ukf_deg": None,
            "elbow_ukf_deg": None,
            "trunk_angle_deg": p2,
            "posture_status": "WAITING",
            "calibration_status": self.calibration_manager.get_status_text(),
        }

    def get_completed_results(self) -> SessionResults:
        """Return the saved Excel workbook path and analysis result from the last session."""
        with self._lock:
            return SessionResults(
                self._latest_workbook_path,
                self._latest_analysis_result,
                self.recorder.sample_count,
            )

    def wait_for_session(self, duration_seconds: Optional[float] = None) -> None:
        """Block until the active session finishes or `duration_seconds` elapses."""
        start = time.monotonic()
        limit = duration_seconds if duration_seconds is not None else self.config.record_seconds
        while not self._stop_event.is_set() and (time.monotonic() - start) < limit:
            if self._vision_thread is not None and not self._vision_thread.is_alive():
                break
            time.sleep(0.05)

    def _vision_and_fusion_worker(self) -> None:
        """
        Camera and UKF fusion loop.
        When `self.config.show_opencv_window` is True, opens the webcam window and draws
        the exact 8-line right-aligned telemetry overlay and bottom posture status
        from `run_camera()` in `rehab_vision_delsys_ukf_Final.py`.
        """
        cap: Optional[cv2.VideoCapture] = None
        camera_available = False
        start = time.monotonic()
        target_period = 1.0 / max(1.0, self.config.camera_loop_hz)

        try:
            self.vision_processor.initialize_detector()
        except Exception as exc:
            logger.error("MediaPipe initialization error: %s", exc)
            with self._lock:
                self._vision_status = f"MEDIAPIPE ERROR: {exc}"

        try:
            cap = cv2.VideoCapture(self.config.camera_index)
            if cap is not None and cap.isOpened():
                camera_available = True
                with self._lock:
                    self._vision_status = f"Camera {self.config.camera_index} streaming"
                if self.config.show_opencv_window:
                    cv2.namedWindow(self.config.window_title, cv2.WINDOW_NORMAL)
            else:
                with self._lock:
                    self._vision_status = f"CAMERA ERROR: Cannot open camera {self.config.camera_index}"
                if self.config.show_opencv_window:
                    raise RuntimeError(f"Cannot open camera {self.config.camera_index}.")

            while not self._stop_event.is_set() and (time.monotonic() - start) < self.config.record_seconds:
                timestamp = time.monotonic()
                frame = None
                if camera_available and cap is not None:
                    ret, raw_frame = cap.read()
                    if ret:
                        frame = raw_frame
                    elif self.config.show_opencv_window:
                        break
                    else:
                        camera_available = False
                        with self._lock:
                            self._vision_status = "Camera stream ended (sensor-only fallback)"

                if frame is not None:
                    vis_meas, annotated = self.vision_processor.process_frame(
                        frame, timestamp=timestamp, annotate_frame=True
                    )
                    with self._lock:
                        self._latest_frame_bgr = annotated.copy()
                else:
                    vis_meas = VisionMeasurement(timestamp, False, posture_status="CAMERA UNAVAILABLE")
                    annotated = None

                rec = self.step_session(timestamp=timestamp, vision_measurement=vis_meas)

                if self.config.show_opencv_window and annotated is not None:
                    h, w = annotated.shape[:2]
                    lines = [
                        f"Shoulder Vision: {fmt(rec['shoulder_vision_deg'])}",
                        f"IMU 1 Pitch: {fmt(rec['imu1_pitch_deg'])}",
                        f"Shoulder UKF: {fmt(rec['shoulder_ukf_deg'])}",
                        f"Elbow Vision: {fmt(rec['elbow_vision_deg'])}",
                        f"IMU 1 Yaw: {fmt(rec['imu1_yaw_deg'])}",
                        f"Elbow UKF: {fmt(rec['elbow_ukf_deg'])}",
                        f"IMU 2 Pitch / Trunk: {fmt(rec['trunk_angle_deg'])}",
                        f"Calibration: {rec['calibration_status']}",
                    ]
                    draw_overlay(annotated, lines)
                    cv2.putText(
                        annotated,
                        vis_meas.posture_status,
                        (max(10, w - 480), h - 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        vis_meas.posture_color_bgr,
                        3,
                    )
                    cv2.imshow(self.config.window_title, annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        self._stop_event.set()
                        break
                elif frame is None:
                    time.sleep(max(0.002, target_period - (time.monotonic() - timestamp)))
        except Exception as exc:
            logger.error("Vision/Fusion worker error: %s", exc)
            with self._lock:
                self._vision_status = f"VISION ERROR: {exc}"
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            if self.config.show_opencv_window:
                try:
                    cv2.destroyAllWindows()
                except Exception:
                    pass
            self.vision_processor.close()
