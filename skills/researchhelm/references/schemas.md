# Flight Recorder state contract

This document is the normative contract for the portable JSON and JSONL state
stored in `.researchhelm/<run-id>/`. The eight files below are the complete
source of truth. A rendered Cockpit is derived output and is not part of this
contract.

## Common envelope and encoding

Every JSON document and every non-blank JSONL record is a JSON object with a
`schema_version` of `"1.0"` and a `record_type` appropriate to its file. JSONL
files are append-only. Unknown schema versions or record types fail closed.
`_line` is reserved for the parser's internal line location and is never a
source JSONL field; a source record containing it fails closed. The internal
line location is metadata, not part of the source payload.

All text is UTF-8. Timestamps are UTC RFC 3339 values ending in `Z`. Every
field described as a SHA-256 digest is 64 hexadecimal characters. A canonical
JSON value is UTF-8 encoded after serialization with sorted keys,
`ensure_ascii=False`, and separators `(',', ':')`. A decision event's hash is
the SHA-256 digest of its complete canonical record after removing only its own
`event_hash` field. Non-finite numeric constants and values that cannot be
encoded as canonical UTF-8 JSON are malformed input.

The mode enum is `pi|scout|optimize`. The lifecycle stage enum is:

`RESOURCE_INTAKE|IDEA_SCOUT|GATE_1_IDEA|PREREGISTRATION|GATE_2_PLAN_AND_BUDGET|BUILD|VERIFY|PILOT|GATE_3_FULL_RUN|BOUNDED_EXECUTION|ANALYZE_AND_AUDIT|GATE_4_CLAIMS|PACKAGE`.

Skill recommendation is a sidecar and is never a lifecycle stage. Human
decision values are `approve|revise|reject|defer`.

## Field sensitivity and public projection

Every JSON document object and every JSONL record contains a
`field_sensitivity` object. Its keys are RFC 6901 JSON Pointers rooted at that
document or record, with `~` escaped as `~0` and `/` escaped as `~1`. Its values
are exactly `public` or `project-private`. A pointer must resolve to an existing
leaf string outside the `field_sensitivity` object.

The structural-field allowlist is closed. It contains only `schema_version`,
record and lifecycle enums, identifiers, UTC timestamps, Boolean and numeric
values, SHA-256 hashes, and commit hashes defined by this contract. Structural
fields need no sensitivity entry and remain in a public projection. Every
other leaf string requires exactly one sensitivity entry. Classification does
not waive content-security scanning: a credential or personal-machine finding
always blocks persistence and public export.

A public projection retains structural fields and leaves classified `public`,
removes leaves classified `project-private`, removes their sensitivity entries,
and keeps a valid sensitivity map for retained public leaves. Artifact paths
are rewritten to repository-relative identifiers. Stable classification codes
are `privacy.missing_classification`, `privacy.invalid_classification`, and
`privacy.classification_path_missing`.

## Required files

### `research-brief.json`

The `record_type` is `research-brief`. Required fields are `schema_version`,
`record_type`, `run_id`, `mode`, `stage`, `created_at`, `updated_at`,
`stage_input_hash`, `resources`, `constraints`, and `network_status`.

`resources` records the resource envelope. Each entry in `resources.apis`
contains exactly `provider`, `capability`, and `credential_available`, where
`credential_available` is a Boolean. It never contains an environment-variable
name, credential value, credential location, or account identifier.

`constraints.commands` is an array of objects containing a non-empty `template`
and an optional string `description`; it never stores captured command-line
records. If present, `resume` is an object whose `enabled` field is Boolean.
When enabled, it contains `expected` and `actual` snapshots. Each snapshot contains
`state_hash`, `branch`, `code_hash`, `data_hash`, `config_hash`, and
`environment_hash`. `branch` is a non-empty string and the other five values
are SHA-256 digests. Both snapshots contain every field. Resume is allowed only
when all six values match.

### `evidence.jsonl`

Each `record_type: evidence` record contains `evidence_id`, `kind`, `source`,
`retrieved_at`, `coverage`, `content_hash`, `status`, and `notes`. `content_hash`
is SHA-256. `coverage` keeps search limits, cut-off dates, and gaps visible.

### `idea-candidates.json`

The `record_type` is `idea-candidates` and `candidates` is an array. Each
candidate contains `candidate_id`, `hypothesis`, `mechanism`, `nearest_work`,
`overlap`, `differentiating_claim`, `minimum_falsification_experiment`,
`resource_estimate`, `scores`, `risks`, `pivots`, and `status`.

`overlap` has exactly the five comparison dimensions `question`, `method`,
`data`, `evaluation`, and `claimed_contribution`. `resource_estimate` contains
`low`, `expected`, and `high`. `scores` contains exactly the six numeric fields
`information_gain`, `feasibility`, `impact`, `evidence_quality`, `compute_fit`,
and `risk`. `risks` and `pivots` are arrays of strings. Candidate status is restricted
to `overlapping|incremental|differentiated|unknown`.

### `decision-log.jsonl`

Each `record_type: decision` event contains `event_id`, `stage`, `decision`,
`input_hash`, `actor`, `timestamp`, `rationale`, `constraints`,
`previous_event_hash`, and `event_hash`. `input_hash` and `event_hash` are
SHA-256; `previous_event_hash` is JSON `null` for the first event and the exact
prior `event_hash` thereafter. An approval is current only when its
`input_hash` equals the current `research-brief.json` `stage_input_hash` for
the same lifecycle stage.

### `skill-recommendations.jsonl`

Records have `record_type: skill-recommendation-card` or
`record_type: skill-recommendation-decision`. Both record types contain
`recommendation_id`, `stage`, `stage_input_hash`, `source`, `revision`,
`content_hash`, `permissions`, and `data_boundary`. A card also records the
capability gap, rationale and whether the skill was used. A decision record
contains `decision`, `actor`, `timestamp`, `rationale`, and `constraints`.
Card recommendation IDs are unique, `used` is Boolean, and
`decision_requested` uses the human decision enum.

Using a recommended skill requires an `approve` decision with an exact match
on recommendation ID, current stage input hash, source, immutable revision,
content hash, permissions, and data boundary. A missing approval fails closed;
any difference invalidates the approval.

### `experiment-ledger.jsonl`

Each `record_type: experiment` record contains `experiment_id`, `commit`,
`code_hash`, `config_hash`, `data_hash`, `environment_hash`, `metrics`,
`uncertainty`, `runtime`, `peak_memory`, `cost`, `status`, `decision`, and
`artifact_ids`. The four named hashes are SHA-256. `decision` uses the human
decision enum. `metrics` is an object. When `status` is `crash`, `metrics`
explicitly contains `primary` and its value is JSON `null`, not a number,
numeric sentinel, or omitted field.

An optional `environment` record contains only `dependencies`, `runtime`,
`drivers`, and `hardware_class`. It may record public dependency, runtime and
driver versions and a public hardware class. It excludes full environment
dumps, usernames, hostnames, serial numbers, device IDs, local IP or MAC
addresses, account IDs, credential locations, and absolute paths.

### `artifact-manifest.json`

The `record_type` is `artifact-manifest` and `artifacts` is an array. Every
entry contains string `artifact_id`, `path`, `kind`, `sha256`, and
`producing_run`, plus Boolean `frozen`. `path` is normalized and relative to the run directory; absolute
paths and paths containing a parent traversal are invalid. `sha256` is a
SHA-256 digest and `frozen` is Boolean.

### `claim-evidence.json`

The `record_type` is `claim-evidence` and `claims` is an array. Every entry
contains string `claim_id`, `text`, and `status`; `run_ids`, `artifact_ids`,
`citations`, `caveats`, and `counter_evidence` are arrays of strings. Claim status is restricted to
`supported|qualified|unsupported`.

## Stable validation findings

The validator returns content-free findings. Required stable codes are
`run.missing_file`, `brief.invalid_mode`, `schema.version_mismatch`,
`schema.invalid_enum`, `schema.reserved_field`,
`hash.invalid_sha256`, `json.malformed`, `approval.input_hash_mismatch`,
`decision.hash_chain_broken`, `decision.event_hash_mismatch`,
`experiment.crash_metric_must_be_null`, `recommendation.approval_missing`,
`recommendation.approval_binding_mismatch`, `resume.hash_mismatch`, and
`artifact.path_escapes_run` and unsafe artifact identifiers as
`artifact.invalid_id`. Credential content is reported as
`security.high_confidence_content`; personal-machine content retains its
specific `privacy.*` scan code. JSON and Unicode decoding failures never
include the source text or parser exception in a finding.
