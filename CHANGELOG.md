# Changelog

All notable changes to ResearchHelm are documented here. This project follows
[Semantic Versioning](https://semver.org/); the format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- README (EN/中文): quick-start table, live-demo link to the hosted Research
  Cockpit, a `How it works` pipeline diagram, and an FAQ section.
- Community infrastructure: `CONTRIBUTING.md`, `CHANGELOG.md`, `ROADMAP.md`,
  `CODE_OF_CONDUCT.md`, bug-report and feature-request issue templates, and a
  `scripts/quick_verify.py` smoke check.

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

[3.0.0]: https://github.com/zhangyiCristino/researchhelm/releases/tag/v3.0.0
