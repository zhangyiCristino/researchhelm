# Implementation Audit

Separate construction from verification. The Builder may create an implementation and artifacts; the Verifier independently decides whether the registered experiment remains intact and trustworthy.

Use the canonical experiment-ledger fields and artifact-manifest fields in `schemas.md`. Apply `privacy-security.md` to code, logs, environment records, paths, and reports.

## Builder

Give the Builder input consisting of the approved hypothesis, preregistration, editable-file boundary, frozen evaluator, data boundary, resource ceiling, tests, and required artifacts.

Require the Builder to write tests first, work on an isolated branch or worktree, and make one causal factor per experiment. Prevent edits outside the approved scope.

Require Builder output to include the implementation diff, test results, runnable command, configuration, environment evidence, raw artifacts, hashes, known failures, and an implementation note. Treat the Builder's interpretation as a proposal, not verification evidence.

## Verifier

Give the Verifier input consisting of the approved contract, clean source state, implementation diff, raw artifacts, hashes, commands, and environment evidence. Do not give it authority to silently repair the implementation it is judging.

Require Verifier output to list every check performed, identify evidence and missing evidence, separate critical findings from advisory findings, and recommend whether Gate 3 must remain blocked or is ready for human review.

The Verifier cannot issue a human decision. Persist only a human `approve|revise|reject|defer` decision through the canonical decision record after the user reviews the evidence.

Perform a diff-to-hypothesis review. Confirm that every material change supports the registered hypothesis and that no unrelated optimization entered the experiment.

## Integrity Checks

Verify at least:

- evaluator integrity and data integrity;
- shapes, units, splits, seeds, and environment;
- baseline, controls, ablations, and invariants;
- resource use and stop conditions;
- absence of leakage, gaming, and cherry-picking;
- consistency of commands, artifacts, manifests, and hashes;
- a clean smoke run and pilot reproduction from the recorded instructions.

Treat missing raw evidence as missing, not as a pass. Keep one causal factor per experiment auditable from the diff and ledger.

## Anomalous Gains

When an anomalous gain appears, block promotion and investigate evaluator integrity, data integrity, leakage, accidental data access, metric computation, cached artifacts, environment drift, and unregistered changes.

Require independent pilot reproduction from a clean state. Preserve the suspicious artifacts and hashes; do not overwrite them with a later run.

Any critical finding must block Gate 3 until the user approves a revised contract or the evidence resolves the finding. Never downgrade a critical finding merely to keep an experiment moving.
