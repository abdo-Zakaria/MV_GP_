"""
Delsys Trigno sensor connection, mode configuration, channel mapping,
and background data acquisition.

If sensors are not detected, fail to connect, or stop streaming, inspect this module.

Preserves the exact AeroPy integration from rehab_vision_delsys_ukf_Final.py:
- Connects to TrignoBase and scans for paired sensors.
- Configures Sensor 1 (index 0) and Sensor 2 (index 1) into 'OR 16 bits (74 Hz)' mode.
- Maps the four quaternion channels: ORIENTATION W, X, Y, Z.
- Polls YT packets in a background worker thread and sends raw (W, X, Y, Z)
  quaternions to CalibrationManager.
- Enforces the 1.0-second staleness check when reading sensor angles.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from rehab_app.calibration import (
    CalibratedOrientation,
    CalibrationManager,
    Quaternion,
    normalize,
)
from rehab_app.config import (
    PROJECT_ROOT,
    RECORD_SECONDS,
    SENSOR1_INDEX,
    SENSOR2_INDEX,
    SENSOR_STALE_SECONDS,
)

logger = logging.getLogger(__name__)


def _import_trigno_base() -> Any:
    """
    Import AeroPy.TrignoBase safely from any working directory.
    AeroPy/TrignoBase.py loads 'resources\\DelsysAPI' relative to the current
    working directory, so we temporarily switch to PROJECT_ROOT during import.
    """
    root_str = str(PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    prev_cwd = os.getcwd()
    try:
        os.chdir(root_str)
        from AeroPy import TrignoBase as tb
        return tb
    finally:
        try:
            os.chdir(prev_cwd)
        except OSError:
            pass


class DataHandler:
    """Minimal data handler required by AeroPy.TrignoBase (enables YT streaming)."""
    streamYTData = True
    pauseFlag = False
    EMGplot = None

    class Data:
        packetCount = 0
        allcollectiondata: List[Any] = []

    DataHandler = Data()

    def threadManager(self, start_trigger: bool, stop_trigger: bool) -> None:
        pass


class LinkController:
    """Minimal link controller required by AeroPy.TrignoBase.scan_callback()."""
    use_ant = False

    def get_device_types(self) -> List[str]:
        return []


def find_or_mode(base: Any, index: int) -> str:
    """
    Find the 'OR 16 bits' orientation sample mode for the sensor at `index`.
    Raises RuntimeError if the sensor does not support 16-bit orientation mode.
    """
    modes = [str(m) for m in base.getSampleModes(index)]
    mode = next(
        (
            m
            for m in modes
            if "16" in m.lower() and ("or" in m.lower() or "orientation" in m.lower())
        ),
        None,
    )
    if mode is None:
        raise RuntimeError(f"OR 16 bits mode not found for sensor {index}. Modes: {modes}")
    return mode


def find_quaternion_channels(sensor: Any) -> Tuple[Dict[str, str], Optional[str]]:
    """
    Find the channel GUIDs for 'ORIENTATION W', 'ORIENTATION X', 'ORIENTATION Y',
    and 'ORIENTATION Z' (plus optional 'ORIENTATION ACCURACY') on a Trigno sensor.
    """
    result: Dict[str, str] = {}
    accuracy: Optional[str] = None
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


@dataclass
class SensorReading:
    """Stores the latest raw quaternion and calibrated angles for a single Delsys IMU."""
    sensor_number: int
    sensor_name: str = ""
    pair_number: int = 0
    mode: str = ""
    pitch: Optional[float] = None
    yaw: Optional[float] = None
    raw_quaternion: Optional[Quaternion] = None
    relative_quaternion: Optional[Quaternion] = None
    mathematical_roll_deg: Optional[float] = None
    mathematical_pitch_deg: Optional[float] = None
    mathematical_yaw_deg: Optional[float] = None
    calibration_phase: str = "Waiting"
    time: float = 0.0
    ready: bool = False


class DelsysSensorManager:
    """
    Manages the Delsys Trigno connection, background data polling thread,
    and thread-safe access to the latest sensor readings.
    """

    def __init__(
        self,
        calibration_manager: CalibrationManager,
        sensor1_index: int = SENSOR1_INDEX,
        sensor2_index: int = SENSOR2_INDEX,
        sensor_stale_seconds: float = SENSOR_STALE_SECONDS,
        record_seconds: float = RECORD_SECONDS,
        on_sample_callback: Optional[Callable[[CalibratedOrientation], None]] = None,
    ) -> None:
        self.calibration_manager = calibration_manager
        self.sensor1_index = int(sensor1_index)
        self.sensor2_index = int(sensor2_index)
        self.sensor_stale_seconds = float(sensor_stale_seconds)
        self.record_seconds = float(record_seconds)
        self.on_sample_callback = on_sample_callback

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._base: Any = None
        self._sensor_data: Dict[int, SensorReading] = {
            1: SensorReading(sensor_number=1),
            2: SensorReading(sensor_number=2),
        }
        self._sensor_status: str = "Starting"

    def reset_state(self) -> None:
        """Clear latest pitch/yaw readings while keeping hardware metadata."""
        with self._lock:
            for num, prev in list(self._sensor_data.items()):
                self._sensor_data[num] = SensorReading(
                    sensor_number=num,
                    sensor_name=prev.sensor_name,
                    pair_number=prev.pair_number,
                    mode=prev.mode,
                )

    def set_status(self, sensor: Optional[str] = None) -> None:
        if sensor is not None:
            with self._lock:
                self._sensor_status = str(sensor)

    def get_status(self) -> Dict[str, str]:
        """Return current sensor connection status and calibration status."""
        with self._lock:
            sensor_stat = self._sensor_status
        return {
            "sensor": sensor_stat,
            "calibration": self.calibration_manager.get_status_text(),
        }

    def set_sensor(
        self,
        number: int,
        pitch: Optional[float],
        yaw: Optional[float],
        timestamp: float,
        calibrated_orientation: Optional[CalibratedOrientation] = None,
    ) -> None:
        """Store the latest calibrated pitch and yaw for sensor `number`."""
        with self._lock:
            reading = self._sensor_data.setdefault(number, SensorReading(sensor_number=number))
            reading.pitch = pitch
            reading.yaw = yaw
            reading.time = float(timestamp)
            reading.ready = pitch is not None and yaw is not None
            if calibrated_orientation is not None:
                reading.raw_quaternion = calibrated_orientation.raw_quaternion
                reading.relative_quaternion = calibrated_orientation.relative_quaternion
                reading.mathematical_roll_deg = calibrated_orientation.mathematical_roll_deg
                reading.mathematical_pitch_deg = calibrated_orientation.mathematical_pitch_deg
                reading.mathematical_yaw_deg = calibrated_orientation.mathematical_yaw_deg
                reading.calibration_phase = calibrated_orientation.phase

    def get_sensor(self, number: int, axis: str, now: Optional[float] = None) -> Optional[float]:
        """
        Read 'pitch' or 'yaw' for sensor `number`.
        Returns None if the sensor is not calibrated yet or if data is older than sensor_stale_seconds.
        """
        snapshot = self.get_reading_snapshot(number, now=now)
        return getattr(snapshot, axis, None)

    def get_reading_snapshot(self, number: int, now: Optional[float] = None) -> SensorReading:
        """Return a thread-safe copy of SensorReading, clearing stale angles if older than 1.0 s."""
        check_time = time.monotonic() if now is None else float(now)
        with self._lock:
            snapshot = replace(self._sensor_data.get(number, SensorReading(sensor_number=number)))
        if not snapshot.ready or (check_time - snapshot.time > self.sensor_stale_seconds):
            snapshot.pitch = None
            snapshot.yaw = None
            snapshot.ready = False
        return snapshot

    def get_sensor_metadata(self) -> Dict[int, Dict[str, Any]]:
        with self._lock:
            return {
                num: {
                    "name": r.sensor_name,
                    "pair_number": r.pair_number,
                    "mode": r.mode,
                    "ready": r.ready,
                }
                for num, r in self._sensor_data.items()
            }

    def pair_sensor(self, pair_number: int) -> Any:
        """Initiate sensor pairing on the Delsys receiver for `pair_number`."""
        if self._base is None:
            tb = _import_trigno_base()
            self._base = tb.TrignoBase(DataHandler())
            self._base.Connect_Callback()
        self._base.pairnumber = int(pair_number)
        return self._base.Pair_Callback()

    def inject_quaternion_sample(
        self,
        sensor_number: int,
        raw_q: Sequence[float],
        timestamp: Optional[float] = None,
    ) -> Optional[CalibratedOrientation]:
        """
        Pass a raw (W, X, Y, Z) quaternion sample through CalibrationManager
        and update the latest sensor reading. Used by both live polling and simulation.
        """
        ts = time.monotonic() if timestamp is None else float(timestamp)
        cal = self.calibration_manager.process_quaternion(sensor_number, raw_q, ts)
        if cal is None:
            return None

        if cal.is_calibrated and cal.phase == "active":
            self.set_sensor(sensor_number, cal.imu_pitch_deg, cal.imu_yaw_deg, ts, cal)
        else:
            with self._lock:
                r = self._sensor_data.setdefault(sensor_number, SensorReading(sensor_number=sensor_number))
                r.raw_quaternion = cal.raw_quaternion
                r.calibration_phase = cal.phase
                r.time = ts

        if self.on_sample_callback is not None:
            try:
                self.on_sample_callback(cal)
            except Exception as exc:
                logger.warning("on_sample_callback error: %s", exc)
        return cal

    def start_worker(self) -> None:
        """Start the background Delsys acquisition thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._sensor_worker_loop,
            name="DelsysSensorWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop_worker(self, timeout: float = 5.0) -> None:
        """Stop the background Delsys acquisition thread and wait for cleanup."""
        self._stop_event.set()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        self._worker_thread = None

    def _sensor_worker_loop(self) -> None:
        """
        Background worker that connects to Delsys TrignoBase, configures both sensors
        in OR 16 bits mode, and continuously polls raw W, X, Y, Z quaternion packets.
        Matches sensor_worker() in rehab_vision_delsys_ukf_Final.py.
        """
        base = None
        try:
            tb = _import_trigno_base()
            base = tb.TrignoBase(DataHandler())
            self._base = base
            print("Connecting to Delsys...")
            base.Connect_Callback()
            base.scan_callback(LinkController())
            if not base.sensors:
                raise RuntimeError("No Delsys sensors found.")

            indexes = {1: self.sensor1_index, 2: self.sensor2_index}
            for number, idx in indexes.items():
                if idx >= len(base.sensors):
                    raise RuntimeError(f"Sensor {number}, index {idx}, not found.")
                mode = find_or_mode(base, idx)
                base.setSampleMode(idx, mode)
                print(f"Sensor {number}: {base.sensors[idx].name} -> {mode}")

            base.set_sensors_list()

            guid_map: Dict[str, Tuple[int, str]] = {}
            for number, idx in indexes.items():
                sensor_obj = base.sensors[idx]
                with self._lock:
                    r = self._sensor_data.setdefault(number, SensorReading(sensor_number=number))
                    r.sensor_name = str(sensor_obj.name)
                    r.pair_number = int(sensor_obj.pair_number)
                    r.mode = str(sensor_obj.mode)
                channels, _accuracy = find_quaternion_channels(sensor_obj)
                for component, guid in channels.items():
                    guid_map[guid] = (number, component)

            base.Start_Callback(False, False, None, None)
            start = time.monotonic()
            self.calibration_manager.start(start)
            self.set_status(sensor="Delsys streaming")
            print(
                f"Keep both sensors stationary for {self.calibration_manager.warmup_seconds:.0f} s "
                f"warm-up + {self.calibration_manager.calibration_seconds:.0f} s neutral calibration."
            )

            latest: Dict[int, Dict[str, float]] = {1: {}, 2: {}}

            while not self._stop_event.is_set() and (time.monotonic() - start) < self.record_seconds:
                if not base.TrigBase.CheckYTDataQueue():
                    time.sleep(0.003)
                    continue
                raw = base.TrigBase.PollYTDataByString()
                received_at = time.monotonic()

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

                for number in (1, 2):
                    vals = latest[number]
                    if not all(k in vals for k in "wxyz"):
                        continue
                    q = normalize(tuple(vals[k] for k in "wxyz"))
                    if q is None:
                        continue
                    self.inject_quaternion_sample(number, q, timestamp=received_at)

        except Exception as exc:
            print("Delsys error:", exc)
            logger.error("Delsys error: %s", exc)
            self.set_status(sensor=f"DELSYS ERROR: {exc}")
        finally:
            if base is not None:
                try:
                    base.Stop_Callback()
                except Exception as exc:
                    print("Delsys stop warning:", exc)
            self._base = None
