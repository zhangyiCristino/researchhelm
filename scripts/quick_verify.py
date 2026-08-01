"""Quick smoke check for contributors.

Runs the repository-contract test modules and the compatibility README sync
check without the full 270+ test suite. Standard library only.

Usage:
    python scripts/quick_verify.py
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tests.test_repository_contracts",
    "tests.test_legacy_compatibility",
    "tests.test_validate_compatibility",
    "tests.test_skill_contract",
)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    ok = result.wasSuccessful()

    sync = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills" / "researchhelm" / "scripts" / "validate_compatibility.py"),
            "sync-readme",
            "--check",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if sync.returncode != 0:
        print("compatibility sync-readme check FAILED")
        print(sync.stderr or sync.stdout)
        ok = False
    else:
        print("compatibility sync-readme check OK")

    print("quick verify:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
