# Idea Diligence

Convert a research brief into a small, evidence-grounded Pareto set of candidate ideas. Treat novelty as a claim to investigate, not a fact to advertise.

Use the candidate fields and enumerations defined in `schemas.md`. Apply `privacy-security.md` while searching, recording sources, and preparing any shareable output.

## Query Ladder

Run three explicit ladders when the permitted tools and connectivity allow them:

1. Use a paper query ladder: broad review terms, nearest-method terms, exact mechanism terms, then citation and related-work expansion.
2. Use a code query ladder: task repositories, method implementations, benchmark implementations, then issue and release evidence.
3. Use a dataset query ladder: benchmark names, task-plus-modality terms, licenses, access constraints, and known contamination or leakage reports.

For every ladder, record sources, coverage, failures, conflicts, and the search cutoff. If a ladder cannot run, report the limitation instead of implying exhaustive coverage. Never upload private research merely to improve discovery.

Summarize what is known, what is disputed, and what remains unknown. Preserve source links or local artifact identifiers without exposing secrets or private absolute paths.

## Overlap Dimensions

Compare each candidate with its nearest work along these dimensions:

- question;
- method;
- data;
- evaluation;
- claimed contribution.

Assign the overlap assessment exactly as `overlapping|incremental|differentiated|unknown`. Explain the evidence for each dimension and mark weak coverage as unknown. Do not describe an idea as novel solely because no exact title match appeared.

Reject or revise candidates whose differentiating claim depends on changing an evaluator, hiding a stronger baseline, exploiting leakage, or making an unsupported compatibility or safety claim.

## Candidate Contract

For each surviving candidate, complete the exact candidate fields from `schemas.md`, including:

- a falsifiable hypothesis and the proposed mechanism;
- the nearest work and dimension-level overlap assessment;
- the differentiating claim;
- the minimum falsification experiment;
- low, expected, and high costs in the resource estimate;
- benefits, risks, and plausible pivots;
- the canonical scores and status.

Make the minimum falsification experiment cheaper than the intended full experiment whenever possible. Define the result that would count against the hypothesis.

Rank candidates as a Pareto set across expected information value, differentiation, feasibility, cost, and risk. Do not collapse incomparable tradeoffs into a false single optimum. Keep only a decision-ready short list and include a no-experiment or gather-more-evidence option when it is competitive.

End with a Gate 1 decision card that shows the candidates, evidence limits, costs, risks, pivots, recommendation, and the exact approve, revise, reject, or defer decision requested from the user.
