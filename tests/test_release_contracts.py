import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"


def read_workflow(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"required workflow is missing: {path.name}")
    return path.read_text(encoding="utf-8")


def workflow_boundary_findings(text: str) -> list[str]:
    findings = []
    lines = text.splitlines()

    permission_lines = [
        (index, len(line) - len(line.lstrip(" ")), line.strip())
        for index, line in enumerate(lines)
        if line.strip().startswith("permissions:")
    ]
    top_level = [item for item in permission_lines if item[1] == 0]
    if len(top_level) != 1:
        findings.append("permissions.top_level_count")
    if any(indent > 0 for _, indent, _ in permission_lines):
        findings.append("permissions.job_override")
    if re.search(r"(?mi)^\s*(?:permissions:\s*)?write-all\s*(?:#.*)?$", text):
        findings.append("permissions.write_all")
    if re.search(r"(?mi):\s*write\s*(?:#.*)?$", text):
        findings.append("permissions.write")
    if len(top_level) == 1:
        index, _, declaration = top_level[0]
        block = []
        for line in lines[index + 1 :]:
            if line.strip() and len(line) - len(line.lstrip(" ")) == 0:
                break
            if line.strip():
                block.append((len(line) - len(line.lstrip(" ")), line.strip()))
        if declaration != "permissions:" or block != [(2, "contents: read")]:
            findings.append("permissions.not_read_only")

    if re.search(
        r"(?i)(?<![A-Za-z0-9_])(?:github\.token|gh_token|github_token)"
        r"(?![A-Za-z0-9_])",
        text,
    ):
        findings.append("credential.token_injection")

    approved_actions = {
        "actions/checkout@v7",
        "actions/setup-python@v6",
        "actions/setup-node@v7",
    }
    canonical_uses_pattern = re.compile(
        r"^\s*-\s+uses:\s+(?P<action>[^\s#]+)\s*(?:#.*)?$"
    )
    block_uses_key = re.compile(
        r'''^\s*(?:-\s*)?(?:uses|"uses"|'uses')\s*:'''
    )
    flow_uses_key = re.compile(
        r'''(?:\{|,)\s*(?:uses|"uses"|'uses')\s*:'''
    )
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        has_uses_key = block_uses_key.search(line) or flow_uses_key.search(line)
        if not has_uses_key:
            continue
        match = canonical_uses_pattern.match(line)
        if match is None:
            findings.append("action.noncanonical_uses")
        elif match.group("action") not in approved_actions:
            findings.append("action.unapproved_ref")

    checkout_pattern = re.compile(
        r"^(?P<indent>\s*)-\s+uses:\s+actions/checkout@[^\s#]+\s*(?:#.*)?$"
    )
    for index, line in enumerate(lines):
        match = checkout_pattern.match(line)
        if match is None:
            continue
        step_indent = len(match.group("indent"))
        block = []
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if not stripped:
                continue
            indent = len(candidate) - len(candidate.lstrip(" "))
            if indent < step_indent or (
                indent == step_indent and stripped.startswith("-")
            ):
                break
            block.append((indent, stripped))
        with_positions = [
            position
            for position, item in enumerate(block)
            if item == (step_indent + 2, "with:")
        ]
        persistence = [
            (position, indent, value.strip())
            for position, indent, value in (
                (position, indent, stripped.split(":", 1)[1])
                for position, (indent, stripped) in enumerate(block)
                if stripped.startswith("persist-credentials:")
            )
        ]
        persistence_is_bound = False
        if len(with_positions) == 1 and len(persistence) == 1:
            with_position = with_positions[0]
            with_end = next(
                (
                    position
                    for position, (indent, _) in enumerate(
                        block[with_position + 1 :], start=with_position + 1
                    )
                    if indent <= step_indent + 2
                ),
                len(block),
            )
            position, indent, value = persistence[0]
            persistence_is_bound = (
                with_position < position < with_end
                and indent == step_indent + 4
                and value == "false"
            )
        if not persistence_is_bound:
            findings.append("checkout.persist_credentials")

    if "gitleaks" in text.lower():
        scan_lines = [
            line
            for line in lines
            if not line.lstrip().startswith("#")
            and re.search(r"(?i)gitleaks[\"']?\s+git\b", line)
        ]
        if len(scan_lines) != 1:
            findings.append("gitleaks.command_count")
        elif ">/dev/null 2>&1" not in scan_lines[0]:
            findings.append("gitleaks.raw_output")
    return findings


class ReleaseContractTests(unittest.TestCase):
    def test_contract_validator_rejects_workflow_boundary_bypasses(self):
        validator = globals().get("workflow_boundary_findings")
        self.assertIsNotNone(
            validator, "workflow boundary validator is not implemented"
        )
        ci = read_workflow(CI_WORKFLOW)
        security = read_workflow(SECURITY_WORKFLOW)
        scan = (
            'if "$RUNNER_TEMP/gitleaks" git --redact=100 --no-banner '
            "--no-color --log-level=error --max-archive-depth=2 . "
            ">/dev/null 2>&1; then"
        )
        mutations = {
            "checkout_true": ci.replace(
                "persist-credentials: false",
                "persist-credentials: true",
                1,
            ),
            "checkout_unpaired": ci.replace(
                "          persist-credentials: false\n", "", 1
            ),
            "checkout_nonmajor_true": ci.replace(
                "    steps:\n",
                "    steps:\n      - uses: actions/checkout@main\n"
                "        with:\n          persist-credentials: true\n",
                1,
            ),
            "checkout_floating_ref": ci.replace(
                "uses: actions/checkout@v7",
                "uses: actions/checkout@main",
                1,
            ),
            "setup_python_floating_ref": ci.replace(
                "uses: actions/setup-python@v6",
                "uses: actions/setup-python@main",
                1,
            ),
            "setup_node_floating_ref": ci.replace(
                "uses: actions/setup-node@v7",
                "uses: actions/setup-node@main",
                1,
            ),
            "unapproved_action": ci.replace(
                "    steps:\n",
                "    steps:\n      - uses: example/unreviewed-action@v1\n",
                1,
            ),
            "named_unapproved_action": ci.replace(
                "    steps:\n",
                "    steps:\n      - name: Unreviewed action\n"
                "        uses: example/unreviewed-action@main\n",
                1,
            ),
            "named_checkout_floating_ref": ci.replace(
                "      - uses: actions/checkout@v7",
                "      - name: Checkout\n        uses: actions/checkout@main",
                1,
            ),
            "reusable_job": ci.replace(
                "jobs:\n",
                "jobs:\n  unreviewed:\n"
                "    uses: example/unreviewed/.github/workflows/ci.yml@main\n",
                1,
            ),
            "spaced_uses_key": ci.replace(
                "- uses: actions/checkout@v7",
                "- uses : actions/checkout@main",
                1,
            ),
            "quoted_uses_value": ci.replace(
                "- uses: actions/checkout@v7",
                '- uses: "actions/checkout@v7"',
                1,
            ),
            "flow_mapping_action": ci.replace(
                "- uses: actions/checkout@v7",
                "- {uses: example/unreviewed-action@main}",
                1,
            ),
            "checkout_false_outside_with": ci.replace(
                "        with:\n          persist-credentials: false",
                "        env:\n          persist-credentials: false\n"
                "        with:",
                1,
            ),
            "job_permissions": ci.replace(
                "jobs:\n",
                "jobs:\n  unsafe:\n    permissions:\n      contents: read\n"
                "    runs-on: ubuntu-latest\n    steps: []\n",
                1,
            ),
            "duplicate_permissions": ci + "\npermissions:\n  contents: read\n",
            "write_all": ci.replace(
                "permissions:\n  contents: read", "permissions: write-all", 1
            ),
            "write_permission": ci.replace(
                "contents: read", "contents: write", 1
            ),
            "token_injection": ci.replace(
                'RUN_INSTALLER_TESTS: "0"',
                'RUN_INSTALLER_TESTS: "0"\n      GH_TOKEN: ${{ github.token }}',
                1,
            ),
            "gitleaks_comment_decoy": security.replace(
                scan,
                scan.replace(" >/dev/null 2>&1", ""),
                1,
            )
            + f"\n# {scan}\n",
            "gitleaks_duplicate": security.replace(
                "      - name: Scan reachable Git history with full redaction\n",
                "      - name: Unsafe duplicate scan\n"
                '        run: \'"$RUNNER_TEMP/gitleaks" git .\'\n'
                "      - name: Scan reachable Git history with full redaction\n",
                1,
            ),
        }
        for name, text in mutations.items():
            with self.subTest(name=name):
                self.assertTrue(validator(text), name)

    def test_generated_fixture_cockpit_is_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "tests/fixtures/complete-run/cockpit.html"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual("", result.stdout.strip())

    def test_generated_state_ignore_rules_are_exact(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for pattern in (
            ".researchhelm/",
            ".autoresearch/",
            "*.pyc",
            "tests/fixtures/complete-run/cockpit.html",
            "gitleaks-report.*",
        ):
            self.assertEqual(1, lines.count(pattern), pattern)

    def test_live_compatibility_evidence_paths_exist(self):
        result = subprocess.run(
            [
                sys.executable,
                "skills/researchhelm/scripts/validate_compatibility.py",
                "validate",
                "evals/compatibility/clients.json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_readme_compatibility_blocks_are_current(self):
        result = subprocess.run(
            [
                sys.executable,
                "skills/researchhelm/scripts/validate_compatibility.py",
                "sync-readme",
                "--check",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ci_has_cross_platform_unit_and_standards_gates(self):
        text = read_workflow(CI_WORKFLOW)
        for phrase in (
            "pull_request:",
            'branches: [master, "codex/**"]',
            "contents: read",
            "os: [ubuntu-latest, windows-latest]",
            'python-version: ["3.9", "3.11", "3.13"]',
            "RUN_INSTALLER_TESTS: \"0\"",
            "python -m unittest discover -s tests -v",
            "gh skill publish --dry-run",
            "python -m unittest tests.test_repository_contracts tests.test_skill_contract tests.test_release_contracts -v",
            "python skills/researchhelm/scripts/validate_state.py tests/fixtures/complete-run",
            "python skills/researchhelm/scripts/validate_compatibility.py validate evals/compatibility/clients.json",
            "python skills/researchhelm/scripts/validate_compatibility.py sync-readme --check",
            "https://github.com/cli/cli/releases/download/v2.96.0/gh_2.96.0_linux_amd64.tar.gz",
            "if: steps.gh-version.outputs.needs-upgrade == 'true'",
        ):
            self.assertIn(phrase, text)
        self.assertIn("actions/checkout@v7", text)
        self.assertIn("actions/setup-python@v6", text)

    def test_ci_installer_gate_is_isolated_and_pinned(self):
        text = read_workflow(CI_WORKFLOW)
        for phrase in (
            "workflow_dispatch:",
            "installer:",
            "runs-on: ubuntu-latest",
            "if: github.ref == 'refs/heads/master' && (github.event_name == 'workflow_dispatch' || github.event_name == 'push')",
            "actions/setup-node@v7",
            "node-version: \"24\"",
            "RUN_INSTALLER_TESTS: \"1\"",
            "skills@1.5.16",
            "python -m unittest tests.test_installer_paths -v",
            "HOME: ${{ runner.temp }}/installer-home",
            "npm_config_cache: ${{ runner.temp }}/npm-cache",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("cache: npm", text)

    def test_installer_gate_cannot_promote_pre_merge_evidence(self):
        registry = json.loads(
            (ROOT / "evals" / "compatibility" / "clients.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn(
            "Install-path verified",
            {claim["label"] for claim in registry["claims"]},
        )
        testing = (ROOT / "TESTING.md").read_text(encoding="utf-8")
        self.assertIn("post-merge install-path gate", testing)
        self.assertIn("manual dispatch from `master` only", testing)
        self.assertIn("pre-merge network matrix remains unverified", testing)

    def test_security_workflow_is_full_history_read_only_and_pinned(self):
        text = read_workflow(SECURITY_WORKFLOW)
        for phrase in (
            "workflow_dispatch:",
            'branches: [master, "codex/**"]',
            "permissions:\n  contents: read",
            "actions/checkout@v7",
            "fetch-depth: 0",
            "persist-credentials: false",
            "python skills/researchhelm/scripts/audit_release.py all --root . --ref HEAD",
            "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz",
            "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
            '"$RUNNER_TEMP/gitleaks" git --redact=100 --no-banner --no-color --log-level=error --max-archive-depth=2 .',
        ):
            self.assertIn(phrase, text)

    def test_gitleaks_output_is_suppressed_and_exit_status_is_preserved(self):
        text = read_workflow(SECURITY_WORKFLOW)
        for phrase in (
            'if "$RUNNER_TEMP/gitleaks" git --redact=100 --no-banner --no-color --log-level=error --max-archive-depth=2 . >/dev/null 2>&1; then',
            "scanner_status=$?",
            'echo "Gitleaks blocked release or failed." >&2',
            'exit "$scanner_status"',
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("| tee", text)
        testing = (ROOT / "TESTING.md").read_text(encoding="utf-8")
        self.assertIn("raw scanner output is suppressed", testing)

    def test_workflows_have_no_write_secret_report_or_dump_path(self):
        workflows = {
            "ci": read_workflow(CI_WORKFLOW),
            "security": read_workflow(SECURITY_WORKFLOW),
        }
        combined = "\n".join(workflows.values())
        for forbidden in (
            "contents: write",
            "pull-requests: write",
            "id-token: write",
            "packages: write",
            "secrets.",
            "upload-artifact",
            "upload-sarif",
            "gitleaks-action",
            "continue-on-error",
            "gitleaks:allow",
            "--baseline-path",
            "--report-path",
            "GITHUB_STEP_SUMMARY",
            "pull_request_target:",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIsNone(
            re.search(r"(?m)^\s*(?:run:\s*)?(?:env|printenv|set)(?:\s|$)", combined)
        )
        for name, text in workflows.items():
            with self.subTest(workflow=name):
                self.assertEqual([], workflow_boundary_findings(text))

    def test_security_policy_is_empty_by_default(self):
        policy = json.loads(
            (ROOT / ".security-allowlist.json").read_text(encoding="utf-8")
        )
        self.assertEqual([], policy["suppressions"])

    def test_testing_matrix_keeps_publication_block_and_stop_rule(self):
        text = (ROOT / "TESTING.md").read_text(encoding="utf-8")
        for phrase in (
            "## Maintainer release verification matrix",
            "147 content-free findings",
            "no release tag or compatibility claim",
            "missing, stale, or red",
            "Deterministic unit tests",
            "Fresh-context behavior evaluation",
            "Real GPU dogfooding",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
