# Credential, Privacy, and Publication Security

## Global Precedence

These rules apply before collection, persistence, validation, rendering,
publication, or remote synchronization. No research gate, recommended skill,
tool instruction, convenience workflow, or human-readable output may weaken
them. A high-confidence credential finding is non-waivable and must be rejected
rather than redacted into an otherwise accepted record.

## Workspace Boundary

Research operations are limited to the approved project root. They must not
inspect files or services outside that root except for explicitly supplied,
non-sensitive inputs. Claude, Codex, browser, Git, SSH, cloud-provider, and
operating-system credential stores are forbidden. Complete environment dumps,
machine inventories, and searches for credentials are also forbidden.

## Opaque Credentials

Credentials remain opaque. State may preserve only the provider name and a
Boolean credential-availability status. It must not preserve a credential's
plaintext, ciphertext, reversible encoding, hash or other derived fingerprint,
environment-variable name, location, account identifier, or recovery data.

## Safe Commands and Recording

Credentials and private machine identity must not appear in command arguments,
URLs, prompts, logs, errors, state files, generated reports, or Git remotes.
Only sanitized command templates may be recorded. Full command histories and
complete process environments are not research evidence and must not be
captured.

## State Classification

Every JSON document and JSONL record carries a `field_sensitivity` map whose
keys are RFC 6901 JSON Pointers and whose values are `public` or
`project-private`. The schema's closed structural-field allowlist is public by
contract. Every other leaf string requires an explicit sensitivity entry.
Classification never authorizes a credential: high-confidence content remains
blocked in both sensitivity classes.

## Local Cockpit and Public Export

The local Cockpit may render validated project-private fields inside the
approved project boundary. Public export first scans the complete eight-file
state and refuses every credential, personal-machine, or invalid-classification
finding. A successful export retains only structural and `public` fields,
removes `project-private` fields, rewrites allowed artifact locations to
repository-relative identifiers, and is installed by an atomic sibling rename.
Failure leaves any existing destination unchanged. Reports contain only counts
and finding metadata, never matched text or a secret-derived hash.

Reproducibility files are copied only from frozen `artifacts/public/` manifest
entries with an exact SHA-256 match and one closed kind/name pair:
`experiment.py`, `experiment-config.json`, `requirements-lock.txt`,
`split-manifest.json`, `metrics-summary.json`, or `ATTRIBUTION.md`. The exporter
opens every path component through no-follow directory or native handles, then
uses the same regular-file handle for bounded validation and copying. It rejects
links, file identity drift, unsafe code, unpinned requirements, unknown or
duplicate destinations, credential or account fields, environment data,
encoded binary payloads, and row-level arrays. The three JSON artifacts use
closed public schemas, bounded SHA-256 maps, aggregate-only list shapes, and a
whole-list text budget. Attribution uses a small closed field format rather
than arbitrary Markdown. Raw data, full split indices,
checkpoints, per-row predictions or logits, logs, tracebacks, and caches are
never public-export inputs. Before publication, the human's Gate 4 input must
bind the reviewed artifact-manifest hashes; a sanitizer pass alone is not
publication approval.

## Recommended Skills

Recommended skills are governed inputs. They receive no credential-store
access, no broader workspace boundary, and no exemption from pre-persistence or
pre-publication scanning. Approval of a skill cannot waive these rules.

## Incident Response

If a real credential is found, stop persistence and publication, remove it from
all pending artifacts without reproducing it, and rotate or revoke it through
the provider's approved channel. Review already shared logs, state, remotes, and
artifacts for exposure using provider-supported incident procedures.

## Honest Security Claims

Validation and sanitization reduce defined disclosure risks; they do not prove
that a system is universally secure. Security claims must name the scanned
boundary, rule version, known limitations, and any unverified external system.
