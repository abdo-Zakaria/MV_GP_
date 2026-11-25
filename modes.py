# import time

# import AeroPy.TrignoBase as tb


# class DataHandler:
#     streamYTData = True
#     pauseFlag = False
#     EMGplot = None

#     class Data:
#         packetCount = 0
#         allcollectiondata = []

#     DataHandler = Data()

#     def threadManager(self, start_trigger, stop_trigger):
#         pass


# class LinkController:
#     use_ant = False

#     def get_device_types(self):
#         return []


# PRINT_INTERVAL_SECONDS = 1


# base = tb.TrignoBase(DataHandler())

# try:
#     base.Connect_Callback()
#     base.scan_callback(LinkController())

#     if not base.sensors:
#         raise RuntimeError("No sensors found.")

#     sensor_index = 0
#     sensor = base.sensors[sensor_index]
#     modes = list(base.getSampleModes(sensor_index))

#     print(f"Sensor {sensor_index}: {sensor.name}")
#     print("Available modes:")
#     for i, mode in enumerate(modes, start=1):
#         print(f"  {i}. {mode}")

#     mode_text = [str(mode).lower() for mode in modes]

#     selected_index = next(
#         (i for i, text in enumerate(mode_text)
#          if "16" in text and ("or" in text or "orientation" in text)),
#         None,
#     )
#     if selected_index is None:
#         selected_index = next(
#             (i for i, text in enumerate(mode_text)
#              if "orientation" in text or text.strip().startswith("39")),
#             None,
#         )
#     if selected_index is None:
#         raise RuntimeError(
#             "No 16-bit Orientation/OR mode was found. "
#             "See the available modes printed above."
#         )

#     selected_mode = modes[selected_index]
#     base.setSampleMode(sensor_index, selected_mode)
#     base.set_sensors_list()
#     sensor = base.sensors[sensor_index]

#     print("\nSelected mode:", selected_mode)
#     print("=== CHANNELS ===")

#     channels_by_guid = {}
#     for i, channel in enumerate(sensor.channels, start=1):
#         guid = str(channel.guid).lower()
#         channels_by_guid[guid] = channel
#         print(
#             f"Channel {i}: "
#             f"Name={channel.name}, "
#             f"Type={channel.channel_type}, "
#             f"Rate={channel.sample_rate} Hz, "
#             f"GUID={channel.guid}"
#         )

#     base.Start_Callback(False, False, None, None)
#     print("\n=== DATA OUTPUT (5 seconds) ===")

#     start = time.monotonic()
#     last_print_time = 0.0
#     packet_count = 0
#     while time.monotonic() - start < 25:
#         if not base.TrigBase.CheckYTDataQueue():
#             time.sleep(0.005)
#             continue

#         data = base.TrigBase.PollYTDataByString()
#         latest_values = {}
#         for guid in data.Keys:
#             guid_key = str(guid).lower()
#             channel = channels_by_guid.get(guid_key)
#             name = channel.name if channel is not None else str(guid)
#             for point in data[guid]:
#                 packet_count += 1
#                 latest_values[name] = (point.Item1, point.Item2)

#         elapsed = time.monotonic() - start
#         if elapsed - last_print_time >= PRINT_INTERVAL_SECONDS:
#             print(f"\n--- {elapsed:.1f} seconds ---")
#             for name, (device_time, value) in latest_values.items():
#                 print(f"{name}: device_time={device_time:.6f}, value={value:.9g}")
#             last_print_time = elapsed

#     print(f"\nReceived {packet_count} channel samples.")
# finally:
#     try:
#         base.Stop_Callback()
#     except Exception:
#         pass


# import time
# import math

# import AeroPy.TrignoBase as tb


# class DataHandler:
#     streamYTData = True
#     pauseFlag = False
#     EMGplot = None

#     class Data:
#         packetCount = 0
#         allcollectiondata = []

#     DataHandler = Data()

#     def threadManager(self, start_trigger, stop_trigger):
#         pass


# class LinkController:
#     use_ant = False

#     def get_device_types(self):
#         return []


# PRINT_INTERVAL_SECONDS = 1


# def quaternion_to_euler(w, x, y, z):
#     # Normalize quaternion
#     norm = math.sqrt(w*w + x*x + y*y + z*z)

#     if norm == 0:
#         return 0.0, 0.0, 0.0

#     w, x, y, z = (
#         w / norm,
#         x / norm,
#         y / norm,
#         z / norm
#     )

#     # Roll (X-axis rotation)
#     sin_roll = 2.0 * (w*x + y*z)
#     cos_roll = 1.0 - 2.0 * (x*x + y*y)

#     roll = math.atan2(sin_roll, cos_roll)

#     # Pitch (Y-axis rotation)
#     sin_pitch = 2.0 * (w*y - z*x)
#     sin_pitch = max(-1.0, min(1.0, sin_pitch))

#     pitch = math.asin(sin_pitch)

#     # Yaw (Z-axis rotation)
#     sin_yaw = 2.0 * (w*z + x*y)
#     cos_yaw = 1.0 - 2.0 * (y*y + z*z)

#     yaw = math.atan2(sin_yaw, cos_yaw)

#     return (
#         math.degrees(roll),
#         math.degrees(pitch),
#         math.degrees(yaw)
#     )


# base = tb.TrignoBase(DataHandler())

# try:
#     base.Connect_Callback()
#     base.scan_callback(LinkController())

#     if not base.sensors:
#         raise RuntimeError("No sensors found.")

#     sensor_index = 0
#     sensor = base.sensors[sensor_index]
#     modes = list(base.getSampleModes(sensor_index))

#     print(f"Sensor {sensor_index}: {sensor.name}")
#     print("Available modes:")

#     for i, mode in enumerate(modes, start=1):
#         print(f"  {i}. {mode}")

#     mode_text = [str(mode).lower() for mode in modes]

#     selected_index = next(
#         (i for i, text in enumerate(mode_text)
#          if "16" in text and ("or" in text or "orientation" in text)),
#         None,
#     )

#     if selected_index is None:
#         selected_index = next(
#             (i for i, text in enumerate(mode_text)
#              if "orientation" in text or text.strip().startswith("39")),
#             None,
#         )

#     if selected_index is None:
#         raise RuntimeError(
#             "No 16-bit Orientation/OR mode was found."
#         )

#     selected_mode = modes[selected_index]
#     base.setSampleMode(sensor_index, selected_mode)
#     base.set_sensors_list()

#     sensor = base.sensors[sensor_index]

#     print("\nSelected mode:", selected_mode)
#     print("=== CHANNELS ===")

#     channels_by_guid = {}

#     for i, channel in enumerate(sensor.channels, start=1):
#         guid = str(channel.guid).lower()
#         channels_by_guid[guid] = channel

#         print(
#             f"Channel {i}: "
#             f"Name={channel.name}, "
#             f"Type={channel.channel_type}, "
#             f"Rate={channel.sample_rate} Hz, "
#             f"GUID={channel.guid}"
#         )

#     # Find quaternion channels
#     quaternion_channels = {}

#     for guid, channel in channels_by_guid.items():
#         name = channel.name.upper()

#         if "ORIENTATION W" in name:
#             quaternion_channels["w"] = guid
#         elif "ORIENTATION X" in name:
#             quaternion_channels["x"] = guid
#         elif "ORIENTATION Y" in name:
#             quaternion_channels["y"] = guid
#         elif "ORIENTATION Z" in name:
#             quaternion_channels["z"] = guid

#     if len(quaternion_channels) != 4:
#         raise RuntimeError(
#             "Could not find all four quaternion channels. "
#             "Check the printed channel names."
#         )

#     base.Start_Callback(False, False, None, None)

#     print("\n=== EULER ANGLES (ROLL, PITCH, YAW) ===")

#     start = time.monotonic()
#     last_print_time = 0.0

#     latest_quaternion = {}

#     while time.monotonic() - start < 75:

#         if not base.TrigBase.CheckYTDataQueue():
#             time.sleep(0.005)
#             continue

#         data = base.TrigBase.PollYTDataByString()

#         for guid in data.Keys:
#             guid_key = str(guid).lower()

#             for point in data[guid]:

#                 for component, component_guid in quaternion_channels.items():

#                     if guid_key == component_guid:
#                         latest_quaternion[component] = point.Item2

#         elapsed = time.monotonic() - start

#         if elapsed - last_print_time >= PRINT_INTERVAL_SECONDS:

#             if all(k in latest_quaternion for k in ("w", "x", "y", "z")):

#                 w = latest_quaternion["w"]
#                 x = latest_quaternion["x"]
#                 y = latest_quaternion["y"]
#                 z = latest_quaternion["z"]

#                 roll, pitch, yaw = quaternion_to_euler(w, x, y, z)

#                 print(f"\n--- {elapsed:.1f} seconds ---")
#                 # print(f"Roll : {roll:.2f} degrees")
#                 # print(f"Pitch: {pitch:.2f} degrees")
#                 # print(f"Yaw  : {yaw:.2f} degrees")
#                 print(f"w  : {w:.2f} unit")
#                 print(f"x  : {x:.2f} unit")
#                 print(f"y  : {y:.2f} unit")
#                 print(f"z  : {z:.2f} unit")

#             last_print_time = elapsed

# finally:
#     try:
#         base.Stop_Callback()
#     except Exception:
#         pass

############## 
### calibration /zero Drift Quaternions





# import time
# import math

# import AeroPy.TrignoBase as tb


# # ============================================================
# # SETTINGS
# # ============================================================

# WARMUP_DURATION = 30.0       # Allow Delsys orientation to settle
# CALIBRATION_DURATION = 5.0   # Neutral-position calibration
# PRINT_INTERVAL = 1.0
# RUN_DURATION = 300.0

# ZERO_DEADBAND_DEG = 2.0      # Ignore small residual angle variations

# sensor_index = 0


# # ============================================================
# # DELSYS DATA HANDLER
# # ============================================================

# class DataHandler:
#     streamYTData = True
#     pauseFlag = False
#     EMGplot = None

#     class Data:
#         packetCount = 0
#         allcollectiondata = []

#     DataHandler = Data()

#     def threadManager(self, start_trigger, stop_trigger):
#         pass


# class LinkController:
#     use_ant = False

#     def get_device_types(self):
#         return []


# # ============================================================
# # QUATERNION FUNCTIONS
# # Format: [w, x, y, z]
# # ============================================================

# def normalize(q):
#     norm = math.sqrt(sum(v * v for v in q))

#     if norm < 1e-8:
#         return None

#     return tuple(v / norm for v in q)


# def quaternion_conjugate(q):
#     w, x, y, z = q
#     return (w, -x, -y, -z)


# def quaternion_multiply(q1, q2):
#     w1, x1, y1, z1 = q1
#     w2, x2, y2, z2 = q2

#     return (
#         w1*w2 - x1*x2 - y1*y2 - z1*z2,
#         w1*x2 + x1*w2 + y1*z2 - z1*y2,
#         w1*y2 - x1*z2 + y1*w2 + z1*x2,
#         w1*z2 + x1*y2 - y1*x2 + z1*w2
#     )


# def average_quaternions(samples):
#     if not samples:
#         return None

#     reference = samples[0]
#     total = [0.0, 0.0, 0.0, 0.0]

#     for q in samples:
#         # q and -q represent the same orientation.
#         if sum(a*b for a, b in zip(reference, q)) < 0:
#             q = tuple(-v for v in q)

#         for i in range(4):
#             total[i] += q[i]

#     return normalize(total)


# def quaternion_to_euler(q):
#     q = normalize(q)

#     if q is None:
#         return None

#     w, x, y, z = q

#     # Roll
#     sin_roll = 2.0 * (w*x + y*z)
#     cos_roll = 1.0 - 2.0 * (x*x + y*y)
#     roll = math.atan2(sin_roll, cos_roll)

#     # Pitch
#     sin_pitch = 2.0 * (w*y - z*x)
#     sin_pitch = max(-1.0, min(1.0, sin_pitch))
#     pitch = math.asin(sin_pitch)

#     # Yaw
#     sin_yaw = 2.0 * (w*z + x*y)
#     cos_yaw = 1.0 - 2.0 * (y*y + z*z)
#     yaw = math.atan2(sin_yaw, cos_yaw)

#     return tuple(
#         math.degrees(a)
#         for a in (roll, pitch, yaw)
#     )


# def apply_deadband(angle, threshold):
#     if abs(angle) <= threshold:
#         return 0.0

#     return angle


# # ============================================================
# # CONNECT TO DELSYS
# # ============================================================

# base = tb.TrignoBase(DataHandler())

# try:

#     print("Connecting to Delsys...")

#     base.Connect_Callback()
#     base.scan_callback(LinkController())

#     if not base.sensors:
#         raise RuntimeError("No sensors found.")

#     sensor = base.sensors[sensor_index]

#     print("Connected sensor:", sensor.name)

#     # --------------------------------------------------------
#     # SELECT OR 16 BITS MODE
#     # --------------------------------------------------------

#     modes = list(base.getSampleModes(sensor_index))

#     selected_index = next(
#         (
#             i for i, mode in enumerate(modes)
#             if "16" in str(mode).lower()
#             and (
#                 "or" in str(mode).lower()
#                 or "orientation" in str(mode).lower()
#             )
#         ),
#         None
#     )

#     if selected_index is None:
#         raise RuntimeError("OR 16 bits mode not found.")

#     selected_mode = modes[selected_index]

#     base.setSampleMode(sensor_index, selected_mode)
#     base.set_sensors_list()

#     sensor = base.sensors[sensor_index]

#     print("Selected mode:", selected_mode)

#     # --------------------------------------------------------
#     # FIND QUATERNION CHANNELS
#     # --------------------------------------------------------

#     quaternion_channels = {}
#     accuracy_guid = None

#     for channel in sensor.channels:

#         guid = str(channel.guid).lower()
#         name = channel.name.upper()

#         if "ORIENTATION W" in name:
#             quaternion_channels["w"] = guid

#         elif "ORIENTATION X" in name:
#             quaternion_channels["x"] = guid

#         elif "ORIENTATION Y" in name:
#             quaternion_channels["y"] = guid

#         elif "ORIENTATION Z" in name:
#             quaternion_channels["z"] = guid

#         elif "ORIENTATION ACCURACY" in name:
#             accuracy_guid = guid

#     if len(quaternion_channels) != 4:
#         raise RuntimeError("Could not find all quaternion channels.")

#     guid_to_component = {
#         guid: component
#         for component, guid in quaternion_channels.items()
#     }

#     print("Quaternion channels found.")

#     # --------------------------------------------------------
#     # START COLLECTION
#     # --------------------------------------------------------

#     base.Start_Callback(False, False, None, None)

#     print("\nData collection started.")
#     print("Keep the sensor attached to the patient's arm.")
#     print("Keep the arm in neutral position during warm-up and calibration.")

#     latest_values = {}
#     latest_accuracy = None

#     warmup_samples = []
#     calibration_samples = []

#     reference_quaternion = None

#     start_time = time.monotonic()
#     last_print_time = 0.0

#     valid_updates = 0
#     calibration_complete = False

#     # ========================================================
#     # MAIN LOOP
#     # ========================================================

#     while time.monotonic() - start_time < RUN_DURATION:

#         if not base.TrigBase.CheckYTDataQueue():
#             time.sleep(0.005)
#             continue

#         data = base.TrigBase.PollYTDataByString()

#         new_quaternion_data = False

#         # ----------------------------------------------------
#         # READ LATEST CHANNEL VALUES
#         # ----------------------------------------------------

#         for guid in data.Keys:

#             guid_key = str(guid).lower()

#             for point in data[guid]:

#                 value = float(point.Item2)

#                 if guid_key in guid_to_component:

#                     component = guid_to_component[guid_key]
#                     latest_values[component] = value
#                     new_quaternion_data = True

#                 elif accuracy_guid and guid_key == accuracy_guid:

#                     latest_accuracy = value

#         if not new_quaternion_data:
#             continue

#         if not all(
#             key in latest_values
#             for key in ("w", "x", "y", "z")
#         ):
#             continue

#         raw_q = (
#             latest_values["w"],
#             latest_values["x"],
#             latest_values["y"],
#             latest_values["z"]
#         )

#         q = normalize(raw_q)

#         # Ignore invalid startup samples.
#         if q is None:
#             continue

#         valid_updates += 1

#         now = time.monotonic()
#         elapsed = now - start_time

#         # ----------------------------------------------------
#         # STAGE 1: WARM-UP
#         # ----------------------------------------------------

#         if elapsed < WARMUP_DURATION:

#             warmup_samples.append(q)

#         # ----------------------------------------------------
#         # STAGE 2: CALIBRATION
#         # ----------------------------------------------------

#         elif not calibration_complete:

#             calibration_samples.append(q)

#             if len(calibration_samples) > 0:
#                 calibration_elapsed = elapsed - WARMUP_DURATION

#                 if calibration_elapsed >= CALIBRATION_DURATION:

#                     reference_quaternion = average_quaternions(
#                         calibration_samples
#                     )

#                     if reference_quaternion is None:
#                         raise RuntimeError(
#                             "Could not calculate calibration reference."
#                         )

#                     calibration_complete = True

#                     print("\n===================================")
#                     print("CALIBRATION COMPLETE")
#                     print("Reference quaternion:")
#                     print(reference_quaternion)
#                     print("===================================\n")

#         # ----------------------------------------------------
#         # STAGE 3: CALIBRATED ORIENTATION
#         # ----------------------------------------------------

#         if calibration_complete:

#             q_reference_inverse = quaternion_conjugate(
#                 reference_quaternion
#             )

#             q_relative = normalize(
#                 quaternion_multiply(
#                     q_reference_inverse,
#                     q
#                 )
#             )

#             angles = quaternion_to_euler(q_relative)

#             if angles is not None:

#                 roll, pitch, yaw = angles

#                 roll = apply_deadband(
#                     roll, ZERO_DEADBAND_DEG
#                 )

#                 pitch = apply_deadband(
#                     pitch, ZERO_DEADBAND_DEG
#                 )

#                 yaw = apply_deadband(
#                     yaw, ZERO_DEADBAND_DEG
#                 )

#         # ----------------------------------------------------
#         # PRINT STATUS
#         # ----------------------------------------------------

#         if now - last_print_time >= PRINT_INTERVAL:

#             print(f"\nTime: {elapsed:.1f} seconds")

#             if not calibration_complete:

#                 if elapsed < WARMUP_DURATION:

#                     remaining = WARMUP_DURATION - elapsed

#                     print("STAGE: WARM-UP")
#                     print(
#                         f"Waiting for orientation to settle: "
#                         f"{remaining:.1f} seconds remaining"
#                     )

#                 else:

#                     remaining = (
#                         CALIBRATION_DURATION
#                         - (elapsed - WARMUP_DURATION)
#                     )

#                     print("STAGE: CALIBRATION")
#                     print(
#                         f"Collecting neutral reference: "
#                         f"{max(0.0, remaining):.1f} seconds remaining"
#                     )

#             print("\nRaw Quaternion:")
#             print(f"W: {q[0]: .4f}")
#             print(f"X: {q[1]: .4f}")
#             print(f"Y: {q[2]: .4f}")
#             print(f"Z: {q[3]: .4f}")

#             if latest_accuracy is not None:
#                 print("Orientation accuracy:", latest_accuracy)

#             if calibration_complete:

#                 print("\nRelative Quaternion:")
#                 print(f"W: {q_relative[0]: .4f}")
#                 print(f"X: {q_relative[1]: .4f}")
#                 print(f"Y: {q_relative[2]: .4f}")
#                 print(f"Z: {q_relative[3]: .4f}")

#                 print("\nCalibrated Euler Angles:")
#                 print(f"Roll : {roll: .2f} degrees")
#                 print(f"Pitch: {pitch: .2f} degrees")
#                 print(f"Yaw  : {yaw: .2f} degrees")

#             last_print_time = now

#     print("\nRun duration finished.")
#     print("Valid quaternion updates:", valid_updates)

#     if not calibration_complete:
#         print("WARNING: Calibration was not completed.")

# finally:

#     try:
#         base.Stop_Callback()
#     except Exception as error:
#         print("Stop warning:", error)

#     print("\nData collection stopped.")



import time
import math

import AeroPy.TrignoBase as tb


# ============================================================
# SETTINGS
# ============================================================

WARMUP_DURATION = 30.0
CALIBRATION_DURATION = 5.0
PRINT_INTERVAL = 1.0
RUN_DURATION = 300.0

ZERO_DEADBAND_DEG = 2.0

sensor_index = 0


# ============================================================
# DELSYS DATA HANDLER
# ============================================================

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


# ============================================================
# QUATERNION FUNCTIONS
# Format: [w, x, y, z]
# ============================================================

def normalize(q):
    norm = math.sqrt(sum(v * v for v in q))

    if norm < 1e-8:
        return None

    return tuple(v / norm for v in q)


def quaternion_conjugate(q):
    w, x, y, z = q
    return (w, -x, -y, -z)


def quaternion_multiply(q1, q2):
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2

    return (
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2
    )


def average_quaternions(samples):
    if not samples:
        return None

    reference = samples[0]
    total = [0.0, 0.0, 0.0, 0.0]

    for q in samples:

        # q and -q represent the same orientation.
        if sum(a*b for a, b in zip(reference, q)) < 0:
            q = tuple(-v for v in q)

        for i in range(4):
            total[i] += q[i]

    return normalize(total)


def quaternion_to_euler(q):

    q = normalize(q)

    if q is None:
        return None

    w, x, y, z = q

    # Mathematical Roll
    sin_roll = 2.0 * (w*x + y*z)
    cos_roll = 1.0 - 2.0 * (x*x + y*y)

    roll = math.atan2(sin_roll, cos_roll)

    # Mathematical Pitch
    sin_pitch = 2.0 * (w*y - z*x)
    sin_pitch = max(-1.0, min(1.0, sin_pitch))

    pitch = math.asin(sin_pitch)

    # Mathematical Yaw
    sin_yaw = 2.0 * (w*z + x*y)
    cos_yaw = 1.0 - 2.0 * (y*y + z*z)

    yaw = math.atan2(sin_yaw, cos_yaw)

    return tuple(
        math.degrees(a)
        for a in (roll, pitch, yaw)
    )


def apply_deadband(angle, threshold):

    if abs(angle) <= threshold:
        return 0.0

    return angle


# ============================================================
# CONNECT TO DELSYS
# ============================================================

base = tb.TrignoBase(DataHandler())

try:

    print("Connecting to Delsys...")

    base.Connect_Callback()
    base.scan_callback(LinkController())

    if not base.sensors:
        raise RuntimeError("No sensors found.")

    sensor = base.sensors[sensor_index]

    print("Connected sensor:", sensor.name)

    # --------------------------------------------------------
    # SELECT OR 16 BITS MODE
    # --------------------------------------------------------

    modes = list(base.getSampleModes(sensor_index))

    selected_index = next(
        (
            i for i, mode in enumerate(modes)
            if "16" in str(mode).lower()
            and (
                "or" in str(mode).lower()
                or "orientation" in str(mode).lower()
            )
        ),
        None
    )

    if selected_index is None:
        raise RuntimeError("OR 16 bits mode not found.")

    selected_mode = modes[selected_index]

    base.setSampleMode(sensor_index, selected_mode)
    base.set_sensors_list()

    sensor = base.sensors[sensor_index]

    print("Selected mode:", selected_mode)

    # --------------------------------------------------------
    # FIND QUATERNION CHANNELS
    # --------------------------------------------------------

    quaternion_channels = {}
    accuracy_guid = None

    for channel in sensor.channels:

        guid = str(channel.guid).lower()
        name = channel.name.upper()

        if "ORIENTATION W" in name:
            quaternion_channels["w"] = guid

        elif "ORIENTATION X" in name:
            quaternion_channels["x"] = guid

        elif "ORIENTATION Y" in name:
            quaternion_channels["y"] = guid

        elif "ORIENTATION Z" in name:
            quaternion_channels["z"] = guid

        elif "ORIENTATION ACCURACY" in name:
            accuracy_guid = guid

    if len(quaternion_channels) != 4:
        raise RuntimeError(
            "Could not find all quaternion channels."
        )

    guid_to_component = {
        guid: component
        for component, guid in quaternion_channels.items()
    }

    print("Quaternion channels found.")

    # --------------------------------------------------------
    # START COLLECTION
    # --------------------------------------------------------

    base.Start_Callback(False, False, None, None)

    print("\nData collection started.")
    print("Keep the sensor attached to the patient's arm.")
    print("Keep the arm in neutral position during calibration.")

    latest_values = {}
    latest_accuracy = None

    calibration_samples = []

    reference_quaternion = None

    start_time = time.monotonic()
    last_print_time = 0.0

    valid_updates = 0
    calibration_complete = False

    # ========================================================
    # MAIN LOOP
    # ========================================================

    while time.monotonic() - start_time < RUN_DURATION:

        if not base.TrigBase.CheckYTDataQueue():
            time.sleep(0.005)
            continue

        data = base.TrigBase.PollYTDataByString()

        new_quaternion_data = False

        # ----------------------------------------------------
        # READ LATEST CHANNEL VALUES
        # ----------------------------------------------------

        for guid in data.Keys:

            guid_key = str(guid).lower()

            for point in data[guid]:

                value = float(point.Item2)

                if guid_key in guid_to_component:

                    component = guid_to_component[guid_key]

                    latest_values[component] = value
                    new_quaternion_data = True

                elif accuracy_guid and guid_key == accuracy_guid:

                    latest_accuracy = value

        if not new_quaternion_data:
            continue

        if not all(
            key in latest_values
            for key in ("w", "x", "y", "z")
        ):
            continue

        raw_q = (
            latest_values["w"],
            latest_values["x"],
            latest_values["y"],
            latest_values["z"]
        )

        q = normalize(raw_q)

        # Ignore invalid startup samples.
        if q is None:
            continue

        valid_updates += 1

        now = time.monotonic()
        elapsed = now - start_time

        # ----------------------------------------------------
        # STAGE 1: WARM-UP
        # ----------------------------------------------------

        if elapsed < WARMUP_DURATION:

            pass

        # ----------------------------------------------------
        # STAGE 2: CALIBRATION
        # ----------------------------------------------------

        elif not calibration_complete:

            calibration_samples.append(q)

            calibration_elapsed = elapsed - WARMUP_DURATION

            if calibration_elapsed >= CALIBRATION_DURATION:

                reference_quaternion = average_quaternions(
                    calibration_samples
                )

                if reference_quaternion is None:
                    raise RuntimeError(
                        "Could not calculate calibration reference."
                    )

                calibration_complete = True

                print("\n===================================")
                print("CALIBRATION COMPLETE")
                print("Reference quaternion:")
                print(reference_quaternion)
                print("===================================\n")

        # ----------------------------------------------------
        # STAGE 3: CALIBRATED ORIENTATION
        # ----------------------------------------------------

        if calibration_complete:

            q_reference_inverse = quaternion_conjugate(
                reference_quaternion
            )

            q_relative = normalize(
                quaternion_multiply(
                    q_reference_inverse,
                    q
                )
            )

            angles = quaternion_to_euler(q_relative)

            if angles is not None:

                # Original mathematical Euler outputs
                mathematical_roll, mathematical_pitch, yaw = angles

                # ------------------------------------------------
                # PHYSICAL AXIS MAPPING
                # Swap Roll and Pitch
                # ------------------------------------------------

                roll = mathematical_pitch
                pitch = mathematical_roll

                # Apply deadband
                roll = apply_deadband(
                    roll,
                    ZERO_DEADBAND_DEG
                )

                pitch = apply_deadband(
                    pitch,
                    ZERO_DEADBAND_DEG
                )

                yaw = apply_deadband(
                    yaw,
                    ZERO_DEADBAND_DEG
                )

        # ----------------------------------------------------
        # PRINT STATUS
        # ----------------------------------------------------

        if now - last_print_time >= PRINT_INTERVAL:

            print(f"\nTime: {elapsed:.1f} seconds")

            if not calibration_complete:

                if elapsed < WARMUP_DURATION:

                    remaining = WARMUP_DURATION - elapsed

                    print("STAGE: WARM-UP")
                    print(
                        f"Waiting for orientation to settle: "
                        f"{remaining:.1f} seconds remaining"
                    )

                else:

                    remaining = (
                        CALIBRATION_DURATION
                        - (elapsed - WARMUP_DURATION)
                    )

                    print("STAGE: CALIBRATION")
                    print(
                        f"Collecting neutral reference: "
                        f"{max(0.0, remaining):.1f} seconds remaining"
                    )

            print("\nRaw Quaternion:")
            print(f"W: {q[0]: .4f}")
            print(f"X: {q[1]: .4f}")
            print(f"Y: {q[2]: .4f}")
            print(f"Z: {q[3]: .4f}")

            if latest_accuracy is not None:
                print("Orientation accuracy:", latest_accuracy)

            if calibration_complete:

                print("\nRelative Quaternion:")
                print(f"W: {q_relative[0]: .4f}")
                print(f"X: {q_relative[1]: .4f}")
                print(f"Y: {q_relative[2]: .4f}")
                print(f"Z: {q_relative[3]: .4f}")

                print("\nCalibrated Euler Angles:")
                print(f"Roll : {roll: .2f} degrees")
                print(f"Pitch: {pitch: .2f} degrees")
                print(f"Yaw  : {yaw: .2f} degrees")

            last_print_time = now

    print("\nRun duration finished.")
    print("Valid quaternion updates:", valid_updates)

    if not calibration_complete:
        print("WARNING: Calibration was not completed.")

finally:

    try:
        base.Stop_Callback()
    except Exception as error:
        print("Stop warning:", error)

    print("\nData collection stopped.")



