"""
Read-only output bridge connecting the existing `main.py` / `RehabApplicationController`
runtime to the PySide6 display layer.

Architecture guarantees:
1. Exactly ONE `RehabApplicationController` instance exists.
2. `show_opencv_window` is kept False so no separate OpenCV popup window opens;
   annotated MediaPipe frames are read directly via `controller.get_latest_frame()`.
3. Real hardware execution runs the exact `main.py` Option 4 lifecycle:
       controller.start_experiment()
       controller.wait_for_session(...)
       controller.stop_experiment(export_recording=True, run_analysis=True)
4. Simulation mode (ONLY when explicitly enabled) delegates directly to
   `main.run_live_webcam_with_simulated_sensors()` or `main.run_simulated_experiment()`
   from `main.py` without generating or computing any simulated values in the GUI.
5. Zero sensor acquisition, calibration, quaternion, alignment, Vision, or UKF
   calculations are performed here — every value is read directly from the controller.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

import main as app_main
from rehab_app import RehabApplicationController, RehabConfig, SessionResults
from rehab_app.vision import fmt

logger = logging.getLogger(__name__)


@dataclass
class TelemetrySnapshot:
    """Immutable read-only snapshot of outputs produced by `RehabApplicationController`."""
    is_running: bool
    is_simulation: bool
    is_calibrated: bool
    sensor_status: str
    calibration_status: str
    vision_status: str
    posture_status: str
    elapsed_s: float
    recorded_samples: int
    total_calibration_seconds: float
    recordings_dir: Path
    last_workbook_path: Optional[Path]

    # Joint & sensor measurements directly from controller.get_current_measurements()
    measurements: Dict[str, Any]

    # Vision calibration references from controller.get_sensor_status()
    shoulder_vision_ref_deg: Optional[float]
    elbow_vision_ref_deg: Optional[float]

    # Read-only sensor metadata & raw quaternions from controller.sensor_manager
    sensor1_meta: Dict[str, Any]
    sensor2_meta: Dict[str, Any]
    sensor1_raw_q: Optional[Tuple[float, float, float, float]]
    sensor2_raw_q: Optional[Tuple[float, float, float, float]]
    sensor1_phase: str
    sensor2_phase: str

    # Exact text lines that `main.py` renders on its OpenCV telemetry view
    main_overlay_lines: List[str]

    # Latest BGR camera frame already annotated by PoseVisionProcessor
    frame_bgr: Optional[np.ndarray]


def build_main_display_lines(measurements: Dict[str, Any], is_calibrated: bool) -> List[str]:
    """
    Format the exact telemetry text lines displayed by `main.py` (`controller.py` L408-L427)
    using `rehab_app.vision.fmt` without altering any values.
    """
    if not is_calibrated:
        return [
            f"Shoulder Vision: {fmt(measurements.get('shoulder_vision_deg'))}",
            f"IMU 1 Pitch (Raw): {fmt(measurements.get('imu1_pitch_deg'))}",
            f"Elbow Vision: {fmt(measurements.get('elbow_vision_deg'))}",
            f"IMU 1 Yaw (Raw): {fmt(measurements.get('imu1_yaw_deg'))}",
            f"IMU 2 Pitch / Trunk: {fmt(measurements.get('trunk_angle_deg'))}",
            f"Calibration: {measurements.get('calibration_status', 'Waiting')}",
        ]
    return [
        f"Shoulder Vision: {fmt(measurements.get('shoulder_vision_deg'))}",
        f"IMU 1 Pitch (Aligned): {fmt(measurements.get('imu1_shoulder_corrected_deg'))}",
        f"Shoulder UKF: {fmt(measurements.get('shoulder_ukf_deg'))}",
        f"Elbow Vision: {fmt(measurements.get('elbow_vision_deg'))}",
        f"IMU 1 Yaw (Aligned): {fmt(measurements.get('imu1_elbow_deg'))}",
        f"Elbow UKF: {fmt(measurements.get('elbow_ukf_deg'))}",
        f"IMU 2 Pitch / Trunk: {fmt(measurements.get('trunk_angle_deg'))}",
        f"Calibration: {measurements.get('calibration_status', 'Both sensors calibrated')}",
    ]


class ApplicationOutputBridge(QObject):
    """
    Qt bridge that polls the single `RehabApplicationController` instance and
    broadcasts read-only `TelemetrySnapshot` updates to the GUI.
    """

    snapshot_updated = Signal(object)       # TelemetrySnapshot
    session_completed = Signal(object)      # SessionResults
    session_error = Signal(str)

    def __init__(
        self,
        controller: Optional[RehabApplicationController] = None,
        simulate_mode: bool = False,
        refresh_hz: float = 30.0,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        if controller is None:
            controller = RehabApplicationController(RehabConfig(show_opencv_window=False))
        else:
            # Suppress separate OpenCV popup window so frames render inside the GUI
            controller.config.show_opencv_window = False

        self.controller: RehabApplicationController = controller
        self._simulate_mode: bool = bool(simulate_mode)
        self._session_thread: Optional[threading.Thread] = None
        self._is_stopping: bool = False
        self._configured_duration: float = float(self.controller.config.record_seconds)

        self._poll_timer = QTimer(self)
        interval_ms = max(15, int(round(1000.0 / max(1.0, float(refresh_hz)))))
        self._poll_timer.setInterval(interval_ms)
        self._poll_timer.timeout.connect(self.poll_once)

    @property
    def simulate_mode(self) -> bool:
        return self._simulate_mode

    def set_simulate_mode(self, enabled: bool) -> None:
        if self.is_session_active:
            return
        self._simulate_mode = bool(enabled)

    @property
    def is_session_active(self) -> bool:
        return self.controller.is_running or (
            self._session_thread is not None and self._session_thread.is_alive()
        )

    def start_polling(self) -> None:
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        self.poll_once()

    def stop_polling(self) -> None:
        self._poll_timer.stop()

    def start_session(self, export_on_finish: bool = True) -> None:
        """
        Launch the exact `main.py` session workflow on a single background thread
        using the existing `self.controller` instance.
        """
        if self.is_session_active:
            return

        self._is_stopping = False
        cfg = self.controller.config
        cfg.show_opencv_window = False
        use_sim = self._simulate_mode

        def _runner() -> None:
            try:
                if use_sim:
                    active_dur = (
                        self._configured_duration
                        if self._configured_duration != 3000.0
                        else 3000.0
                    )
                    total_dur = cfg.warmup_seconds + cfg.calibration_seconds + active_dur
                    cfg.record_seconds = total_dur
                    if cfg.enable_vision:
                        results = app_main.run_live_webcam_with_simulated_sensors(
                            self.controller, total_duration=total_dur
                        )
                    else:
                        results = app_main.run_simulated_experiment(
                            self.controller, active_seconds=active_dur
                        )
                else:
                    cfg.enable_sensors = True
                    cfg.record_seconds = self._configured_duration
                    self.controller.start_experiment()
                    try:
                        self.controller.wait_for_session(duration_seconds=cfg.record_seconds)
                    finally:
                        results = self.controller.stop_experiment(
                            export_recording=export_on_finish,
                            run_analysis=export_on_finish,
                        )
                self.session_completed.emit(results)
            except Exception as exc:
                logger.exception("Application session runner error: %s", exc)
                self.session_error.emit(str(exc))

        self._session_thread = threading.Thread(
            target=_runner,
            name="MainAppSessionRunner",
            daemon=True,
        )
        self._session_thread.start()
        self.poll_once()

    def stop_session(self) -> None:
        """
        Signal the active `main.py` session runner to finish cleanly, export the
        Excel recording, and generate analysis plots without blocking the GUI thread.
        """
        if not self.is_session_active or self._is_stopping:
            return
        self._is_stopping = True
        # Signaling `_stop_event` exits `controller.wait_for_session()` cleanly so
        # the runner thread's `finally` block executes `controller.stop_experiment(...)`
        # exactly once (including `main.run_live_webcam_with_simulated_sensors`).
        self.controller._stop_event.set()

    def reset_calibration(self) -> None:
        """Delegate directly to `controller.reset_calibration()`."""
        if not self.controller.is_running:
            return
        self.controller.reset_calibration()
        self.poll_once()

    def reset_session(self) -> None:
        """Delegate directly to `controller.reset_session()` when idle."""
        if self.is_session_active:
            return
        self.controller.reset_session()
        self.poll_once()

    def read_snapshot(self) -> TelemetrySnapshot:
        """Collect a purely read-only snapshot from `self.controller`."""
        measurements = self.controller.get_current_measurements()
        status = self.controller.get_sensor_status()
        completed = self.controller.get_completed_results()
        frame = self.controller.get_latest_frame()

        s1_snap = self.controller.sensor_manager.get_reading_snapshot(1)
        s2_snap = self.controller.sensor_manager.get_reading_snapshot(2)
        meta = status.get("sensors_metadata") or {}
        v_refs = status.get("vision_references") or {"shoulder": None, "elbow": None}
        is_cal = bool(status.get("is_calibrated", False))

        # Ensure calibration_status and sensor_status inside measurements match latest status
        merged_meas = dict(measurements)
        merged_meas.setdefault("calibration_status", status.get("calibration", "Waiting"))
        merged_meas.setdefault("sensor_status", status.get("sensor", "Starting"))

        cfg = self.controller.config
        total_cal = float(cfg.warmup_seconds + cfg.calibration_seconds)
        lines = build_main_display_lines(merged_meas, is_calibrated=is_cal)

        return TelemetrySnapshot(
            is_running=self.is_session_active,
            is_simulation=self._simulate_mode,
            is_calibrated=is_cal,
            sensor_status=str(status.get("sensor", "Starting")),
            calibration_status=str(status.get("calibration", "Waiting")),
            vision_status=str(status.get("vision", "Idle")),
            posture_status=str(merged_meas.get("posture_status") or "WAITING"),
            elapsed_s=float(merged_meas.get("elapsed_s") or 0.0),
            recorded_samples=int(status.get("recorded_samples") or 0),
            total_calibration_seconds=total_cal,
            recordings_dir=Path(cfg.recordings_dir),
            last_workbook_path=completed.workbook_path,
            measurements=merged_meas,
            shoulder_vision_ref_deg=v_refs.get("shoulder"),
            elbow_vision_ref_deg=v_refs.get("elbow"),
            sensor1_meta=dict(meta.get(1) or {}),
            sensor2_meta=dict(meta.get(2) or {}),
            sensor1_raw_q=s1_snap.raw_quaternion,
            sensor2_raw_q=s2_snap.raw_quaternion,
            sensor1_phase=str(s1_snap.calibration_phase),
            sensor2_phase=str(s2_snap.calibration_phase),
            main_overlay_lines=lines,
            frame_bgr=frame,
        )

    def poll_once(self) -> TelemetrySnapshot:
        snap = self.read_snapshot()
        self.snapshot_updated.emit(snap)
        return snap

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cleanly stop polling and wait for any active session thread on window close."""
        self.stop_polling()
        if self.is_session_active:
            self.controller._stop_event.set()
            if self._session_thread is not None and self._session_thread.is_alive():
                self._session_thread.join(timeout=timeout)
            if self.controller.is_running:
                self.controller.stop_experiment(export_recording=False, run_analysis=False)
