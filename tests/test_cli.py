import json
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

    def test_init_scaffolds_valid_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "demo-run"
            self.assertEqual(0, main(["init", str(target), "--run-id", "demo-run"]))
            self.assertTrue((target / "research-brief.json").is_file())
            brief = json.loads((target / "research-brief.json").read_text(encoding="utf-8"))
            self.assertEqual("demo-run", brief["run_id"])
            self.assertEqual(0, main(["validate", str(target)]))

    def test_init_refuses_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "busy"
            target.mkdir()
            (target / "x.txt").write_text("x", encoding="utf-8")
            self.assertEqual(1, main(["init", str(target)]))

    def test_doctor_returns_zero(self):
        self.assertEqual(0, main(["doctor"]))

    def test_scan_credentials_clean_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "readme.txt").write_text("ok", encoding="utf-8")
            self.assertEqual(0, main(["scan-credentials", str(path)]))

    def test_scan_credentials_flags_forbidden_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text("x=1", encoding="utf-8")
            self.assertEqual(1, main(["scan-credentials", str(path)]))

    def test_recommend_model_gate_4_frontier(self):
        result = main([
            "recommend-model",
            "--stage", "GATE_4_CLAIMS",
            "--novelty", "2",
            "--ambiguity", "3",
            "--scope", "1",
            "--risk", "5",
            "--reversibility", "5",
            "--safety", "5",
        ])
        self.assertEqual(0, result)

    def test_recommend_model_build_balanced(self):
        result = main([
            "recommend-model",
            "--stage", "BUILD",
            "--novelty", "5",
            "--ambiguity", "4",
            "--scope", "5",
            "--risk", "4",
            "--reversibility", "5",
            "--safety", "3",
        ])
        self.assertEqual(0, result)

    def test_python_dash_m_help(self):
        proc = subprocess.run(
            [sys.executable, "-m", "researchhelm_cli", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, proc.returncode)
        self.assertIn("ResearchHelm protocol toolchain", proc.stdout)
        self.assertIn("init", proc.stdout)
        self.assertIn("doctor", proc.stdout)


class BundledScriptsTests(unittest.TestCase):
    def test_bundled_scripts_match_canonical_when_present(self):
        canonical = ROOT / "skills" / "researchhelm" / "scripts"
        bundled = ROOT / "researchhelm_cli" / "bundled" / "scripts"
        names = sorted(p.name for p in canonical.glob("*.py"))
        self.assertTrue(names)
        for name in names:
            left = (canonical / name).read_bytes()
            right = (bundled / name).read_bytes()
            self.assertEqual(left, right, name)

    def test_bundled_root_helpers_present(self):
        root = ROOT / "researchhelm_cli" / "bundled" / "root"
        for name in ("quick_verify.py", "native_preflight.py", "credential_scan.py"):
            self.assertTrue((root / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
