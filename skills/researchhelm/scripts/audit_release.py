from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from sanitize_export import SecurityFinding, scan_text  # noqa: E402


FORBIDDEN_PARTS = {".claude", ".codex", ".ssh", ".aws", ".azure", ".gnupg"}
FORBIDDEN_NAMES = {
    ".env",
    "auth.json",
    "credentials",
    "credentials.json",
    "cookies",
    "cookies.sqlite",
    "id_rsa",
    "id_ed25519",
}
FORBIDDEN_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
NON_WAIVABLE_PREFIXES = (
    "credential.",
    "account.",
    "session.",
    "private_key.",
    "credential_file.",
)
PRIVACY_PREFIX = "privacy."
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PUBLIC_EMAIL = re.compile(r"(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$")
EMAIL_TOKEN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PATH_SLASH = chr(47)
STRICT_JSON_POINTER_VALUE = re.compile(
    rf"{_PATH_SLASH}(?:[A-Za-z0-9_.-]|~[01])+(?:/(?:[A-Za-z0-9_.-]|~[01])*)*"
)
QUOTED_JSON_POINTER = re.compile(
    r"(?P<prefix>[rRuUbBfF]{0,2})(?P<quote>['\"])(?P<value>/(?:[A-Za-z0-9_.-]|~[01])+(?:/(?:[A-Za-z0-9_.-]|~[01])*)*)(?P=quote)"
)
RAW_STRING_LITERAL = re.compile(
    r"(?P<prefix>[rR])(?P<quote>['\"])(?P<value>[^'\"\r\n]*)(?P=quote)"
)
QUOTED_SLASH_SEPARATOR = re.compile(
    r"(?P<prefix>[rRuUbBfF]{0,2})(?P<quote>['\"])/(?P=quote)"
)
SLASH_COMMAND = re.compile(
    r"(?:/plugin\s+(?:marketplace\s+add|install)\b|/researchhelm\b|/autoresearch\b)"
)
FILESYSTEM_ROOT_SEGMENTS = {
    "dev",
    "etc",
    "home",
    "media",
    "mnt",
    "opt",
    "private",
    "proc",
    "program files",
    "programdata",
    "root",
    "srv",
    "sys",
    "tmp",
    "users",
    "usr",
    "var",
    "volumes",
    "windows",
}
SCHEMA_POINTER_ROOTS = {
    "artifact_ids",
    "artifacts",
    "candidates",
    "claims",
    "code_hash",
    "commit",
    "config_hash",
    "content_hash",
    "created_at",
    "data_hash",
    "decision",
    "decision_requested",
    "environment",
    "environment_hash",
    "event_hash",
    "event_id",
    "evidence_id",
    "experiment_id",
    "input_hash",
    "mode",
    "previous_event_hash",
    "recommendation_id",
    "record_type",
    "resume",
    "retrieved_at",
    "run_id",
    "schema_version",
    "stage",
    "stage_input_hash",
    "timestamp",
    "updated_at",
}
DEFAULT_POLICY = {
    "schema_version": 1,
    "approved_public_emails": [],
    "suppressions": [],
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_ALLOWED_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"}
PNG_TEXT_CHUNKS = {b"tEXt", b"zTXt", b"iTXt"}


@dataclass(frozen=True)
class AuditFinding:
    code: str
    path: str
    location: str
    line_digest: str | None
    severity: str
    remediation: str


@dataclass(frozen=True)
class AuditResult:
    scope: str
    findings: list[AuditFinding]

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "clean": not self.findings,
            "findings": [asdict(item) for item in self.findings],
        }


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid usage")


def run_git(root: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return completed.stdout


def normalized(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _is_repository_relative(path: str) -> bool:
    value = normalized(path)
    candidate = PurePosixPath(value)
    return bool(value and not candidate.is_absolute() and ".." not in candidate.parts)


def _safe_report_path(path: str) -> str:
    value = normalized(path)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return "<redacted-path>"
    if any(ord(character) < 32 for character in value):
        return "<redacted-path>"
    if not _is_repository_relative(value):
        return "<redacted-path>"
    if scan_text(value, "state"):
        return "<redacted-path>"
    return value


def _policy_finding(code: str, index: int) -> AuditFinding:
    remediation = {
        "policy.invalid": "remove or correct the invalid suppression",
        "policy.expired": "remove or renew the expired suppression after review",
        "policy.drift": "remove or update the drifted suppression after review",
    }[code]
    return AuditFinding(
        code,
        ".security-allowlist.json",
        f"suppression:{index}",
        None,
        "block",
        remediation,
    )


def _approved_emails(policy: dict[str, object] | None) -> tuple[str, ...]:
    if not isinstance(policy, dict):
        return ()
    values = policy.get("approved_public_emails", [])
    if not isinstance(values, list):
        return ()
    return tuple(
        value
        for value in values
        if isinstance(value, str) and PUBLIC_EMAIL.fullmatch(value)
    )


def _mask_approved_emails(text: str, approved: Iterable[str]) -> str:
    approved_exact = set(approved)

    def replace(match: re.Match[str]) -> str:
        if match.group(0) in approved_exact:
            return "x" * len(match.group(0))
        return match.group(0)

    return EMAIL_TOKEN.sub(replace, text)


def _mask_strict_json_pointers(
    text: str,
    *,
    allowed_values: set[str] | frozenset[str] = frozenset(),
    allowed_spans: set[tuple[int, int]] | frozenset[tuple[int, int]] = frozenset(),
) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group("value")
        if value not in allowed_values and match.span() not in allowed_spans:
            return match.group(0)
        return (
            match.group("prefix")
            + match.group("quote")
            + "<json-pointer>"
            + match.group("quote")
        )

    return QUOTED_JSON_POINTER.sub(replace, text)


def _mask_nonfilesystem_slash_syntax(
    text: str,
    *,
    allowed_pointer_values: set[str] | frozenset[str] = frozenset(),
    allowed_pointer_spans: set[tuple[int, int]] | frozenset[tuple[int, int]] = frozenset(),
) -> str:
    masked = _mask_strict_json_pointers(
        text,
        allowed_values=allowed_pointer_values,
        allowed_spans=allowed_pointer_spans,
    )

    def replace_regex(match: re.Match[str]) -> str:
        value = match.group("value")
        if value not in allowed_pointer_values:
            return match.group(0)
        regex_syntax = ("(?:", "(?=", "(?!", "[", "\\d", "\\s", "*", "+", "?", "|")
        if not any(marker in value for marker in regex_syntax):
            return match.group(0)
        return match.group("prefix") + match.group("quote") + "<regex>" + match.group("quote")

    masked = RAW_STRING_LITERAL.sub(replace_regex, masked)
    masked = QUOTED_SLASH_SEPARATOR.sub(
        lambda match: match.group("prefix")
        + match.group("quote")
        + "<slash-separator>"
        + match.group("quote"),
        masked,
    )
    return SLASH_COMMAND.sub("<claude-plugin-command>", masked)


def _scan_release_line(
    text: str,
    *,
    allowed_pointer_values: set[str] | frozenset[str] = frozenset(),
    allowed_pointer_spans: set[tuple[int, int]] | frozenset[tuple[int, int]] = frozenset(),
) -> list[SecurityFinding]:
    masked = _mask_nonfilesystem_slash_syntax(
        text,
        allowed_pointer_values=allowed_pointer_values,
        allowed_pointer_spans=allowed_pointer_spans,
    )
    unique: dict[str, SecurityFinding] = {}
    for variant in (text, text.replace("\\\\", "\\")):
        for item in scan_text(variant, "state"):
            if item.code != "privacy.absolute_path":
                unique.setdefault(item.code, item)
    for variant in (masked, masked.replace("\\\\", "\\")):
        for item in scan_text(variant, "state"):
            unique.setdefault(item.code, item)
    return list(unique.values())


def _assignment_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for item in target.elts:
            names.update(_assignment_names(item))
        return names
    return set()


def _is_explicit_schema_pointer(value: str) -> bool:
    if not value.startswith("/"):
        return False
    encoded_root = value[1:].split("/", 1)[0]
    known_root = (
        "~0" in encoded_root
        or "~1" in encoded_root
        or encoded_root.lower() in SCHEMA_POINTER_ROOTS
    )
    if not known_root:
        return False
    return bool(
        STRICT_JSON_POINTER_VALUE.fullmatch(value)
        or any(marker in value for marker in ("(?:", "(?=", "(?!", "[", "\\d"))
    )


def _python_pointer_values(path: str, text: str) -> dict[int, set[str]]:
    if PurePosixPath(normalized(path)).suffix.lower() != ".py":
        return {}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    lines: dict[int, set[str]] = {}
    source_lines = text.splitlines()
    for node in ast.walk(tree):
        value: ast.expr | None = None
        names: set[str] = set()
        if isinstance(node, ast.Assign):
            value = node.value
            for target in node.targets:
                names.update(_assignment_names(target))
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            names.update(_assignment_names(node.target))
        if value is None or not any("POINTER" in name.upper() for name in names):
            continue
        for item in ast.walk(value):
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                continue
            if not _is_explicit_schema_pointer(item.value):
                continue
            start = getattr(item, "lineno", 0)
            end = getattr(item, "end_lineno", start)
            if start > 0:
                for number in range(start, end + 1):
                    if number == start:
                        lines.setdefault(number, set()).add(item.value)
                    if number <= len(source_lines):
                        for match in RAW_STRING_LITERAL.finditer(
                            source_lines[number - 1]
                        ):
                            if _is_explicit_schema_pointer(match.group("value")):
                                lines.setdefault(number, set()).add(
                                    match.group("value")
                                )
    return lines


@dataclass(frozen=True)
class _JsonToken:
    kind: str
    value: str
    line: int
    start: int
    end: int


def _json_tokens(text: str) -> list[_JsonToken]:
    tokens: list[_JsonToken] = []
    index = 0
    line = 1
    line_start = 0
    while index < len(text):
        character = text[index]
        if character.isspace():
            if character == "\n":
                line += 1
                line_start = index + 1
            index += 1
            continue
        if character in "{}[]:,":
            column = index - line_start
            tokens.append(_JsonToken(character, character, line, column, column + 1))
            index += 1
            continue
        if character == '"':
            start = index
            start_line = line
            start_column = start - line_start
            index += 1
            escaped = False
            while index < len(text):
                current = text[index]
                if current == "\n":
                    line += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    index += 1
                    break
                index += 1
            else:
                return []
            try:
                value = json.loads(text[start:index])
            except json.JSONDecodeError:
                return []
            if not isinstance(value, str):
                return []
            tokens.append(
                _JsonToken("string", value, start_line, start_column, index - line_start)
            )
            continue
        start = index
        while index < len(text) and not text[index].isspace() and text[index] not in "{}[]:,":
            index += 1
        tokens.append(
            _JsonToken(
                "atom", text[start:index], line, start - line_start, index - line_start
            )
        )
    return tokens


def _json_field_sensitivity_spans(
    path: str, text: str
) -> dict[int, set[tuple[int, int]]]:
    suffix = PurePosixPath(normalized(path)).suffix.lower()
    if suffix not in {".json", ".jsonl"}:
        return {}
    tokens = _json_tokens(text)
    allowed: dict[int, set[tuple[int, int]]] = {}

    def parse_value(index: int, sensitivity: bool = False) -> tuple[int, bool]:
        if index >= len(tokens):
            return index, False
        token = tokens[index]
        if token.kind == "{":
            index += 1
            if index < len(tokens) and tokens[index].kind == "}":
                return index + 1, True
            while index < len(tokens):
                key = tokens[index]
                if key.kind != "string":
                    return index, False
                index += 1
                if index >= len(tokens) or tokens[index].kind != ":":
                    return index, False
                index += 1
                if sensitivity and STRICT_JSON_POINTER_VALUE.fullmatch(key.value):
                    allowed.setdefault(key.line, set()).add((key.start, key.end))
                index, valid = parse_value(
                    index, sensitivity=key.value == "field_sensitivity"
                )
                if not valid or index >= len(tokens):
                    return index, False
                if tokens[index].kind == "}":
                    return index + 1, True
                if tokens[index].kind != ",":
                    return index, False
                index += 1
            return index, False
        if token.kind == "[":
            index += 1
            if index < len(tokens) and tokens[index].kind == "]":
                return index + 1, True
            while index < len(tokens):
                index, valid = parse_value(index)
                if not valid or index >= len(tokens):
                    return index, False
                if tokens[index].kind == "]":
                    return index + 1, True
                if tokens[index].kind != ",":
                    return index, False
                index += 1
            return index, False
        return index + 1, token.kind in {"string", "atom"}

    index = 0
    while index < len(tokens):
        index, valid = parse_value(index)
        if not valid:
            return {}
    return allowed


def _path_findings(path: str) -> list[AuditFinding]:
    value = normalized(path)
    report_path = _safe_report_path(value)
    candidate = PurePosixPath(value)
    parts = {part.lower() for part in candidate.parts}
    name = candidate.name.lower()
    suffix = candidate.suffix.lower()
    findings: list[AuditFinding] = []

    if not _is_repository_relative(value):
        findings.append(
            AuditFinding(
                "path.unsafe_repository_path",
                report_path,
                "path",
                None,
                "block",
                "remove the unsafe repository path",
            )
        )
    if parts & FORBIDDEN_PARTS or name in FORBIDDEN_NAMES or suffix in FORBIDDEN_SUFFIXES:
        findings.append(
            AuditFinding(
                "credential.forbidden_filename",
                report_path,
                "path",
                None,
                "block",
                "remove the credential or account file",
            )
        )
    for item in scan_text(value, "state"):
        findings.append(
            AuditFinding(
                item.code,
                report_path,
                "path",
                None,
                item.severity,
                item.remediation,
            )
        )
    return findings


def path_finding(path: str) -> AuditFinding | None:
    findings = _path_findings(path)
    return findings[0] if findings else None


def scan_blob(
    path: str,
    payload: bytes,
    scope: str,
    approved_public_emails: Iterable[str] = (),
    *,
    location_prefix: str | None = None,
) -> list[AuditFinding]:
    report_path = _safe_report_path(path)
    results = _path_findings(path)
    if PurePosixPath(normalized(path)).suffix.lower() == ".png":
        results.extend(_scan_png(report_path, payload, scope))
        return results
    text = payload.decode("utf-8", errors="replace")
    prefix = location_prefix or scope
    pointer_values = _python_pointer_values(path, text)
    pointer_spans = _json_field_sensitivity_spans(path, text)

    for number, original_line in enumerate(text.splitlines(), 1):
        masked_line = _mask_approved_emails(original_line, approved_public_emails)
        scanned = _scan_release_line(
            masked_line,
            allowed_pointer_values=pointer_values.get(number, set()),
            allowed_pointer_spans=pointer_spans.get(number, set()),
        )
        if not scanned:
            continue
        protected_line = any(
            item.code.startswith(NON_WAIVABLE_PREFIXES) for item in scanned
        )
        digest = None
        if not protected_line:
            digest = hashlib.sha256(original_line.encode("utf-8")).hexdigest()
        for item in scanned:
            results.append(
                AuditFinding(
                    item.code,
                    report_path,
                    f"{prefix}:line:{number}",
                    digest,
                    item.severity,
                    item.remediation,
                )
            )
    return results


def _scan_png(path: str, payload: bytes, scope: str) -> list[AuditFinding]:
    def blocked(code: str, remediation: str) -> list[AuditFinding]:
        return [AuditFinding(code, path, scope, None, "block", remediation)]

    if not payload.startswith(PNG_SIGNATURE):
        return blocked("binary.invalid_png", "replace the file with a valid PNG")

    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    saw_idat = False
    saw_iend = False
    while offset < len(payload):
        if saw_iend or len(payload) - offset < 12:
            return blocked("binary.invalid_png", "remove malformed or trailing PNG data")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload) or not re.fullmatch(rb"[A-Za-z]{4}", chunk_type):
            return blocked("binary.invalid_png", "replace the file with a valid PNG")
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            return blocked("binary.invalid_png", "replace the file with a valid PNG")
        if chunk_index == 0 and (chunk_type != b"IHDR" or length != 13):
            return blocked("binary.invalid_png", "replace the file with a valid PNG")
        if chunk_type in PNG_TEXT_CHUNKS:
            return blocked(
                "binary.png_text_metadata",
                "remove PNG text metadata before release",
            )
        if chunk_type not in PNG_ALLOWED_CHUNKS:
            return blocked(
                "binary.png_unsafe_chunk",
                "remove non-rendering PNG metadata before release",
            )
        if chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"IEND":
            if length != 0:
                return blocked("binary.invalid_png", "replace the file with a valid PNG")
            saw_iend = True
        offset = chunk_end
        chunk_index += 1

    if not saw_idat or not saw_iend:
        return blocked("binary.invalid_png", "replace the file with a valid PNG")
    return []


def _load_policy(root: Path, policy_path: Path | None = None) -> dict[str, object]:
    target = policy_path or (root / ".security-allowlist.json")
    if not target.is_file():
        return dict(DEFAULT_POLICY)
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid policy")
    return value


def _split_nul(payload: bytes) -> list[str]:
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in payload.split(b"\0")
        if item
    ]


def _worktree_candidate(root: Path, path: str) -> Path:
    return root.joinpath(*PurePosixPath(path).parts)


def _safe_worktree_file(root: Path, path: str) -> Path | None:
    if not _is_repository_relative(path):
        return None
    candidate = _worktree_candidate(root, path)
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return candidate


def scan_worktree(
    root: Path, policy: dict[str, object] | None = None
) -> AuditResult:
    root = Path(root)
    effective_policy = policy if policy is not None else _load_policy(root)
    approved = _approved_emails(effective_policy)
    tracked = _split_nul(run_git(root, "ls-files", "-z", text=False))
    staged = set(
        _split_nul(
        run_git(
            root,
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "-z",
            text=False,
        )
        )
    )
    index_records = _split_nul(
        run_git(root, "ls-files", "--stage", "-z", text=False)
    )
    index_entries: list[tuple[str, str, str]] = []
    for record in index_records:
        header, separator, path = record.partition("\t")
        fields = header.split()
        if (
            not separator
            or not path
            or len(fields) != 3
            or not re.fullmatch(r"[0-9a-f]{40,64}", fields[1])
            or fields[2] not in {"0", "1", "2", "3"}
        ):
            continue
        index_entries.append((fields[1], fields[2], path))
    unmerged_entries: list[tuple[str, str, str]] = []
    staged_entries: list[tuple[str, str, str]] = []
    for entry in index_entries:
        _oid, stage, path = entry
        if stage == "0" and path in staged:
            staged_entries.append(entry)
        elif stage != "0":
            unmerged_entries.append(entry)
    unmerged = {path for _oid, _stage, path in unmerged_entries}
    findings: list[AuditFinding] = []

    for path in sorted(unmerged):
        findings.append(
            AuditFinding(
                "git.unmerged_index",
                _safe_report_path(path),
                "index",
                None,
                "block",
                "resolve the unmerged index before release",
            )
        )

    for oid, stage, path in sorted(unmerged_entries):
        payload = run_git(root, "cat-file", "blob", oid, text=False)
        assert isinstance(payload, bytes)
        findings.extend(
            scan_blob(
                path,
                payload,
                "index",
                approved,
                location_prefix=f"index-stage:{stage}:object:{oid}",
            )
        )

    for path in sorted(set(tracked)):
        target = _safe_worktree_file(root, path)
        if target is None:
            findings.extend(_path_findings(path))
            if not _is_repository_relative(path):
                continue
            try:
                if _worktree_candidate(root, path).is_symlink():
                    findings.append(
                        AuditFinding(
                            "path.unsafe_symlink",
                            _safe_report_path(path),
                            "worktree",
                            None,
                            "block",
                            "replace the symlink with a repository-contained file",
                        )
                    )
            except OSError:
                pass
            continue
        findings.extend(
            scan_blob(path, target.read_bytes(), "worktree", approved)
        )

    for oid, stage, path in sorted(staged_entries):
        payload = run_git(root, "cat-file", "blob", oid, text=False)
        assert isinstance(payload, bytes)
        findings.extend(
            scan_blob(
                path,
                payload,
                "index",
                approved,
                location_prefix=f"index-stage:{stage}:object:{oid}",
            )
        )

    return AuditResult("worktree", _deduplicate(findings))


def _history_objects(root: Path, ref: str) -> list[tuple[str, str]]:
    output = run_git(root, "rev-list", "--objects", ref)
    assert isinstance(output, str)
    objects: list[tuple[str, str]] = []
    for line in output.splitlines():
        oid, separator, path = line.partition(" ")
        if separator and oid and path:
            objects.append((oid, path))
    return objects


def _resolve_ref(root: Path, ref: str) -> str:
    output = run_git(
        root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
    )
    if not isinstance(output, str):
        raise ValueError("invalid ref")
    oid = output.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", oid):
        raise ValueError("invalid ref")
    return oid


def _historical_blob_paths(
    root: Path, ref: str
) -> dict[tuple[str, str], set[str]]:
    commits_output = run_git(root, "rev-list", ref)
    assert isinstance(commits_output, str)
    paths: dict[tuple[str, str], set[str]] = {}
    for commit in commits_output.splitlines():
        if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            continue
        tree = run_git(
            root,
            "ls-tree",
            "-r",
            "--full-tree",
            "-z",
            commit,
            text=False,
        )
        assert isinstance(tree, bytes)
        for record in _split_nul(tree):
            header, separator, path = record.partition("\t")
            fields = header.split()
            if not separator or len(fields) != 3 or fields[1] != "blob":
                continue
            oid = fields[2]
            if not re.fullmatch(r"[0-9a-f]{40,64}", oid):
                continue
            paths.setdefault((oid, path), set()).add(commit)
    return paths


def scan_history(
    root: Path,
    ref: str,
    policy: dict[str, object] | None = None,
) -> AuditResult:
    root = Path(root)
    resolved_ref = _resolve_ref(root, ref)
    effective_policy = policy if policy is not None else _load_policy(root)
    approved = _approved_emails(effective_policy)
    approved_exact = set(approved)
    findings: list[AuditFinding] = []

    reachable_blobs: set[str] = set()
    for oid, _path in _history_objects(root, resolved_ref):
        object_type = run_git(root, "cat-file", "-t", oid)
        if isinstance(object_type, str) and object_type.strip() == "blob":
            reachable_blobs.add(oid)
    blob_paths = {
        identity: commits
        for identity, commits in _historical_blob_paths(root, resolved_ref).items()
        if identity[0] in reachable_blobs
    }

    for (oid, path), commits in sorted(blob_paths.items()):
        payload = run_git(root, "cat-file", "blob", oid, text=False)
        assert isinstance(payload, bytes)
        scanned = scan_blob(
            path,
            payload,
            "history",
            approved,
            location_prefix=f"object:{oid}",
        )
        path_location = sorted(commits)[0] if commits else f"object:{oid}"
        for item in scanned:
            if item.location == "path":
                findings.append(
                    AuditFinding(
                        item.code,
                        item.path,
                        path_location,
                        item.line_digest,
                        item.severity,
                        item.remediation,
                    )
                )
            else:
                findings.append(item)

    log_output = run_git(
        root, "log", resolved_ref, "--format=%H%x00%ae%x00"
    )
    assert isinstance(log_output, str)
    fields = log_output.split("\0")
    for offset in range(0, len(fields) - 1, 2):
        commit = fields[offset].strip()
        email = fields[offset + 1].strip()
        if email.lower().endswith("@users.noreply.github.com"):
            continue
        if email in approved_exact:
            continue
        findings.append(
            AuditFinding(
                "identity.unapproved_author_email",
                "<git-author>",
                commit if re.fullmatch(r"[0-9a-f]{40,64}", commit) else "commit",
                None,
                "block",
                "use a public no-reply address or explicitly approve a public email",
            )
        )
    return AuditResult("history", _deduplicate(findings))


def _unsafe_archive_member(name: str) -> bool:
    value = name.replace("\\", "/")
    candidate = PurePosixPath(value)
    return (
        not value
        or candidate.is_absolute()
        or ".." in candidate.parts
        or bool(re.match(r"^[A-Za-z]:", value))
    )


def scan_archive_file(
    archive: Path,
    extraction: Path,
    policy: dict[str, object] | None = None,
) -> AuditResult:
    approved = _approved_emails(policy)
    findings: list[AuditFinding] = []
    with zipfile.ZipFile(archive) as handle:
        members = handle.infolist()
        unsafe = [member for member in members if _unsafe_archive_member(member.filename)]
        if unsafe:
            for _member in unsafe:
                findings.append(
                    AuditFinding(
                        "archive.unsafe_member",
                        "<redacted-path>",
                        "archive",
                        None,
                        "block",
                        "remove the unsafe archive member",
                    )
                )
            return AuditResult("archive", _deduplicate(findings))

        extraction.mkdir(parents=True, exist_ok=True)
        for member in members:
            if member.is_dir():
                continue
            path = normalized(member.filename)
            payload = handle.read(member)
            target = extraction.joinpath(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            findings.extend(scan_blob(path, payload, "archive", approved))
    return AuditResult("archive", _deduplicate(findings))


def verify_archive(
    root: Path,
    ref: str,
    policy: dict[str, object] | None = None,
) -> AuditResult:
    root = Path(root)
    resolved_ref = _resolve_ref(root, ref)
    effective_policy = policy if policy is not None else _load_policy(root)
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp)
        archive = temporary / "candidate.zip"
        extraction = temporary / "extract"
        run_git(
            root,
            "archive",
            "--format=zip",
            f"--output={archive}",
            resolved_ref,
        )
        return scan_archive_file(archive, extraction, effective_policy)


def _valid_suppression(entry: object) -> tuple[bool, date | None]:
    if not isinstance(entry, dict):
        return False, None
    if set(entry) != {
        "rule_id",
        "path",
        "line_digest",
        "reason",
        "expires",
        "approval",
    }:
        return False, None
    rule_id = entry.get("rule_id")
    path = entry.get("path")
    digest = entry.get("line_digest")
    reason = entry.get("reason")
    expires = entry.get("expires")
    approval = entry.get("approval")
    if not isinstance(rule_id, str) or not rule_id.startswith(PRIVACY_PREFIX):
        return False, None
    if not isinstance(path, str) or path != normalized(path) or not _is_repository_relative(path):
        return False, None
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        return False, None
    if not isinstance(reason, str) or not reason.strip():
        return False, None
    if not isinstance(approval, str) or not approval.strip():
        return False, None
    if not isinstance(expires, str):
        return False, None
    try:
        expiry = date.fromisoformat(expires)
    except ValueError:
        return False, None
    if expiry.isoformat() != expires:
        return False, None
    return True, expiry


def apply_policy(
    findings: Iterable[AuditFinding],
    policy: dict[str, object],
    today: date,
) -> list[AuditFinding]:
    source = list(findings)
    retained = list(source)
    policy_findings: list[AuditFinding] = []

    approved_values = (
        policy.get("approved_public_emails") if isinstance(policy, dict) else None
    )
    invalid_approved = (
        not isinstance(approved_values, list)
        or any(
            not isinstance(value, str) or not PUBLIC_EMAIL.fullmatch(value)
            for value in approved_values
        )
        or len(
            {
                value.lower()
                for value in approved_values
                if isinstance(value, str)
            }
        )
        != len(approved_values)
    )
    if (
        not isinstance(policy, dict)
        or set(policy)
        != {"schema_version", "approved_public_emails", "suppressions"}
        or policy.get("schema_version") != 1
        or isinstance(policy.get("schema_version"), bool)
        or invalid_approved
        or not isinstance(policy.get("suppressions"), list)
    ):
        return _deduplicate(
            retained
            + [
                AuditFinding(
                    "policy.invalid",
                    ".security-allowlist.json",
                    "policy",
                    None,
                    "block",
                    "replace the invalid policy with the documented schema",
                )
            ]
        )

    suppressions = policy.get("suppressions", [])
    assert isinstance(suppressions, list)
    for index, entry in enumerate(suppressions):
        valid, expiry = _valid_suppression(entry)
        if not valid or expiry is None:
            policy_findings.append(_policy_finding("policy.invalid", index))
            continue
        if expiry < today:
            policy_findings.append(_policy_finding("policy.expired", index))
            continue

        assert isinstance(entry, dict)
        rule_id = entry["rule_id"]
        path = entry["path"]
        digest = entry["line_digest"]
        exact = [
            item
            for item in retained
            if item.code == rule_id
            and item.path == path
            and item.line_digest == digest
            and item.code.startswith(PRIVACY_PREFIX)
        ]
        if not exact:
            policy_findings.append(_policy_finding("policy.drift", index))
            continue
        retained = [item for item in retained if item not in exact]

    return _deduplicate(retained + policy_findings)


def _deduplicate(findings: Iterable[AuditFinding]) -> list[AuditFinding]:
    unique: dict[tuple[str, str, str, str | None], AuditFinding] = {}
    for finding in findings:
        identity = (
            finding.code,
            finding.path,
            finding.location,
            finding.line_digest,
        )
        unique.setdefault(identity, finding)
    return sorted(
        unique.values(),
        key=lambda item: (item.code, item.path, item.location, item.line_digest or ""),
    )


def audit_all(
    root: Path,
    ref: str = "HEAD",
    policy: dict[str, object] | None = None,
) -> AuditResult:
    root = Path(root)
    resolved_ref = _resolve_ref(root, ref)
    effective_policy = policy if policy is not None else _load_policy(root)
    combined = (
        scan_worktree(root, effective_policy).findings
        + scan_history(root, resolved_ref, effective_policy).findings
        + verify_archive(root, resolved_ref, effective_policy).findings
    )
    return AuditResult(
        "all",
        apply_policy(_deduplicate(combined), effective_policy, date.today()),
    )


def _single_finding_result(scope: str, code: str, remediation: str) -> AuditResult:
    return AuditResult(
        scope,
        [AuditFinding(code, "<repository>", "audit", None, "block", remediation)],
    )


def _parser() -> SafeArgumentParser:
    parser = SafeArgumentParser(add_help=False)
    parser.add_argument("scope", choices=("worktree", "history", "archive", "all"))
    parser.add_argument("--root", default=".")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--policy")
    return parser


def _run_cli(argv: list[str]) -> tuple[AuditResult, int]:
    try:
        arguments = _parser().parse_args(argv)
    except (ValueError, SystemExit):
        result = _single_finding_result(
            "usage", "audit.invalid_usage", "use a supported audit scope and option"
        )
        return result, 2

    try:
        root = Path(arguments.root).resolve()
        top = run_git(root, "rev-parse", "--show-toplevel")
        if not isinstance(top, str) or Path(top.strip()).resolve() != root:
            result = _single_finding_result(
                arguments.scope,
                "audit.invalid_usage",
                "set root to the Git repository top level",
            )
            return result, 2
        policy_path = None
        if arguments.policy:
            candidate = Path(arguments.policy)
            if not candidate.is_absolute():
                candidate = root / candidate
            policy_path = candidate.resolve()
            try:
                policy_path.relative_to(root)
            except ValueError:
                result = _single_finding_result(
                    arguments.scope,
                    "audit.invalid_usage",
                    "keep the policy inside the repository root",
                )
                return result, 2
        policy = _load_policy(root, policy_path)
        if arguments.scope == "worktree":
            result = scan_worktree(root, policy)
        elif arguments.scope == "history":
            result = scan_history(root, arguments.ref, policy)
        elif arguments.scope == "archive":
            result = verify_archive(root, arguments.ref, policy)
        else:
            result = audit_all(root, arguments.ref, policy)
        if arguments.scope != "all":
            result = AuditResult(
                result.scope,
                apply_policy(result.findings, policy, date.today()),
            )
        return result, 1 if result.findings else 0
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, subprocess.SubprocessError):
        result = _single_finding_result(
            "audit", "audit.internal_error", "inspect the repository and retry the audit"
        )
        return result, 1


def main(argv: list[str] | None = None) -> int:
    result, exit_code = _run_cli(list(sys.argv[1:] if argv is None else argv))
    print(json.dumps(result.to_dict(), sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
