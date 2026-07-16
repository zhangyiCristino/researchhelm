# ResearchHelm Internal Identity Rename Design

## Goal

Complete the rename that the 2026-07-15 display rebrand and repository rename
deliberately deferred: retire the internal identity `autoresearch` and make
`researchhelm` the single Skill ID, plugin ID, marketplace ID, command, and
state-directory name. This is a breaking release: **v3.0.0**.

## Identity mapping

| Surface | v2 (before) | v3 (after) |
|---|---|---|
| Skill directory | `skills/autoresearch/` | `skills/researchhelm/` |
| SKILL.md frontmatter `name` | `autoresearch` | `researchhelm` |
| plugin.json `name` / version | `autoresearch` / `2.0.0` | `researchhelm` / `3.0.0` |
| marketplace.json `name` / plugin | `autoresearch-skill` / `autoresearch` | `researchhelm` / `researchhelm` |
| Claude Code command | `/autoresearch` | `/researchhelm` |
| Claude Code install | `/plugin install autoresearch@autoresearch-skill` | `/plugin install researchhelm@researchhelm` |
| Manual copy | `cp -r researchhelm/skills/autoresearch ~/.claude/skills/` | `cp -r researchhelm/skills/researchhelm ~/.claude/skills/` |
| Third-party installer | `--skill autoresearch`, `@autoresearch` | `--skill researchhelm`, `@researchhelm` |
| Codex adapter prompt | `$autoresearch` | `$researchhelm` |
| Run state directory | `.autoresearch/<run-id>/` | `.researchhelm/<run-id>/` |
| Cockpit template internals | `__AUTORESEARCH_DATA__`, `id="autoresearch-data"` | `__RESEARCHHELM_DATA__`, `id="researchhelm-data"` |
| Internal helper module names | `_autoresearch_*` | `_researchhelm_*` |

## Deliberately unchanged

- **Legacy optimize branch prefix `autoresearch/<tag>`.** The optimize mode
  exists to preserve every v1 rule (`test_legacy_protocol_preserves_every_v1_rule`);
  its branch naming is part of those semantics.
- **Historical records.** `docs/superpowers/` specifications and plans, dated
  TESTING.md narrative sections, and the frozen `demo/one-gpu-public/` package
  are not rewritten.
- **`.gitignore` keeps ignoring `.autoresearch/`** alongside `.researchhelm/`
  so migrated working copies never accidentally track legacy run state.
- **`audit_release.py` `SLASH_COMMAND`** recognizes both `/researchhelm` and
  `/autoresearch` so migration documentation is not flagged as absolute paths.
- **plugin.json keywords** keep `autoresearch` (alongside `researchhelm`) so
  marketplace search by the old name still finds the successor.
- **karpathy/autoresearch** attribution refers to the external project.

## Migration surface

README (both languages) replaces the "identities remain unchanged" promise
with a v2 -> v3 migration section: reinstall under the new IDs, invoke
`/researchhelm`, and `mv .autoresearch .researchhelm` to resume existing runs.
The legacy redirect section keeps the verbatim v2-era commands as historical
reference only.

## Compatibility claim re-verification

`evals/compatibility/clients.json` binds a claim to the tested commit, and the
claim JSON cannot contain its own commit hash. The PR therefore lands in two
commits:

1. **Commit A** — the full rename; `gh skill publish --dry-run` re-run locally
   against the renamed folder.
2. **Commit B** — claim row updated (`tested_at` 2026-07-16, `commit` = A) and
   README compatibility blocks regenerated via `sync-readme`.

## Verification

Contract tests are updated **before** the implementation (RED), then the
rename lands (GREEN): identity contracts, legacy-compatibility contracts
(rewritten as v3 + migration-surface contracts), installer path contracts,
release contracts (workflow paths, `.gitignore` pins), audit slash-command
contracts, and the full unit suite. Post-merge, the master-only isolated
installer job exercises the pinned third-party installer against the new
skill name.
