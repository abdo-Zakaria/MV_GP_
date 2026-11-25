"""
Main entry point for the modular rehabilitation application.

Execution Modes:
1. Live webcam + real Delsys Trigno sensors (default):
       python main.py
2. Live webcam + simulated Delsys Trigno sensors (test without Delsys hardware):
       python main.py --simulate --warmup 5 --calibration 3 --duration 60
3. Headless simulation (no webcam or sensors required, used for automated verification):
       python main.py --simulate --no-window --no-vision --warmup 2 --calibration 1 --duration 4
4. Analyze an existing saved Excel recording:
       python main.py --analyze-file recordings/<filename>.xlsx
"""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
import sys
import threading
import time

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rehab_app import (
    RehabApplicationController,
    RehabConfig,
    SessionAnalyzer,
    SessionResults,
    VisionMeasurement,
)

logger = logging.getLogger(__name__)


def _euler_deg_to_quaternion(roll_deg: float, pitch_deg: float, yaw_deg: float):
    """
    Generate a synthetic unit quaternion (w, x, y, z) from mathematical Euler angles.
    Used ONLY in `--simulate` mode to create mock quaternion packets when physical
    Delsys sensors are not connected.
    """
    r = math.radians(roll_deg) * 0.5
    p = math.radians(pitch_deg) * 0.5
    y = math.radians(yaw_deg) * 0.5
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )


def _simulated_sensor_quaternions(elapsed: float, cal_end: float):
    """Return synthetic (q1, q2) unit quaternions for Sensor 1 and Sensor 2 at `elapsed` seconds."""
    if elapsed <= cal_end:
        neutral_q = _euler_deg_to_quaternion(0.0, 0.0, 0.0)
        return neutral_q, neutral_q

    active_t = elapsed - cal_end
    true_shoulder = 60.0 + 25.0 * math.sin(2.0 * math.pi * 0.25 * active_t)
    true_elbow = 125.0 + 30.0 * math.sin(2.0 * math.pi * 0.2 * active_t)
    true_trunk = 8.0 + 5.0 * math.sin(2.0 * math.pi * 0.15 * active_t)

    # Physical axis mapping: mathematical_roll -> IMU Pitch, mathematical_yaw -> IMU Yaw
    q1 = _euler_deg_to_quaternion(
        roll_deg=true_shoulder + 1.2 * math.sin(7.0 * active_t),
        pitch_deg=15.0,
        yaw_deg=(true_elbow - 90.0) + 1.5 * math.cos(5.0 * active_t),
    )
    q2 = _euler_deg_to_quaternion(
        roll_deg=true_trunk + 0.8 * math.sin(4.0 * active_t),
        pitch_deg=-5.0,
        yaw_deg=3.0,
    )
    return q1, q2


def run_simulated_experiment(
    controller: RehabApplicationController,
    active_seconds: float = 10.0,
    rate_hz: float = 30.0,
) -> SessionResults:
    """
    Run a deterministic offline simulation (no physical camera or Delsys sensors needed)
    that tests warm-up, neutral calibration, UKF fusion (+90 deg elbow offset,
    unfused trunk angle), Excel recording, and post-experiment analysis.
    """
    c = controller.config
    logger.info(
        "Starting simulated experiment (warmup=%.1fs, cal=%.1fs, active=%.1fs)...",
        c.warmup_seconds,
        c.calibration_seconds,
        active_seconds,
    )
    controller.reset_session()
    t0 = 1000.0
    controller.calibration_manager.start(t0)
    controller.sensor_manager.set_status("Simulated Delsys OR 16 bits (74 Hz)")

    dt = 1.0 / rate_hz
    cal_end = c.warmup_seconds + c.calibration_seconds
    steps = int(round((cal_end + active_seconds) * rate_hz))

    for step_idx in range(steps + 1):
        elapsed = step_idx * dt
        ts = t0 + elapsed
        q1, q2 = _simulated_sensor_quaternions(elapsed, cal_end)
        controller.sensor_manager.inject_quaternion_sample(1, q1, timestamp=ts)
        controller.sensor_manager.inject_quaternion_sample(2, q2, timestamp=ts)

        if elapsed <= cal_end:
            vis = VisionMeasurement(
                timestamp=ts,
                pose_detected=True,
                shoulder_angle_deg=45.0,
                elbow_angle_deg=95.0,
                shoulder_z_diff=0.02,
                relative_elbow_z=0.01,
                r_hip_visibility=0.98,
                r_shoulder_visibility=0.98,
                l_shoulder_visibility=0.97,
                r_elbow_visibility=0.96,
                r_wrist_visibility=0.95,
                posture_status="START POSITION (Ready)",
            )
        else:
            active_t = elapsed - cal_end
            # Simulate brief camera occlusion to verify missing-data preservation in Excel
            if int(active_t * 10) % 17 == 0:
                vis = VisionMeasurement(
                    timestamp=ts,
                    pose_detected=False,
                    posture_status="LANDMARKS NOT VISIBLE",
                )
            else:
                true_sh = 60.0 + 25.0 * math.sin(2.0 * math.pi * 0.25 * active_t)
                true_el = 125.0 + 30.0 * math.sin(2.0 * math.pi * 0.2 * active_t)
                v_sh = true_sh + 2.5 * math.cos(3.0 * active_t)
                v_el = true_el - 2.0 * math.sin(4.0 * active_t)
                status = "RIGHT" if 130.0 <= v_el <= 160.0 else "START POSITION (Ready)"
                vis = VisionMeasurement(
                    timestamp=ts,
                    pose_detected=True,
                    shoulder_angle_deg=v_sh,
                    elbow_angle_deg=v_el,
                    shoulder_z_diff=0.03,
                    relative_elbow_z=-0.06 if v_el >= 130.0 else 0.01,
                    r_hip_visibility=0.95,
                    r_shoulder_visibility=0.96,
                    l_shoulder_visibility=0.94,
                    r_elbow_visibility=0.93,
                    r_wrist_visibility=0.92,
                    posture_status=status,
                )
        controller.step_session(timestamp=ts, vision_measurement=vis)

    return controller.stop_experiment(export_recording=True, run_analysis=True)


def run_live_webcam_with_simulated_sensors(
    controller: RehabApplicationController,
    total_duration: float,
) -> SessionResults:
    """
    Open the live webcam + MediaPipe window while streaming simulated 74 Hz
    Delsys quaternion packets in a background thread.
    """
    stop_sim = threading.Event()
    c = controller.config
    cal_end = c.warmup_seconds + c.calibration_seconds

    def _sim_sensor_loop() -> None:
        start = time.monotonic()
        controller.calibration_manager.start(start)
        controller.sensor_manager.set_status("Simulated Delsys (74 Hz)")
        period = 1.0 / 74.0
        while not stop_sim.is_set():
            now = time.monotonic()
            elapsed = now - start
            if elapsed >= total_duration:
                break
            q1, q2 = _simulated_sensor_quaternions(elapsed, cal_end)
            controller.sensor_manager.inject_quaternion_sample(1, q1, timestamp=now)
            controller.sensor_manager.inject_quaternion_sample(2, q2, timestamp=now)
            time.sleep(period)

    controller.config.enable_sensors = False
    controller.start_experiment()
    sim_thread = threading.Thread(target=_sim_sensor_loop, name="SimulatedDelsysWorker", daemon=True)
    sim_thread.start()
    try:
        controller.wait_for_session(duration_seconds=total_duration)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        stop_sim.set()
        sim_thread.join(timeout=2.0)
        return controller.stop_experiment(export_recording=True, run_analysis=True)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Modular Rehabilitation Application (MediaPipe + Delsys Trigno + UKF)"
    )
    parser.add_argument("--duration", type=float, default=3000.0, help="Maximum recording duration in seconds.")
    parser.add_argument("--warmup", type=float, default=30.0, help="Stationary warm-up time in seconds.")
    parser.add_argument("--calibration", type=float, default=5.0, help="Neutral calibration window in seconds.")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index.")
    parser.add_argument(
        "--show-window",
        dest="show_window",
        action="store_true",
        default=True,
        help="Open OpenCV real-time webcam preview window (enabled by default).",
    )
    parser.add_argument(
        "--no-window",
        dest="show_window",
        action="store_false",
        help="Run headless without opening the OpenCV preview window.",
    )
    parser.add_argument("--no-sensors", action="store_true", help="Disable Delsys sensor connection.")
    parser.add_argument("--no-vision", action="store_true", help="Disable camera/MediaPipe vision worker.")
    parser.add_argument("--simulate", action="store_true", help="Stream simulated Delsys sensor data.")
    parser.add_argument("--gui", action="store_true", help="Launch the PySide6 graphical user interface.")
    parser.add_argument("--analyze-file", type=str, default=None, help="Path to an existing Excel workbook to analyze.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)

    # Option 0: Launch the PySide6 GUI
    if args.gui:
        from gui_main import launch_gui
        gui_argv = [
            "--warmup", str(args.warmup),
            "--calibration", str(args.calibration),
            "--camera-index", str(args.camera_index),
        ]
        if args.simulate:
            gui_argv.append("--simulate")
        return launch_gui(gui_argv)

    # Option 1: Re-analyze an existing Excel recording workbook
    if args.analyze_file:
        result = SessionAnalyzer().analyze_workbook(Path(args.analyze_file))
        print(f"Workbook analyzed: {result.workbook_path}")
        print(f"Analysis plots directory: {result.output_dir}")
        print(result.metrics_df.to_string(index=False))
        return 0

    # Option 2: Create configuration and application controller
    config = RehabConfig(
        record_seconds=args.duration,
        warmup_seconds=args.warmup,
        calibration_seconds=args.calibration,
        camera_index=args.camera_index,
        show_opencv_window=args.show_window,
        enable_sensors=not (args.no_sensors or args.simulate),
        enable_vision=not args.no_vision,
    )
    controller = RehabApplicationController(config=config)

    # Option 3: Run with simulated Delsys sensors
    if args.simulate:
        active_dur = args.duration if args.duration != 3000.0 else 15.0
        total_dur = args.warmup + args.calibration + active_dur
        controller.config.record_seconds = total_dur
        if args.show_window and not args.no_vision:
            results = run_live_webcam_with_simulated_sensors(controller, total_duration=total_dur)
        else:
            results = run_simulated_experiment(controller, active_seconds=active_dur)
        print(f"Simulated session exported to: {results.workbook_path}")
        if results.analysis_result is not None:
            print(f"Analysis plots saved to: {results.analysis_result.output_dir}")
            print(results.analysis_result.metrics_df.to_string(index=False))
        return 0

    # Option 4: Run live with real Delsys Trigno sensors and webcam
    controller.start_experiment()
    try:
        controller.wait_for_session(duration_seconds=args.duration)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        results = controller.stop_experiment(export_recording=True, run_analysis=True)
        print(f"Recording exported to: {results.workbook_path}")
        if results.analysis_result is not None:
            print(f"Analysis plots saved to: {results.analysis_result.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
