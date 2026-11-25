"""
Quaternion math utilities and neutral sensor calibration.

If calibrated IMU angles look wrong or calibration fails to complete,
inspect this module.

Preserves the exact equations and procedure from rehab_vision_delsys_ukf_Final.py:
1. 30 s stationary warm-up (quaternions are received but not used for reference).
2. 5 s neutral calibration (incoming quaternions are hemisphere-aligned and averaged
   to form the neutral reference quaternion q_ref).
3. Relative orientation: q_rel = normalize(q_multiply(q_conjugate(q_ref), q_current)).
4. Euler conversion: (mathematical_roll, mathematical_pitch, mathematical_yaw).
5. Physical axis mapping (from modes.py):
   - Reported IMU Pitch = deadband(mathematical_roll)
   - Reported IMU Yaw   = deadband(mathematical_yaw)
   - Mathematical Pitch (physical roll) is ignored for joint fusion.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import threading
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from rehab_app.config import CALIBRATION_SECONDS, WARMUP_SECONDS, ZERO_DEADBAND_DEG

logger = logging.getLogger(__name__)

Quaternion = Tuple[float, float, float, float]
EulerAngles = Tuple[float, float, float]


# =====================================================================
# QUATERNION AND ANGLE MATH FUNCTIONS
# =====================================================================
def normalize(q: Sequence[float] | np.ndarray) -> Optional[Quaternion]:
    """
    Normalize a 4-element quaternion (w, x, y, z) to unit length.
    Returns None if the norm is near zero (< 1e-8).
    """
    n = math.sqrt(sum(float(v) ** 2 for v in q))
    if n < 1e-8:
        return None
    return tuple(float(v) / n for v in q)  # type: ignore[return-value]


def q_conjugate(q: Quaternion) -> Quaternion:
    """
    Return the conjugate (w, -x, -y, -z) of a unit quaternion.
    For unit quaternions, the conjugate is equal to the inverse rotation.
    """
    w, x, y, z = q
    return w, -x, -y, -z


def q_multiply(a: Quaternion, b: Quaternion) -> Quaternion:
    """
    Compute the Hamilton product (a * b) of two quaternions (w, x, y, z).
    Used to compute relative rotation: q_relative = q_conjugate(q_ref) * q_current.
    """
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def average_quaternions(samples: Sequence[Quaternion]) -> Optional[Quaternion]:
    """
    Average a list of quaternions collected during the 5-second neutral calibration window.
    Because q and -q represent the same 3D rotation, each sample is sign-aligned
    to the first sample (dot product >= 0) before summing and normalizing.
    """
    if not samples:
        return None
    ref = samples[0]
    total = np.zeros(4, dtype=float)
    for q in samples:
        if sum(a * b for a, b in zip(ref, q)) < 0:
            q = tuple(-v for v in q)  # type: ignore[assignment]
        total += np.asarray(q, dtype=float)
    return normalize(total)


def quaternion_to_euler(q: Quaternion) -> Optional[EulerAngles]:
    """
    Convert a quaternion (w, x, y, z) into standard ZYX Euler angles in degrees:
    Returns (mathematical_roll, mathematical_pitch, mathematical_yaw).
    """
    q_norm = normalize(q)
    if q_norm is None:
        return None
    w, x, y, z = q_norm
    sr, cr = 2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)
    sp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    sy, cy = 2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)
    return (
        math.degrees(math.atan2(sr, cr)),
        math.degrees(math.asin(sp)),
        math.degrees(math.atan2(sy, cy)),
    )


def wrap_deg(a: float) -> float:
    """Wrap any angle in degrees into the interval [-180.0, 180.0)."""
    return (float(a) + 180.0) % 360.0 - 180.0


def deadband(a: float, threshold_deg: float = ZERO_DEADBAND_DEG) -> float:
    """Set small angles within [-threshold_deg, +threshold_deg] to 0.0 degrees."""
    return 0.0 if abs(a) <= threshold_deg else float(a)


# =====================================================================
# CALIBRATION MANAGER
# =====================================================================
@dataclass
class CalibratedOrientation:
    """Holds both the raw quaternion and the resulting calibrated angles for one sensor sample."""
    sensor_number: int
    timestamp: float
    raw_quaternion: Quaternion
    is_calibrated: bool
    phase: str
    reference_quaternion: Optional[Quaternion] = None
    relative_quaternion: Optional[Quaternion] = None
    mathematical_roll_deg: Optional[float] = None
    mathematical_pitch_deg: Optional[float] = None
    mathematical_yaw_deg: Optional[float] = None
    imu_pitch_deg: Optional[float] = None
    imu_yaw_deg: Optional[float] = None


class CalibrationManager:
    """
    Manages the 30-second warm-up and 5-second neutral calibration for Sensor 1 and Sensor 2.
    """

    def __init__(
        self,
        warmup_seconds: float = WARMUP_SECONDS,
        calibration_seconds: float = CALIBRATION_SECONDS,
        zero_deadband_deg: float = ZERO_DEADBAND_DEG,
        sensor_numbers: Tuple[int, ...] = (1, 2),
    ) -> None:
        self.warmup_seconds = float(warmup_seconds)
        self.calibration_seconds = float(calibration_seconds)
        self.zero_deadband_deg = float(zero_deadband_deg)
        self.sensor_numbers = tuple(sensor_numbers)

        self._lock = threading.Lock()
        self._start_time: Optional[float] = None
        self._samples: Dict[int, List[Quaternion]] = {n: [] for n in self.sensor_numbers}
        self._refs: Dict[int, Optional[Quaternion]] = {n: None for n in self.sensor_numbers}
        self._calibrated: Dict[int, bool] = {n: False for n in self.sensor_numbers}
        self._status_text: str = "Waiting"

        # Dynamic Vision reference angles captured during the same neutral calibration window
        self._vision_samples: Dict[str, List[float]] = {"shoulder": [], "elbow": []}
        self._vision_refs: Dict[str, Optional[float]] = {"shoulder": None, "elbow": None}
        self._vision_finalized: Dict[str, bool] = {"shoulder": False, "elbow": False}

    def start(self, start_timestamp: float) -> None:
        """Start or restart the warm-up and calibration timer at start_timestamp."""
        self.reset(new_start_timestamp=start_timestamp)

    def reset(self, new_start_timestamp: Optional[float] = None) -> None:
        """Clear saved reference quaternions, Vision references, and calibration samples."""
        with self._lock:
            self._start_time = float(new_start_timestamp) if new_start_timestamp is not None else None
            for n in list(self._samples):
                self._samples[n].clear()
                self._refs[n] = None
                self._calibrated[n] = False
            for joint in ("shoulder", "elbow"):
                self._vision_samples[joint].clear()
                self._vision_refs[joint] = None
                self._vision_finalized[joint] = False
            self._status_text = (
                f"Warm-up {self.warmup_seconds:.0f} s" if self._start_time is not None else "Waiting"
            )

    @property
    def is_fully_calibrated(self) -> bool:
        with self._lock:
            return all(self._calibrated.values())

    def get_status_text(self) -> str:
        with self._lock:
            return self._status_text

    def get_reference_quaternions(self) -> Dict[int, Optional[Quaternion]]:
        with self._lock:
            return dict(self._refs)

    def get_sample_counts(self) -> Dict[int, int]:
        with self._lock:
            return {n: len(s) for n, s in self._samples.items()}

    def get_vision_references(self) -> Dict[str, Optional[float]]:
        """Return averaged Vision reference angles {'shoulder': float|None, 'elbow': float|None}."""
        with self._lock:
            return dict(self._vision_refs)

    def get_vision_sample_counts(self) -> Dict[str, int]:
        """Return number of valid Vision samples collected for each joint during calibration."""
        with self._lock:
            return {joint: len(samples) for joint, samples in self._vision_samples.items()}

    def record_vision_sample(
        self,
        shoulder_angle_deg: Optional[float],
        elbow_angle_deg: Optional[float],
        timestamp: float,
    ) -> Dict[str, Optional[float]]:
        """
        Capture and average Shoulder and Elbow Vision angles during the calibration window.
        - During warm-up (elapsed < warmup_seconds): samples are ignored.
        - During calibration (warmup_seconds <= elapsed < warmup_seconds + calibration_seconds):
          valid finite angles are appended independently for shoulder and elbow.
        - Once elapsed >= warmup_seconds + calibration_seconds: each joint's reference is
          finalized as the arithmetic mean of its valid samples (or None if none were valid).
        """
        with self._lock:
            if self._start_time is None:
                return dict(self._vision_refs)

            elapsed = float(timestamp) - self._start_time
            total_cal_time = self.warmup_seconds + self.calibration_seconds

            if elapsed < self.warmup_seconds:
                return dict(self._vision_refs)

            joint_values = {
                "shoulder": shoulder_angle_deg,
                "elbow": elbow_angle_deg,
            }
            for joint, val in joint_values.items():
                if self._vision_finalized[joint]:
                    continue
                if val is not None and math.isfinite(float(val)):
                    self._vision_samples[joint].append(float(val))
                if elapsed >= total_cal_time:
                    self._finalize_vision_joint_locked(joint)

            return dict(self._vision_refs)

    def _finalize_vision_joint_locked(self, joint: str) -> None:
        """Finalize the Vision reference angle for `joint` at the end of calibration."""
        if self._vision_finalized[joint]:
            return
        samples = self._vision_samples[joint]
        if samples:
            ref_deg = float(np.mean(samples))
            self._vision_refs[joint] = ref_deg
            logger.info(
                "Vision %s calibration reference finalized: %.2f deg (%d valid samples).",
                joint,
                ref_deg,
                len(samples),
            )
        else:
            self._vision_refs[joint] = None
            logger.warning(
                "Vision %s calibration finished with 0 valid samples; "
                "dynamic IMU offset alignment for %s is unavailable.",
                joint,
                joint,
            )
        self._vision_finalized[joint] = True

    def process_quaternion(
        self,
        sensor_number: int,
        raw_q: Sequence[float],
        timestamp: float,
    ) -> Optional[CalibratedOrientation]:
        """
        Process one incoming raw quaternion (w, x, y, z) from `sensor_number`:
        - During warm-up (elapsed < warmup_seconds): returns phase='warmup'.
        - During calibration window (warmup <= elapsed < warmup + calibration):
          collects neutral samples and computes reference quaternion when window ends.
        - After calibration: computes relative quaternion, converts to Euler angles,
          and applies physical axis mapping and deadband.
        """
        q = normalize(raw_q)
        if q is None:
            return None

        with self._lock:
            if self._start_time is None:
                self._start_time = float(timestamp)
            if sensor_number not in self._samples:
                self._samples[sensor_number] = []
                self._refs[sensor_number] = None
                self._calibrated[sensor_number] = False

            elapsed = float(timestamp) - self._start_time
            total_cal_time = self.warmup_seconds + self.calibration_seconds

            # Step 1: Stationary warm-up phase
            if elapsed < self.warmup_seconds:
                self._update_status_locked(elapsed, total_cal_time)
                return CalibratedOrientation(
                    sensor_number=sensor_number,
                    timestamp=float(timestamp),
                    raw_quaternion=q,
                    is_calibrated=False,
                    phase="warmup",
                )

            # Step 2: Neutral calibration sample collection phase (matches modes.py)
            if not self._calibrated[sensor_number]:
                self._samples[sensor_number].append(q)
                calibration_elapsed = elapsed - self.warmup_seconds
                if calibration_elapsed >= self.calibration_seconds:
                    ref_q = average_quaternions(self._samples[sensor_number])
                    if ref_q is None:
                        raise RuntimeError(f"Sensor {sensor_number}: calibration failed.")
                    self._refs[sensor_number] = ref_q
                    self._calibrated[sensor_number] = True
                    logger.info(
                        "Sensor %d: calibration complete (%d samples).",
                        sensor_number,
                        len(self._samples[sensor_number]),
                    )
                if not self._calibrated[sensor_number]:
                    self._update_status_locked(elapsed, total_cal_time)
                    return CalibratedOrientation(
                        sensor_number=sensor_number,
                        timestamp=float(timestamp),
                        raw_quaternion=q,
                        is_calibrated=False,
                        phase="calibrating",
                        reference_quaternion=None,
                    )

            # Step 3: Active calibrated measurement phase (falls through immediately
            # once calibration completes, matching `if calibration_complete:` in modes.py)
            ref = self._refs[sensor_number]
            assert ref is not None
            relative = normalize(q_multiply(q_conjugate(ref), q))
            if relative is None:
                return None
            euler = quaternion_to_euler(relative)
            if euler is None:
                return None

            mathematical_roll, mathematical_pitch, mathematical_yaw = euler

            # Preserve physical sensor axis mapping from modes.py:
            # - Reported IMU Pitch is mathematical Roll.
            # - Reported IMU Yaw is mathematical Yaw.
            # - Mathematical Pitch (physical roll) is ignored for joint fusion.
            imu_pitch = deadband(mathematical_roll, self.zero_deadband_deg)
            imu_yaw = deadband(mathematical_yaw, self.zero_deadband_deg)
            self._update_status_locked(elapsed, total_cal_time)

            return CalibratedOrientation(
                sensor_number=sensor_number,
                timestamp=float(timestamp),
                raw_quaternion=q,
                is_calibrated=True,
                phase="active",
                reference_quaternion=ref,
                relative_quaternion=relative,
                mathematical_roll_deg=mathematical_roll,
                mathematical_pitch_deg=mathematical_pitch,
                mathematical_yaw_deg=mathematical_yaw,
                imu_pitch_deg=imu_pitch,
                imu_yaw_deg=imu_yaw,
            )

    def _update_status_locked(self, elapsed: float, total_cal_time: float) -> None:
        if all(self._calibrated.values()):
            self._status_text = "Both sensors calibrated"
        else:
            self._status_text = f"Warm-up/calibration {elapsed:.0f}/{total_cal_time:.0f} s"
