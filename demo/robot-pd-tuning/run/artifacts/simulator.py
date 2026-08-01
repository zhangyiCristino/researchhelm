"""Deterministic 2-DOF planar arm point-reaching simulator (standard library only).

This is a deliberately tiny simulator used by the ResearchHelm demo run:
PD position control of a two-link planar arm toward a fixed target. The
dynamics are unit-inertia with viscous damping; the controller is four
gains (kp1, kd1, kp2, kd2). Everything is deterministic for a fixed seed.

Run directly to see the default configuration:
    python simulator.py
"""

import math
import random
import sys

L1 = 0.6
L2 = 0.5
TARGET = (0.8, 0.6)
DT = 0.01
DURATION = 3.0
ENERGY_WEIGHT = 0.05


def _inverse_kinematics(tx: float, ty: float):
    """Return joint angles (q1, q2) that place the end effector at (tx, ty).

    Elbow-down solution; returns None when the target is out of reach.
    """
    distance = math.hypot(tx, ty)
    if distance > L1 + L2 or distance < abs(L1 - L2):
        return None
    cos_q2 = (distance * distance - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
    q2 = -math.acos(max(-1.0, min(1.0, cos_q2)))
    q1 = math.atan2(ty, tx) - math.atan2(L2 * math.sin(q2), L1 + L2 * math.cos(q2))
    return q1, q2


def simulate(
    kp1: float,
    kd1: float,
    kp2: float,
    kd2: float,
    target: tuple[float, float] = TARGET,
    seed: int = 7,
    dt: float = DT,
    duration: float = DURATION,
    energy_weight: float = ENERGY_WEIGHT,
    trajectory: bool = False,
) -> dict:
    """Simulate PD control for ``duration`` seconds; return metrics dict.

    With ``trajectory=True`` the result also includes a downsampled end-
    effector trajectory as ``trajectory`` (a list of (x, y) tuples).
    """
    desired = _inverse_kinematics(*target)
    if desired is None:
        raise ValueError(f"target {target} out of reach")
    q1_target, q2_target = desired

    rng = random.Random(seed)
    q1 = rng.uniform(-0.5, 0.5)
    q2 = rng.uniform(-0.5, 0.5)
    dq1 = 0.0
    dq2 = 0.0

    steps = int(duration / dt)
    energy = 0.0
    sampled = []
    for step in range(steps):
        e1 = q1_target - q1
        e2 = q2_target - q2
        tau1 = kp1 * e1 - kd1 * dq1
        tau2 = kp2 * e2 - kd2 * dq2
        ddq1 = tau1 - 0.1 * dq1
        ddq2 = tau2 - 0.1 * dq2
        dq1 += ddq1 * dt
        dq2 += ddq2 * dt
        q1 += dq1 * dt
        q2 += dq2 * dt
        energy += tau1 * tau1 + tau2 * tau2
        if trajectory and step % 10 == 0:
            sampled.append(
                (
                    round(L1 * math.cos(q1) + L2 * math.cos(q1 + q2), 6),
                    round(L1 * math.sin(q1) + L2 * math.sin(q1 + q2), 6),
                )
            )

    x = L1 * math.cos(q1) + L2 * math.cos(q1 + q2)
    y = L1 * math.sin(q1) + L2 * math.sin(q1 + q2)
    distance = math.hypot(x - target[0], y - target[1])
    energy_cost = energy * dt
    cost = distance + energy_weight * energy_cost
    result = {
        "x": round(x, 6),
        "y": round(y, 6),
        "distance": round(distance, 6),
        "energy": round(energy_cost, 6),
        "cost": round(cost, 6),
        "q1_final": round(q1, 6),
        "q2_final": round(q2, 6),
    }
    if trajectory:
        result["trajectory"] = sampled
    return result


def main() -> int:
    result = simulate(2.0, 0.8, 2.0, 0.8)
    print(f"target={TARGET} terminal_distance={result['distance']} cost={result['cost']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
