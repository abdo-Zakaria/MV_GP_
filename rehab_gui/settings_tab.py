"""
Settings tab for configuring camera, Delsys sensors, calibration durations,
UKF parameters, and Excel recording options.

Communicates directly with `RehabApplicationController.get_settings()` and
`RehabApplicationController.update_settings(**kwargs)` without changing any
default values or duplicating validation logic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rehab_app.config import RehabConfig
from rehab_app.controller import RehabApplicationController
from rehab_gui.theme import PALETTE


class SettingsTab(QWidget):
    """Organized settings view for all configurable parameters in `RehabConfig`."""

    def __init__(
        self,
        controller: RehabApplicationController,
        on_settings_applied: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.on_settings_applied = on_settings_applied
        self._build_ui()
        self.load_from_config(self.controller.config)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        # 1. Camera & MediaPipe Vision Group
        vision_group = QGroupBox("Camera & MediaPipe Vision Settings")
        vision_form = QFormLayout(vision_group)
        vision_form.setSpacing(8)

        self.camera_index_spin = self._make_int_spin(0, 10)
        self.camera_hz_spin = self._make_float_spin(1.0, 120.0, decimals=1, step=5.0)
        self.visibility_min_spin = self._make_float_spin(0.0, 1.0, decimals=2, step=0.05)
        self.shoulder_z_tol_spin = self._make_float_spin(0.01, 1.0, decimals=3, step=0.01)
        self.landmark_alpha_spin = self._make_float_spin(0.01, 1.0, decimals=2, step=0.05)
        self.min_confidence_spin = self._make_float_spin(0.0, 1.0, decimals=2, step=0.05)
        self.flip_horizontal_chk = QCheckBox("Mirror / Flip Camera Horizontally")

        vision_form.addRow("Camera Index:", self.camera_index_spin)
        vision_form.addRow("Target Loop Rate (Hz):", self.camera_hz_spin)
        vision_form.addRow("Min Landmark Visibility (0–1):", self.visibility_min_spin)
        vision_form.addRow("Shoulder Z Tolerance:", self.shoulder_z_tol_spin)
        vision_form.addRow("Landmark Smoothing Alpha (0–1]:", self.landmark_alpha_spin)
        vision_form.addRow("Min Pose Detection Confidence:", self.min_confidence_spin)
        vision_form.addRow("", self.flip_horizontal_chk)
        grid.addWidget(vision_group, 0, 0)

        # 2. Delsys Trigno Sensor & Calibration Group
        sensor_group = QGroupBox("Delsys Sensors & Calibration Settings")
        sensor_form = QFormLayout(sensor_group)
        sensor_form.setSpacing(8)

        self.sensor1_index_spin = self._make_int_spin(0, 15)
        self.sensor2_index_spin = self._make_int_spin(0, 15)
        self.warmup_sec_spin = self._make_float_spin(0.0, 600.0, decimals=1, step=5.0)
        self.calibration_sec_spin = self._make_float_spin(0.5, 120.0, decimals=1, step=1.0)
        self.deadband_deg_spin = self._make_float_spin(0.0, 30.0, decimals=1, step=0.5)
        self.elbow_offset_deg_spin = self._make_float_spin(-180.0, 180.0, decimals=1, step=5.0)
        self.sensor_stale_sec_spin = self._make_float_spin(0.1, 30.0, decimals=2, step=0.1)

        sensor_form.addRow("Sensor 1 Index (Upper Limb):", self.sensor1_index_spin)
        sensor_form.addRow("Sensor 2 Index (Trunk):", self.sensor2_index_spin)
        sensor_form.addRow("Stationary Warm-Up Duration (s):", self.warmup_sec_spin)
        sensor_form.addRow("Neutral Calibration Window (s):", self.calibration_sec_spin)
        sensor_form.addRow("Zero Deadband Threshold (deg):", self.deadband_deg_spin)
        sensor_form.addRow("Elbow IMU Yaw Offset (deg):", self.elbow_offset_deg_spin)
        sensor_form.addRow("Sensor Staleness Timeout (s):", self.sensor_stale_sec_spin)
        grid.addWidget(sensor_group, 0, 1)

        # 3. Unscented Kalman Filter (UKF) Parameters Group
        ukf_group = QGroupBox("Unscented Kalman Filter (UKF) Tuning")
        ukf_form = QFormLayout(ukf_group)
        ukf_form.setSpacing(8)

        self.q_angle_spin = self._make_float_spin(0.001, 1000.0, decimals=3, step=0.5)
        self.q_velocity_spin = self._make_float_spin(0.001, 2000.0, decimals=2, step=5.0)
        self.r_imu_spin = self._make_float_spin(0.001, 1000.0, decimals=2, step=1.0)
        self.r_vision_spin = self._make_float_spin(0.001, 1000.0, decimals=2, step=1.0)
        self.init_p_angle_spin = self._make_float_spin(0.1, 5000.0, decimals=1, step=10.0)
        self.init_p_velocity_spin = self._make_float_spin(0.1, 5000.0, decimals=1, step=25.0)
        self.ukf_alpha_spin = self._make_float_spin(0.001, 2.0, decimals=3, step=0.05)
        self.ukf_beta_spin = self._make_float_spin(0.0, 10.0, decimals=2, step=0.5)
        self.ukf_kappa_spin = self._make_float_spin(-5.0, 10.0, decimals=2, step=0.5)

        ukf_form.addRow("Process Noise Q_angle:", self.q_angle_spin)
        ukf_form.addRow("Process Noise Q_velocity:", self.q_velocity_spin)
        ukf_form.addRow("IMU Measurement Variance R_IMU (deg²):", self.r_imu_spin)
        ukf_form.addRow("Vision Measurement Variance R_VISION (deg²):", self.r_vision_spin)
        ukf_form.addRow("Initial Covariance P_angle:", self.init_p_angle_spin)
        ukf_form.addRow("Initial Covariance P_velocity:", self.init_p_velocity_spin)
        ukf_form.addRow("Sigma-Point Scaling Alpha:", self.ukf_alpha_spin)
        ukf_form.addRow("Distribution Weight Beta:", self.ukf_beta_spin)
        ukf_form.addRow("Secondary Scaling Kappa:", self.ukf_kappa_spin)
        grid.addWidget(ukf_group, 1, 0)

        # 4. Recording & Output Settings Group
        rec_group = QGroupBox("Session Recording & Excel Export Settings")
        rec_form = QFormLayout(rec_group)
        rec_form.setSpacing(8)

        self.record_sec_spin = self._make_float_spin(1.0, 36000.0, decimals=1, step=60.0)
        dir_row = QHBoxLayout()
        self.recordings_dir_edit = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_recordings_dir)
        dir_row.addWidget(self.recordings_dir_edit, stretch=1)
        dir_row.addWidget(browse_btn)

        self.auto_analyze_chk = QCheckBox("Automatically Generate Analysis Plots on Experiment Stop")

        note_lbl = QLabel(
            "Note: Every session generates a uniquely named 4-sheet Excel workbook\n"
            "(RawData, ProcessedData, Metrics, Settings) inside the recordings folder\n"
            "without overwriting existing recordings."
        )
        note_lbl.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 9.5pt; margin-top: 6px;")
        note_lbl.setWordWrap(True)

        rec_form.addRow("Max Session Duration (s):", self.record_sec_spin)
        rec_form.addRow("Recordings Directory:", dir_row)
        rec_form.addRow("", self.auto_analyze_chk)
        rec_form.addRow("", note_lbl)
        grid.addWidget(rec_group, 1, 1)

        root_layout.addLayout(grid)

        # Bottom action bar
        action_bar = QFrame()
        action_bar.setObjectName("panelCard")
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(14, 10, 14, 10)

        self.status_msg_label = QLabel("Settings loaded from active configuration.")
        self.status_msg_label.setStyleSheet(f"color: {PALETTE['text_secondary']};")

        self.restore_defaults_btn = QPushButton("Restore Original Defaults")
        self.restore_defaults_btn.setMinimumHeight(38)
        self.restore_defaults_btn.clicked.connect(self.restore_defaults)

        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.setProperty("role", "primary")
        self.apply_btn.setMinimumHeight(38)
        self.apply_btn.clicked.connect(self.apply_settings)

        action_layout.addWidget(self.status_msg_label)
        action_layout.addStretch(1)
        action_layout.addWidget(self.restore_defaults_btn)
        action_layout.addWidget(self.apply_btn)
        root_layout.addWidget(action_bar)
        root_layout.addStretch(1)

        self.form_groups = [vision_group, sensor_group, ukf_group, rec_group]

    @staticmethod
    def _make_int_spin(min_val: int, max_val: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        return spin

    @staticmethod
    def _make_float_spin(min_val: float, max_val: float, decimals: int = 2, step: float = 0.1) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        return spin

    def _browse_recordings_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Recordings Directory", self.recordings_dir_edit.text()
        )
        if chosen:
            self.recordings_dir_edit.setText(chosen)

    def set_editing_enabled(self, enabled: bool) -> None:
        """Disable settings editing while sensor streaming or recording is active."""
        for grp in self.form_groups:
            grp.setEnabled(enabled)
        self.apply_btn.setEnabled(enabled)
        self.restore_defaults_btn.setEnabled(enabled)
        if not enabled:
            self.status_msg_label.setText("Settings are locked while sensors or experiment are running.")
            self.status_msg_label.setStyleSheet(f"color: {PALETTE['status_warn']};")

    def load_from_config(self, cfg: RehabConfig) -> None:
        """Populate UI spinboxes and checkboxes from a RehabConfig instance."""
        self.camera_index_spin.setValue(cfg.camera_index)
        self.camera_hz_spin.setValue(cfg.camera_loop_hz)
        self.visibility_min_spin.setValue(cfg.visibility_min)
        self.shoulder_z_tol_spin.setValue(cfg.shoulder_z_tolerance)
        self.landmark_alpha_spin.setValue(cfg.landmark_alpha)
        self.min_confidence_spin.setValue(cfg.min_pose_confidence)
        self.flip_horizontal_chk.setChecked(cfg.flip_camera_horizontal)

        self.sensor1_index_spin.setValue(cfg.sensor1_index)
        self.sensor2_index_spin.setValue(cfg.sensor2_index)
        self.warmup_sec_spin.setValue(cfg.warmup_seconds)
        self.calibration_sec_spin.setValue(cfg.calibration_seconds)
        self.deadband_deg_spin.setValue(cfg.zero_deadband_deg)
        self.elbow_offset_deg_spin.setValue(cfg.elbow_imu_offset_deg)
        self.sensor_stale_sec_spin.setValue(cfg.sensor_stale_seconds)

        self.q_angle_spin.setValue(cfg.q_angle)
        self.q_velocity_spin.setValue(cfg.q_velocity)
        self.r_imu_spin.setValue(cfg.r_imu)
        self.r_vision_spin.setValue(cfg.r_vision)
        self.init_p_angle_spin.setValue(cfg.initial_p_angle)
        self.init_p_velocity_spin.setValue(cfg.initial_p_velocity)
        self.ukf_alpha_spin.setValue(cfg.ukf_alpha)
        self.ukf_beta_spin.setValue(cfg.ukf_beta)
        self.ukf_kappa_spin.setValue(cfg.ukf_kappa)

        self.record_sec_spin.setValue(cfg.record_seconds)
        self.recordings_dir_edit.setText(str(cfg.recordings_dir))
        self.auto_analyze_chk.setChecked(cfg.auto_analyze_on_stop)

    def collect_form_values(self) -> Dict[str, Any]:
        """Read current form values into a dictionary matching `RehabConfig` field names."""
        return {
            "camera_index": int(self.camera_index_spin.value()),
            "camera_loop_hz": float(self.camera_hz_spin.value()),
            "visibility_min": float(self.visibility_min_spin.value()),
            "shoulder_z_tolerance": float(self.shoulder_z_tol_spin.value()),
            "landmark_alpha": float(self.landmark_alpha_spin.value()),
            "min_pose_confidence": float(self.min_confidence_spin.value()),
            "flip_camera_horizontal": bool(self.flip_horizontal_chk.isChecked()),
            "sensor1_index": int(self.sensor1_index_spin.value()),
            "sensor2_index": int(self.sensor2_index_spin.value()),
            "warmup_seconds": float(self.warmup_sec_spin.value()),
            "calibration_seconds": float(self.calibration_sec_spin.value()),
            "zero_deadband_deg": float(self.deadband_deg_spin.value()),
            "elbow_imu_offset_deg": float(self.elbow_offset_deg_spin.value()),
            "sensor_stale_seconds": float(self.sensor_stale_sec_spin.value()),
            "q_angle": float(self.q_angle_spin.value()),
            "q_velocity": float(self.q_velocity_spin.value()),
            "r_imu": float(self.r_imu_spin.value()),
            "r_vision": float(self.r_vision_spin.value()),
            "initial_p_angle": float(self.init_p_angle_spin.value()),
            "initial_p_velocity": float(self.init_p_velocity_spin.value()),
            "ukf_alpha": float(self.ukf_alpha_spin.value()),
            "ukf_beta": float(self.ukf_beta_spin.value()),
            "ukf_kappa": float(self.ukf_kappa_spin.value()),
            "record_seconds": float(self.record_sec_spin.value()),
            "recordings_dir": Path(self.recordings_dir_edit.text().strip()),
            "auto_analyze_on_stop": bool(self.auto_analyze_chk.isChecked()),
        }

    def apply_settings(self) -> bool:
        """Validate and apply settings to `self.controller`."""
        values = self.collect_form_values()
        try:
            # Validate on a candidate copy first so an invalid value never leaves partial state
            candidate = RehabConfig(**{**self.controller.config.__dict__, **values})
            candidate.validate()
            self.controller.update_settings(**values)
            self.status_msg_label.setText("Settings applied successfully.")
            self.status_msg_label.setStyleSheet(f"color: {PALETTE['status_ok']}; font-weight: bold;")
            if self.on_settings_applied is not None:
                self.on_settings_applied()
            return True
        except Exception as exc:
            self.status_msg_label.setText(f"Validation Error: {exc}")
            self.status_msg_label.setStyleSheet(f"color: {PALETTE['status_error']}; font-weight: bold;")
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            return False

    def restore_defaults(self) -> None:
        """Restore all form fields to the original defaults from `rehab_vision_delsys_ukf_Final.py`."""
        defaults = RehabConfig(show_opencv_window=False)
        self.load_from_config(defaults)
        self.apply_settings()
        self.status_msg_label.setText("Restored default settings.")
