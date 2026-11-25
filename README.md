<<<<<<< HEAD
# Upper-Limb Rehabilitation Application (MediaPipe Vision + Delsys Trigno IMUs + UKF Fusion + PySide6 GUI)

This project is a modular, class-based Python rehabilitation monitoring and data-acquisition application. It combines **MediaPipe Pose** computer vision with **Delsys Trigno** wireless orientation sensors (`OR 16 bits (74 Hz)` quaternion streaming), performs **30 s warm-up + 5 s neutral quaternion calibration**, fuses upper-limb joint angles in real time using **Unscented Kalman Filters (UKFs)**, records every session into a **4-sheet Excel workbook**, and generates **post-experiment comparison metrics and diagnostic plots**.

It can be operated through either the **PySide6 Graphical User Interface (`gui_main.py`)** or the **Command-Line Interface (`main.py`)**.

---

## A. Project Structure

```text
Python/
├── rehab_app/                          # Core modular rehabilitation package (independent of GUI)
│   ├── __init__.py                     # Package exports for clean imports
│   ├── config.py                       # Default constants and RehabConfig validation
│   ├── calibration.py                  # Quaternion math, warm-up, neutral calibration, axis mapping
│   ├── sensors.py                      # Delsys Trigno connection, OR 16 bits mode, WXYZ polling
│   ├── vision.py                       # MediaPipe pose detection, smoothing, 2D angles, overlay
│   ├── fusion.py                       # AngleUKF and Shoulder / Elbow / Trunk fusion rules
│   ├── recording.py                    # SessionRecorder and 4-sheet Excel workbook export
│   ├── analysis.py                     # Excel-loaded consistency metrics and 7 Matplotlib plots
│   └── controller.py                   # RehabApplicationController coordinating all subsystems
├── rehab_gui/                          # PySide6 Graphical User Interface package
│   ├── __init__.py                     # GUI package exports
│   ├── theme.py                        # Visual theme, Delsys color palette, and Images/ asset paths
│   ├── main_window.py                  # RehabMainWindow (header bar, 30 Hz refresh timer, tab container)
│   ├── dashboard_tab.py                # Live webcam view, posture banner, angle cards, experiment controls
│   ├── settings_tab.py                 # Organized settings form for camera, Delsys, calibration, and UKF
│   └── results_tab.py                  # Recorded Excel workbook browser, plot viewer, and metrics table
├── tests/                              # Automated unit, integration, and GUI test suite
│   ├── test_rehab_app.py               # Verifies mathematical parity with original script & pipeline
│   └── test_rehab_gui.py               # Verifies GUI widgets, button guards, settings, and results viewer
├── Images/                             # Visual assets used by the GUI
│   ├── delsys.png                      # Delsys header logo
│   ├── window_icon.png                 # Application window icon
│   ├── checked.png                     # Custom checkbox checked icon
│   ├── unchecked.png                   # Custom checkbox unchecked icon
│   └── centro_trigger_config.png       # Delsys Centro trigger diagram
├── AeroPy/                             # Delsys AeroPy .NET wrapper layer (preserved unchanged)
│   ├── TrignoBase.py                   # DelsysAPI license validation, sensor scan, mode setup, polling
│   └── DataManager.py                  # Delsys demo data buffer manager
├── resources/                          # DelsysAPI.dll and .NET runtime dependencies
├── recordings/                         # Saved Excel workbooks (.xlsx) and analysis plot folders
├── DataCollector/                      # Original Delsys demo GUI collector modules (preserved)
├── Export/                             # Original Delsys demo CSV writer (preserved)
├── Plotter/                            # Original Delsys demo VisPy plotter (preserved)
├── StartMenu/                          # Original Delsys demo start window (preserved)
├── UIControls/                         # Original Delsys demo landing controller (preserved)
├── gui_main.py                         # Dedicated entry point to launch the PySide6 GUI
├── main.py                             # CLI entry point (supports --gui, live, --simulate, --analyze-file)
├── rehab_vision_delsys_ukf_Final.py    # Original single-file reference implementation (preserved)
├── DelsysPythonDemo.py                 # Original Delsys EMG demo entry point (preserved)
├── pose_landmarker_full.task           # MediaPipe PoseLandmarker model asset file
└── requirements.txt                    # Python package dependencies
```

### Folder-Specific Documentation
For detailed module-level documentation, see the dedicated README inside each folder:
- **[rehab_app/README.md](rehab_app/README.md)**: Core rehabilitation modules, classes, functions, mathematical pipeline, and independent debugging guide.
- **[rehab_gui/README.md](rehab_gui/README.md)**: PySide6 GUI screens, widgets, theme customization, and controller communication guide.
- **[tests/README.md](tests/README.md)**: Automated unit, pipeline, and GUI test cases, commands, failure diagnosis, and instructions for adding new tests.

---

## B. Data Flow & GUI Architecture

### 1. Core Data Pipeline
```text
[Delsys Trigno Sensors 1 & 2] (OR 16 bits, 74 Hz)
       │  Raw Quaternion Channels: ORIENTATION W, X, Y, Z
       ▼
[rehab_app/sensors.py: DelsysSensorManager]
       │  Normalizes (W, X, Y, Z) and passes to CalibrationManager
       ▼
[rehab_app/calibration.py: CalibrationManager]
       │  1. 0–30 s: Stationary Warm-up
       │  2. 30–35 s: Averages neutral quaternions -> q_ref
       │  3. >35 s: q_rel = normalize(q_conjugate(q_ref) * q_curr)
       │  4. Euler angles -> Physical mapping & 2.0° deadband:
       │     • imu_pitch = deadband(mathematical_roll)
       │     • imu_yaw   = deadband(mathematical_yaw)
       │     • mathematical_pitch (physical roll) is ignored
       ▼
[rehab_app/controller.py: RehabApplicationController.step_session()] ◄─── [rehab_app/vision.py: PoseVisionProcessor]
       │                                                                   • Flips webcam frame & runs MediaPipe Pose
       │                                                                   • Exponential smoothing (alpha = 0.3)
       │                                                                   • Computes 2D Shoulder & Elbow Vision angles
       ▼
[rehab_app/fusion.py: JointFusionPipeline.step()]
       │  • Shoulder UKF: fuses IMU 1 Pitch + Shoulder Vision
       │  • Elbow UKF:    fuses (IMU 1 Yaw + 90.0°) + Elbow Vision
       │  • Trunk Angle:  passes through IMU 2 Pitch directly (unfused)
       │  • Records actual UKF Kalman gains K = [K_angle, K_velocity]
       ▼
[rehab_app/recording.py: SessionRecorder.record_step()]
       │  Appends timestamped row to RawData and ProcessedData buffers
       │  (Preserves missing data as NaN without silent interpolation)
       ▼
[On Experiment Stop: SessionRecorder.export_to_excel()]
       │  Writes recordings/rehab_session_YYYYMMDD_HHMMSS_mmm.xlsx
       │  Sheets: RawData | ProcessedData | Metrics | Settings
       ▼
[rehab_app/analysis.py: SessionAnalyzer.analyze_workbook()]
          Loads saved Excel workbook and generates 7 PNG plots in
          recordings/rehab_session_YYYYMMDD_HHMMSS_mmm_analysis/
```

### 2. How the GUI Communicates with the Core Controller
The `rehab_gui/` package is a pure presentation and control layer built on **PySide6**. It never duplicates sensor acquisition, quaternion math, MediaPipe processing, UKF equations, or Excel export logic. Instead, `RehabMainWindow` holds an instance of `RehabApplicationController` and communicates via its public methods:
- **Non-blocking 30 Hz UI Poll (`QTimer`):** Calls `controller.get_current_measurements()`, `controller.get_sensor_status()`, and `controller.get_latest_frame()` every 33 ms to update the webcam display, calibration progress bar, and joint angle cards without blocking the Qt event loop.
- **Experiment Lifecycle Controls:**
  - **Connect / Disconnect Delsys:** Calls `controller.start_experiment()` (or starts a 74 Hz simulated quaternion feeder thread when *Use Simulated Delsys Sensors* is checked) to begin sensor warm-up, neutral calibration, and webcam preview.
  - **Start Experiment:** Guarded until `status["is_calibrated"]` is `True`. Resets the `SessionRecorder` buffer (`controller.recorder.reset()`) and UKF filter states (`controller.fusion_pipeline.reset()`) so the saved Excel workbook records the active experiment cleanly from `t = 0.0 s` while keeping the neutral calibration reference quaternions.
  - **Stop Experiment:** Runs `controller.stop_experiment(export_recording=True, run_analysis=True)` on a background worker thread so Excel export and Matplotlib plot generation never freeze the UI.
  - **Reset Calibration / Reset Session:** Calls `controller.reset_calibration()` and `controller.reset_session()`.
  - **Settings Management:** Calls `controller.get_settings()` and `controller.update_settings(**kwargs)`.

### 3. Explanation of Each GUI Screen and Its Controls
1. **Tab 1 — Live Rehabilitation Dashboard (`rehab_gui/dashboard_tab.py`):**
   - **Live Webcam Panel:** Shows the mirrored webcam feed with MediaPipe skeleton connections (red) and landmarks (green), plus an optional *Draw On-Video Text Overlay* checkbox (using `Images/checked.png`).
   - **Posture Feedback Banner:** Color-coded banner (`START POSITION (Ready)`, `RIGHT`, `WRONG: Keep Shoulders Straight!`, `LANDMARKS NOT VISIBLE`, `NO POSE DETECTED`).
   - **System & Calibration Status Card:** Shows sensor connection status, calibration progress bar (`0%` → `100%`), experiment state, elapsed time, and sample count.
   - **Joint Telemetry Cards:** Separate cards for **Shoulder** (`Shoulder Vision`, `IMU 1 Pitch`, `Shoulder UKF`), **Elbow** (`Elbow Vision`, `IMU 1 Yaw`, `IMU 1 Yaw + 90°`, `Elbow UKF`), and **Trunk** (`IMU 2 Pitch / Trunk Angle`).
   - **Experiment Controls Bar:** *Use Simulated Delsys Sensors* checkbox, *Connect / Disconnect Delsys*, *Reset Calibration*, *Start Experiment* (locked until calibrated), *Stop Experiment*, *Reset Session*, and *Results & Plots*.
2. **Tab 2 — Experiment & UKF Settings (`rehab_gui/settings_tab.py`):**
   - Grouped forms for **Camera & MediaPipe Vision**, **Delsys Sensors & Calibration**, **Unscented Kalman Filter (UKF) Tuning**, and **Session Recording & Excel Export**.
   - Includes **Apply Settings** (validates via `RehabConfig.validate()`) and **Restore Original Defaults**. Automatically locked while sensors or an experiment are running.
3. **Tab 3 — Recorded Sessions & Analysis (`rehab_gui/results_tab.py`):**
   - Lists all `.xlsx` files in `recordings/` (newest first).
   - Displays any of the 7 generated diagnostic PNG plots in a scalable viewer alongside the full `Metrics` sheet table (`MAE`, `RMSE`, `Bias`, `Std_Residual`, `LoA_95`, `Pearson_r`), with buttons to **Generate / Refresh Analysis Plots**, **Open Excel Workbook**, and **Open Recordings Folder**.

---

## C. How to Run

> **Python Interpreter:** Use Python 3.13 where all dependencies are installed:
> `C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe`

### 1. Launch the PySide6 GUI (Standard Mode)
```powershell
& "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" gui_main.py
```
*(Or equivalently: `& "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" main.py --gui`)*

### 2. Launch the PySide6 GUI in Simulation Mode (Fast Warm-Up for Immediate Testing)
```powershell
& "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" gui_main.py --simulate --warmup 3 --calibration 2
```
1. Click **Connect Delsys** in the bottom-left control bar.
2. Watch the webcam feed and the **Calibration Progress** bar reach `100% (Both Sensors Calibrated)` after 5 seconds.
3. Click **Start Experiment** to record live fused movements, then click **Stop Experiment** to export the 4-sheet Excel workbook and view the 7 plots in the **Recorded Sessions & Analysis** tab.

### 3. Run the Standalone CLI (Without PySide6 GUI)
- **Live Webcam + Real Delsys Hardware:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" main.py
  ```
- **Live Webcam + Simulated Delsys Sensors:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" main.py --simulate --warmup 5 --calibration 3 --duration 30
  ```
- **Headless Simulation (No Webcam or Sensors Required):**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" main.py --simulate --no-window --no-vision --warmup 2 --calibration 1 --duration 4
  ```
- **Analyze an Existing Saved Excel Workbook:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" main.py --analyze-file recordings\<your_session_file>.xlsx
  ```

---

## D. Where to Modify Things (Core & GUI)

| If I want to modify... | File | Function / Class |
| :--- | :--- | :--- |
| **GUI color palette, fonts, or `Images/` asset paths** | `rehab_gui/theme.py` | `PALETTE`, `build_stylesheet()` |
| **GUI top header bar, window size, or 30 Hz refresh timer** | `rehab_gui/main_window.py` | `RehabMainWindow._setup_window()`, `_build_ui()`, `_refresh_ui()` |
| **GUI live webcam display, angle cards, or experiment buttons** | `rehab_gui/dashboard_tab.py` | `DashboardTab._build_ui()`, `update_telemetry()`, `update_video_frame()` |
| **GUI settings form fields or validation feedback** | `rehab_gui/settings_tab.py` | `SettingsTab._build_ui()`, `apply_settings()`, `restore_defaults()` |
| **GUI recorded Excel browser, plot viewer, or metrics table** | `rehab_gui/results_tab.py` | `ResultsTab._build_ui()`, `refresh_recordings_list()`, `_load_workbook_views()` |
| **Camera index, frame rate, or default durations** | `rehab_app/config.py` | `CAMERA_INDEX`, `RECORD_SECONDS`, `RehabConfig` |
| **MediaPipe skeleton connections or landmark indices** | `rehab_app/vision.py` | `POSE_CONNECTIONS`, `PoseVisionProcessor.evaluate_landmarks()` |
| **Shoulder & Elbow 2D Vision angle calculation** | `rehab_app/vision.py` | `calculate_angle()`, `vision_angle()`, `PoseVisionProcessor.evaluate_landmarks()` |
| **Exercise posture feedback rules (`RIGHT`, `WRONG`, `START POSITION`)** | `rehab_app/vision.py` | `PoseVisionProcessor.evaluate_landmarks()` |
| **Delsys sensor indices, `OR 16 bits` mode, or WXYZ channel mapping** | `rehab_app/sensors.py` | `find_or_mode()`, `find_quaternion_channels()`, `DelsysSensorManager._sensor_worker_loop()` |
| **Quaternion math, warm-up, neutral calibration, or `2.0°` deadband** | `rehab_app/calibration.py` | `normalize()`, `q_multiply()`, `average_quaternions()`, `CalibrationManager.process_quaternion()` |
| **Physical IMU axis mapping (Roll → Pitch, Yaw → Yaw)** | `rehab_app/calibration.py` | `CalibrationManager.process_quaternion()` |
| **UKF tuning (`Q_ANGLE`, `Q_VELOCITY`, `R_IMU`, `R_VISION`) & equations** | `rehab_app/config.py` & `rehab_app/fusion.py` | `AngleUKF.sigma_points()`, `AngleUKF.predict()`, `AngleUKF.update()` |
| **Joint fusion assignments or Elbow `+90.0°` IMU offset** | `rehab_app/fusion.py` | `fuse_shoulder_angle()`, `fuse_elbow_angle()`, `JointFusionPipeline.step()` |
| **Excel sheet columns (`RawData`, `ProcessedData`, `Settings`)** | `rehab_app/recording.py` | `RAW_COLUMNS`, `PROCESSED_COLUMNS`, `SessionRecorder.record_step()` |
| **Consistency metrics (`MAE`, `RMSE`, `Bias`, `Std`, `LoA`, `Pearson_r`)** | `rehab_app/recording.py` | `compute_consistency_metrics_table()` |
| **Post-experiment Matplotlib plots** | `rehab_app/analysis.py` | `SessionAnalyzer.analyze_workbook()`, `_plot_joint_angles()`, `_plot_kalman_gains()` |

---

## E. Testing and Verification

### 1. Run All Automated Core & GUI Tests (Simulated / Mock Data)
- **Command:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest discover -s tests -v
  ```
- **Expected Result:** `Ran 10 tests in ~4.5s — OK` (7 core mathematical/pipeline tests in `tests/test_rehab_app.py` + 3 GUI workflow tests in `tests/test_rehab_gui.py`).

### 2. Run GUI Automated Tests Only (Offscreen Qt Verification)
- **Command:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests/test_rehab_gui.py -v
  ```
- **Expected Result:** `Ran 3 tests — OK` (verifies `Images/` assets, `PALETTE` stylesheet, button lock guards before/after calibration, live angle/frame updates, settings validation, and Excel results loading).

### 3. Interactive GUI Simulation Test
- **Command:**
  ```powershell
  & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" gui_main.py --simulate --warmup 3 --calibration 2
  ```
- **Expected Result:** GUI opens with *Use Simulated Delsys Sensors* checked; clicking **Connect Delsys** shows live webcam + MediaPipe skeleton, completes calibration in 5 seconds, enables **Start Experiment**, and exports the 4-sheet Excel workbook and 7 analysis plots on **Stop Experiment**.
=======
# MV_GP_
>>>>>>> 38c5d1e8cc7ae8c077bdea66f7697f27b51748a9
