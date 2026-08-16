"""Environment and install health check for ResearchHelm CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def _version(command: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            command, text=True, capture_output=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (proc.stdout or proc.stderr).strip().splitlines()
    return lines[0] if lines else None


def run_doctor() -> dict:
    import researchhelm_cli as cli

    scripts = {}
    for name in (
        "validate_state",
        "render_cockpit",
        "audit_release",
        "sanitize_export",
        "validate_compatibility",
        "inspect_skill",
    ):
        path = cli._resolve_script(name)
        scripts[name] = str(path) if path and path.is_file() else None

    skill_home = Path.home() / ".claude" / "skills" / "researchhelm" / "SKILL.md"
    repo_marker = cli._ROOT / "skills" / "researchhelm" / "SKILL.md"
    report = {
        "python": _version([sys.executable, "--version"]),
        "git": _version(["git", "--version"]),
        "claude": _version(["claude", "--version"]),
        "repo_checkout": repo_marker.is_file(),
        "scripts_dir": str(cli._SCRIPTS_DIR) if cli._SCRIPTS_DIR.is_dir() else None,
        "canonical_scripts": scripts,
        "quick_verify": str(cli._QUICK_VERIFY) if cli._QUICK_VERIFY.is_file() else None,
        "credential_scan": str(cli._CREDENTIAL_SCAN)
        if cli._CREDENTIAL_SCAN.is_file()
        else None,
        "user_skill_installed": skill_home.is_file(),
        "user_skill_path": str(skill_home) if skill_home.is_file() else None,
        "path_researchhelm": shutil.which("researchhelm"),
    }
    missing_scripts = [k for k, v in scripts.items() if not v]
    report["ok"] = (
        report["python"] is not None
        and report["git"] is not None
        and not missing_scripts
    )
    report["missing_scripts"] = missing_scripts
    return report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        print(
            "usage: researchhelm doctor\n"
            "  Report CLI/script resolution, git/python availability, and optional skill install.\n"
            "  Does not read credential stores or client config contents."
        )
        return 0
    report = run_doctor()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1
