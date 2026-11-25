"""
Central configuration and default constants for the rehabilitation application.

All default constants match rehab_vision_delsys_ukf_Final.py so that every
tunable parameter can be found and adjusted in one place.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

# ---------------- Project Paths ----------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_RECORDINGS_DIR: Path = PROJECT_ROOT / "recordings"
DEFAULT_MODEL_ASSET_PATH: Path = PROJECT_ROOT / "pose_landmarker_full.task"

# ---------------- Default Experiment & Sensor Settings ----------------
RECORD_SECONDS: float = 3000.0
SENSOR1_INDEX: int = 0
SENSOR2_INDEX: int = 1
WARMUP_SECONDS: float = 30.0
CALIBRATION_SECONDS: float = 5.0
ZERO_DEADBAND_DEG: float = 2.0
SENSOR_STALE_SECONDS: float = 1.0
ELBOW_IMU_OFFSET_DEG: float = 0.0
SHOULDER_IMU_DIRECTION_SIGN: float = -1.0
ELBOW_IMU_DIRECTION_SIGN: float = -1.0

# ---------------- Default Vision / MediaPipe Settings ----------------
CAMERA_INDEX: int = 0
VISIBILITY_MIN: float = 0.5
SHOULDER_Z_TOLERANCE: float = 0.08
LANDMARK_ALPHA: float = 0.3
MIN_POSE_CONFIDENCE: float = 0.5
WINDOW_TITLE: str = "Rehab Monitor - MediaPipe + Delsys UKF"

# ---------------- Default UKF Tuning Parameters ----------------
# State vector: [angle (deg), angular velocity (deg/s)].
# These are the initial tuning values from rehab_vision_delsys_ukf_Final.py.
Q_ANGLE: float = 1.0
Q_VELOCITY: float = 25.0
R_IMU: float = 9.0          # IMU measurement variance (deg^2)
R_VISION: float = 16.0      # Vision measurement variance (deg^2)
INITIAL_P_ANGLE: float = 100.0
INITIAL_P_VELOCITY: float = 400.0
UKF_ALPHA: float = 0.35
UKF_BETA: float = 2.0
UKF_KAPPA: float = 0.0


@dataclass
class RehabConfig:
    """
    Configuration container for an experiment session.
    Modify fields here or pass custom values when creating RehabConfig().
    """
    # Session timing
    record_seconds: float = RECORD_SECONDS
    warmup_seconds: float = WARMUP_SECONDS
    calibration_seconds: float = CALIBRATION_SECONDS

    # Delsys Trigno sensor settings
    sensor1_index: int = SENSOR1_INDEX
    sensor2_index: int = SENSOR2_INDEX
    sensor_stale_seconds: float = SENSOR_STALE_SECONDS
    zero_deadband_deg: float = ZERO_DEADBAND_DEG
    elbow_imu_offset_deg: float = ELBOW_IMU_OFFSET_DEG
    shoulder_imu_direction_sign: float = SHOULDER_IMU_DIRECTION_SIGN
    elbow_imu_direction_sign: float = ELBOW_IMU_DIRECTION_SIGN

    # Camera and MediaPipe settings
    camera_index: int = CAMERA_INDEX
    visibility_min: float = VISIBILITY_MIN
    shoulder_z_tolerance: float = SHOULDER_Z_TOLERANCE
    landmark_alpha: float = LANDMARK_ALPHA
    min_pose_confidence: float = MIN_POSE_CONFIDENCE
    flip_camera_horizontal: bool = True
    show_opencv_window: bool = False
    window_title: str = WINDOW_TITLE
    camera_loop_hz: float = 30.0

    # UKF parameters
    q_angle: float = Q_ANGLE
    q_velocity: float = Q_VELOCITY
    r_imu: float = R_IMU
    r_vision: float = R_VISION
    initial_p_angle: float = INITIAL_P_ANGLE
    initial_p_velocity: float = INITIAL_P_VELOCITY
    ukf_alpha: float = UKF_ALPHA
    ukf_beta: float = UKF_BETA
    ukf_kappa: float = UKF_KAPPA
    max_predict_dt: float = 0.25
    min_process_noise_dt: float = 1e-3

    # File paths
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    recordings_dir: Path = field(default_factory=lambda: DEFAULT_RECORDINGS_DIR)
    model_asset_path: Path = field(default_factory=lambda: DEFAULT_MODEL_ASSET_PATH)

    # Subsystem flags
    enable_sensors: bool = True
    enable_vision: bool = True
    auto_analyze_on_stop: bool = True

    def __post_init__(self) -> None:
        self.project_root = Path(self.project_root).resolve()
        self.recordings_dir = Path(self.recordings_dir).resolve()
        self.model_asset_path = Path(self.model_asset_path).resolve()
        self.validate()

    def validate(self) -> None:
        """Raise ValueError with a clear message if any setting is invalid."""
        if self.record_seconds <= 0:
            raise ValueError("record_seconds must be positive.")
        if self.warmup_seconds < 0:
            raise ValueError("warmup_seconds must be non-negative.")
        if self.calibration_seconds <= 0:
            raise ValueError("calibration_seconds must be positive.")
        if self.sensor1_index < 0 or self.sensor2_index < 0:
            raise ValueError("sensor1_index and sensor2_index must be non-negative.")
        if self.sensor1_index == self.sensor2_index:
            raise ValueError("sensor1_index and sensor2_index must be different.")
        if self.sensor_stale_seconds <= 0:
            raise ValueError("sensor_stale_seconds must be positive.")
        if self.zero_deadband_deg < 0:
            raise ValueError("zero_deadband_deg must be non-negative.")
        if self.shoulder_imu_direction_sign not in (-1.0, 1.0):
            raise ValueError("shoulder_imu_direction_sign must be +1.0 or -1.0.")
        if self.elbow_imu_direction_sign not in (-1.0, 1.0):
            raise ValueError("elbow_imu_direction_sign must be +1.0 or -1.0.")
        if not (0.0 <= self.visibility_min <= 1.0):
            raise ValueError("visibility_min must be between 0.0 and 1.0.")
        if not (0.0 < self.landmark_alpha <= 1.0):
            raise ValueError("landmark_alpha must be in (0.0, 1.0].")
        if min(
            self.q_angle,
            self.q_velocity,
            self.r_imu,
            self.r_vision,
            self.initial_p_angle,
            self.initial_p_velocity,
            self.ukf_alpha,
        ) <= 0:
            raise ValueError("UKF variances and ukf_alpha must be positive.")

    def to_settings_dict(self) -> Dict[str, Any]:
        """Return a flat dictionary of settings for saving to the Excel Settings sheet."""
        return {
            key: (str(value) if isinstance(value, Path) else value)
            for key, value in asdict(self).items()
        }
