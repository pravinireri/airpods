import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = Path(__file__).resolve().parents[2] / "data" / "sensor_logger.jsonl"
last_arrival = {}
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

        head = [
            sample for sample in payload
            if isinstance(sample, dict)
            and sample.get("name") == "headphone"
        ]
        latest = max(head, key=lambda sample: sample["time"]) if head else {}
        values = latest.get("values", {})
        key = (message.get("deviceId"), message.get("sessionId"))

        with lock:
            now = time.monotonic()
            previous = last_arrival.get(key)
            gap = (
                "first" if previous is None
                else f"{1000 * (now - previous):.0f} ms"
            )
            last_arrival[key] = now

            record = {
                "received_monotonic_s": now,
                "received_unix_ns": time.time_ns(),
                "message": message,
            }
            with LOG.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record) + "\n")

            print(
                f"headphone={len(head)}  batch_gap={gap}  "
                f"yaw={values.get('yaw')}  pitch={values.get('pitch')}",
                flush=True,
            )

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print("receiver running on port 8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Receiver).serve_forever()