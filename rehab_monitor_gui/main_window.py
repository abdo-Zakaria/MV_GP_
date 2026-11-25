"""
Top-level PySide6 window for the Rehabilitation Monitor GUI.

Acts strictly as a display interface around `ApplicationOutputBridge` -> `RehabApplicationController`.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rehab_app import RehabApplicationController, SessionResults
from rehab_monitor_gui.bridge import ApplicationOutputBridge, TelemetrySnapshot
from rehab_monitor_gui.styles import (
    COLORS,
    DELSYS_LOGO_PATH,
    WINDOW_ICON_PATH,
    build_app_stylesheet,
)
from rehab_monitor_gui.widgets import (
    JointMeasurementsPanel,
    SessionResultsPanel,
    StatusAndRecordingPanel,
    VideoFeedPanel,
)


class RehabMonitorWindow(QMainWindow):
    """Main rehabilitation dashboard window consuming `main.py` outputs."""

    def __init__(
        self,
        controller: Optional[RehabApplicationController] = None,
        simulate_mode: bool = False,
        auto_start: bool = False,
    ) -> None:
        super().__init__()
        self.bridge = ApplicationOutputBridge(
            controller=controller,
            simulate_mode=simulate_mode,
            refresh_hz=30.0,
            parent=self,
        )

        self._configure_window()
        self._build_ui(simulate_mode=simulate_mode)

        self.bridge.snapshot_updated.connect(self._on_snapshot)
        self.bridge.session_completed.connect(self._on_session_completed)
        self.bridge.session_error.connect(self._on_session_error)
        self.bridge.start_polling()

        if auto_start:
            self.bridge.start_session(export_on_finish=True)

    def _configure_window(self) -> None:
        self.setWindowTitle("Upper Limb Rehabilitation Monitor — MediaPipe + Delsys Trigno UKF")
        self.resize(1420, 880)
        self.setMinimumSize(1160, 740)
        if WINDOW_ICON_PATH.is_file():
            self.setWindowIcon(QIcon(str(WINDOW_ICON_PATH)))
        self.setStyleSheet(build_app_stylesheet())

    def _build_ui(self, simulate_mode: bool) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # =====================================================================
        # TOP HEADER & NON-INTRUSIVE SESSION CONTROLS BAR
        # =====================================================================
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(68)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 8, 16, 8)
        top_layout.setSpacing(12)

        if DELSYS_LOGO_PATH.is_file():
            logo = QLabel()
            logo.setPixmap(
                QPixmap(str(DELSYS_LOGO_PATH)).scaledToHeight(
                    34, Qt.TransformationMode.SmoothTransformation
                )
            )
            top_layout.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        h_title = QLabel("Active Upper Limb Rehabilitation Monitor")
        h_title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        h_sub = QLabel("Live Display Layer for main.py  •  Delsys Trigno IMU + MediaPipe Vision + UKF")
        h_sub.setStyleSheet(f"font-size: 8.8pt; color: {COLORS['text_secondary']};")
        titles.addWidget(h_title)
        titles.addWidget(h_sub)
        top_layout.addLayout(titles)

        top_layout.addStretch(1)

        self.simulate_chk = QCheckBox("Simulation Mode (--simulate)")
        self.simulate_chk.setChecked(bool(simulate_mode))
        self.simulate_chk.setToolTip(
            "When checked before starting, runs main.py's built-in simulation mode."
        )
        self.simulate_chk.toggled.connect(self.bridge.set_simulate_mode)
        top_layout.addWidget(self.simulate_chk)

        self.start_btn = QPushButton("Start Session")
        self.start_btn.setProperty("variant", "primary")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.clicked.connect(self._handle_start)
        top_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop && Export")
        self.stop_btn.setProperty("variant", "danger")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._handle_stop)
        top_layout.addWidget(self.stop_btn)

        self.reset_cal_btn = QPushButton("Reset Calibration")
        self.reset_cal_btn.setMinimumHeight(36)
        self.reset_cal_btn.setEnabled(False)
        self.reset_cal_btn.clicked.connect(self.bridge.reset_calibration)
        top_layout.addWidget(self.reset_cal_btn)

        self.reset_session_btn = QPushButton("Reset Session")
        self.reset_session_btn.setMinimumHeight(36)
        self.reset_session_btn.clicked.connect(self.bridge.reset_session)
        top_layout.addWidget(self.reset_session_btn)

        self.state_pill = QLabel("● Standby")
        self.state_pill.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 14px; padding: 5px 14px; font-weight: 700; color: {COLORS['text_secondary']};"
        )
        top_layout.addWidget(self.state_pill)
        root.addWidget(top_bar)

        # =====================================================================
        # TABS: 1. LIVE REHABILITATION DASHBOARD  |  2. RECORDED WORKBOOKS & PLOTS
        # =====================================================================
        tabs_wrap = QWidget()
        tabs_layout = QVBoxLayout(tabs_wrap)
        tabs_layout.setContentsMargins(10, 10, 10, 10)

        self.tabs = QTabWidget()

        # Tab 1: Three-column / balanced 2-split Live Rehabilitation Dashboard
        dashboard_page = QWidget()
        dash_layout = QHBoxLayout(dashboard_page)
        dash_layout.setContentsMargins(8, 8, 8, 8)
        dash_layout.setSpacing(12)

        self.video_panel = VideoFeedPanel()
        self.joints_panel = JointMeasurementsPanel()
        self.status_panel = StatusAndRecordingPanel()

        dash_layout.addWidget(self.video_panel, stretch=5)
        dash_layout.addWidget(self.joints_panel, stretch=3)
        dash_layout.addWidget(self.status_panel, stretch=3)

        # Tab 2: Session Recording & Analysis Viewer
        self.results_panel = SessionResultsPanel(
            recordings_dir=self.bridge.controller.config.recordings_dir
        )

        self.tabs.addTab(dashboard_page, "Live Rehabilitation Dashboard")
        self.tabs.addTab(self.results_panel, "Session Recordings && Plots")
        tabs_layout.addWidget(self.tabs)
        root.addWidget(tabs_wrap, stretch=1)

    def _handle_start(self) -> None:
        self.bridge.set_simulate_mode(self.simulate_chk.isChecked())
        self.bridge.start_session(export_on_finish=True)

    def _handle_stop(self) -> None:
        self.stop_btn.setEnabled(False)
        self.state_pill.setText("● Exporting Excel...")
        self.bridge.stop_session()

    def _on_snapshot(self, snap: TelemetrySnapshot) -> None:
        self.video_panel.update_from_snapshot(snap)
        self.joints_panel.update_from_snapshot(snap)
        self.status_panel.update_from_snapshot(snap)

        # Control states
        self.start_btn.setEnabled(not snap.is_running)
        self.stop_btn.setEnabled(snap.is_running and not self.bridge._is_stopping)
        self.simulate_chk.setEnabled(not snap.is_running)
        self.reset_cal_btn.setEnabled(snap.is_running)
        self.reset_session_btn.setEnabled(not snap.is_running)

        if snap.is_running and snap.is_calibrated:
            self.state_pill.setText("● Calibrated & Active")
            p_col = COLORS["ok"]
        elif snap.is_running:
            self.state_pill.setText("● Calibrating")
            p_col = COLORS["warn"]
        else:
            self.state_pill.setText("● Standby")
            p_col = COLORS["text_secondary"]
        self.state_pill.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {p_col}; "
            f"border-radius: 14px; padding: 5px 14px; font-weight: 700; color: {p_col};"
        )

    def _on_session_completed(self, results: SessionResults) -> None:
        self.video_panel.clear_video()
        self.bridge.poll_once()
        self.results_panel.load_session_results(results)

    def _on_session_error(self, message: str) -> None:
        self.bridge.poll_once()
        QMessageBox.critical(self, "Application Error", f"An error occurred in the session runner:\n{message}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.bridge.shutdown()
        event.accept()
