# 🧪 `tests/` — Automated Unit, Pipeline, and GUI Test Suite

![Test Runner unittest](https://img.shields.io/badge/Runner-unittest-22C55E)
![GUI Mode Offscreen Qt](https://img.shields.io/badge/GUI%20Tests-Offscreen%20Qt-0284C7)

This folder contains the automated verification tests for the core rehabilitation package ([`../rehab_app/`](../rehab_app/README.md)), [`../main.py`](../main.py), and the standalone PySide6 GUI ([`../rehab_monitor_gui/`](../rehab_monitor_gui/README.md)).

---

## 📦 Test Files Overview

| Test File | Target | Status | Purpose |
| :--- | :--- | :--- | :--- |
| [`test_rehab_app.py`](test_rehab_app.py) | `rehab_app/` & `main.py` | **Active** (8 tests) | Verifies mathematical parity with `rehab_vision_delsys_ukf_Final.py`, `modes.py`-aligned calibration & continuous updates, dynamic IMU-to-Vision offset alignment (`sign = -1.0`), sensor helpers, 4-sheet Excel export, and 7-plot analysis generation. |
| [`test_rehab_monitor_gui.py`](test_rehab_monitor_gui.py) | `rehab_monitor_gui/` & `gui_main.py` | **Active** (2 tests) | Verifies single-controller execution, suppressed OpenCV popup (`show_opencv_window=False`), continuous GUI updates matching `controller.get_current_measurements()` verbatim, and end-to-end delegation to `main.py` with Excel/plot loading. |
| [`test_rehab_gui.py`](test_rehab_gui.py) | Deprecated `rehab_gui/` | **Legacy** | Left over from the previously removed `rehab_gui/` package; do not include it when running the active test suite. |

---

## 📋 Detailed Breakdown of Active Test Cases

### 1. [`tests/test_rehab_app.py`](test_rehab_app.py)

#### `TestMathematicalEquivalence`
1. **`test_quaternion_and_angle_helpers`** — Verifies `normalize()`, `q_conjugate()`, `q_multiply()`, `average_quaternions()`, `quaternion_to_euler()`, `wrap_deg()`, `deadband()`, and `angle_residual()` match `rehab_vision_delsys_ukf_Final.py` to `1e-12`.
2. **`test_vision_angle_and_smoothing_parity`** — Verifies `calculate_angle()`, `vision_angle()`, visibility `< 0.5` gating, and `PoseVisionProcessor.evaluate_landmarks()` smoothing (`LANDMARK_ALPHA = 0.3`).
3. **`test_ukf_and_fusion_exact_parity`** — Verifies `AngleUKF`, `fuse_shoulder_angle()`, and `fuse_elbow_angle()` produce identical states `x` and covariances `P` (to `1e-12`) over a 50-step trajectory with periodic missing Vision frames.
4. **`test_dynamic_offset_alignment_and_trunk_unfused`** — Verifies dynamic Vision-reference alignment with default direction signs (`-1.0` for both Shoulder and Elbow) and confirms Trunk (`IMU 2 Pitch`) remains unfused.
5. **`test_dynamic_alignment_calibration_signs_missing_and_reset`** — Verifies Vision sample filtering during warm-up/calibration (`None`/`NaN` ignored), independent Shoulder/Elbow Vision reference averaging, inverted direction signs (`-1.0`), `reset()` clearing, and safe `None` handling when a Vision reference is missing.
6. **`test_calibration_warmup_neutral_and_axis_mapping`** — Verifies Stage 1 (`warmup`), Stage 2 (`calibrating`), immediate Stage 3 (`active`) fallthrough upon calibration completion (matching `modes.py`), physical axis mapping, and continuous non-constant IMU angle updates across varying orientations.

#### `TestSensorsAndRecordingAndAnalysis`
7. **`test_sensor_mode_and_channel_helpers`** — Verifies `find_or_mode()` selects `"OR 16 bits (74 Hz)"` and `find_quaternion_channels()` maps `W/X/Y/Z` and `Accuracy` channel GUIDs.
8. **`test_simulated_experiment_recording_and_analysis`** — Verifies `controller.update_settings()`, `run_simulated_experiment()`, 4-sheet Excel export (`RawData`, `ProcessedData`, `Metrics`, `Settings`) with exact `RAW_COLUMNS` / `PROCESSED_COLUMNS`, `NaN` missing-data preservation, UKF Kalman gain logging, and generation of all 7 PNG diagnostic plots.

### 2. [`tests/test_rehab_monitor_gui.py`](test_rehab_monitor_gui.py)

#### `TestRehabMonitorGUI` (Runs with `QT_QPA_PLATFORM=offscreen`)
1. **`test_single_controller_instance_and_continuous_exact_output_matching`** — Verifies:
   - `RehabMonitorWindow` binds to the single `RehabApplicationController` and forces `show_opencv_window=False`.
   - Warm-up (`6`-line mirror), neutral calibration (`100%` progress, Shoulder & Elbow Vision references), and active stages (`8`-line mirror) update continuously.
   - Every GUI label (`Shoulder Vision`, `IMU 1 Pitch Raw/Aligned`, `Shoulder UKF`, `Elbow Vision`, `IMU 1 Yaw Raw/Aligned`, `Elbow UKF`, `Trunk`, `Posture Status`) matches `controller.get_current_measurements()` verbatim.
2. **`test_bridge_delegates_session_to_main_without_duplicating_pipeline`** — Verifies `ApplicationOutputBridge.start_session()` delegates to `main.py`, exports a valid `.xlsx` workbook, and loads the `Metrics` table and all 7 diagnostic PNG plots in `SessionResultsPanel`.

---

## 🚀 How to Run Tests

From the `Python/` project root directory:

- **Run all active tests (core + new GUI — 10 tests total):**
  ```powershell
  python -m unittest tests.test_rehab_app tests.test_rehab_monitor_gui -v
  ```
- **Run only core application tests (`8` tests):**
  ```powershell
  python -m unittest tests.test_rehab_app -v
  ```
- **Run only new GUI tests (`2` tests, offscreen Qt):**
  ```powershell
  python -m unittest tests.test_rehab_monitor_gui -v
  ```
- **Run a single test method:**
  ```powershell
  python -m unittest tests.test_rehab_app.TestMathematicalEquivalence.test_calibration_warmup_neutral_and_axis_mapping -v
  ```

---

## ✅ Expected Output & Interpreting Failures

- **Expected Result:** Every test prints `... ok` and ends with `Ran 10 tests in ~7–9s — OK`.
- **Interpreting Failures:**
  - Failure in `TestMathematicalEquivalence`: A constant, calibration stage transition, dynamic alignment sign, axis mapping, or UKF equation in `rehab_app/` changed unexpectedly.
  - Failure in `TestSensorsAndRecordingAndAnalysis`: A schema mismatch in `RAW_COLUMNS` / `PROCESSED_COLUMNS`, Excel write error, or missing Matplotlib plot in `rehab_app/analysis.py`.
  - Failure in `TestRehabMonitorGUI`: A GUI display label diverged from `controller.get_current_measurements()`, `show_opencv_window` was not suppressed, or `SessionResultsPanel` failed to load exported files.

---

## ➕ Adding New Tests & Mock vs. Hardware Scope

- **All automated tests use deterministic mock/simulated inputs** (`DummyBase`, `DummySensor`, `DummyLandmark`, and synthetic quaternions via `inject_quaternion_sample()`), requiring no physical Delsys sensors or webcam.
- **Physical hardware verification** (Delsys USB RF receiver, two paired sensors in `OR 16 bits (74 Hz)` mode, and live webcam) is performed interactively via `python main.py` or `python gui_main.py`.
- When adding new tests, always use `tempfile.TemporaryDirectory()` for Excel/plot outputs and pass `show_opencv_window=False`, `enable_sensors=False`, and `enable_vision=False` for deterministic offscreen execution.
