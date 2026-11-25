"""
Unscented Kalman Filter (UKF) and joint angle fusion pipelines.

If fused Shoulder or Elbow angles behave unexpectedly, inspect this module.

Preserves the exact mathematical equations and fusion assignments from
rehab_vision_delsys_ukf_Final.py:
- UKF state vector: x = [angle (deg), angular_velocity (deg/s)]
- Shoulder UKF: fuses IMU 1 Pitch + Shoulder Vision
- Elbow UKF: fuses (IMU 1 Yaw + 90.0 deg) + Elbow Vision
  (the +90.0 deg offset is added to IMU 1 Yaw before calling the UKF update)
- Trunk angle: IMU 2 Pitch directly, without UKF fusion
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from typing import Dict, Optional, Tuple

import numpy as np

from rehab_app.calibration import wrap_deg
from rehab_app.config import (
    ELBOW_IMU_DIRECTION_SIGN,
    ELBOW_IMU_OFFSET_DEG,
    INITIAL_P_ANGLE,
    INITIAL_P_VELOCITY,
    Q_ANGLE,
    Q_VELOCITY,
    R_IMU,
    R_VISION,
    SHOULDER_IMU_DIRECTION_SIGN,
    UKF_ALPHA,
    UKF_BETA,
    UKF_KAPPA,
)

logger = logging.getLogger(__name__)


def align_imu_angle(
    imu_relative: Optional[float],
    vision_reference: Optional[float],
    direction_sign: float = 1.0,
) -> Optional[float]:
    """
    Align a neutral-calibrated relative IMU angle to the Vision reference frame:
        IMU_corrected = Vision_reference + direction_sign * IMU_relative

    Returns None if either `imu_relative` or `vision_reference` is missing or non-finite,
    so an invalid reference is never silently applied.
    """
    if imu_relative is None or vision_reference is None:
        return None
    if not (math.isfinite(imu_relative) and math.isfinite(vision_reference)):
        return None
    return float(vision_reference + float(direction_sign) * float(imu_relative))


def angle_residual(a: float, b: float) -> float:
    """
    Compute the shortest-arc signed difference (a - b) in degrees within [-180, 180).
    Used instead of simple subtraction so angles near +/-180 deg do not jump by 360 deg.
    """
    return wrap_deg(a - b)


class AngleUKF:
    """
    Scaled sigma-point Unscented Kalman Filter for a single joint angle.
    - State x: [angle (deg), angular_velocity (deg/s)]
    - Measurement z: scalar angle (deg) from either "imu" (R_IMU = 9.0) or "vision" (R_VISION = 16.0).
    """

    def __init__(
        self,
        q_angle: float = Q_ANGLE,
        q_velocity: float = Q_VELOCITY,
        r_imu: float = R_IMU,
        r_vision: float = R_VISION,
        initial_p_angle: float = INITIAL_P_ANGLE,
        initial_p_velocity: float = INITIAL_P_VELOCITY,
        ukf_alpha: float = UKF_ALPHA,
        ukf_beta: float = UKF_BETA,
        ukf_kappa: float = UKF_KAPPA,
        max_predict_dt: float = 0.25,
        min_process_noise_dt: float = 1e-3,
    ) -> None:
        self.q_angle = float(q_angle)
        self.q_velocity = float(q_velocity)
        self.r_imu = float(r_imu)
        self.r_vision = float(r_vision)
        self.initial_p_angle = float(initial_p_angle)
        self.initial_p_velocity = float(initial_p_velocity)
        self.ukf_alpha = float(ukf_alpha)
        self.ukf_beta = float(ukf_beta)
        self.ukf_kappa = float(ukf_kappa)
        self.max_predict_dt = float(max_predict_dt)
        self.min_process_noise_dt = float(min_process_noise_dt)

        self.x = np.array([0.0, 0.0], dtype=float)
        self.P = np.diag([self.initial_p_angle, self.initial_p_velocity]).astype(float)
        self.Q = np.diag([self.q_angle, self.q_velocity]).astype(float)
        self.initialized: bool = False
        self.last_time: Optional[float] = None
        self.last_source_time: Dict[str, Optional[float]] = {"imu": None, "vision": None}

        # Store the most recent Kalman gain vector K = [K_angle, K_velocity] for Excel logging
        self.last_kalman_gain: Optional[np.ndarray] = None
        self.last_kalman_gain_by_source: Dict[str, Optional[np.ndarray]] = {
            "imu": None,
            "vision": None,
        }

    def reset(self) -> None:
        """Reset filter state, covariance, and timestamps to initial values."""
        self.x = np.array([0.0, 0.0], dtype=float)
        self.P = np.diag([self.initial_p_angle, self.initial_p_velocity]).astype(float)
        self.initialized = False
        self.last_time = None
        self.last_source_time = {"imu": None, "vision": None}
        self.last_kalman_gain = None
        self.last_kalman_gain_by_source = {"imu": None, "vision": None}

    def weights(self) -> Tuple[float, np.ndarray, np.ndarray]:
        """
        Compute scaled unscented transform scaling parameter `c` and
        mean/covariance weights (`wm`, `wc`) for n=2 state dimensions (5 sigma points).
        """
        n = 2
        lam = self.ukf_alpha ** 2 * (n + self.ukf_kappa) - n
        c = n + lam
        wm = np.full(2 * n + 1, 1.0 / (2.0 * c))
        wc = wm.copy()
        wm[0] = lam / c
        wc[0] = lam / c + 1.0 - self.ukf_alpha ** 2 + self.ukf_beta
        return c, wm, wc

    @staticmethod
    def circular_mean(sigmas: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """
        Compute the weighted mean of sigma points using circular (atan2 of sin/cos)
        averaging for the angle state and linear averaging for angular velocity.
        """
        radians = np.radians(sigmas[:, 0])
        angle = math.degrees(
            math.atan2(
                float(np.sum(weights * np.sin(radians))),
                float(np.sum(weights * np.cos(radians))),
            )
        )
        velocity = float(np.sum(weights * sigmas[:, 1]))
        return np.array([angle, velocity], dtype=float)

    def sigma_points(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Generate the 2n+1 = 5 sigma points around current state `self.x`
        using the Cholesky square-root of `c * self.P`.
        """
        c, wm, wc = self.weights()
        try:
            root = np.linalg.cholesky(c * self.P)
        except np.linalg.LinAlgError:
            root = np.linalg.cholesky(c * (self.P + np.eye(2) * 1e-8))
        sigmas = [self.x.copy()]
        for i in range(2):
            sigmas.extend([self.x + root[:, i], self.x - root[:, i]])
        return np.asarray(sigmas, dtype=float), wm, wc

    def predict(self, timestamp: float) -> None:
        """
        UKF Time-Update (Prediction) Step:
        Propagate sigma points forward by dt seconds using constant-velocity kinematics:
            angle_next = wrap_deg(angle + velocity * dt)
            velocity_next = velocity
        """
        timestamp = float(timestamp)
        if self.last_time is None:
            self.last_time = timestamp
            return
        dt = timestamp - self.last_time
        if dt <= 0:
            return
        dt = min(dt, self.max_predict_dt)
        sigmas, wm, wc = self.sigma_points()
        propagated = np.asarray(
            [[wrap_deg(s[0] + s[1] * dt), s[1]] for s in sigmas],
            dtype=float,
        )
        x_pred = self.circular_mean(propagated, wm)
        p_pred = np.zeros((2, 2), dtype=float)
        for i, s in enumerate(propagated):
            d = np.array([angle_residual(s[0], x_pred[0]), s[1] - x_pred[1]], dtype=float)
            p_pred += wc[i] * np.outer(d, d)
        self.x = x_pred
        self.x[0] = wrap_deg(self.x[0])
        self.P = p_pred + self.Q * max(dt, self.min_process_noise_dt)
        self.P = 0.5 * (self.P + self.P.T)
        self.last_time = timestamp

    def update(self, measurement: Optional[float], source: str, timestamp: float) -> Optional[float]:
        """
        UKF Measurement-Update (Correction) Step:
        1. Predict state up to `timestamp`.
        2. On first valid measurement, initialize state x = [z, 0.0].
        3. Compute predicted measurement mean `z_mean`, innovation variance `S`,
           and state-measurement cross-covariance `Pxz`.
        4. Compute Kalman gain `K = Pxz / S` and update state `x` and covariance `P`.
        """
        if measurement is None or not np.isfinite(measurement):
            return float(self.x[0]) if self.initialized else None
        timestamp = float(timestamp)
        previous = self.last_source_time[source]
        if previous is not None and timestamp <= previous:
            return float(self.x[0]) if self.initialized else None
        if self.last_time is None:
            self.last_time = timestamp
        elif timestamp < self.last_time - 1e-6:
            # Out-of-order delayed samples are ignored without filter rewind
            return float(self.x[0]) if self.initialized else None
        else:
            self.predict(timestamp)

        z = wrap_deg(measurement)
        R = self.r_imu if source == "imu" else self.r_vision
        if not self.initialized:
            self.x[:] = [z, 0.0]
            self.P[0, 0] = min(self.P[0, 0], R)
            self.initialized = True
            self.last_source_time[source] = timestamp
            return float(self.x[0])

        sigmas, wm, wc = self.sigma_points()
        z_values = sigmas[:, 0]
        z_mean = math.degrees(
            math.atan2(
                float(np.sum(wm * np.sin(np.radians(z_values)))),
                float(np.sum(wm * np.cos(np.radians(z_values)))),
            )
        )
        S = R
        Pxz = np.zeros(2, dtype=float)
        for i, s in enumerate(sigmas):
            dz = angle_residual(z_values[i], z_mean)
            dx = np.array([angle_residual(s[0], self.x[0]), s[1] - self.x[1]], dtype=float)
            S += wc[i] * dz * dz
            Pxz += wc[i] * dx * dz
        if S <= 1e-12:
            return float(self.x[0])
        K = Pxz / S
        self.last_kalman_gain = K.copy()
        self.last_kalman_gain_by_source[source] = K.copy()

        self.x += K * angle_residual(z, z_mean)
        self.x[0] = wrap_deg(self.x[0])
        self.P -= np.outer(K, K) * S
        self.P = 0.5 * (self.P + self.P.T)
        self.last_source_time[source] = timestamp
        return float(self.x[0])


# =====================================================================
# HELPER FUNCTIONS (Matching rehab_vision_delsys_ukf_Final.py)
# =====================================================================
def initialize_shoulder_ukf() -> AngleUKF:
    """Create a fresh AngleUKF instance for the Shoulder joint."""
    return AngleUKF()


def initialize_elbow_ukf() -> AngleUKF:
    """Create a fresh AngleUKF instance for the Elbow joint."""
    return AngleUKF()


def predict_ukf(ukf: AngleUKF, timestamp: float) -> None:
    """Run the prediction step on `ukf` up to `timestamp`."""
    ukf.predict(timestamp)


def update_ukf_with_imu(ukf: AngleUKF, imu_angle: Optional[float], timestamp: float) -> Optional[float]:
    """Update `ukf` with an IMU angle measurement (variance R_IMU = 9.0 deg^2)."""
    return ukf.update(imu_angle, "imu", timestamp)


def update_ukf_with_vision(ukf: AngleUKF, vision_angle: Optional[float], timestamp: float) -> Optional[float]:
    """Update `ukf` with a MediaPipe vision angle measurement (variance R_VISION = 16.0 deg^2)."""
    return ukf.update(vision_angle, "vision", timestamp)


def fuse_shoulder_angle(
    ukf: AngleUKF,
    imu_pitch: Optional[float],
    vision_shoulder: Optional[float],
    timestamp: float,
) -> Optional[float]:
    """
    Shoulder fusion rule:
    IMU 1 Pitch + Shoulder Vision -> Shoulder UKF.
    """
    if imu_pitch is not None:
        update_ukf_with_imu(ukf, imu_pitch, timestamp)
    if vision_shoulder is not None:
        update_ukf_with_vision(ukf, vision_shoulder, timestamp)
    return float(ukf.x[0]) if ukf.initialized else None


def fuse_elbow_angle(
    ukf: AngleUKF,
    imu_yaw: Optional[float],
    vision_elbow: Optional[float],
    timestamp: float,
    elbow_offset_deg: float = ELBOW_IMU_OFFSET_DEG,
) -> Optional[float]:
    """
    Elbow fusion rule:
    (IMU 1 Yaw + 90.0 degrees) + Elbow Vision -> Elbow UKF.
    The +90.0 deg offset converts IMU 1 Yaw to the elbow-angle convention before UKF update.
    """
    if imu_yaw is not None:
        imu_elbow_angle = imu_yaw + elbow_offset_deg
        update_ukf_with_imu(ukf, imu_elbow_angle, timestamp)
    if vision_elbow is not None:
        update_ukf_with_vision(ukf, vision_elbow, timestamp)
    return float(ukf.x[0]) if ukf.initialized else None


# =====================================================================
# JOINT FUSION PIPELINE
# =====================================================================
@dataclass
class FusionStepResult:
    """Outputs of a single fusion step across Shoulder, Elbow, and Trunk."""
    timestamp: float
    imu1_pitch_deg: Optional[float]
    imu1_yaw_deg: Optional[float]
    imu1_shoulder_corrected_deg: Optional[float]
    imu1_elbow_deg: Optional[float]
    imu2_pitch_deg: Optional[float]
    shoulder_vision_deg: Optional[float]
    elbow_vision_deg: Optional[float]
    shoulder_ukf_deg: Optional[float]
    shoulder_ukf_velocity_deg_s: Optional[float]
    elbow_ukf_deg: Optional[float]
    elbow_ukf_velocity_deg_s: Optional[float]
    trunk_angle_deg: Optional[float]
    shoulder_vision_ref_deg: Optional[float] = None
    elbow_vision_ref_deg: Optional[float] = None
    shoulder_direction_sign: float = SHOULDER_IMU_DIRECTION_SIGN
    elbow_direction_sign: float = ELBOW_IMU_DIRECTION_SIGN
    shoulder_dynamic_offset_deg: Optional[float] = None
    elbow_dynamic_offset_deg: Optional[float] = None
    shoulder_k_imu: Optional[np.ndarray] = None
    shoulder_k_vision: Optional[np.ndarray] = None
    elbow_k_imu: Optional[np.ndarray] = None
    elbow_k_vision: Optional[np.ndarray] = None


class JointFusionPipeline:
    """
    Coordinates the two UKF filters (Shoulder and Elbow) and the unfused Trunk angle.
    Applies dynamic Vision-reference IMU offset alignment before each UKF update:
        IMU_corrected = Vision_reference + direction_sign * IMU_relative
    """

    def __init__(
        self,
        shoulder_ukf: Optional[AngleUKF] = None,
        elbow_ukf: Optional[AngleUKF] = None,
        elbow_imu_offset_deg: float = ELBOW_IMU_OFFSET_DEG,
        shoulder_direction_sign: float = SHOULDER_IMU_DIRECTION_SIGN,
        elbow_direction_sign: float = ELBOW_IMU_DIRECTION_SIGN,
    ) -> None:
        self.shoulder_ukf = shoulder_ukf if shoulder_ukf is not None else initialize_shoulder_ukf()
        self.elbow_ukf = elbow_ukf if elbow_ukf is not None else initialize_elbow_ukf()
        self.elbow_imu_offset_deg = float(elbow_imu_offset_deg)
        self.shoulder_direction_sign = float(shoulder_direction_sign)
        self.elbow_direction_sign = float(elbow_direction_sign)

    def reset(self) -> None:
        """Reset both Shoulder and Elbow UKFs."""
        self.shoulder_ukf.reset()
        self.elbow_ukf.reset()

    def step(
        self,
        timestamp: float,
        imu1_pitch: Optional[float],
        imu1_yaw: Optional[float],
        imu2_pitch: Optional[float],
        shoulder_vision: Optional[float],
        elbow_vision: Optional[float],
        shoulder_vision_ref: Optional[float] = None,
        elbow_vision_ref: Optional[float] = None,
    ) -> FusionStepResult:
        """
        Run one fusion step at `timestamp`:
        1. Align IMU 1 Pitch using Shoulder Vision reference and direction sign -> Shoulder UKF
        2. Align IMU 1 Yaw using Elbow Vision reference and direction sign -> Elbow UKF
           (Replaces any hardcoded static 90 deg offset so it is never applied twice.)
        3. IMU 2 Pitch -> Trunk angle (without fusion)
        """
        self.shoulder_ukf.last_kalman_gain_by_source["imu"] = None
        self.shoulder_ukf.last_kalman_gain_by_source["vision"] = None
        self.elbow_ukf.last_kalman_gain_by_source["imu"] = None
        self.elbow_ukf.last_kalman_gain_by_source["vision"] = None

        # Dynamic offset alignment for Shoulder:
        # IMU_shoulder_corrected = shoulder_vision_ref + shoulder_direction_sign * imu1_pitch
        shoulder_imu_corrected = align_imu_angle(
            imu1_pitch, shoulder_vision_ref, self.shoulder_direction_sign
        )
        shoulder_dynamic_offset = (
            float(shoulder_vision_ref)
            if (shoulder_vision_ref is not None and math.isfinite(shoulder_vision_ref))
            else None
        )

        # Dynamic offset alignment for Elbow:
        # IMU_elbow_corrected = elbow_vision_ref + elbow_direction_sign * imu1_yaw
        # Note: elbow_vision_ref already captures the true calibration pose angle,
        # so no static +90 deg offset is added on top.
        elbow_imu_corrected = align_imu_angle(
            imu1_yaw, elbow_vision_ref, self.elbow_direction_sign
        )
        elbow_dynamic_offset = (
            float(elbow_vision_ref)
            if (elbow_vision_ref is not None and math.isfinite(elbow_vision_ref))
            else None
        )

        shoulder_fused = fuse_shoulder_angle(
            self.shoulder_ukf, shoulder_imu_corrected, shoulder_vision, timestamp
        )
        elbow_fused = fuse_elbow_angle(
            self.elbow_ukf,
            elbow_imu_corrected,
            elbow_vision,
            timestamp,
            elbow_offset_deg=0.0,
        )
        trunk_angle = float(imu2_pitch) if imu2_pitch is not None else None

        if logger.isEnabledFor(logging.DEBUG):
            sh_diff = (
                angle_residual(shoulder_vision, shoulder_imu_corrected)
                if (shoulder_vision is not None and shoulder_imu_corrected is not None)
                else None
            )
            el_diff = (
                angle_residual(elbow_vision, elbow_imu_corrected)
                if (elbow_vision is not None and elbow_imu_corrected is not None)
                else None
            )
            logger.debug(
                "Alignment [Shoulder] vis=%s ref=%s imu_rel=%s sign=%+.0f offset=%s imu_corr=%s diff=%s | "
                "[Elbow] vis=%s ref=%s imu_rel=%s sign=%+.0f offset=%s imu_corr=%s diff=%s",
                shoulder_vision, shoulder_vision_ref, imu1_pitch, self.shoulder_direction_sign,
                shoulder_dynamic_offset, shoulder_imu_corrected, sh_diff,
                elbow_vision, elbow_vision_ref, imu1_yaw, self.elbow_direction_sign,
                elbow_dynamic_offset, elbow_imu_corrected, el_diff,
            )

        return FusionStepResult(
            timestamp=float(timestamp),
            imu1_pitch_deg=imu1_pitch,
            imu1_yaw_deg=imu1_yaw,
            imu1_shoulder_corrected_deg=shoulder_imu_corrected,
            imu1_elbow_deg=elbow_imu_corrected,
            imu2_pitch_deg=imu2_pitch,
            shoulder_vision_deg=shoulder_vision,
            elbow_vision_deg=elbow_vision,
            shoulder_ukf_deg=shoulder_fused,
            shoulder_ukf_velocity_deg_s=(
                float(self.shoulder_ukf.x[1]) if self.shoulder_ukf.initialized else None
            ),
            elbow_ukf_deg=elbow_fused,
            elbow_ukf_velocity_deg_s=(
                float(self.elbow_ukf.x[1]) if self.elbow_ukf.initialized else None
            ),
            trunk_angle_deg=trunk_angle,
            shoulder_vision_ref_deg=shoulder_vision_ref,
            elbow_vision_ref_deg=elbow_vision_ref,
            shoulder_direction_sign=self.shoulder_direction_sign,
            elbow_direction_sign=self.elbow_direction_sign,
            shoulder_dynamic_offset_deg=shoulder_dynamic_offset,
            elbow_dynamic_offset_deg=elbow_dynamic_offset,
            shoulder_k_imu=self.shoulder_ukf.last_kalman_gain_by_source["imu"],
            shoulder_k_vision=self.shoulder_ukf.last_kalman_gain_by_source["vision"],
            elbow_k_imu=self.elbow_ukf.last_kalman_gain_by_source["imu"],
            elbow_k_vision=self.elbow_ukf.last_kalman_gain_by_source["vision"],
        )
