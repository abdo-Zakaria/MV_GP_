# `rehab_app/` — Core Rehabilitation Application Package

This folder contains the core mathematical, sensor acquisition, computer vision, Kalman filtering, Excel recording, and post-experiment analysis logic for the Active Upper Limb Rehabilitation system.

It is completely independent of any Graphical User Interface (GUI) and can be imported and executed headlessly or driven by `main.py` or `rehab_gui/`.

---

## 1. Responsibility of Each Module

| File | Responsibility |
| :--- | :--- |
| `__init__.py` | Re-exports all public classes, constants, and functions so callers can import directly from `rehab_app`. |
| `config.py` | Defines all default constants (matching `rehab_vision_delsys_ukf_Final.py`) and the validated `RehabConfig` dataclass. |
| `calibration.py` | Implements 4-element `(W, X, Y, Z)` quaternion math, 30 s stationary warm-up, 5 s neutral quaternion averaging, relative rotation, Euler conversion, physical axis mapping, and `2.0°` deadband. |
| `sensors.py` | Wraps `AeroPy.TrignoBase`, discovers `OR 16 bits (74 Hz)` mode, maps `ORIENTATION W/X/Y/Z` channel GUIDs, polls YT quaternion packets on a background thread, and enforces the `1.0 s` sensor staleness timeout. |
| `vision.py` | Wraps MediaPipe `PoseLandmarker` (`pose_landmarker_full.task`), smooths 3D landmarks (`alpha = 0.3`), checks visibility (`>= 0.5`), computes 2D Shoulder and Elbow angles, evaluates posture feedback rules, and draws the skeleton and text overlay. |
| `fusion.py` | Implements the scaled sigma-point Unscented Kalman Filter (`AngleUKF`) and `JointFusionPipeline` for Shoulder (`IMU 1 Pitch + Vision`), Elbow (`IMU 1 Yaw + 90° + Vision`), and Trunk (`IMU 2 Pitch`, unfused). |
| `recording.py` | Buffers timestamped raw and processed measurements thread-safely (`SessionRecorder`) and exports a uniquely named 4-sheet Excel workbook (`RawData`, `ProcessedData`, `Metrics`, `Settings`) to `recordings/`. |
| `analysis.py` | Loads a saved Excel workbook from disk (`SessionAnalyzer`), computes pairwise inter-source consistency metrics, and generates 7 Matplotlib PNG plots in `recordings/<workbook_stem>_analysis/`. |
| `controller.py` | Coordinates all modules (`RehabApplicationController`), manages background worker threads, and exposes the public lifecycle and telemetry API. |

---

## 2. Detailed Class and Function Reference

### A. `config.py`
- **Module Constants:**
  - `PROJECT_ROOT`, `DEFAULT_RECORDINGS_DIR`, `DEFAULT_MODEL_ASSET_PATH`
  - `RECORD_SECONDS = 3000.0`, `WARMUP_SECONDS = 30.0`, `CALIBRATION_SECONDS = 5.0`
  - `SENSOR1_INDEX = 0`, `SENSOR2_INDEX = 1`, `SENSOR_STALE_SECONDS = 1.0`, `ZERO_DEADBAND_DEG = 2.0`, `ELBOW_IMU_OFFSET_DEG = 90.0`
  - `CAMERA_INDEX = 0`, `VISIBILITY_MIN = 0.5`, `SHOULDER_Z_TOLERANCE = 0.08`, `LANDMARK_ALPHA = 0.3`, `MIN_POSE_CONFIDENCE = 0.5`
  - `Q_ANGLE = 1.0`, `Q_VELOCITY = 25.0`, `R_IMU = 9.0`, `R_VISION = 16.0`, `INITIAL_P_ANGLE = 100.0`, `INITIAL_P_VELOCITY = 400.0`, `UKF_ALPHA = 0.35`, `UKF_BETA = 2.0`, `UKF_KAPPA = 0.0`
- **`RehabConfig` (dataclass):**
  - `validate()`: Validates all timing, index, visibility, smoothing, and UKF variance parameters. Raises `ValueError` on invalid input.
  - `to_settings_dict()`: Converts configuration fields into a flat serializable dictionary for the Excel `Settings` sheet.

### B. `calibration.py`
- **`normalize(q)`**: Normalizes a 4-tuple `(w, x, y, z)` to unit length; returns `None` if norm `< 1e-8`.
- **`q_conjugate(q)`**: Returns `(w, -x, -y, -z)`, representing the inverse rotation for a unit quaternion.
- **`q_multiply(a, b)`**: Computes the Hamilton product of two quaternions.
- **`average_quaternions(samples)`**: Aligns all sample quaternions to the same hemisphere as `samples[0]` (`dot >= 0`), sums them, and normalizes to obtain the neutral reference quaternion.
- **`quaternion_to_euler(q)`**: Converts `(w, x, y, z)` into ZYX Euler angles `(mathematical_roll, mathematical_pitch, mathematical_yaw)` in degrees.
- **`wrap_deg(a)`**: Wraps an angle in degrees into `[-180.0, 180.0)`.
- **`deadband(a, threshold_deg=2.0)`**: Returns `0.0` if `abs(a) <= threshold_deg`, else `float(a)`.
- **`CalibratedOrientation` (dataclass)**: Stores raw quaternion, calibration phase (`warmup`, `calibrating`, `calibrated_init`, `active`), reference quaternion, relative quaternion, mathematical Euler angles, and mapped `imu_pitch_deg` / `imu_yaw_deg`.
- **`CalibrationManager`**:
  - `start(start_timestamp)` / `reset(new_start_timestamp=None)`: Starts or resets the warm-up and calibration clock and clears saved reference quaternions.
  - `process_quaternion(sensor_number, raw_q, timestamp)`:
    1. If `elapsed < warmup_seconds`: returns `phase="warmup"`, `is_calibrated=False`.
    2. If `warmup_seconds <= elapsed < warmup_seconds + calibration_seconds`: appends `q` to `_samples[sensor_number]`. Once `elapsed >= warmup_seconds + calibration_seconds`, computes `_refs[sensor_number] = average_quaternions(...)` and marks `_calibrated[sensor_number] = True`.
    3. Once calibrated: computes `relative = normalize(q_multiply(q_conjugate(ref), q))`, converts to `(mathematical_roll, mathematical_pitch, mathematical_yaw)`, and maps:
       - `imu_pitch = deadband(mathematical_roll)`
       - `imu_yaw = deadband(mathematical_yaw)`
       - `mathematical_pitch` (physical roll) is ignored for fusion.

### C. `sensors.py`
- **`_import_trigno_base()`**: Safely imports `AeroPy.TrignoBase` from any working directory by temporarily switching to `PROJECT_ROOT` so `clr.AddReference("resources\\DelsysAPI")` succeeds.
- **`DataHandler` & `LinkController`**: Minimal adapter classes expected by `AeroPy.TrignoBase`.
- **`find_or_mode(base, index)`**: Queries `base.getSampleModes(index)` and returns the `"OR 16 bits (74 Hz)"` orientation mode string.
- **`find_quaternion_channels(sensor)`**: Inspects `sensor.channels` and returns `({"w": guid_w, "x": guid_x, "y": guid_y, "z": guid_z}, accuracy_guid)`.
- **`SensorReading` (dataclass)**: Holds the latest raw quaternion, mathematical Euler angles, calibrated `pitch` and `yaw`, `calibration_phase`, monotonic timestamp `time`, and `ready` flag for one sensor.
- **`DelsysSensorManager`**:
  - `start_worker()` / `stop_worker()`: Launches or stops the background `_sensor_worker_loop` thread.
  - `inject_quaternion_sample(sensor_number, raw_q, timestamp=None)`: Passes a raw `(w, x, y, z)` quaternion through `CalibrationManager.process_quaternion()` and updates `_sensor_data[sensor_number]`. Used by both live Delsys polling and simulation mode.
  - `get_sensor(number, axis, now=None)`: Returns the latest calibrated `"pitch"` or `"yaw"` for sensor `number`, or `None` if not ready or older than `sensor_stale_seconds` (`1.0 s`).
  - `get_reading_snapshot(number, now=None)`: Returns a thread-safe copy of `SensorReading` with stale angles cleared if older than `1.0 s`.

### D. `vision.py`
- **`POSE_CONNECTIONS`**: List of 12 landmark index pairs used to draw the upper/lower body skeleton.
- **`calculate_angle(a, b, c)`**: Computes the 2D planar angle at vertex `b` in `[0.0, 180.0]` degrees using `atan2`.
- **`vision_angle(p1, p2, p3, width, height, visibility_min=0.5)`**: Returns `None` if `min(p1.visibility, p2.visibility, p3.visibility) < visibility_min`; otherwise converts normalized coordinates to pixel coordinates and calls `calculate_angle`.
- **`fmt(value)` & `draw_overlay(frame, lines)`**: Formats angle values (`+45.0` or `None`) and renders the right-aligned text block in the top-right corner of the video frame.
- **`VisionMeasurement` (dataclass)**: Holds `shoulder_angle_deg`, `elbow_angle_deg`, `shoulder_z_diff`, `relative_elbow_z`, landmark visibilities, `posture_status`, and `posture_color_bgr`.
- **`PoseVisionProcessor`**:
  - `initialize_detector()`: Loads `pose_landmarker_full.task` into MediaPipe `PoseLandmarker`.
  - `evaluate_landmarks(landmarks, width, height, timestamp, frame_to_annotate=None)`:
    1. Smooths landmark `(x, y, z)` using `LANDMARK_ALPHA = 0.3`.
    2. Draws skeleton lines and circles if `frame_to_annotate` is provided.
    3. Computes `elbow_vis` (`r_shoulder [12], r_elbow [14], r_wrist [16]`) and `shoulder_vis` (`r_hip [24], r_shoulder [12], r_elbow [14]`).
    4. Evaluates posture status (`LANDMARKS NOT VISIBLE`, `WRONG: Keep Shoulders Straight!`, `START POSITION (Ready)`, `RIGHT`, `WRONG`).
  - `process_frame(bgr_frame, timestamp, annotate_frame=False)`: Flips the frame horizontally (if enabled), runs MediaPipe detection, and calls `evaluate_landmarks`.

### E. `fusion.py`
- **`angle_residual(a, b)`**: Shortest-arc signed difference `wrap_deg(a - b)` in `[-180, 180)`.
- **`AngleUKF`**:
  - `weights()`: Computes unscented transform scaling `c` and weights `wm`, `wc` for `n = 2` (`5` sigma points).
  - `circular_mean(sigmas, weights)`: Computes circular mean (`atan2` of weighted `sin`/`cos`) for angle and linear mean for angular velocity.
  - `sigma_points()`: Generates 5 sigma points using Cholesky decomposition of `c * P` (with `1e-8 * I` fallback).
  - `predict(timestamp)`: Propagates sigma points by `dt = min(timestamp - last_time, 0.25)` using constant-velocity kinematics and adds process noise `Q * max(dt, 1e-3)`.
  - `update(measurement, source, timestamp)`: Updates state `x` and covariance `P` using measurement variance `R_IMU = 9.0` (`source="imu"`) or `R_VISION = 16.0` (`source="vision"`), storing the Kalman gain vector `K = [K_angle, K_velocity]` in `last_kalman_gain_by_source[source]`.
- **`fuse_shoulder_angle(ukf, imu_pitch, vision_shoulder, timestamp)`**: Updates Shoulder UKF with `imu_pitch` and `vision_shoulder`.
- **`fuse_elbow_angle(ukf, imu_yaw, vision_elbow, timestamp, elbow_offset_deg=90.0)`**: Adds `+90.0°` to `imu_yaw` (`imu_elbow_angle = imu_yaw + 90.0`) before updating Elbow UKF with IMU and `vision_elbow`.
- **`JointFusionPipeline.step(...)`**: Executes one step across Shoulder UKF, Elbow UKF, and unfused Trunk angle (`imu2_pitch`) and returns a `FusionStepResult`.

### F. `recording.py` and `analysis.py`
- **`RAW_COLUMNS` & `PROCESSED_COLUMNS`**: Exact column schemas for `RawData` (32 columns) and `ProcessedData` (36 columns).
- **`compute_consistency_metrics_table(processed_df)`**: Calculates `MAE_deg`, `RMSE_deg`, `Bias_Signed_Mean_deg`, `Std_Residual_deg`, `Median_Abs_Diff_deg`, `Max_Abs_Diff_deg`, `LoA_95_Lower_deg`, `LoA_95_Upper_deg`, `Pearson_r`, and `Missing_Paired_Pct`.
- **`SessionRecorder`**:
  - `record_step(...)`: Appends one timestamped row to `_raw_rows` and `_proc_rows`.
  - `export_to_excel(...)`: Writes `RawData`, `ProcessedData`, `Metrics`, and `Settings` sheets to a uniquely named `.xlsx` file in `recordings/`.
- **`SessionAnalyzer.analyze_workbook(workbook_path, ...)`**: Reads the saved `.xlsx` file from disk, updates the `Metrics` sheet, and saves 7 diagnostic PNG plots in `recordings/<workbook_stem>_analysis/`.

### G. `controller.py`
- **`RehabApplicationController`**:
  - `start_experiment()` / `stop_experiment(export_recording=True, run_analysis=None)`
  - `reset_session()` / `reset_calibration(new_start_timestamp=None)`
  - `step_session(timestamp, vision_measurement)`
  - `get_current_measurements()` / `get_sensor_status()` / `get_latest_frame()` / `get_completed_results()`
  - `get_settings()` / `update_settings(**kwargs)`

---

## 3. Data Flow Between Modules

```text
sensors.py (DelsysSensorManager._sensor_worker_loop)
   │  Polls raw W, X, Y, Z quaternions from AeroPy.TrignoBase
   ▼
calibration.py (CalibrationManager.process_quaternion)
   │  30 s warm-up -> 5 s neutral quaternion average -> relative quaternion -> Euler
   │  Maps mathematical_roll -> imu_pitch, mathematical_yaw -> imu_yaw (+ 2.0° deadband)
   ▼
controller.py (RehabApplicationController.step_session) ◄── vision.py (PoseVisionProcessor.process_frame)
   │  Combines latest non-stale Sensor 1 & 2 angles with Shoulder & Elbow Vision angles
   ▼
fusion.py (JointFusionPipeline.step)
   │  • Shoulder UKF <- IMU 1 Pitch + Shoulder Vision
   │  • Elbow UKF    <- (IMU 1 Yaw + 90.0°) + Elbow Vision
   │  • Trunk Angle  <- IMU 2 Pitch (unfused)
   ▼
recording.py (SessionRecorder.record_step & export_to_excel)
   │  Writes RawData, ProcessedData, Metrics, Settings to recordings/*.xlsx
   ▼
analysis.py (SessionAnalyzer.analyze_workbook)
      Reads recordings/*.xlsx and generates 7 comparison PNG plots
```

---

## 4. Where to Modify Specific Rehabilitation Logic

- **Change warm-up duration, calibration window, or deadband degrees:** Edit `WARMUP_SECONDS`, `CALIBRATION_SECONDS`, or `ZERO_DEADBAND_DEG` in `rehab_app/config.py`, or modify `CalibrationManager.process_quaternion()` in `rehab_app/calibration.py`.
- **Change physical sensor axis mapping:** Edit `CalibrationManager.process_quaternion()` in `rehab_app/calibration.py` where `mathematical_roll, mathematical_pitch, mathematical_yaw` are assigned to `imu_pitch` and `imu_yaw`.
- **Change Elbow IMU offset (`+90.0°`) or joint-to-sensor assignments:** Edit `fuse_elbow_angle()` and `JointFusionPipeline.step()` in `rehab_app/fusion.py`.
- **Change UKF noise variances (`Q_ANGLE`, `Q_VELOCITY`, `R_IMU`, `R_VISION`):** Edit `rehab_app/config.py` or `AngleUKF.__init__()` in `rehab_app/fusion.py`.
- **Change MediaPipe landmarks or posture feedback rules (`START POSITION`, `RIGHT`, `WRONG`):** Edit `PoseVisionProcessor.evaluate_landmarks()` in `rehab_app/vision.py`.
- **Add a new column to the Excel workbook:** Add the column name to `RAW_COLUMNS` or `PROCESSED_COLUMNS` and populate it inside `SessionRecorder.record_step()` in `rehab_app/recording.py`.

---

## 5. How to Debug and Test `rehab_app/` Independently

You can test `rehab_app/` without launching the GUI or connecting physical hardware:

1. **Run all core unit and mathematical parity tests:**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests/test_rehab_app.py -v
   ```
2. **Test `AngleUKF` and `JointFusionPipeline` directly from Python:**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -c "from rehab_app import JointFusionPipeline; p = JointFusionPipeline(); r = p.step(1.0, imu1_pitch=45.0, imu1_yaw=20.0, imu2_pitch=5.0, shoulder_vision=47.0, elbow_vision=112.0); print('Shoulder UKF:', r.shoulder_ukf_deg, 'Elbow UKF:', r.elbow_ukf_deg, 'Trunk:', r.trunk_angle_deg)"
   ```
3. **Test `CalibrationManager` directly from Python:**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -c "from rehab_app import CalibrationManager; c = CalibrationManager(warmup_seconds=1.0, calibration_seconds=1.0); c.start(0.0); print(c.process_quaternion(1, (1,0,0,0), 0.5).phase); print(c.process_quaternion(1, (1,0,0,0), 1.5).phase); print(c.process_quaternion(1, (1,0,0,0), 2.1).is_calibrated)"
   ```
