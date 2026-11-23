"""convert sensor logger headphone readings into the existing Sample type."""

import math

from stream import Sample

FIELD_MAP = {
    "yaw": "yaw", "pitch": "pitch", "roll": "roll",
    "ax": "accelerationX", "ay": "accelerationY", "az": "accelerationZ",
    "rx": "rotationRateX", "ry": "rotationRateY", "rz": "rotationRateZ",
}


def finite_number(value):
    if type(value) not in (int, float):
        raise ValueError("Expected a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite number")
    return result


class SensorAdapter:
    def __init__(self, *, acceleration_unit):
        scales = {"g": 1.0, "m/s2": 1.0 / 9.80665}
        if acceleration_unit not in scales:
            raise ValueError("set acceleration_unit to 'g' or 'm/s2'")

        self.acceleration_unit = acceleration_unit
        self._scale = scales[acceleration_unit]
        self.session_key = None
        self._closed_sessions = set()
        self._origin_ns = 0
        self._last_ns = -1
        self.invalid_samples = 0
        self.dropped_samples = 0

    def convert(self, message):
        if not isinstance(message, dict):
            return []

        device = message.get("deviceId")
        session = message.get("sessionId")
        payload = message.get("payload")
        if not (
            isinstance(device, str) and device
            and isinstance(session, str) and session
            and isinstance(payload, list)
        ):
            return []

        key = (device, session)
        if key in self._closed_sessions:
            return []  # delayed packet from an older recording.

        timestamps = [
            row["time"] for row in payload
            if isinstance(row, dict)
            and type(row.get("time")) is int
            and row["time"] > 0
        ]
        if not timestamps:
            self.invalid_samples += sum(
                isinstance(row, dict) and row.get("name") == "headphone"
                for row in payload
            )
            return []

        if key != self.session_key:
            if self.session_key is not None:
                self._closed_sessions.add(self.session_key)
            self.session_key = key
            self._origin_ns = min(timestamps)
            self._last_ns = -1

        candidates = []
        for row in payload:
            if not isinstance(row, dict) or row.get("name") != "headphone":
                continue
            try:
                stamp = row["time"]
                values = row["values"]
                if type(stamp) is not int or stamp <= 0:
                    raise ValueError("Invalid timestamp")
                if not isinstance(values, dict):
                    raise ValueError("Invalid values")
                source = values["devicelocation"]
                if source not in ("left", "right"):
                    raise ValueError("Invalid headphone source")
                numbers = {
                    name: finite_number(values[field])
                    for name, field in FIELD_MAP.items()
                }
            except (KeyError, TypeError, ValueError, OverflowError):
                self.invalid_samples += 1
                continue

            for name in ("ax", "ay", "az"):
                numbers[name] *= self._scale
            candidates.append((stamp, source, numbers))

        samples = []
        for stamp, source, numbers in sorted(candidates, key=lambda row: row[0]):
            if stamp < self._origin_ns or stamp <= self._last_ns:
                self.dropped_samples += 1
                continue
            self._last_ns = stamp
            samples.append(Sample(
                **numbers,
                t=(stamp - self._origin_ns) / 1_000_000_000,
                source=source,
            ))
        return samples