# Experiment Design

Turn an approved candidate into a preregistered, bounded experiment plan. Make the cheapest decisive test happen before a more expensive stage.

Use the experiment fields and artifact conventions in `schemas.md`. Apply `privacy-security.md` to data, configuration, environment capture, logs, and exports.

## Preregistration

Before implementation or execution, record:

- the hypothesis and causal logic;
- the baseline, controls, and ablations;
- primary and secondary metrics, including direction and aggregation;
- invariants that must remain unchanged;
- data splits and evaluation-data protections;
- seeds or repetitions;
- the uncertainty method;
- the minimum effect that would justify continuation;
- the resource ceiling for compute, time, money, and storage;
- editable files and the frozen evaluator;
- required artifacts, hashes, and stop conditions.

Do not select the primary metric after seeing results. Treat any requested change to the hypothesis, evaluator, data boundary, primary metric, minimum effect, or resource ceiling as a new human decision.

## Pilot

Design the pilot as the smallest credible falsification test. Use representative data and a clean execution path, but keep cost below the approved ceiling.

Require the pilot to produce registered artifacts, a reproducible command, configuration, environment evidence, logs, and raw results. Record failures and negative results rather than silently rerunning until a favorable outcome appears.

## Promotion and Kill Rules

Write deterministic promotion and kill criteria before the pilot runs. Tie promotion to the preregistered primary metric, minimum effect, uncertainty, invariants, resource use, and integrity checks.

Kill or return for revision when the pilot shows anomalous gain, non-reproducibility, unstable statistics, leakage, environment drift, an invariant violation, or an exceeded resource ceiling.

Require a new Gate 2 decision before entering a more expensive stage. Never promote solely because a secondary metric looks favorable.

## Bounded Block

Define each bounded block by its question, data, risk profile, experimental design, budget, timebox, editable files, frozen evaluator, allowed tools, expected artifacts, and stop conditions.

Change one causal factor per experiment unless a preregistered interaction test requires otherwise. Stop at the boundary even when unused budget remains.

Escalate to the user when results reveal anomalous gain, non-reproducibility, unstable statistics, leakage, environment drift, a changed question, changed data, changed risk profile, or changed experimental design. Do not spend into a more expensive stage without explicit approval.
