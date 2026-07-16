# Legacy Optimize Protocol

Use this protocol only when the user explicitly selects legacy `optimize` mode for one mechanical metric. Preserve its bounded autonomous continuation behavior for existing users; do not import that behavior into `pi` or `scout`.

## Setup

Agree with the user on all five items before the first experiment. If any item is missing, ask now; once the bounded loop starts, Do not stop to ask whether ordinary in-scope iterations should continue.

1. Define one numeric metric, its direction, and the verification output that is ground truth.
2. Define one reproducible verification command and treat it as the frozen evaluator. You must always redirect verification output to a file so it cannot flood context, then extract the metric mechanically from that file.
3. Define the editable scope. Keep the evaluation harness and evaluation data read-only. Reading the harness only to learn how to run it is allowed; editing it or probing, copying, leaking, or fitting its data, constants, or expected outputs is forbidden, including from scratch scripts outside the repository.
4. Define the budget and default to 25 iterations unless the user chooses another iteration, wall-clock, or target stop condition. Set a per-run timeout; default to two times a normal run, then kill the run and classify it as Crashed.
5. Create `autoresearch/<tag>` from the user's current branch. The branch must be new, isolated, and different from the user's working branch.

Require a clean working tree before setup. If the tree is dirty, stop and ask how the user wants their changes handled. Do not alter user-owned work: never stash, reset, overwrite, delete, or commit it.

Create `results.tsv` as an untracked and never committed ledger with the exact literal-tab header `commit	metric	status	description`. Run the unchanged frozen evaluator as iteration 1 and record the baseline before changing code.

## Atomic Loop

Repeat until the budget is exhausted or the agreed stop condition is met:

1. Review `git log`, `results.tsv`, the current best state, failures, untried ideas, and remaining budget.
2. Choose ONE focused change: one improvement idea or one single deletion. Never combine independent hypotheses. Dead parameters, no-op terms, and needless branches are valid deletion experiments.
3. Implement only inside the editable scope.
4. Create a commit and note its short hash. Make the commit BEFORE verification so every attempted code state has a stable identity even if it crashes or execution is interrupted.
5. Run the frozen evaluator once under the timeout, capture the raw log, and extract the metric.
6. Apply exactly one outcome rule:
   - **Improved:** keep the commit and advance the best state.
   - **Exactly equal:** treat it as a tie. Keep it only when it deletes or clearly simplifies code; otherwise run `git reset --hard HEAD~1` inside the isolated experiment branch.
   - **Worse:** run `git reset --hard HEAD~1` inside the isolated experiment branch.
   - **Crashed:** inspect only the bounded error log. For one trivial mechanical fix such as a typo or missing import, fix it, run `git commit --amend`, note the new post-amend hash, and re-run once. If the idea is fundamentally broken, reset the isolated branch one commit and move on.
7. Before the next continuation, append one row to `results.tsv`: the last noted tested hash, metric (`NA` for a crash, never a numeric sentinel), status `keep`, `discard`, or `crash`, and a one-line description. After a reset, record the attempted hash already noted; do not substitute the current `HEAD`.

Out of ideas is not an automatic stop while budget remains. Try a deletion, re-read the code, revisit a near miss, combine evidence without combining hypotheses, or try a more radical single change. Treat rewinding more than one commit as a last resort; use it sparingly and only on the isolated experiment branch.

### Simplicity criterion

Weigh metric gain against complexity. Discard a hair-thin gain that adds unjustified complexity. Treat a deletion that preserves the metric as a win, and a deletion that improves it as the strongest outcome. Do not finish with suspicious complexity that was never challenged by a deletion experiment.

### Red flags

Stop and repair the protocol if any of these occur:

- editing on main or master, or on the user's branch;
- hiding a dirty tree by stashing or discarding user changes;
- putting two ideas in one commit;
- verifying before committing;
- recording a hash that does not contain the code that produced its metric;
- recording results only in commit messages or ad-hoc notes instead of `results.tsv`;
- pausing to ask the user whether to continue an ordinary approved iteration;
- Fitting the evaluation data, including reading it merely to explain failures;
- keeping suspicious complexity without testing whether it can be deleted.

## Crash and Hash Integrity

For every Crashed experiment, preserve the bounded error evidence and record `NA`. A crash never receives a fabricated numeric metric.

When using `git commit --amend`, the pre-amend hash must never appear as the tested artifact in `results.tsv`; record only the post-amend hash after the one allowed re-run. If the repair changes the hypothesis, evaluator, data, permissions, or scope, end the old experiment as Crashed and require the appropriate approval before starting a new committed experiment.

Never amend a commit whose result is already recorded unless the ledger explicitly marks the old row superseded while preserving the audit trail. Never use reset, amend, or deletion permissions outside the clean isolated experiment branch or against user-owned work.

Before resume, verify the branch, clean tree, best commit, ledger tail, editable and data boundaries, frozen evaluator, configuration, environment, and remaining budget. Refuse automatic resume when any binding differs from the recorded state.

## Final Report

End with a Final Report containing:

- baseline and best valid metric;
- best commit hash and reproducible verification command;
- every `results.tsv` attempt, including ties, discards, and `NA` crashes;
- kept, reverted, and deleted experiment commits;
- what worked, what failed, and why;
- resource use, integrity concerns, and remaining uncertainty;
- any complexity left in the winner that never received a deletion test;
- final branch state and ledger location;
- recommended next experiments, clearly labeled as not performed.

Leave the isolated branch and `results.tsv` available for audit. Do not merge, push, publish, or delete the branch without separate user authorization.
