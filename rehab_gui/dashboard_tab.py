"""
Main Dashboard tab for the Rehabilitation GUI.

Displays:
1. Live webcam video feed with MediaPipe pose landmarks and skeleton.
2. Exercise posture status banner.
3. Live sensor, vision, and UKF fused angle cards:
   - Shoulder: Vision angle, IMU 1 Pitch, Shoulder UKF angle.
   - Elbow: Vision angle, IMU 1 Yaw, IMU 1 Yaw + 90°, Elbow UKF angle.
   - Trunk: IMU 2 Pitch / Trunk angle (unfused).
4. Sensor connection status, calibration status & progress bar, and elapsed time.
5. Experiment controls:
   - Connect / Disconnect Delsys (supports both real Delsys hardware and simulation mode).
   - Start / Reset Calibration.
   - Start Experiment (guarded until sensors are connected and calibration is complete).
   - Stop Experiment (exports Excel workbook & runs analysis in background).
   - Reset Session.
   - Open Results & Analysis tab.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rehab_gui.theme import PALETTE


def _format_deg(val: Optional[float]) -> str:
    """Format an angle reading in degrees for display on a telemetry card."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "— °"
    return f"{float(val):+6.1f} °"


class AngleValueRow(QWidget):
    """A single labeled measurement row inside a joint telemetry card."""

    def __init__(self, label_text: str, is_highlighted: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(8)

        self.title_label = QLabel(label_text)
        self.title_label.setStyleSheet(
            f"color: {PALETTE['tab_selected_bg'] if is_highlighted else PALETTE['text_secondary']}; "
            f"font-size: {'11pt' if is_highlighted else '10pt'}; "
            f"font-weight: {'700' if is_highlighted else '500'};"
        )

        self.value_label = QLabel("— °")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val_color = PALETTE["status_ok"] if is_highlighted else PALETTE["text_primary"]
        val_size = "14pt" if is_highlighted else "12pt"
        self.value_label.setStyleSheet(
            f"color: {val_color}; font-size: {val_size}; font-weight: bold; "
            f"font-family: 'Consolas', 'Courier New', monospace;"
        )

        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_angle(self, value: Optional[float]) -> None:
        self.value_label.setText(_format_deg(value))


class DashboardTab(QWidget):
    """Main real-time monitoring dashboard and experiment control panel."""

    def __init__(
        self,
        on_connect_toggled: Callable[[], None],
        on_start_experiment: Callable[[], None],
        on_stop_experiment: Callable[[], None],
        on_reset_calibration: Callable[[], None],
        on_reset_session: Callable[[], None],
        on_view_results: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._build_ui(
            on_connect_toggled=on_connect_toggled,
            on_start_experiment=on_start_experiment,
            on_stop_experiment=on_stop_experiment,
            on_reset_calibration=on_reset_calibration,
            on_reset_session=on_reset_session,
            on_view_results=on_view_results,
        )

    def _build_ui(
        self,
        on_connect_toggled: Callable[[], None],
        on_start_experiment: Callable[[], None],
        on_stop_experiment: Callable[[], None],
        on_reset_calibration: Callable[[], None],
        on_reset_session: Callable[[], None],
        on_view_results: Callable[[], None],
    ) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(14)

        # =====================================================================
        # LEFT COLUMN: LIVE WEBCAM FEED, POSTURE BANNER & EXPERIMENT CONTROLS
        # =====================================================================
        left_panel = QFrame()
        left_panel.setObjectName("panelCard")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        # Video header row
        video_header = QHBoxLayout()
        video_title = QLabel("Live Webcam & MediaPipe Pose Tracking")
        video_title.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {PALETTE['tab_selected_bg']};")
        video_header.addWidget(video_title)
        video_header.addStretch(1)
        left_layout.addLayout(video_header)

        # Webcam display area
        self.video_label = QLabel("Camera feed inactive.\nClick 'Connect Delsys' to begin sensor warm-up and camera preview.")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(640, 440)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_label.setStyleSheet(
            f"background-color: #141829; border: 1px solid {PALETTE['border']}; "
            f"border-radius: 6px; color: {PALETTE['text_secondary']}; font-size: 11pt;"
        )
        left_layout.addWidget(self.video_label, stretch=1)

        # Exercise posture feedback banner
        self.posture_banner = QLabel("Posture Feedback: WAITING FOR SESSION")
        self.posture_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.posture_banner.setFixedHeight(40)
        self.posture_banner.setStyleSheet(
            f"background-color: {PALETTE['bg_card']}; border: 1px solid {PALETTE['border']}; "
            f"border-radius: 6px; font-size: 12pt; font-weight: bold; color: {PALETTE['text_primary']};"
        )
        left_layout.addWidget(self.posture_banner)

        # Experiment controls bar
        controls_frame = QFrame()
        controls_frame.setObjectName("metricCard")
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(8)

        mode_row = QHBoxLayout()
        self.simulate_checkbox = QCheckBox("Use Simulated Delsys Sensors (74 Hz Quaternion Stream)")
        self.simulate_checkbox.setToolTip(
            "When checked, streams simulated 74 Hz Delsys W,X,Y,Z quaternions so you can test "
            "the full GUI and live webcam without physical Delsys Trigno sensors plugged in."
        )
        self.control_hint_label = QLabel("Step 1: Connect sensors and complete neutral calibration.")
        self.control_hint_label.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 9.5pt;")
        mode_row.addWidget(self.simulate_checkbox)
        mode_row.addStretch(1)
        mode_row.addWidget(self.control_hint_label)
        controls_layout.addLayout(mode_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.connect_btn = QPushButton("Connect Delsys")
        self.connect_btn.setProperty("role", "primary")
        self.connect_btn.setMinimumHeight(40)
        self.connect_btn.setToolTip("Connect to Delsys Trigno sensors (or simulated stream) and start calibration.")
        self.connect_btn.clicked.connect(on_connect_toggled)

        self.reset_cal_btn = QPushButton("Reset Calibration")
        self.reset_cal_btn.setMinimumHeight(40)
        self.reset_cal_btn.setEnabled(False)
        self.reset_cal_btn.setToolTip("Restart the warm-up and neutral quaternion calibration window.")
        self.reset_cal_btn.clicked.connect(on_reset_calibration)

        self.start_exp_btn = QPushButton("Start Experiment")
        self.start_exp_btn.setProperty("role", "primary")
        self.start_exp_btn.setMinimumHeight(40)
        self.start_exp_btn.setEnabled(False)
        self.start_exp_btn.setToolTip("Start recording the rehabilitation experiment (requires calibrated sensors).")
        self.start_exp_btn.clicked.connect(on_start_experiment)

        self.stop_exp_btn = QPushButton("Stop Experiment")
        self.stop_exp_btn.setProperty("role", "danger")
        self.stop_exp_btn.setMinimumHeight(40)
        self.stop_exp_btn.setEnabled(False)
        self.stop_exp_btn.setToolTip("Stop recording, export the 4-sheet Excel workbook, and generate analysis plots.")
        self.stop_exp_btn.clicked.connect(on_stop_experiment)

        self.reset_session_btn = QPushButton("Reset Session")
        self.reset_session_btn.setMinimumHeight(40)
        self.reset_session_btn.setToolTip("Clear current session measurements and reset UKF filter states.")
        self.reset_session_btn.clicked.connect(on_reset_session)

        self.view_results_btn = QPushButton("Results && Plots")
        self.view_results_btn.setMinimumHeight(40)
        self.view_results_btn.setToolTip("Open the Results & Analysis tab to inspect saved Excel files and plots.")
        self.view_results_btn.clicked.connect(on_view_results)

        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.reset_cal_btn)
        btn_row.addWidget(self.start_exp_btn)
        btn_row.addWidget(self.stop_exp_btn)
        btn_row.addWidget(self.reset_session_btn)
        btn_row.addWidget(self.view_results_btn)
        controls_layout.addLayout(btn_row)

        left_layout.addWidget(controls_frame)
        root_layout.addWidget(left_panel, stretch=3)

        # =====================================================================
        # RIGHT COLUMN: STATUS INDICATORS & JOINT TELEMETRY CARDS
        # =====================================================================
        right_panel = QFrame()
        right_panel.setObjectName("panelCard")
        right_panel.setMinimumWidth(410)
        right_panel.setMaximumWidth(480)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(12)

        # 1. System & Calibration Status Card
        status_card = QFrame()
        status_card.setObjectName("metricCard")
        status_grid = QGridLayout(status_card)
        status_grid.setContentsMargins(12, 10, 12, 10)
        status_grid.setHorizontalSpacing(10)
        status_grid.setVerticalSpacing(6)

        status_header = QLabel("System & Calibration Status")
        status_header.setStyleSheet(f"font-size: 11.5pt; font-weight: bold; color: {PALETTE['tab_selected_bg']};")
        status_grid.addWidget(status_header, 0, 0, 1, 2)

        status_grid.addWidget(self._make_caption("Sensor Status:"), 1, 0)
        self.sensor_status_label = QLabel("Disconnected")
        self.sensor_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['text_secondary']};")
        self.sensor_status_label.setWordWrap(True)
        status_grid.addWidget(self.sensor_status_label, 1, 1)

        status_grid.addWidget(self._make_caption("Calibration:"), 2, 0)
        self.calibration_status_label = QLabel("Waiting")
        self.calibration_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_warn']};")
        status_grid.addWidget(self.calibration_status_label, 2, 1)

        self.calibration_progress = QProgressBar()
        self.calibration_progress.setRange(0, 100)
        self.calibration_progress.setValue(0)
        self.calibration_progress.setFormat("Calibration Progress: %p%")
        status_grid.addWidget(self.calibration_progress, 3, 0, 1, 2)

        status_grid.addWidget(self._make_caption("Experiment:"), 4, 0)
        self.experiment_status_label = QLabel("Idle")
        self.experiment_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['text_secondary']};")
        status_grid.addWidget(self.experiment_status_label, 4, 1)

        status_grid.addWidget(self._make_caption("Elapsed / Samples:"), 5, 0)
        self.elapsed_label = QLabel("00:00.0  (0 samples)")
        self.elapsed_label.setStyleSheet(
            f"font-weight: bold; font-family: 'Consolas', monospace; color: {PALETTE['text_primary']};"
        )
        status_grid.addWidget(self.elapsed_label, 5, 1)

        right_layout.addWidget(status_card)

        # 2. Shoulder Joint Card (IMU 1 Pitch + Shoulder Vision -> Shoulder UKF)
        shoulder_card = self._build_joint_card(
            title="Shoulder Joint (IMU 1 Pitch + Vision → UKF)",
            subtitle="Fuses calibrated IMU 1 Pitch with MediaPipe Right Shoulder angle",
        )
        self.row_shoulder_vision = AngleValueRow("Shoulder Vision (MediaPipe)")
        self.row_imu1_pitch = AngleValueRow("IMU 1 Pitch (Calibrated)")
        self.row_shoulder_ukf = AngleValueRow("Shoulder UKF (Fused)", is_highlighted=True)
        shoulder_card.layout().addWidget(self.row_shoulder_vision)
        shoulder_card.layout().addWidget(self.row_imu1_pitch)
        shoulder_card.layout().addWidget(self.row_shoulder_ukf)
        right_layout.addWidget(shoulder_card)

        # 3. Elbow Joint Card (IMU 1 Yaw + 90° + Elbow Vision -> Elbow UKF)
        elbow_card = self._build_joint_card(
            title="Elbow Joint (IMU 1 Yaw + 90° + Vision → UKF)",
            subtitle="Applies +90° offset to IMU 1 Yaw before UKF update with Elbow Vision",
        )
        self.row_elbow_vision = AngleValueRow("Elbow Vision (MediaPipe)")
        self.row_imu1_yaw = AngleValueRow("IMU 1 Yaw (Raw Calibrated)")
        self.row_imu1_elbow = AngleValueRow("IMU 1 Yaw + 90° (Elbow IMU)")
        self.row_elbow_ukf = AngleValueRow("Elbow UKF (Fused)", is_highlighted=True)
        elbow_card.layout().addWidget(self.row_elbow_vision)
        elbow_card.layout().addWidget(self.row_imu1_yaw)
        elbow_card.layout().addWidget(self.row_imu1_elbow)
        elbow_card.layout().addWidget(self.row_elbow_ukf)
        right_layout.addWidget(elbow_card)

        # 4. Trunk Angle Card (IMU 2 Pitch, unfused)
        trunk_card = self._build_joint_card(
            title="Trunk Orientation (IMU 2 Pitch — Unfused)",
            subtitle="Direct calibrated pitch from Sensor 2 without UKF fusion",
        )
        self.row_trunk_pitch = AngleValueRow("IMU 2 Pitch / Trunk Angle", is_highlighted=True)
        trunk_card.layout().addWidget(self.row_trunk_pitch)
        right_layout.addWidget(trunk_card)

        right_layout.addStretch(1)
        root_layout.addWidget(right_panel, stretch=2)

    @staticmethod
    def _make_caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 10pt;")
        return lbl

    @staticmethod
    def _build_joint_card(title: str, subtitle: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {PALETTE['tab_selected_bg']};")
        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(f"font-size: 8.8pt; color: {PALETTE['text_secondary']}; margin-bottom: 4px;")
        layout.addWidget(title_lbl)
        layout.addWidget(sub_lbl)
        return card

    def update_telemetry(
        self,
        measurements: Dict[str, Any],
        status: Dict[str, Any],
        is_connected: bool,
        is_recording_experiment: bool,
        total_cal_seconds: float,
    ) -> None:
        """Update all dashboard angle labels, status badges, progress bar, and button states."""
        # Update angle cards
        self.row_shoulder_vision.set_angle(measurements.get("shoulder_vision_deg"))
        self.row_imu1_pitch.set_angle(measurements.get("imu1_pitch_deg"))
        self.row_shoulder_ukf.set_angle(measurements.get("shoulder_ukf_deg"))

        self.row_elbow_vision.set_angle(measurements.get("elbow_vision_deg"))
        self.row_imu1_yaw.set_angle(measurements.get("imu1_yaw_deg"))
        self.row_imu1_elbow.set_angle(measurements.get("imu1_elbow_deg"))
        self.row_elbow_ukf.set_angle(measurements.get("elbow_ukf_deg"))

        self.row_trunk_pitch.set_angle(measurements.get("trunk_angle_deg"))

        # Update sensor status label (truncate multi-line .NET stack traces cleanly for the card)
        raw_sensor_text = str(status.get("sensor", "Disconnected")).splitlines()[0]
        self.sensor_status_label.setText(raw_sensor_text)
        if "ERROR" in raw_sensor_text.upper():
            self.sensor_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_error']};")
        elif is_connected:
            self.sensor_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_ok']};")
        else:
            self.sensor_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['text_secondary']};")

        # Update calibration status and progress percentage
        cal_text = str(status.get("calibration", "Waiting"))
        is_calibrated = bool(status.get("is_calibrated", False))
        self.calibration_status_label.setText(cal_text)

        if is_calibrated:
            self.calibration_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_ok']};")
            self.calibration_progress.setValue(100)
            self.calibration_progress.setFormat("Both Sensors Calibrated (100%)")
        else:
            self.calibration_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_warn']};")
            match = re.search(r"(\d+)\s*/\s*(\d+)", cal_text)
            if match:
                cur_s, tot_s = float(match.group(1)), max(1.0, float(match.group(2)))
                pct = min(99, max(0, int(round(100.0 * cur_s / tot_s))))
                self.calibration_progress.setValue(pct)
                self.calibration_progress.setFormat(f"{cal_text} ({pct}%)")
            elif is_connected:
                self.calibration_progress.setValue(5)
                self.calibration_progress.setFormat(cal_text)
            else:
                self.calibration_progress.setValue(0)
                self.calibration_progress.setFormat("Waiting for sensor connection")

        # Update experiment recording status and elapsed time
        elapsed_s = float(measurements.get("elapsed_s") or 0.0)
        samples = int(status.get("recorded_samples") or 0)
        mins, secs = divmod(max(0.0, elapsed_s), 60.0)

        if is_recording_experiment:
            self.experiment_status_label.setText("RECORDING EXPERIMENT")
            self.experiment_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_ok']};")
            self.elapsed_label.setText(f"{int(mins):02d}:{secs:04.1f}  ({samples} samples)")
        elif is_connected and is_calibrated:
            self.experiment_status_label.setText("Ready to Start Experiment")
            self.experiment_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['tab_selected_bg']};")
            self.elapsed_label.setText(f"00:00.0  ({samples} samples buffered)")
        elif is_connected:
            self.experiment_status_label.setText("Warming Up / Calibrating Sensors...")
            self.experiment_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['status_warn']};")
            self.elapsed_label.setText(f"{int(mins):02d}:{secs:04.1f}")
        else:
            self.experiment_status_label.setText("Standby (Sensors Disconnected)")
            self.experiment_status_label.setStyleSheet(f"font-weight: bold; color: {PALETTE['text_secondary']};")
            self.elapsed_label.setText(f"00:00.0  ({samples} samples)")

        # Update posture feedback banner
        posture = str(measurements.get("posture_status") or "WAITING")
        self.posture_banner.setText(f"Posture Feedback: {posture}")
        if posture == "RIGHT":
            p_color = PALETTE["status_ok"]
        elif "START POSITION" in posture:
            p_color = PALETTE["status_warn"]
        elif "WRONG" in posture or "NOT VISIBLE" in posture:
            p_color = PALETTE["status_error"]
        else:
            p_color = PALETTE["text_primary"]
        self.posture_banner.setStyleSheet(
            f"background-color: {PALETTE['bg_card']}; border: 1px solid {p_color}; "
            f"border-radius: 6px; font-size: 12pt; font-weight: bold; color: {p_color};"
        )

        # Update button lock states to prevent invalid operations
        self.connect_btn.setText("Disconnect Delsys" if is_connected else "Connect Delsys")
        self.connect_btn.setEnabled(not is_recording_experiment)
        self.simulate_checkbox.setEnabled(not is_connected and not is_recording_experiment)
        self.reset_cal_btn.setEnabled(is_connected and not is_recording_experiment)

        has_sensor_error = "ERROR" in raw_sensor_text.upper()
        can_start_experiment = is_connected and is_calibrated and not is_recording_experiment and not has_sensor_error
        self.start_exp_btn.setEnabled(can_start_experiment)
        self.stop_exp_btn.setEnabled(is_recording_experiment)
        self.reset_session_btn.setEnabled(not is_recording_experiment)

        if is_recording_experiment:
            self.control_hint_label.setText("Experiment recording in progress. Click 'Stop Experiment' to finish & export.")
        elif can_start_experiment:
            self.control_hint_label.setText("Calibration complete! Click 'Start Experiment' to begin recording.")
        elif is_connected and has_sensor_error:
            self.control_hint_label.setText("Delsys connection error. Reconnect hardware or enable Simulated Sensors.")
        elif is_connected:
            self.control_hint_label.setText(
                f"Keep sensors stationary during warm-up & calibration ({total_cal_seconds:.0f} s total)..."
            )
        else:
            self.control_hint_label.setText("Step 1: Click 'Connect Delsys' to connect sensors and start calibration.")

    def update_video_frame(
        self,
        bgr_frame: Optional[np.ndarray],
        measurements: Dict[str, Any],
    ) -> None:
        """Render the latest BGR frame (with MediaPipe landmarks) into `self.video_label`."""
        if bgr_frame is None:
            return
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        q_img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img).scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)
