import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "validate_state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("validate_state", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ValidateStateTests(unittest.TestCase):
    def copy_valid_run(self, temporary_directory):
        run_dir = Path(temporary_directory) / "run"
        shutil.copytree(ROOT / "tests" / "fixtures" / "minimal-valid-run", run_dir)
        return run_dir

    def read_jsonl(self, path):
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def write_jsonl(self, path, records):
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )

    def test_minimal_valid_run_has_no_errors(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "minimal-valid-run")
        self.assertEqual([], [item for item in findings if item.severity == "error"])

    def test_stale_approval_is_rejected(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-stale-approval")
        self.assertEqual(
            ["approval.input_hash_mismatch"], [item.code for item in findings]
        )

    def test_crash_cannot_have_numeric_primary_metric(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-crash-metric")
        self.assertEqual(
            ["experiment.crash_metric_must_be_null"],
            [item.code for item in findings],
        )

    def test_append_only_decision_chain_is_verified(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-broken-chain")
        self.assertEqual(["decision.hash_chain_broken"], [item.code for item in findings])

    def test_skill_use_requires_exact_approval_binding(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-skill-approval")
        self.assertEqual(
            ["recommendation.approval_binding_mismatch"],
            [item.code for item in findings],
        )

    def test_resume_hash_drift_is_rejected(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-resume-drift")
        self.assertEqual(["resume.hash_mismatch"], [item.code for item in findings])

    def test_artifact_path_cannot_escape_run(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-artifact-path")
        self.assertEqual(["artifact.path_escapes_run"], [item.code for item in findings])

    def test_artifact_id_must_be_a_safe_single_segment(self):
        module = load_module()
        unsafe_ids = (
            ".",
            "..",
            "/" + "absolute",
            "C:" + "\\" + "absolute",
            "nested/name",
            "nested" + "\\" + "name",
            ".." + "/" + "outside",
        )
        for index, artifact_id in enumerate(unsafe_ids):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary_directory:
                run_dir = self.copy_valid_run(temporary_directory)
                path = run_dir / "artifact-manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["artifacts"][0]["artifact_id"] = artifact_id
                path.write_text(json.dumps(manifest), encoding="utf-8")
                findings = module.validate_run(run_dir)
                self.assertIn(
                    "artifact.invalid_id", [item.code for item in findings]
                )

    def test_malformed_json_becomes_a_finding(self):
        module = load_module()
        findings = module.validate_run(ROOT / "tests" / "fixtures" / "invalid-malformed-json")
        self.assertEqual(["json.malformed"], [item.code for item in findings])

    def test_hash_is_key_order_independent(self):
        module = load_module()
        self.assertEqual(module.hash_json({"a": 1, "b": 2}), module.hash_json({"b": 2, "a": 1}))

    def test_recommendation_card_requires_explicit_used_boolean(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "skill-recommendations.jsonl"
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            del records[0]["used"]
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            findings = module.validate_run(run_dir)
        self.assertIn("schema.invalid_enum", {item.code for item in findings})

    def test_recommendation_approval_binds_stage_exactly(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "skill-recommendations.jsonl"
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            records[1]["stage"] = "PACKAGE"
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            findings = module.validate_run(run_dir)
        self.assertIn("recommendation.approval_binding_mismatch", {item.code for item in findings})

    def test_resume_snapshot_requires_every_binding_field(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            del brief["resume"]["expected"]["branch"]
            del brief["resume"]["actual"]["branch"]
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertIn("resume.hash_mismatch", {item.code for item in findings})

    def test_non_finite_json_becomes_a_finding(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "evidence.jsonl"
            text = path.read_text(encoding="utf-8").replace(
                '"notes":"Local normative design evidence."', '"notes":NaN'
            )
            path.write_text(text, encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertIn("json.malformed", {item.code for item in findings})

    def test_artifact_frozen_flag_must_be_boolean(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "artifact-manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["artifacts"][0]["frozen"] = "yes"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertIn("schema.invalid_enum", {item.code for item in findings})

    def test_command_record_must_be_a_sanitized_template(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["constraints"]["commands"] = [
                {"command_line": "tool --auth <redacted:credential>"}
            ]
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertIn("schema.invalid_enum", {item.code for item in findings})

    def test_environment_shape_is_portable(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            ledger_path = run_dir / "experiment-ledger.jsonl"
            record = json.loads(ledger_path.read_text(encoding="utf-8"))
            record["environment"]["runtime"] = ["CPython"]
            ledger_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_claim_shape_is_portable(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            claims_path = run_dir / "claim-evidence.json"
            claims = json.loads(claims_path.read_text(encoding="utf-8"))
            claims["claims"][0]["citations"] = "evidence-001"
            claims_path.write_text(json.dumps(claims), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_source_jsonl_line_field_is_reserved(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "evidence.jsonl"
            records = self.read_jsonl(path)
            records[0]["_line"] = "source-value"
            self.write_jsonl(path, records)
            loaded = module.load_jsonl(path)
            findings = module.validate_run(run_dir)
        self.assertEqual("source-value", loaded[0]["_line"])
        self.assertEqual(["schema.reserved_field"], [item.code for item in findings])

    def test_crash_requires_explicit_null_primary_metric(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "experiment-ledger.jsonl"
            records = self.read_jsonl(path)
            records[0]["status"] = "crash"
            del records[0]["metrics"]["primary"]
            self.write_jsonl(path, records)
            findings = module.validate_run(run_dir)
        self.assertEqual(
            ["experiment.crash_metric_must_be_null"],
            [item.code for item in findings],
        )

    def test_experiment_metrics_must_be_an_object(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "experiment-ledger.jsonl"
            records = self.read_jsonl(path)
            records[0]["metrics"] = []
            self.write_jsonl(path, records)
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_resume_must_be_an_object(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["resume"] = []
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_resume_enabled_must_be_boolean(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["resume"]["enabled"] = "true"
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_idea_scores_require_exact_numeric_dimensions(self):
        module = load_module()
        mutations = (
            ("missing", lambda scores: scores.pop("risk")),
            ("extra", lambda scores: scores.update({"novelty": 5})),
            ("non_numeric", lambda scores: scores.update({"risk": "low"})),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_directory:
                run_dir = self.copy_valid_run(temporary_directory)
                path = run_dir / "idea-candidates.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                mutate(data["candidates"][0]["scores"])
                path.write_text(json.dumps(data), encoding="utf-8")
                findings = module.validate_run(run_dir)
                self.assertEqual(
                    ["schema.invalid_enum"], [item.code for item in findings]
                )

    def test_idea_risks_require_string_elements(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "idea-candidates.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["candidates"][0]["risks"] = [1]
            path.write_text(json.dumps(data), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_idea_pivots_require_string_elements(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "idea-candidates.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["candidates"][0]["pivots"] = [{}]
            path.write_text(json.dumps(data), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.invalid_enum"], [item.code for item in findings])

    def test_missing_source_file_has_stable_code(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            (run_dir / "evidence.jsonl").unlink()
            findings = module.validate_run(run_dir)
        self.assertEqual(["run.missing_file"], [item.code for item in findings])

    def test_schema_version_mismatch_has_stable_code(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["schema_version"] = "2.0"
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertEqual(["schema.version_mismatch"], [item.code for item in findings])

    def test_invalid_sha256_has_stable_code(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "evidence.jsonl"
            records = self.read_jsonl(path)
            records[0]["content_hash"] = "not-a-sha256"
            self.write_jsonl(path, records)
            findings = module.validate_run(run_dir)
        self.assertEqual(["hash.invalid_sha256"], [item.code for item in findings])

    def test_used_recommendation_requires_approval(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "skill-recommendations.jsonl"
            records = self.read_jsonl(path)
            self.write_jsonl(path, records[:1])
            findings = module.validate_run(run_dir)
        self.assertEqual(
            ["recommendation.approval_missing"],
            [item.code for item in findings],
        )

    def test_secret_content_is_invalid_before_persistence(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            token = "sk" + "-proj-" + ("A" * 48)
            brief["public_summary"] = token
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertIn(
            "security.high_confidence_content", {item.code for item in findings}
        )
        self.assertNotIn(token, json.dumps([item.__dict__ for item in findings]))

    def test_findings_use_logical_state_paths(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["schema_version"] = "2.0"
            path.write_text(json.dumps(brief), encoding="utf-8")
            findings = module.validate_run(run_dir)
        self.assertTrue(findings)
        self.assertTrue(all(not Path(item.path).is_absolute() for item in findings))

    def test_independent_classification_error_is_not_hidden_by_schema_error(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["schema_version"] = "2.0"
            del brief["field_sensitivity"]
            path.write_text(json.dumps(brief), encoding="utf-8")
            codes = {item.code for item in module.validate_run(run_dir)}
        self.assertTrue(
            {
                "schema.version_mismatch",
                "privacy.missing_classification",
            }.issubset(codes)
        )

    def test_leaf_classification_error_is_not_hidden_by_unrelated_schema_error(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["schema_version"] = "2.0"
            del brief["field_sensitivity"]["/" + "public_summary"]
            path.write_text(json.dumps(brief), encoding="utf-8")
            codes = {item.code for item in module.validate_run(run_dir)}
        self.assertTrue(
            {
                "schema.version_mismatch",
                "privacy.missing_classification",
            }.issubset(codes)
        )

    def test_unknown_extra_leaf_and_unrelated_schema_error_are_both_reported(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["schema_version"] = "2.0"
            brief["unclassified_note"] = "safe synthetic note"
            path.write_text(json.dumps(brief), encoding="utf-8")
            codes = {item.code for item in module.validate_run(run_dir)}
        self.assertTrue(
            {
                "schema.version_mismatch",
                "privacy.missing_classification",
            }.issubset(codes)
        )

    def test_stale_pointer_and_unrelated_schema_error_are_both_reported(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = self.copy_valid_run(temporary_directory)
            path = run_dir / "research-brief.json"
            brief = json.loads(path.read_text(encoding="utf-8"))
            brief["schema_version"] = "2.0"
            brief["field_sensitivity"]["/" + "missing_synthetic_field"] = "public"
            path.write_text(json.dumps(brief), encoding="utf-8")
            codes = {item.code for item in module.validate_run(run_dir)}
        self.assertTrue(
            {
                "schema.version_mismatch",
                "privacy.classification_path_missing",
            }.issubset(codes)
        )


if __name__ == "__main__":
    unittest.main()
