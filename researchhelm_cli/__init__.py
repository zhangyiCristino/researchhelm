"""ResearchHelm command-line interface (standard library only).

This package wraps the canonical protocol scripts under
``skills/researchhelm/scripts/`` without modifying them, so the skill folder
stays contract-pinned. Every subcommand delegates to the script's own
``main(argv)`` entry point.

Usage: ``researchhelm <command> [args...]``
"""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _ROOT / "skills" / "researchhelm" / "scripts"
_QUICK_VERIFY = _ROOT / "scripts" / "quick_verify.py"

USAGE = """\
researchhelm — ResearchHelm protocol toolchain (standard library only)

Usage:
  researchhelm validate <run_dir>                                  Validate a run state directory
  researchhelm render <run_dir> [--output FILE] [--public]         Render the Research Cockpit HTML
  researchhelm audit <worktree|history|archive|all> [--root DIR] [--ref REF] [--policy FILE]
  researchhelm sanitize scan-state <run_dir>                       Scan a run for public-export readiness
  researchhelm sanitize public-export <run_dir> <output_dir>       Create a sanitized public export
  researchhelm compat validate <path> [--max-age-days N]           Validate a compatibility registry
  researchhelm compat render <path> [--max-age-days N]             Render the compatibility table
  researchhelm compat sync-readme [--check]                        Sync the README compatibility table
  researchhelm inspect <root> [--source] [--revision]              Inspect a skill folder
  researchhelm verify                                              Run the quick smoke check
  researchhelm -h | --help                                         Show this help
"""

_COMMANDS = {
    "validate": "validate_state",
    "render": "render_cockpit",
    "audit": "audit_release",
    "sanitize": "sanitize_export",
    "compat": "validate_compatibility",
    "inspect": "inspect_skill",
}


def _load_path(path: Path, name: str):
    """Load a canonical script by file path without touching the skill folder."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load(script_name: str):
    return _load_path(_SCRIPTS_DIR / f"{script_name}.py", f"researchhelm_canonical_{script_name}")


def main(argv=None) -> int:
    # Canonical scripts import each other both as siblings
    # (``from sanitize_export import ...``) and via the repository package
    # path (``from skills.researchhelm.scripts...``); expose both roots so the
    # same files run identically inside the repo and from a pip install.
    for entry in (str(_ROOT), str(_SCRIPTS_DIR)):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    command, rest = args[0], args[1:]

    if command == "verify":
        return _load_path(_QUICK_VERIFY, "researchhelm_quick_verify").main()

    if command not in _COMMANDS:
        print(f"researchhelm: unknown command '{command}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    module = _load(_COMMANDS[command])
    return module.main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
