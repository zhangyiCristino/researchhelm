from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

try:
    from sanitize_export import scan_value
except ModuleNotFoundError:
    from skills.researchhelm.scripts.sanitize_export import scan_value


SCHEMA_VERSION = "1.0"
MODES = {"pi", "scout", "optimize"}
STAGES = {
    "RESOURCE_INTAKE",
    "IDEA_SCOUT",
    "GATE_1_IDEA",
    "PREREGISTRATION",
    "GATE_2_PLAN_AND_BUDGET",
    "BUILD",
    "VERIFY",
    "PILOT",
    "GATE_3_FULL_RUN",
    "BOUNDED_EXECUTION",
    "ANALYZE_AND_AUDIT",
    "GATE_4_CLAIMS",
    "PACKAGE",
}
DECISIONS = {"approve", "revise", "reject", "defer"}
CANDIDATE_STATUSES = {"overlapping", "incremental", "differentiated", "unknown"}
CLAIM_STATUSES = {"supported", "qualified", "unsupported"}
SCORE_FIELDS = {
    "information_gain",
    "feasibility",
    "impact",
    "evidence_quality",
    "compute_fit",
    "risk",
}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)

REQUIRED_FILES = {
    "research-brief.json": "json",
    "evidence.jsonl": "jsonl",
    "idea-candidates.json": "json",
    "decision-log.jsonl": "jsonl",
    "skill-recommendations.jsonl": "jsonl",
    "experiment-ledger.jsonl": "jsonl",
    "artifact-manifest.json": "json",
    "claim-evidence.json": "json",
}
@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    severity: str = "error"


class JsonlRecord(dict[str, Any]):
    def __init__(self, value: dict[str, Any], line_number: int):
        super().__init__(value)
        self.line_number = line_number


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _parse_json(value: str) -> Any:
    data = json.loads(value, parse_constant=_reject_json_constant)
    canonical_json(data).encode("utf-8")
    return data


def load_json(path: Path) -> Any:
    return _parse_json(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[Any]:
    records: list[Any] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if line.strip():
            record = _parse_json(line)
            if isinstance(record, dict):
                record = JsonlRecord(record, line_number)
            records.append(record)
    return records


def validate_envelope(data: Any, expected_kind: str | Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(data, dict):
        return [
            Finding(
                "schema.invalid_enum",
                "$",
                "record must be a JSON object",
            )
        ]
    if data.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "schema.version_mismatch",
                "$",
                f"schema_version must be {SCHEMA_VERSION}",
            )
        )
    expected = {expected_kind} if isinstance(expected_kind, str) else set(expected_kind)
    if data.get("record_type") not in expected:
        findings.append(
            Finding(
                "schema.invalid_enum",
                "$",
                "record_type is not valid for this file",
            )
        )
    return findings


def validate_artifact_path(root: Path, value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    windows_path = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    if windows_path.is_absolute() or windows_path.drive or posix_path.is_absolute():
        return False
    if ".." in posix_path.parts:
        return False
    try:
        candidate = (root / Path(*posix_path.parts)).resolve(strict=False)
        return candidate.is_relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False


def validate_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _recommendation_records(data: Any) -> tuple[list[Any], Any, Any]:
    if isinstance(data, dict):
        records = data.get("records", [])
        return (
            records if isinstance(records, list) else [],
            data.get("stage_input_hash"),
            data.get("stage"),
        )
    return (data if isinstance(data, list) else []), None, None


def validate_recommendation_binding(data: Any) -> list[Finding]:
    records, current_input_hash, current_stage = _recommendation_records(data)
    findings: list[Finding] = []
    cards: dict[str, dict[str, Any]] = {}
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("record_type") == "skill-recommendation-card"
            and isinstance(record.get("recommendation_id"), str)
        ):
            recommendation_id = record["recommendation_id"]
            if recommendation_id in cards:
                findings.append(
                    Finding(
                        "schema.invalid_enum",
                        "skill-recommendations.jsonl",
                        "recommendation_id must be unique for cards",
                    )
                )
            else:
                cards[recommendation_id] = record
    decisions = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("record_type") == "skill-recommendation-decision"
    ]
    binding_fields = (
        "recommendation_id",
        "stage",
        "stage_input_hash",
        "source",
        "revision",
        "content_hash",
        "permissions",
        "data_boundary",
    )
    for recommendation_id, card in cards.items():
        if card.get("used") is not True:
            continue
        approvals = [
            decision
            for decision in decisions
            if decision.get("recommendation_id") == recommendation_id
            and decision.get("decision") == "approve"
        ]
        if not approvals:
            findings.append(
                Finding(
                    "recommendation.approval_missing",
                    "skill-recommendations.jsonl",
                    "used recommendation has no approval",
                )
            )
            continue
        matches = any(
            all(decision.get(field) == card.get(field) for field in binding_fields)
            and (current_stage is None or decision.get("stage") == current_stage)
            and (
                current_input_hash is None
                or decision.get("stage_input_hash") == current_input_hash
            )
            for decision in approvals
        )
        if not matches:
            findings.append(
                Finding(
                    "recommendation.approval_binding_mismatch",
                    "skill-recommendations.jsonl",
                    "approval does not exactly match the used recommendation",
                )
            )
    return findings


def validate_resume_binding(data: Any) -> list[Finding]:
    if not isinstance(data, dict) or "resume" not in data:
        return []
    resume = data["resume"]
    if not isinstance(resume, dict):
        return [
            Finding(
                "schema.invalid_enum",
                "research-brief.json",
                "resume must be an object",
            )
        ]
    if not isinstance(resume.get("enabled"), bool):
        return [
            Finding(
                "schema.invalid_enum",
                "research-brief.json",
                "resume enabled must be a Boolean",
            )
        ]
    if resume["enabled"] is False:
        return []
    expected = resume.get("expected")
    actual = resume.get("actual")
    fields = (
        "state_hash",
        "branch",
        "code_hash",
        "data_hash",
        "config_hash",
        "environment_hash",
    )
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return [
            Finding(
                "resume.hash_mismatch",
                "research-brief.json",
                "resume snapshot does not match recorded state",
            )
        ]
    if (
        any(field not in expected or field not in actual for field in fields)
        or not isinstance(expected.get("branch"), str)
        or not expected.get("branch")
        or not isinstance(actual.get("branch"), str)
        or not actual.get("branch")
        or any(
            not validate_sha256(snapshot.get(field))
            for snapshot in (expected, actual)
            for field in fields
            if field != "branch"
        )
        or any(expected.get(field) != actual.get(field) for field in fields)
    ):
        return [
            Finding(
                "resume.hash_mismatch",
                "research-brief.json",
                "resume snapshot does not match recorded state",
            )
        ]
    return []


def _path_for(path: Path, record: Any) -> str:
    if isinstance(record, JsonlRecord):
        return f"{path}#line={record.line_number}"
    return str(path)


def _add_envelope_findings(
    findings: list[Finding], path: Path, data: Any, expected_kind: str | Iterable[str]
) -> None:
    record_path = _path_for(path, data)
    if isinstance(data, JsonlRecord) and "_line" in data:
        findings.append(
            Finding(
                "schema.reserved_field",
                record_path,
                "JSONL record contains a reserved parser field",
            )
        )
    for finding in validate_envelope(data, expected_kind):
        findings.append(
            Finding(finding.code, record_path, finding.message, finding.severity)
        )


def _require_fields(
    findings: list[Finding], path: Path, data: Any, fields: Iterable[str]
) -> bool:
    if not isinstance(data, dict):
        return False
    missing = sorted(field for field in fields if field not in data)
    if missing:
        findings.append(
            Finding(
                "schema.invalid_enum",
                _path_for(path, data),
                "required fields are missing: " + ", ".join(missing),
            )
        )
        return False
    return True


def _validate_enum(
    findings: list[Finding], path: Path, record: Any, field: str, allowed: set[str]
) -> None:
    if not isinstance(record, dict) or record.get(field) not in allowed:
        findings.append(
            Finding(
                "schema.invalid_enum",
                _path_for(path, record),
                f"{field} is not an allowed value",
            )
        )


def _validate_timestamp(
    findings: list[Finding], path: Path, record: Any, field: str
) -> None:
    value = record.get(field) if isinstance(record, dict) else None
    valid = isinstance(value, str) and RFC3339_UTC_RE.fullmatch(value) is not None
    if valid:
        try:
            datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError:
            valid = False
    if not valid:
        findings.append(
            Finding(
                "schema.invalid_enum",
                _path_for(path, record),
                f"{field} must be a UTC RFC 3339 timestamp",
            )
        )


def _validate_hash(
    findings: list[Finding], path: Path, record: Any, field: str
) -> None:
    value = record.get(field) if isinstance(record, dict) else None
    if not validate_sha256(value):
        findings.append(
            Finding(
                "hash.invalid_sha256",
                _path_for(path, record),
                f"{field} must be a SHA-256 digest",
            )
        )


def _invalid_shape(
    findings: list[Finding], path: Path, record: Any, message: str
) -> None:
    findings.append(
        Finding("schema.invalid_enum", _path_for(path, record), message)
    )


def _commands_are_sanitized(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for record in value:
        if (
            not isinstance(record, dict)
            or "template" not in record
            or not set(record).issubset({"template", "description"})
            or not isinstance(record.get("template"), str)
            or not record.get("template")
            or (
                "description" in record
                and not isinstance(record.get("description"), str)
            )
        ):
            return False
    return True


def _environment_is_portable(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value).issubset(
        {"dependencies", "runtime", "drivers", "hardware_class"}
    ):
        return False
    for field in ("dependencies", "drivers"):
        if field in value:
            versions = value.get(field)
            if not isinstance(versions, dict) or any(
                not isinstance(name, str)
                or not isinstance(version, str)
                for name, version in versions.items()
            ):
                return False
    for field in ("runtime", "hardware_class"):
        if field in value and (
            not isinstance(value.get(field), str)
            or not value.get(field)
        ):
            return False
    return True


def _read_file(path: Path, kind: str, findings: list[Finding]) -> Any:
    try:
        return load_json(path) if kind == "json" else load_jsonl(path)
    except (
        json.JSONDecodeError,
        TypeError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        OSError,
        ValueError,
    ):
        findings.append(
            Finding(
                "json.malformed",
                path.name,
                "file is not valid UTF-8 JSON",
            )
        )
        return None


def _add_security_findings(
    path: Path,
    data: Any,
    findings: list[Finding],
) -> None:
    records = data if isinstance(data, list) else [data]
    for record in records:
        location = _path_for(path, record)
        try:
            security_findings = scan_value(record, location)
        except Exception:
            findings.append(
                Finding(
                    "security.scan_failed",
                    location,
                    "content security scan could not be completed",
                )
            )
            continue
        for security_finding in security_findings:
            code = (
                "security.high_confidence_content"
                if security_finding.code.startswith("credential.")
                else security_finding.code
            )
            mapped = Finding(
                code,
                security_finding.location,
                security_finding.remediation,
            )
            findings.append(mapped)


def _validate_brief(path: Path, brief: Any, findings: list[Finding]) -> None:
    _add_envelope_findings(findings, path, brief, "research-brief")
    if not _require_fields(
        findings,
        path,
        brief,
        (
            "schema_version",
            "record_type",
            "run_id",
            "mode",
            "stage",
            "created_at",
            "updated_at",
            "stage_input_hash",
            "resources",
            "constraints",
            "network_status",
        ),
    ):
        return
    if brief.get("mode") not in MODES:
        findings.append(
            Finding(
                "brief.invalid_mode",
                str(path),
                "mode must be pi, scout, or optimize",
            )
        )
    if (
        not isinstance(brief.get("run_id"), str)
        or not brief.get("run_id")
        or not isinstance(brief.get("resources"), dict)
        or not isinstance(brief.get("constraints"), dict)
        or not isinstance(brief.get("network_status"), (str, dict))
    ):
        _invalid_shape(
            findings,
            path,
            brief,
            "research brief fields have invalid types",
        )
    _validate_enum(findings, path, brief, "stage", STAGES)
    _validate_timestamp(findings, path, brief, "created_at")
    _validate_timestamp(findings, path, brief, "updated_at")
    _validate_hash(findings, path, brief, "stage_input_hash")

    resources = brief.get("resources")
    if isinstance(resources, dict) and "apis" in resources:
        apis = resources.get("apis")
        valid_apis = isinstance(apis, list) and all(
            isinstance(item, dict)
            and set(item) == {"provider", "capability", "credential_available"}
            and isinstance(item.get("credential_available"), bool)
            for item in apis
        )
        if not valid_apis:
            findings.append(
                Finding(
                    "schema.invalid_enum",
                    str(path),
                    "API resource entries must use the safe three-field contract",
                )
            )

    constraints = brief.get("constraints")
    if isinstance(constraints, dict) and "commands" in constraints:
        if not _commands_are_sanitized(constraints.get("commands")):
            _invalid_shape(
                findings,
                path,
                brief,
                "command records must be sanitized templates",
            )

    resume = brief.get("resume")
    if isinstance(resume, dict) and resume.get("enabled") is True:
        for snapshot_name in ("expected", "actual"):
            snapshot = resume.get(snapshot_name)
            if isinstance(snapshot, dict):
                _require_fields(
                    findings,
                    path,
                    snapshot,
                    (
                        "state_hash",
                        "branch",
                        "code_hash",
                        "data_hash",
                        "config_hash",
                        "environment_hash",
                    ),
                )
                for field in (
                    "state_hash",
                    "code_hash",
                    "data_hash",
                    "config_hash",
                    "environment_hash",
                ):
                    _validate_hash(findings, path, snapshot, field)
                if not isinstance(snapshot.get("branch"), str) or not snapshot.get(
                    "branch"
                ):
                    _invalid_shape(
                        findings,
                        path,
                        snapshot,
                        "resume branch must be a non-empty string",
                    )
    for finding in validate_resume_binding(brief):
        findings.append(Finding(finding.code, str(path), finding.message))


def _validate_evidence(path: Path, records: Any, findings: list[Finding]) -> None:
    if not isinstance(records, list):
        return
    fields = (
        "evidence_id",
        "kind",
        "source",
        "retrieved_at",
        "coverage",
        "content_hash",
        "status",
        "notes",
    )
    for record in records:
        _add_envelope_findings(findings, path, record, "evidence")
        _require_fields(findings, path, record, fields)
        _validate_timestamp(findings, path, record, "retrieved_at")
        _validate_hash(findings, path, record, "content_hash")
        if isinstance(record, dict) and (
            any(
                not isinstance(record.get(field), str) or not record.get(field)
                for field in ("evidence_id", "kind", "status")
            )
            or not isinstance(record.get("source"), (str, dict))
            or not isinstance(record.get("coverage"), (list, dict))
            or not isinstance(record.get("notes"), (str, list))
        ):
            _invalid_shape(
                findings, path, record, "evidence fields have invalid types"
            )


def _validate_ideas(path: Path, data: Any, findings: list[Finding]) -> None:
    _add_envelope_findings(findings, path, data, "idea-candidates")
    if not _require_fields(
        findings, path, data, ("schema_version", "record_type", "candidates")
    ):
        return
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        findings.append(
            Finding("schema.invalid_enum", str(path), "candidates must be an array")
        )
        return
    fields = (
        "candidate_id",
        "hypothesis",
        "mechanism",
        "nearest_work",
        "overlap",
        "differentiating_claim",
        "minimum_falsification_experiment",
        "resource_estimate",
        "scores",
        "risks",
        "pivots",
        "status",
    )
    overlap_fields = {
        "question",
        "method",
        "data",
        "evaluation",
        "claimed_contribution",
    }
    for candidate in candidates:
        _require_fields(findings, path, candidate, fields)
        _validate_enum(findings, path, candidate, "status", CANDIDATE_STATUSES)
        if isinstance(candidate, dict) and (
            any(
                not isinstance(candidate.get(field), str) or not candidate.get(field)
                for field in (
                    "candidate_id",
                    "hypothesis",
                    "mechanism",
                    "differentiating_claim",
                    "minimum_falsification_experiment",
                )
            )
            or not isinstance(candidate.get("nearest_work"), list)
        ):
            _invalid_shape(
                findings, path, candidate, "idea candidate fields have invalid types"
            )
        scores = candidate.get("scores") if isinstance(candidate, dict) else None
        if (
            not isinstance(scores, dict)
            or set(scores) != SCORE_FIELDS
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                for value in scores.values()
            )
        ):
            _invalid_shape(
                findings,
                path,
                candidate,
                "scores must contain the six numeric dimensions",
            )
        for field in ("risks", "pivots"):
            values = candidate.get(field) if isinstance(candidate, dict) else None
            if not isinstance(values, list) or any(
                not isinstance(value, str) for value in values
            ):
                _invalid_shape(
                    findings,
                    path,
                    candidate,
                    f"{field} must be an array of strings",
                )
        overlap = candidate.get("overlap") if isinstance(candidate, dict) else None
        if not isinstance(overlap, dict) or set(overlap) != overlap_fields:
            findings.append(
                Finding(
                    "schema.invalid_enum",
                    str(path),
                    "overlap must contain the five required dimensions",
                )
            )
        estimate = (
            candidate.get("resource_estimate") if isinstance(candidate, dict) else None
        )
        if not isinstance(estimate, dict) or not {
            "low",
            "expected",
            "high",
        }.issubset(estimate):
            findings.append(
                Finding(
                    "schema.invalid_enum",
                    str(path),
                    "resource_estimate must contain low, expected, and high",
                )
            )


def _validate_decisions(
    path: Path, records: Any, brief: Any, findings: list[Finding]
) -> None:
    if not isinstance(records, list):
        return
    fields = (
        "event_id",
        "stage",
        "decision",
        "input_hash",
        "actor",
        "timestamp",
        "rationale",
        "constraints",
        "previous_event_hash",
        "event_hash",
    )
    previous_hash: Any = None
    for record in records:
        _add_envelope_findings(findings, path, record, "decision")
        _require_fields(findings, path, record, fields)
        _validate_enum(findings, path, record, "stage", STAGES)
        _validate_enum(findings, path, record, "decision", DECISIONS)
        _validate_timestamp(findings, path, record, "timestamp")
        _validate_hash(findings, path, record, "input_hash")
        _validate_hash(findings, path, record, "event_hash")
        if isinstance(record, dict) and (
            any(
                not isinstance(record.get(field), str) or not record.get(field)
                for field in ("event_id", "actor", "rationale")
            )
            or not isinstance(record.get("constraints"), (list, dict))
        ):
            _invalid_shape(
                findings, path, record, "decision event fields have invalid types"
            )
        predecessor = record.get("previous_event_hash") if isinstance(record, dict) else None
        if predecessor is not None and not validate_sha256(predecessor):
            findings.append(
                Finding(
                    "hash.invalid_sha256",
                    _path_for(path, record),
                    "previous_event_hash must be null or a SHA-256 digest",
                )
            )
        if predecessor != previous_hash:
            findings.append(
                Finding(
                    "decision.hash_chain_broken",
                    _path_for(path, record),
                    "previous_event_hash does not match the prior event",
                )
            )
        stored_hash = record.get("event_hash") if isinstance(record, dict) else None
        if isinstance(record, dict):
            payload = {
                key: value
                for key, value in record.items()
                if key != "event_hash"
            }
            try:
                computed_hash = hash_json(payload)
            except (TypeError, ValueError):
                computed_hash = None
            if stored_hash != computed_hash:
                findings.append(
                    Finding(
                        "decision.event_hash_mismatch",
                        _path_for(path, record),
                        "event_hash does not match the canonical record",
                    )
                )
            if (
                isinstance(brief, dict)
                and record.get("decision") == "approve"
                and record.get("stage") == brief.get("stage")
                and record.get("input_hash") != brief.get("stage_input_hash")
            ):
                findings.append(
                    Finding(
                        "approval.input_hash_mismatch",
                        _path_for(path, record),
                        "approval does not match the current stage input",
                    )
                )
        previous_hash = stored_hash


def _validate_recommendations(
    path: Path, records: Any, brief: Any, findings: list[Finding]
) -> None:
    if not isinstance(records, list):
        return
    common_fields = (
        "recommendation_id",
        "stage",
        "stage_input_hash",
        "source",
        "revision",
        "content_hash",
        "permissions",
        "data_boundary",
    )
    kinds = {"skill-recommendation-card", "skill-recommendation-decision"}
    for record in records:
        _add_envelope_findings(findings, path, record, kinds)
        _require_fields(findings, path, record, common_fields)
        _validate_enum(findings, path, record, "stage", STAGES)
        _validate_hash(findings, path, record, "stage_input_hash")
        _validate_hash(findings, path, record, "content_hash")
        if isinstance(record, dict) and (
            any(
                not isinstance(record.get(field), str) or not record.get(field)
                for field in ("recommendation_id", "source", "revision")
            )
            or not isinstance(record.get("permissions"), list)
            or any(
                not isinstance(permission, str)
                for permission in record.get("permissions", [])
            )
            or not isinstance(record.get("data_boundary"), (str, list, dict))
        ):
            _invalid_shape(
                findings,
                path,
                record,
                "recommendation binding fields have invalid types",
            )
        if isinstance(record, dict) and record.get("record_type") == "skill-recommendation-card":
            _require_fields(
                findings,
                path,
                record,
                ("capability_gap", "rationale", "decision_requested", "used"),
            )
            if (
                not isinstance(record.get("capability_gap"), str)
                or not record.get("capability_gap")
                or not isinstance(record.get("rationale"), str)
                or not record.get("rationale")
                or record.get("decision_requested") not in DECISIONS
                or not isinstance(record.get("used"), bool)
            ):
                _invalid_shape(
                    findings,
                    path,
                    record,
                    "recommendation card fields have invalid types",
                )
        if isinstance(record, dict) and record.get("record_type") == "skill-recommendation-decision":
            _require_fields(
                findings,
                path,
                record,
                ("decision", "actor", "timestamp", "rationale", "constraints"),
            )
            _validate_enum(findings, path, record, "decision", DECISIONS)
            _validate_timestamp(findings, path, record, "timestamp")
            if (
                not isinstance(record.get("actor"), str)
                or not record.get("actor")
                or not isinstance(record.get("rationale"), str)
                or not isinstance(record.get("constraints"), (list, dict))
            ):
                _invalid_shape(
                    findings,
                    path,
                    record,
                    "recommendation decision fields have invalid types",
                )
    binding_data = {
        "records": records,
        "stage_input_hash": brief.get("stage_input_hash")
        if isinstance(brief, dict)
        else None,
        "stage": brief.get("stage") if isinstance(brief, dict) else None,
    }
    for finding in validate_recommendation_binding(binding_data):
        findings.append(Finding(finding.code, str(path), finding.message))


def _validate_experiments(
    path: Path, records: Any, findings: list[Finding]
) -> None:
    if not isinstance(records, list):
        return
    fields = (
        "experiment_id",
        "commit",
        "code_hash",
        "config_hash",
        "data_hash",
        "environment_hash",
        "metrics",
        "uncertainty",
        "runtime",
        "peak_memory",
        "cost",
        "status",
        "decision",
        "artifact_ids",
    )
    for record in records:
        _add_envelope_findings(findings, path, record, "experiment")
        _require_fields(findings, path, record, fields)
        _validate_enum(findings, path, record, "decision", DECISIONS)
        for field in ("code_hash", "config_hash", "data_hash", "environment_hash"):
            _validate_hash(findings, path, record, field)
        if isinstance(record, dict) and (
            not isinstance(record.get("experiment_id"), str)
            or not record.get("experiment_id")
            or not isinstance(record.get("commit"), str)
            or not record.get("commit")
            or not isinstance(record.get("metrics"), dict)
            or not isinstance(record.get("uncertainty"), dict)
            or not isinstance(record.get("runtime"), (int, float, dict))
            or isinstance(record.get("runtime"), bool)
            or not isinstance(record.get("peak_memory"), (int, float, dict))
            or isinstance(record.get("peak_memory"), bool)
            or not isinstance(record.get("cost"), (int, float, dict))
            or isinstance(record.get("cost"), bool)
            or not isinstance(record.get("status"), str)
            or not record.get("status")
            or not isinstance(record.get("artifact_ids"), list)
            or any(
                not isinstance(artifact_id, str)
                for artifact_id in record.get("artifact_ids", [])
            )
        ):
            _invalid_shape(
                findings, path, record, "experiment fields have invalid types"
            )
        if isinstance(record, dict) and record.get("status") == "crash":
            metrics = record.get("metrics")
            if (
                not isinstance(metrics, dict)
                or "primary" not in metrics
                or metrics["primary"] is not None
            ):
                findings.append(
                    Finding(
                        "experiment.crash_metric_must_be_null",
                        _path_for(path, record),
                        "crash primary metric must be null",
                    )
                )
        environment = record.get("environment") if isinstance(record, dict) else None
        if environment is not None and not _environment_is_portable(environment):
            _invalid_shape(
                findings,
                path,
                record,
                "environment record has invalid structural fields",
            )


def _validate_artifacts(
    path: Path, data: Any, run_dir: Path, findings: list[Finding]
) -> None:
    _add_envelope_findings(findings, path, data, "artifact-manifest")
    if not _require_fields(
        findings, path, data, ("schema_version", "record_type", "artifacts")
    ):
        return
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        findings.append(
            Finding("schema.invalid_enum", str(path), "artifacts must be an array")
        )
        return
    fields = ("artifact_id", "path", "kind", "sha256", "producing_run", "frozen")
    for artifact in artifacts:
        _require_fields(findings, path, artifact, fields)
        _validate_hash(findings, path, artifact, "sha256")
        if isinstance(artifact, dict) and (
            any(
                not isinstance(artifact.get(field), str) or not artifact.get(field)
                for field in ("artifact_id", "path", "kind", "producing_run")
            )
            or not isinstance(artifact.get("frozen"), bool)
        ):
            _invalid_shape(
                findings, path, artifact, "artifact fields have invalid types"
            )
        artifact_id = (
            artifact.get("artifact_id") if isinstance(artifact, dict) else None
        )
        if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(
            artifact_id
        ):
            findings.append(
                Finding(
                    "artifact.invalid_id",
                    str(path),
                    "artifact id must be a safe single-segment identifier",
                )
            )
        artifact_path = artifact.get("path") if isinstance(artifact, dict) else None
        if not validate_artifact_path(run_dir, artifact_path):
            findings.append(
                Finding(
                    "artifact.path_escapes_run",
                    str(path),
                    "artifact path must remain inside the run directory",
                )
            )


def _validate_claims(path: Path, data: Any, findings: list[Finding]) -> None:
    _add_envelope_findings(findings, path, data, "claim-evidence")
    if not _require_fields(
        findings, path, data, ("schema_version", "record_type", "claims")
    ):
        return
    claims = data.get("claims")
    if not isinstance(claims, list):
        findings.append(
            Finding("schema.invalid_enum", str(path), "claims must be an array")
        )
        return
    fields = (
        "claim_id",
        "text",
        "status",
        "run_ids",
        "artifact_ids",
        "citations",
        "caveats",
        "counter_evidence",
    )
    for claim in claims:
        _require_fields(findings, path, claim, fields)
        _validate_enum(findings, path, claim, "status", CLAIM_STATUSES)
        if isinstance(claim, dict) and (
            not isinstance(claim.get("claim_id"), str)
            or not claim.get("claim_id")
            or not isinstance(claim.get("text"), str)
            or any(
                not isinstance(claim.get(field), list)
                or any(not isinstance(item, str) for item in claim.get(field, []))
                for field in (
                    "run_ids",
                    "artifact_ids",
                    "citations",
                    "caveats",
                    "counter_evidence",
                )
            )
        ):
            _invalid_shape(
                findings, path, claim, "claim evidence fields have invalid types"
            )


def load_run(run_dir: Path) -> tuple[dict[str, Any], list[Finding]]:
    loaded: dict[str, Any] = {}
    findings: list[Finding] = []
    for filename, kind in REQUIRED_FILES.items():
        source_path = run_dir / filename
        if not source_path.is_file():
            continue
        loaded[filename] = _read_file(source_path, kind, findings)
    return loaded, findings


def validate_loaded(
    run_dir: Path,
    loaded: dict[str, Any],
    initial_findings: Iterable[Finding] = (),
) -> list[Finding]:
    findings = list(initial_findings)
    for filename in REQUIRED_FILES:
        if filename not in loaded:
            findings.append(
                Finding(
                    "run.missing_file",
                    filename,
                    f"{filename} is required",
                )
            )

    for filename, data in loaded.items():
        if data is not None:
            _add_security_findings(
                Path(filename),
                data,
                findings,
            )

    brief = loaded.get("research-brief.json")
    if brief is not None:
        _validate_brief(Path("research-brief.json"), brief, findings)
    evidence = loaded.get("evidence.jsonl")
    if evidence is not None:
        _validate_evidence(Path("evidence.jsonl"), evidence, findings)
    ideas = loaded.get("idea-candidates.json")
    if ideas is not None:
        _validate_ideas(Path("idea-candidates.json"), ideas, findings)
    decisions = loaded.get("decision-log.jsonl")
    if decisions is not None:
        _validate_decisions(Path("decision-log.jsonl"), decisions, brief, findings)
    recommendations = loaded.get("skill-recommendations.jsonl")
    if recommendations is not None:
        _validate_recommendations(
            Path("skill-recommendations.jsonl"),
            recommendations,
            brief,
            findings,
        )
    experiments = loaded.get("experiment-ledger.jsonl")
    if experiments is not None:
        _validate_experiments(
            Path("experiment-ledger.jsonl"), experiments, findings
        )
    artifacts = loaded.get("artifact-manifest.json")
    if artifacts is not None:
        _validate_artifacts(
            Path("artifact-manifest.json"), artifacts, run_dir, findings
        )
    claims = loaded.get("claim-evidence.json")
    if claims is not None:
        _validate_claims(Path("claim-evidence.json"), claims, findings)
    return findings


def validate_run(run_dir: Path) -> list[Finding]:
    loaded, parsing_findings = load_run(run_dir)
    return validate_loaded(run_dir, loaded, parsing_findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    findings = validate_run(args.run_dir)
    payload = {
        "valid": not any(item.severity == "error" for item in findings),
        "findings": [asdict(item) for item in findings],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
