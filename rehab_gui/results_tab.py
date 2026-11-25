"""
Results and Analysis tab for browsing recorded Excel workbooks, viewing
the 7 generated comparison plots, and inspecting inter-source consistency metrics.

Loads recorded data directly from the saved `.xlsx` files in `recordings/`
using `SessionAnalyzer` on a non-blocking background worker thread.
"""
from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Dict, List, Optional

import pandas as pd
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rehab_app.analysis import AnalysisResult, SessionAnalyzer
from rehab_gui.theme import PALETTE

PLOT_TITLES: Dict[str, str] = {
    "shoulder_angles_comparison.png": "1. Shoulder Angles: Vision vs. IMU 1 Pitch vs. UKF",
    "elbow_angles_comparison.png": "2. Elbow Angles: Vision vs. (IMU 1 Yaw + 90°) vs. UKF",
    "trunk_angle.png": "3. Trunk Angle (IMU 2 Pitch — Unfused)",
    "shoulder_differences.png": "4. Shoulder Signed & Absolute Differences",
    "elbow_differences.png": "5. Elbow Signed & Absolute Differences",
    "ukf_kalman_gains.png": "6. Actual UKF Kalman Gain Evolution Over Time",
    "ukf_consistency_distributions.png": "7. Residual Distributions (UKF vs. IMU vs. Vision)",
}


class _AnalysisSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class ResultsTab(QWidget):
    """Browser and viewer for saved Excel recordings, metrics, and analysis plots."""

    def __init__(self, recordings_dir: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.recordings_dir = Path(recordings_dir).resolve()
        self.analyzer = SessionAnalyzer()
        self._signals = _AnalysisSignals()
        self._signals.finished.connect(self._on_analysis_finished)
        self._signals.failed.connect(self._on_analysis_failed)
        self._current_plot_paths: List[Path] = []
        self._current_pixmap: Optional[QPixmap] = None

        self._build_ui()
        self.refresh_recordings_list()

    def _build_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(14)

        # =====================================================================
        # LEFT PANEL: SAVED EXCEL WORKBOOKS LIST & FILE ACTIONS
        # =====================================================================
        left_panel = QFrame()
        left_panel.setObjectName("panelCard")
        left_panel.setMinimumWidth(300)
        left_panel.setMaximumWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        list_title = QLabel("Recorded Sessions (recordings/)")
        list_title.setStyleSheet(f"font-size: 11.5pt; font-weight: bold; color: {PALETTE['tab_selected_bg']};")
        left_layout.addWidget(list_title)

        self.workbooks_list = QListWidget()
        self.workbooks_list.currentItemChanged.connect(self._on_workbook_selected)
        left_layout.addWidget(self.workbooks_list, stretch=1)

        btn_refresh = QPushButton("Refresh Recordings List")
        btn_refresh.clicked.connect(lambda: self.refresh_recordings_list())
        left_layout.addWidget(btn_refresh)

        self.analyze_btn = QPushButton("Generate / Refresh Analysis Plots")
        self.analyze_btn.setProperty("role", "primary")
        self.analyze_btn.clicked.connect(self.run_analysis_on_selected)
        left_layout.addWidget(self.analyze_btn)

        self.open_excel_btn = QPushButton("Open Excel Workbook")
        self.open_excel_btn.clicked.connect(self.open_selected_excel)
        left_layout.addWidget(self.open_excel_btn)

        self.open_folder_btn = QPushButton("Open Recordings Folder")
        self.open_folder_btn.clicked.connect(self.open_recordings_folder)
        left_layout.addWidget(self.open_folder_btn)

        root_layout.addWidget(left_panel)

        # =====================================================================
        # RIGHT PANEL: INTERACTIVE PLOT VIEWER & CONSISTENCY METRICS TABLE
        # =====================================================================
        right_panel = QFrame()
        right_panel.setObjectName("panelCard")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        top_bar = QHBoxLayout()
        plot_lbl = QLabel("Diagnostic Plot:")
        plot_lbl.setStyleSheet(f"font-weight: bold; color: {PALETTE['tab_selected_bg']};")
        self.plot_selector = QComboBox()
        self.plot_selector.setMinimumWidth(360)
        self.plot_selector.currentIndexChanged.connect(self._on_plot_index_changed)

        self.results_status_label = QLabel("Select a recording to inspect plots and metrics.")
        self.results_status_label.setStyleSheet(f"color: {PALETTE['text_secondary']};")

        top_bar.addWidget(plot_lbl)
        top_bar.addWidget(self.plot_selector, stretch=1)
        top_bar.addSpacing(12)
        top_bar.addWidget(self.results_status_label)
        right_layout.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Plot image preview area
        self.plot_image_label = QLabel("No analysis plot loaded.")
        self.plot_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_image_label.setMinimumHeight(310)
        self.plot_image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.plot_image_label.setStyleSheet(
            f"background-color: #141829; border: 1px solid {PALETTE['border']}; "
            f"border-radius: 6px; color: {PALETTE['text_secondary']};"
        )
        splitter.addWidget(self.plot_image_label)

        # Metrics table widget
        metrics_container = QWidget()
        metrics_layout = QVBoxLayout(metrics_container)
        metrics_layout.setContentsMargins(0, 6, 0, 0)
        metrics_layout.setSpacing(4)

        metrics_title = QLabel(
            "Inter-Source Consistency & Filter Agreement Metrics "
            "(Loaded from Excel 'Metrics' Sheet — Consistency, Not Ground-Truth Accuracy)"
        )
        metrics_title.setStyleSheet(f"font-size: 10pt; font-weight: bold; color: {PALETTE['tab_selected_bg']};")
        metrics_layout.addWidget(metrics_title)

        self.metrics_table = QTableWidget()
        self.metrics_table.setAlternatingRowColors(False)
        self.metrics_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.metrics_table.setMinimumHeight(180)
        metrics_layout.addWidget(self.metrics_table)

        splitter.addWidget(metrics_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        right_layout.addWidget(splitter, stretch=1)

        root_layout.addWidget(right_panel, stretch=1)

    def set_recordings_dir(self, recordings_dir: Path) -> None:
        self.recordings_dir = Path(recordings_dir).resolve()
        self.refresh_recordings_list()

    def refresh_recordings_list(self, select_workbook: Optional[Path] = None) -> None:
        """Scan `self.recordings_dir` for `.xlsx` files and populate the list."""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            self.recordings_dir.glob("*.xlsx"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        self.workbooks_list.blockSignals(True)
        self.workbooks_list.clear()
        selected_row = 0
        for idx, fpath in enumerate(files):
            item = QListWidgetItem(fpath.name)
            item.setData(Qt.ItemDataRole.UserRole, str(fpath))
            self.workbooks_list.addItem(item)
            if select_workbook is not None and fpath.resolve() == select_workbook.resolve():
                selected_row = idx
        self.workbooks_list.blockSignals(False)

        if files:
            self.workbooks_list.setCurrentRow(selected_row)
            self._on_workbook_selected(self.workbooks_list.currentItem(), None)
        else:
            self.plot_selector.clear()
            self.plot_image_label.clear()
            self.plot_image_label.setText("No recorded Excel sessions found in recordings/.")
            self.metrics_table.setRowCount(0)
            self.metrics_table.setColumnCount(0)

    def get_selected_workbook_path(self) -> Optional[Path]:
        item = self.workbooks_list.currentItem()
        if item is None:
            return None
        path_str = item.data(Qt.ItemDataRole.UserRole)
        return Path(path_str) if path_str else None

    def _on_workbook_selected(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        wb_path = self.get_selected_workbook_path()
        if wb_path is None or not wb_path.is_file():
            return
        self._load_workbook_views(wb_path)

    def _load_workbook_views(self, wb_path: Path) -> None:
        """Load the `Metrics` sheet and any existing `_analysis/*.png` plots for `wb_path`."""
        try:
            metrics_df = pd.read_excel(wb_path, sheet_name="Metrics")
            self._populate_metrics_table(metrics_df)
        except Exception as exc:
            self.results_status_label.setText(f"Could not read Metrics sheet: {exc}")

        analysis_dir = wb_path.parent / f"{wb_path.stem}_analysis"
        self.plot_selector.blockSignals(True)
        self.plot_selector.clear()
        self._current_plot_paths.clear()

        if analysis_dir.is_dir():
            for filename, title in PLOT_TITLES.items():
                p = analysis_dir / filename
                if p.is_file():
                    self._current_plot_paths.append(p)
                    self.plot_selector.addItem(title)
            for extra in sorted(analysis_dir.glob("*.png")):
                if extra not in self._current_plot_paths:
                    self._current_plot_paths.append(extra)
                    self.plot_selector.addItem(extra.name)

        self.plot_selector.blockSignals(False)

        if self._current_plot_paths:
            self.plot_selector.setCurrentIndex(0)
            self._on_plot_index_changed(0)
            self.results_status_label.setText(f"Loaded {wb_path.name} ({len(self._current_plot_paths)} plots).")
        else:
            self._current_pixmap = None
            self.plot_image_label.clear()
            self.plot_image_label.setText(
                f"No plots folder found for {wb_path.name}.\n"
                "Click 'Generate / Refresh Analysis Plots' to create them."
            )
            self.results_status_label.setText(f"Loaded {wb_path.name} (click Generate Plots to visualize).")

    def _populate_metrics_table(self, df: pd.DataFrame) -> None:
        display_cols = [
            c for c in (
                "Joint", "Comparison", "Valid_Paired_Samples", "Missing_Paired_Pct",
                "MAE_deg", "RMSE_deg", "Bias_Signed_Mean_deg", "Std_Residual_deg",
                "LoA_95_Lower_deg", "LoA_95_Upper_deg", "Pearson_r",
            )
            if c in df.columns
        ]
        if not display_cols:
            display_cols = list(df.columns)

        self.metrics_table.setColumnCount(len(display_cols))
        self.metrics_table.setHorizontalHeaderLabels(display_cols)
        self.metrics_table.setRowCount(len(df))

        for r_idx in range(len(df)):
            for c_idx, col_name in enumerate(display_cols):
                val = df.iloc[r_idx][col_name]
                if pd.isna(val):
                    text = "—"
                elif isinstance(val, float):
                    text = f"{val:.4f}" if abs(val) < 1000 else f"{val:.1f}"
                else:
                    text = str(val)
                item = QTableWidgetItem(text)
                if c_idx >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.metrics_table.setItem(r_idx, c_idx, item)

        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def _on_plot_index_changed(self, index: int) -> None:
        if 0 <= index < len(self._current_plot_paths):
            plot_path = self._current_plot_paths[index]
            pix = QPixmap(str(plot_path))
            if not pix.isNull():
                self._current_pixmap = pix
                self._rescale_current_pixmap()

    def _rescale_current_pixmap(self) -> None:
        if self._current_pixmap is not None and not self._current_pixmap.isNull():
            scaled = self._current_pixmap.scaled(
                self.plot_image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.plot_image_label.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale_current_pixmap()

    def run_analysis_on_selected(self) -> None:
        """Run `SessionAnalyzer.analyze_workbook()` in a background thread."""
        wb_path = self.get_selected_workbook_path()
        if wb_path is None or not wb_path.is_file():
            QMessageBox.information(self, "No Recording Selected", "Please select an Excel workbook from the list.")
            return

        self.analyze_btn.setEnabled(False)
        self.results_status_label.setText(f"Analyzing {wb_path.name} in background...")

        def _worker() -> None:
            try:
                res = self.analyzer.analyze_workbook(wb_path, update_workbook_metrics=True)
                self._signals.finished.emit(res)
            except Exception as exc:
                self._signals.failed.emit(str(exc))

        threading.Thread(target=_worker, name="GUIAnalysisWorker", daemon=True).start()

    def _on_analysis_finished(self, result: AnalysisResult) -> None:
        self.analyze_btn.setEnabled(True)
        self._load_workbook_views(result.workbook_path)
        self.results_status_label.setText(f"Analysis complete: {len(result.generated_plots)} plots ready.")

    def _on_analysis_failed(self, error_msg: str) -> None:
        self.analyze_btn.setEnabled(True)
        self.results_status_label.setText(f"Analysis failed: {error_msg}")
        QMessageBox.warning(self, "Analysis Error", f"Failed to analyze workbook:\n{error_msg}")

    def open_selected_excel(self) -> None:
        wb_path = self.get_selected_workbook_path()
        if wb_path is None or not wb_path.is_file():
            return
        try:
            os.startfile(str(wb_path))  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.information(self, "Excel File Path", f"Saved at:\n{wb_path}\n({exc})")

    def open_recordings_folder(self) -> None:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(self.recordings_dir))  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.information(self, "Recordings Folder", f"Folder path:\n{self.recordings_dir}\n({exc})")
