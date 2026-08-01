import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researchhelm_cli import main  # noqa: E402

VALID_FIXTURE = ROOT / "tests" / "fixtures" / "minimal-valid-run"
INVALID_FIXTURE = ROOT / "tests" / "fixtures" / "invalid-malformed-json"


class CliDispatchTests(unittest.TestCase):
    def test_help_returns_zero(self):
        self.assertEqual(0, main(["--help"]))
        self.assertEqual(0, main([]))

    def test_unknown_command_returns_two(self):
        self.assertEqual(2, main(["no-such-command"]))

    def test_validate_accepts_valid_fixture(self):
        self.assertEqual(0, main(["validate", str(VALID_FIXTURE)]))

    def test_validate_rejects_malformed_fixture(self):
        self.assertEqual(1, main(["validate", str(INVALID_FIXTURE)]))

    def test_render_produces_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "cockpit.html"
            self.assertEqual(
                0, main(["render", str(VALID_FIXTURE), "--output", str(out)])
            )
            self.assertTrue(out.exists())
            self.assertIn(b"<!doctype html>", out.read_bytes()[:200].lower())

    def test_compat_sync_readme_check_returns_zero(self):
        self.assertEqual(0, main(["compat", "sync-readme", "--check"]))

    def test_verify_returns_zero(self):
        self.assertEqual(0, main(["verify"]))

    def test_inspect_accepts_safe_skill_fixture(self):
        self.assertEqual(
            0,
            main(
                [
                    "inspect",
                    str(ROOT / "tests" / "fixtures" / "skills" / "safe-skill"),
                    "--source",
                    "https://example.test/safe",
                    "--revision",
                    "abc123",
                ]
            ),
        )

    def test_python_dash_m_help(self):
        proc = subprocess.run(
            [sys.executable, "-m", "researchhelm_cli", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, proc.returncode)
        self.assertIn("researchhelm — ResearchHelm protocol toolchain", proc.stdout)


if __name__ == "__main__":
    unittest.main()
