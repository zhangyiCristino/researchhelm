# Changelog

All notable changes to ResearchHelm are documented here. This project follows
[Semantic Versioning](https://semver.org/); the format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [3.2.0] - 2026-08-04

### Added

- CLI packaging bundles canonical scripts and helpers under
  `researchhelm_cli/bundled/` so `pip install researchhelm` (non-editable)
  can still run `validate` / `render` / `audit` / `sanitize` / `compat` /
  `inspect` without a live checkout.
- `researchhelm init <run_dir>` scaffolds a protocol-valid run directory from
  the minimal fixture (synthetic; replace fields for real research).
- `researchhelm doctor` reports script resolution, git/python availability,
  and whether a user skill install is present — without reading credential
  stores or client config contents.
- `researchhelm scan-credentials <path>` and `scripts/credential_scan.py`:
  independent worktree filename/path-segment scan with **content-free**
  findings (no secret values echoed).
- Skill first-turn checklist and optional Decision / Recommendation card
  templates under `skills/researchhelm/assets/templates/`.
- Offline robot PD-tuning walkthrough demo and SVG visuals (carried from the
  post-3.1.0 tree into this release narrative).
- Native-tested verification protocol docs, scenarios, and preflight helper
  (evidence still requires a real client run before any Native-tested label).

### Changed

- Plugin, marketplace, and package versions bumped to 3.2.0.
- README quick-start documents the expanded CLI surface.
- ROADMAP delivered list updated for CLI packaging, demos, and the independent
  credential filename scanner slice.

### Security

- Independent credential **filename** scanner is an incremental release gate
  helper. It does **not** replace reachable-history sanitization, exact
  release-archive scanning, or a full independent secret-content scanner.

## [3.1.0] - 2026-08-01

### Added

- `researchhelm` command-line interface: a pip-installable toolchain
  (`pip install researchhelm`, standard library only) wrapping the canonical
  protocol scripts as subcommands — `validate`, `render`, `audit`,
  `sanitize`, `compat`, `inspect`, `verify`. The skill folder itself is
  untouched and stays contract-pinned.
- `tests/test_cli.py` covering CLI dispatch and every subcommand.
- README (EN/中文): quick-start table, live-demo link to the hosted Research
  Cockpit, a `How it works` pipeline diagram, and an FAQ section.
- Community infrastructure: `CONTRIBUTING.md`, `CHANGELOG.md`, `ROADMAP.md`,
  `CODE_OF_CONDUCT.md`, bug-report and feature-request issue templates, and a
  `scripts/quick_verify.py` smoke check.

### Changed

- Plugin and marketplace metadata versions bumped to 3.1.0.

## [3.0.0] - 2026-07-16

### Changed

- Unified the internal identity from `autoresearch` to `researchhelm` across
  the plugin, marketplace, skill folder, slash command, and run-state
  directory. See the legacy-identifier notes in the READMEs.
- Re-rendered the README Research Cockpit screenshot at 2x from the frozen
  public demo; pinned CI actions to current major versions.

### Deliberately unchanged

- `optimize` mode keeps its `autoresearch/<tag>` branch prefix (a v1 safety
  contract); `.gitignore` still ignores `.autoresearch/`; the release auditor
  still recognizes both old and new slash commands.

## [2.x] and [1.x] - historical

Earlier releases shipped under the `autoresearch` identity in the previous
repository location. Their identifiers and install commands are recorded for
reference in the `## Legacy identifiers` section of the READMEs and in the
v2-era release notes; the current tree no longer matches those commands.

[3.2.0]: https://github.com/zhangyiCristino/researchhelm/releases/tag/v3.2.0
[3.1.0]: https://github.com/zhangyiCristino/researchhelm/releases/tag/v3.1.0
[3.0.0]: https://github.com/zhangyiCristino/researchhelm/releases/tag/v3.0.0
