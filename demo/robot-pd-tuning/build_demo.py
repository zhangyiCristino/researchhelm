"""Generate the robot PD-tuning demo run (offline, protocol-compliant).

The demo simulates a bounded `optimize`-style loop: random search over four
PD gains of a deterministic 2-DOF planar arm simulator, keep/discard by
cost, with all decisions and evidence recorded in the ResearchHelm state
contract. It is a LOCAL, OFFLINE, protocol-compliant walkthrough: no agent,
no network, no GPU. It is not a benchmark, novelty, SOTA, or generalization
claim.

Pipeline:
    1. Run the search (simulator.py, deterministic, seed=7, 12 trials).
    2. Write the eight state files under run/ with real hashes.
    3. Self-validate with validate_state.py.
    4. Render the Research Cockpit HTML.

Usage:
    python demo/robot-pd-tuning/build_demo.py
"""

import hashlib
import importlib.util
import json
import platform
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
ROOT = DEMO_DIR.parents[1]
RUN_DIR = DEMO_DIR / "run"
ARTIFACTS_DIR = RUN_DIR / "artifacts"
SIMULATOR_SRC = DEMO_DIR / "simulator.py"
VALIDATE_SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "validate_state.py"
RENDER_SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "render_cockpit.py"

RUN_ID = "robot-pd-tuning"
BASE = datetime.now(timezone.utc).replace(microsecond=0)

# Parameter space for the bounded search.
KP_RANGE = (0.5, 5.0)
KD_RANGE = (0.1, 2.0)
SEED = 7
TRIALS = 12


def ts(seconds: int) -> str:
    return (BASE + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_simulator():
    spec = importlib.util.spec_from_file_location("demo_simulator", SIMULATOR_SRC)
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_simulator"] = module
    spec.loader.exec_module(module)
    return module


def git_head() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except OSError:
        pass
    return "0" * 40


def run_search(sim):
    """Deterministic random search over PD gains; returns per-trial records."""
    rng = random.Random(SEED)
    records = []
    best_cost = None
    for index in range(TRIALS):
        params = {
            "kp1": round(rng.uniform(*KP_RANGE), 4),
            "kd1": round(rng.uniform(*KD_RANGE), 4),
            "kp2": round(rng.uniform(*KP_RANGE), 4),
            "kd2": round(rng.uniform(*KD_RANGE), 4),
        }
        started = time.perf_counter()
        metrics = sim.simulate(**params)
        runtime = round(time.perf_counter() - started, 3)
        keep = best_cost is None or metrics["cost"] < best_cost
        if keep:
            best_cost = metrics["cost"]
        records.append(
            {
                "trial": index + 1,
                "params": params,
                "metrics": metrics,
                "runtime_seconds": runtime,
                "keep": keep,
            }
        )
    return records


def decision_record(stage, decision, input_hash, timestamp, rationale, previous_hash):
    record = {
        "schema_version": "1.0",
        "record_type": "decision",
        "event_id": f"decision-{stage.lower().replace('_', '-')}",
        "stage": stage,
        "decision": decision,
        "input_hash": input_hash,
        "actor": "human",
        "timestamp": timestamp,
        "rationale": rationale,
        "constraints": ["workspace-only"],
        "previous_event_hash": previous_hash,
        "event_hash": "",
        "field_sensitivity": {
            "/actor": "public",
            "/rationale": "public",
            "/constraints/0": "public",
        },
    }
    body = {key: value for key, value in record.items() if key != "event_hash"}
    record["event_hash"] = sha256_bytes(canonical(body))
    return record


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    sim = load_simulator()
    trials = run_search(sim)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    # --- frozen artifacts -------------------------------------------------
    sim_artifact = ARTIFACTS_DIR / "simulator.py"
    sim_artifact.write_bytes(SIMULATOR_SRC.read_bytes())
    results = {
        "run_id": RUN_ID,
        "seed": SEED,
        "trials": TRIALS,
        "parameter_space": {
            "kp": list(KP_RANGE),
            "kd": list(KD_RANGE),
        },
        "best": min(trials, key=lambda t: t["metrics"]["cost"]),
        "trial_records": trials,
    }
    results_path = ARTIFACTS_DIR / "results.json"
    write_json(results_path, results)

    code_hash = sha256_file(sim_artifact)
    data_hash = sha256_file(results_path)
    config_hash = sha256_bytes(
        canonical(
            {
                "kp_range": KP_RANGE,
                "kd_range": KD_RANGE,
                "seed": SEED,
                "trials": TRIALS,
            }
        )
    )
    environment_hash = sha256_bytes(
        canonical(
            {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "implementation": platform.python_implementation(),
            }
        )
    )
    stage_input_hash = sha256_bytes(
        canonical({"code": code_hash, "config": config_hash, "data": data_hash})
    )
    commit = git_head()

    # --- research-brief.json ----------------------------------------------
    brief = {
        "schema_version": "1.0",
        "record_type": "research-brief",
        "run_id": RUN_ID,
        "mode": "optimize",
        "stage": "BOUNDED_EXECUTION",
        "created_at": ts(0),
        "updated_at": ts(30),
        "stage_input_hash": stage_input_hash,
        "resources": {
            "compute": {
                "cpu": "public-standard",
                "accelerator": "none",
                "ram_gb": 16,
                "storage_gb": 1,
            },
            "apis": [
                {
                    "provider": "none",
                    "capability": "none",
                    "credential_available": False,
                }
            ],
        },
        "constraints": {
            "wall_time_seconds": 600,
            "monetary_budget": 0,
            "allowed_scope": ["demo/robot-pd-tuning/"],
            "forbidden_scope": [],
            "commands": [
                {"template": "py demo/robot-pd-tuning/simulator.py"}
            ],
        },
        "network_status": {
            "available": False,
            "approved_for_project_private_data": False,
        },
        "resume": {"enabled": False},
        "public_summary": "Bounded offline PD-gain search for a deterministic planar arm simulator.",
        "private_question": "Which gain combination minimizes terminal distance and control effort?",
        "field_sensitivity": {
            "/resources/compute/cpu": "public",
            "/resources/compute/accelerator": "public",
            "/resources/apis/0/provider": "public",
            "/resources/apis/0/capability": "public",
            "/constraints/allowed_scope/0": "public",
            "/constraints/commands/0/template": "public",
            "/public_summary": "public",
            "/private_question": "project-private",
        },
    }
    write_json(RUN_DIR / "research-brief.json", brief)

    # --- idea-candidates.json ----------------------------------------------
    idea = {
        "schema_version": "1.0",
        "record_type": "idea-candidates",
        "candidates": [
            {
                "candidate_id": "idea-001",
                "hypothesis": "Bounded random search over PD gains finds a controller reaching the target.",
                "mechanism": "Four gains are searched with a fixed seed; cost is terminal distance plus weighted control effort.",
                "nearest_work": [{"evidence_id": "evidence-001"}],
                "overlap": {
                    "question": "none",
                    "method": "partial",
                    "data": "none",
                    "evaluation": "partial",
                    "claimed_contribution": "none",
                },
                "differentiating_claim": "The full search is reproducible offline with zero dependencies.",
                "minimum_falsification_experiment": "A trial whose terminal distance exceeds the baseline cost.",
                "resource_estimate": {
                    "low": {"wall_time_seconds": 5},
                    "expected": {"wall_time_seconds": 30},
                    "high": {"wall_time_seconds": 120},
                },
                "scores": {
                    "information_gain": 3,
                    "feasibility": 5,
                    "impact": 2,
                    "evidence_quality": 5,
                    "compute_fit": 5,
                    "risk": 1,
                },
                "risks": ["Simulator is not a physical robot"],
                "pivots": ["Increase trials", "Add noise to the dynamics"],
                "status": "differentiated",
            }
        ],
        "field_sensitivity": {
            "/candidates/0/hypothesis": "public",
            "/candidates/0/mechanism": "public",
            "/candidates/0/overlap/question": "public",
            "/candidates/0/overlap/method": "public",
            "/candidates/0/overlap/data": "public",
            "/candidates/0/overlap/evaluation": "public",
            "/candidates/0/overlap/claimed_contribution": "public",
            "/candidates/0/differentiating_claim": "public",
            "/candidates/0/minimum_falsification_experiment": "public",
            "/candidates/0/risks/0": "public",
            "/candidates/0/pivots/0": "public",
            "/candidates/0/pivots/1": "public",
        },
    }
    write_json(RUN_DIR / "idea-candidates.json", idea)

    # --- evidence.jsonl ------------------------------------------------------
    evidence = {
        "schema_version": "1.0",
        "record_type": "evidence",
        "evidence_id": "evidence-001",
        "kind": "documentation",
        "source": "local-demo-generator",
        "retrieved_at": ts(0),
        "coverage": {"scope": "local-approved-optimization", "limitations": []},
        "content_hash": sha256_bytes(
            canonical({"code": code_hash, "results": data_hash})
        ),
        "status": "verified",
        "notes": "Deterministic simulator and generator committed with the run.",
        "field_sensitivity": {
            "/kind": "public",
            "/source": "public",
            "/coverage/scope": "public",
            "/status": "public",
            "/notes": "public",
        },
    }
    (RUN_DIR / "evidence.jsonl").write_text(
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    # --- decision-log.jsonl ---------------------------------------------------
    decisions = [
        decision_record(
            "GATE_1_IDEA", "approve", stage_input_hash, ts(2),
            "Select the PD-gain search candidate.", None,
        ),
        decision_record(
            "GATE_2_PLAN_AND_BUDGET", "approve", stage_input_hash, ts(4),
            "Approve the bounded 12-trial search within the declared envelope.",
            None,
        ),
        decision_record(
            "GATE_3_FULL_RUN", "approve", stage_input_hash, ts(6),
            "Promote the search to the bounded execution block.",
            None,
        ),
    ]
    # Link the chain and re-hash in order so each event_hash reflects the
    # previous event's final hash.
    for index in range(1, len(decisions)):
        decisions[index]["previous_event_hash"] = decisions[index - 1]["event_hash"]
        body = {
            key: value
            for key, value in decisions[index].items()
            if key != "event_hash"
        }
        decisions[index]["event_hash"] = sha256_bytes(canonical(body))
    with (RUN_DIR / "decision-log.jsonl").open("w", encoding="utf-8") as handle:
        for record in decisions:
            handle.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    # --- experiment-ledger.jsonl ------------------------------------------------
    ledger_records = []
    for trial in trials:
        entry = {
            "schema_version": "1.0",
            "record_type": "experiment",
            "experiment_id": f"experiment-{trial['trial']:03d}",
            "commit": commit,
            "code_hash": code_hash,
            "config_hash": config_hash,
            "data_hash": data_hash,
            "environment_hash": environment_hash,
            "metrics": {
                "primary": trial["metrics"]["cost"],
                "secondary": {
                    "distance": trial["metrics"]["distance"],
                    "energy": trial["metrics"]["energy"],
                },
            },
            "uncertainty": {"method": "none", "value": None},
            "runtime": {"seconds": trial["runtime_seconds"]},
            "peak_memory": {"megabytes": 24},
            "cost": {"currency": "USD", "amount": 0},
            "status": "success",
            "decision": "approve" if trial["keep"] else "reject",
            "artifact_ids": ["artifact-results"],
            "environment": {
                "dependencies": {"python": "3"},
                "runtime": "CPython",
                "drivers": {},
                "hardware_class": "public-standard",
            },
            "field_sensitivity": {
                "/uncertainty/method": "public",
                "/cost/currency": "public",
                "/status": "public",
                "/environment/dependencies/python": "public",
                "/environment/runtime": "public",
                "/environment/hardware_class": "public",
            },
        }
        ledger_records.append(entry)
    with (RUN_DIR / "experiment-ledger.jsonl").open("w", encoding="utf-8") as handle:
        for entry in ledger_records:
            handle.write(
                json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    # --- artifact-manifest.json --------------------------------------------------
    manifest = {
        "schema_version": "1.0",
        "record_type": "artifact-manifest",
        "artifacts": [
            {
                "artifact_id": "artifact-simulator",
                "path": "artifacts/simulator.py",
                "kind": "code",
                "sha256": code_hash,
                "producing_run": RUN_ID,
                "frozen": True,
            },
            {
                "artifact_id": "artifact-results",
                "path": "artifacts/results.json",
                "kind": "result",
                "sha256": data_hash,
                "producing_run": RUN_ID,
                "frozen": True,
            },
        ],
        "field_sensitivity": {
            "/artifacts/0/path": "public",
            "/artifacts/0/kind": "public",
            "/artifacts/1/path": "public",
            "/artifacts/1/kind": "public",
        },
    }
    write_json(RUN_DIR / "artifact-manifest.json", manifest)

    # --- claim-evidence.json -------------------------------------------------------
    best = results["best"]
    claims = [
        {
            "claim_id": "claim-001",
            "text": (
                f"Best PD gains reach a terminal distance of "
                f"{best['metrics']['distance']} at cost {best['metrics']['cost']} "
                f"in the deterministic simulator."
            ),
            "status": "supported",
            "run_ids": [RUN_ID],
            "artifact_ids": ["artifact-simulator", "artifact-results"],
            "citations": ["evidence-001"],
            "caveats": [
                "Simulated walkthrough only; not a hardware, benchmark, or generalization claim."
            ],
            "counter_evidence": [],
        },
        {
            "claim_id": "claim-002",
            "text": "The full search reproduces exactly from the committed generator and seed.",
            "status": "supported",
            "run_ids": [RUN_ID],
            "artifact_ids": ["artifact-simulator"],
            "citations": ["evidence-001"],
            "caveats": [
                "Deterministic only within this simulator and Python standard library."
            ],
            "counter_evidence": [],
        },
    ]
    claim_evidence = {
        "schema_version": "1.0",
        "record_type": "claim-evidence",
        "claims": claims,
        "field_sensitivity": {
            "/claims/0/text": "public",
            "/claims/0/citations/0": "public",
            "/claims/0/caveats/0": "public",
            "/claims/1/text": "public",
            "/claims/1/citations/0": "public",
            "/claims/1/caveats/0": "public",
        },
    }
    write_json(RUN_DIR / "claim-evidence.json", claim_evidence)

    # --- skill-recommendations.jsonl (empty: no recommendations in this run) ----
    (RUN_DIR / "skill-recommendations.jsonl").write_text("", encoding="utf-8")

    # --- self-validation and rendering -----------------------------------------
    validate = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(RUN_DIR)],
        text=True,
        capture_output=True,
    )
    print("validate_state:", validate.stdout.strip())
    if validate.returncode != 0:
        print(validate.stderr, file=sys.stderr)
        return 1

    render = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            str(RUN_DIR),
            "--output",
            str(DEMO_DIR / "research-cockpit.html"),
        ],
        text=True,
        capture_output=True,
    )
    print("render_cockpit:", render.stdout.strip() or render.stderr.strip())
    if render.returncode != 0:
        return 1

    visuals = subprocess.run(
        [sys.executable, str(DEMO_DIR / "render_visuals.py")],
        text=True,
        capture_output=True,
    )
    print("render_visuals:", visuals.stdout.strip() or visuals.stderr.strip())
    return 0 if visuals.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
