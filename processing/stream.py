"""read airpods motion data from the swift bridge"""

from __future__ import annotations

import socket
from dataclasses import dataclass

HOST = "127.0.0.1"
PORT = 9999


@dataclass(frozen = True)
class Sample:
    yaw: float
    pitch: float
    roll: float
    ax: float
    ay: float
    az: float
    rx: float
    ry: float
    rz: float
    t: float


def parse(payload: bytes, t: float | None = None) -> Sample | None:
    """parse single `yaw,pitch,roll,ax,ay,az` datagram. return none if it is malformed."""
    try:
        parts = payload.decode("utf-8").strip().split(",")
        if len(parts) != 10:
            return None
        timestamp, yaw, pitch, roll, ax, ay, az, rx, ry, rz = (float(part) for part in parts)
    except (UnicodeDecodeError, ValueError):
        return None
    return Sample(yaw, pitch, roll, ax, ay, az, rx, ry, rz, timestamp if t is None else t)


class MotionStream:
    """non-blocking UDP reader. one `read` call never waits on the bridge."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        try:
            self.sock.bind((host, port))
        except OSError:
            self.sock.close()
            raise
        self.sock.setblocking(False)
        self.host = host
        self.port = self.sock.getsockname()[1]

    def read(self) -> Sample | None:
        """return the next valid sample, skipping malformed packets."""
        while True:
            try:
                data, _addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                return None
            except (InterruptedError, ConnectionResetError):
                return None
            sample = parse(data)
            if sample is not None:
                return sample

    def drain(self) -> list[Sample]:
        samples: list[Sample] = []
        while True:
            sample = self.read()
            if sample is None:
                return samples
            samples.append(sample)

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> MotionStream:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def open_stream(host: str = HOST, port: int = PORT) -> MotionStream:
    try:
        stream = MotionStream(host, port)
    except OSError as exc:
        raise SystemExit(
            f"can't listen on {host}:{port} ({exc}). stop anything else bound to that port."
        ) from exc
    print(f"listening on {host}:{stream.port}", flush = True)
    return stream