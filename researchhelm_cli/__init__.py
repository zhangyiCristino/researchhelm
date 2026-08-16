"""ResearchHelm command-line interface (standard library only).

Wraps the canonical protocol scripts. Prefers the live repository tree when
present; otherwise loads scripts bundled inside this package so
``pip install researchhelm`` works without an editable checkout.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_ROOT = _PACKAGE_DIR.parents[0]
# When installed as a site-packages module, parents[0] is site-packages — not the repo.
# Detect a real checkout by looking for the skill scripts path.
_REPO_SCRIPTS = _ROOT / "skills" / "researchhelm" / "scripts"
_REPO_ROOT_SCRIPTS = _ROOT / "scripts"
_BUNDLED_SCRIPTS = _PACKAGE_DIR / "bundled" / "scripts"
_BUNDLED_ROOT = _PACKAGE_DIR / "bundled" / "root"

if _REPO_SCRIPTS.is_dir():
    _SCRIPTS_DIR = _REPO_SCRIPTS
    _QUICK_VERIFY = _REPO_ROOT_SCRIPTS / "quick_verify.py"
    _CREDENTIAL_SCAN = _REPO_ROOT_SCRIPTS / "credential_scan.py"
    _NATIVE_PREFLIGHT = _REPO_ROOT_SCRIPTS / "native_preflight.py"
    _LOAD_ROOT = _ROOT
else:
    _SCRIPTS_DIR = _BUNDLED_SCRIPTS
    _QUICK_VERIFY = _BUNDLED_ROOT / "quick_verify.py"
    _CREDENTIAL_SCAN = _BUNDLED_ROOT / "credential_scan.py"
    _NATIVE_PREFLIGHT = _BUNDLED_ROOT / "native_preflight.py"
    _LOAD_ROOT = _PACKAGE_DIR / "bundled"

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
  researchhelm init <run_dir> [--run-id ID]                         Scaffold a valid run directory
  researchhelm doctor                                              Report install/script health (no secrets)
  researchhelm scan-credentials <path>                             Independent filename credential scan
  researchhelm recommend-model --stage STAGE [--role ROLE]         Recommend a model tier by complexity
  researchhelm verify                                              Run the quick smoke check (repo checkout)
  researchhelm -h | --help                                         Show this help
"""

_COMMANDS = {
    "validate": "validate_state",
    "render": "render_cockpit",
    "audit": "audit_release",
    "sanitize": "sanitize_export",
    "compat": "validate_compatibility",
    "inspect": "inspect_skill",
    "recommend-model": "recommend_model",
}


def _resolve_script(script_name: str) -> Path | None:
    for base in (_SCRIPTS_DIR, _BUNDLED_SCRIPTS):
        path = base / f"{script_name}.py"
        if path.is_file():
            return path
    return None


def _load_path(path: Path, name: str):
    """Load a script by file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load(script_name: str):
    path = _resolve_script(script_name)
    if path is None:
        raise FileNotFoundError(
            f"canonical script not found: {script_name}.py "
            f"(looked in {_SCRIPTS_DIR} and {_BUNDLED_SCRIPTS})"
        )
    return _load_path(path, f"researchhelm_canonical_{script_name}")


def main(argv=None) -> int:
    # Canonical scripts import each other as siblings and via package paths.
    script_dir = _resolve_script("validate_state")
    script_parent = script_dir.parent if script_dir else _SCRIPTS_DIR
    for entry in (str(_LOAD_ROOT), str(script_parent), str(_ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    command, rest = args[0], args[1:]

    if command == "verify":
        if not _QUICK_VERIFY.is_file():
            print(
                "researchhelm verify: quick_verify.py not available in this install",
                file=sys.stderr,
            )
            return 1
        return _load_path(_QUICK_VERIFY, "researchhelm_quick_verify").main()

    if command == "init":
        from researchhelm_cli.init_run import main as init_main

        return init_main(rest)

    if command == "doctor":
        from researchhelm_cli.doctor import main as doctor_main

        return doctor_main(rest)

    if command == "scan-credentials":
        if not _CREDENTIAL_SCAN.is_file():
            print(
                "researchhelm scan-credentials: credential_scan.py not found",
                file=sys.stderr,
            )
            return 1
        return _load_path(_CREDENTIAL_SCAN, "researchhelm_credential_scan").main(rest)

    if command not in _COMMANDS:
        print(f"researchhelm: unknown command '{command}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    try:
        module = _load(_COMMANDS[command])
    except FileNotFoundError as exc:
        print(f"researchhelm: {exc}", file=sys.stderr)
        return 1
    return module.main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
