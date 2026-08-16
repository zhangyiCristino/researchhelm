"""Independent worktree credential/filename scanner (content-free findings).

Scans a directory tree for forbidden credential-like filenames and path
segments. Never prints matched secret values — only finding codes and
repository-relative paths. Standard library only.

Usage:
    python scripts/credential_scan.py <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

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
SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".researchhelm",
    ".autoresearch",
    "researchhelm.egg-info",
}


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    severity: str
    remediation: str


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def scan_tree(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    if not root.exists():
        return [
            Finding(
                "scan.path_missing",
                str(root),
                "error",
                "provide an existing directory",
            )
        ]

    for path in root.rglob("*"):
        if not path.is_file():
            # prune skip dirs by not descending — rglob still enters; filter path parts
            continue
        parts_lower = {part.lower() for part in path.parts}
        if parts_lower & {s.lower() for s in SKIP_DIR_NAMES}:
            continue
        name = path.name
        name_lower = name.lower()
        rel = _rel(root, path)

        for part in path.parts:
            if part.lower() in FORBIDDEN_PARTS:
                findings.append(
                    Finding(
                        "credential_file.forbidden_path_segment",
                        rel,
                        "error",
                        "remove or exclude the credential-bearing path segment",
                    )
                )
                break

        if name_lower in FORBIDDEN_NAMES or name in FORBIDDEN_NAMES:
            findings.append(
                Finding(
                    "credential_file.forbidden_filename",
                    rel,
                    "error",
                    "remove the credential or account file",
                )
            )
            continue

        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            findings.append(
                Finding(
                    "credential_file.forbidden_suffix",
                    rel,
                    "error",
                    "remove the private-key or certificate material",
                )
            )

    # stable unique by (code, path)
    seen: set[tuple[str, str]] = set()
    unique: list[Finding] = []
    for item in findings:
        key = (item.code, item.path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda f: (f.path, f.code))
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan a worktree for credential-like filenames (content-free)."
    )
    parser.add_argument("path", type=Path, help="Directory to scan")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON findings only",
    )
    args = parser.parse_args(argv)
    findings = scan_tree(args.path)
    payload = {
        "valid": len(findings) == 0,
        "findings": [asdict(item) for item in findings],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2 if not args.json else None)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(text)
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
