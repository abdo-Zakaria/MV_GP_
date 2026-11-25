# `tests/` — Automated Unit, Pipeline, and GUI Test Suite

This folder contains the automated verification tests for both the core rehabilitation package (`rehab_app/`) and the PySide6 graphical user interface (`rehab_gui/`).

---

## 1. What Each Test File Tests

| Test File | Target Package | Purpose |
| :--- | :--- | :--- |
| `test_rehab_app.py` | `rehab_app/` & `main.py` | Verifies 100% mathematical equivalence against the original reference script (`rehab_vision_delsys_ukf_Final.py`), Delsys sensor mode/channel helpers, 4-sheet Excel recording, missing-data preservation, and post-experiment plot generation. |
| `test_rehab_gui.py` | `rehab_gui/` & `gui_main.py` | Verifies PySide6 GUI widget creation, `Images/` asset loading, `PALETTE` stylesheet generation, button guards before and after calibration, live telemetry card and video frame updates, settings validation, and Excel results loading. |

---

## 2. Detailed Breakdown of Every Test Case

### A. `tests/test_rehab_app.py`

#### Class 1: `TestMathematicalEquivalence`
1. **`test_quaternion_and_angle_helpers`**
   - **Verifies:** `normalize()`, `q_conjugate()`, `q_multiply()`, `average_quaternions()`, `quaternion_to_euler()`, `wrap_deg()`, `deadband()`, and `angle_residual()` produce the exact same outputs (to `1e-12`) as the original functions in `rehab_vision_delsys_ukf_Final.py`.
2. **`test_vision_angle_and_smoothing_parity`**
   - **Verifies:** `calculate_angle()` and `vision_angle()` match `rehab_vision_delsys_ukf_Final.py` to `1e-12`, landmarks with visibility `< 0.5` return `None`, and `PoseVisionProcessor.evaluate_landmarks()` computes the expected 2D Elbow (`90.0°`) and Shoulder (`0.0°`) angles with exponential smoothing (`LANDMARK_ALPHA = 0.3`).
3. **`test_ukf_and_fusion_exact_parity`**
   - **Verifies:** Over a 50-step sequence of timestamps with periodic missing vision measurements, `AngleUKF`, `fuse_shoulder_angle()`, and `fuse_elbow_angle()` produce identical fused outputs, state vectors `x = [angle, velocity]`, and covariance matrices `P` (to `1e-12`) as `rehab_vision_delsys_ukf_Final.py`.
4. **`test_elbow_90_offset_and_trunk_unfused`**
   - **Verifies:** `JointFusionPipeline.step()` applies the `+90.0°` offset to `IMU 1 Yaw` before updating the Elbow UKF (`15.0° + 90.0° = 105.0°`), fuses `IMU 1 Pitch` in the Shoulder UKF, and passes `IMU 2 Pitch` directly to `trunk_angle_deg` without UKF fusion.
5. **`test_calibration_warmup_neutral_and_axis_mapping`**
   - **Verifies:** `CalibrationManager.process_quaternion()` returns `phase="warmup"` during the 30 s warm-up, `phase="calibrating"` during the 5 s neutral window, finalizes calibration at `t >= 35.0 s`, and maps `mathematical_roll -> imu_pitch_deg` and `mathematical_yaw -> imu_yaw_deg` while ignoring `mathematical_pitch`.

#### Class 2: `TestSensorsAndRecordingAndAnalysis`
6. **`test_sensor_mode_and_channel_helpers`**
   - **Verifies:** `find_or_mode()` selects `"OR 16 bits (74 Hz)"` from a list of sensor modes, and `find_quaternion_channels()` maps `"Orientation W"`, `"Orientation X"`, `"Orientation Y"`, `"Orientation Z"`, and `"Orientation Accuracy"` channel names to lowercase GUID dictionary keys `{"w", "x", "y", "z"}`.
7. **`test_simulated_experiment_recording_and_analysis`**
   - **Verifies:**
     - `controller.update_settings()` and `controller.get_settings()` update and read `RehabConfig` values.
     - `run_simulated_experiment()` exports a valid `.xlsx` workbook containing all 4 sheets (`RawData`, `ProcessedData`, `Metrics`, `Settings`) with exact column schemas (`RAW_COLUMNS`, `PROCESSED_COLUMNS`).
     - Simulated camera occlusion intervals are preserved as `NaN` in `ProcessedData["shoulder_vision_deg"]` without silent interpolation.
     - Actual UKF Kalman gains (`shoulder_k_imu_angle`, `elbow_k_imu_angle`) are recorded.
     - `SessionAnalyzer` generates all 7 non-empty PNG plot files (`shoulder_angles`, `elbow_angles`, `trunk_angle`, `shoulder_differences`, `elbow_differences`, `kalman_gains`, `ukf_consistency_distributions`).

---

### B. `tests/test_rehab_gui.py`

#### Class: `TestRehabGUI` (Runs with `QT_QPA_PLATFORM=offscreen`)
1. **`test_theme_and_image_assets_exist`**
   - **Verifies:** All required image files in `Images/` (`delsys.png`, `window_icon.png`, `checked.png`, `unchecked.png`) exist on disk and `build_stylesheet()` compiles a valid Qt stylesheet containing `PALETTE` colors and checkbox icon URLs.
2. **`test_dashboard_controls_and_live_telemetry_updates`**
   - **Verifies:**
     - `Start Experiment` and `Stop Experiment` buttons are disabled before sensors are connected and calibrated.
     - During warm-up, `Start Experiment` remains disabled.
     - Once calibration reaches 100%, `Start Experiment` becomes enabled and `calibration_progress.value() == 100`.
     - Clicking `Start Experiment` enables `Stop Experiment` and updates the Shoulder, Elbow, and Trunk telemetry cards and live `QPixmap` video display.
3. **`test_settings_and_results_tabs`**
   - **Verifies:**
     - Modifying spinboxes in `SettingsTab` and calling `apply_settings()` updates `controller.config`.
     - `ResultsTab` discovers the exported `.xlsx` workbook in `recordings/`, populates `plot_selector` with all 7 generated diagnostic plots, and loads the `Metrics` sheet into `metrics_table`.

---

## 3. How to Run All Tests and Individual Tests

From the `Python` project root directory:

- **Run the entire test suite (all 10 tests across both files):**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest discover -s tests -v
  ```
- **Run only the core mathematical and pipeline tests (`test_rehab_app.py`):**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests/test_rehab_app.py -v
  ```
- **Run only the PySide6 GUI tests (`test_rehab_gui.py`):**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests/test_rehab_gui.py -v
  ```
- **Run a single specific test case:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests.test_rehab_app.TestMathematicalEquivalence.test_ukf_and_fusion_exact_parity -v
  ```

---

## 4. Expected Results and Interpreting Failures

- **Expected Output:** Every test prints `... ok` and ends with `Ran 10 tests in ~6.0s — OK`.
- **Interpreting Failures:**
  - Failure in `TestMathematicalEquivalence`: Indicates that a formula, constant, deadband threshold, axis mapping, or UKF equation in `rehab_app/` diverged from `rehab_vision_delsys_ukf_Final.py`.
  - Failure in `test_simulated_experiment_recording_and_analysis`: Indicates a mismatch in `RAW_COLUMNS` / `PROCESSED_COLUMNS`, an openpyxl file-write issue, or a missing plot in `rehab_app/analysis.py`.
  - Failure in `TestRehabGUI`: Indicates a broken widget signal/slot connection, missing image asset in `Images/`, or changed button state guard in `rehab_gui/`.

---

## 5. How to Add New Tests

1. **For core math, sensor, fusion, recording, or analysis changes:**
   - Open `tests/test_rehab_app.py`.
   - Add a `test_<feature_name>(self)` method to `TestMathematicalEquivalence` or `TestSensorsAndRecordingAndAnalysis`.
   - Use `tempfile.TemporaryDirectory()` whenever testing Excel exports or plot files so test artifacts are cleaned up automatically and never clutter `recordings/`.
2. **For GUI widget, layout, or workflow changes:**
   - Open `tests/test_rehab_gui.py`.
   - Add a `test_<gui_feature>(self)` method to `TestRehabGUI`.
   - Always pass `show_opencv_window=False`, `enable_sensors=False`, and `enable_vision=False` in `RehabConfig` when writing unit tests so they run deterministically in offscreen mode without requiring hardware.

---

## 6. Mock / Simulation Tests vs. Real Hardware Tests

- **All 10 automated tests in `tests/` use deterministic mock/simulated data** (`DummyBase`, `DummySensor`, `DummyLandmark`, and synthetic `(W, X, Y, Z)` quaternion trajectories via `inject_quaternion_sample()`). They run completely offline without physical Delsys Trigno sensors or a webcam.
- **Physical hardware verification** (testing the USB RF receiver base station, physical Trigno sensors in `OR 16 bits (74 Hz)` mode, and live camera capture) is performed interactively by running `python gui_main.py` or `python main.py` with the Delsys receiver and two paired sensors powered on.
