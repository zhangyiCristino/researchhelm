import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "skills" / "researchhelm" / "references"
REQUIRED = {
    "resource-triage.md": (
        "# Resource Triage",
        "## Intake Contract",
        "## Feasibility Envelope",
        "## Missing Inputs",
    ),
    "idea-diligence.md": (
        "# Idea Diligence",
        "## Query Ladder",
        "## Overlap Dimensions",
        "## Candidate Contract",
    ),
    "experiment-design.md": (
        "# Experiment Design",
        "## Preregistration",
        "## Pilot",
        "## Promotion and Kill Rules",
        "## Bounded Block",
    ),
    "implementation-audit.md": (
        "# Implementation Audit",
        "## Builder",
        "## Verifier",
        "## Integrity Checks",
        "## Anomalous Gains",
    ),
    "post-processing.md": (
        "# Post-processing",
        "## Freeze Raw Results",
        "## Analysis",
        "## Claim-Evidence Matrix",
    ),
    "legacy-optimize.md": (
        "# Legacy Optimize Protocol",
        "## Setup",
        "## Atomic Loop",
        "## Crash and Hash Integrity",
        "## Final Report",
    ),
    "skill-recommendations.md": (
        "# Governed Skill Recommendations",
        "## Triggers",
        "## Recommendation Card",
        "## Approval",
        "## Untrusted Sources",
    ),
    "privacy-security.md": (
        "# Credential, Privacy, and Publication Security",
        "## Global Precedence",
        "## Workspace Boundary",
        "## Opaque Credentials",
        "## Safe Commands and Recording",
        "## State Classification",
        "## Local Cockpit and Public Export",
        "## Recommended Skills",
        "## Incident Response",
        "## Honest Security Claims",
    ),
}


def read_reference(name):
    return (REFS / name).read_text(encoding="utf-8")


def assert_phrases(testcase, name, phrases):
    text = read_reference(name)
    for phrase in phrases:
        testcase.assertIn(phrase, text, f"{name}: missing {phrase}")


class ReferenceContractTests(unittest.TestCase):
    def test_required_references_are_focused_and_complete(self):
        for name, headings in REQUIRED.items():
            with self.subTest(name=name):
                text = read_reference(name)
                for heading in headings:
                    self.assertIn(heading, text, f"{name}: missing {heading}")
                self.assertLess(len(text.splitlines()), 400, name)

    def test_resource_triage_contract(self):
        assert_phrases(
            self,
            "resource-triage.md",
            (
                "domain or question", "existing code", "existing data",
                "accelerators and VRAM", "CPU, RAM, and storage", "wall time",
                "money", "APIs", "licenses", "expertise", "deadline and venue",
                "allowed scope", "forbidden scope", "risk tolerance",
                "low", "expected", "high", "assumptions", "tiered options",
                "block the full run",
            ),
        )
        missing_inputs = read_reference("resource-triage.md").split(
            "## Missing Inputs", 1
        )[1]
        self.assertIn(
            "Always block the full run while required inputs remain missing",
            missing_inputs,
        )
        self.assertIn("Always present tiered options", missing_inputs)
        self.assertNotIn("Otherwise, block the full run", missing_inputs)

    def test_idea_diligence_contract(self):
        assert_phrases(
            self,
            "idea-diligence.md",
            (
                "paper query ladder", "code query ladder", "dataset query ladder",
                "sources", "coverage", "failures", "conflicts", "cutoff",
                "question", "method", "data", "evaluation", "claimed contribution",
                "overlapping|incremental|differentiated|unknown",
                "falsifiable hypothesis", "mechanism", "nearest work",
                "differentiating claim", "minimum falsification experiment",
                "costs", "risks", "pivots", "Pareto set",
            ),
        )

    def test_experiment_and_audit_contracts(self):
        assert_phrases(
            self,
            "experiment-design.md",
            (
                "hypothesis", "causal logic", "baseline", "controls", "ablations",
                "primary and secondary metrics", "invariants", "splits",
                "seeds or repetitions", "uncertainty method", "minimum effect",
                "resource ceiling", "pilot", "promotion", "kill criteria",
                "editable files", "frozen evaluator", "artifacts", "bounded block",
                "question", "data", "risk profile", "experimental design",
                "anomalous gain", "non-reproducibility", "unstable statistics",
                "leakage", "environment drift", "more expensive stage",
            ),
        )
        assert_phrases(
            self,
            "implementation-audit.md",
            (
                "Builder input", "Builder output", "Verifier input", "Verifier output",
                "tests first", "isolated branch or worktree", "diff-to-hypothesis",
                "evaluator integrity", "data integrity", "shapes", "units", "splits",
                "seeds", "environment", "one causal factor per experiment",
                "leakage", "gaming", "cherry-picking", "clean smoke",
                "pilot reproduction", "hashes", "critical finding", "block",
            ),
        )
        audit = read_reference("implementation-audit.md")
        self.assertIn("experiment-ledger fields", audit)
        self.assertIn("artifact-manifest fields", audit)
        self.assertIn("approve|revise|reject|defer", audit)
        self.assertIn("Verifier cannot issue a human decision", audit)
        self.assertNotIn("pass, conditional pass, or block", audit)

    def test_post_processing_contract(self):
        assert_phrases(
            self,
            "post-processing.md",
            (
                "freeze the manifest", "derived from registered artifacts",
                "effect sizes", "uncertainty", "ablations", "sensitivity",
                "alternative explanations", "failures", "negative results",
                "supported|qualified|unsupported", "human-only publication",
            ),
        )
        analysis = read_reference("post-processing.md").split("## Analysis", 1)[1]
        self.assertIn("every table and figure", analysis)
        self.assertIn("generated from registered artifacts", analysis)
        self.assertIn(
            "record its inputs, transformation, version, and output hash",
            analysis,
        )

    def test_legacy_protocol_preserves_every_v1_rule(self):
        assert_phrases(
            self,
            "legacy-optimize.md",
            (
                "autoresearch/<tag>", "frozen evaluator", "ONE focused change",
                "commit BEFORE verification", "Exactly equal", "tie", "Crashed",
                "git commit --amend", "post-amend hash", "results.tsv", "dirty tree",
                "never stash", "deletion", "continuation", "resume", "NA",
                "Do not stop to ask", "evaluation data", "Final Report",
                "always redirect verification output", "default to 25 iterations",
                "two times a normal run", "branch must be new",
                "untracked and never committed", "iteration 1",
                "single deletion", "git reset --hard HEAD~1",
                "`keep`, `discard`, or `crash`", "re-run once",
                "pre-amend hash must never appear",
                "rewinding more than one commit", "Out of ideas",
                "Simplicity criterion", "Red flags", "main or master",
                "commit messages or ad-hoc notes", "Fitting the evaluation data",
                "suspicious complexity", "complexity left in the winner",
            ),
        )
        legacy = read_reference("legacy-optimize.md")
        self.assertIn("`commit\tmetric\tstatus\tdescription`", legacy)
        atomic_loop = legacy.split("## Atomic Loop", 1)[1].split(
            "### Simplicity criterion", 1
        )[0]
        self.assertLess(
            atomic_loop.index("commit BEFORE verification"),
            atomic_loop.index("Run the frozen evaluator"),
        )

    def test_recommendation_contract_is_human_gated(self):
        assert_phrases(
            self,
            "skill-recommendations.md",
            (
                "already installed", "private or team catalogs",
                "official or client-curated catalogs", "known public directories",
                "specific public repository", "at most three", "no-new-skill",
                "research stage", "capability gap", "reason for recommending now",
                "expected contribution", "alternatives", "installed status", "source",
                "author", "license", "immutable version or commit", "trust evidence",
                "required tools and permissions", "network or credential needs",
                "data exposure", "executable content", "known limitations", "confidence",
                "exact decision requested", "valid_skill", "frontmatter", "files",
                "tree_hash", "risks", "revision", "non-executing", "content hash",
                "stage input hash", "approve", "revise", "reject", "defer",
                "Do not install", "Do not invoke", "matching approval",
                "rejected candidate", "recommendation cycle", "private research",
                "subordinate", "permissions", "scope", "Do not claim",
                "never recommend researchhelm itself",
                "user asks for help finding a Skill",
                "failure is directly attributable",
                "future help after the idea decision",
                "approved metric, evaluator, scope, and budget",
            ),
        )
        recommendation = read_reference("skill-recommendations.md")
        self.assertIn("repository-relative", recommendation)
        self.assertIn("inside the approved project root", recommendation)


if __name__ == "__main__":
    unittest.main()
