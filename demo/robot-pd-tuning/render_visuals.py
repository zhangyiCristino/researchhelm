"""Render SVG visualizations for the robot PD-tuning demo (standard library only).

Reads ``run/artifacts/results.json`` and produces ``visuals.svg``: the best
final arm pose with the end-effector trajectory and target on the left, and
the per-trial cost bars (kept vs discarded) on the right.

Usage:
    python demo/robot-pd-tuning/render_visuals.py
"""

import json
import math
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
RESULTS = DEMO_DIR / "run" / "artifacts" / "results.json"
OUT = DEMO_DIR / "visuals.svg"

L1 = 0.6
L2 = 0.5

# Arm view geometry.
ORIGIN_X = 110
ORIGIN_Y = 330
SCALE = 250.0

# Cost bars geometry.
BARS_X = 470
BARS_Y_TOP = 90
BARS_Y_BOTTOM = 330
BAR_W = 26
BAR_GAP = 5


def forward(q1: float, q2: float) -> tuple[float, float]:
    x = L1 * math.cos(q1) + L2 * math.cos(q1 + q2)
    y = L1 * math.sin(q1) + L2 * math.sin(q1 + q2)
    return x, y


def w2s(x: float, y: float) -> tuple[float, float]:
    return ORIGIN_X + x * SCALE, ORIGIN_Y - y * SCALE


def arm_segment(x1, y1, x2, y2, color, width, dash=None):
    sx1, sy1 = w2s(x1, y1)
    sx2, sy2 = w2s(x2, y2)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{sx1:.1f}" y1="{sy1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" '
        f'stroke="{color}" stroke-width="{width}"{dash_attr}/>'
    )


def build_arm_view(data: dict) -> list[str]:
    best = data["best"]
    params = best["params"]
    metrics = best["metrics"]
    q1, q2 = metrics["q1_final"], metrics["q2_final"]
    elbow = (L1 * math.cos(q1), L1 * math.sin(q1))
    tip = (metrics["x"], metrics["y"])
    target = (0.8, 0.6)

    # Re-run the best configuration to obtain the deterministic trajectory.
    import random
    import sys
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "demo_simulator", DEMO_DIR / "simulator.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_simulator"] = module
    spec.loader.exec_module(module)
    traced = module.simulate(**params, trajectory=True)
    points = traced["trajectory"]

    lines = [
        '<g id="arm-view">',
        '<text x="10" y="24" font-family="sans-serif" font-size="14" fill="#17212b">Best trial: end-effector trajectory (deterministic)</text>',
        '<text x="10" y="42" font-family="sans-serif" font-size="11" fill="#57606a">'
        f"kp1={params['kp1']} kd1={params['kd1']}  kp2={params['kp2']} kd2={params['kd2']}  "
        f"terminal distance={metrics['distance']}",
        "</text>",
    ]

    # Trajectory polyline.
    if points:
        path = " ".join(
            f"{w2s(x, y)[0]:.1f},{w2s(x, y)[1]:.1f}" for x, y in points
        )
        lines.append(
            f'<polyline points="{path}" fill="none" stroke="#d4a72c" '
            'stroke-width="2" stroke-linejoin="round" opacity="0.85"/>'
        )

    # Base, arm segments, target, tip.
    lines.append(f'<circle cx="{ORIGIN_X:.1f}" cy="{ORIGIN_Y:.1f}" r="6" fill="#17212b"/>')
    lines.append(
        arm_segment(0, 0, elbow[0], elbow[1], "#8b949e", 10, dash="4,3")
    )
    lines.append(
        arm_segment(elbow[0], elbow[1], tip[0], tip[1], "#8b949e", 10, dash="4,3")
    )
    lines.append(
        arm_segment(0, 0, elbow[0], elbow[1], "#0969da", 6)
    )
    lines.append(
        arm_segment(elbow[0], elbow[1], tip[0], tip[1], "#0969da", 6)
    )
    tx, ty = w2s(*target)
    lines.append(
        f'<path d="M {tx-8:.1f} {ty-8:.1f} L {tx+8:.1f} {ty+8:.1f} '
        f'M {tx+8:.1f} {ty-8:.1f} L {tx-8:.1f} {ty+8:.1f}" '
        'stroke="#cf222e" stroke-width="3"/>'
    )
    lines.append(
        f'<circle cx="{w2s(*tip)[0]:.1f}" cy="{w2s(*tip)[1]:.1f}" r="5" fill="#0969da"/>'
    )

    # Legend.
    lines.append(
        '<g font-family="sans-serif" font-size="11" fill="#57606a">'
        '<rect x="20" y="380" width="14" height="4" fill="#0969da"/><text x="40" y="385">final pose</text>'
        '<rect x="110" y="380" width="14" height="4" fill="#d4a72c"/><text x="130" y="385">trajectory</text>'
        '<rect x="215" y="380" width="14" height="4" fill="#cf222e"/><text x="235" y="385">target (0.8, 0.6)</text>'
        "</g>"
    )
    lines.append("</g>")
    return lines


def build_cost_bars(data: dict) -> list[str]:
    trials = data["trial_records"]
    costs = [t["metrics"]["cost"] for t in trials]
    kept = [t["keep"] for t in trials]
    max_cost = max(costs)
    lines = [
        '<g id="cost-bars">',
        '<text x="470" y="24" font-family="sans-serif" font-size="14" fill="#17212b">Cost per trial (lower is better)</text>',
        '<text x="470" y="42" font-family="sans-serif" font-size="11" fill="#57606a">green = kept, gray = discarded</text>',
    ]
    for index, (cost, keep) in enumerate(zip(costs, kept)):
        x = BARS_X + index * (BAR_W + BAR_GAP)
        height = (BARS_Y_BOTTOM - BARS_Y_TOP) * cost / max_cost
        y = BARS_Y_BOTTOM - height
        color = "#1a7f37" if keep else "#d0d7de"
        lines.append(
            f'<rect x="{x}" y="{y:.1f}" width="{BAR_W}" height="{height:.1f}" '
            f'fill="{color}" rx="2"><title>trial {index + 1}: cost {cost}</title></rect>'
        )
        lines.append(
            f'<text x="{x + BAR_W / 2:.1f}" y="{BARS_Y_BOTTOM + 14}" '
            'font-family="sans-serif" font-size="9" fill="#57606a" text-anchor="middle">'
            f"{index + 1}</text>"
        )
    lines.append(
        f'<line x1="{BARS_X - 6}" y1="{BARS_Y_BOTTOM}" x2="{BARS_X + 12 * (BAR_W + BAR_GAP) + 2}" '
        'y2="330" stroke="#57606a" stroke-width="1"/>'
    )
    best = min(trials, key=lambda t: t["metrics"]["cost"])
    lines.append(
        '<g font-family="sans-serif" font-size="11" fill="#1a7f37">'
        f'<text x="470" y="66">best: trial {best["trial"]} — cost {best["metrics"]["cost"]}, '
        f'distance {best["metrics"]["distance"]}</text></g>'
    )
    lines.append("</g>")
    return lines


def main() -> int:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="880" height="420" '
        'viewBox="0 0 880 420" role="img" '
        'aria-label="Robot PD-tuning demo: end-effector trajectory and per-trial cost">',
    ]
    parts += build_arm_view(data)
    parts += build_cost_bars(data)
    parts.append("</svg>")
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"visuals written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
