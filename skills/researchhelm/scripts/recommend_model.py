#!/usr/bin/env python3
"""Deterministic model-tier recommendation for ResearchHelm stages.

Scores task complexity on six declared dimensions, applies per-stage minimum
tier floors, and emits a content-free JSON recommendation. The recommendation
is advisory: a human must approve it in a Decision Card before use.

Pure standard library. No network. No credential access. No environment dump.
"""
from __future__ import annotations

import argparse
import json
import sys

SCHEMA_VERSION = "1.0"

TIERS = ("light", "balanced", "frontier")
TIER_RANK = {tier: index for index, tier in enumerate(TIERS)}

DEFAULT_TIER_MODELS = {
    "light": "claude-haiku-4-5",
    "balanced": "claude-sonnet-5",
    "frontier": "claude-opus-5",
}

DIMENSIONS = (
    "novelty",
    "ambiguity",
    "scope",
    "risk",
    "reversibility",
    "safety",
)

STAGES = (
    "RESOURCE_INTAKE",
    "IDEA_SCOUT",
    "GATE_1_IDEA",
    "PREREGISTRATION",
    "GATE_2_PLAN_AND_BUDGET",
    "BUILD",
    "VERIFY",
    "PILOT",
    "GATE_3_FULL_RUN",
    "BOUNDED_EXECUTION",
    "ANALYZE_AND_AUDIT",
    "GATE_4_CLAIMS",
    "PACKAGE",
)

# Minimum tier per stage. Absent stages have no floor and may use light tier.
STAGE_FLOORS = {
    "IDEA_SCOUT": "balanced",
    "GATE_1_IDEA": "balanced",
    "PREREGISTRATION": "balanced",
    "GATE_2_PLAN_AND_BUDGET": "balanced",
    "VERIFY": "frontier",
    "GATE_3_FULL_RUN": "balanced",
    "ANALYZE_AND_AUDIT": "frontier",
    "GATE_4_CLAIMS": "frontier",
}

# Roles that carry their own floor regardless of stage.
ROLE_FLOORS = {
    "verifier": "frontier",
    "anomaly-review": "frontier",
    "builder": "balanced",
}

SCORE_BANDS = ((15, "light"), (35, "balanced"), (60, "frontier"))


def clamp_dimension(name: str, value: int) -> int:
    if not 0 <= value <= 10:
        raise ValueError(f"{name} must be between 0 and 10")
    return value


def score_to_tier(score: int) -> str:
    for threshold, tier in SCORE_BANDS:
        if score <= threshold:
            return tier
    return "frontier"


def resolve_floor(stage: str, role: str | None) -> str | None:
    floors = [STAGE_FLOORS.get(stage)]
    if role:
        floors.append(ROLE_FLOORS.get(role))
    present = [tier for tier in floors if tier]
    if not present:
        return None
    return max(present, key=lambda tier: TIER_RANK[tier])


def apply_floor(tier: str, floor: str | None) -> str:
    if floor is None:
        return tier
    return tier if TIER_RANK[tier] >= TIER_RANK[floor] else floor


def build_rationale(stage: str, role: str | None, score: int,
                    scored_tier: str, final_tier: str,
                    floor: str | None) -> str:
    parts = [f"stage {stage}"]
    if role:
        parts.append(f"role {role}")
    parts.append(f"complexity score {score}/60 maps to {scored_tier}")
    if floor and final_tier != scored_tier:
        parts.append(f"raised to {final_tier} by the {floor} floor")
    elif floor:
        parts.append(f"floor {floor} satisfied")
    else:
        parts.append("no stage floor applies")
    return "; ".join(parts) + "."


def recommend(stage: str, dimensions: dict, role: str | None = None,
              tier_models: dict | None = None) -> dict:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    if role is not None and role not in ROLE_FLOORS:
        raise ValueError(f"unknown role: {role}")

    scores = {name: clamp_dimension(name, int(dimensions[name]))
              for name in DIMENSIONS}
    score = sum(scores.values())
    scored_tier = score_to_tier(score)
    floor = resolve_floor(stage, role)
    final_tier = apply_floor(scored_tier, floor)

    models = dict(DEFAULT_TIER_MODELS)
    if tier_models:
        for tier, model in tier_models.items():
            if tier not in TIERS:
                raise ValueError(f"unknown tier in mapping: {tier}")
            if not isinstance(model, str) or not model.strip():
                raise ValueError(f"model for {tier} must be a non-empty string")
            models[tier] = model

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "model-recommendation",
        "stage": stage,
        "role": role,
        "dimensions": scores,
        "score": score,
        "scored_tier": scored_tier,
        "floor": floor,
        "recommended_tier": final_tier,
        "recommended_model": models[final_tier],
        "tier_models": models,
        "downgrade_allowed": floor is None
        or TIER_RANK[final_tier] > TIER_RANK[floor],
        "requires_human_approval": True,
        "rationale": build_rationale(stage, role, score, scored_tier,
                                     final_tier, floor),
    }


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Recommend a model tier for a ResearchHelm stage.")
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--role", choices=sorted(ROLE_FLOORS))
    for name in DIMENSIONS:
        parser.add_argument(f"--{name}", type=int, default=5,
                            help=f"{name} score 0-10 (default 5)")
    parser.add_argument("--tier-models", type=str,
                        help="JSON object overriding tier-to-model mapping")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    dimensions = {name: getattr(args, name) for name in DIMENSIONS}

    tier_models = None
    if args.tier_models:
        try:
            tier_models = json.loads(args.tier_models)
        except json.JSONDecodeError:
            json.dump({"error": "tier_models is not valid JSON"}, sys.stdout)
            sys.stdout.write("\n")
            return 2
        if not isinstance(tier_models, dict):
            json.dump({"error": "tier_models must be a JSON object"},
                      sys.stdout)
            sys.stdout.write("\n")
            return 2

    try:
        result = recommend(args.stage, dimensions, args.role, tier_models)
    except ValueError as error:
        json.dump({"error": str(error)}, sys.stdout)
        sys.stdout.write("\n")
        return 2

    json.dump(result, sys.stdout, indent=2, sort_keys=True,
              ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
