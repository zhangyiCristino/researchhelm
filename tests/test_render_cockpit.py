import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "render_cockpit.py"
TEMPLATE = ROOT / "skills" / "researchhelm" / "assets" / "templates" / "research-cockpit.html"
FIXTURE = ROOT / "tests" / "fixtures" / "complete-run"


def load_module():
    spec = importlib.util.spec_from_file_location("render_cockpit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RenderCockpitTests(unittest.TestCase):
    def test_template_locks_accessible_offline_visual_contract(self):
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(1, template.count("__RESEARCHHELM_DATA__"))
        for section in (
            "resources",
            "ideas",
            "overlap",
            "decisions",
            "experiments",
            "claims",
        ):
            self.assertRegex(
                template,
                rf'<section id="{section}"[^>]+aria-labelledby="{section}-title"',
            )
        for marker in (
            'id="data-boundary" role="status"',
            "createElementNS",
            "Text equivalent",
            "@media print",
            "@media (max-width: 520px)",
        ):
            self.assertIn(marker, template)
        for unsafe_dom_api in ("innerHTML", "outerHTML", "document.write"):
            self.assertNotIn(unsafe_dom_api, template)

    def test_complete_fixture_covers_the_cockpit_story(self):
        def read_json(name):
            return json.loads((FIXTURE / name).read_text(encoding="utf-8"))

        def read_jsonl(name):
            return [
                json.loads(line)
                for line in (FIXTURE / name).read_text(encoding="utf-8").splitlines()
                if line
            ]

        self.assertEqual(2, len(read_json("idea-candidates.json")["candidates"]))
        decisions = read_jsonl("decision-log.jsonl")
        self.assertEqual(
            [
                "GATE_1_IDEA",
                "GATE_2_PLAN_AND_BUDGET",
                "GATE_3_FULL_RUN",
                "GATE_4_CLAIMS",
            ],
            [item["stage"] for item in decisions],
        )
        experiments = read_jsonl("experiment-ledger.jsonl")
        self.assertEqual(3, len(experiments))
        crashes = [item for item in experiments if item["status"] == "crash"]
        self.assertEqual(1, len(crashes))
        self.assertIsNone(crashes[0]["metrics"]["primary"])
        manifest = read_json("artifact-manifest.json")
        self.assertEqual(2, len(manifest["artifacts"]))
        for artifact in manifest["artifacts"]:
            digest = hashlib.sha256((FIXTURE / artifact["path"]).read_bytes()).hexdigest()
            self.assertEqual(artifact["sha256"], digest)
        claims = read_json("claim-evidence.json")["claims"]
        self.assertEqual(
            {"supported", "qualified", "unsupported"},
            {item["status"] for item in claims},
        )
        recommendations = read_jsonl("skill-recommendations.jsonl")
        self.assertTrue(recommendations[0]["used"])
        self.assertEqual("approve", recommendations[1]["decision"])

    def test_render_is_self_contained_and_complete(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "cockpit.html"
            module.render_cockpit(FIXTURE, output)
            html = output.read_text(encoding="utf-8")
            for pattern in (
                r"<script[^>]+src=",
                r"<link[^>]+href=",
                r"<img[^>]+src=['\"]https?://",
                r"url\(['\"]?https?://",
            ):
                self.assertIsNone(re.search(pattern, html, re.I), pattern)
            for marker in (
                "Resource envelope",
                "Idea map",
                "Overlap matrix",
                "Decision timeline",
                "Experiment Pareto",
                "Claim evidence",
            ):
                self.assertIn(marker, html)
            self.assertIn("Private local Cockpit - do not commit", html)
            self.assertNotIn("\ufffd", html)

    def test_render_reads_each_state_file_once(self):
        module = load_module()
        state_files = {
            "research-brief.json",
            "evidence.jsonl",
            "idea-candidates.json",
            "decision-log.jsonl",
            "skill-recommendations.jsonl",
            "experiment-ledger.jsonl",
            "artifact-manifest.json",
            "claim-evidence.json",
        }
        reads = {name: 0 for name in state_files}
        original_read_text = Path.read_text

        def tracked_read_text(path, *args, **kwargs):
            if path.parent == FIXTURE and path.name in reads:
                reads[path.name] += 1
            return original_read_text(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            Path, "read_text", tracked_read_text
        ):
            module.render_cockpit(FIXTURE, Path(tmp) / "cockpit.html")
        self.assertEqual({1}, set(reads.values()))

    def test_metric_normalizer_executes_null_as_nan(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js unavailable for template behavior test")
        template = TEMPLATE.read_text(encoding="utf-8")
        match = re.search(r"const finiteMetric = ([^;]+);", template)
        self.assertIsNotNone(match)
        script = (
            f"const finiteMetric = {match.group(1)};"
            "console.log(JSON.stringify(["
            "Number.isNaN(finiteMetric(null)),"
            "Number.isNaN(finiteMetric(undefined)),"
            "finiteMetric(0),finiteMetric(0.61),"
            "Number.isNaN(finiteMetric('0.61'))]));"
        )
        result = subprocess.run(
            [node, "-e", script],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [True, True, 0, 0.61, True], json.loads(result.stdout)
        )

    def test_embedded_data_cannot_close_script_tag(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "cockpit.html"
            module.render_cockpit(FIXTURE, output)
            html = output.read_text(encoding="utf-8")
            self.assertNotIn("</script><script>alert", html)

    def test_script_safe_json_escapes_breakout_sequences(self):
        module = load_module()
        payload = {"value": "</script><script>alert(1)</script>\u2028next"}
        encoded = module.script_safe_json(payload)
        self.assertNotIn("</script>", encoded.lower())
        self.assertIn("<\\/script>", encoded.lower())
        self.assertEqual(json.loads(encoded), payload)

    def test_invalid_state_is_not_rendered(self):
        module = load_module()
        invalid = ROOT / "tests" / "fixtures" / "invalid-stale-approval"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                module.render_cockpit(invalid, Path(tmp) / "cockpit.html")

    def test_public_render_refuses_raw_local_state(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                module.render_cockpit(FIXTURE, Path(tmp) / "cockpit.html", public=True)

    def test_public_render_accepts_only_sanitized_export(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            exported = Path(tmp) / "public"
            sanitize_public_run(FIXTURE, exported)
            output = Path(tmp) / "public-cockpit.html"
            module.render_cockpit(exported, output, public=True)
            html = output.read_text(encoding="utf-8")
            self.assertIn("Public sanitized export", html)
            self.assertNotIn("private_question", html)
            self.assertNotIn('"field_sensitivity"', html)

    def test_public_render_accepts_export_with_public_artifact(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            shutil.copytree(FIXTURE, run)
            payload = (
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "record_type": "metrics-summary",
                        "run_id": "complete-run",
                        "status": "complete",
                        "aggregate_metrics": {"macro_f1": 0.5},
                        "uncertainty": {},
                        "guardrails": {},
                        "runtime": {},
                        "limitations": [],
                        "artifact_hashes": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            source = run / "artifacts" / "public" / "metrics-summary.json"
            source.parent.mkdir(parents=True)
            source.write_bytes(payload)
            manifest_path = run / "artifact-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"].append(
                {
                    "artifact_id": "public-metrics",
                    "path": "artifacts/public/metrics-summary.json",
                    "kind": "metrics-summary",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "producing_run": "complete-run",
                    "frozen": True,
                }
            )
            index = len(manifest["artifacts"]) - 1
            slash = "/"
            pointer_root = slash + "artifacts" + slash + str(index) + slash
            manifest["field_sensitivity"][pointer_root + "path"] = "public"
            manifest["field_sensitivity"][pointer_root + "kind"] = "public"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            exported = root / "public"
            sanitize_public_run(run, exported)
            output = root / "public-cockpit.html"
            module.render_cockpit(exported, output, public=True)
            self.assertTrue(output.is_file())

    def test_public_render_rejects_inconsistent_artifact_count(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exported = root / "public"
            sanitize_public_run(FIXTURE, exported)
            report_path = exported / "sanitization-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["artifacts_exported"] += 1
            report_path.write_text(json.dumps(report), encoding="utf-8")
            output = root / "public-cockpit.html"
            with self.assertRaises(module.CockpitError) as raised:
                module.render_cockpit(exported, output, public=True)
            self.assertEqual(
                "ERR_PUBLIC_EXPORT_REQUIRED", raised.exception.code
            )
            self.assertFalse(output.exists())

    def test_public_render_rejects_replayed_report_on_private_run(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exported = root / "public"
            sanitize_public_run(FIXTURE, exported)
            forged = root / "forged"
            shutil.copytree(FIXTURE, forged)
            shutil.copy2(
                exported / "sanitization-report.json",
                forged / "sanitization-report.json",
            )
            output = root / "public-cockpit.html"
            with self.assertRaises(module.CockpitError) as raised:
                module.render_cockpit(forged, output, public=True)
            self.assertEqual("ERR_UNSAFE_STATE", raised.exception.code)
            self.assertFalse(output.exists())

    def test_public_render_rejects_inconsistent_report_contract(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exported = root / "public"
            sanitize_public_run(FIXTURE, exported)
            report_path = exported / "sanitization-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["records_exported"] += 1
            report_path.write_text(json.dumps(report), encoding="utf-8")
            output = root / "public-cockpit.html"
            with self.assertRaises(module.CockpitError) as raised:
                module.render_cockpit(exported, output, public=True)
            self.assertEqual(
                "ERR_PUBLIC_EXPORT_REQUIRED", raised.exception.code
            )
            self.assertFalse(output.exists())

    def test_public_render_rejects_boolean_finding_count(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exported = root / "public"
            sanitize_public_run(FIXTURE, exported)
            report_path = exported / "sanitization-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["finding_count"] = False
            report_path.write_text(json.dumps(report), encoding="utf-8")
            output = root / "public-cockpit.html"
            with self.assertRaises(module.CockpitError) as raised:
                module.render_cockpit(exported, output, public=True)
            self.assertEqual(
                "ERR_PUBLIC_EXPORT_REQUIRED", raised.exception.code
            )
            self.assertFalse(output.exists())

    def test_public_render_rejects_malformed_report_without_partial(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            exported = Path(tmp) / "public"
            sanitize_public_run(FIXTURE, exported)
            (exported / "sanitization-report.json").write_text(
                "[]\n", encoding="utf-8"
            )
            output = Path(tmp) / "public-cockpit.html"
            with self.assertRaises(ValueError):
                module.render_cockpit(exported, output, public=True)
            self.assertFalse(output.exists())

    def test_public_render_fails_closed_when_security_scan_errors(self):
        module = load_module()
        from sanitize_export import sanitize_public_run

        with tempfile.TemporaryDirectory() as tmp:
            exported = Path(tmp) / "public"
            sanitize_public_run(FIXTURE, exported)
            output = Path(tmp) / "public-cockpit.html"
            original_scan = module.scan_value
            module.scan_value = lambda _record: (_ for _ in ()).throw(
                RuntimeError("scanner unavailable")
            )
            try:
                with self.assertRaises(module.CockpitError) as raised:
                    module.render_cockpit(exported, output, public=True)
            finally:
                module.scan_value = original_scan
            self.assertEqual(raised.exception.code, "ERR_UNSAFE_STATE")
            self.assertFalse(output.exists())

    def test_cli_malformed_public_report_is_content_free(self):
        load_module()
        from sanitize_export import sanitize_public_run

        for malformed in ("[]\n", "{not-json\n"):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as tmp:
                exported = Path(tmp) / "public"
                sanitize_public_run(FIXTURE, exported)
                (exported / "sanitization-report.json").write_text(
                    malformed, encoding="utf-8"
                )
                output = Path(tmp) / "partial.html"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        str(exported),
                        "--public",
                        "--output",
                        str(output),
                    ],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr, "ERR_PUBLIC_EXPORT_REQUIRED\n"
                )
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(output.exists())

    def test_cli_invalid_state_has_content_free_error_and_no_partial(self):
        invalid = ROOT / "tests" / "fixtures" / "invalid-stale-approval"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "partial.html"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(invalid), "--output", str(output)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "ERR_INVALID_STATE\n")
            self.assertFalse(output.exists())

    def test_cli_usage_error_is_content_free(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "ERR_USAGE\n")

    def test_cli_default_output_is_inside_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "complete-run"
            shutil.copytree(FIXTURE, run_dir)
            output = run_dir / "research-cockpit.html"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(run_dir)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.stdout.strip(), str(output))
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
