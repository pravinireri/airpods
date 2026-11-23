import argparse
import json
from collections import Counter

from control import Controller
from reciever import LOG
from sensor_adapter import SensorAdapter

parser = argparse.ArgumentParser()
parser.add_argument("--input", default=str(LOG))
parser.add_argument("--accel-unit", choices=("g", "m/s2"), required=True)
args = parser.parse_args()

adapter = SensorAdapter(acceleration_unit=args.accel_unit)
controller = None
controller_key = None
sources = Counter()
total = 0
resets = 0

with open(args.input, encoding="utf-8") as recording:
    for line in recording:
        record = json.loads(line)
        recorded_unit = record.get("input_acceleration_unit")

        if recorded_unit is not None and recorded_unit != args.accel_unit:
            raise ValueError(
                f"Recorded unit is {recorded_unit!r}, "
                f"but --accel-unit is {args.accel_unit!r}"
            )
        samples = adapter.convert(record["message"])

        for sample in samples:
            key = (adapter.session_key, sample.source)
            if key != controller_key:
                controller = Controller()
                controller_key = key
                resets += 1
                print(
                    f"new stream {resets}: "
                    f"source={sample.source}, first_t={sample.t:.6f}s"
                )

            state = controller.update(sample)
            sources[sample.source] += 1
            total += 1

print(f"samples={total}, controller_resets={resets}")
print(f"sources={dict(sources)}")
print(
    f"invalid={adapter.invalid_samples}, "
    f"dropped={adapter.dropped_samples}"
)