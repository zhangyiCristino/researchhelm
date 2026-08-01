# Contributing to ResearchHelm

Thank you for considering a contribution. ResearchHelm is a human-governed
research protocol; the same standard applies to its own development: **every
claim should come with reproducible, sanitized evidence**.

## What we welcome

- **Bug reports** with a minimal, reproducible case and exact commands.
- **Compatibility evidence reports** via the
  [dedicated form](.github/ISSUE_TEMPLATE/compatibility-report.yml).
- **Documentation improvements** that keep the tone honest: state boundaries,
  name third-party tools as third-party, and never claim more than is tested.
- **Protocol or test improvements** that make the skill safer, more auditable,
  or easier to verify — not features that weaken human gates.
- **Design proposals** for roadmap items, opened as an issue before code.

## Before you submit

Remove secrets, credentials, account identifiers, private research data,
personal paths, and machine identifiers from everything you share. Community
compatibility reports stay `Community-reported` until independently reproduced
by a maintainer.

## Development environment

- Python 3.9+ (tested on 3.9 / 3.11 / 3.13, Linux and Windows).
- Standard library only — no third-party dependencies for tests or scripts.

Run the full suite:

```bash
python -m unittest discover -s tests
```

For a faster smoke check during iteration:

```bash
python scripts/quick_verify.py
```

The repository also ships a pip-installable CLI wrapping the canonical
protocol scripts (standard library only):

```bash
pip install -e .
researchhelm --help
researchhelm validate <run_dir>
```

The compatibility table in the READMEs is generated from
`evals/compatibility/clients.json`; never edit the marked block by hand:

```bash
python skills/researchhelm/scripts/validate_compatibility.py sync-readme --check
```

## Commit and branch conventions

- Work on a descriptive branch (e.g. `codex/your-change`), not on `master`.
- Keep commits focused; reference the issue or design doc when one exists.
- Do not re-introduce the legacy `autoresearch` identity outside the
  `## Legacy identifiers` sections; repository contract tests enforce this.
- Run the repository contract tests before pushing:
  `python -m unittest tests.test_repository_contracts tests.test_legacy_compatibility tests.test_validate_compatibility`

## Release gates

Releases are audited: CI (unit + standards), the Security gates
(full-history repository audit + gitleaks), and the release auditor
(`skills/researchhelm/scripts/audit_release.py`) all run before a tag is
published. A contribution that cannot pass these gates will not be released.

## Code of conduct

All participants must follow the [Code of Conduct](CODE_OF_CONDUCT.md).
