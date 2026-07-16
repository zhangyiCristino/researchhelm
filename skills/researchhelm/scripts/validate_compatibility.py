#!/usr/bin/env python3
"""Validate and render evidence-backed compatibility claims."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LABELS = (
    "Standard-validated",
    "Install-path verified",
    "Native-tested",
    "Portable-tested",
    "Community-reported",
)
LABEL_ORDER = {label: index for index, label in enumerate(LABELS)}
MAX_AGE_DAYS = 90
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_TEXT = (
    "client",
    "version",
    "operating_system",
    "install_command",
    "tested_at",
)
START = "<!-- COMPATIBILITY:START -->"
END = "<!-- COMPATIBILITY:END -->"
README_NAMES = ("README.md", "README.zh-CN.md")


@dataclass(frozen=True)
class Finding:
    code: str
    path: str


def _finding(code: str, path: str) -> Finding:
    return Finding(f"compatibility.{code}", path)


def _load_registry(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, [_finding("unreadable", "registry")]
    try:
        registry = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, [_finding("invalid_json", "registry")]
    if not isinstance(registry, dict):
        return None, [_finding("invalid_root", "registry")]
    return registry, []


def _required_text_findings(claim: dict[str, Any], index: int) -> list[Finding]:
    findings: list[Finding] = []
    for field in REQUIRED_TEXT:
        value = claim.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append(_finding(f"missing_{field}", f"claims/{index}/{field}"))
    return findings


def _git_object_type(specification: str) -> str | None:
    try:
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "--no-optional-locks",
                "-C",
                str(REPOSITORY_ROOT),
                "cat-file",
                "-t",
                specification,
            ],
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _commit_contains_evidence(commit: str, evidence: str) -> bool:
    return (
        _git_object_type(f"{commit}^{{commit}}") == "commit"
        and _git_object_type(f"{commit}:{evidence}") == "blob"
    )


def _validate_evidence(value: Any, commit: Any, index: int) -> list[Finding]:
    logical = f"claims/{index}/evidence"
    if not isinstance(value, str) or not value.strip():
        return [_finding("missing_evidence", logical)]
    if "\\" in value or "\x00" in value:
        return [_finding("invalid_evidence", logical)]
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(":" in part for part in pure.parts)
        or any(part.casefold() == ".git" for part in pure.parts)
    ):
        return [_finding("invalid_evidence", logical)]
    try:
        repository = REPOSITORY_ROOT.resolve(strict=True)
        candidate = repository.joinpath(*pure.parts).resolve(strict=True)
    except OSError:
        return [_finding("missing_evidence", logical)]
    if not candidate.is_relative_to(repository) or not candidate.is_file():
        return [_finding("invalid_evidence", logical)]
    if (
        isinstance(commit, str)
        and COMMIT_PATTERN.fullmatch(commit)
        and not _commit_contains_evidence(commit, pure.as_posix())
    ):
        return [_finding("unverified_commit_evidence", logical)]
    return []


def _validate_claim(
    claim: Any,
    index: int,
    today: date,
    max_age_days: int,
) -> tuple[list[Finding], tuple[Any, ...] | None]:
    logical = f"claims/{index}"
    if not isinstance(claim, dict):
        return [_finding("invalid_claim", logical)], None

    findings = _required_text_findings(claim, index)
    label = claim.get("label")
    if not isinstance(label, str) or not label.strip():
        findings.append(_finding("missing_label", f"{logical}/label"))
    elif label not in LABELS:
        findings.append(_finding("invalid_label", f"{logical}/label"))

    limitations = claim.get("limitations")
    if not isinstance(limitations, list) or any(
        not isinstance(item, str) or not item.strip() for item in limitations
    ):
        findings.append(_finding("invalid_limitations", f"{logical}/limitations"))

    commit = claim.get("commit")
    if not isinstance(commit, str) or not commit.strip():
        findings.append(_finding("missing_commit", f"{logical}/commit"))
    elif not COMMIT_PATTERN.fullmatch(commit):
        findings.append(_finding("invalid_commit", f"{logical}/commit"))

    findings.extend(
        _validate_evidence(claim.get("evidence"), claim.get("commit"), index)
    )

    tested: date | None = None
    tested_at = claim.get("tested_at")
    if isinstance(tested_at, str) and tested_at.strip():
        try:
            tested = date.fromisoformat(tested_at)
        except ValueError:
            findings.append(_finding("invalid_tested_at", f"{logical}/tested_at"))
    if tested is not None:
        age = (today - tested).days
        if age < 0:
            findings.append(_finding("future_tested_at", f"{logical}/tested_at"))
        elif age > max_age_days:
            findings.append(_finding("needs_revalidation", logical))

    duplicate_key = (
        claim.get("client"),
        claim.get("label"),
        claim.get("version"),
        claim.get("commit"),
    )
    return findings, duplicate_key


def validate_registry(
    path: Path,
    today: date,
    max_age_days: int = MAX_AGE_DAYS,
) -> list[Finding]:
    """Return deterministic findings for a compatibility registry."""

    registry, findings = _load_registry(Path(path))
    if registry is None:
        return findings

    if (
        type(max_age_days) is not int
        or max_age_days <= 0
        or max_age_days > MAX_AGE_DAYS
    ):
        findings.append(_finding("invalid_max_age_days", "max_age_days"))
        max_age_days = MAX_AGE_DAYS
    if registry.get("schema_version") != 1 or isinstance(
        registry.get("schema_version"), bool
    ):
        findings.append(_finding("invalid_schema_version", "schema_version"))
    stored_age = registry.get("max_age_days")
    if (
        type(stored_age) is not int
        or stored_age <= 0
        or stored_age > MAX_AGE_DAYS
    ):
        findings.append(_finding("invalid_max_age_days", "registry/max_age_days"))
    else:
        max_age_days = min(max_age_days, stored_age)

    claims = registry.get("claims")
    if not isinstance(claims, list):
        findings.append(_finding("invalid_claims", "claims"))
        return findings

    seen: set[tuple[Any, ...]] = set()
    for index, claim in enumerate(claims):
        claim_findings, duplicate_key = _validate_claim(
            claim, index, today, max_age_days
        )
        findings.extend(claim_findings)
        if duplicate_key is not None:
            if duplicate_key in seen:
                findings.append(_finding("duplicate_claim", f"claims/{index}"))
            seen.add(duplicate_key)
    return findings


def _escape_markdown(value: Any) -> str:
    return str(value).replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|")


def _rendered_label(claim: dict[str, Any], today: date, max_age_days: int) -> str:
    label = str(claim.get("label", ""))
    try:
        tested = date.fromisoformat(str(claim.get("tested_at", "")))
    except ValueError:
        return label
    if (today - tested).days > max_age_days:
        return "needs revalidation"
    return label


def render_markdown(registry: dict[str, Any]) -> str:
    """Render the canonical compatibility table in deterministic order."""

    lines = [
        "| Client | Label | Version | Tested | Evidence |",
        "|---|---|---|---|---|",
    ]
    claims = registry.get("claims", []) if isinstance(registry, dict) else []
    if not isinstance(claims, list):
        return "\n".join(lines) + "\n"
    max_age = registry.get("max_age_days", MAX_AGE_DAYS)
    if type(max_age) is not int or max_age <= 0:
        max_age = MAX_AGE_DAYS
    max_age = min(max_age, MAX_AGE_DAYS)
    rows = [claim for claim in claims if isinstance(claim, dict)]
    rows.sort(
        key=lambda claim: (
            LABEL_ORDER.get(str(claim.get("label", "")), len(LABEL_ORDER)),
            str(claim.get("client", "")).casefold(),
            str(claim.get("version", "")).casefold(),
        )
    )
    for claim in rows:
        evidence = _escape_markdown(claim.get("evidence", ""))
        cells = (
            _escape_markdown(claim.get("client", "")),
            _escape_markdown(_rendered_label(claim, date.today(), max_age)),
            _escape_markdown(claim.get("version", "")),
            _escape_markdown(claim.get("tested_at", "")),
            f"[evidence]({evidence})",
        )
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def replace_marked_block(text: str, rendered: str) -> str:
    """Replace exactly one generated compatibility block."""

    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("README must contain exactly one compatibility marker pair")
    before, remainder = text.split(START, 1)
    _, after = remainder.split(END, 1)
    return f"{before}{START}\n{rendered.rstrip()}\n{END}{after}"


def _atomic_write(path: Path, text: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            temporary = Path(handle.name)
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sync_readmes(root: Path = REPOSITORY_ROOT, check: bool = False) -> bool:
    """Synchronize README compatibility blocks; return False on check drift."""

    root = Path(root)
    registry_path = root / "evals" / "compatibility" / "clients.json"
    registry, findings = _load_registry(registry_path)
    if registry is None or findings:
        raise ValueError("compatibility registry is unreadable")
    if validate_registry(registry_path, date.today()):
        raise ValueError("compatibility registry has findings")
    rendered = render_markdown(registry)
    replacements: list[tuple[Path, str, str]] = []
    for name in README_NAMES:
        path = root / name
        current = path.read_text(encoding="utf-8")
        updated = replace_marked_block(current, rendered)
        replacements.append((path, current, updated))
    drifted = any(current != updated for _, current, updated in replacements)
    if check:
        return not drifted
    for path, current, updated in replacements:
        if current != updated:
            _atomic_write(path, updated)
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validate_compatibility.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "render"):
        child = subparsers.add_parser(command)
        child.add_argument("path", type=Path)
        child.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    sync = subparsers.add_parser("sync-readme")
    sync.add_argument("--check", action="store_true")
    return parser


def _emit_findings(findings: list[Finding]) -> None:
    for finding in findings:
        print(f"{finding.code} {finding.path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "sync-readme":
        try:
            current = sync_readmes(check=args.check)
        except (OSError, UnicodeError, ValueError):
            print("compatibility.sync_failed readmes", file=sys.stderr)
            return 1
        if not current:
            print("compatibility.readme_drift readmes", file=sys.stderr)
            return 1
        return 0
    findings = validate_registry(args.path, date.today(), args.max_age_days)
    if findings:
        _emit_findings(findings)
        return 1
    if args.command == "render":
        registry, load_findings = _load_registry(args.path)
        if registry is None:
            _emit_findings(load_findings)
            return 1
        rendered_registry = dict(registry)
        rendered_registry["max_age_days"] = args.max_age_days
        sys.stdout.write(render_markdown(rendered_registry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
