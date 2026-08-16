# Roadmap

ResearchHelm is developed in public, one audited release at a time. This page
states what is done, what is next, and how new ideas get in. It is a plan, not
a promise: every item ships only when it passes the release gates (CI,
Security audit, release auditor) and keeps the human-governed boundary intact.

## Delivered (2026-08 snapshot)

- Deterministic state and validation (`validate_state.py`)
- Privacy and publication boundary (local Cockpit is private and untracked;
  public Cockpits require a validated sanitized export)
- Zero-dependency Research Cockpit renderer (`render_cockpit.py`)
- Evidence-backed compatibility registry (`evals/compatibility/clients.json`)
- Repository contract tests that pin the READMEs, plugin metadata, and legacy
  identifiers
- Sanitized one-GPU public walkthrough with 18 frozen runs on UCI Covertype
  (`demo/one-gpu-public/`)
- Offline robot PD-tuning walkthrough with SVG visuals
  (`demo/robot-pd-tuning/`)
- Release audit (`audit_release.py`) and CI across Python 3.9/3.11/3.13 on
  Linux and Windows
- Pip-installable CLI with bundled scripts (`researchhelm` package) including
  `init`, `doctor`, `scan-credentials`, and the protocol subcommands
- Independent worktree credential **filename** scanner
  (`scripts/credential_scan.py`) — content-free findings only
- Native-tested verification protocol docs and preflight (label still requires
  a real client evidence report)

## Next release gates (declared in SECURITY.md / TESTING.md)

- Reachable-history sanitization for public exports
- Exact release-archive scanning (beyond current archive scope helpers)
- Broader independent credential **content** scanning (not only filenames)
- Remote publication of run artifacts

## Community directions (candidate, not committed)

- **Native client verification:** real install/activate/refuse/exit evidence
  for Claude Code, Codex, and other coding agents, recorded through the
  compatibility-report form.
- **More bounded walkthroughs:** additional frozen demos (different resource
  envelopes, domains, and budget levels) to broaden the evidence base without
  turning demos into benchmarks.
- **Evaluation scenarios:** a shared, versioned scenario set so community
  reports are comparable across clients and dates.
- **i18n:** keep the Chinese and English READMEs and templates in sync as the
  protocol evolves.

## How roadmap items get in

Open an issue with a concrete motivation and, where relevant, reproducible
evidence. Items that weaken human gates, blur claim-to-artifact auditing, or
add unverifiable marketing language are out of scope by design.
