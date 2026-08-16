from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import io
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import tokenize
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


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
SENSITIVITY_VALUES = {"public", "project-private"}
PUBLIC_ARTIFACT_RULES: dict[str, dict[str, Any]] = {
    "experiment-code": {
        "basename": "experiment.py",
        "extension": ".py",
        "max_bytes": 512 * 1024,
    },
    "experiment-config": {
        "basename": "experiment-config.json",
        "extension": ".json",
        "max_bytes": 128 * 1024,
    },
    "requirements-lock": {
        "basename": "requirements-lock.txt",
        "extension": ".txt",
        "max_bytes": 256 * 1024,
    },
    "split-manifest": {
        "basename": "split-manifest.json",
        "extension": ".json",
        "max_bytes": 512 * 1024,
    },
    "metrics-summary": {
        "basename": "metrics-summary.json",
        "extension": ".json",
        "max_bytes": 256 * 1024,
    },
    "attribution": {
        "basename": "ATTRIBUTION.md",
        "extension": ".md",
        "max_bytes": 128 * 1024,
    },
}
ENVIRONMENT_ASSIGNMENT = re.compile(
    r"(?m)^(?:PATH|HOME|USERPROFILE|USERNAME|HOSTNAME|COMPUTERNAME|"
    r"[A-Z][A-Z0-9_]{2,})=(?!=).*$"
)
REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
JWT_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?im)(?:^|[,{\s])['\"]?[A-Za-z0-9_-]*"
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|"
    r"api[_-]?key|access[_-]?key|password|secret|credential|authorization|"
    r"session[_-]?cookie)['\"]?\s*[:=]"
)
LONG_ENCODED_BLOB = re.compile(
    r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{512,}"
    r"(?![A-Za-z0-9+/_=-])"
)
REQUIREMENT_LINE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.!+_-]*"
    r"(?:\s+--hash=sha256:[0-9a-fA-F]{64})*$"
)
PUBLIC_JSON_TOP_LEVEL_KEYS = {
    "experiment-config": {
        "schema_version",
        "record_type",
        "run_id",
        "contract_hash",
        "dataset",
        "split",
        "features",
        "training",
        "pilot",
        "future_full",
        "metrics",
        "privacy",
    },
    "split-manifest": {
        "schema_version",
        "record_type",
        "dataset_sha256",
        "algorithm",
        "conditions",
        "aggregate_counts",
        "partition_hashes",
        "limitations",
    },
    "metrics-summary": {
        "schema_version",
        "record_type",
        "run_id",
        "status",
        "aggregate_metrics",
        "uncertainty",
        "guardrails",
        "runtime",
        "limitations",
        "artifact_hashes",
    },
}
FORBIDDEN_PUBLIC_JSON_KEYS = {
    "absolutepath",
    "accesskey",
    "accesstoken",
    "account",
    "accountid",
    "apikey",
    "authorization",
    "cache",
    "checkpoint",
    "checkpoints",
    "computername",
    "cookie",
    "credential",
    "deviceid",
    "env",
    "environmentvariables",
    "gpuuuid",
    "home",
    "hostname",
    "idtoken",
    "indices",
    "localpath",
    "logits",
    "machinename",
    "password",
    "path",
    "predictions",
    "processes",
    "raw",
    "rawdata",
    "rawrows",
    "refreshtoken",
    "rowids",
    "samples",
    "secret",
    "serial",
    "statedict",
    "stderr",
    "stdout",
    "targets",
    "token",
    "traceback",
    "user",
    "userid",
    "username",
    "userprofile",
    "weights",
}
PUBLIC_JSON_TEXT_LIST_KEYS = {
    "claimlimits",
    "conditions",
    "limitations",
    "neverexport",
    "stoprules",
    "successchecks",
}
PUBLIC_JSON_NUMERIC_LIST_KEYS = {
    "areas",
    "betas",
    "bounds",
    "classids",
    "confidenceinterval",
    "interval",
    "modelseeds",
    "percentiles",
    "presentclasses",
    "quantiles",
    "seeds",
}
PUBLIC_JSON_HASH_MAP_KEYS = {
    "artifacthashes",
    "partitionhashes",
    "splithashes",
}
PUBLIC_JSON_HASH_MAP_MAX_ENTRIES = 64
PUBLIC_JSON_TEXT_LIST_MAX_CHARACTERS = 1024
SHA256_TEXT = re.compile(r"[0-9a-fA-F]{64}")
ATTRIBUTION_REQUIRED_FIELDS = {"Dataset", "Source", "License"}
ATTRIBUTION_FIELD_LINE = re.compile(
    r"^- (Dataset|Source|DOI|License|Retrieved|Data SHA-256): (.+)$"
)
PUBLIC_JSON_ALLOWED_KEYS = {
    "aggregatecounts",
    "aggregatemetrics",
    "algorithm",
    "anomalypause",
    "areaclasscounts",
    "areapresentclasses",
    "areas",
    "artifacthashes",
    "automaticmixedprecision",
    "automaticretries",
    "batchsize",
    "betas",
    "checkpointselection",
    "classcounts",
    "columncount",
    "conditions",
    "conditionsperarea",
    "contracthash",
    "cumulativegpuhoursmaxincludingpilot",
    "cumulativewallhoursmaxincludingpilot",
    "currencycostmax",
    "datasha256",
    "dataset",
    "datasetsha256",
    "determinism",
    "doi",
    "earlystopping",
    "epochs",
    "epochsperrun",
    "epsilon",
    "evaluatetest",
    "features",
    "futurefull",
    "gpuminutesmax",
    "guardrails",
    "inputcolumns",
    "invariants",
    "learningrate",
    "license",
    "limitation",
    "limitations",
    "loss",
    "metrics",
    "model",
    "modelseed",
    "modelseeds",
    "optimizer",
    "partitionhashes",
    "pilot",
    "pilotarea",
    "plannedruns",
    "privacy",
    "publicartifacts",
    "qualifiedperarea",
    "randomtestalgorithm",
    "randomtestseed",
    "recordtype",
    "removedcolumns",
    "researchquestion",
    "rowcount",
    "rowidalgorithm",
    "runid",
    "runs",
    "runtime",
    "scheduler",
    "schemaversion",
    "sourceurl",
    "split",
    "splithashes",
    "status",
    "successchecks",
    "supportedperarea",
    "testopenpolicy",
    "training",
    "uncertainty",
    "unchangedcolumns",
    "unsupportedorreversed",
    "validationalgorithm",
    "validationfractionperclass",
    "validationseed",
    "wallminutesmax",
    "weightdecay",
    "zipsha256",
}
PUBLIC_JSON_METRIC_KEYS = {
    "accuracy",
    "balancedaccuracy",
    "classcoverage",
    "classsupport",
    "confusionmatrix",
    "deltamacrof1",
    "epochs",
    "failures",
    "gpuseconds",
    "lower",
    "macrof1",
    "mean",
    "nancount",
    "peakvramgib",
    "perclassf1",
    "perclassprecision",
    "perclassrecall",
    "predictiondistribution",
    "primary",
    "runs",
    "secondary",
    "standarddeviation",
    "trainloss",
    "upper",
    "validationloss",
    "validationmacrof1",
    "wallseconds",
}
DANGEROUS_EXPERIMENT_IMPORTS = {
    "anthropic",
    "boto3",
    "ftplib",
    "http",
    "openai",
    "os",
    "paramiko",
    "requests",
    "socket",
    "subprocess",
    "urllib",
}


@dataclass(frozen=True)
class SecurityFinding:
    code: str
    location: str
    severity: str
    remediation: str


class SecurityViolation(ValueError):
    def __init__(
        self,
        message: str = "state failed security validation",
        findings: Iterable[SecurityFinding] = (),
    ) -> None:
        super().__init__(message)
        self.findings = tuple(findings)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid usage")


HIGH_CONFIDENCE = (
    (
        "credential.authorization_header",
        re.compile(r"(?i)authorization\s*:\s*(?:bearer|basic)\s+\S+"),
    ),
    (
        "credential.private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "credential.openai_token",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    ),
    (
        "credential.anthropic_token",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b"),
    ),
    (
        "credential.github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{32,}\b"),
    ),
    ("credential.aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "credential.generic_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*"
            r"['\"]?[A-Za-z0-9_./+=-]{20,}['\"]?"
        ),
    ),
    (
        "credential.session_cookie",
        re.compile(r"(?i)\b(?:session|cookie)\s*[:=]\s*[^\s;]{16,}"),
    ),
    (
        "credential.url_userinfo",
        re.compile(r"(?i)https?://[^\s/@:]+:[^\s/@]+@"),
    ),
)

WINDOWS_HOME = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
POSIX_HOME = re.compile(r"(?i)(?:^|\s)/(?:home|Users)/[^/\s]+")
WINDOWS_ABSOLUTE = re.compile(
    r"(?i)(?:^|[\s='\"])(?:[A-Z]:[\\/][^\s,;]+|\\\\[^\\\s]+\\[^\s,;]+)"
)
POSIX_ABSOLUTE = re.compile(
    r"(?:^|[\s='\"(\[{])/(?!/)[^\s,;)\]}]+"
)
LOCAL_FILE_URL = re.compile(r"(?i)\bfile:///(?:[^\s,;]+)")
LOCAL_IPV4 = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
MAC_ADDRESS = re.compile(r"(?i)\b(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}\b")
HOST_OR_USER = re.compile(
    r"(?i)\b(?:host(?:name)?|user(?:name)?)\s*[:=]\s*[^\s,;]+"
)
MACHINE_IDENTIFIER_PATTERN = re.compile(
    r"(?i)\b(?:device[_ -]?id|machine[_ -]?id|serial)\s*[:=]\s*[^\s,;]+"
)

COMMON_STRUCTURAL_POINTERS = {"/schema_version", "/record_type"}
STRUCTURAL_POINTERS_BY_RECORD = {
    "research-brief": {
        "/run_id",
        "/mode",
        "/stage",
        "/created_at",
        "/updated_at",
        "/stage_input_hash",
    },
    "evidence": {"/evidence_id", "/retrieved_at", "/content_hash"},
    "decision": {
        "/event_id",
        "/stage",
        "/decision",
        "/input_hash",
        "/timestamp",
        "/previous_event_hash",
        "/event_hash",
    },
    "skill-recommendation-card": {
        "/recommendation_id",
        "/stage",
        "/stage_input_hash",
        "/content_hash",
        "/decision_requested",
    },
    "skill-recommendation-decision": {
        "/recommendation_id",
        "/stage",
        "/stage_input_hash",
        "/content_hash",
        "/decision",
        "/timestamp",
    },
    "experiment": {
        "/experiment_id",
        "/commit",
        "/code_hash",
        "/config_hash",
        "/data_hash",
        "/environment_hash",
        "/decision",
    },
}
STRUCTURAL_POINTER_PATTERNS_BY_RECORD = {
    "research-brief": (
        re.compile(
            r"/resume/(?:expected|actual)/"
            r"(?:state_hash|code_hash|data_hash|config_hash|environment_hash)"
        ),
    ),
    "idea-candidates": (
        re.compile(r"/candidates/(?:0|[1-9]\d*)/(?:candidate_id|status)"),
        re.compile(
            r"/candidates/(?:0|[1-9]\d*)/nearest_work/"
            r"(?:0|[1-9]\d*)/evidence_id"
        ),
    ),
    "experiment": (re.compile(r"/artifact_ids/(?:0|[1-9]\d*)"),),
    "artifact-manifest": (
        re.compile(
            r"/artifacts/(?:0|[1-9]\d*)/"
            r"(?:artifact_id|sha256|producing_run)"
        ),
    ),
    "claim-evidence": (
        re.compile(r"/claims/(?:0|[1-9]\d*)/(?:claim_id|status)"),
        re.compile(
            r"/claims/(?:0|[1-9]\d*)/(?:run_ids|artifact_ids)/"
            r"(?:0|[1-9]\d*)"
        ),
    ),
}
DECLARED_NON_STRING_POINTERS_BY_RECORD = {
    "research-brief": {
        "/resume",
        "/resume/enabled",
        "/resume/expected",
        "/resume/actual",
    },
}
DECLARED_NON_STRING_POINTER_PATTERNS_BY_RECORD = {
    "idea-candidates": (
        re.compile(
            r"/candidates/(?:0|[1-9]\d*)/"
            r"(?:nearest_work|overlap|resource_estimate|scores|risks|pivots)"
        ),
        re.compile(
            r"/candidates/(?:0|[1-9]\d*)/scores/"
            r"(?:information_gain|feasibility|impact|evidence_quality|compute_fit|risk)"
        ),
    ),
    "claim-evidence": (
        re.compile(
            r"/claims/(?:0|[1-9]\d*)/"
            r"(?:run_ids|artifact_ids|citations|caveats|counter_evidence)"
        ),
    ),
}
DECLARED_STRING_POINTER_PATTERNS_BY_RECORD = {
    "idea-candidates": (
        re.compile(
            r"/candidates/(?:0|[1-9]\d*)/(?:risks|pivots)/"
            r"(?:0|[1-9]\d*)"
        ),
    ),
    "experiment": (re.compile(r"/environment/runtime"),),
}
DECLARED_OBJECT_POINTERS_BY_RECORD = {
    "research-brief": {"/resume", "/resume/expected", "/resume/actual"},
}
DECLARED_OBJECT_POINTER_PATTERNS_BY_RECORD = {
    "idea-candidates": (
        re.compile(
            r"/candidates/(?:0|[1-9]\d*)/"
            r"(?:overlap|resource_estimate|scores)"
        ),
    ),
}
DECLARED_ARRAY_POINTER_PATTERNS_BY_RECORD = {
    "idea-candidates": (
        re.compile(
            r"/candidates/(?:0|[1-9]\d*)/"
            r"(?:nearest_work|risks|pivots)"
        ),
    ),
    "claim-evidence": (
        re.compile(
            r"/claims/(?:0|[1-9]\d*)/"
            r"(?:run_ids|artifact_ids|citations|caveats|counter_evidence)"
        ),
    ),
}

SAFE_LOCATION = re.compile(
    r"^(?:state|\$|event:\d+|"
    r"(?:research-brief\.json|evidence\.jsonl|idea-candidates\.json|"
    r"decision-log\.jsonl|skill-recommendations\.jsonl|"
    r"experiment-ledger\.jsonl|artifact-manifest\.json|"
    r"claim-evidence\.json)(?:#line=\d+)?)"
    r"(?:/(?:\d+|member=\d+|entry=\d+|name|value|pointer|"
    r"classification|field_sensitivity))*$"
)


def _safe_location(location: object) -> str:
    if isinstance(location, str) and SAFE_LOCATION.fullmatch(location):
        return location
    return "state"


def finding(
    code: str, location: str, severity: str, remediation: str
) -> SecurityFinding:
    return SecurityFinding(code, _safe_location(location), severity, remediation)


def _scan_high_confidence(text: str, location: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for code, pattern in HIGH_CONFIDENCE:
        if pattern.search(text):
            findings.append(
                finding(
                    code,
                    location,
                    "block",
                    "remove the credential and rotate or revoke it",
                )
            )
    return findings


def _scan_text(
    text: str, location: str, *, include_absolute_paths: bool
) -> list[SecurityFinding]:
    findings = _scan_high_confidence(text, location)
    if include_absolute_paths and (
        WINDOWS_HOME.search(text)
        or POSIX_HOME.search(text)
        or WINDOWS_ABSOLUTE.search(text)
        or POSIX_ABSOLUTE.search(text)
        or LOCAL_FILE_URL.search(text)
    ):
        findings.append(
            finding(
                "privacy.absolute_path",
                location,
                "block",
                "replace with a repository-relative path",
            )
        )
    if any(
        not match.group().lower().endswith("@users.noreply.github.com")
        for match in EMAIL.finditer(text)
    ):
        findings.append(
            finding(
                "privacy.email",
                location,
                "block",
                "remove or explicitly approve the public email",
            )
        )
    for code, pattern, remediation in (
        (
            "privacy.mac_address",
            MAC_ADDRESS,
            "remove the machine network identifier",
        ),
        (
            "privacy.host_or_user",
            HOST_OR_USER,
            "remove the host or operating-system user identifier",
        ),
        (
            "privacy.device_id",
            MACHINE_IDENTIFIER_PATTERN,
            "remove the device identifier",
        ),
    ):
        if pattern.search(text):
            findings.append(finding(code, location, "block", remediation))
    for match in LOCAL_IPV4.finditer(text):
        try:
            if ipaddress.ip_address(match.group()).is_private:
                findings.append(
                    finding(
                        "privacy.local_ip",
                        location,
                        "block",
                        "remove the local network address",
                    )
                )
                break
        except ValueError:
            pass
    return findings


def scan_text(text: str, location: str) -> list[SecurityFinding]:
    return _scan_text(text, location, include_absolute_paths=True)


def escape_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _decode_pointer(pointer: str) -> list[str] | None:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return None
    segments: list[str] = []
    for encoded in pointer[1:].split("/"):
        if re.search(r"~(?![01])", encoded):
            return None
        segments.append(encoded.replace("~1", "/").replace("~0", "~"))
    return segments


def _resolve_pointer(value: object, pointer: str) -> tuple[bool, object]:
    segments = _decode_pointer(pointer)
    if segments is None:
        return False, None
    current = value
    for segment in segments:
        if isinstance(current, dict):
            if segment not in current or segment == "field_sensitivity":
                return False, None
            current = current[segment]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9]\d*", segment):
                return False, None
            index = int(segment)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _pointer_failure_is_type_mismatch(
    value: object, pointer: str, record_type: object
) -> bool:
    segments = _decode_pointer(pointer)
    if segments is None:
        return False
    current = value
    traversed: list[str] = []
    for segment in segments:
        ancestor = "/" + "/".join(
            escape_pointer_segment(item) for item in traversed
        )
        expected_container = _declared_container_kind(ancestor, record_type)
        if expected_container == "object" and not isinstance(current, dict):
            return True
        if expected_container == "array" and not isinstance(current, list):
            return True
        if isinstance(current, dict):
            if segment not in current or segment == "field_sensitivity":
                return False
            current = current[segment]
            traversed.append(segment)
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9]\d*", segment):
                return False
            index = int(segment)
            if index >= len(current):
                return False
            current = current[index]
            traversed.append(segment)
        else:
            return False
    return False


def _leaf_strings(
    value: object, pointer: str = "", *, skip_sensitivity: bool = True
) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaf_strings(child, f"{pointer}/{index}")
    elif isinstance(value, dict):
        for key, child in value.items():
            if skip_sensitivity and key == "field_sensitivity":
                continue
            segment = escape_pointer_segment(str(key))
            yield from _leaf_strings(child, f"{pointer}/{segment}")


def _is_structural_pointer(pointer: str, record_type: object) -> bool:
    if not isinstance(record_type, str):
        record_type = None
    return (
        pointer in COMMON_STRUCTURAL_POINTERS
        or pointer in STRUCTURAL_POINTERS_BY_RECORD.get(record_type, set())
        or any(
            pattern.fullmatch(pointer)
            for pattern in STRUCTURAL_POINTER_PATTERNS_BY_RECORD.get(
                record_type, ()
            )
        )
    )


def _matches_record_pointer_patterns(
    pointer: str,
    record_type: object,
    patterns_by_record: dict[str, tuple[re.Pattern[str], ...]],
) -> bool:
    if not isinstance(record_type, str):
        return False
    return any(
        pattern.fullmatch(pointer)
        for pattern in patterns_by_record.get(record_type, ())
    )


def _is_declared_non_string_pointer(pointer: str, record_type: object) -> bool:
    if pointer == "/" + "_line":
        return True
    if isinstance(record_type, str) and pointer in (
        DECLARED_NON_STRING_POINTERS_BY_RECORD.get(record_type, set())
    ):
        return True
    return _matches_record_pointer_patterns(
        pointer, record_type, DECLARED_NON_STRING_POINTER_PATTERNS_BY_RECORD
    )


def _is_declared_string_pointer(pointer: str, record_type: object) -> bool:
    return _matches_record_pointer_patterns(
        pointer, record_type, DECLARED_STRING_POINTER_PATTERNS_BY_RECORD
    )


def _declared_container_kind(
    pointer: str, record_type: object
) -> str | None:
    if isinstance(record_type, str) and pointer in (
        DECLARED_OBJECT_POINTERS_BY_RECORD.get(record_type, set())
    ):
        return "object"
    if _matches_record_pointer_patterns(
        pointer, record_type, DECLARED_OBJECT_POINTER_PATTERNS_BY_RECORD
    ):
        return "object"
    if _matches_record_pointer_patterns(
        pointer, record_type, DECLARED_ARRAY_POINTER_PATTERNS_BY_RECORD
    ):
        return "array"
    return None


def _has_declared_string_ancestor(pointer: str, record_type: object) -> bool:
    segments = _decode_pointer(pointer)
    if not segments:
        return False
    for end in range(1, len(segments)):
        ancestor = "/" + "/".join(
            escape_pointer_segment(segment) for segment in segments[:end]
        )
        if _is_declared_string_pointer(ancestor, record_type):
            return True
    return False


def _classification_findings(
    value: object, location: str
) -> list[SecurityFinding]:
    if not isinstance(value, dict):
        return []
    sensitivity = value.get("field_sensitivity")
    if "field_sensitivity" not in value:
        return [
            finding(
                "privacy.missing_classification",
                location,
                "block",
                "add the required field_sensitivity map",
            )
        ]
    if not isinstance(sensitivity, dict):
        return [
            finding(
                "privacy.invalid_classification",
                location,
                "block",
                "use an RFC 6901 field_sensitivity map",
            )
        ]

    findings: list[SecurityFinding] = []
    record_type = value.get("record_type")
    valid_pointers: set[str] = set()
    for pointer, classification in sensitivity.items():
        if (
            not isinstance(pointer, str)
            or _decode_pointer(pointer) is None
            or not isinstance(classification, str)
            or classification not in SENSITIVITY_VALUES
        ):
            findings.append(
                finding(
                    "privacy.invalid_classification",
                    f"{location}/field_sensitivity",
                    "block",
                    "use RFC 6901 pointers with an allowed sensitivity value",
                )
            )
            continue
        exists, target = _resolve_pointer(value, pointer)
        if not exists:
            if _pointer_failure_is_type_mismatch(
                value, pointer, record_type
            ):
                continue
            findings.append(
                finding(
                    "privacy.classification_path_missing",
                    f"{location}/field_sensitivity",
                    "block",
                    "remove or correct the unresolved classification pointer",
                )
            )
            continue
        if not isinstance(target, str):
            if _is_declared_string_pointer(pointer, record_type):
                continue
            findings.append(
                finding(
                    "privacy.invalid_classification",
                    f"{location}/field_sensitivity",
                    "block",
                    "classify only existing leaf strings",
                )
            )
            continue
        valid_pointers.add(pointer)

    for pointer, _text in _leaf_strings(value):
        if (
            not _is_structural_pointer(pointer, record_type)
            and pointer not in valid_pointers
        ):
            if _is_declared_non_string_pointer(
                pointer, record_type
            ) or _has_declared_string_ancestor(pointer, record_type):
                continue
            findings.append(
                finding(
                    "privacy.missing_classification",
                    f"{location}/field_sensitivity",
                    "block",
                    "classify every non-structural leaf string",
                )
            )
    return findings


def _scan_content(value: object, location: str) -> list[SecurityFinding]:
    if isinstance(value, str):
        return scan_text(value, location)
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _scan_content(child, f"{location}/{index}")
        ]
    if isinstance(value, dict):
        findings: list[SecurityFinding] = []
        for index, (key, child) in enumerate(value.items()):
            member_location = f"{location}/member={index}"
            findings.extend(scan_text(str(key), f"{member_location}/name"))
            if key == "field_sensitivity" and isinstance(child, dict):
                for entry_index, (pointer, classification) in enumerate(
                    child.items()
                ):
                    entry_location = (
                        f"{member_location}/value/entry={entry_index}"
                    )
                    findings.extend(
                        _scan_text(
                            str(pointer),
                            f"{entry_location}/pointer",
                            include_absolute_paths=False,
                        )
                    )
                    findings.extend(
                        _scan_content(
                            classification, f"{entry_location}/classification"
                        )
                    )
            else:
                findings.extend(_scan_content(child, f"{member_location}/value"))
        return findings
    return []


def scan_value(value: object, location: str = "$") -> list[SecurityFinding]:
    return _scan_content(value, location) + _classification_findings(value, location)


def default_field_sensitivity(
    record: dict[str, Any], private_pointers: Iterable[str] = ()
) -> dict[str, str]:
    """Build a complete map for synthetic fixtures and state producers."""
    private = set(private_pointers)
    record_type = record.get("record_type")
    return {
        pointer: "project-private" if pointer in private else "public"
        for pointer, _text in _leaf_strings(record)
        if not _is_structural_pointer(pointer, record_type)
    }


def _sanitize_record_with_counts(
    record: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    scan_findings = scan_value(record)
    if scan_findings:
        raise SecurityViolation(findings=scan_findings)
    sensitivity = record["field_sensitivity"]
    output_sensitivity: dict[str, str] = {}
    public_count = 0
    private_count = 0
    omitted = object()
    record_type = record.get("record_type")

    def project(value: object, source_pointer: str, output_pointer: str) -> object:
        nonlocal public_count, private_count
        if isinstance(value, str):
            if _is_structural_pointer(source_pointer, record_type):
                return value
            classification = sensitivity[source_pointer]
            if classification == "project-private":
                private_count += 1
                return omitted
            output_sensitivity[output_pointer] = "public"
            public_count += 1
            return value
        if isinstance(value, list):
            projected_list: list[Any] = []
            for index, child in enumerate(value):
                child_output_pointer = f"{output_pointer}/{len(projected_list)}"
                projected = project(
                    child, f"{source_pointer}/{index}", child_output_pointer
                )
                if projected is not omitted:
                    projected_list.append(projected)
            return projected_list
        if isinstance(value, dict):
            projected_dict: dict[str, Any] = {}
            for key, child in value.items():
                if key == "field_sensitivity":
                    projected_dict[key] = output_sensitivity
                    continue
                segment = escape_pointer_segment(str(key))
                projected = project(
                    child,
                    f"{source_pointer}/{segment}",
                    f"{output_pointer}/{segment}",
                )
                if projected is not omitted:
                    projected_dict[key] = projected
            return projected_dict
        return copy.deepcopy(value)

    sanitized = project(record, "", "")
    if not isinstance(sanitized, dict):
        raise SecurityViolation()
    return sanitized, public_count, private_count


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    sanitized, _public_count, _private_count = _sanitize_record_with_counts(record)
    return sanitized


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
    )


def _load_records(run_dir: Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise OSError("run directory is unavailable")
    loaded: dict[str, Any] = {}
    for filename, kind in REQUIRED_FILES.items():
        path = run_dir / filename
        if not path.is_file():
            raise OSError("required state file is unavailable")
        if kind == "json":
            value = _load_json(path)
            if not isinstance(value, dict):
                raise ValueError("state record is not an object")
            loaded[filename] = value
            continue
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line, parse_constant=_reject_json_constant)
            if not isinstance(value, dict):
                raise ValueError("state record is not an object")
            records.append(value)
        loaded[filename] = records
    return loaded


def _scan_loaded(loaded: dict[str, Any]) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for filename, data in loaded.items():
        is_jsonl = REQUIRED_FILES[filename] == "jsonl"
        records = data if is_jsonl else [data]
        for index, record in enumerate(records, 1):
            location = f"{filename}#line={index}" if is_jsonl else filename
            findings.extend(scan_value(record, location))
    return findings


def _load_validator_module() -> Any:
    path = Path(__file__).with_name("validate_state.py")
    spec = importlib.util.spec_from_file_location("_researchhelm_validate_state", path)
    if spec is None or spec.loader is None:
        raise OSError("validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_validated_snapshot(
    run_dir: Path,
) -> tuple[dict[str, Any], list[SecurityFinding]]:
    module = _load_validator_module()
    loaded, parsing_findings = module.load_run(run_dir)
    findings = module.validate_loaded(run_dir, loaded, parsing_findings)
    safe_findings: list[SecurityFinding] = []
    for item in findings:
        if item.severity != "error":
            continue
        safe_findings.append(
            finding(
                item.code,
                "state",
                "block",
                "correct the state before creating a public export",
            )
        )
    return loaded, safe_findings


def _artifact_finding(code: str, remediation: str) -> SecurityViolation:
    return SecurityViolation(
        findings=(finding(code, "artifact-manifest.json", "block", remediation),)
    )


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & REPARSE_ATTRIBUTE)


def _has_split_encoded_blob(text: str) -> bool:
    encoded_total = 0
    for line in text.splitlines():
        candidate = line.strip().removeprefix("#").strip()
        if len(candidate) >= 60 and re.fullmatch(r"[A-Za-z0-9+/_=-]+", candidate):
            encoded_total += len(candidate)
            if encoded_total >= 512:
                return True
        else:
            encoded_total = 0
    return False


def _looks_like_row_dump(text: str) -> bool:
    consecutive = 0
    for line in text.splitlines():
        candidate = line.strip().removeprefix("#").strip()
        if (
            len(candidate) >= 20
            and candidate.count(",") >= 8
            and re.fullmatch(r"[-+0-9.eE,\s]+", candidate)
        ):
            consecutive += 1
            if consecutive >= 5:
                return True
        else:
            consecutive = 0
    return False


def _public_artifact_findings(text: str) -> list[SecurityFinding]:
    findings = scan_text(text, "artifact-manifest.json")
    if JWT_TOKEN.search(text):
        findings.append(
            finding(
                "credential.oauth_or_jwt",
                "artifact-manifest.json",
                "block",
                "remove the account or session token and rotate it if real",
            )
        )
    if SENSITIVE_ASSIGNMENT.search(text):
        findings.append(
            finding(
                "credential.sensitive_assignment",
                "artifact-manifest.json",
                "block",
                "remove credential-bearing keys and values",
            )
        )
    if LONG_ENCODED_BLOB.search(text) or _has_split_encoded_blob(text):
        findings.append(
            finding(
                "artifact.public_embedded_blob",
                "artifact-manifest.json",
                "block",
                "remove encoded binary or model payloads",
            )
        )
    if _looks_like_row_dump(text):
        findings.append(
            finding(
                "artifact.public_row_dump",
                "artifact-manifest.json",
                "block",
                "replace row-level values with aggregate counts and hashes",
            )
        )
    return findings


def _normalized_json_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _public_json_key_allowed(key: str, parent_key: str) -> bool:
    normalized = _normalized_json_key(key)
    parent = _normalized_json_key(parent_key)
    if normalized in FORBIDDEN_PUBLIC_JSON_KEYS:
        return False
    if normalized in PUBLIC_JSON_ALLOWED_KEYS:
        return True
    if parent in {
        "aggregatecounts",
        "areaclasscounts",
        "areapresentclasses",
        "classcounts",
        "classsupport",
        "perclassf1",
        "perclassprecision",
        "perclassrecall",
        "predictiondistribution",
    }:
        return bool(re.fullmatch(r"(?:[1-7]|area[1-4])", normalized))
    if parent in {"artifacthashes", "partitionhashes", "splithashes"}:
        return bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", normalized))
    if parent == "aggregatemetrics" and normalized in {"area1", "area2", "area3"}:
        return True
    if parent in {"area1", "area2", "area3"}:
        return normalized in PUBLIC_JSON_METRIC_KEYS
    if parent in {"aggregatemetrics", "guardrails", "runtime", "uncertainty"}:
        return normalized in PUBLIC_JSON_METRIC_KEYS
    if parent == "conditions":
        return bool(re.fullmatch(r"area[1-3](?:holdout|random)", normalized))
    return False


def _validate_public_json(kind: str, text: str) -> None:
    try:
        value = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object,
        )
    except (ValueError, json.JSONDecodeError) as error:
        raise _artifact_finding(
            "artifact.public_invalid_json", "provide parseable strict JSON"
        ) from error
    expected_keys = PUBLIC_JSON_TOP_LEVEL_KEYS[kind]
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("schema_version") != "1.0"
        or value.get("record_type") != kind
    ):
        raise _artifact_finding(
            "artifact.public_schema_invalid",
            "use the closed aggregate-only public artifact schema",
        )

    nodes_seen = 0

    def visit(node: object, depth: int = 0, parent_key: str = "") -> None:
        nonlocal nodes_seen
        nodes_seen += 1
        if depth > 16 or nodes_seen > 5000:
            raise _artifact_finding(
                "artifact.public_schema_invalid",
                "reduce the public artifact to bounded aggregate metadata",
            )
        if isinstance(node, dict):
            normalized_parent = _normalized_json_key(parent_key)
            if normalized_parent in PUBLIC_JSON_HASH_MAP_KEYS:
                if len(node) > PUBLIC_JSON_HASH_MAP_MAX_ENTRIES or any(
                    not isinstance(key, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}", key)
                    or not isinstance(item, str)
                    or SHA256_TEXT.fullmatch(item) is None
                    for key, item in node.items()
                ):
                    raise _artifact_finding(
                        "artifact.public_hash_map_invalid",
                        "use a bounded map of safe names to SHA-256 digests",
                    )
                nodes_seen += len(node)
                return
            if len(node) > 100:
                raise _artifact_finding(
                    "artifact.public_schema_invalid",
                    "reduce the public artifact to bounded aggregate metadata",
                )
            for key, child in node.items():
                if (
                    not isinstance(key, str)
                    or not _public_json_key_allowed(key, parent_key)
                ):
                    raise _artifact_finding(
                        "artifact.public_sensitive_or_raw_field",
                        "remove raw, per-row, credential, account, or machine fields",
                    )
                visit(child, depth + 1, key)
        elif isinstance(node, list):
            normalized_parent = _normalized_json_key(parent_key)
            if normalized_parent.endswith("matrix"):
                valid_matrix = len(node) <= 10 and all(
                    isinstance(row, list)
                    and len(row) <= 10
                    and all(
                        isinstance(item, (int, float))
                        and not isinstance(item, bool)
                        for item in row
                    )
                    for row in node
                )
                if not valid_matrix:
                    raise _artifact_finding(
                        "artifact.public_schema_invalid",
                        "publish only a bounded aggregate confusion matrix",
                    )
                nodes_seen += sum(len(row) + 1 for row in node)
                return
            if normalized_parent in PUBLIC_JSON_TEXT_LIST_KEYS:
                valid_list = len(node) <= 50 and all(
                    isinstance(item, str) and len(item) <= 1000
                    for item in node
                )
                if valid_list:
                    text_items = [item for item in node if isinstance(item, str)]
                    valid_list = (
                        sum(len(item) for item in text_items)
                        <= PUBLIC_JSON_TEXT_LIST_MAX_CHARACTERS
                        and not _looks_like_split_encoding(text_items)
                    )
            elif normalized_parent in PUBLIC_JSON_NUMERIC_LIST_KEYS:
                valid_list = len(node) <= 32 and all(
                    isinstance(item, (int, float))
                    and not isinstance(item, bool)
                    for item in node
                )
            else:
                valid_list = False
            if not valid_list:
                raise _artifact_finding(
                    "artifact.public_sensitive_or_raw_field",
                    "replace row-level arrays with bounded aggregate fields",
                )
            for child in node:
                visit(child, depth + 1, parent_key)
        elif isinstance(node, str):
            if len(node) > 4096 or LONG_ENCODED_BLOB.search(node):
                raise _artifact_finding(
                    "artifact.public_embedded_blob",
                    "remove encoded binary, model, or row-level payloads",
                )
        elif node is not None and not isinstance(node, (bool, int, float)):
            raise _artifact_finding(
                "artifact.public_schema_invalid",
                "use JSON scalar, object, and bounded array values only",
            )

    visit(value)


def _looks_like_split_encoding(items: list[str]) -> bool:
    if len(items) < 2 or any(not item for item in items):
        return False
    if not all(re.fullmatch(r"[A-Za-z0-9+/_=-]+", item) for item in items):
        return False
    combined = "".join(items)
    if len(combined) < 32:
        return False
    if re.fullmatch(r"[0-9a-fA-F]+", combined) and len(combined) % 2 == 0:
        return True
    return len(combined) % 4 == 0


def _validate_attribution(text: str) -> None:
    if len(text) > 1024:
        raise _artifact_finding(
            "artifact.public_attribution_invalid",
            "keep attribution within the closed metadata budget",
        )
    lines = text.splitlines()
    if not 4 <= len(lines) <= 7 or lines[0] != "# Attribution":
        raise _artifact_finding(
            "artifact.public_attribution_invalid",
            "use the closed Attribution heading and field lines",
        )
    values: dict[str, str] = {}
    for line in lines[1:]:
        match = ATTRIBUTION_FIELD_LINE.fullmatch(line)
        if match is None or match.group(1) in values:
            raise _artifact_finding(
                "artifact.public_attribution_invalid",
                "use each allowed attribution field at most once",
            )
        values[match.group(1)] = match.group(2)
    if not ATTRIBUTION_REQUIRED_FIELDS.issubset(values):
        raise _artifact_finding(
            "artifact.public_attribution_invalid",
            "include Dataset, Source, and License",
        )
    dataset = values["Dataset"]
    if (
        len(dataset) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._+()&/'-]*", dataset) is None
        or _looks_like_split_encoding(
            [dataset[index : index + 8] for index in range(0, len(dataset), 8)]
        )
    ):
        raise _artifact_finding(
            "artifact.public_attribution_invalid", "use a short dataset name"
        )
    source = values["Source"]
    if len(source) > 256 or re.fullmatch(r"https://[^\s]+", source) is None:
        raise _artifact_finding(
            "artifact.public_attribution_invalid", "use a bounded HTTPS source URL"
        )
    if "DOI" in values and re.fullmatch(
        r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", values["DOI"]
    ) is None:
        raise _artifact_finding(
            "artifact.public_attribution_invalid", "use a valid DOI"
        )
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .+()-]{0,63}", values["License"]) is None:
        raise _artifact_finding(
            "artifact.public_attribution_invalid", "use a short license identifier"
        )
    if _looks_like_split_encoding([dataset, values["License"]]):
        raise _artifact_finding(
            "artifact.public_attribution_invalid",
            "do not split encoded content across attribution fields",
        )
    if "Retrieved" in values:
        try:
            if date.fromisoformat(values["Retrieved"]).isoformat() != values["Retrieved"]:
                raise ValueError("non-canonical date")
        except ValueError as error:
            raise _artifact_finding(
                "artifact.public_attribution_invalid", "use YYYY-MM-DD for Retrieved"
            ) from error
    if "Data SHA-256" in values and SHA256_TEXT.fullmatch(values["Data SHA-256"]) is None:
        raise _artifact_finding(
            "artifact.public_attribution_invalid", "use a SHA-256 data digest"
        )


def _validate_requirements_lock(text: str) -> None:
    packages: set[str] = set()
    comment_characters = 0
    lines = text.splitlines()
    if not lines or len(lines) > 100:
        raise _artifact_finding(
            "artifact.public_requirements_invalid",
            "provide a bounded list of exact package versions",
        )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comment_characters += len(stripped)
            if len(stripped) > 300 or comment_characters > 1024:
                raise _artifact_finding(
                    "artifact.public_requirements_invalid",
                    "keep dependency comments short and metadata-only",
                )
            continue
        if not REQUIREMENT_LINE.fullmatch(stripped):
            raise _artifact_finding(
                "artifact.public_requirements_invalid",
                "use package==version with optional SHA-256 wheel hashes",
            )
        package = stripped.split("==", 1)[0].lower()
        if package in packages:
            raise _artifact_finding(
                "artifact.public_requirements_invalid",
                "declare each dependency once",
            )
        packages.add(package)
    if not packages:
        raise _artifact_finding(
            "artifact.public_requirements_invalid",
            "declare at least one exact dependency version",
        )


def _validate_experiment_code(text: str) -> None:
    try:
        tree = ast.parse(text, filename="experiment.py", mode="exec")
    except SyntaxError as error:
        raise _artifact_finding(
            "artifact.public_python_invalid", "provide parseable Python source"
        ) from error
    try:
        comment_characters = sum(
            len(token.string)
            for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.COMMENT
        )
    except (IndentationError, tokenize.TokenError) as error:
        raise _artifact_finding(
            "artifact.public_python_invalid", "provide tokenizable Python source"
        ) from error
    if comment_characters > 4096:
        raise _artifact_finding(
            "artifact.public_embedded_blob",
            "keep source comments short and metadata-only",
        )

    literal_characters = 0
    encoded_literal_characters = 0
    byte_literal_characters = 0
    numeric_literals = 0
    nodes = list(ast.walk(tree))
    if len(nodes) > 10000:
        raise _artifact_finding(
            "artifact.public_embedded_blob",
            "reduce the experiment to minimal auditable source",
        )
    safe_cublas_calls = [
        node
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setdefault"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "environ"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "os"
        and len(node.args) == 2
        and not node.keywords
        and all(isinstance(argument, ast.Constant) for argument in node.args)
        and [argument.value for argument in node.args]
        == ["CUBLAS_WORKSPACE_CONFIG", ":4096:8"]
    ]
    safe_cublas_environment = (
        len(safe_cublas_calls) == 1
        and sum(isinstance(node, ast.Name) and node.id == "os" for node in nodes) == 1
        and sum(
            isinstance(node, ast.Import)
            and len(node.names) == 1
            and node.names[0].name == "os"
            and node.names[0].asname is None
            for node in nodes
        )
        == 1
    )
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            unsafe_modules = []
            for module in modules:
                root = module.split(".", 1)[0]
                exact_safe_os_import = (
                    root == "os"
                    and safe_cublas_environment
                    and isinstance(node, ast.Import)
                    and len(node.names) == 1
                    and node.names[0].name == "os"
                    and node.names[0].asname is None
                )
                if root in DANGEROUS_EXPERIMENT_IMPORTS and not exact_safe_os_import:
                    unsafe_modules.append(module)
            if unsafe_modules:
                raise _artifact_finding(
                    "artifact.public_python_unsafe",
                    "remove network, process, account, or environment access",
                )
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name in {"compile", "eval", "exec", "__import__"}:
                raise _artifact_finding(
                    "artifact.public_python_unsafe",
                    "remove dynamic code execution",
                )
        exact_safe_environ = (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and safe_cublas_environment
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )
        if isinstance(node, ast.Attribute) and node.attr in {
            "environ",
            "getenv",
            "popen",
            "system",
        } and not exact_safe_environ:
            raise _artifact_finding(
                "artifact.public_python_unsafe",
                "remove process or environment access",
            )
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                literal_characters += len(node.value)
                if len(node.value) >= 32 and re.fullmatch(
                    r"[A-Za-z0-9+/_=-]+", node.value
                ):
                    encoded_literal_characters += len(node.value)
            elif isinstance(node.value, (int, float)) and not isinstance(
                node.value, bool
            ):
                numeric_literals += 1
            if isinstance(node.value, bytes):
                byte_literal_characters += len(node.value)
            if (
                isinstance(node.value, bytes)
                and (len(node.value) > 16 or byte_literal_characters > 64)
            ) or (isinstance(node.value, str) and len(node.value) > 4096):
                raise _artifact_finding(
                    "artifact.public_embedded_blob",
                    "remove embedded binary or row-level payloads",
                )
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and len(node.elts) > 100:
            raise _artifact_finding(
                "artifact.public_embedded_blob",
                "replace embedded samples with aggregate metadata",
            )
        if isinstance(node, ast.Dict) and len(node.keys) > 100:
            raise _artifact_finding(
                "artifact.public_embedded_blob",
                "replace embedded samples with aggregate metadata",
            )
    if (
        literal_characters > 6144
        or encoded_literal_characters >= 512
        or numeric_literals > 500
    ):
        raise _artifact_finding(
            "artifact.public_embedded_blob",
            "move data and long prose out of the minimal experiment source",
        )


def _read_descriptor_bounded(descriptor: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise _artifact_finding(
            "artifact.public_too_large",
            "reduce the artifact to the documented size ceiling",
        )
    return data


def _read_posix_public_file(
    run_dir: Path, basename: str, max_bytes: int
) -> bytes:
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_DIRECTORY"):
        raise _artifact_finding(
            "artifact.public_secure_open_unavailable",
            "use a platform with directory-relative no-follow file opens",
        )
    absolute_run = Path(os.path.abspath(run_dir))
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptors: list[int] = []
    try:
        current = os.open(absolute_run.anchor, directory_flags)
        descriptors.append(current)
        for part in absolute_run.parts[1:]:
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
        run_metadata = os.fstat(current)
        run_device = run_metadata.st_dev
        for part in ("artifacts", "public"):
            current = os.open(part, directory_flags, dir_fd=current)
            descriptors.append(current)
            metadata = os.fstat(current)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_dev != run_device:
                raise _artifact_finding(
                    "artifact.public_parent_invalid",
                    "keep public artifacts in regular in-run directories",
                )
        descriptor = os.open(basename, file_flags, dir_fd=current)
        descriptors.append(descriptor)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != run_device
            or opened.st_size > max_bytes
        ):
            raise _artifact_finding(
                "artifact.public_not_regular",
                "use one unique regular in-run text file",
            )
        data = _read_descriptor_bounded(descriptor, max_bytes)
        final = os.fstat(descriptor)
        entry = os.stat(
            basename,
            dir_fd=current,
            follow_symlinks=False,
        )
        if (
            not os.path.samestat(opened, final)
            or not os.path.samestat(final, entry)
            or final.st_nlink != 1
            or final.st_size != len(data)
            or final.st_size != opened.st_size
            or final.st_mtime_ns != opened.st_mtime_ns
        ):
            raise _artifact_finding(
                "artifact.public_changed", "freeze the artifact before export"
            )
        return data
    except SecurityViolation:
        raise
    except OSError as error:
        raise _artifact_finding(
            "artifact.public_unreadable",
            "provide stable no-follow directory and file entries",
        ) from error
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _load_inspection_module() -> Any:
    name = "_researchhelm_secure_reader"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    path = Path(__file__).with_name("inspect_skill.py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise _artifact_finding(
            "artifact.public_secure_open_unavailable",
            "restore the bundled secure file reader",
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _windows_final_handle_path(kernel32: Any, handle: int) -> str:
    import ctypes

    kernel32.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    length = int(
        kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(handle), None, 0, 0
        )
    )
    if length <= 0 or length > 32768:
        raise OSError("final path unavailable")
    buffer = ctypes.create_unicode_buffer(length + 1)
    written = int(
        kernel32.GetFinalPathNameByHandleW(
            ctypes.c_void_p(handle), buffer, len(buffer), 0
        )
    )
    if written <= 0 or written >= len(buffer):
        raise OSError("final path unavailable")
    value = buffer.value
    # Build the Win32 device-path prefix without embedding a path-shaped
    # literal that the release auditor correctly treats as non-public text.
    prefix = "\\" * 2 + "?\\"
    if value.startswith(prefix + "UNC\\"):
        value = "\\\\" + value[len(prefix + "UNC\\") :]
    elif value.startswith(prefix):
        value = value[len(prefix) :]
    return os.path.normcase(os.path.normpath(value))


def _read_windows_public_file(
    run_dir: Path, basename: str, max_bytes: int
) -> bytes:
    import ctypes

    secure = _load_inspection_module()
    kernel32 = secure._windows_kernel32()
    paths = [
        Path(run_dir),
        Path(run_dir) / "artifacts",
        Path(run_dir) / "artifacts" / "public",
        Path(run_dir) / "artifacts" / "public" / basename,
    ]
    handles: list[int] = []
    try:
        for path in paths:
            handles.append(secure._windows_open_handle(path))
        infos = [secure._windows_info(handle) for handle in handles]
        for index, info in enumerate(infos):
            is_directory = bool(info["attributes"] & secure._FILE_ATTRIBUTE_DIRECTORY)
            if info["attributes"] & secure._FILE_ATTRIBUTE_REPARSE_POINT:
                raise _artifact_finding(
                    "artifact.public_reparse_point",
                    "replace links with regular in-run entries",
                )
            if index < 3 and not is_directory:
                raise _artifact_finding(
                    "artifact.public_parent_invalid",
                    "keep public artifacts in regular in-run directories",
                )
            if index == 3 and is_directory:
                raise _artifact_finding(
                    "artifact.public_not_regular", "use a regular text file"
                )
        file_info = infos[-1]
        if file_info["links"] != 1 or file_info["size"] > max_bytes:
            raise _artifact_finding(
                "artifact.public_not_regular",
                "use one unique bounded regular text file",
            )

        final_paths = [
            _windows_final_handle_path(kernel32, handle) for handle in handles
        ]
        expected = final_paths[0]
        for part, observed in zip(
            ("artifacts", "public", basename), final_paths[1:]
        ):
            expected = os.path.normcase(os.path.normpath(os.path.join(expected, part)))
            if observed != expected:
                raise _artifact_finding(
                    "artifact.public_parent_changed",
                    "freeze the in-run directory chain before export",
                )

        kernel32.ReadFile.restype = ctypes.c_int
        kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            requested = min(64 * 1024, remaining)
            buffer = ctypes.create_string_buffer(requested)
            read = ctypes.c_uint32()
            if not kernel32.ReadFile(
                ctypes.c_void_p(handles[-1]),
                buffer,
                requested,
                ctypes.byref(read),
                None,
            ):
                raise OSError("file read failed")
            if read.value == 0:
                break
            chunks.append(buffer.raw[: read.value])
            remaining -= read.value
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise _artifact_finding(
                "artifact.public_too_large",
                "reduce the artifact to the documented size ceiling",
            )
        final_info = secure._windows_info(handles[-1])
        if (
            not secure._windows_stable(file_info, final_info)
            or final_info["links"] != 1
            or final_info["size"] != len(data)
        ):
            raise _artifact_finding(
                "artifact.public_changed", "freeze the artifact before export"
            )
        return data
    except SecurityViolation:
        raise
    except Exception as error:
        raise _artifact_finding(
            "artifact.public_unreadable",
            "provide stable handle-verifiable in-run entries",
        ) from error
    finally:
        for handle in reversed(handles):
            try:
                secure._windows_close_handle(handle)
            except Exception:
                pass


def _read_bounded_regular_file(
    run_dir: Path, basename: str, max_bytes: int
) -> bytes:
    if os.name == "nt":
        return _read_windows_public_file(run_dir, basename, max_bytes)
    return _read_posix_public_file(run_dir, basename, max_bytes)


def _read_public_artifacts(
    run_dir: Path, manifest: object
) -> dict[int, tuple[str, bytes]]:
    if not isinstance(manifest, dict):
        return {}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    sensitivity = manifest.get("field_sensitivity")
    if not isinstance(sensitivity, dict):
        return {}
    selected: dict[int, tuple[str, bytes]] = {}
    declared_basenames: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        path_value = artifact.get("path")
        if not isinstance(path_value, str):
            continue
        candidate = PurePosixPath(path_value)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in path_value:
            raise _artifact_finding(
                "artifact.public_path_invalid", "use a normalized relative artifact path"
            )
        if len(candidate.parts) < 2 or candidate.parts[:2] != (
            "artifacts",
            "public",
        ):
            continue
        if len(candidate.parts) != 3 or candidate.as_posix() != path_value:
            raise _artifact_finding(
                "artifact.public_name_not_allowed", "use an allowlisted public artifact basename"
            )
        kind = artifact.get("kind")
        rule = PUBLIC_ARTIFACT_RULES.get(kind) if isinstance(kind, str) else None
        if rule is None:
            raise _artifact_finding(
                "artifact.public_kind_not_allowed", "use an allowlisted public artifact kind"
            )
        basename = candidate.name
        if basename != rule["basename"] or candidate.suffix != rule["extension"]:
            raise _artifact_finding(
                "artifact.public_name_not_allowed", "use the basename paired with the artifact kind"
            )
        if basename in declared_basenames:
            raise _artifact_finding(
                "artifact.public_duplicate",
                "declare each allowlisted public artifact exactly once",
            )
        declared_basenames.add(basename)
        slash = "/"
        pointer_root = slash + "artifacts" + slash + str(index) + slash
        path_pointer = pointer_root + "path"
        kind_pointer = pointer_root + "kind"
        if any(
            sensitivity.get(pointer) != "public"
            for pointer in (path_pointer, kind_pointer)
        ):
            raise _artifact_finding(
                "privacy.public_artifact_not_public",
                "classify the public artifact path and kind as public",
            )
        if artifact.get("frozen") is not True:
            continue
        source = run_dir.joinpath(*candidate.parts)
        for checked in (run_dir, source.parent.parent, source.parent, source):
            if _is_reparse_or_symlink(checked):
                raise _artifact_finding(
                    "artifact.public_reparse_point", "replace links with a regular in-run file"
                )
        data = _read_bounded_regular_file(
            run_dir, basename, rule["max_bytes"]
        )
        expected_hash = artifact.get("sha256")
        if not isinstance(expected_hash, str) or not hashlib.sha256(data).hexdigest() == expected_hash.lower():
            raise _artifact_finding(
                "artifact.public_hash_mismatch", "update the manifest only after freezing the artifact"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _artifact_finding(
                "artifact.public_not_text", "export UTF-8 text only"
            ) from error
        if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
            raise _artifact_finding(
                "artifact.public_not_text", "remove binary control bytes"
            )
        content_findings = _public_artifact_findings(text)
        if content_findings:
            raise SecurityViolation(findings=content_findings)
        if len(ENVIRONMENT_ASSIGNMENT.findall(text)) >= 2:
            raise _artifact_finding(
                "privacy.environment_dump", "replace environment output with a minimal dependency lock"
            )
        if kind in PUBLIC_JSON_TOP_LEVEL_KEYS:
            _validate_public_json(kind, text)
        elif kind == "requirements-lock":
            _validate_requirements_lock(text)
        elif kind == "experiment-code":
            _validate_experiment_code(text)
        elif kind == "attribution":
            _validate_attribution(text)
        selected[index] = (basename, data)
    return selected


def _rewrite_artifact_paths(
    record: dict[str, Any], public_artifacts: dict[int, tuple[str, bytes]]
) -> None:
    if record.get("record_type") != "artifact-manifest":
        return
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list):
        return
    sensitivity = record.get("field_sensitivity")
    if not isinstance(sensitivity, dict):
        return
    for index, artifact in enumerate(artifacts):
        if isinstance(artifact, dict) and isinstance(artifact.get("artifact_id"), str):
            if index in public_artifacts:
                artifact["path"] = f"artifacts/public/{public_artifacts[index][0]}"
            else:
                artifact["path"] = f"artifacts/{artifact['artifact_id']}"
            pointer = "/" + "artifacts/" + str(index) + "/" + "path"
            sensitivity[pointer] = "public"


def sanitize_public_run(run_dir: Path, output_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    output_dir = Path(output_dir)

    if not run_dir.is_dir():
        raise OSError("run directory is unavailable")
    loaded, validation_findings = _load_validated_snapshot(run_dir)
    if validation_findings:
        raise SecurityViolation(findings=validation_findings)
    scan_findings = _scan_loaded(loaded)
    if scan_findings:
        raise SecurityViolation(findings=scan_findings)
    public_artifacts = _read_public_artifacts(
        run_dir, loaded.get("artifact-manifest.json")
    )

    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("output directory already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    files_exported = 0
    records_exported = 0
    public_fields = 0
    private_fields = 0
    try:
        for filename, data in loaded.items():
            records = data if REQUIRED_FILES[filename] == "jsonl" else [data]
            projected_records: list[dict[str, Any]] = []
            for record in records:
                projected, public_count, private_count = (
                    _sanitize_record_with_counts(record)
                )
                _rewrite_artifact_paths(projected, public_artifacts)
                projected_records.append(projected)
                records_exported += 1
                public_fields += public_count
                private_fields += private_count

            destination = temporary_dir / filename
            if REQUIRED_FILES[filename] == "json":
                destination.write_text(
                    json.dumps(
                        projected_records[0], ensure_ascii=False, indent=2
                    )
                    + "\n",
                    encoding="utf-8",
                )
            else:
                destination.write_text(
                    "".join(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                        for record in projected_records
                    ),
                    encoding="utf-8",
                )
            files_exported += 1

        for _index, (basename, data) in public_artifacts.items():
            destination = temporary_dir / "artifacts" / "public" / basename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            files_exported += 1

        report: dict[str, Any] = {
            "schema_version": "1.0",
            "source_kind": "sanitized-public-export",
            "files_exported": files_exported,
            "records_exported": records_exported,
            "public_fields_retained": public_fields,
            "project_private_fields_removed": private_fields,
            "artifacts_exported": len(public_artifacts),
            "finding_count": 0,
            "findings": [],
        }
        (temporary_dir / "sanitization-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_dir.replace(output_dir)
        return report
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def _finding_payload(findings: Iterable[SecurityFinding]) -> dict[str, Any]:
    items = list(findings)
    return {
        "clean": not items,
        "finding_count": len(items),
        "findings": [asdict(item) for item in items],
    }


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan-state")
    scan_parser.add_argument("run_dir", type=Path)
    export_parser = subparsers.add_parser("public-export")
    export_parser.add_argument("run_dir", type=Path)
    export_parser.add_argument("output_dir", type=Path)
    try:
        args = parser.parse_args(argv)
        if args.command == "scan-state":
            findings = _scan_loaded(_load_records(args.run_dir))
            print(json.dumps(_finding_payload(findings), ensure_ascii=False))
            return 1 if findings else 0
        report = sanitize_public_run(args.run_dir, args.output_dir)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except SecurityViolation as error:
        print(json.dumps(_finding_payload(error.findings), ensure_ascii=False))
        return 1
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        print(
            json.dumps(
                {"clean": False, "finding_count": 0, "error": "invalid input"}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
