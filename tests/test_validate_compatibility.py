import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "skills"
    / "researchhelm"
    / "scripts"
    / "validate_compatibility.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "validate_compatibility", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = ROOT / "tests" / "fixtures" / "compatibility"

    def validate_data(
        self,
        module,
        data,
        today=date(2026, 7, 13),
        max_age_days=90,
    ):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "registry.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return module.validate_registry(path, today, max_age_days)

    def test_valid_registry_passes_and_renders(self):
        module = load_module()
        module._commit_contains_evidence = lambda commit, evidence: True
        path = self.fixture_dir / "valid.json"
        self.assertEqual(
            [], module.validate_registry(path, date(2026, 7, 13))
        )
        table = module.render_markdown(
            json.loads(path.read_text(encoding="utf-8"))
        )
        self.assertIn(
            "| Client | Label | Version | Tested | Evidence |", table
        )

    def test_stale_native_claim_is_rejected(self):
        module = load_module()
        module._commit_contains_evidence = lambda commit, evidence: True
        path = self.fixture_dir / "stale.json"
        findings = module.validate_registry(path, date(2026, 7, 13))
        self.assertIn(
            "compatibility.needs_revalidation",
            {item.code for item in findings},
        )

    def test_every_claim_has_immutable_evidence(self):
        module = load_module()
        registry = ROOT / "evals" / "compatibility" / "clients.json"
        self.assertEqual([], module.validate_registry(registry, date.today()))

    def test_commit_must_contain_evidence_and_metadata_is_rejected(self):
        module = load_module()
        valid = json.loads(
            (self.fixture_dir / "valid.json").read_text(encoding="utf-8")
        )
        valid["claims"][0]["commit"] = "0" * 40
        codes = {
            finding.code for finding in self.validate_data(module, valid)
        }
        self.assertIn("compatibility.unverified_commit_evidence", codes)

        valid["claims"][0]["evidence"] = ".git/HEAD"
        codes = {
            finding.code for finding in self.validate_data(module, valid)
        }
        self.assertIn("compatibility.invalid_evidence", codes)

    def test_claim_contract_rejects_invalid_fields(self):
        module = load_module()
        valid = json.loads(
            (self.fixture_dir / "valid.json").read_text(encoding="utf-8")
        )
        cases = (
            ("label", "invented", "compatibility.invalid_label"),
            ("client", "", "compatibility.missing_client"),
            ("version", "", "compatibility.missing_version"),
            (
                "operating_system",
                "",
                "compatibility.missing_operating_system",
            ),
            (
                "install_command",
                "",
                "compatibility.missing_install_command",
            ),
            ("tested_at", "not-a-date", "compatibility.invalid_tested_at"),
            (
                "commit",
                "ABCDEF0123456789ABCDEF0123456789ABCDEF01",
                "compatibility.invalid_commit",
            ),
            (
                "evidence",
                "../outside.txt",
                "compatibility.invalid_evidence",
            ),
            (
                "limitations",
                "none",
                "compatibility.invalid_limitations",
            ),
        )
        for field, value, expected in cases:
            with self.subTest(field=field):
                data = json.loads(json.dumps(valid))
                data["claims"][0][field] = value
                codes = {
                    finding.code
                    for finding in self.validate_data(module, data)
                }
                self.assertIn(expected, codes)

    def test_duplicate_claim_is_rejected(self):
        module = load_module()
        data = json.loads(
            (self.fixture_dir / "valid.json").read_text(encoding="utf-8")
        )
        data["claims"].append(dict(data["claims"][0]))
        codes = {
            finding.code for finding in self.validate_data(module, data)
        }
        self.assertIn("compatibility.duplicate_claim", codes)

    def test_malformed_registry_is_a_finding(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "registry.json"
            path.write_text("{", encoding="utf-8")
            findings = module.validate_registry(path, date(2026, 7, 13))
        self.assertEqual(
            ["compatibility.invalid_json"],
            [finding.code for finding in findings],
        )

    def test_render_sorts_escapes_pipes_and_marks_stale(self):
        module = load_module()
        data = json.loads(
            (self.fixture_dir / "valid.json").read_text(encoding="utf-8")
        )
        standard = dict(data["claims"][0])
        standard.update(
            {
                "client": "A|Client",
                "label": "Standard-validated",
                "tested_at": date.today().isoformat(),
            }
        )
        stale = dict(data["claims"][0])
        stale.update(
            {
                "client": "B Client",
                "label": "Native-tested",
                "tested_at": "2000-01-01",
                "commit": "abcdef0123456789abcdef0123456789abcdef01",
            }
        )
        table = module.render_markdown(
            {
                "schema_version": 1,
                "max_age_days": 90,
                "claims": [stale, standard],
            }
        )
        self.assertIn("A\\|Client", table)
        self.assertIn("needs revalidation", table)
        self.assertLess(table.index("A\\|Client"), table.index("B Client"))

    def test_freshness_policy_can_tighten_but_never_exceed_90_days(self):
        module = load_module()
        module._commit_contains_evidence = lambda commit, evidence: True
        data = json.loads(
            (self.fixture_dir / "valid.json").read_text(encoding="utf-8")
        )
        findings = self.validate_data(
            module,
            data,
            today=date(2026, 10, 12),
        )
        self.assertIn(
            "compatibility.needs_revalidation",
            {finding.code for finding in findings},
        )

        data["max_age_days"] = 30
        findings = self.validate_data(
            module,
            data,
            today=date(2026, 8, 13),
        )
        self.assertIn(
            "compatibility.needs_revalidation",
            {finding.code for finding in findings},
        )

        data["max_age_days"] = 365
        findings = self.validate_data(
            module,
            data,
            today=date(2026, 10, 12),
            max_age_days=365,
        )
        self.assertIn(
            "compatibility.invalid_max_age_days",
            {finding.code for finding in findings},
        )
        data["claims"][0]["tested_at"] = "2000-01-01"
        self.assertIn("needs revalidation", module.render_markdown(data))

    def test_cli_validate_render_and_usage_exit_codes(self):
        valid = ROOT / "evals" / "compatibility" / "clients.json"
        stale = self.fixture_dir / "stale.json"
        validated = subprocess.run(
            [sys.executable, str(SCRIPT), "validate", str(valid)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validated.returncode, validated.stderr)
        rendered = subprocess.run(
            [sys.executable, str(SCRIPT), "render", str(valid)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        self.assertTrue(rendered.stdout.startswith("| Client | Label |"))
        rejected = subprocess.run(
            [sys.executable, str(SCRIPT), "validate", str(stale)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, rejected.returncode)
        overlong = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "render",
                str(stale),
                "--max-age-days",
                "365",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, overlong.returncode)
        self.assertIn("compatibility.invalid_max_age_days", overlong.stderr)
        usage = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, usage.returncode)

    def test_live_registry_has_no_unverified_native_claim(self):
        registry = json.loads(
            (ROOT / "evals" / "compatibility" / "clients.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn(
            "Native-tested", {claim["label"] for claim in registry["claims"]}
        )

    def test_compatibility_issue_form_requires_reproducible_evidence(self):
        text = (
            ROOT
            / ".github"
            / "ISSUE_TEMPLATE"
            / "compatibility-report.yml"
        ).read_text(encoding="utf-8")
        for field in (
            "client_name",
            "client_version",
            "operating_system",
            "repository_commit",
            "tested_at",
            "install_command",
            "scope",
            "label_requested",
            "scenario_ids",
            "raw_evidence",
            "limitations",
            "data_safety",
        ):
            self.assertIn(f"id: {field}", text)
        self.assertIn("Community-reported", text)
        for sensitive_class in (
            "secrets",
            "credentials",
            "account identifiers",
            "private research data",
            "personal paths",
            "machine identifiers",
        ):
            self.assertIn(sensitive_class, text)
        self.assertIn("Redacted raw evidence or immutable artifact link", text)

    def test_sync_readme_check_accepts_only_canonical_blocks(self):
        checked = subprocess.run(
            [sys.executable, str(SCRIPT), "sync-readme", "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, checked.returncode, checked.stderr)

        module = load_module()
        registry = json.loads(
            (ROOT / "evals" / "compatibility" / "clients.json").read_text(
                encoding="utf-8"
            )
        )
        rendered = module.render_markdown(registry).rstrip()
        for readme in (ROOT / "README.md", ROOT / "README.zh-CN.md"):
            text = readme.read_text(encoding="utf-8")
            self.assertEqual(1, text.count(module.START), readme.name)
            self.assertEqual(1, text.count(module.END), readme.name)
            block = text.split(module.START, 1)[1].split(module.END, 1)[0]
            self.assertEqual(rendered, block.strip(), readme.name)

    def test_marked_block_requires_exactly_one_marker_pair(self):
        module = load_module()
        valid = f"before{module.START}\nold\n{module.END}after"
        replaced = module.replace_marked_block(valid, "new\n")
        self.assertEqual(
            f"before{module.START}\nnew\n{module.END}after", replaced
        )
        for invalid in ("no markers", valid + module.START, valid + module.END):
            with self.subTest(invalid=invalid[-20:]):
                with self.assertRaises(ValueError):
                    module.replace_marked_block(invalid, "new")

    def test_sync_check_makes_no_writes_and_sync_is_idempotent(self):
        module = load_module()
        registry_text = (
            ROOT / "evals" / "compatibility" / "clients.json"
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            registry = root / "evals" / "compatibility" / "clients.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(registry_text, encoding="utf-8")
            original = f"before\n{module.START}\nstale\n{module.END}\nafter\n"
            readmes = (root / "README.md", root / "README.zh-CN.md")
            for path in readmes:
                path.write_text(original, encoding="utf-8")

            self.assertFalse(module.sync_readmes(root, check=True))
            self.assertEqual(
                [original, original],
                [path.read_text(encoding="utf-8") for path in readmes],
            )

            self.assertTrue(module.sync_readmes(root))
            first = [
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in readmes
            ]
            self.assertTrue(module.sync_readmes(root))
            second = [
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in readmes
            ]
            self.assertEqual(first, second)
            self.assertEqual([], list(root.rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
