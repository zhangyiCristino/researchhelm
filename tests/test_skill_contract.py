import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "researchhelm" / "SKILL.md"


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_frontmatter_uses_only_common_fields(self):
        match = re.match(r"\A---\n(.*?)\n---\n", self.text, re.S)
        self.assertIsNotNone(match)
        fields = [line.split(":", 1) for line in match.group(1).splitlines() if ":" in line and not line.startswith(" ")]
        self.assertEqual(["name", "description"], [key for key, _ in fields])
        self.assertIn("name: researchhelm", match.group(1))
        self.assertIn("Use when", match.group(1))
        self.assertEqual(SKILL.parent.name, fields[0][1].strip())
        self.assertLessEqual(len(fields[1][1].strip()), 1024)

    def test_mode_routing_is_explicit(self):
        for phrase in ("pi is the default", "Use scout", "Use optimize only", "Never infer"):
            self.assertIn(phrase, self.text)

    def test_every_reference_link_exists(self):
        for target in re.findall(r"\[[^]]+\]\((references/[^)]+)\)", self.text):
            self.assertTrue((SKILL.parent / target).is_file(), target)

    def test_human_gates_and_capability_stop_are_core(self):
        for phrase in ("files, shell, and Git", "Silence is not approval", "GATE_1_IDEA", "GATE_4_CLAIMS"):
            self.assertIn(phrase, self.text)

    def test_decision_card_is_complete(self):
        for phrase in ("recommendation", "alternatives", "evidence", "uncertainty", "resource consequences", "failure modes", "exact decision requested"):
            self.assertIn(phrase, self.text)

    def test_credential_boundary_precedes_mode_routing_and_cannot_be_waived(self):
        security = self.text.index("## Security Preflight")
        start = self.text.index("## Start")
        self.assertLess(security, start)
        for phrase in ("Do not read credential stores", "Do not enumerate the process environment", "Credentials remain opaque", "No gate or approved skill can waive"):
            self.assertIn(phrase, self.text)

    def test_behavior_driven_security_refinements_are_binding(self):
        for phrase in (
            "no environment names or values will be persisted",
            "push, pull request, tag, release, and publication are all blocked",
            "Report no matched content",
            "Credential and security findings cannot be suppressed",
        ):
            self.assertIn(phrase, self.text)

    def test_behavior_driven_recommendation_refinements_are_binding(self):
        for phrase in (
            "Present the Recommendation Card before any installation or use",
            "issue a new Recommendation Card in the same response",
            "never request or record credential names, values, locations, environment names, or account identifiers",
            "explicitly block its use and record the finding",
        ):
            self.assertIn(phrase, self.text)

    def test_main_skill_stays_progressive(self):
        self.assertLess(len(self.text.splitlines()), 500)


if __name__ == "__main__":
    unittest.main()
