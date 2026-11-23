"""calculate a robot's position relative to the user's head."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RelativePosition:
    distance_m: float
    bearing_rad: float | None


def relative_robot(user_xy, robot_xy, head_yaw):
    dx = robot_xy[0] - user_xy[0]
    dy = robot_xy[1] - user_xy[1]

    distance = math.hypot(dx, dy)

    # direction is undefined if both positions are effectively identical.
    if distance < 1e-6:
        return RelativePosition(distance, None)

    world_bearing = math.atan2(dy, dx)

    # subtract head direction and wrap into [-pi, pi).
    bearing = (world_bearing - head_yaw + math.pi) % math.tau - math.pi

    return RelativePosition(distance, bearing)