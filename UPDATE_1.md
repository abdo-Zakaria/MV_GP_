# Update 1: Dynamic IMU Offset Alignment for Shoulder and Elbow UKF Fusion

## 1. The Original Reference-Angle Mismatch

During neutral calibration (`30 s` stationary warm-up followed by `5 s` quaternion averaging), `CalibrationManager` computes a neutral reference quaternion $q_{\text{ref}}$ and outputs relative IMU angles derived from:

$$q_{\text{rel}} = \text{normalize}\!\left(q_{\text{ref}}^{*} \otimes q_{\text{current}}\right)$$

Because $q_{\text{rel}}$ is the rotation relative to the calibration pose, both IMU 1 Pitch (Shoulder) and IMU 1 Yaw (Elbow) are approximately **$0^\circ$** at the calibration pose.

By contrast, MediaPipe Vision measures the actual geometric joint angles at that same pose (for example, Shoulder $\approx 45^\circ$ and Elbow $\approx 95^\circ$). Previously:
- **Shoulder** had no reference offset, so the Shoulder UKF fused IMU 1 Pitch ($\approx 0^\circ$ at rest) directly against Shoulder Vision ($\approx 45^\circ$ at rest).
- **Elbow** previously relied on a hardcoded `+90.0°` static offset, which assumed the subject always calibrated at exactly $90^\circ$ and risked double-counting if combined with another offset.

As a result, the UKF received two measurements with different reference origins.

---

## 2. Dynamic Offset Solution

Both **Shoulder** and **Elbow** now use an independent, dynamically captured Vision calibration reference averaged during the exact same `5 s` calibration window as the IMU quaternion calibration:

1. **IMU quaternion calibration is unchanged:** `average_quaternions()`, `q_conjugate()`, `q_multiply()`, `quaternion_to_euler()`, physical axis mapping (`mathematical_roll -> imu_pitch`, `mathematical_yaw -> imu_yaw`), and `2.0°` deadband remain identical.
2. **Simultaneous Vision reference capture:** During the calibration window (`warmup_seconds <= elapsed <= warmup_seconds + calibration_seconds`), valid (non-`None`, finite) Shoulder Vision and Elbow Vision angles are collected independently and averaged to produce `shoulder_vision_ref` and `elbow_vision_ref`.
3. **No hardcoded calibration angle:** Neither `90°` nor any other static pose angle is assumed. The hardcoded static `+90°` elbow offset is replaced by `elbow_vision_ref` (and is never added twice).
4. **Configurable direction signs:** Explicit, validated direction signs (`shoulder_imu_direction_sign` and `elbow_imu_direction_sign`, each `+1.0` or `-1.0`) align the sign convention of each relative IMU axis before UKF fusion.
5. **Safe handling of missing Vision data:** If no valid Vision samples are captured for a joint during calibration, its Vision reference remains `None`, a warning is logged, and `align_imu_angle()` returns `None` instead of silently substituting an invalid reference.
6. **Reset support:** Calling `CalibrationManager.reset()` (via `controller.reset_calibration()` or `controller.reset_session()`) clears both IMU and Vision calibration samples and references together.

---

## 3. Exact Code Changes

| File | Functions / Classes Modified | Change Summary |
| :--- | :--- | :--- |
| `rehab_app/config.py` | `SHOULDER_IMU_DIRECTION_SIGN`, `ELBOW_IMU_DIRECTION_SIGN`, `RehabConfig`, `RehabConfig.validate()` | Added validated `+1.0` / `-1.0` direction sign parameters for Shoulder and Elbow IMU alignment. |
| `rehab_app/calibration.py` | `CalibrationManager.__init__()`, `reset()`, `record_vision_sample()`, `_finalize_vision_joint_locked()`, `get_vision_references()`, `get_vision_sample_counts()` | Captures and averages valid Shoulder and Elbow Vision angles independently during the calibration window, logs finalized references (or warnings if missing), and clears them on `reset()`. |
| `rehab_app/fusion.py` | `align_imu_angle()`, `FusionStepResult`, `JointFusionPipeline.__init__()`, `JointFusionPipeline.step()` | Added `align_imu_angle()` implementing `Vision_reference + direction_sign * IMU_relative`, reconciled the Elbow offset (`elbow_offset_deg=0.0` inside `step()` so no static `+90°` is added twice), added debug logging and alignment fields to `FusionStepResult`. |
| `rehab_app/controller.py` | `RehabApplicationController._init_subsystems()`, `step_session()`, `get_sensor_status()`, `get_current_measurements()` | Passes Vision samples into `calibration_manager.record_vision_sample()` during each step and forwards `shoulder_vision_ref` and `elbow_vision_ref` to `fusion_pipeline.step()`. |
| `rehab_app/recording.py` | `PROCESSED_COLUMNS`, `SessionRecorder.record_step()`, `build_dataframes()`, `compute_consistency_metrics_table()` | Logs `shoulder_vision_ref_deg`, `shoulder_direction_sign`, `shoulder_dynamic_offset_deg`, `imu1_shoulder_corrected_deg`, `elbow_vision_ref_deg`, `elbow_direction_sign`, `elbow_dynamic_offset_deg`, and `imu1_elbow_deg` in `ProcessedData` and Vision references in `Settings`. |
| `rehab_app/analysis.py` | `SessionAnalyzer.analyze_workbook()` | Plots `imu1_shoulder_corrected_deg` ("IMU 1 Shoulder (Aligned)") and `imu1_elbow_deg` ("IMU 1 Elbow (Aligned)"). |
| `rehab_app/__init__.py` | Package exports | Exported `align_imu_angle`, `SHOULDER_IMU_DIRECTION_SIGN`, and `ELBOW_IMU_DIRECTION_SIGN`. |
| `main.py` | `_simulated_sensor_quaternions()` | Updated simulation deltas to be relative to the calibration pose (`45.0°` shoulder, `95.0°` elbow) so simulation accurately reflects physical neutral calibration. |
| `tests/test_rehab_app.py` | `test_dynamic_offset_alignment_and_trunk_unfused()`, `test_dynamic_alignment_calibration_signs_missing_and_reset()` | Added unit tests verifying dynamic Vision reference averaging, calibration-pose alignment, multi-angle tracking, `+1`/`-1` direction signs, missing/NaN Vision handling, and reset behavior. |

---

## 4. How Calibration Works Now

1. **Warm-Up Phase (`0 <= elapsed < warmup_seconds`, default `30 s`):**
   - Incoming IMU quaternions and Vision angles are ignored for reference computation.
2. **Neutral Calibration Phase (`warmup_seconds <= elapsed < warmup_seconds + calibration_seconds`, default `30–35 s`):**
   - **IMU 1 & IMU 2:** Raw `(W, X, Y, Z)` quaternions are collected and averaged into `q_ref[1]` and `q_ref[2]` (unchanged).
   - **Shoulder Vision:** Valid finite `shoulder_vision_deg` values are averaged into `shoulder_vision_ref`.
   - **Elbow Vision:** Valid finite `elbow_vision_deg` values are averaged into `elbow_vision_ref`.
3. **Active Streaming Phase (`elapsed >= warmup_seconds + calibration_seconds`):**
   - Relative IMU angles (`imu1_pitch`, `imu1_yaw`) are computed from `q_rel` with deadband (unchanged).
   - Before entering the UKFs, each relative IMU angle is aligned to its corresponding Vision reference.
   - **Trunk (`IMU 2 Pitch`)** remains unfused and unchanged.

---

## 5. Equations Used

For each joint independently:

$$\text{IMU}_{\text{shoulder, corrected}} = \text{Vision}_{\text{shoulder, ref}} + s_{\text{shoulder}} \cdot \text{IMU}_{1,\text{pitch, rel}}$$

$$\text{IMU}_{\text{elbow, corrected}} = \text{Vision}_{\text{elbow, ref}} + s_{\text{elbow}} \cdot \text{IMU}_{1,\text{yaw, rel}}$$

where:
- $\text{Vision}_{\text{shoulder, ref}} = \frac{1}{N_s}\sum_{i=1}^{N_s} \theta_{\text{vis, shoulder}, i}$ over valid samples in the calibration window,
- $\text{Vision}_{\text{elbow, ref}} = \frac{1}{N_e}\sum_{i=1}^{N_e} \theta_{\text{vis, elbow}, i}$ over valid samples in the calibration window,
- $s_{\text{shoulder}}, s_{\text{elbow}} \in \{+1, -1\}$ are the configurable axis direction signs (default $+1.0$ matching existing conventions).

At the calibration pose ($\text{IMU}_{\text{rel}} \approx 0^\circ$):

$$\text{IMU}_{\text{shoulder, corrected}} \approx \text{Vision}_{\text{shoulder, ref}}, \qquad \text{IMU}_{\text{elbow, corrected}} \approx \text{Vision}_{\text{elbow, ref}}$$

---

## 6. How to Test

1. **Run all automated unit, pipeline, and GUI tests (simulated/mock data):**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest discover -s tests -v
   ```
2. **Run only the dynamic alignment tests:**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" -m unittest tests.test_rehab_app.TestMathematicalEquivalence.test_dynamic_offset_alignment_and_trunk_unfused tests.test_rehab_app.TestMathematicalEquivalence.test_dynamic_alignment_calibration_signs_missing_and_reset -v
   ```
3. **Run the headless end-to-end simulation and inspect the generated Excel `ProcessedData` and `Settings` sheets:**
   ```powershell
   & "C:\Users\DELL\AppData\Local\Programs\Python\Python313\python.exe" main.py --simulate --no-window --no-vision --warmup 2 --calibration 1 --duration 4
   ```
4. **Verify direction sign on physical Delsys hardware:**
   - Launch `python gui_main.py` or `python main.py` with the Delsys receiver and both sensors attached.
   - Hold a steady neutral pose during the 30 s warm-up and 5 s calibration window with the upper limb clearly visible to the webcam.
   - Move the shoulder and elbow slowly; if either `imu1_shoulder_corrected_deg` or `imu1_elbow_deg` moves opposite to Vision, set `shoulder_imu_direction_sign = -1.0` or `elbow_imu_direction_sign = -1.0` in `rehab_app/config.py`.

---

## 7. Remaining Limitations & Hardware Notes

- **Simulated vs. Real Hardware Validation:** All verification so far was performed using automated unit tests and deterministic simulation (`11/11` tests passing). Real Delsys Trigno hardware direction signs (`+1.0` vs `-1.0`) must be confirmed during live hardware testing with the sensors mounted in their actual clinical orientation.
- **Vision Visibility Requirement During Calibration:** Because dynamic alignment relies on the averaged Vision angle during the `5 s` calibration window, the subject's right hip, right shoulder, right elbow, and right wrist must be visible to the webcam during calibration; otherwise that joint's reference remains `None` and IMU updates for that joint are safely withheld until recalibrated.
