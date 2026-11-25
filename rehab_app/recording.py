"""
Session recording and 4-sheet Excel workbook export.

If columns or values are missing in the generated Excel file, inspect this module.

Every experiment saves a uniquely named Excel workbook inside `recordings/`
with four sheets:
- `RawData`: timestamped raw sensor quaternions (W, X, Y, Z), mathematical Euler
  angles, raw vision angles, landmark visibilities, and calibration phase.
- `ProcessedData`: calibrated IMU angles, vision angles, fused UKF outputs,
  inter-source differences, and actual UKF Kalman gains.
- `Metrics`: pairwise inter-source consistency metrics (MAE, RMSE, Bias, Std, LoA, Pearson r).
- `Settings`: experiment configuration and calibration reference quaternions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import math
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from rehab_app.calibration import CalibrationManager, wrap_deg
from rehab_app.config import DEFAULT_RECORDINGS_DIR
from rehab_app.fusion import FusionStepResult
from rehab_app.sensors import SensorReading
from rehab_app.vision import VisionMeasurement

logger = logging.getLogger(__name__)

# Column order for the RawData Excel sheet
RAW_COLUMNS: Tuple[str, ...] = (
    "sample_index",
    "timestamp_monotonic_s",
    "elapsed_s",
    "iso_timestamp",
    "imu1_raw_qw",
    "imu1_raw_qx",
    "imu1_raw_qy",
    "imu1_raw_qz",
    "imu1_math_roll_deg",
    "imu1_math_pitch_deg_ignored",
    "imu1_math_yaw_deg",
    "imu1_calibration_phase",
    "imu2_raw_qw",
    "imu2_raw_qx",
    "imu2_raw_qy",
    "imu2_raw_qz",
    "imu2_math_roll_deg",
    "imu2_math_pitch_deg_ignored",
    "imu2_math_yaw_deg",
    "imu2_calibration_phase",
    "pose_detected",
    "shoulder_vision_raw_deg",
    "elbow_vision_raw_deg",
    "shoulder_z_diff",
    "relative_elbow_z",
    "r_hip_visibility",
    "r_shoulder_visibility",
    "l_shoulder_visibility",
    "r_elbow_visibility",
    "r_wrist_visibility",
    "sensor_status",
    "calibration_status",
)

# Column order for the ProcessedData Excel sheet
PROCESSED_COLUMNS: Tuple[str, ...] = (
    "sample_index",
    "timestamp_monotonic_s",
    "elapsed_s",
    "iso_timestamp",
    "imu1_pitch_deg",
    "imu1_yaw_deg",
    "imu1_elbow_deg",
    "imu2_pitch_trunk_deg",
    "shoulder_vision_deg",
    "elbow_vision_deg",
    "shoulder_ukf_deg",
    "shoulder_ukf_velocity_deg_s",
    "elbow_ukf_deg",
    "elbow_ukf_velocity_deg_s",
    "trunk_angle_deg",
    "shoulder_diff_vision_minus_imu_deg",
    "shoulder_abs_diff_vision_vs_imu_deg",
    "shoulder_diff_ukf_minus_imu_deg",
    "shoulder_abs_diff_ukf_vs_imu_deg",
    "shoulder_diff_ukf_minus_vision_deg",
    "shoulder_abs_diff_ukf_vs_vision_deg",
    "elbow_diff_vision_minus_imu_deg",
    "elbow_abs_diff_vision_vs_imu_deg",
    "elbow_diff_ukf_minus_imu_deg",
    "elbow_abs_diff_ukf_vs_imu_deg",
    "elbow_diff_ukf_minus_vision_deg",
    "elbow_abs_diff_ukf_vs_vision_deg",
    "shoulder_k_imu_angle",
    "shoulder_k_imu_velocity",
    "shoulder_k_vision_angle",
    "shoulder_k_vision_velocity",
    "elbow_k_imu_angle",
    "elbow_k_imu_velocity",
    "elbow_k_vision_angle",
    "elbow_k_vision_velocity",
    "posture_status",
)


def _signed_and_abs_diff(a: Optional[float], b: Optional[float]) -> Tuple[Optional[float], float]:
    """
    Compute (signed_difference, absolute_difference) in degrees between angles a and b.
    Returns (None, np.nan) if either measurement is missing.
    """
    if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
        return None, np.nan
    signed = wrap_deg(a - b)
    return signed, abs(signed)


def compute_consistency_metrics_table(processed_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute pairwise inter-source consistency metrics (Vision vs. IMU, UKF vs. IMU,
    UKF vs. Vision) and single-channel descriptive summaries from `ProcessedData`.

    Note: Without an external optical motion-capture reference, these metrics
    measure inter-sensor consistency and filter agreement, NOT absolute accuracy.
    """
    comparison_pairs = (
        ("Shoulder", "Vision vs IMU 1 Pitch (Inter-Sensor Consistency)", "shoulder_vision_deg", "imu1_pitch_deg"),
        ("Shoulder", "Shoulder UKF vs IMU 1 Pitch (Filter-to-IMU Agreement)", "shoulder_ukf_deg", "imu1_pitch_deg"),
        ("Shoulder", "Shoulder UKF vs Shoulder Vision (Filter-to-Vision Agreement)", "shoulder_ukf_deg", "shoulder_vision_deg"),
        ("Elbow", "Vision vs IMU 1 Yaw+90 (Inter-Sensor Consistency)", "elbow_vision_deg", "imu1_elbow_deg"),
        ("Elbow", "Elbow UKF vs IMU 1 Yaw+90 (Filter-to-IMU Agreement)", "elbow_ukf_deg", "imu1_elbow_deg"),
        ("Elbow", "Elbow UKF vs Elbow Vision (Filter-to-Vision Agreement)", "elbow_ukf_deg", "elbow_vision_deg"),
    )
    total_rows = len(processed_df)
    rows: List[Dict[str, Any]] = []

    for joint, label, col_a, col_b in comparison_pairs:
        if col_a not in processed_df.columns or col_b not in processed_df.columns:
            continue
        series_a = pd.to_numeric(processed_df[col_a], errors="coerce")
        series_b = pd.to_numeric(processed_df[col_b], errors="coerce")
        valid_mask = series_a.notna() & series_b.notna()
        n_valid = int(valid_mask.sum())
        missing_pct = round(100.0 * (total_rows - n_valid) / total_rows, 2) if total_rows > 0 else 100.0

        row: Dict[str, Any] = {
            "Joint": joint,
            "Comparison": label,
            "Metric_Interpretation": "Inter-measurement consistency (not ground-truth accuracy)",
            "Total_Samples": total_rows,
            "Valid_Paired_Samples": n_valid,
            "Missing_Paired_Pct": missing_pct,
        }
        if n_valid == 0:
            for key in (
                "MAE_deg", "RMSE_deg", "Bias_Signed_Mean_deg", "Std_Residual_deg",
                "Median_Abs_Diff_deg", "Max_Abs_Diff_deg", "LoA_95_Lower_deg", "LoA_95_Upper_deg", "Pearson_r",
            ):
                row[key] = np.nan
            rows.append(row)
            continue

        a_vals = series_a[valid_mask].to_numpy(dtype=float)
        b_vals = series_b[valid_mask].to_numpy(dtype=float)
        residuals = (a_vals - b_vals + 180.0) % 360.0 - 180.0
        abs_residuals = np.abs(residuals)
        bias = float(np.mean(residuals))
        std_res = float(np.std(residuals, ddof=1)) if n_valid > 1 else 0.0
        corr = (
            float(np.corrcoef(a_vals, b_vals)[0, 1])
            if (n_valid > 1 and np.std(a_vals) > 1e-9 and np.std(b_vals) > 1e-9)
            else np.nan
        )
        row.update({
            "MAE_deg": round(float(np.mean(abs_residuals)), 4),
            "RMSE_deg": round(float(np.sqrt(np.mean(residuals ** 2))), 4),
            "Bias_Signed_Mean_deg": round(bias, 4),
            "Std_Residual_deg": round(std_res, 4),
            "Median_Abs_Diff_deg": round(float(np.median(abs_residuals)), 4),
            "Max_Abs_Diff_deg": round(float(np.max(abs_residuals)), 4),
            "LoA_95_Lower_deg": round(bias - 1.96 * std_res, 4),
            "LoA_95_Upper_deg": round(bias + 1.96 * std_res, 4),
            "Pearson_r": round(corr, 4) if np.isfinite(corr) else np.nan,
        })
        rows.append(row)

    # Single-channel descriptive statistics
    signal_columns = (
        ("Shoulder", "Shoulder Vision (deg)", "shoulder_vision_deg"),
        ("Shoulder", "IMU 1 Pitch (deg)", "imu1_pitch_deg"),
        ("Shoulder", "Shoulder UKF (deg)", "shoulder_ukf_deg"),
        ("Shoulder", "Shoulder UKF K_angle (IMU)", "shoulder_k_imu_angle"),
        ("Shoulder", "Shoulder UKF K_angle (Vision)", "shoulder_k_vision_angle"),
        ("Elbow", "Elbow Vision (deg)", "elbow_vision_deg"),
        ("Elbow", "IMU 1 Yaw + 90 (deg)", "imu1_elbow_deg"),
        ("Elbow", "Elbow UKF (deg)", "elbow_ukf_deg"),
        ("Elbow", "Elbow UKF K_angle (IMU)", "elbow_k_imu_angle"),
        ("Elbow", "Elbow UKF K_angle (Vision)", "elbow_k_vision_angle"),
        ("Trunk", "IMU 2 Pitch / Trunk Angle (deg, unfused)", "trunk_angle_deg"),
    )
    for joint, label, col_name in signal_columns:
        if col_name not in processed_df.columns:
            continue
        series = pd.to_numeric(processed_df[col_name], errors="coerce").dropna()
        n_val = int(len(series))
        missing_pct = round(100.0 * (total_rows - n_val) / total_rows, 2) if total_rows > 0 else 100.0
        rows.append({
            "Joint": joint,
            "Comparison": f"Signal Summary: {label}",
            "Metric_Interpretation": "Single-channel descriptive statistics",
            "Total_Samples": total_rows,
            "Valid_Paired_Samples": n_val,
            "Missing_Paired_Pct": missing_pct,
            "MAE_deg": np.nan,
            "RMSE_deg": np.nan,
            "Bias_Signed_Mean_deg": round(float(series.mean()), 4) if n_val > 0 else np.nan,
            "Std_Residual_deg": round(float(series.std(ddof=1)), 4) if n_val > 1 else np.nan,
            "Median_Abs_Diff_deg": round(float(series.median()), 4) if n_val > 0 else np.nan,
            "Max_Abs_Diff_deg": round(float(series.max() - series.min()), 4) if n_val > 0 else np.nan,
            "LoA_95_Lower_deg": round(float(series.min()), 4) if n_val > 0 else np.nan,
            "LoA_95_Upper_deg": round(float(series.max()), 4) if n_val > 0 else np.nan,
            "Pearson_r": np.nan,
        })

    return pd.DataFrame(rows)


class SessionRecorder:
    """
    Buffers timestamped raw and processed rows during an experiment and exports
    them to a uniquely named 4-sheet Excel workbook in `recordings/`.
    """

    def __init__(self, config: Any = None, recordings_dir: Optional[Path | str] = None) -> None:
        self.config = config
        if recordings_dir is not None:
            self.recordings_dir = Path(recordings_dir).resolve()
        elif config is not None and hasattr(config, "recordings_dir"):
            self.recordings_dir = Path(config.recordings_dir).resolve()
        else:
            self.recordings_dir = DEFAULT_RECORDINGS_DIR

        self._lock = threading.Lock()
        self._raw_rows: List[Dict[str, Any]] = []
        self._proc_rows: List[Dict[str, Any]] = []
        self._start_monotonic: Optional[float] = None
        self._start_wall_iso: Optional[str] = None
        self._last_exported_path: Optional[Path] = None

    def reset(self) -> None:
        """Clear all recorded rows for a new session."""
        with self._lock:
            self._raw_rows.clear()
            self._proc_rows.clear()
            self._start_monotonic = None
            self._start_wall_iso = None
            self._last_exported_path = None

    @property
    def sample_count(self) -> int:
        with self._lock:
            return len(self._proc_rows)

    @property
    def last_exported_path(self) -> Optional[Path]:
        with self._lock:
            return self._last_exported_path

    def record_step(
        self,
        timestamp: float,
        sensor1: SensorReading,
        sensor2: SensorReading,
        vision: VisionMeasurement,
        fusion: FusionStepResult,
        sensor_status: str = "",
        calibration_status: str = "",
    ) -> Dict[str, Any]:
        """Append one timestamped step into the RawData and ProcessedData row buffers."""
        iso_now = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
        q1, q2 = sensor1.raw_quaternion, sensor2.raw_quaternion

        sh_vis_imu, sh_abs_vis_imu = _signed_and_abs_diff(fusion.shoulder_vision_deg, fusion.imu1_pitch_deg)
        sh_ukf_imu, sh_abs_ukf_imu = _signed_and_abs_diff(fusion.shoulder_ukf_deg, fusion.imu1_pitch_deg)
        sh_ukf_vis, sh_abs_ukf_vis = _signed_and_abs_diff(fusion.shoulder_ukf_deg, fusion.shoulder_vision_deg)
        el_vis_imu, el_abs_vis_imu = _signed_and_abs_diff(fusion.elbow_vision_deg, fusion.imu1_elbow_deg)
        el_ukf_imu, el_abs_ukf_imu = _signed_and_abs_diff(fusion.elbow_ukf_deg, fusion.imu1_elbow_deg)
        el_ukf_vis, el_abs_ukf_vis = _signed_and_abs_diff(fusion.elbow_ukf_deg, fusion.elbow_vision_deg)

        sk_imu, sk_vis = fusion.shoulder_k_imu, fusion.shoulder_k_vision
        ek_imu, ek_vis = fusion.elbow_k_imu, fusion.elbow_k_vision

        with self._lock:
            if self._start_monotonic is None:
                self._start_monotonic = float(timestamp)
                self._start_wall_iso = iso_now
            elapsed = float(timestamp) - self._start_monotonic
            idx = len(self._proc_rows)

            raw_row = {
                "sample_index": idx,
                "timestamp_monotonic_s": float(timestamp),
                "elapsed_s": elapsed,
                "iso_timestamp": iso_now,
                "imu1_raw_qw": q1[0] if q1 is not None else np.nan,
                "imu1_raw_qx": q1[1] if q1 is not None else np.nan,
                "imu1_raw_qy": q1[2] if q1 is not None else np.nan,
                "imu1_raw_qz": q1[3] if q1 is not None else np.nan,
                "imu1_math_roll_deg": sensor1.mathematical_roll_deg,
                "imu1_math_pitch_deg_ignored": sensor1.mathematical_pitch_deg,
                "imu1_math_yaw_deg": sensor1.mathematical_yaw_deg,
                "imu1_calibration_phase": sensor1.calibration_phase,
                "imu2_raw_qw": q2[0] if q2 is not None else np.nan,
                "imu2_raw_qx": q2[1] if q2 is not None else np.nan,
                "imu2_raw_qy": q2[2] if q2 is not None else np.nan,
                "imu2_raw_qz": q2[3] if q2 is not None else np.nan,
                "imu2_math_roll_deg": sensor2.mathematical_roll_deg,
                "imu2_math_pitch_deg_ignored": sensor2.mathematical_pitch_deg,
                "imu2_math_yaw_deg": sensor2.mathematical_yaw_deg,
                "imu2_calibration_phase": sensor2.calibration_phase,
                "pose_detected": vision.pose_detected,
                "shoulder_vision_raw_deg": vision.shoulder_angle_deg,
                "elbow_vision_raw_deg": vision.elbow_angle_deg,
                "shoulder_z_diff": vision.shoulder_z_diff,
                "relative_elbow_z": vision.relative_elbow_z,
                "r_hip_visibility": vision.r_hip_visibility,
                "r_shoulder_visibility": vision.r_shoulder_visibility,
                "l_shoulder_visibility": vision.l_shoulder_visibility,
                "r_elbow_visibility": vision.r_elbow_visibility,
                "r_wrist_visibility": vision.r_wrist_visibility,
                "sensor_status": sensor_status,
                "calibration_status": calibration_status,
            }
            proc_row = {
                "sample_index": idx,
                "timestamp_monotonic_s": float(timestamp),
                "elapsed_s": elapsed,
                "iso_timestamp": iso_now,
                "imu1_pitch_deg": fusion.imu1_pitch_deg,
                "imu1_yaw_deg": fusion.imu1_yaw_deg,
                "imu1_elbow_deg": fusion.imu1_elbow_deg,
                "imu2_pitch_trunk_deg": fusion.imu2_pitch_deg,
                "shoulder_vision_deg": fusion.shoulder_vision_deg,
                "elbow_vision_deg": fusion.elbow_vision_deg,
                "shoulder_ukf_deg": fusion.shoulder_ukf_deg,
                "shoulder_ukf_velocity_deg_s": fusion.shoulder_ukf_velocity_deg_s,
                "elbow_ukf_deg": fusion.elbow_ukf_deg,
                "elbow_ukf_velocity_deg_s": fusion.elbow_ukf_velocity_deg_s,
                "trunk_angle_deg": fusion.trunk_angle_deg,
                "shoulder_diff_vision_minus_imu_deg": sh_vis_imu,
                "shoulder_abs_diff_vision_vs_imu_deg": sh_abs_vis_imu,
                "shoulder_diff_ukf_minus_imu_deg": sh_ukf_imu,
                "shoulder_abs_diff_ukf_vs_imu_deg": sh_abs_ukf_imu,
                "shoulder_diff_ukf_minus_vision_deg": sh_ukf_vis,
                "shoulder_abs_diff_ukf_vs_vision_deg": sh_abs_ukf_vis,
                "elbow_diff_vision_minus_imu_deg": el_vis_imu,
                "elbow_abs_diff_vision_vs_imu_deg": el_abs_vis_imu,
                "elbow_diff_ukf_minus_imu_deg": el_ukf_imu,
                "elbow_abs_diff_ukf_vs_imu_deg": el_abs_ukf_imu,
                "elbow_diff_ukf_minus_vision_deg": el_ukf_vis,
                "elbow_abs_diff_ukf_vs_vision_deg": el_abs_ukf_vis,
                "shoulder_k_imu_angle": float(sk_imu[0]) if sk_imu is not None else None,
                "shoulder_k_imu_velocity": float(sk_imu[1]) if sk_imu is not None else None,
                "shoulder_k_vision_angle": float(sk_vis[0]) if sk_vis is not None else None,
                "shoulder_k_vision_velocity": float(sk_vis[1]) if sk_vis is not None else None,
                "elbow_k_imu_angle": float(ek_imu[0]) if ek_imu is not None else None,
                "elbow_k_imu_velocity": float(ek_imu[1]) if ek_imu is not None else None,
                "elbow_k_vision_angle": float(ek_vis[0]) if ek_vis is not None else None,
                "elbow_k_vision_velocity": float(ek_vis[1]) if ek_vis is not None else None,
                "posture_status": vision.posture_status,
            }
            self._raw_rows.append(raw_row)
            self._proc_rows.append(proc_row)
            return proc_row

    def generate_unique_workbook_path(self, prefix: str = "rehab_session") -> Path:
        """Create a unique `.xlsx` file path inside `recordings/` without overwriting existing files."""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        candidate = self.recordings_dir / f"{prefix}_{stamp}.xlsx"
        counter = 1
        while candidate.exists():
            candidate = self.recordings_dir / f"{prefix}_{stamp}_{counter}.xlsx"
            counter += 1
        return candidate

    def build_dataframes(
        self,
        calibration_manager: Optional[CalibrationManager] = None,
        sensor_metadata: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Convert buffered rows and settings into the four Excel sheet DataFrames."""
        with self._lock:
            raw_copy = list(self._raw_rows)
            proc_copy = list(self._proc_rows)
            start_iso = self._start_wall_iso

        raw_df = pd.DataFrame(raw_copy, columns=RAW_COLUMNS)
        proc_df = pd.DataFrame(proc_copy, columns=PROCESSED_COLUMNS)
        metrics_df = compute_consistency_metrics_table(proc_df)

        settings_items: List[Dict[str, Any]] = []
        if self.config is not None and hasattr(self.config, "to_settings_dict"):
            for k, v in self.config.to_settings_dict().items():
                settings_items.append({"Parameter": k, "Value": v})

        settings_items.extend([
            {"Parameter": "fusion_assignment_shoulder", "Value": "IMU 1 Pitch + Shoulder Vision -> Shoulder UKF"},
            {"Parameter": "fusion_assignment_elbow", "Value": "IMU 1 Yaw + 90.0 deg + Elbow Vision -> Elbow UKF (offset applied before UKF update)"},
            {"Parameter": "fusion_assignment_trunk", "Value": "IMU 2 Pitch -> Trunk angle (unfused)"},
            {"Parameter": "axis_mapping_note", "Value": "Reported IMU Pitch = mathematical Roll; Reported IMU Yaw = mathematical Yaw; mathematical Pitch discarded."},
            {"Parameter": "missing_data_policy", "Value": "Missing measurements are preserved as empty/NaN cells without silent interpolation."},
            {"Parameter": "session_start_iso", "Value": start_iso or ""},
            {"Parameter": "session_export_iso", "Value": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")},
            {"Parameter": "recorded_sample_count", "Value": len(proc_copy)},
        ])

        if calibration_manager is not None:
            refs = calibration_manager.get_reference_quaternions()
            counts = calibration_manager.get_sample_counts()
            settings_items.append({"Parameter": "calibration_final_status", "Value": calibration_manager.get_status_text()})
            for num, ref_q in refs.items():
                settings_items.append({"Parameter": f"sensor_{num}_reference_quaternion_wxyz", "Value": str(ref_q) if ref_q is not None else "Not calibrated"})
                settings_items.append({"Parameter": f"sensor_{num}_calibration_sample_count", "Value": counts.get(num, 0)})

        if sensor_metadata:
            for num, meta in sensor_metadata.items():
                for mk, mv in meta.items():
                    settings_items.append({"Parameter": f"sensor_{num}_{mk}", "Value": mv})

        return {
            "RawData": raw_df,
            "ProcessedData": proc_df,
            "Metrics": metrics_df,
            "Settings": pd.DataFrame(settings_items, columns=["Parameter", "Value"]),
        }

    def export_to_excel(
        self,
        calibration_manager: Optional[CalibrationManager] = None,
        sensor_metadata: Optional[Dict[int, Dict[str, Any]]] = None,
        custom_filename_prefix: str = "rehab_session",
    ) -> Path:
        """Write `RawData`, `ProcessedData`, `Metrics`, and `Settings` sheets to a new Excel file."""
        workbook_path = self.generate_unique_workbook_path(prefix=custom_filename_prefix)
        sheets = self.build_dataframes(
            calibration_manager=calibration_manager,
            sensor_metadata=sensor_metadata,
        )
        with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        with self._lock:
            self._last_exported_path = workbook_path
        logger.info("Exported session recording to Excel workbook: %s", workbook_path)
        return workbook_path
