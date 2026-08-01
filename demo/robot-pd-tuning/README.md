# Robot PD-tuning walkthrough (offline demo)

A **local, offline, protocol-compliant** ResearchHelm demo run: bounded random
search over four PD gains of a deterministic 2-DOF planar arm simulator
(`simulator.py`), with every trial, decision, and claim recorded in the
ResearchHelm state contract and auditable in a self-contained Research
Cockpit.

## What it demonstrates

- A bounded `optimize`-style loop: 12 trials, keep/discard by cost, frozen
  artifacts, truthful records.
- The full state contract: `research-brief.json`, `idea-candidates.json`,
  `evidence.jsonl`, `decision-log.jsonl` (hash-chained gates),
  `experiment-ledger.jsonl`, `artifact-manifest.json`, `claim-evidence.json`,
  and `skill-recommendations.jsonl` — all validated by
  `validate_state.py`.
- The zero-dependency Cockpit renderer producing one self-contained HTML.

## Reproduce

```bash
python demo/robot-pd-tuning/build_demo.py
```

The generator runs the deterministic simulator (seed 7), writes the state
under `run/`, self-validates with `validate_state.py`, and renders
`research-cockpit.html`. Re-running it yields the same experiment records;
timestamps and repository commit are recorded at generation time.

## What this walkthrough does and does not claim

- **Is:** a reproducible offline product walkthrough of the protocol
  toolchain, generated locally with the standard library only (no GPU, no
  network, no third-party packages).
- **Is not:** an agent-run session, a benchmark, a novelty claim, a SOTA
  claim, a generalization claim, or any statement about physical robots.
  The human decision records in `decision-log.jsonl` are simulated for
  demonstration purposes, exactly like the synthetic test fixtures.
- The simulator is a toy planar-arm model; the "best" gains only describe
  this model at this seed.

## Files

| Path | Purpose |
|---|---|
| `simulator.py` | Deterministic 2-DOF planar arm PD-control simulator (standard library only) |
| `build_demo.py` | Run the search, write the state contract, self-validate, render the Cockpit |
| `run/` | Generated state: the eight contract files + frozen artifacts |
| `research-cockpit.html` | Rendered output (generated, not committed manually) |
