# `rehab_gui/` — PySide6 Graphical User Interface Package

This folder contains the PySide6 graphical user interface for the Active Upper Limb Rehabilitation application. It acts purely as a visual presentation and user-control layer on top of `rehab_app.RehabApplicationController`.

It does **not** duplicate any sensor polling, quaternion calibration, MediaPipe pose detection, UKF math, or Excel recording logic.

---

## 1. Purpose of Each GUI File and Component

| File | Main Classes / Functions | Purpose |
| :--- | :--- | :--- |
| `__init__.py` | Package exports | Exports `RehabMainWindow`, `DashboardTab`, `SettingsTab`, `ResultsTab`, `PALETTE`, and `build_stylesheet`. |
| `theme.py` | `PALETTE`, `build_stylesheet()`, asset path constants | Defines the cohesive Delsys color scheme and Qt stylesheet built around the existing assets in `Images/` (`delsys.png`, `window_icon.png`, `checked.png`, `unchecked.png`, `centro_trigger_config.png`). |
| `main_window.py` | `RehabMainWindow` | Top-level application window containing the Delsys branding header bar, live status badge, 3-tab navigation widget (`QTabWidget`), 30 Hz non-blocking UI refresh timer (`QTimer`), and background worker signals. |
| `dashboard_tab.py` | `DashboardTab`, `AngleValueRow` | Real-time monitoring dashboard displaying the live webcam feed with MediaPipe landmarks, posture feedback banner, system/calibration progress card, joint angle cards (Shoulder, Elbow, Trunk), and experiment control buttons. |
| `settings_tab.py` | `SettingsTab` | Form interface exposing all configurable parameters in `RehabConfig` (Camera & Vision, Delsys Sensors & Calibration, UKF Tuning, and Recording & Export), with validation and default restoration. |
| `results_tab.py` | `ResultsTab` | Post-experiment browser listing all `.xlsx` files in `recordings/`, displaying the 7 generated diagnostic PNG plots in an interactive viewer, and showing the `Metrics` sheet in a table. |

---

## 2. Screens, Widgets, and Navigation Structure

`RehabMainWindow` organizes the interface into a persistent **Top Header Bar** and three tabs inside `self.tabs` (`QTabWidget`):

1. **Top Header Bar (`RehabMainWindow._build_ui`)**
   - Displays `Images/delsys.png` logo, application title, subtitle, and `self.header_status_badge` (`● Standby`, `● Warm-up/calibration ...`, `● Calibrated & Ready`, or `● Recording Experiment`).
2. **Tab 1: Live Rehabilitation Dashboard (`DashboardTab`)**
   - **Left Column:**
     - `video_label`: Renders the live webcam feed annotated with MediaPipe skeleton connections and landmarks.
     - `overlay_checkbox`: Toggles drawing the 8-line telemetry text overlay directly onto the video frame.
     - `posture_banner`: Color-coded banner displaying `START POSITION (Ready)`, `RIGHT`, `WRONG: Keep Shoulders Straight!`, `LANDMARKS NOT VISIBLE`, or `NO POSE DETECTED`.
     - **Control Bar:**
       - `simulate_checkbox`: Switches between real Delsys Trigno hardware and a simulated 74 Hz quaternion stream.
       - `connect_btn`: Connects or disconnects Delsys sensors and starts the camera preview and calibration timer.
       - `reset_cal_btn`: Calls `controller.reset_calibration()` to restart warm-up and neutral calibration.
       - `start_exp_btn`: Starts recording the active experiment (disabled until sensors are connected and calibrated).
       - `stop_exp_btn`: Stops recording, exports the 4-sheet Excel workbook, and generates the 7 analysis plots.
       - `reset_session_btn`: Clears buffered measurements after confirmation.
       - `view_results_btn`: Switches directly to the **Recorded Sessions & Analysis** tab.
   - **Right Column:**
     - **System & Calibration Status Card:** `sensor_status_label`, `calibration_status_label`, `calibration_progress` (`QProgressBar`, `0%`–`100%`), `experiment_status_label`, and `elapsed_label`.
     - **Shoulder Joint Card:** `row_shoulder_vision`, `row_imu1_pitch`, `row_shoulder_ukf` (highlighted).
     - **Elbow Joint Card:** `row_elbow_vision`, `row_imu1_yaw`, `row_imu1_elbow` (`IMU 1 Yaw + 90°`), `row_elbow_ukf` (highlighted).
     - **Trunk Orientation Card:** `row_trunk_pitch` (`IMU 2 Pitch / Trunk Angle`).
3. **Tab 2: Experiment & UKF Settings (`SettingsTab`)**
   - Four `QGroupBox` panels:
     - *Camera & MediaPipe Vision Settings*
     - *Delsys Sensors & Calibration Settings*
     - *Unscented Kalman Filter (UKF) Tuning*
     - *Session Recording & Excel Export Settings*
   - Bottom bar with `restore_defaults_btn` (*Restore Original Defaults*) and `apply_btn` (*Apply Settings*).
4. **Tab 3: Recorded Sessions & Analysis (`ResultsTab`)**
   - **Left Panel:** `workbooks_list` (`QListWidget` of `.xlsx` files in `recordings/`), *Refresh Recordings List*, `analyze_btn` (*Generate / Refresh Analysis Plots*), `open_excel_btn` (*Open Excel Workbook*), and `open_folder_btn` (*Open Recordings Folder*).
   - **Right Panel:** `plot_selector` (`QComboBox` selecting among the 7 diagnostic plots), `plot_image_label` (auto-scaling high-DPI plot viewer), and `metrics_table` (`QTableWidget` displaying the `Metrics` sheet).

---

## 3. How the GUI Communicates with `RehabApplicationController`

All interaction with the core application happens through `self.controller` (`RehabApplicationController`) in `rehab_gui/main_window.py`:

| User Action in GUI | GUI Method (`RehabMainWindow`) | Controller Method Called |
| :--- | :--- | :--- |
| Click **Connect Delsys** | `connect_sensors()` | `controller.start_experiment()` (starts background sensor & vision workers) |
| Click **Disconnect Delsys** | `disconnect_sensors()` | `controller.stop_experiment(export_recording=False, run_analysis=False)` |
| Click **Reset Calibration** | `reset_calibration()` | `controller.reset_calibration(new_start_timestamp=time.monotonic())` |
| Click **Start Experiment** | `start_experiment_recording()` | Checks `controller.get_sensor_status()["is_calibrated"]`, then calls `controller.fusion_pipeline.reset()` and `controller.recorder.reset()` |
| Click **Stop Experiment** | `stop_experiment_recording()` | Spawns background thread calling `controller.stop_experiment(export_recording=True, run_analysis=True)` |
| Click **Reset Session** | `reset_session()` | `controller.reset_session()` |
| Click **Apply Settings** | `SettingsTab.apply_settings()` | `controller.update_settings(**values)` |

---

## 4. How Live Measurements and Statuses Are Updated

`RehabMainWindow.__init__()` starts a non-blocking `QTimer` (`self._ui_timer`) with a `33 ms` interval (~30 Hz) connected to `RehabMainWindow._refresh_ui()`:

1. `_refresh_ui()` calls:
   - `measurements = self.controller.get_current_measurements()`
   - `status = self.controller.get_sensor_status()`
2. It passes `measurements` and `status` to `DashboardTab.update_telemetry(...)`, which:
   - Formats and updates every `AngleValueRow` (`+6.1f °` or `— °`).
   - Parses the calibration status string (e.g., `"Warm-up/calibration 12/35 s"`) to update `calibration_progress` (`0%`–`100%`).
   - Updates the posture feedback banner color and text.
   - Enables or disables `start_exp_btn`, `stop_exp_btn`, `reset_cal_btn`, and `connect_btn` so invalid operations are impossible.
3. When connected, `_refresh_ui()` calls `frame = self.controller.get_latest_frame()` and passes it to `DashboardTab.update_video_frame(frame, measurements)`, which converts the BGR NumPy array to a `QPixmap` and scales it smoothly into `video_label`.

---

## 5. Where to Modify Layouts, Colors, Themes, and UI Elements

- **Change colors, fonts, border radii, or button styles:** Edit `PALETTE` or `build_stylesheet()` in `rehab_gui/theme.py`.
- **Change image assets (`delsys.png`, `window_icon.png`, `checked.png`, `unchecked.png`):** Edit the path constants at the top of `rehab_gui/theme.py`.
- **Modify the webcam view size, angle cards, or control buttons on the Dashboard:** Edit `DashboardTab._build_ui()` and `DashboardTab.update_telemetry()` in `rehab_gui/dashboard_tab.py`.
- **Add or rearrange a setting field in the Settings tab:** Edit `SettingsTab._build_ui()`, `load_from_config()`, and `collect_form_values()` in `rehab_gui/settings_tab.py`.
- **Modify the plot selector titles or metrics table columns in the Results tab:** Edit `PLOT_TITLES` or `ResultsTab._populate_metrics_table()` in `rehab_gui/results_tab.py`.

---

## 6. How to Run and Test the GUI Independently

1. **Launch the GUI interactively (with simulated sensors pre-selected and 5 s total calibration):**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" gui_main.py --simulate --warmup 3 --calibration 2
   ```
2. **Launch the GUI for real Delsys Trigno hardware (30 s warm-up + 5 s calibration):**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" gui_main.py
   ```
3. **Run the automated offscreen GUI test suite:**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests/test_rehab_gui.py -v
   ```
