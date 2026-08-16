import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "recommend_model.py"


class RecommendModelTests(unittest.TestCase):
    def run_script(self, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)] + list(args),
            capture_output=True,
            text=True,
        )
        return result

    def test_gate_4_enforces_frontier_floor(self):
        result = self.run_script(
            "--stage", "GATE_4_CLAIMS",
            "--novelty", "1",
            "--ambiguity", "1",
            "--scope", "1",
            "--risk", "1",
            "--reversibility", "1",
            "--safety", "1",
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("GATE_4_CLAIMS", payload["stage"])
        self.assertEqual(6, payload["score"])
        self.assertEqual("light", payload["scored_tier"])
        self.assertEqual("frontier", payload["floor"])
        self.assertEqual("frontier", payload["recommended_tier"])
        self.assertEqual("claude-opus-5", payload["recommended_model"])
        self.assertFalse(payload["downgrade_allowed"])
        self.assertTrue(payload["requires_human_approval"])

    def test_verifier_role_enforces_frontier_floor(self):
        result = self.run_script(
            "--stage", "BUILD",
            "--role", "verifier",
            "--novelty", "2",
            "--ambiguity", "2",
            "--scope", "2",
            "--risk", "2",
            "--reversibility", "2",
            "--safety", "2",
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("BUILD", payload["stage"])
        self.assertEqual("verifier", payload["role"])
        self.assertEqual("frontier", payload["floor"])
        self.assertEqual("frontier", payload["recommended_tier"])

    def test_light_tier_when_no_floor_and_low_complexity(self):
        result = self.run_script(
            "--stage", "RESOURCE_INTAKE",
            "--novelty", "1",
            "--ambiguity", "1",
            "--scope", "1",
            "--risk", "1",
            "--reversibility", "10",
            "--safety", "1",
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(15, payload["score"])
        self.assertEqual("light", payload["scored_tier"])
        self.assertIsNone(payload["floor"])
        self.assertEqual("light", payload["recommended_tier"])
        self.assertEqual("claude-haiku-4-5", payload["recommended_model"])
        self.assertTrue(payload["downgrade_allowed"])

    def test_balanced_tier_for_mid_complexity(self):
        result = self.run_script(
            "--stage", "BUILD",
            "--novelty", "5",
            "--ambiguity", "4",
            "--scope", "5",
            "--risk", "3",
            "--reversibility", "5",
            "--safety", "4",
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(26, payload["score"])
        self.assertEqual("balanced", payload["scored_tier"])
        self.assertEqual("balanced", payload["recommended_tier"])
        self.assertEqual("claude-sonnet-5", payload["recommended_model"])

    def test_frontier_tier_for_high_complexity(self):
        result = self.run_script(
            "--stage", "PILOT",
            "--novelty", "10",
            "--ambiguity", "8",
            "--scope", "7",
            "--risk", "9",
            "--reversibility", "2",
            "--safety", "8",
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(44, payload["score"])
        self.assertEqual("frontier", payload["scored_tier"])
        self.assertEqual("frontier", payload["recommended_tier"])

    def test_custom_tier_models_override_defaults(self):
        custom = json.dumps({"light": "gpt-4o-mini", "frontier": "o1"})
        result = self.run_script(
            "--stage", "GATE_4_CLAIMS",
            "--tier-models", custom,
        )
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("frontier", payload["recommended_tier"])
        self.assertEqual("o1", payload["recommended_model"])
        self.assertEqual("gpt-4o-mini", payload["tier_models"]["light"])

    def test_dimension_out_of_range_returns_error(self):
        result = self.run_script(
            "--stage", "BUILD",
            "--novelty", "11",
        )
        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stdout)
        self.assertIn("error", payload)
        self.assertIn("novelty", payload["error"])

    def test_unknown_stage_returns_error(self):
        result = self.run_script("--stage", "NONSENSE")
        self.assertNotEqual(0, result.returncode)

    def test_all_stages_can_run_without_error(self):
        stages = (
            "RESOURCE_INTAKE", "IDEA_SCOUT", "GATE_1_IDEA",
            "PREREGISTRATION", "GATE_2_PLAN_AND_BUDGET", "BUILD", "VERIFY",
            "PILOT", "GATE_3_FULL_RUN", "BOUNDED_EXECUTION",
            "ANALYZE_AND_AUDIT", "GATE_4_CLAIMS", "PACKAGE",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                result = self.run_script("--stage", stage)
                self.assertEqual(0, result.returncode, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(stage, payload["stage"])
                self.assertIn(payload["recommended_tier"],
                              ("light", "balanced", "frontier"))


if __name__ == "__main__":
    unittest.main()
