"""
Modular UI display panels for the Rehabilitation Monitor GUI.

Every widget in this module is strictly a visual presentation component:
it formats and renders values already computed by `main.py` / `RehabApplicationController`
and performs zero sensor, quaternion, calibration, alignment, Vision, or UKF math.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rehab_app import SessionAnalyzer, SessionResults
from rehab_app.vision import fmt
from rehab_monitor_gui.bridge import TelemetrySnapshot
from rehab_monitor_gui.styles import COLORS


def format_angle_deg(value: Optional[float]) -> str:
    """Format an angle value using the same numeric precision as `main.py` (`fmt`), plus degree symbol."""
    if value is None:
        return "None"
    try:
        val = float(value)
    except (TypeError, ValueError):
        return "None"
    if not math.isfinite(val):
        return "None"
    return f"{fmt(val)}°"


def format_velocity_deg_s(value: Optional[float]) -> str:
    if value is None:
        return "—"
    try:
        val = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(val):
        return "—"
    return f"{val:+6.1f} °/s"


def format_quaternion(q: Optional[Tuple[float, float, float, float]]) -> str:
    if q is None or len(q) != 4:
        return "Waiting for quaternion packet..."
    return f"W:{q[0]:+.3f}  X:{q[1]:+.3f}  Y:{q[2]:+.3f}  Z:{q[3]:+.3f}"


class MetricRowWidget(QWidget):
    """Single labeled telemetry row displaying a read-only measurement value."""

    def __init__(
        self,
        label_text: str,
        highlight: bool = False,
        accent_color: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(8)

        self.name_label = QLabel(label_text)
        name_color = COLORS["accent_blue"] if highlight else COLORS["text_secondary"]
        self.name_label.setStyleSheet(
            f"color: {name_color}; font-size: {'10.5pt' if highlight else '9.8pt'}; "
            f"font-weight: {'700' if highlight else '500'};"
        )

        self.value_label = QLabel("None")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        val_color = accent_color or (COLORS["ok"] if highlight else COLORS["text_primary"])
        val_size = "13.5pt" if highlight else "11.5pt"
        self.value_label.setStyleSheet(
            f"color: {val_color}; font-size: {val_size}; font-weight: 700; "
            f"font-family: 'Consolas', 'Cascadia Mono', 'Courier New', monospace;"
        )

        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_text(self, text: str) -> None:
        self.value_label.setText(text)

    def set_angle(self, value: Optional[float]) -> None:
        self.value_label.setText(format_angle_deg(value))


class VideoFeedPanel(QFrame):
    """
    Displays the live camera feed annotated by MediaPipe (`controller.get_latest_frame()`),
    camera stream status, posture feedback banner, and verbatim `main.py` telemetry lines.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header row
        header_row = QHBoxLayout()
        title = QLabel("Live Camera Feed & MediaPipe Pose Visualization")
        title.setStyleSheet(f"font-size: 11.5pt; font-weight: 700; color: {COLORS['accent_blue']};")
        self.vision_badge = QLabel("Camera: Idle")
        self.vision_badge.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 3px 10px; color: {COLORS['text_secondary']}; font-size: 9pt;"
        )
        header_row.addWidget(title)
        header_row.addStretch(1)
        header_row.addWidget(self.vision_badge)
        layout.addLayout(header_row)

        # Video viewport
        self.video_canvas = QLabel(
            "Camera stream inactive.\nClick 'Start Session' to run the rehabilitation application."
        )
        self.video_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_canvas.setMinimumSize(580, 400)
        self.video_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_canvas.setStyleSheet(
            f"background-color: {COLORS['bg_video']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; color: {COLORS['text_secondary']}; font-size: 10.5pt;"
        )
        layout.addWidget(self.video_canvas, stretch=1)

        # Posture feedback banner (matches bottom status text in main.py)
        self.posture_banner = QLabel("Posture Status: WAITING")
        self.posture_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.posture_banner.setFixedHeight(38)
        self.posture_banner.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; font-size: 11.5pt; font-weight: 700; color: {COLORS['text_primary']};"
        )
        layout.addWidget(self.posture_banner)

        # Verbatim `main.py` telemetry mirror card
        mirror_card = QFrame()
        mirror_card.setObjectName("subCard")
        mirror_layout = QVBoxLayout(mirror_card)
        mirror_layout.setContentsMargins(10, 8, 10, 8)
        mirror_layout.setSpacing(4)

        mirror_title = QLabel("Live main.py Telemetry Output (Active Phase Stream)")
        mirror_title.setStyleSheet(
            f"font-size: 9.2pt; font-weight: 700; color: {COLORS['accent_teal']};"
        )
        self.mirror_text_label = QLabel("")
        self.mirror_text_label.setStyleSheet(
            f"font-family: 'Consolas', 'Courier New', monospace; font-size: 9.5pt; "
            f"color: {COLORS['text_primary']};"
        )
        self.mirror_text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        mirror_layout.addWidget(mirror_title)
        mirror_layout.addWidget(self.mirror_text_label)
        layout.addWidget(mirror_card)

    def update_from_snapshot(self, snap: TelemetrySnapshot) -> None:
        # Camera badge
        vis_text = snap.vision_status
        self.vision_badge.setText(f"Vision: {vis_text}")
        if "ERROR" in vis_text.upper() or "UNAVAILABLE" in vis_text.upper():
            v_col = COLORS["danger"]
        elif snap.is_running:
            v_col = COLORS["ok"]
        else:
            v_col = COLORS["text_secondary"]
        self.vision_badge.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {v_col}; "
            f"border-radius: 10px; padding: 3px 10px; color: {v_col}; font-size: 9pt; font-weight: 600;"
        )

        # Frame rendering (MediaPipe visualization only — no OpenCV popup or text clutter)
        if snap.frame_bgr is not None:
            rgb = cv2.cvtColor(snap.frame_bgr, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            q_img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(q_img).scaled(
                self.video_canvas.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.video_canvas.setPixmap(pix)
        elif not snap.is_running and self.video_canvas.pixmap() is None:
            self.video_canvas.setText(
                "Camera stream inactive.\nClick 'Start Session' to run the rehabilitation application."
            )

        # Posture status banner
        posture = snap.posture_status or "WAITING"
        self.posture_banner.setText(f"Posture Status: {posture}")
        if posture == "RIGHT":
            p_col = COLORS["ok"]
        elif "START POSITION" in posture:
            p_col = COLORS["warn"]
        elif "WRONG" in posture or "NOT VISIBLE" in posture or "NO POSE" in posture:
            p_col = COLORS["danger"]
        else:
            p_col = COLORS["text_primary"]
        self.posture_banner.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {p_col}; "
            f"border-radius: 6px; font-size: 11.5pt; font-weight: 700; color: {p_col};"
        )

        # Render the exact lines produced by main.py in a compact 2-column grid text
        lines = snap.main_overlay_lines
        mid = (len(lines) + 1) // 2
        left_col = lines[:mid]
        right_col = lines[mid:]
        paired_rows = []
        for idx in range(mid):
            left_str = left_col[idx].ljust(36)
            right_str = right_col[idx] if idx < len(right_col) else ""
            paired_rows.append(f"{left_str}  {right_str}".rstrip())
        self.mirror_text_label.setText("\n".join(paired_rows))

    def clear_video(self) -> None:
        self.video_canvas.clear()
        self.video_canvas.setText(
            "Session stopped.\nClick 'Start Session' to begin a new rehabilitation run."
        )


class JointMeasurementsPanel(QFrame):
    """
    Structured GUI cards for Shoulder, Elbow, and Trunk measurements, showing:
    - MediaPipe Vision joint angles
    - Raw calibrated IMU relative angles
    - Dynamically aligned IMU angles
    - Fused UKF angles and UKF angular velocities
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Joint Angles, IMU Alignment & UKF Fusion")
        header.setStyleSheet(f"font-size: 11.5pt; font-weight: 700; color: {COLORS['accent_blue']};")
        layout.addWidget(header)

        # 1. Shoulder Section
        sh_card, sh_layout, self.sh_ref_badge = self._make_joint_section(
            "Shoulder Joint  (IMU 1 Pitch + Vision → UKF)"
        )
        self.row_sh_vision = MetricRowWidget("Shoulder Vision")
        self.row_sh_imu_raw = MetricRowWidget("IMU 1 Pitch (Raw)")
        self.row_sh_imu_aligned = MetricRowWidget(
            "IMU 1 Pitch (Aligned)", accent_color=COLORS["accent_teal"]
        )
        self.row_sh_ukf = MetricRowWidget("Shoulder UKF", highlight=True)
        self.row_sh_vel = MetricRowWidget("Shoulder UKF Velocity")
        for w in (
            self.row_sh_vision,
            self.row_sh_imu_raw,
            self.row_sh_imu_aligned,
            self.row_sh_ukf,
            self.row_sh_vel,
        ):
            sh_layout.addWidget(w)
        layout.addWidget(sh_card)

        # 2. Elbow Section
        el_card, el_layout, self.el_ref_badge = self._make_joint_section(
            "Elbow Joint  (IMU 1 Yaw + Vision → UKF)"
        )
        self.row_el_vision = MetricRowWidget("Elbow Vision")
        self.row_el_imu_raw = MetricRowWidget("IMU 1 Yaw (Raw)")
        self.row_el_imu_aligned = MetricRowWidget(
            "IMU 1 Yaw (Aligned)", accent_color=COLORS["accent_teal"]
        )
        self.row_el_ukf = MetricRowWidget("Elbow UKF", highlight=True)
        self.row_el_vel = MetricRowWidget("Elbow UKF Velocity")
        for w in (
            self.row_el_vision,
            self.row_el_imu_raw,
            self.row_el_imu_aligned,
            self.row_el_ukf,
            self.row_el_vel,
        ):
            el_layout.addWidget(w)
        layout.addWidget(el_card)

        # 3. Trunk Section
        tr_card, tr_layout, self.tr_badge = self._make_joint_section(
            "Trunk Orientation  (IMU 2 Pitch — Unfused)"
        )
        self.tr_badge.setText("Direct IMU 2")
        self.row_trunk = MetricRowWidget("IMU 2 Pitch / Trunk", highlight=True)
        tr_layout.addWidget(self.row_trunk)
        layout.addWidget(tr_card)

        layout.addStretch(1)

    @staticmethod
    def _make_joint_section(title_text: str) -> Tuple[QFrame, QVBoxLayout, QLabel]:
        card = QFrame()
        card.setObjectName("subCard")
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(10, 8, 10, 8)
        vbox.setSpacing(2)

        top = QHBoxLayout()
        lbl = QLabel(title_text)
        lbl.setStyleSheet(f"font-size: 10.2pt; font-weight: 700; color: {COLORS['accent_blue']};")
        badge = QLabel("Vision Ref: None")
        badge.setStyleSheet(
            f"font-size: 8.5pt; color: {COLORS['text_secondary']}; "
            f"font-family: 'Consolas', monospace;"
        )
        top.addWidget(lbl)
        top.addStretch(1)
        top.addWidget(badge)
        vbox.addLayout(top)
        return card, vbox, badge

    def update_from_snapshot(self, snap: TelemetrySnapshot) -> None:
        m = snap.measurements

        # Shoulder values
        self.row_sh_vision.set_angle(m.get("shoulder_vision_deg"))
        self.row_sh_imu_raw.set_angle(m.get("imu1_pitch_deg"))
        self.row_sh_imu_aligned.set_angle(m.get("imu1_shoulder_corrected_deg"))
        self.row_sh_ukf.set_angle(m.get("shoulder_ukf_deg"))
        self.row_sh_vel.set_text(format_velocity_deg_s(m.get("shoulder_ukf_velocity_deg_s")))
        self.sh_ref_badge.setText(f"Vision Ref: {format_angle_deg(snap.shoulder_vision_ref_deg)}")

        # Elbow values
        self.row_el_vision.set_angle(m.get("elbow_vision_deg"))
        self.row_el_imu_raw.set_angle(m.get("imu1_yaw_deg"))
        self.row_el_imu_aligned.set_angle(m.get("imu1_elbow_deg"))
        self.row_el_ukf.set_angle(m.get("elbow_ukf_deg"))
        self.row_el_vel.set_text(format_velocity_deg_s(m.get("elbow_ukf_velocity_deg_s")))
        self.el_ref_badge.setText(f"Vision Ref: {format_angle_deg(snap.elbow_vision_ref_deg)}")

        # Trunk value
        self.row_trunk.set_angle(m.get("trunk_angle_deg"))


class StatusAndRecordingPanel(QFrame):
    """
    Displays:
    - Sensor connection status, mode, and live raw quaternions (Sensor 1 & Sensor 2)
    - Calibration status, progress bar, and Vision reference summary
    - Experiment status, elapsed time, recorded sample count, and Excel recording output info
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Sensor Connection, Calibration & Experiment Status")
        header.setStyleSheet(f"font-size: 11.5pt; font-weight: 700; color: {COLORS['accent_blue']};")
        layout.addWidget(header)

        # 1. Sensor Connection & Raw Quaternions Card
        sensor_card = QFrame()
        sensor_card.setObjectName("subCard")
        s_grid = QGridLayout(sensor_card)
        s_grid.setContentsMargins(10, 8, 10, 8)
        s_grid.setHorizontalSpacing(10)
        s_grid.setVerticalSpacing(5)

        s_title = QLabel("Delsys Trigno Sensor Stream")
        s_title.setStyleSheet(f"font-weight: 700; color: {COLORS['accent_teal']};")
        s_grid.addWidget(s_title, 0, 0, 1, 2)

        s_grid.addWidget(self._caption("Connection:"), 1, 0)
        self.sensor_status_val = QLabel("Starting")
        self.sensor_status_val.setWordWrap(True)
        self.sensor_status_val.setStyleSheet("font-weight: 700;")
        s_grid.addWidget(self.sensor_status_val, 1, 1)

        s_grid.addWidget(self._caption("Sensor 1 (Arm):"), 2, 0)
        self.s1_info_val = QLabel("—")
        self.s1_info_val.setStyleSheet("font-family: 'Consolas', monospace; font-size: 9pt;")
        s_grid.addWidget(self.s1_info_val, 2, 1)

        s_grid.addWidget(self._caption("IMU 1 Quat:"), 3, 0)
        self.s1_quat_val = QLabel("Waiting for quaternion packet...")
        self.s1_quat_val.setStyleSheet("font-family: 'Consolas', monospace; font-size: 9pt;")
        s_grid.addWidget(self.s1_quat_val, 3, 1)

        s_grid.addWidget(self._caption("Sensor 2 (Trunk):"), 4, 0)
        self.s2_info_val = QLabel("—")
        self.s2_info_val.setStyleSheet("font-family: 'Consolas', monospace; font-size: 9pt;")
        s_grid.addWidget(self.s2_info_val, 4, 1)

        s_grid.addWidget(self._caption("IMU 2 Quat:"), 5, 0)
        self.s2_quat_val = QLabel("Waiting for quaternion packet...")
        self.s2_quat_val.setStyleSheet("font-family: 'Consolas', monospace; font-size: 9pt;")
        s_grid.addWidget(self.s2_quat_val, 5, 1)

        layout.addWidget(sensor_card)

        # 2. Calibration Status Card
        cal_card = QFrame()
        cal_card.setObjectName("subCard")
        c_layout = QVBoxLayout(cal_card)
        c_layout.setContentsMargins(10, 8, 10, 8)
        c_layout.setSpacing(6)

        c_top = QHBoxLayout()
        c_title = QLabel("Warm-Up & Neutral Calibration")
        c_title.setStyleSheet(f"font-weight: 700; color: {COLORS['accent_teal']};")
        self.cal_status_val = QLabel("Waiting")
        self.cal_status_val.setStyleSheet(f"font-weight: 700; color: {COLORS['warn']};")
        c_top.addWidget(c_title)
        c_top.addStretch(1)
        c_top.addWidget(self.cal_status_val)
        c_layout.addLayout(c_top)

        self.cal_progress = QProgressBar()
        self.cal_progress.setRange(0, 100)
        self.cal_progress.setValue(0)
        self.cal_progress.setFormat("Waiting (0%)")
        c_layout.addWidget(self.cal_progress)

        self.cal_refs_val = QLabel("Captured Vision Refs — Shoulder: None  |  Elbow: None")
        self.cal_refs_val.setStyleSheet(
            f"font-family: 'Consolas', monospace; font-size: 9pt; color: {COLORS['text_secondary']};"
        )
        c_layout.addWidget(self.cal_refs_val)
        layout.addWidget(cal_card)

        # 3. Experiment & Recording Info Card
        exp_card = QFrame()
        exp_card.setObjectName("subCard")
        e_grid = QGridLayout(exp_card)
        e_grid.setContentsMargins(10, 8, 10, 8)
        e_grid.setHorizontalSpacing(10)
        e_grid.setVerticalSpacing(5)

        e_title = QLabel("Experiment & Excel Recording")
        e_title.setStyleSheet(f"font-weight: 700; color: {COLORS['accent_teal']};")
        e_grid.addWidget(e_title, 0, 0, 1, 2)

        e_grid.addWidget(self._caption("Session State:"), 1, 0)
        self.exp_state_val = QLabel("Standby")
        self.exp_state_val.setStyleSheet("font-weight: 700;")
        e_grid.addWidget(self.exp_state_val, 1, 1)

        e_grid.addWidget(self._caption("Elapsed Time:"), 2, 0)
        self.elapsed_val = QLabel("00:00.0")
        self.elapsed_val.setStyleSheet("font-family: 'Consolas', monospace; font-weight: 700; font-size: 11pt;")
        e_grid.addWidget(self.elapsed_val, 2, 1)

        e_grid.addWidget(self._caption("Recorded Rows:"), 3, 0)
        self.samples_val = QLabel("0 samples")
        self.samples_val.setStyleSheet("font-family: 'Consolas', monospace; font-weight: 700;")
        e_grid.addWidget(self.samples_val, 3, 1)

        e_grid.addWidget(self._caption("Output Folder:"), 4, 0)
        self.rec_dir_val = QLabel("recordings/")
        self.rec_dir_val.setWordWrap(True)
        self.rec_dir_val.setStyleSheet(f"font-size: 8.8pt; color: {COLORS['text_secondary']};")
        e_grid.addWidget(self.rec_dir_val, 4, 1)

        e_grid.addWidget(self._caption("Last Workbook:"), 5, 0)
        self.last_wb_val = QLabel("None exported yet in this session")
        self.last_wb_val.setWordWrap(True)
        self.last_wb_val.setStyleSheet(f"font-size: 9pt; color: {COLORS['accent_blue']}; font-weight: 600;")
        e_grid.addWidget(self.last_wb_val, 5, 1)

        layout.addWidget(exp_card)
        layout.addStretch(1)

    @staticmethod
    def _caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 9.5pt;")
        return lbl

    def update_from_snapshot(self, snap: TelemetrySnapshot) -> None:
        # Sensor status (keep first line clean if .NET stack trace is present)
        first_line = snap.sensor_status.splitlines()[0] if snap.sensor_status else "Starting"
        self.sensor_status_val.setText(first_line)
        if "ERROR" in first_line.upper():
            s_col = COLORS["danger"]
        elif snap.is_running:
            s_col = COLORS["ok"]
        else:
            s_col = COLORS["text_secondary"]
        self.sensor_status_val.setStyleSheet(f"font-weight: 700; color: {s_col};")

        # Sensor 1 & 2 metadata + raw quaternion display
        s1_name = snap.sensor1_meta.get("name") or "Trigno Sensor 1"
        s1_mode = snap.sensor1_meta.get("mode") or ("Simulated 74 Hz" if snap.is_simulation else "OR 16 bits")
        self.s1_info_val.setText(f"{s1_name} [{s1_mode}] ({snap.sensor1_phase})")
        self.s1_quat_val.setText(format_quaternion(snap.sensor1_raw_q))

        s2_name = snap.sensor2_meta.get("name") or "Trigno Sensor 2"
        s2_mode = snap.sensor2_meta.get("mode") or ("Simulated 74 Hz" if snap.is_simulation else "OR 16 bits")
        self.s2_info_val.setText(f"{s2_name} [{s2_mode}] ({snap.sensor2_phase})")
        self.s2_quat_val.setText(format_quaternion(snap.sensor2_raw_q))

        # Calibration status & progress
        self.cal_status_val.setText(snap.calibration_status)
        if snap.is_calibrated:
            self.cal_status_val.setStyleSheet(f"font-weight: 700; color: {COLORS['ok']};")
            self.cal_progress.setValue(100)
            self.cal_progress.setFormat("Both Sensors Calibrated (100%)")
        else:
            self.cal_status_val.setStyleSheet(f"font-weight: 700; color: {COLORS['warn']};")
            match = re.search(r"(\d+)\s*/\s*(\d+)", snap.calibration_status)
            if match:
                cur_s = float(match.group(1))
                tot_s = max(1.0, float(match.group(2)))
                pct = min(99, max(0, int(round(100.0 * cur_s / tot_s))))
                self.cal_progress.setValue(pct)
                self.cal_progress.setFormat(f"{snap.calibration_status} ({pct}%)")
            elif snap.is_running:
                pct = min(99, max(1, int(round(100.0 * snap.elapsed_s / max(1.0, snap.total_calibration_seconds)))))
                self.cal_progress.setValue(pct)
                self.cal_progress.setFormat(f"{snap.calibration_status} ({pct}%)")
            else:
                self.cal_progress.setValue(0)
                self.cal_progress.setFormat("Waiting (0%)")

        self.cal_refs_val.setText(
            f"Captured Vision Refs — Shoulder: {format_angle_deg(snap.shoulder_vision_ref_deg)}  |  "
            f"Elbow: {format_angle_deg(snap.elbow_vision_ref_deg)}"
        )

        # Experiment & Recording state
        mins, secs = divmod(max(0.0, snap.elapsed_s), 60.0)
        self.elapsed_val.setText(f"{int(mins):02d}:{secs:04.1f}")
        self.samples_val.setText(f"{snap.recorded_samples:,} samples")
        self.rec_dir_val.setText(str(snap.recordings_dir))

        if snap.is_running and snap.is_calibrated:
            mode_tag = " (Simulation)" if snap.is_simulation else " (Live Hardware)"
            self.exp_state_val.setText(f"ACTIVE & RECORDING{mode_tag}")
            self.exp_state_val.setStyleSheet(f"font-weight: 700; color: {COLORS['ok']};")
        elif snap.is_running:
            self.exp_state_val.setText("WARMING UP / CALIBRATING")
            self.exp_state_val.setStyleSheet(f"font-weight: 700; color: {COLORS['warn']};")
        else:
            self.exp_state_val.setText("STANDBY")
            self.exp_state_val.setStyleSheet(f"font-weight: 700; color: {COLORS['text_secondary']};")

        if snap.last_workbook_path is not None:
            self.last_wb_val.setText(snap.last_workbook_path.name)


class SessionResultsPanel(QWidget):
    """
    Read-only viewer for Excel recordings and PNG plots generated by `main.py`'s
    `SessionRecorder` and `SessionAnalyzer`.
    """

    def __init__(self, recordings_dir: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.recordings_dir = Path(recordings_dir)
        self._current_plots: Dict[str, Path] = {}
        self._build_ui()
        self.refresh_workbooks()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Top selector bar
        bar = QFrame()
        bar.setObjectName("sectionCard")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        bar_layout.setSpacing(10)

        bar_layout.addWidget(QLabel("Recorded Workbook:"))
        self.workbook_combo = QComboBox()
        self.workbook_combo.setMinimumWidth(340)
        self.workbook_combo.currentIndexChanged.connect(self._on_workbook_selected)
        bar_layout.addWidget(self.workbook_combo, stretch=1)

        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(lambda: self.refresh_workbooks())
        bar_layout.addWidget(self.refresh_btn)

        bar_layout.addWidget(QLabel("Diagnostic Plot:"))
        self.plot_combo = QComboBox()
        self.plot_combo.setMinimumWidth(240)
        self.plot_combo.currentIndexChanged.connect(self._render_selected_plot)
        bar_layout.addWidget(self.plot_combo)
        layout.addWidget(bar)

        # Body split: Metrics table on top, Plot preview on bottom
        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        table_card = QFrame()
        table_card.setObjectName("sectionCard")
        t_layout = QVBoxLayout(table_card)
        t_layout.setContentsMargins(10, 10, 10, 10)
        t_title = QLabel("Exported Consistency & Summary Metrics (Read from Workbook)")
        t_title.setStyleSheet(f"font-weight: 700; color: {COLORS['accent_blue']};")
        self.metrics_table = QTableWidget(0, 0)
        self.metrics_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t_layout.addWidget(t_title)
        t_layout.addWidget(self.metrics_table, stretch=1)
        content_row.addWidget(table_card, stretch=1)

        plot_card = QFrame()
        plot_card.setObjectName("sectionCard")
        p_layout = QVBoxLayout(plot_card)
        p_layout.setContentsMargins(10, 10, 10, 10)
        p_title = QLabel("Generated Analysis Plot")
        p_title.setStyleSheet(f"font-weight: 700; color: {COLORS['accent_blue']};")
        self.plot_scroll = QScrollArea()
        self.plot_scroll.setWidgetResizable(True)
        self.plot_label = QLabel("Complete a session or select a saved workbook to view plots.")
        self.plot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_scroll.setWidget(self.plot_label)
        p_layout.addWidget(p_title)
        p_layout.addWidget(self.plot_scroll, stretch=1)
        content_row.addWidget(plot_card, stretch=1)

        layout.addLayout(content_row, stretch=1)

    def refresh_workbooks(self, select_path: Optional[Path] = None) -> None:
        self.workbook_combo.blockSignals(True)
        self.workbook_combo.clear()
        files = []
        if self.recordings_dir.is_dir():
            files = sorted(
                self.recordings_dir.glob("*.xlsx"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        for f in files:
            self.workbook_combo.addItem(f.name, str(f))

        target_idx = 0
        if select_path is not None:
            for idx in range(self.workbook_combo.count()):
                if Path(self.workbook_combo.itemData(idx)).resolve() == select_path.resolve():
                    target_idx = idx
                    break
        if self.workbook_combo.count() > 0:
            self.workbook_combo.setCurrentIndex(target_idx)
        self.workbook_combo.blockSignals(False)
        self._on_workbook_selected()

    def load_session_results(self, results: SessionResults) -> None:
        if results.workbook_path is not None:
            self.refresh_workbooks(select_path=results.workbook_path)

    def _on_workbook_selected(self) -> None:
        idx = self.workbook_combo.currentIndex()
        if idx < 0:
            self.metrics_table.setRowCount(0)
            self.plot_combo.clear()
            return
        wb_path = Path(self.workbook_combo.itemData(idx))
        if not wb_path.is_file():
            return

        try:
            metrics_df = pd.read_excel(wb_path, sheet_name="Metrics")
            self._populate_table(metrics_df)
        except Exception as exc:
            self.plot_label.setText(f"Could not read Metrics sheet: {exc}")

        analysis_dir = wb_path.parent / f"{wb_path.stem}_analysis"
        if not analysis_dir.is_dir():
            try:
                SessionAnalyzer().analyze_workbook(wb_path, update_workbook_metrics=False)
            except Exception:
                pass

        self._current_plots.clear()
        self.plot_combo.blockSignals(True)
        self.plot_combo.clear()
        if analysis_dir.is_dir():
            for png in sorted(analysis_dir.glob("*.png")):
                self._current_plots[png.stem] = png
                self.plot_combo.addItem(png.stem.replace("_", " ").title(), png.stem)
        self.plot_combo.blockSignals(False)
        self._render_selected_plot()

    def _populate_table(self, df: pd.DataFrame) -> None:
        self.metrics_table.setColumnCount(len(df.columns))
        self.metrics_table.setRowCount(len(df))
        self.metrics_table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r_idx in range(len(df)):
            for c_idx, col in enumerate(df.columns):
                val = df.iloc[r_idx, c_idx]
                txt = "" if pd.isna(val) else str(val)
                self.metrics_table.setItem(r_idx, c_idx, QTableWidgetItem(txt))
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def _render_selected_plot(self) -> None:
        idx = self.plot_combo.currentIndex()
        if idx < 0:
            self.plot_label.clear()
            self.plot_label.setText("No plot PNGs found for this workbook.")
            return
        key = self.plot_combo.itemData(idx)
        png_path = self._current_plots.get(key)
        if png_path is None or not png_path.is_file():
            return
        pix = QPixmap(str(png_path))
        if not pix.isNull():
            scaled = pix.scaled(
                max(420, self.plot_scroll.viewport().width() - 20),
                max(320, self.plot_scroll.viewport().height() - 20),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.plot_label.setPixmap(scaled)
