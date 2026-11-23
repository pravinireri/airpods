import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import argparse

from control import Controller
from sensor_adapter import SensorAdapter

controller = Controller()
controller_key = None

LOG = Path(__file__).resolve().parents[1] / "data" / "sensor_logger.jsonl"
lock = threading.Lock()

PAGE = b"""<!doctype html>
<meta name="viewport" content="width=device-width">
<h2>Audio and sensor check</h2>
<button onclick="play()">Play a quiet 5-second tone</button>
<p>Keep this page open and turn your head. Check the laptop terminal.</p>
<script>
async function play() {
  const ctx = new AudioContext();
  await ctx.resume();
  const tone = ctx.createOscillator();
  const gain = ctx.createGain();
  gain.gain.value = 0.02;
  tone.connect(gain).connect(ctx.destination);
  tone.start();
  tone.stop(ctx.currentTime + 5);
  tone.onended = () => ctx.close();
}
</script>
"""


class Receiver(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):

        global controller, controller_key

        if self.path != "/data":
            self.send_error(404)
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2_000_000:
                raise ValueError("invalid request size")

            message = json.loads(self.rfile.read(size))
            if not isinstance(message, dict):
                raise ValueError("expected JSON object")

            payload = message.get("payload", [])
            if not isinstance(payload, list):
                raise ValueError("expected payload list")
        except (ValueError, UnicodeError):
            self.send_error(400, "expected sensor logger JSON")
            return

        latest = max(head, key=lambda sample: sample["time"]) if head else {}
        values = latest.get("values", {})

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

            samples = adapter.convert(message)
            last_state = None
            clench_count = 0

            for sample in samples:
                key = (adapter.session_key, sample.source)

                if key != controller_key:
                    controller = Controller()
                    controller_key = key

                last_state = controller.update(sample)
                clench_count += int(last_state.clench)

            if samples:
                latest_sample = samples[-1]
                print(
                    f"source={latest_sample.source}  "
                    f"samples={len(samples)}  "
                    f"t={latest_sample.t:.3f}s  "
                    f"calibrating={last_state.calibrating}  "
                    f"yaw={last_state.yaw:.3f}  "
                    f"pitch={last_state.pitch:.3f}  "
                    f"clench_candidate={clench_count}",
                    flush=True,
                )

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--accel-unit",
        choices=("g", "m/s2"),
        required=True,
    )
    args = parser.parse_args()

    adapter = SensorAdapter(acceleration_unit=args.accel_unit)
    LOG.parent.mkdir(parents=True, exist_ok=True)

    print(f"receiver running; input acceleration unit={args.accel_unit}")
    ThreadingHTTPServer(("0.0.0.0", 8000), Receiver).serve_forever()