import math
import time
import threading

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from AeroPy import TrignoBase as tb

# ---------------- Settings ----------------
RECORD_SECONDS = 3000.0
SENSOR1_INDEX, SENSOR2_INDEX = 0, 1
WARMUP_SECONDS, CALIBRATION_SECONDS = 30.0, 5.0
ZERO_DEADBAND_DEG = 2.0
VISIBILITY_MIN = 0.5
SHOULDER_Z_TOLERANCE = 0.08
LANDMARK_ALPHA = 0.3
SENSOR_STALE_SECONDS = 1.0
CAMERA_INDEX = 0

# UKF tuning: state [angle (deg), angular velocity (deg/s)].
# These are initial tuning values, not experimentally identified noise values.
Q_ANGLE, Q_VELOCITY = 1.0, 25.0
R_IMU, R_VISION = 9.0, 16.0       # measurement variances, deg^2
INITIAL_P_ANGLE, INITIAL_P_VELOCITY = 100.0, 400.0
UKF_ALPHA, UKF_BETA, UKF_KAPPA = 0.35, 2.0, 0.0

stop_event = threading.Event()
lock = threading.Lock()
sensor_data = {
    1: {"pitch": None, "yaw": None, "time": 0.0, "ready": False},
    2: {"pitch": None, "yaw": None, "time": 0.0, "ready": False},
}
status = {"sensor": "Starting", "calibration": "Waiting"}


# =====================================================================
# DELSYS AND QUATERNIONS
# =====================================================================
class DataHandler:
    streamYTData = True
    pauseFlag = False
    EMGplot = None

    class Data:
        packetCount = 0
        allcollectiondata = []

    DataHandler = Data()

    def threadManager(self, start_trigger, stop_trigger):
        pass


class LinkController:
    use_ant = False

    def get_device_types(self):
        return []


def normalize(q):
    n = math.sqrt(sum(float(v) ** 2 for v in q))
    return None if n < 1e-8 else tuple(float(v) / n for v in q)


def q_conjugate(q):
    w, x, y, z = q
    return w, -x, -y, -z


def q_multiply(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (
        w1*w2-x1*x2-y1*y2-z1*z2,
        w1*x2+x1*w2+y1*z2-z1*y2,
        w1*y2-x1*z2+y1*w2+z1*x2,
        w1*z2+x1*y2-y1*x2+z1*w2,
    )


def average_quaternions(samples):
    if not samples:
        return None
    ref, total = samples[0], np.zeros(4)
    for q in samples:
        if sum(a*b for a, b in zip(ref, q)) < 0:
            q = tuple(-v for v in q)
        total += np.asarray(q)
    return normalize(total)


def quaternion_to_euler(q):
    q = normalize(q)
    if q is None:
        return None
    w, x, y, z = q
    sr, cr = 2*(w*x+y*z), 1-2*(x*x+y*y)
    sp = max(-1.0, min(1.0, 2*(w*y-z*x)))
    sy, cy = 2*(w*z+x*y), 1-2*(y*y+z*z)
    return tuple(math.degrees(v) for v in (
        math.atan2(sr, cr), math.asin(sp), math.atan2(sy, cy)
    ))


def wrap_deg(a):
    return (float(a) + 180.0) % 360.0 - 180.0


def deadband(a):
    return 0.0 if abs(a) <= ZERO_DEADBAND_DEG else a


def find_or_mode(base, index):
    modes = [str(m) for m in base.getSampleModes(index)]
    mode = next((m for m in modes if "16" in m.lower()
                 and ("or" in m.lower() or "orientation" in m.lower())), None)
    if mode is None:
        raise RuntimeError(f"OR 16 bits mode not found for sensor {index}. Modes: {modes}")
    return mode


def find_quaternion_channels(sensor):
    result, accuracy = {}, None
    for ch in sensor.channels:
        name, guid = str(ch.name).upper(), str(ch.guid).lower()
        for component in "WXYZ":
            if f"ORIENTATION {component}" in name:
                result[component.lower()] = guid
        if "ORIENTATION ACCURACY" in name:
            accuracy = guid
    if set(result) != set("wxyz"):
        raise RuntimeError(
            f"{sensor.name}: missing quaternion channels; found {[c.name for c in sensor.channels]}"
        )
    return result, accuracy


def set_sensor(number, pitch, yaw, timestamp):
    with lock:
        sensor_data[number] = {
            "pitch": pitch, "yaw": yaw, "time": timestamp, "ready": True
        }


def get_sensor(number, axis):
    with lock:
        d = sensor_data[number].copy()
    if not d["ready"] or time.monotonic() - d["time"] > SENSOR_STALE_SECONDS:
        return None
    return d[axis]


def set_status(sensor=None, calibration=None):
    with lock:
        if sensor is not None:
            status["sensor"] = sensor
        if calibration is not None:
            status["calibration"] = calibration


def get_status():
    with lock:
        return status.copy()


def sensor_worker():
    """One TrignoBase connection streams both sensors in OR 16 bits mode."""
    base = None
    try:
        base = tb.TrignoBase(DataHandler())
        print("Connecting to Delsys...")
        base.Connect_Callback()
        base.scan_callback(LinkController())
        if not base.sensors:
            raise RuntimeError("No Delsys sensors found.")

        indexes = {1: SENSOR1_INDEX, 2: SENSOR2_INDEX}
        for number, idx in indexes.items():
            if idx >= len(base.sensors):
                raise RuntimeError(f"Sensor {number}, index {idx}, not found.")
            mode = find_or_mode(base, idx)
            base.setSampleMode(idx, mode)
            print(f"Sensor {number}: {base.sensors[idx].name} -> {mode}")

        base.set_sensors_list()

        guid_map = {}
        for number, idx in indexes.items():
            channels, _accuracy = find_quaternion_channels(base.sensors[idx])
            for component, guid in channels.items():
                guid_map[guid] = (number, component)

        base.Start_Callback(False, False, None, None)
        set_status(sensor="Delsys streaming", calibration="Warm-up 30 s")
        print("Keep both sensors stationary for 30 s warm-up + 5 s neutral calibration.")

        latest = {1: {}, 2: {}}
        refs = {1: None, 2: None}
        calibration_samples = {1: [], 2: []}
        calibrated = {1: False, 2: False}
        start = time.monotonic()

        while not stop_event.is_set() and time.monotonic() - start < RECORD_SECONDS:
            if not base.TrigBase.CheckYTDataQueue():
                time.sleep(0.003)
                continue
            raw = base.TrigBase.PollYTDataByString()
            received_at = time.monotonic()

            # Same channel-value assembly strategy as supplied modes.py:
            # latest W/X/Y/Z values. API timestamp units were not established.
            for guid in raw.Keys:
                key = str(guid).lower()
                if key not in guid_map:
                    continue
                number, component = guid_map[key]
                for sample in raw[guid]:
                    try:
                        latest[number][component] = float(sample.Item2)
                    except (TypeError, ValueError):
                        pass

            elapsed = received_at - start
            for number in (1, 2):
                vals = latest[number]
                if not all(k in vals for k in "wxyz"):
                    continue
                q = normalize(tuple(vals[k] for k in "wxyz"))
                if q is None or elapsed < WARMUP_SECONDS:
                    continue

                if not calibrated[number]:
                    calibration_samples[number].append(q)
                    if elapsed >= WARMUP_SECONDS + CALIBRATION_SECONDS:
                        refs[number] = average_quaternions(calibration_samples[number])
                        if refs[number] is None:
                            raise RuntimeError(f"Sensor {number}: calibration failed.")
                        calibrated[number] = True
                        print(f"Sensor {number}: calibration complete.")
                    continue

                relative = normalize(q_multiply(q_conjugate(refs[number]), q))
                euler = quaternion_to_euler(relative)
                if euler is None:
                    continue
                mathematical_roll, mathematical_pitch, mathematical_yaw = euler

                # Preserve modes.py physical mapping:
                # its reported Pitch is mathematical Roll.
                # Elbow uses mathematical Yaw. Roll output is discarded entirely.
                imu_pitch = deadband(mathematical_roll)
                imu_yaw = deadband(mathematical_yaw)
                set_sensor(number, imu_pitch, imu_yaw, received_at)

            if all(calibrated.values()):
                set_status(sensor="Delsys streaming", calibration="Both sensors calibrated")
            else:
                set_status(
                    sensor="Delsys streaming",
                    calibration=f"Warm-up/calibration {elapsed:.0f}/35 s"
                )

    except Exception as exc:
        print("Delsys error:", exc)
        set_status(sensor=f"DELSYS ERROR: {exc}")
    finally:
        if base is not None:
            try:
                base.Stop_Callback()
            except Exception as exc:
                print("Delsys stop warning:", exc)


# =====================================================================
# REAL UNSCENTED KALMAN FILTER
# =====================================================================
def angle_residual(a, b):
    return wrap_deg(a - b)


class AngleUKF:
    """Scaled sigma-point UKF; state [angle, angular velocity], scalar angle input."""
    def __init__(self):
        self.x = np.array([0.0, 0.0])
        self.P = np.diag([INITIAL_P_ANGLE, INITIAL_P_VELOCITY]).astype(float)
        self.Q = np.diag([Q_ANGLE, Q_VELOCITY]).astype(float)
        self.initialized = False
        self.last_time = None
        self.last_source_time = {"imu": None, "vision": None}

    def weights(self):
        n = 2
        lam = UKF_ALPHA**2 * (n + UKF_KAPPA) - n
        c = n + lam
        wm = np.full(2*n+1, 1/(2*c))
        wc = wm.copy()
        wm[0] = lam/c
        wc[0] = lam/c + 1 - UKF_ALPHA**2 + UKF_BETA
        return c, wm, wc

    @staticmethod
    def circular_mean(sigmas, weights):
        radians = np.radians(sigmas[:, 0])
        angle = math.degrees(math.atan2(
            float(np.sum(weights*np.sin(radians))),
            float(np.sum(weights*np.cos(radians)))
        ))
        velocity = float(np.sum(weights*sigmas[:, 1]))
        return np.array([angle, velocity])

    def sigma_points(self):
        c, wm, wc = self.weights()
        try:
            root = np.linalg.cholesky(c*self.P)
        except np.linalg.LinAlgError:
            root = np.linalg.cholesky(c*(self.P + np.eye(2)*1e-8))
        sigmas = [self.x.copy()]
        for i in range(2):
            sigmas.extend([self.x + root[:, i], self.x - root[:, i]])
        return np.asarray(sigmas), wm, wc

    def predict(self, timestamp):
        timestamp = float(timestamp)
        if self.last_time is None:
            self.last_time = timestamp
            return
        dt = timestamp - self.last_time
        if dt <= 0:
            return
        dt = min(dt, 0.25)
        sigmas, wm, wc = self.sigma_points()
        propagated = np.asarray([
            [wrap_deg(s[0] + s[1]*dt), s[1]] for s in sigmas
        ])
        x_pred = self.circular_mean(propagated, wm)
        p_pred = np.zeros((2, 2))
        for i, s in enumerate(propagated):
            d = np.array([angle_residual(s[0], x_pred[0]), s[1]-x_pred[1]])
            p_pred += wc[i]*np.outer(d, d)
        self.x = x_pred
        self.x[0] = wrap_deg(self.x[0])
        self.P = p_pred + self.Q*max(dt, 1e-3)
        self.P = 0.5*(self.P + self.P.T)
        self.last_time = timestamp

    def update(self, measurement, source, timestamp):
        if measurement is None or not np.isfinite(measurement):
            return self.x[0] if self.initialized else None
        timestamp = float(timestamp)
        previous = self.last_source_time[source]
        if previous is not None and timestamp <= previous:
            return self.x[0] if self.initialized else None
        if self.last_time is None:
            self.last_time = timestamp
        elif timestamp < self.last_time - 1e-6:
            # No rewind/replay is implemented for out-of-order delayed samples.
            return self.x[0] if self.initialized else None
        else:
            self.predict(timestamp)

        z = wrap_deg(measurement)
        R = R_IMU if source == "imu" else R_VISION
        if not self.initialized:
            self.x[:] = [z, 0.0]
            self.P[0, 0] = min(self.P[0, 0], R)
            self.initialized = True
            self.last_source_time[source] = timestamp
            return self.x[0]

        sigmas, wm, wc = self.sigma_points()
        z_values = sigmas[:, 0]
        z_mean = math.degrees(math.atan2(
            float(np.sum(wm*np.sin(np.radians(z_values)))),
            float(np.sum(wm*np.cos(np.radians(z_values))))
        ))
        S = R
        Pxz = np.zeros(2)
        for i, s in enumerate(sigmas):
            dz = angle_residual(z_values[i], z_mean)
            dx = np.array([angle_residual(s[0], self.x[0]), s[1]-self.x[1]])
            S += wc[i]*dz*dz
            Pxz += wc[i]*dx*dz
        if S <= 1e-12:
            return self.x[0]
        K = Pxz/S
        self.x += K*angle_residual(z, z_mean)
        self.x[0] = wrap_deg(self.x[0])
        self.P -= np.outer(K, K)*S
        self.P = 0.5*(self.P + self.P.T)
        self.last_source_time[source] = timestamp
        return self.x[0]


def initialize_shoulder_ukf():
    return AngleUKF()


def initialize_elbow_ukf():
    return AngleUKF()


def predict_ukf(ukf, timestamp):
    ukf.predict(timestamp)


def update_ukf_with_imu(ukf, imu_angle, timestamp):
    return ukf.update(imu_angle, "imu", timestamp)


def update_ukf_with_vision(ukf, vision_angle, timestamp):
    return ukf.update(vision_angle, "vision", timestamp)


def fuse_shoulder_angle(ukf, imu_pitch, vision_shoulder, timestamp):
    if imu_pitch is not None:
        update_ukf_with_imu(ukf, imu_pitch, timestamp)
    if vision_shoulder is not None:
        update_ukf_with_vision(ukf, vision_shoulder, timestamp)
    return ukf.x[0] if ukf.initialized else None


def fuse_elbow_angle(ukf, imu_yaw, vision_elbow, timestamp):
    # Convert IMU 1 Yaw to the elbow-angle convention before UKF fusion.
    # Elbow IMU measurement = IMU 1 Yaw + 90 degrees.
    if imu_yaw is not None:
        imu_elbow_angle = imu_yaw + 90.0
        update_ukf_with_imu(ukf, imu_elbow_angle, timestamp)
    if vision_elbow is not None:
        update_ukf_with_vision(ukf, vision_elbow, timestamp)
    return ukf.x[0] if ukf.initialized else None


# =====================================================================
# MEDIAPIPE VISION (original angle definitions retained)
# =====================================================================
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
    (24, 26), (26, 28)
]


def calculate_angle(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    radians = (np.arctan2(c[1]-b[1], c[0]-b[0])
               - np.arctan2(a[1]-b[1], a[0]-b[0]))
    angle = abs(radians*180.0/np.pi)
    return float(360-angle if angle > 180 else angle)


def vision_angle(p1, p2, p3, width, height):
    if min(p1.visibility, p2.visibility, p3.visibility) < VISIBILITY_MIN:
        return None
    return calculate_angle(
        (p1.x*width, p1.y*height),
        (p2.x*width, p2.y*height),
        (p3.x*width, p3.y*height)
    )


def fmt(value):
    return "None" if value is None else f"{value:+.1f}"


def draw_overlay(frame, lines):
    h, w = frame.shape[:2]
    scale = w/640.0
    font = max(0.35, 0.5*scale)
    thickness = max(1, int(round(scale)))
    step, margin = max(16, int(22*scale)), max(6, int(10*scale))
    text_width = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, font, thickness)[0][0]
                     for t in lines)
    x, y = max(margin, w-margin-text_width), margin+step
    for i, text in enumerate(lines):
        pos = (x, y+step*i)
        cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, font,
                    (0, 0, 0), thickness+2, cv2.LINE_AA)


def run_camera():
    shoulder_ukf, elbow_ukf = initialize_shoulder_ukf(), initialize_elbow_ukf()
    options = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path="pose_landmarker_full.task"),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )
    detector = vision.PoseLandmarker.create_from_options(options)
    cap = cv2.VideoCapture(CAMERA_INDEX)
    previous_landmarks = None
    start = time.monotonic()

    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {CAMERA_INDEX}.")
        cv2.namedWindow("Rehab Monitor - MediaPipe + Delsys UKF", cv2.WINDOW_NORMAL)

        while cap.isOpened() and not stop_event.is_set():
            timestamp = time.monotonic()
            if timestamp-start >= RECORD_SECONDS:
                break
            ret, frame = cap.read()
            if not ret:
                break
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

            elbow_vis = shoulder_vis = None
            relative_elbow_z = shoulder_z_diff = None
            status_text, status_color = "NO POSE DETECTED", (255, 255, 255)

            if result.pose_landmarks:
                landmarks = result.pose_landmarks[0]
                if previous_landmarks is not None:
                    for i in range(len(landmarks)):
                        landmarks[i].x = LANDMARK_ALPHA*landmarks[i].x + (1-LANDMARK_ALPHA)*previous_landmarks[i].x
                        landmarks[i].y = LANDMARK_ALPHA*landmarks[i].y + (1-LANDMARK_ALPHA)*previous_landmarks[i].y
                        landmarks[i].z = LANDMARK_ALPHA*landmarks[i].z + (1-LANDMARK_ALPHA)*previous_landmarks[i].z
                previous_landmarks = landmarks

                for a, b in POSE_CONNECTIONS:
                    p1, p2 = landmarks[a], landmarks[b]
                    if p1.visibility > VISIBILITY_MIN and p2.visibility > VISIBILITY_MIN:
                        cv2.line(frame, (int(p1.x*w), int(p1.y*h)),
                                 (int(p2.x*w), int(p2.y*h)), (0, 0, 255), 2)
                for p in landmarks:
                    if p.visibility > VISIBILITY_MIN:
                        cv2.circle(frame, (int(p.x*w), int(p.y*h)), 4, (0, 255, 0), -1)

                l_shoulder, r_shoulder = landmarks[11], landmarks[12]
                r_elbow, r_wrist, r_hip = landmarks[14], landmarks[16], landmarks[24]
                shoulder_z_diff = abs(r_shoulder.z-l_shoulder.z)
                avg_shoulder_z = (r_shoulder.z+l_shoulder.z)/2.0
                relative_elbow_z = r_elbow.z-avg_shoulder_z

                elbow_vis = vision_angle(r_shoulder, r_elbow, r_wrist, w, h)
                shoulder_vis = vision_angle(r_hip, r_shoulder, r_elbow, w, h)

                if elbow_vis is None:
                    status_text, status_color = "LANDMARKS NOT VISIBLE", (0, 0, 255)
                elif shoulder_z_diff > SHOULDER_Z_TOLERANCE:
                    status_text, status_color = "WRONG: Keep Shoulders Straight!", (0, 0, 255)
                elif 90 <= elbow_vis <= 100 and abs(relative_elbow_z) < 0.05:
                    status_text, status_color = "START POSITION (Ready)", (255, 255, 0)
                elif 130 <= elbow_vis <= 160 and relative_elbow_z < -0.05:
                    status_text, status_color = "RIGHT", (0, 255, 0)
                else:
                    status_text, status_color = "WRONG", (0, 0, 255)

            imu1_pitch = get_sensor(1, "pitch")
            imu1_yaw = get_sensor(1, "yaw")
            imu2_pitch = get_sensor(2, "pitch")

            shoulder_fused = fuse_shoulder_angle(
                shoulder_ukf, imu1_pitch, shoulder_vis, timestamp
            )
            elbow_fused = fuse_elbow_angle(
                elbow_ukf, imu1_yaw, elbow_vis, timestamp
            )

            with lock:
                cal = status["calibration"]
            lines = [
                f"Shoulder Vision: {fmt(shoulder_vis)}",
                f"IMU 1 Pitch: {fmt(imu1_pitch)}",
                f"Shoulder UKF: {fmt(shoulder_fused)}",
                f"Elbow Vision: {fmt(elbow_vis)}",
                f"IMU 1 Yaw: {fmt(imu1_yaw)}",
                f"Elbow UKF: {fmt(elbow_fused)}",
                f"IMU 2 Pitch / Trunk: {fmt(imu2_pitch)}",
                f"Calibration: {cal}",
            ]
            draw_overlay(frame, lines)
            cv2.putText(frame, status_text, (max(10, w-480), h-40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 3)
            cv2.imshow("Rehab Monitor - MediaPipe + Delsys UKF", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        try:
            detector.close()
        except Exception:
            pass


if __name__ == "__main__":
    worker = threading.Thread(target=sensor_worker, daemon=True)
    worker.start()
    try:
        run_camera()
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        stop_event.set()
        worker.join(timeout=5.0)
        print("Program stopped.")
