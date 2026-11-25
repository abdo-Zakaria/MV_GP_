"""
Main application window for the Active Upper Limb Rehabilitation GUI.

Coordinates:
- Top branding header with `Images/delsys.png` and live status badges.
- `DashboardTab` (live webcam + MediaPipe skeleton, joint angle cards, experiment controls).
- `SettingsTab` (camera, Delsys sensors, calibration, UKF, and recording parameters).
- `ResultsTab` (recorded Excel workbooks, metrics table, and 7 diagnostic plots).

Communicates exclusively through `RehabApplicationController` on non-blocking
worker threads and a 30 Hz UI refresh `QTimer`.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from main import _simulated_sensor_quaternions
from rehab_app.config import RehabConfig
from rehab_app.controller import RehabApplicationController, SessionResults
from rehab_gui.dashboard_tab import DashboardTab
from rehab_gui.results_tab import ResultsTab
from rehab_gui.settings_tab import SettingsTab
from rehab_gui.theme import DELSYS_LOGO_PATH, PALETTE, WINDOW_ICON_PATH, build_stylesheet

logger = logging.getLogger(__name__)


class _StopSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class RehabMainWindow(QMainWindow):
    """Top-level PySide6 window for the Active Upper Limb Rehabilitation application."""

    def __init__(
        self,
        controller: Optional[RehabApplicationController] = None,
        start_in_simulation_mode: bool = False,
    ) -> None:
        super().__init__()
        if controller is None:
            controller = RehabApplicationController(RehabConfig(show_opencv_window=False))
        else:
            controller.config.show_opencv_window = False
        self.controller = controller

        # GUI lifecycle state
        self._is_connected: bool = False
        self._is_recording_experiment: bool = False
        self._sim_stop_event = threading.Event()
        self._sim_thread: Optional[threading.Thread] = None
        self._stop_signals = _StopSignals()
        self._stop_signals.finished.connect(self._on_stop_experiment_completed)
        self._stop_signals.failed.connect(self._on_stop_experiment_failed)

        self._setup_window()
        self._build_ui()

        if start_in_simulation_mode:
            self.dashboard_tab.simulate_checkbox.setChecked(True)

        # 30 Hz non-blocking UI refresh timer
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(33)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()
        self._refresh_ui()

    def _setup_window(self) -> None:
        self.setWindowTitle("Active Upper Limb Rehabilitation — MediaPipe + Delsys Trigno UKF")
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        if WINDOW_ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(WINDOW_ICON_PATH)))
        self.setStyleSheet(build_stylesheet())

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # =====================================================================
        # TOP BRANDING & STATUS HEADER BAR (Using Images/delsys.png)
        # =====================================================================
        header = QFrame()
        header.setObjectName("headerBar")
        header.setFixedHeight(64)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 8, 18, 8)
        header_layout.setSpacing(16)

        if DELSYS_LOGO_PATH.is_file():
            logo_label = QLabel()
            pix = QPixmap(str(DELSYS_LOGO_PATH)).scaledToHeight(
                36, Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(pix)
            header_layout.addWidget(logo_label)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        app_title = QLabel("Active Upper Limb Rehabilitation System")
        app_title.setStyleSheet(f"font-size: 13.5pt; font-weight: bold; color: {PALETTE['text_primary']};")
        app_subtitle = QLabel("MediaPipe Pose Vision  •  Delsys Trigno Quaternions (OR 16 bits, 74 Hz)  •  Real-Time UKF Fusion")
        app_subtitle.setStyleSheet(f"font-size: 9pt; color: {PALETTE['text_secondary']};")
        title_box.addWidget(app_title)
        title_box.addWidget(app_subtitle)
        header_layout.addLayout(title_box)

        header_layout.addStretch(1)

        self.header_status_badge = QLabel("● Standby")
        self.header_status_badge.setStyleSheet(
            f"background-color: {PALETTE['bg_panel']}; border: 1px solid {PALETTE['border']}; "
            f"border-radius: 14px; padding: 5px 14px; font-weight: bold; color: {PALETTE['text_secondary']};"
        )
        header_layout.addWidget(self.header_status_badge)
        main_layout.addWidget(header)

        # =====================================================================
        # MAIN TAB WIDGET (Dashboard | Settings | Results & Analysis)
        # =====================================================================
        body_container = QWidget()
        body_layout = QVBoxLayout(body_container)
        body_layout.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()
        self.dashboard_tab = DashboardTab(
            on_connect_toggled=self.toggle_sensor_connection,
            on_start_experiment=self.start_experiment_recording,
            on_stop_experiment=self.stop_experiment_recording,
            on_reset_calibration=self.reset_calibration,
            on_reset_session=self.reset_session,
            on_view_results=lambda: self.tabs.setCurrentWidget(self.results_tab),
        )
        self.settings_tab = SettingsTab(
            controller=self.controller,
            on_settings_applied=self._on_settings_updated,
        )
        self.results_tab = ResultsTab(recordings_dir=self.controller.config.recordings_dir)

        self.tabs.addTab(self.dashboard_tab, "Live Rehabilitation Dashboard")
        self.tabs.addTab(self.settings_tab, "Experiment && UKF Settings")
        self.tabs.addTab(self.results_tab, "Recorded Sessions && Analysis")

        body_layout.addWidget(self.tabs)
        main_layout.addWidget(body_container, stretch=1)

    def _on_settings_updated(self) -> None:
        self.results_tab.set_recordings_dir(self.controller.config.recordings_dir)
        self._refresh_ui()

    # =====================================================================
    # EXPERIMENT & SENSOR CONTROL ACTIONS
    # =====================================================================
    def toggle_sensor_connection(self) -> None:
        """Connect or disconnect Delsys sensors (or simulated 74 Hz quaternion stream) and camera preview."""
        if self._is_recording_experiment:
            QMessageBox.warning(
                self,
                "Experiment in Progress",
                "Please stop the active experiment before disconnecting sensors.",
            )
            return

        if self._is_connected:
            self.disconnect_sensors()
        else:
            self.connect_sensors()

    def connect_sensors(self) -> None:
        """Start sensor streaming (real Delsys or simulated 74 Hz stream), calibration, and webcam preview."""
        if self._is_connected:
            return

        use_sim = self.dashboard_tab.simulate_checkbox.isChecked()
        self.controller.config.show_opencv_window = False
        self.controller.config.enable_sensors = not use_sim
        self.controller.config.enable_vision = True

        self.controller.start_experiment()
        if use_sim:
            self._start_simulated_sensor_thread()

        self._is_connected = True
        self._is_recording_experiment = False
        self.settings_tab.set_editing_enabled(False)
        self._refresh_ui()

    def disconnect_sensors(self) -> None:
        """Stop sensor acquisition and webcam preview without exporting an experiment workbook."""
        self._stop_simulated_sensor_thread()
        if self.controller.is_running:
            self.controller.stop_experiment(export_recording=False, run_analysis=False)
        self._is_connected = False
        self._is_recording_experiment = False
        self.dashboard_tab.video_label.clear()
        self.dashboard_tab.video_label.setText(
            "Sensors and camera disconnected.\nClick 'Connect Delsys' to reconnect."
        )
        self.settings_tab.set_editing_enabled(True)
        self._refresh_ui()

    def _start_simulated_sensor_thread(self) -> None:
        """Stream 74 Hz simulated Delsys W, X, Y, Z quaternions into `controller.sensor_manager`."""
        self._stop_simulated_sensor_thread()
        self._sim_stop_event.clear()
        c = self.controller.config
        cal_end = c.warmup_seconds + c.calibration_seconds

        def _sim_loop() -> None:
            start = time.monotonic()
            self.controller.calibration_manager.start(start)
            self.controller.sensor_manager.set_status("Simulated Delsys (74 Hz)")
            period = 1.0 / 74.0
            while not self._sim_stop_event.is_set():
                now = time.monotonic()
                elapsed = now - start
                q1, q2 = _simulated_sensor_quaternions(elapsed, cal_end)
                self.controller.sensor_manager.inject_quaternion_sample(1, q1, timestamp=now)
                self.controller.sensor_manager.inject_quaternion_sample(2, q2, timestamp=now)
                time.sleep(period)

        self._sim_thread = threading.Thread(target=_sim_loop, name="GUISimulatedDelsysWorker", daemon=True)
        self._sim_thread.start()

    def _stop_simulated_sensor_thread(self) -> None:
        self._sim_stop_event.set()
        if self._sim_thread is not None and self._sim_thread.is_alive():
            self._sim_thread.join(timeout=2.0)
        self._sim_thread = None

    def reset_calibration(self) -> None:
        """Restart the warm-up and neutral quaternion calibration window."""
        if not self._is_connected or self._is_recording_experiment:
            return
        self.controller.reset_calibration(new_start_timestamp=time.monotonic())
        if self.dashboard_tab.simulate_checkbox.isChecked():
            self._start_simulated_sensor_thread()
        self._refresh_ui()

    def start_experiment_recording(self) -> None:
        """
        Begin the active recorded experiment session once sensors are connected
        and neutral calibration is complete.
        """
        status = self.controller.get_sensor_status()
        if not self._is_connected:
            QMessageBox.warning(self, "Sensors Not Connected", "Please connect Delsys sensors first.")
            return
        if not status.get("is_calibrated", False):
            QMessageBox.warning(
                self,
                "Calibration Incomplete",
                "Please wait for stationary warm-up and neutral calibration to finish before starting.",
            )
            return

        # Reset the recorder buffer and UKF filters so the saved Excel file starts
        # cleanly at t = 0.0 s for the active experiment while keeping calibration references
        self.controller.fusion_pipeline.reset()
        self.controller.recorder.reset()
        self._is_recording_experiment = True
        self._refresh_ui()

    def stop_experiment_recording(self) -> None:
        """Stop the active experiment, export the 4-sheet Excel workbook, and generate plots."""
        if not self._is_recording_experiment:
            return

        self.dashboard_tab.stop_exp_btn.setEnabled(False)
        self.dashboard_tab.control_hint_label.setText("Exporting Excel workbook and generating analysis plots...")
        self._stop_simulated_sensor_thread()

        def _stop_worker() -> None:
            try:
                res = self.controller.stop_experiment(export_recording=True, run_analysis=True)
                self._stop_signals.finished.emit(res)
            except Exception as exc:
                self._stop_signals.failed.emit(str(exc))

        threading.Thread(target=_stop_worker, name="GUIStopExperimentWorker", daemon=True).start()

    def _on_stop_experiment_completed(self, results: SessionResults) -> None:
        self._is_recording_experiment = False
        self._is_connected = False
        self.settings_tab.set_editing_enabled(True)
        self.results_tab.refresh_recordings_list(select_workbook=results.workbook_path)
        self._refresh_ui()

        if results.workbook_path is not None:
            ans = QMessageBox.question(
                self,
                "Experiment Recording Saved",
                f"Session exported ({results.recorded_samples} samples):\n"
                f"{results.workbook_path.name}\n\n"
                "Would you like to open the Recorded Sessions & Analysis tab now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.tabs.setCurrentWidget(self.results_tab)

    def _on_stop_experiment_failed(self, error_msg: str) -> None:
        self._is_recording_experiment = False
        self._is_connected = False
        self.settings_tab.set_editing_enabled(True)
        self._refresh_ui()
        QMessageBox.critical(self, "Export Error", f"An error occurred while stopping the experiment:\n{error_msg}")

    def reset_session(self) -> None:
        """Reset current session state after confirmation if samples were recorded."""
        if self._is_recording_experiment:
            return
        if self.controller.recorder.sample_count > 0:
            ans = QMessageBox.question(
                self,
                "Confirm Session Reset",
                "Clear current buffered measurements and reset UKF filter states?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        if self._is_connected:
            self.disconnect_sensors()
        self.controller.reset_session()
        self._refresh_ui()

    # =====================================================================
    # PERIODIC UI REFRESH (30 Hz)
    # =====================================================================
    def _refresh_ui(self) -> None:
        measurements = self.controller.get_current_measurements()
        status = self.controller.get_sensor_status()
        total_cal_sec = self.controller.config.warmup_seconds + self.controller.config.calibration_seconds

        self.dashboard_tab.update_telemetry(
            measurements=measurements,
            status=status,
            is_connected=self._is_connected,
            is_recording_experiment=self._is_recording_experiment,
            total_cal_seconds=total_cal_sec,
        )

        if self._is_connected:
            frame = self.controller.get_latest_frame()
            self.dashboard_tab.update_video_frame(frame, measurements)

        # Update top header badge
        if self._is_recording_experiment:
            self.header_status_badge.setText("● Recording Experiment")
            self.header_status_badge.setStyleSheet(
                f"background-color: {PALETTE['bg_panel']}; border: 1px solid {PALETTE['status_ok']}; "
                f"border-radius: 14px; padding: 5px 14px; font-weight: bold; color: {PALETTE['status_ok']};"
            )
        elif self._is_connected and status.get("is_calibrated", False):
            self.header_status_badge.setText("● Calibrated & Ready")
            self.header_status_badge.setStyleSheet(
                f"background-color: {PALETTE['bg_panel']}; border: 1px solid {PALETTE['tab_selected_border']}; "
                f"border-radius: 14px; padding: 5px 14px; font-weight: bold; color: {PALETTE['tab_selected_bg']};"
            )
        elif self._is_connected:
            self.header_status_badge.setText(f"● {status.get('calibration', 'Calibrating...')}")
            self.header_status_badge.setStyleSheet(
                f"background-color: {PALETTE['bg_panel']}; border: 1px solid {PALETTE['status_warn']}; "
                f"border-radius: 14px; padding: 5px 14px; font-weight: bold; color: {PALETTE['status_warn']};"
            )
        else:
            self.header_status_badge.setText("● Standby")
            self.header_status_badge.setStyleSheet(
                f"background-color: {PALETTE['bg_panel']}; border: 1px solid {PALETTE['border']}; "
                f"border-radius: 14px; padding: 5px 14px; font-weight: bold; color: {PALETTE['text_secondary']};"
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure background worker threads are cleanly stopped when closing the window."""
        self._ui_timer.stop()
        self._stop_simulated_sensor_thread()
        if self.controller.is_running:
            self.controller.stop_experiment(
                export_recording=self._is_recording_experiment,
                run_analysis=self._is_recording_experiment,
            )
        event.accept()
