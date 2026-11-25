"""
MediaPipe pose detection, landmark smoothing, body-angle calculation,
and OpenCV overlay drawing.

If the webcam does not open, landmarks are missing, or vision angles/posture
feedback look unexpected, inspect this module.

Preserves all landmark definitions, smoothing formulas, visibility checks,
and posture rules from rehab_vision_delsys_ukf_Final.py:
- Right Shoulder angle: 2D angle at Right Shoulder (12) between Right Hip (24) and Right Elbow (14).
- Right Elbow angle: 2D angle at Right Elbow (14) between Right Shoulder (12) and Right Wrist (16).
- Exponential landmark smoothing with LANDMARK_ALPHA = 0.3.
- Minimum landmark visibility threshold VISIBILITY_MIN = 0.5.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np

from rehab_app.config import (
    DEFAULT_MODEL_ASSET_PATH,
    LANDMARK_ALPHA,
    MIN_POSE_CONFIDENCE,
    SHOULDER_Z_TOLERANCE,
    VISIBILITY_MIN,
)

logger = logging.getLogger(__name__)

# MediaPipe Pose landmark pairs used to draw the body skeleton overlay
POSE_CONNECTIONS: List[Tuple[int, int]] = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
    (24, 26), (26, 28),
]


def calculate_angle(
    a: Tuple[float, float] | np.ndarray,
    b: Tuple[float, float] | np.ndarray,
    c: Tuple[float, float] | np.ndarray,
) -> float:
    """
    Calculate the 2D planar angle (in degrees, within [0, 180]) at vertex `b`
    formed by points `a` -> `b` -> `c`.
    Matches calculate_angle() in rehab_vision_delsys_ukf_Final.py.
    """
    a_arr, b_arr, c_arr = np.array(a), np.array(b), np.array(c)
    radians = (
        np.arctan2(c_arr[1] - b_arr[1], c_arr[0] - b_arr[0])
        - np.arctan2(a_arr[1] - b_arr[1], a_arr[0] - b_arr[0])
    )
    angle = abs(radians * 180.0 / np.pi)
    return float(360.0 - angle if angle > 180.0 else angle)


def vision_angle(
    p1: Any,
    p2: Any,
    p3: Any,
    width: int | float,
    height: int | float,
    visibility_min: float = VISIBILITY_MIN,
) -> Optional[float]:
    """
    Convert three normalized MediaPipe landmarks (p1, p2, p3) to pixel coordinates
    and return the 2D joint angle at p2. Returns None if any landmark's visibility
    is below `visibility_min`.
    """
    if min(p1.visibility, p2.visibility, p3.visibility) < visibility_min:
        return None
    return calculate_angle(
        (p1.x * width, p1.y * height),
        (p2.x * width, p2.y * height),
        (p3.x * width, p3.y * height),
    )


def fmt(value: Optional[float]) -> str:
    """Format an angle value for the webcam overlay ('+45.0' or 'None')."""
    return "None" if value is None else f"{value:+.1f}"


def draw_overlay(frame: np.ndarray, lines: List[str]) -> None:
    """
    Draw the right-aligned telemetry text block in the top-right corner of the
    webcam frame. Matches draw_overlay() in rehab_vision_delsys_ukf_Final.py.
    """
    if not lines:
        return
    h, w = frame.shape[:2]
    scale = w / 640.0
    font = max(0.35, 0.5 * scale)
    thickness = max(1, int(round(scale)))
    step, margin = max(16, int(22 * scale)), max(6, int(10 * scale))
    text_width = max(
        cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, font, thickness)[0][0]
        for t in lines
    )
    x, y = max(margin, w - margin - text_width), margin + step
    for i, text in enumerate(lines):
        pos = (x, y + step * i)
        cv2.putText(
            frame,
            text,
            pos,
            cv2.FONT_HERSHEY_SIMPLEX,
            font,
            (0, 0, 0),
            thickness + 2,
            cv2.LINE_AA,
        )


@dataclass
class VisionMeasurement:
    """Holds all vision angles, depth metrics, visibilities, and posture status for one frame."""
    timestamp: float
    pose_detected: bool
    shoulder_angle_deg: Optional[float] = None
    elbow_angle_deg: Optional[float] = None
    shoulder_z_diff: Optional[float] = None
    relative_elbow_z: Optional[float] = None
    r_hip_visibility: Optional[float] = None
    r_shoulder_visibility: Optional[float] = None
    l_shoulder_visibility: Optional[float] = None
    r_elbow_visibility: Optional[float] = None
    r_wrist_visibility: Optional[float] = None
    posture_status: str = "NO POSE DETECTED"
    posture_color_bgr: Tuple[int, int, int] = (255, 255, 255)


class PoseVisionProcessor:
    """
    Detects human pose landmarks with MediaPipe, smooths landmark coordinates over time,
    draws the skeleton on the frame, and computes Shoulder and Elbow vision angles.
    """

    def __init__(
        self,
        model_asset_path: Path | str = DEFAULT_MODEL_ASSET_PATH,
        visibility_min: float = VISIBILITY_MIN,
        shoulder_z_tolerance: float = SHOULDER_Z_TOLERANCE,
        landmark_alpha: float = LANDMARK_ALPHA,
        min_confidence: float = MIN_POSE_CONFIDENCE,
        flip_horizontal: bool = True,
    ) -> None:
        self.model_asset_path = Path(model_asset_path).resolve()
        self.visibility_min = float(visibility_min)
        self.shoulder_z_tolerance = float(shoulder_z_tolerance)
        self.landmark_alpha = float(landmark_alpha)
        self.min_confidence = float(min_confidence)
        self.flip_horizontal = bool(flip_horizontal)

        self._detector: Any = None
        self._previous_landmarks: Any = None

    def initialize_detector(self) -> None:
        """Create the MediaPipe PoseLandmarker from pose_landmarker_full.task."""
        if self._detector is not None:
            return
        if not self.model_asset_path.is_file():
            raise FileNotFoundError(f"MediaPipe model asset not found: {self.model_asset_path}")

        # Load model bytes into memory so paths containing spaces work on Windows
        options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=self.model_asset_path.read_bytes()),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=self.min_confidence,
            min_pose_presence_confidence=self.min_confidence,
            min_tracking_confidence=self.min_confidence,
        )
        self._detector = vision.PoseLandmarker.create_from_options(options)
        self._previous_landmarks = None

    def reset_state(self) -> None:
        """Clear previous landmarks used for exponential smoothing."""
        self._previous_landmarks = None

    def close(self) -> None:
        """Release the MediaPipe detector resource."""
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception:
                pass
            self._detector = None
        self._previous_landmarks = None

    def evaluate_landmarks(
        self,
        landmarks: Sequence[Any],
        width: int,
        height: int,
        timestamp: float,
        frame_to_annotate: Optional[np.ndarray] = None,
    ) -> VisionMeasurement:
        """
        Smooth detected landmarks, optionally draw skeleton lines/points on `frame_to_annotate`,
        calculate Elbow and Shoulder angles, and evaluate exercise posture rules.
        """
        # Step 1: Exponential landmark smoothing across consecutive frames
        if self._previous_landmarks is not None:
            alpha = self.landmark_alpha
            for i in range(len(landmarks)):
                landmarks[i].x = alpha * landmarks[i].x + (1.0 - alpha) * self._previous_landmarks[i].x
                landmarks[i].y = alpha * landmarks[i].y + (1.0 - alpha) * self._previous_landmarks[i].y
                landmarks[i].z = alpha * landmarks[i].z + (1.0 - alpha) * self._previous_landmarks[i].z
        self._previous_landmarks = landmarks

        # Step 2: Draw skeleton connections (red) and landmark points (green)
        if frame_to_annotate is not None:
            for a, b in POSE_CONNECTIONS:
                p1, p2 = landmarks[a], landmarks[b]
                if p1.visibility > self.visibility_min and p2.visibility > self.visibility_min:
                    cv2.line(
                        frame_to_annotate,
                        (int(p1.x * width), int(p1.y * height)),
                        (int(p2.x * width), int(p2.y * height)),
                        (0, 0, 255),
                        2,
                    )
            for p in landmarks:
                if p.visibility > self.visibility_min:
                    cv2.circle(
                        frame_to_annotate,
                        (int(p.x * width), int(p.y * height)),
                        4,
                        (0, 255, 0),
                        -1,
                    )

        # Step 3: Extract upper-body landmarks and compute 2D joint angles
        l_shoulder, r_shoulder = landmarks[11], landmarks[12]
        r_elbow, r_wrist, r_hip = landmarks[14], landmarks[16], landmarks[24]

        shoulder_z_diff = float(abs(r_shoulder.z - l_shoulder.z))
        avg_shoulder_z = float((r_shoulder.z + l_shoulder.z) / 2.0)
        relative_elbow_z = float(r_elbow.z - avg_shoulder_z)

        elbow_vis = vision_angle(r_shoulder, r_elbow, r_wrist, width, height, self.visibility_min)
        shoulder_vis = vision_angle(r_hip, r_shoulder, r_elbow, width, height, self.visibility_min)

        # Step 4: Determine posture feedback text and color
        if elbow_vis is None:
            status_text, status_color = "LANDMARKS NOT VISIBLE", (0, 0, 255)
        elif shoulder_z_diff > self.shoulder_z_tolerance:
            status_text, status_color = "WRONG: Keep Shoulders Straight!", (0, 0, 255)
        elif 90.0 <= elbow_vis <= 100.0 and abs(relative_elbow_z) < 0.05:
            status_text, status_color = "START POSITION (Ready)", (255, 255, 0)
        elif 130.0 <= elbow_vis <= 160.0 and relative_elbow_z < -0.05:
            status_text, status_color = "RIGHT", (0, 255, 0)
        else:
            status_text, status_color = "WRONG", (0, 0, 255)

        return VisionMeasurement(
            timestamp=float(timestamp),
            pose_detected=True,
            shoulder_angle_deg=shoulder_vis,
            elbow_angle_deg=elbow_vis,
            shoulder_z_diff=shoulder_z_diff,
            relative_elbow_z=relative_elbow_z,
            r_hip_visibility=float(r_hip.visibility),
            r_shoulder_visibility=float(r_shoulder.visibility),
            l_shoulder_visibility=float(l_shoulder.visibility),
            r_elbow_visibility=float(r_elbow.visibility),
            r_wrist_visibility=float(r_wrist.visibility),
            posture_status=status_text,
            posture_color_bgr=status_color,
        )

    def process_frame(
        self,
        bgr_frame: np.ndarray,
        timestamp: float,
        annotate_frame: bool = False,
    ) -> Tuple[VisionMeasurement, np.ndarray]:
        """
        Flip the camera frame (if configured), run MediaPipe pose detection,
        and return (VisionMeasurement, processed_frame).
        """
        self.initialize_detector()
        if self.flip_horizontal:
            frame = cv2.flip(bgr_frame, 1)
        elif annotate_frame:
            frame = bgr_frame.copy()
        else:
            frame = bgr_frame

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

        if not result.pose_landmarks:
            return VisionMeasurement(timestamp=float(timestamp), pose_detected=False), frame

        measurement = self.evaluate_landmarks(
            result.pose_landmarks[0],
            width=w,
            height=h,
            timestamp=timestamp,
            frame_to_annotate=frame if annotate_frame else None,
        )
        return measurement, frame
