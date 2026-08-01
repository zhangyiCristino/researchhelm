"""Environment preflight for Native-tested compatibility verification.

Checks only that required commands exist and report their versions. It never
reads, lists, or inspects any client configuration directory, browser
profile, credential helper, SSH/GPG key, or environment dump, per the
project's privacy boundary.

Usage:
    python scripts/native_preflight.py
"""

import json
import shutil
import subprocess
import sys


def _version(command: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return first[0] if first else None


def main() -> int:
    checks = {
        "git": _version(["git", "--version"]),
        "python": _version([sys.executable, "--version"]),
        "claude": _version(["claude", "--version"]),
    }
    present = {name: version for name, version in checks.items() if version}
    missing = [name for name, version in checks.items() if not version]
    print(json.dumps({"present": present, "missing": missing}, sort_keys=True))
    return 0 if "claude" in present else 1


if __name__ == "__main__":
    raise SystemExit(main())
