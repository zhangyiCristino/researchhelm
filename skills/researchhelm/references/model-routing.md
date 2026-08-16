# Model Routing — Adaptive Complexity Governance

ResearchHelm routes research tasks to model tiers based on declared complexity, reversibility, and safety requirements. Cheaper models handle straightforward work; stronger models tackle hard reasoning. Human approval is required for model selection; silence is never approval.

## Tier definitions

Three abstract tiers with default Claude mappings:

- **`light`** — fast, cost-effective for mechanical work. Default: `claude-haiku-4-5`. Suitable for: validation, parsing, data transformation, template rendering, deterministic verification scripts.
- **balanced** — general-purpose reasoning. Default: `claude-sonnet-5`. Suitable for: most stages in the default `pi` workflow, resource triage, idea scouting, experiment design, implementation.
- **frontier** — strongest reasoning for hard, safety-critical, or adversarial verification. Default: `claude-opus-5`. **Mandatory** for: Verifier role in Builder-Verifier split, Gate 4 (claims audit), adversarial verification passes, non-reproducibility diagnosis, anomalous gain review.

Tier-to-model mappings are recorded in `research-brief.json` under `resources.model_tiers`. The agent uses the default Claude mapping unless the human explicitly overrides it in the brief.

## Minimum tier floors

The following stages enforce minimum tiers that cannot be downgraded:

| Stage | Minimum tier | Reason |
|---|---|---|
| Gate 4 (claims audit) | **frontier** | Scientific integrity: retained claims must survive strongest scrutiny. |
| Verifier (Builder-Verifier split) | **frontier** | Adversarial check against Builder's work. |
| Anomalous gain review | **frontier** | Detecting leakage, overfitting, evaluator integrity violations. |
| Idea overlap diligence | **balanced** | Public-work comparison requires nuanced judgment. |
| Preregistration | **balanced** | Experimental design sets constraints for the full run. |
| Gate 1, Gate 2, Gate 3 | **balanced** | Human decision gates require clear evidence synthesis. |

Stages not listed (e.g., deterministic validation scripts, template rendering) may use **light** tier with approval. The agent always recommends a tier; the human may upgrade but never downgrade below the floor.

## Complexity scoring

The deterministic script `scripts/recommend_model.py` scores task complexity on six dimensions (0-10 each, total 0-60):

1. **Novelty** — is the question, data, method, or domain new to the project?
2. **Ambiguity** — are requirements, success criteria, or inputs underspecified?
3. **Scope** — how many files, experiments, or decision branches are involved?
4. **Risk** — does failure waste budget, violate constraints, or break reproducibility?
5. **Reversibility** — can the work be easily undone or re-run?
6. **Safety-criticality** — does it touch credentials, publication, claims, or evaluator integrity?

Scoring maps to tiers:
- `0-15` → **light** (if no floor applies)
- `16-35` → **balanced**
- `36-60` → **frontier**

The script outputs JSON:
```json
{
  "recommended_tier": "balanced",
  "score": 28,
  "floor": "balanced",
  "rationale": "Preregistration stage (minimum balanced) with moderate novelty and ambiguity.",
  "dimensions": {"novelty": 6, "ambiguity": 7, "scope": 3, "risk": 5, "reversibility": 4, "safety": 3}
}
```

## Decision Card integration

When the agent reaches a stage requiring model selection, it:

1. Runs `scripts/recommend_model.py` with stage name, scope estimate, and declared novelty/ambiguity.
2. Issues a Decision Card with:
   - **Recommendation**: tier and mapped model.
   - **Alternatives**: next tier up, or explicit downgrade if above floor (with cost/risk tradeoff).
   - **Evidence**: complexity score breakdown, floor policy, similar past stages.
   - **Resource consequences**: token budget consumed by this tier vs alternatives.
   - **Failure modes**: weaker tier → missed edge cases, false negatives in verification; stronger tier → budget overrun without commensurate benefit.
   - **Exact decision requested**: `Approve [balanced: claude-sonnet-5]`, `Upgrade to frontier`, `Defer`.

The agent records the approved tier and model in `research-brief.json` under `model_selection` and never proceeds until approval.

## Escalation triggers

The agent automatically escalates to the next tier (and re-runs) when it detects:

- **Non-reproducibility**: same inputs yield inconsistent outputs across runs.
- **Verification failure**: Verifier rejects Builder's work in 2+ iterations.
- **Low-confidence output**: the model explicitly flags uncertainty or ambiguity in its own reasoning.
- **Anomalous results**: metrics deviate sharply from baseline without explanation.

Escalation is logged in `decision-log.jsonl` with `decision: escalate`, `from_tier`, `to_tier`, and `trigger`. The human is notified but escalation proceeds automatically — downgrading after escalation requires explicit re-approval.

## State recording

`research-brief.json` gains:
```json
{
  "model_selection": {
    "stage": "PREREGISTRATION",
    "recommended_tier": "balanced",
    "approved_tier": "balanced",
    "model": "claude-sonnet-5",
    "score": 28,
    "floor": "balanced",
    "rationale": "...",
    "approval_hash": "<sha256 of decision event>"
  }
}
```

`experiment-ledger.jsonl` records which model produced each run:
```json
{
  "experiment_id": "exp_001",
  "model_tier": "balanced",
  "model": "claude-sonnet-5",
  ...
}
```

## Cost governance

The agent tracks cumulative token spend by tier. Decision Cards present:
- **Budget consumed so far** by tier (light: X tokens, balanced: Y, frontier: Z).
- **Remaining budget** if the user declared a ceiling.
- **Tier switching recommendation** if the current tier risks exhausting budget before Gate 4.

When a `+500k` budget directive is present, the agent scales tier use to fit: more light/balanced work in early stages, reserving frontier capacity for mandatory floors and escalations.

## Honest Claims

This protocol does not promise perfect tier assignment or cost optimization. Complexity scoring is heuristic and conservative. A task scored **balanced** may succeed with **light**, but the governance goal is avoiding silent underprovisioning of safety-critical stages. When in doubt, recommend up.
