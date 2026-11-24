"""Receive Sensor Logger batches and serve the latest pose plus an audio page."""

import argparse
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from control import Controller
from sensor_adapter import SensorAdapter
from spatial import relative_robot

USER_XY = (0.0, 0.0)
ROBOT_XY = (2.0, 0.0)
HEAD_YAW_SIGN = 1.0

# Disconnect tolerance for the current ~1-second input batches, not a latency target.
STALE_AFTER_S = 3.0

controller = Controller()
controller_key = None
LOG = Path(__file__).resolve().parents[1] / "data" / "sensor_logger.jsonl"
PAGE_PATH = Path(__file__).with_name("audio.html")
lock = threading.Lock()
last_received_s = None


def empty_state(sequence=0, session_id=None):
    return {
        "sequence": sequence,
        "session_id": session_id,
        "source": None,
        "calibrating": True,
        "sample_t_s": None,
        "head_yaw_rad": None,
        "robot_distance_m": None,
        "robot_bearing_rad": None,
        "batch_samples": 0,
        "batch_interval_s": None,
    }


latest_state = empty_state()


def state_snapshot(now):
    """Caller holds lock. GET requests never refresh the stored receipt time."""
    snapshot = dict(latest_state)
    age = None if last_received_s is None else max(0.0, now - last_received_s)
    if age is None:
        status = "waiting"
    elif age >= STALE_AFTER_S:
        status = "stale"
    elif snapshot["calibrating"]:
        status = "calibrating"
    elif snapshot["robot_bearing_rad"] is None:
        status = "no_direction"
    else:
        status = "ready"
    snapshot.update(
        status=status,
        ready=status == "ready",
        received_age_s=age,
        stale_after_s=STALE_AFTER_S,
    )
    return snapshot


class Receiver(BaseHTTPRequestHandler):
    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A browser may cancel a slow poll or leave the page.

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/state":
            with lock:
                snapshot = state_snapshot(time.monotonic())
            body = json.dumps(snapshot, allow_nan=False).encode("utf-8")
            self.send_body(body, "application/json; charset=utf-8")
        elif path in ("/", "/audio.html"):
            try:
                body = PAGE_PATH.read_bytes()
            except OSError:
                self.send_error(500, "Place audio.html beside reciever.py")
                return
            self.send_body(body, "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        global controller, controller_key, latest_state, last_received_s

        if urlsplit(self.path).path != "/data":
            self.send_error(404)
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2_000_000:
                raise ValueError("invalid request size")
            message = json.loads(self.rfile.read(size))
            if not isinstance(message, dict):
                raise ValueError("expected JSON object")
            if not isinstance(message.get("payload", []), list):
                raise ValueError("expected payload list")
        except (ValueError, UnicodeError):
            self.send_error(400, "expected Sensor Logger JSON")
            return

        with lock:
            now = time.monotonic()
            record = {
                "received_monotonic_s": now,
                "received_unix_ns": time.time_ns(),
                "input_acceleration_unit": adapter.acceleration_unit,
                "message": message,
            }
            with LOG.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record) + "\n")

            old_session = adapter.session_key
            samples = adapter.convert(message)
            if adapter.session_key != old_session:
                # A new recording may first send phone-only data. Discard the old pose now.
                latest_state = empty_state(
                    sequence=latest_state["sequence"] + 1,
                    session_id=adapter.session_key[1],
                )
                last_received_s = None
                controller_key = None

            last_state = None
            clench_count = 0
            for sample in samples:
                key = (adapter.session_key, sample.source)
                if key != controller_key:
                    controller = Controller()
                    controller_key = key
                    last_received_s = None
                last_state = controller.update(sample)
                clench_count += int(last_state.clench)

            if samples:
                sample = samples[-1]
                head_yaw = None
                distance = None
                bearing = None
                if not last_state.calibrating:
                    head_yaw = HEAD_YAW_SIGN * last_state.yaw
                    relative = relative_robot(USER_XY, ROBOT_XY, head_yaw)
                    distance = relative.distance_m
                    bearing = relative.bearing_rad

                interval = None if last_received_s is None else now - last_received_s
                latest_state = {
                    "sequence": latest_state["sequence"] + 1,
                    "session_id": adapter.session_key[1],
                    "source": sample.source,
                    "calibrating": last_state.calibrating,
                    "sample_t_s": sample.t,
                    "head_yaw_rad": head_yaw,
                    "robot_distance_m": distance,
                    "robot_bearing_rad": bearing,
                    "batch_samples": len(samples),
                    "batch_interval_s": interval,
                }
                # Refresh only for accepted, new headphone measurements.
                last_received_s = now

                print(
                    f"source={sample.source}  samples={len(samples)}  "
                    f"t={sample.t:.3f}s  calibrating={last_state.calibrating}  "
                    f"yaw={last_state.yaw:.3f}  pitch={last_state.pitch:.3f}  "
                    f"clench_candidate={clench_count}",
                    flush=True,
                )
                if head_yaw is not None:
                    bearing_text = (
                        "same position" if bearing is None
                        else f"{math.degrees(bearing):+.1f} deg"
                    )
                    print(
                        f"head={math.degrees(head_yaw):+.1f} deg  "
                        f"robot_distance={distance:.2f} m  robot_bearing={bearing_text}",
                        flush=True,
                    )

        self.send_body(b"OK", "text/plain; charset=utf-8")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--accel-unit", choices=("g", "m/s2"), required=True)
    args = parser.parse_args()
    adapter = SensorAdapter(acceleration_unit=args.accel_unit)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not PAGE_PATH.is_file():
        parser.error("make sure audio.html is in processing folder")

    print(f"receiver running; input acceleration unit={args.accel_unit}")
    print("open http://192.168.1.65:8000/ on your phone")
    ThreadingHTTPServer(("0.0.0.0", 8000), Receiver).serve_forever()
