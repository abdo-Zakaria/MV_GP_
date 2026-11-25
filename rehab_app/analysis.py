"""
Post-experiment data analysis and Matplotlib plot generation.

If plots or summary metrics look wrong, inspect this module.

Loads recorded experiment data directly from the saved Excel workbook inside
`recordings/` and generates seven diagnostic plots:
1. `shoulder_angles_comparison.png`: Shoulder Vision vs. IMU 1 Pitch vs. Shoulder UKF.
2. `elbow_angles_comparison.png`: Elbow Vision vs. (IMU 1 Yaw + 90°) vs. Elbow UKF.
3. `trunk_angle.png`: Trunk angle (IMU 2 Pitch, unfused) over time.
4. `shoulder_differences.png`: Signed and absolute Shoulder differences over time.
5. `elbow_differences.png`: Signed and absolute Elbow differences over time.
6. `ukf_kalman_gains.png`: Actual UKF Kalman gain evolution over time.
7. `ukf_consistency_distributions.png`: Residual histograms comparing UKF, IMU, and Vision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rehab_app.recording import compute_consistency_metrics_table

logger = logging.getLogger(__name__)


def _extract_numeric_column(df: pd.DataFrame, col: str) -> Optional[np.ndarray]:
    """Return column `col` as a float numpy array, or None if missing or all NaN."""
    if col not in df.columns:
        return None
    arr = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    return arr if np.any(np.isfinite(arr)) else None


def _format_axis(
    ax: Any,
    title: str,
    ylabel: str,
    xlabel: Optional[str] = None,
    legend_fontsize: int = 9,
) -> None:
    """Apply consistent grid, labels, title, and legend to a Matplotlib axis."""
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    if xlabel:
        ax.set_xlabel(xlabel)
    ax.grid(True, linestyle="--", alpha=0.4)
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", fontsize=legend_fontsize)


@dataclass
class AnalysisResult:
    """Holds the paths and metrics table produced by analyzing a session workbook."""
    workbook_path: Path
    output_dir: Path
    metrics_df: pd.DataFrame
    summary_dict: Dict[str, Any]
    generated_plots: Dict[str, Path] = field(default_factory=dict)


class SessionAnalyzer:
    """
    Loads a saved Excel workbook from `recordings/`, computes consistency metrics,
    and saves diagnostic comparison plots.
    """

    def __init__(self, dpi: int = 150) -> None:
        self.dpi = int(dpi)

    def _save_figure(self, fig: Any, save_path: Path) -> Path:
        fig.tight_layout()
        fig.savefig(save_path, dpi=self.dpi)
        plt.close(fig)
        return save_path

    def analyze_workbook(
        self,
        workbook_path: Path | str,
        output_dir: Optional[Path | str] = None,
        update_workbook_metrics: bool = True,
    ) -> AnalysisResult:
        """
        Load `RawData`, `ProcessedData`, and `Settings` from `workbook_path`,
        compute the `Metrics` table, and generate all 7 analysis plots.
        """
        wb_path = Path(workbook_path).resolve()
        if not wb_path.is_file():
            raise FileNotFoundError(f"Excel recording workbook not found: {wb_path}")

        out_dir = (
            Path(output_dir).resolve()
            if output_dir is not None
            else wb_path.parent / f"{wb_path.stem}_analysis"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        sheets = pd.read_excel(wb_path, sheet_name=["RawData", "ProcessedData", "Settings"])
        raw_df = sheets["RawData"]
        processed_df = sheets["ProcessedData"]
        settings_df = sheets["Settings"]
        metrics_df = compute_consistency_metrics_table(processed_df)

        if update_workbook_metrics:
            with pd.ExcelWriter(wb_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                metrics_df.to_excel(writer, sheet_name="Metrics", index=False)

        plots: Dict[str, Path] = {}
        if len(processed_df) > 0:
            t = _extract_numeric_column(processed_df, "elapsed_s")
            if t is None:
                t = np.arange(len(processed_df), dtype=float)

            sh_imu_col = (
                "imu1_shoulder_corrected_deg"
                if "imu1_shoulder_corrected_deg" in processed_df.columns
                else "imu1_pitch_deg"
            )
            plots["shoulder_angles"] = self._plot_joint_angles(
                processed_df,
                t,
                out_dir / "shoulder_angles_comparison.png",
                joint_name="Shoulder",
                vision_col="shoulder_vision_deg",
                vision_label="Shoulder Vision (MediaPipe)",
                imu_col=sh_imu_col,
                imu_label="IMU 1 Shoulder (Aligned)",
                ukf_col="shoulder_ukf_deg",
                ukf_label="Shoulder UKF (Fused)",
            )
            plots["elbow_angles"] = self._plot_joint_angles(
                processed_df,
                t,
                out_dir / "elbow_angles_comparison.png",
                joint_name="Elbow",
                vision_col="elbow_vision_deg",
                vision_label="Elbow Vision (MediaPipe)",
                imu_col="imu1_elbow_deg",
                imu_label="IMU 1 Elbow (Aligned)",
                ukf_col="elbow_ukf_deg",
                ukf_label="Elbow UKF (Fused)",
            )
            plots["trunk_angle"] = self._plot_trunk_angle(
                processed_df, t, out_dir / "trunk_angle.png"
            )
            plots["shoulder_differences"] = self._plot_joint_differences(
                processed_df, t, out_dir / "shoulder_differences.png", "Shoulder", "shoulder"
            )
            plots["elbow_differences"] = self._plot_joint_differences(
                processed_df, t, out_dir / "elbow_differences.png", "Elbow", "elbow"
            )
            plots["kalman_gains"] = self._plot_kalman_gains(
                processed_df, t, out_dir / "ukf_kalman_gains.png"
            )
            plots["ukf_consistency_distributions"] = self._plot_ukf_agreement_diagnostics(
                processed_df, out_dir / "ukf_consistency_distributions.png"
            )

        summary = {
            "workbook_path": str(wb_path),
            "analysis_output_dir": str(out_dir),
            "total_recorded_samples": int(len(processed_df)),
            "raw_sample_count": int(len(raw_df)),
            "settings_count": int(len(settings_df)),
            "note": (
                "Metrics quantify inter-measurement consistency and filter agreement "
                "(Vision vs. IMU vs. UKF), not absolute accuracy against an external "
                "ground-truth motion-capture reference."
            ),
            "metrics": metrics_df.to_dict(orient="records"),
        }
        logger.info("Completed analysis for %s (%d plots in %s).", wb_path.name, len(plots), out_dir)
        return AnalysisResult(wb_path, out_dir, metrics_df, summary, plots)

    def _plot_joint_angles(
        self,
        df: pd.DataFrame,
        t: np.ndarray,
        save_path: Path,
        joint_name: str,
        vision_col: str,
        vision_label: str,
        imu_col: str,
        imu_label: str,
        ukf_col: str,
        ukf_label: str,
    ) -> Path:
        """Plot Vision vs. IMU vs. UKF angles over time for a single joint."""
        fig, ax = plt.subplots(figsize=(10, 5))
        series_specs = (
            (vision_col, vision_label, "--", "#1f77b4", 1.4),
            (imu_col, imu_label, ":", "#ff7f0e", 1.6),
            (ukf_col, ukf_label, "-", "#2ca02c", 2.2),
        )
        for col, label, style, color, lw in series_specs:
            vals = _extract_numeric_column(df, col)
            if vals is not None:
                ax.plot(t, vals, linestyle=style, color=color, linewidth=lw, label=label, alpha=0.9)
        _format_axis(
            ax,
            f"{joint_name} Angle Comparison: Vision vs. IMU vs. UKF (Inter-Source Consistency)",
            "Angle (deg)",
            "Elapsed Time (s)",
        )
        return self._save_figure(fig, save_path)

    def _plot_trunk_angle(self, df: pd.DataFrame, t: np.ndarray, save_path: Path) -> Path:
        """Plot IMU 2 Pitch (Trunk angle, without UKF fusion) over time."""
        fig, ax = plt.subplots(figsize=(10, 4.2))
        vals = _extract_numeric_column(df, "trunk_angle_deg")
        if vals is not None:
            ax.plot(t, vals, color="#9467bd", linewidth=2.0, label="IMU 2 Pitch / Trunk Angle (Unfused)")
        ax.axhline(0.0, color="gray", linestyle="--", linewidth=0.9, alpha=0.6)
        _format_axis(
            ax,
            "Trunk Angle Over Time (IMU 2 Pitch, Without UKF Fusion)",
            "Trunk Angle (deg)",
            "Elapsed Time (s)",
        )
        return self._save_figure(fig, save_path)

    def _plot_joint_differences(
        self,
        df: pd.DataFrame,
        t: np.ndarray,
        save_path: Path,
        joint_name: str,
        prefix: str,
    ) -> Path:
        """Plot signed and absolute pairwise differences (Vision-IMU, UKF-IMU, UKF-Vision)."""
        fig, (ax_signed, ax_abs) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

        for col, label, color in (
            (f"{prefix}_diff_vision_minus_imu_deg", "Vision - IMU (Signed)", "#d62728"),
            (f"{prefix}_diff_ukf_minus_imu_deg", "UKF - IMU (Signed)", "#ff7f0e"),
            (f"{prefix}_diff_ukf_minus_vision_deg", "UKF - Vision (Signed)", "#1f77b4"),
        ):
            vals = _extract_numeric_column(df, col)
            if vals is not None:
                ax_signed.plot(t, vals, label=label, color=color, linewidth=1.5, alpha=0.85)
        ax_signed.axhline(0.0, color="black", linestyle="--", linewidth=0.9, alpha=0.6)
        _format_axis(ax_signed, f"{joint_name} Signed Measurement Differences (deg)", "Signed Residual (deg)")

        for col, label, color in (
            (f"{prefix}_abs_diff_vision_vs_imu_deg", "|Vision - IMU|", "#d62728"),
            (f"{prefix}_abs_diff_ukf_vs_imu_deg", "|UKF - IMU|", "#ff7f0e"),
            (f"{prefix}_abs_diff_ukf_vs_vision_deg", "|UKF - Vision|", "#1f77b4"),
        ):
            vals = _extract_numeric_column(df, col)
            if vals is not None:
                ax_abs.plot(t, vals, label=label, color=color, linewidth=1.5, alpha=0.85)
        _format_axis(
            ax_abs,
            f"{joint_name} Absolute Measurement Differences (deg)",
            "Absolute Difference (deg)",
            "Elapsed Time (s)",
        )
        return self._save_figure(fig, save_path)

    def _plot_kalman_gains(self, df: pd.DataFrame, t: np.ndarray, save_path: Path) -> Path:
        """Plot actual UKF Kalman gain values (K_angle and K_velocity) over time."""
        fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
        panels = (
            (
                axes[0, 0],
                "Shoulder UKF Angle Gain (K[0])",
                "Gain (deg / deg)",
                (
                    ("shoulder_k_imu_angle", "K_angle (IMU update)", "#ff7f0e", "o-"),
                    ("shoulder_k_vision_angle", "K_angle (Vision update)", "#1f77b4", "s--"),
                ),
            ),
            (
                axes[0, 1],
                "Shoulder UKF Velocity Gain (K[1])",
                "Gain ((deg/s) / deg)",
                (
                    ("shoulder_k_imu_velocity", "K_velocity (IMU update)", "#ff7f0e", "o-"),
                    ("shoulder_k_vision_velocity", "K_velocity (Vision update)", "#1f77b4", "s--"),
                ),
            ),
            (
                axes[1, 0],
                "Elbow UKF Angle Gain (K[0])",
                "Gain (deg / deg)",
                (
                    ("elbow_k_imu_angle", "K_angle (IMU update)", "#2ca02c", "o-"),
                    ("elbow_k_vision_angle", "K_angle (Vision update)", "#9467bd", "s--"),
                ),
            ),
            (
                axes[1, 1],
                "Elbow UKF Velocity Gain (K[1])",
                "Gain ((deg/s) / deg)",
                (
                    ("elbow_k_imu_velocity", "K_velocity (IMU update)", "#2ca02c", "o-"),
                    ("elbow_k_vision_velocity", "K_velocity (Vision update)", "#9467bd", "s--"),
                ),
            ),
        )
        for ax, title, ylabel, series_list in panels:
            for col, label, color, fmt_str in series_list:
                vals = _extract_numeric_column(df, col)
                if vals is not None:
                    mask = np.isfinite(vals)
                    ax.plot(
                        t[mask], vals[mask], fmt_str, color=color, label=label,
                        markersize=3.5, linewidth=1.3, alpha=0.85,
                    )
            _format_axis(ax, title, ylabel, legend_fontsize=8)
        axes[1, 0].set_xlabel("Elapsed Time (s)")
        axes[1, 1].set_xlabel("Elapsed Time (s)")
        fig.suptitle("Actual UKF Kalman Gain Evolution Over Time", fontsize=12)
        return self._save_figure(fig, save_path)

    def _plot_ukf_agreement_diagnostics(self, df: pd.DataFrame, save_path: Path) -> Path:
        """Plot residual histograms comparing UKF output with IMU and Vision measurements."""
        fig, (ax_sh, ax_el) = plt.subplots(1, 2, figsize=(12, 4.8))
        for ax, joint, prefix in ((ax_sh, "Shoulder", "shoulder"), (ax_el, "Elbow", "elbow")):
            for col, label, color in (
                (f"{prefix}_diff_ukf_minus_imu_deg", "UKF - IMU", "#ff7f0e"),
                (f"{prefix}_diff_ukf_minus_vision_deg", "UKF - Vision", "#1f77b4"),
                (f"{prefix}_diff_vision_minus_imu_deg", "Vision - IMU", "#d62728"),
            ):
                vals = _extract_numeric_column(df, col)
                if vals is not None:
                    clean = vals[np.isfinite(vals)]
                    ax.hist(
                        clean,
                        bins=min(25, max(5, len(clean) // 2 + 1)),
                        alpha=0.45,
                        color=color,
                        edgecolor=color,
                        label=f"{label} (μ={np.mean(clean):+.2f}°, σ={np.std(clean):.2f}°)",
                    )
            ax.axvline(0.0, color="black", linestyle="--", linewidth=1.0)
            _format_axis(
                ax,
                f"{joint}: Residual Distributions (Inter-Source Consistency)",
                "Sample Count",
                "Signed Difference (deg)",
                legend_fontsize=8,
            )
        return self._save_figure(fig, save_path)
