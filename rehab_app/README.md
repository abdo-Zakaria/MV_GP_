# 🧠 `rehab_app/` — Core Rehabilitation Application Package

![Architecture GUI-Independent](https://img.shields.io/badge/Architecture-GUI--Independent-22C55E)
![Filter Unscented Kalman Filter](https://img.shields.io/badge/Fusion-AngleUKF-0284C7)

This package contains the core mathematical, Delsys Trigno sensor acquisition, MediaPipe computer vision, dynamic IMU-to-Vision alignment, Unscented Kalman Filtering (UKF), Excel recording, and post-experiment analysis logic for the Active Upper Limb Rehabilitation system.

It is completely independent of any Graphical User Interface and can be run headlessly, driven by [`../main.py`](../main.py), or observed read-only by [`../rehab_monitor_gui/`](../rehab_monitor_gui/README.md).

---

## 📑 Table of Contents

- [📦 Module Responsibilities](#-module-responsibilities)
- [📘 Detailed Class & Function Reference](#-detailed-class--function-reference)
- [📡 Data Flow Between Modules](#-data-flow-between-modules)
- [⚙️ Where to Modify Specific Logic](#️-where-to-modify-specific-logic)
- [🧪 Debugging & Testing Independently](#-debugging--testing-independently)

---

## 📦 Module Responsibilities

| File | Responsibility |
| :--- | :--- |
| [`__init__.py`](__init__.py) | Re-exports all public classes, constants, and helper functions for clean imports from `rehab_app`. |
| [`config.py`](config.py) | Defines default constants (timings, sensor indices, deadband, direction signs, Vision & UKF parameters) and the validated `RehabConfig` dataclass. |
| [`calibration.py`](calibration.py) | Implements `(W, X, Y, Z)` quaternion math, `modes.py`-aligned 30 s warm-up + 5 s neutral quaternion averaging with immediate Stage 3 fallthrough, simultaneous Shoulder/Elbow Vision reference averaging, physical axis mapping, and `2.0°` deadband. |
| [`sensors.py`](sensors.py) | Wraps `AeroPy.TrignoBase`, selects `OR 16 bits (74 Hz)` mode, maps `ORIENTATION W/X/Y/Z` channel GUIDs, polls YT packets with per-sensor `new_quaternion_data` gating (`modes.py`), and enforces the `1.0 s` staleness timeout. |
| [`vision.py`](vision.py) | Wraps MediaPipe `PoseLandmarker` (`pose_landmarker_full.task`), smooths 3D landmarks (`alpha = 0.3`), checks visibility (`>= 0.5`), computes 2D Shoulder & Elbow angles, evaluates posture feedback rules, and draws skeleton/text overlays. |
| [`fusion.py`](fusion.py) | Implements dynamic IMU offset alignment (`align_imu_angle()`), the scaled sigma-point `AngleUKF`, and `JointFusionPipeline` for Shoulder, Elbow, and unfused Trunk angles. |
| [`recording.py`](recording.py) | Thread-safely buffers raw (`RAW_COLUMNS`, 32 cols) and processed (`PROCESSED_COLUMNS`, 43 cols) rows (`SessionRecorder`), computes pairwise consistency metrics, and exports a 4-sheet Excel workbook to `recordings/`. |
| [`analysis.py`](analysis.py) | Loads saved Excel workbooks (`SessionAnalyzer`) and generates 7 Matplotlib PNG diagnostic plots in `recordings/<workbook_stem>_analysis/`. |
| [`controller.py`](controller.py) | Coordinates all subsystems (`RehabApplicationController`), manages background sensor & vision threads, renders the optional OpenCV window, and exposes the public lifecycle & telemetry API. |

---

## 📘 Detailed Class & Function Reference

### ⚙️ `config.py`
- **Key Constants:**
  - `PROJECT_ROOT`, `DEFAULT_RECORDINGS_DIR`, `DEFAULT_MODEL_ASSET_PATH`
  - `RECORD_SECONDS = 3000.0`, `WARMUP_SECONDS = 30.0`, `CALIBRATION_SECONDS = 5.0`
  - `SENSOR1_INDEX = 0`, `SENSOR2_INDEX = 1`, `SENSOR_STALE_SECONDS = 1.0`, `ZERO_DEADBAND_DEG = 2.0`
  - `ELBOW_IMU_OFFSET_DEG = 0.0`, `SHOULDER_IMU_DIRECTION_SIGN = -1.0`, `ELBOW_IMU_DIRECTION_SIGN = -1.0`
  - `CAMERA_INDEX = 0`, `VISIBILITY_MIN = 0.5`, `SHOULDER_Z_TOLERANCE = 0.08`, `LANDMARK_ALPHA = 0.3`, `MIN_POSE_CONFIDENCE = 0.5`
  - `Q_ANGLE = 1.0`, `Q_VELOCITY = 25.0`, `R_IMU = 9.0`, `R_VISION = 16.0`, `INITIAL_P_ANGLE = 100.0`, `INITIAL_P_VELOCITY = 400.0`, `UKF_ALPHA = 0.35`, `UKF_BETA = 2.0`, `UKF_KAPPA = 0.0`
- **`RehabConfig` (dataclass):**
  - `validate()`: Validates timing, sensor indices, direction signs (`+1.0` or `-1.0`), visibility, smoothing, and positive UKF variances.
  - `to_settings_dict()`: Serializes all settings for the Excel `Settings` sheet.

### 📐 `calibration.py`
- **Quaternion & Angle Utilities:** `normalize(q)`, `q_conjugate(q)`, `q_multiply(a, b)`, `average_quaternions(samples)`, `quaternion_to_euler(q)`, `wrap_deg(a)`, `deadband(a, threshold_deg=2.0)`.
- **`CalibratedOrientation` (dataclass):** Stores raw quaternion, calibration phase (`warmup`, `calibrating`, `active`), reference/relative quaternions, mathematical Euler angles, and mapped `imu_pitch_deg` / `imu_yaw_deg`.
- **`CalibrationManager`:**
  - `start(start_timestamp)` / `reset(new_start_timestamp=None)`: Starts or clears IMU quaternion references, Vision references, and sample buffers.
  - `record_vision_sample(shoulder_angle_deg, elbow_angle_deg, timestamp)`: Ignores Vision samples during warm-up, collects valid finite Shoulder and Elbow Vision angles independently during calibration, and finalizes each joint's arithmetic mean once `elapsed >= warmup_seconds + calibration_seconds`.
  - `get_vision_references()` / `get_vision_sample_counts()`: Thread-safe accessors for finalized Vision references and sample counts.
  - `process_quaternion(sensor_number, raw_q, timestamp)` (matches [`../modes.py`](../modes.py)):
    1. **Stage 1 (`elapsed < warmup_seconds`):** Returns `phase="warmup"`, `is_calibrated=False`.
    2. **Stage 2 (`not _calibrated[sensor_number]`):** Appends `q` and checks `calibration_elapsed = elapsed - warmup_seconds >= calibration_seconds`. When reached, averages samples into `_refs[sensor_number]`, sets `_calibrated[sensor_number] = True`, and **falls straight through into Stage 3**.
    3. **Stage 3 (`_calibrated[sensor_number]`):** Computes `relative = normalize(q_multiply(q_conjugate(ref), q))`, converts to `(mathematical_roll, mathematical_pitch, mathematical_yaw)`, and maps `imu_pitch = deadband(mathematical_roll)` and `imu_yaw = deadband(mathematical_yaw)`.

### 📡 `sensors.py`
- **`_import_trigno_base()`:** Temporarily switches CWD to `PROJECT_ROOT` while importing `AeroPy.TrignoBase` so `clr.AddReference("resources\\DelsysAPI")` resolves cleanly from any directory.
- **`find_or_mode(base, index)` & `find_quaternion_channels(sensor)`:** Discovers `"OR 16 bits (74 Hz)"` and maps `ORIENTATION W/X/Y/Z` (plus optional `ORIENTATION ACCURACY`) channel GUIDs.
- **`DelsysSensorManager`:**
  - `_sensor_worker_loop()`: Connects to TrignoBase, configures Sensor 1 & Sensor 2, and polls `PollYTDataByString()` with a per-sensor `new_quaternion_data` guard and `0.005 s` idle sleep (matching `modes.py`).
  - `inject_quaternion_sample(sensor_number, raw_q, timestamp=None)`: Passes a raw quaternion through `CalibrationManager` and updates `SensorReading`.
  - `get_sensor(number, axis, now=None)` & `get_reading_snapshot(number, now=None)`: Returns calibrated angles or clears them if older than `sensor_stale_seconds` (`1.0 s`).

### 📷 `vision.py`
- **`calculate_angle(a, b, c)` & `vision_angle(p1, p2, p3, width, height, visibility_min=0.5)`:** 2D planar joint angle calculation with visibility gating.
- **`fmt(value)` & `draw_overlay(frame, lines)`:** Formats numeric readings (`+45.0` or `None`) and draws the OpenCV right-aligned overlay.
- **`PoseVisionProcessor`:** Loads `pose_landmarker_full.task`, smooths landmarks (`alpha = 0.3`), computes Shoulder (`hip [24] – shoulder [12] – elbow [14]`) and Elbow (`shoulder [12] – elbow [14] – wrist [16]`) angles, evaluates posture feedback (`START POSITION (Ready)`, `RIGHT`, `WRONG ...`, `LANDMARKS NOT VISIBLE`, `NO POSE DETECTED`), and draws skeleton overlays.

### 🧮 `fusion.py`
- **`align_imu_angle(imu_relative, vision_reference, direction_sign=1.0)`:** Computes `Vision_reference + direction_sign * IMU_relative`, returning `None` if either input is missing or non-finite.
- **`AngleUKF`:** 2-state `[angle, angular_velocity]` scaled sigma-point UKF with circular angle averaging (`circular_mean()`), `predict(timestamp)`, and `update(measurement, source, timestamp)` (`R_IMU = 9.0`, `R_VISION = 16.0`), tracking Kalman gains `K` per source.
- **`JointFusionPipeline.step(...)`:**
  - Shoulder: aligns `imu1_pitch` with `shoulder_vision_ref` and `shoulder_direction_sign` (`-1.0`) → `Shoulder UKF`.
  - Elbow: aligns `imu1_yaw` with `elbow_vision_ref` and `elbow_direction_sign` (`-1.0`) → `Elbow UKF` (no duplicate static `+90.0°` offset).
  - Trunk: passes `imu2_pitch` directly as `trunk_angle_deg` (unfused).

### 📊 `recording.py`, `analysis.py`, and `controller.py`
- **`SessionRecorder`:** Buffers `RawData` (32 cols) and `ProcessedData` (43 cols) and exports 4-sheet `.xlsx` workbooks (`RawData`, `ProcessedData`, `Metrics`, `Settings`) via `export_to_excel()`.
- **`SessionAnalyzer.analyze_workbook()`:** Reads saved `.xlsx` workbooks and generates 7 Matplotlib diagnostic PNG plots.
- **`RehabApplicationController`:** Exposes `start_experiment()`, `stop_experiment()`, `reset_calibration()`, `reset_session()`, `step_session()`, `get_current_measurements()`, `get_sensor_status()`, `get_latest_frame()`, `get_completed_results()`, `get_settings()`, and `update_settings()`. When `show_opencv_window=True`, displays the 6-line raw+vision overlay during calibration and 8-line aligned+UKF overlay after calibration.

---

## 📡 Data Flow Between Modules

```text
sensors.py (DelsysSensorManager._sensor_worker_loop)
   │  Polls W, X, Y, Z quaternions (per-sensor new_quaternion_data guard)
   ▼
calibration.py (CalibrationManager.process_quaternion & record_vision_sample)
   │  30 s warm-up -> 5 s neutral quaternion & Vision reference averaging
   │  Relative quaternion -> Euler -> imu_pitch = deadband(roll), imu_yaw = deadband(yaw)
   ▼
controller.py (RehabApplicationController.step_session) ◄── vision.py (PoseVisionProcessor.process_frame)
   ▼
fusion.py (JointFusionPipeline.step)
   │  • Shoulder UKF <- (shoulder_vision_ref - imu1_pitch) + Shoulder Vision
   │  • Elbow UKF    <- (elbow_vision_ref    - imu1_yaw)   + Elbow Vision
   │  • Trunk Angle  <- imu2_pitch (unfused)
   ▼
recording.py (SessionRecorder) ──► recordings/*.xlsx ──► analysis.py (SessionAnalyzer -> 7 PNGs)
```

---

## ⚙️ Where to Modify Specific Logic

- **Warm-up/calibration durations, deadband, or IMU direction signs:** Edit `WARMUP_SECONDS`, `CALIBRATION_SECONDS`, `ZERO_DEADBAND_DEG`, `SHOULDER_IMU_DIRECTION_SIGN`, or `ELBOW_IMU_DIRECTION_SIGN` in [`config.py`](config.py).
- **Quaternion averaging or physical axis mapping:** Edit `CalibrationManager.process_quaternion()` in [`calibration.py`](calibration.py).
- **Dynamic alignment equation or UKF tuning:** Edit `align_imu_angle()`, `AngleUKF`, or `JointFusionPipeline.step()` in [`fusion.py`](fusion.py) (and UKF defaults in [`config.py`](config.py)).
- **MediaPipe landmarks or posture feedback rules:** Edit `PoseVisionProcessor.evaluate_landmarks()` in [`vision.py`](vision.py).
- **Excel columns or consistency metrics:** Edit `RAW_COLUMNS`, `PROCESSED_COLUMNS`, `SessionRecorder.record_step()`, or `compute_consistency_metrics_table()` in [`recording.py`](recording.py).

---

## 🧪 Debugging & Testing Independently

Run core verification tests from the `Python/` root directory without launching the GUI or connecting hardware:

```powershell
# Run all core unit, alignment, and pipeline tests
python -m unittest tests.test_rehab_app -v

# Quick standalone check of dynamic alignment + JointFusionPipeline
python -c "from rehab_app import JointFusionPipeline; p = JointFusionPipeline(); r = p.step(1.0, imu1_pitch=-30.0, imu1_yaw=-15.0, imu2_pitch=5.0, shoulder_vision=72.0, elbow_vision=111.0, shoulder_vision_ref=42.5, elbow_vision_ref=96.0); print('Shoulder Aligned/UKF:', r.imu1_shoulder_corrected_deg, r.shoulder_ukf_deg, 'Elbow Aligned/UKF:', r.imu1_elbow_deg, r.elbow_ukf_deg, 'Trunk:', r.trunk_angle_deg)"
```
