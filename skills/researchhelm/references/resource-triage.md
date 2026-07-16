# Resource Triage

Turn an initial request into a decision-ready research brief before proposing ideas or experiments. Record uncertainty explicitly. Never infer access to data, compute, money, credentials, licenses, or expertise.

Use the canonical field names defined in `schemas.md`; do not invent a second schema here. Apply `privacy-security.md` to every value you record.

## Intake Contract

Collect or mark unknown for each item:

- State the domain or question in operational terms.
- Identify existing code, its runnable entry points, and its known condition.
- Identify existing data, provenance, allowed uses, splits, scale, and quality concerns.
- Record accelerators and VRAM separately from CPU, RAM, and storage.
- Record available wall time, money, APIs, licenses, and relevant expertise.
- Record the deadline and venue when they constrain evaluation or deliverables.
- Separate allowed scope from forbidden scope.
- Record risk tolerance for scientific, operational, privacy, and cost failure.

For APIs, record only the provider, required capability, and whether access is available. Never request, copy, display, or persist a secret. For local resources, avoid publishing absolute paths or machine identifiers.

Distinguish facts supplied by the user from assumptions made by the agent. Attach a source or rationale to every consequential assumption.

## Feasibility Envelope

Estimate a low, expected, and high case. For each case, state assumptions and estimate:

- compute type and quantity;
- memory and storage;
- elapsed time and human review time;
- money and paid-service exposure;
- data, license, and venue constraints;
- major uncertainty and the observation that would reduce it.

Classify the proposed work as feasible, conditionally feasible, or infeasible under the current envelope. Do not convert unknown resources into optimistic defaults.

When the full objective exceeds the envelope, present tiered options:

1. a minimal scout pass that uses available artifacts only;
2. a bounded pilot that tests the highest-value uncertainty;
3. a full run with the additional resources and approvals it requires.

Show how each option changes expected evidence, cost, risk, and time. Keep the user responsible for choosing among materially different options.

## Missing Inputs

List missing inputs in priority order. Explain what decision each missing input affects and whether the work can proceed without it.

Always block the full run while required inputs remain missing. Always present tiered options that include the smallest safe scout, a bounded pilot where possible, and the full run with the inputs and approvals it still requires.

Proceed with a clearly labeled assumption only inside the smallest safe scout or bounded pilot, and only when the assumption is reversible, low risk, and inside the allowed scope. Never let an assumption silently satisfy a missing full-run input.

End with a decision card containing the resource summary, feasibility class, unresolved assumptions, tiered options, recommended next step, and the exact approve, revise, or defer decision requested from the user.
