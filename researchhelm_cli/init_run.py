"""Scaffold a protocol-valid run directory from the minimal fixture."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent
_ROOT = _PACKAGE.parents[0]
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _resolve_fixture() -> Path:
    candidates = (
        _ROOT / "tests" / "fixtures" / "minimal-valid-run",
        _PACKAGE / "bundled" / "fixtures" / "minimal-valid-run",
    )
    for path in candidates:
        if path.is_dir() and (path / "research-brief.json").is_file():
            return path
    raise FileNotFoundError(
        "minimal-valid-run fixture not found; reinstall researchhelm or use a repo checkout"
    )


def init_run(target: Path, run_id: str | None = None) -> Path:
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"refusing to init non-empty directory: {target}")

    fixture = _resolve_fixture()
    rid = run_id or target.name
    if not _RUN_ID_RE.match(rid):
        raise ValueError(
            f"invalid run_id {rid!r}; use letters, digits, dot, underscore, hyphen (max 64)"
        )

    target.mkdir(parents=True, exist_ok=True)
    for src in fixture.iterdir():
        if src.is_file():
            shutil.copy2(src, target / src.name)

    brief_path = target / "research-brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    brief["run_id"] = rid
    brief_path.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    claims_path = target / "claim-evidence.json"
    if claims_path.is_file():
        claims = json.loads(claims_path.read_text(encoding="utf-8"))
        for claim in claims.get("claims", []):
            if isinstance(claim.get("run_ids"), list):
                claim["run_ids"] = [
                    rid if item == "minimal-valid-run" else item
                    for item in claim["run_ids"]
                ]
        claims_path.write_text(
            json.dumps(claims, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return target


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: researchhelm init <run_dir> [--run-id ID]\n"
            "  Scaffold a protocol-valid run directory from the minimal fixture.\n"
            "  The directory must not already contain files."
        )
        return 0
    run_id = None
    path_args: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--run-id" and i + 1 < len(args):
            run_id = args[i + 1]
            i += 2
            continue
        path_args.append(args[i])
        i += 1
    if len(path_args) != 1:
        print("researchhelm init: provide exactly one run_dir", file=sys.stderr)
        return 2
    try:
        out = init_run(Path(path_args[0]), run_id=run_id)
    except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"researchhelm init: {exc}", file=sys.stderr)
        return 1
    print(out)
    print(
        "Scaffolded a synthetic valid run state. "
        "Replace fields for real research; silence is not approval.",
        file=sys.stderr,
    )
    return 0
