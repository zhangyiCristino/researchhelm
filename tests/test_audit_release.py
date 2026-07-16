from __future__ import annotations

import importlib.util
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "audit_release.py"
POLICY = ROOT / ".security-allowlist.json"


def load_module(testcase: unittest.TestCase):
    testcase.assertTrue(SCRIPT.is_file(), "audit module is missing")
    spec = importlib.util.spec_from_file_location("audit_release", SCRIPT)
    testcase.assertIsNotNone(spec, "audit module cannot be loaded")
    testcase.assertIsNotNone(spec.loader, "audit module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError("temporary Git fixture failed")
    return result.stdout.strip()


def init_repo(root: Path, email: str = "example@users.noreply.github.com") -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Public Example")
    git(root, "config", "user.email", email)


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", message)


def synthetic_token() -> str:
    return "sk" + "-proj-" + ("B" * 48)


def png_bytes(*, text: bytes | None = None, trailing: bytes = b"") -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    scanline = zlib.compress(b"\x00\x00\x00\x00")
    chunks = [chunk(b"IHDR", header)]
    if text is not None:
        chunks.append(chunk(b"tEXt", text))
    chunks.extend((chunk(b"IDAT", scanline), chunk(b"IEND", b"")))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks) + trailing


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def privacy_finding(module, digest: str = "1" * 64):
    return module.AuditFinding(
        "privacy.email",
        "notes.txt",
        "line:1",
        digest,
        "block",
        "remove or approve the public email",
    )


def suppression(
    *,
    rule_id: str = "privacy.email",
    path: str = "notes.txt",
    digest: str = "1" * 64,
    expires: str = "2099-01-01",
):
    return {
        "rule_id": rule_id,
        "path": path,
        "line_digest": digest,
        "reason": "reviewed synthetic fixture",
        "expires": expires,
        "approval": "human-review-record",
    }


def policy_with(*entries: dict, approved: list[str] | None = None) -> dict:
    return {
        "schema_version": 1,
        "approved_public_emails": approved or [],
        "suppressions": list(entries),
    }


class AuditReleaseRedTests(unittest.TestCase):
    def test_policy_is_empty_by_default(self):
        self.assertTrue(POLICY.is_file(), "empty-by-default policy is missing")
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(1, policy.get("schema_version"))
        self.assertEqual([], policy.get("approved_public_emails"))
        self.assertEqual([], policy.get("suppressions"))

    def test_clean_repository_passes_all_scopes(self):
        module = load_module(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "README.md").write_text("public example\n", encoding="utf-8")
            commit_all(root, "clean")
            self.assertEqual([], module.audit_all(root).findings)

    def test_deleted_credential_blocks_history_without_echo_or_line_digest(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            header = "Authorization" + ": " + "Bearer "
            (root / "notes.txt").write_text(header + token, encoding="utf-8")
            commit_all(root, "unsafe")
            (root / "notes.txt").unlink()
            commit_all(root, "remove file")

            result = module.scan_history(root, "HEAD")
            protected = [
                item
                for item in result.findings
                if item.code == "credential.authorization_header"
            ]
            self.assertTrue(protected, "history credential finding is missing")
            self.assertTrue(
                all(item.line_digest is None for item in protected),
                "credential-derived line digest was retained",
            )
            serialized = json.dumps(result.to_dict(), sort_keys=True)
            self.assertFalse(
                token in serialized,
                "content-free result leaked protected material",
            )

    def test_private_author_email_is_blocked_without_echo(self):
        module = load_module(self)
        private_email = "private-person" + "@example.test"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root, private_email)
            (root / "README.md").write_text("public\n", encoding="utf-8")
            commit_all(root, "private author")

            result = module.scan_history(root, "HEAD")
            codes = {item.code for item in result.findings}
            self.assertIn("identity.unapproved_author_email", codes)
            serialized = json.dumps(result.to_dict(), sort_keys=True)
            self.assertFalse(
                private_email in serialized,
                "content-free result leaked an author identity",
            )

    def test_credential_filename_is_blocked_in_archive(self):
        module = load_module(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "auth.json").write_text("{}", encoding="utf-8")
            commit_all(root, "unsafe filename")

            result = module.verify_archive(root, "HEAD")
            self.assertIn(
                "credential.forbidden_filename",
                {item.code for item in result.findings},
            )

    def test_history_checks_every_filename_when_blob_content_is_reused(self):
        module = load_module(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "public.json").write_text("{}", encoding="utf-8")
            (root / "auth.json").write_text("{}", encoding="utf-8")
            commit_all(root, "shared blob")
            (root / "auth.json").unlink()
            commit_all(root, "remove unsafe alias")

            result = module.scan_history(root, "HEAD")
            protected = [
                item
                for item in result.findings
                if item.code == "credential.forbidden_filename"
            ]
            self.assertTrue(protected)
            self.assertTrue(
                any(
                    item.path == "auth.json"
                    and bool(re.fullmatch(r"[0-9a-f]{40,64}", item.location))
                    for item in protected
                )
            )

    def test_high_confidence_finding_cannot_be_allowlisted(self):
        module = load_module(self)
        finding = module.AuditFinding(
            "credential.private_key",
            "sample.txt",
            "line:1",
            None,
            "block",
            "remove and rotate or revoke",
        )
        policy = {
            "schema_version": 1,
            "approved_public_emails": [],
            "suppressions": [
                {
                    "rule_id": "credential.private_key",
                    "path": "sample.txt",
                    "line_digest": "0" * 64,
                    "reason": "synthetic negative control",
                    "expires": "2099-01-01",
                    "approval": "human",
                }
            ],
        }

        remaining = module.apply_policy(
            [finding], policy, module.date(2026, 7, 15)
        )
        self.assertIn(finding, remaining)

    def test_nonwaivable_match_prevents_every_digest_for_that_line(self):
        module = load_module(self)
        token = synthetic_token()
        private_email = "private-person" + "@example.test"
        line = "Authorization" + ": Bearer " + token + " " + private_email

        findings = module.scan_blob("notes.txt", line.encode("utf-8"), "worktree")
        codes = {item.code for item in findings}
        self.assertIn("credential.authorization_header", codes)
        self.assertIn("privacy.email", codes)
        self.assertTrue(
            all(item.line_digest is None for item in findings),
            "a protected line produced a retained digest",
        )
        serialized = json.dumps([item.__dict__ for item in findings], sort_keys=True)
        self.assertFalse(token in serialized, "content-free result leaked protected material")
        self.assertFalse(
            private_email in serialized,
            "content-free result leaked private identity material",
        )

    def test_privacy_only_line_has_exact_suppressible_digest(self):
        module = load_module(self)
        private_email = "private-person" + "@example.test"
        findings = module.scan_blob(
            "notes.txt", private_email.encode("utf-8"), "worktree"
        )
        privacy = [item for item in findings if item.code == "privacy.email"]
        self.assertEqual(1, len(privacy))
        self.assertRegex(privacy[0].line_digest or "", r"^[0-9a-f]{64}$")

    def test_valid_png_is_structurally_scanned_not_decoded_as_text(self):
        module = load_module(self)
        findings = module.scan_blob("docs/public.png", png_bytes(), "worktree")
        self.assertEqual([], findings)

    def test_png_text_metadata_and_trailing_bytes_are_blocked(self):
        module = load_module(self)
        metadata = module.scan_blob(
            "docs/public.png",
            png_bytes(text=b"Comment\x00/" + b"home/private"),
            "worktree",
        )
        trailing = module.scan_blob(
            "docs/public.png", png_bytes(trailing=b"private"), "worktree"
        )
        self.assertIn("binary.png_text_metadata", {item.code for item in metadata})
        self.assertIn("binary.invalid_png", {item.code for item in trailing})

    def test_strict_json_pointer_literal_is_not_an_absolute_path(self):
        module = load_module(self)
        payload = json.dumps(
            {"field_sensitivity": {"/" + "a~1b/0": "public"}}
        ).encode("utf-8")
        findings = module.scan_blob("schema.json", payload, "worktree")
        self.assertNotIn(
            "privacy.absolute_path", {item.code for item in findings}
        )

    def test_arbitrary_json_key_is_not_pointer_context(self):
        module = load_module(self)
        payload = json.dumps({"/" + "custom/private": "public"}).encode("utf-8")
        findings = module.scan_blob("schema.json", payload, "worktree")
        self.assertIn("privacy.absolute_path", {item.code for item in findings})

    def test_field_sensitivity_exemption_is_bound_to_exact_json_token(self):
        module = load_module(self)
        value = "/" + "custom/private"
        payload = json.dumps(
            {value: "ordinary key", "field_sensitivity": {value: "public"}}
        ).encode("utf-8")
        findings = module.scan_blob("schema.json", payload, "worktree")
        self.assertIn("privacy.absolute_path", {item.code for item in findings})

    def test_python_pointer_constants_are_structure_checked(self):
        module = load_module(self)
        safe_source = 'POINTERS = {"' + "/" + 'a~1b/0"}'
        safe_findings = module.scan_blob(
            "schema.py", safe_source.encode("utf-8"), "worktree"
        )
        self.assertNotIn(
            "privacy.absolute_path", {item.code for item in safe_findings}
        )

        filesystem_source = 'POINTERS = {"' + "/" + 'home/user"}'
        filesystem_findings = module.scan_blob(
            "schema.py", filesystem_source.encode("utf-8"), "worktree"
        )
        self.assertIn(
            "privacy.absolute_path", {item.code for item in filesystem_findings}
        )

        for source in (
            'POINTERS = {"' + "/" + 'custom/private"}',
            'POINTER_PATTERN = re.compile(r"' + "/" + 'custom/priv[ate]")',
        ):
            with self.subTest(source_type="custom"):
                findings = module.scan_blob(
                    "schema.py", source.encode("utf-8"), "worktree"
                )
                self.assertIn(
                    "privacy.absolute_path", {item.code for item in findings}
                )

    def test_json_pointer_filter_keeps_filesystem_paths_blocking(self):
        module = load_module(self)
        backslash = chr(92)
        filesystem_paths = (
            "/" + "home/user",
            "/" + "Users/name",
            "/" + "etc/service.conf",
            "C:" + backslash + "Users" + backslash + "name" + backslash + "file.txt",
            backslash * 2 + "server" + backslash + "share" + backslash + "file.txt",
        )
        for index, value in enumerate(filesystem_paths):
            with self.subTest(index=index):
                payload = json.dumps({"value": value}).encode("utf-8")
                findings = module.scan_blob("schema.json", payload, "worktree")
                self.assertIn(
                    "privacy.absolute_path", {item.code for item in findings}
                )

    def test_nonfilesystem_slash_syntax_is_not_an_absolute_path(self):
        module = load_module(self)
        slash = "/"
        samples = (
            'POINTER_PATTERNS = (re.compile(r"'
            + slash
            + 'candidates/(?:0|[1-9]\\d*)"),)',
            'normalized = value.replace("\\\\", "/")',
            "/plugin marketplace add public/example",
            "/plugin install example@public",
            "/researchhelm",
            "/autoresearch",
        )
        for index, value in enumerate(samples):
            with self.subTest(index=index):
                findings = module.scan_blob(
                    "schema.py", value.encode("utf-8"), "worktree"
                )
                self.assertNotIn(
                    "privacy.absolute_path", {item.code for item in findings}
                )

    def test_slash_command_arguments_are_still_scanned(self):
        module = load_module(self)
        samples = (
            "/plugin install " + "/" + "home/private",
            "/plugin marketplace add public/example " + "/" + "etc/private",
            "/researchhelm " + "/" + "home/private",
            "/autoresearch " + "/" + "home/private",
        )
        for index, value in enumerate(samples):
            with self.subTest(index=index):
                findings = module.scan_blob(
                    "commands.md", value.encode("utf-8"), "worktree"
                )
                self.assertIn(
                    "privacy.absolute_path", {item.code for item in findings}
                )

    def test_nonpointer_regex_cannot_hide_an_absolute_path(self):
        module = load_module(self)
        source = 'PATTERN = r"' + "/" + 'custom/u[ser]"'
        findings = module.scan_blob(
            "module.py", source.encode("utf-8"), "worktree"
        )
        self.assertIn("privacy.absolute_path", {item.code for item in findings})

    def test_syntax_masking_never_hides_credentials_or_private_identity(self):
        module = load_module(self)
        token = synthetic_token()
        private_email = "private-person" + "@example.test"
        samples = (
            'PATTERN = r"' + token + '[A-Z]"',
            '{"field_sensitivity": {"' + "/" + token + '": "public"}}',
            "/plugin install " + private_email,
        )
        expected = (
            "credential.openai_token",
            "credential.openai_token",
            "privacy.email",
        )
        for index, (value, code) in enumerate(zip(samples, expected)):
            with self.subTest(index=index):
                findings = module.scan_blob(
                    "public-source.txt", value.encode("utf-8"), "worktree"
                )
                self.assertIn(code, {item.code for item in findings})
                serialized = json.dumps(
                    [item.__dict__ for item in findings], sort_keys=True
                )
                self.assertNotIn(token, serialized)
                self.assertNotIn(private_email, serialized)

    def test_sensitive_filename_is_redacted_without_digest(self):
        module = load_module(self)
        token = synthetic_token()
        findings = module.scan_blob(token + ".txt", b"public", "worktree")
        serialized = json.dumps([item.__dict__ for item in findings], sort_keys=True)
        self.assertTrue(findings, "sensitive filename finding is missing")
        self.assertTrue(all(item.line_digest is None for item in findings))
        self.assertFalse(token in serialized, "content-free result leaked protected material")

    def test_exact_privacy_suppression_applies(self):
        module = load_module(self)
        finding = privacy_finding(module)
        remaining = module.apply_policy(
            [finding], policy_with(suppression()), module.date(2026, 7, 15)
        )
        self.assertEqual([], remaining)

    def test_expired_privacy_suppression_fails_closed(self):
        module = load_module(self)
        finding = privacy_finding(module)
        remaining = module.apply_policy(
            [finding],
            policy_with(suppression(expires="2026-07-14")),
            module.date(2026, 7, 15),
        )
        codes = {item.code for item in remaining}
        self.assertIn("privacy.email", codes)
        self.assertIn("policy.expired", codes)

    def test_drifted_privacy_suppression_fails_closed(self):
        module = load_module(self)
        finding = privacy_finding(module)
        remaining = module.apply_policy(
            [finding],
            policy_with(suppression(digest="2" * 64)),
            module.date(2026, 7, 15),
        )
        codes = {item.code for item in remaining}
        self.assertIn("privacy.email", codes)
        self.assertIn("policy.drift", codes)

    def test_invalid_policy_entry_fails_closed_without_echo(self):
        module = load_module(self)
        finding = privacy_finding(module)
        private_reason = "private-person" + "@example.test"
        entry = suppression(path="../notes.txt")
        entry["reason"] = private_reason
        remaining = module.apply_policy(
            [finding], policy_with(entry), module.date(2026, 7, 15)
        )
        codes = {item.code for item in remaining}
        self.assertIn("privacy.email", codes)
        self.assertIn("policy.invalid", codes)
        serialized = json.dumps([item.__dict__ for item in remaining], sort_keys=True)
        self.assertFalse(
            private_reason in serialized,
            "content-free result leaked invalid policy content",
        )

    def test_policy_schema_and_approved_emails_fail_closed(self):
        module = load_module(self)
        cases = (
            {"schema_version": 1, "approved_public_emails": []},
            {
                "schema_version": 1,
                "approved_public_emails": [],
                "suppressions": [],
                "extra": True,
            },
            policy_with(approved=[""]),
            policy_with(approved=[123]),
            policy_with(approved=["not-an-email"]),
        )
        for index, policy in enumerate(cases):
            with self.subTest(index=index):
                remaining = module.apply_policy(
                    [], policy, module.date(2026, 7, 15)
                )
                self.assertIn("policy.invalid", {item.code for item in remaining})

    def test_approved_email_does_not_mask_a_longer_unapproved_email(self):
        module = load_module(self)
        approved = "contact" + "@example.test"
        private_email = "private-" + approved
        findings = module.scan_blob(
            "notes.txt",
            private_email.encode("utf-8"),
            "worktree",
            approved_public_emails=[approved],
        )
        self.assertIn("privacy.email", {item.code for item in findings})
        serialized = json.dumps([item.__dict__ for item in findings], sort_keys=True)
        self.assertNotIn(private_email, serialized)

    def test_approved_email_is_case_exact_for_content_and_author(self):
        module = load_module(self)
        approved = "Public-Contact" + "@example.test"
        unapproved = "public-contact" + "@example.test"
        content = module.scan_blob(
            "notes.txt",
            unapproved.encode("utf-8"),
            "worktree",
            approved_public_emails=[approved],
        )
        self.assertIn("privacy.email", {item.code for item in content})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root, unapproved)
            (root / "README.md").write_text("public\n", encoding="utf-8")
            commit_all(root, "case-exact author")
            history = module.scan_history(
                root, "HEAD", policy=policy_with(approved=[approved])
            )
            self.assertIn(
                "identity.unapproved_author_email",
                {item.code for item in history.findings},
            )

    def test_staged_content_is_scanned_even_when_worktree_is_clean(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            target = root / "notes.txt"
            target.write_text("Authorization" + ": Bearer " + token, encoding="utf-8")
            git(root, "add", "notes.txt")
            target.write_text("public\n", encoding="utf-8")

            result = module.scan_worktree(root)
            protected = [
                item
                for item in result.findings
                if item.code == "credential.authorization_header"
            ]
            self.assertTrue(protected, "staged credential finding is missing")
            self.assertTrue(all(item.line_digest is None for item in protected))

    def test_stage_zero_blob_is_read_by_oid_not_colon_path_expression(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oid = "a" * 40
            path = "0" + ":" + "notes.txt"
            secret = ("Authorization" + ": Bearer " + token).encode("utf-8")

            def staged_git(_root, *args, **_kwargs):
                if args == ("ls-files", "-z"):
                    return b""
                if args[:3] == ("diff", "--cached", "--name-only"):
                    return path.encode("utf-8") + b"\0"
                if args == ("ls-files", "--unmerged", "-z"):
                    return b""
                if args == ("ls-files", "--stage", "-z"):
                    return f"100644 {oid} 0\t{path}\0".encode("utf-8")
                if args == ("cat-file", "blob", oid):
                    return secret
                if args == ("show", f":{path}"):
                    return b"public"
                raise AssertionError("unexpected Git call")

            with mock.patch.object(module, "run_git", side_effect=staged_git):
                result = module.scan_worktree(root)
            self.assertIn(
                "credential.authorization_header",
                {item.code for item in result.findings},
            )
            self.assertNotIn(token, json.dumps(result.to_dict(), sort_keys=True))

    def test_worktree_open_preserves_literal_backslash_git_path(self):
        module = load_module(self)
        literal = "folder" + chr(92) + "notes.txt"
        root = mock.Mock()
        candidate = mock.Mock()
        root.joinpath.return_value = candidate
        root.resolve.return_value = Path("repository-root").resolve()
        candidate.resolve.return_value = root.resolve.return_value / "notes.txt"
        candidate.is_symlink.return_value = False
        candidate.is_file.return_value = True

        self.assertIs(candidate, module._safe_worktree_file(root, literal))
        root.joinpath.assert_called_once_with(literal)

    def test_unmerged_index_is_a_content_free_release_block(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            target = root / "notes.txt"
            target.write_text("base\n", encoding="utf-8")
            commit_all(root, "base")
            original_branch = git(root, "branch", "--show-current")
            git(root, "checkout", "-q", "-b", "other")
            target.write_text(
                "Authorization" + ": Bearer " + token, encoding="utf-8"
            )
            commit_all(root, "other")
            git(root, "checkout", "-q", original_branch)
            target.write_text("main\n", encoding="utf-8")
            commit_all(root, "main")
            merge = subprocess.run(
                ["git", "merge", "other"],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            self.assertNotEqual(0, merge.returncode)
            target.write_text("public working copy\n", encoding="utf-8")

            result = module.scan_worktree(root)
            codes = {item.code for item in result.findings}
            self.assertIn("git.unmerged_index", codes)
            self.assertIn("credential.authorization_header", codes)
            serialized = json.dumps(result.to_dict(), sort_keys=True)
            self.assertNotIn(token, serialized)

    def test_tracked_worktree_content_is_scanned(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            target = root / "notes.txt"
            target.write_text("public\n", encoding="utf-8")
            commit_all(root, "clean")
            target.write_text("Authorization" + ": Bearer " + token, encoding="utf-8")

            result = module.scan_worktree(root)
            self.assertIn(
                "credential.authorization_header",
                {item.code for item in result.findings},
            )

    def test_approved_public_email_masks_content_and_author_identity(self):
        module = load_module(self)
        approved = "public-contact" + "@example.test"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root, approved)
            (root / "README.md").write_text(approved + "\n", encoding="utf-8")
            commit_all(root, "approved public identity")
            policy = policy_with(approved=[approved])

            history = module.scan_history(root, "HEAD", policy=policy)
            worktree = module.scan_worktree(root, policy=policy)
            self.assertNotIn(
                "identity.unapproved_author_email",
                {item.code for item in history.findings},
            )
            self.assertNotIn(
                "privacy.email", {item.code for item in worktree.findings}
            )

    def test_empty_git_author_email_is_blocked(self):
        module = load_module(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "README.md").write_text("public\n", encoding="utf-8")
            commit_all(root, "base")
            commit = git(root, "rev-parse", "HEAD")
            original_run_git = module.run_git

            def run_git_with_empty_author(repo, *args, **kwargs):
                if args and args[0] == "log":
                    return commit + "\0\0"
                return original_run_git(repo, *args, **kwargs)

            with mock.patch.object(
                module, "run_git", side_effect=run_git_with_empty_author
            ):
                result = module.scan_history(root, "HEAD")
            self.assertIn(
                "identity.unapproved_author_email",
                {item.code for item in result.findings},
            )

    def test_reused_sensitive_blob_is_reported_for_every_historical_path(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            payload = "Authorization" + ": Bearer " + token
            (root / "first.txt").write_text(payload, encoding="utf-8")
            (root / "second.txt").write_text(payload, encoding="utf-8")
            commit_all(root, "shared sensitive blob")

            result = module.scan_history(root, "HEAD")
            paths = {
                item.path
                for item in result.findings
                if item.code == "credential.authorization_header"
            }
            self.assertEqual({"first.txt", "second.txt"}, paths)
            self.assertNotIn(token, json.dumps(result.to_dict(), sort_keys=True))

    def test_newline_historical_path_scans_blob_and_redacts_path(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            path = "line" + chr(10) + "break.txt"
            blob = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=root,
                input=("Authorization" + ": Bearer " + token).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            ).stdout.decode("ascii").strip()
            tree_entry = f"100644 blob {blob}\t{path}\0".encode("utf-8")
            tree = subprocess.run(
                ["git", "mktree", "-z"],
                cwd=root,
                input=tree_entry,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            ).stdout.decode("ascii").strip()
            commit = git(root, "commit-tree", tree, "-m", "newline path")
            git(root, "update-ref", "HEAD", commit)

            result = module.scan_history(root, "HEAD")
            protected = [
                item
                for item in result.findings
                if item.code == "credential.authorization_header"
            ]
            self.assertTrue(protected)
            self.assertTrue(
                all(item.path == "<redacted-path>" for item in protected)
            )
            self.assertTrue(
                all(item.location.startswith("object:") for item in protected)
            )
            self.assertNotIn(token, json.dumps(result.to_dict(), sort_keys=True))

    def test_archive_traversal_is_rejected_before_extraction(self):
        module = load_module(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "candidate.zip"
            extraction = root / "extract"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape.txt", "public")

            result = module.scan_archive_file(archive, extraction)
            self.assertIn(
                "archive.unsafe_member", {item.code for item in result.findings}
            )
            self.assertFalse((root / "escape.txt").exists())

    def test_audit_all_deduplicates_findings(self):
        module = load_module(self)
        token = synthetic_token()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "notes.txt").write_text(
                "Authorization" + ": Bearer " + token, encoding="utf-8"
            )
            commit_all(root, "unsafe")

            result = module.audit_all(root)
            identities = [
                (item.code, item.path, item.location, item.line_digest)
                for item in result.findings
            ]
            self.assertEqual(len(identities), len(set(identities)))

    def test_cli_exit_codes_are_zero_one_and_two_with_content_free_json(self):
        self.assertTrue(SCRIPT.is_file(), "audit module is missing")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "README.md").write_text("public\n", encoding="utf-8")
            commit_all(root, "clean")

            clean = run_cli("worktree", "--root", str(root))
            self.assertEqual(0, clean.returncode, "clean CLI did not exit zero")
            clean_payload = json.loads(clean.stdout)
            self.assertTrue(clean_payload["clean"])

            (root / "auth.json").write_text("{}", encoding="utf-8")
            git(root, "add", "auth.json")
            blocked = run_cli("worktree", "--root", str(root))
            self.assertEqual(1, blocked.returncode, "finding CLI did not exit one")
            blocked_payload = json.loads(blocked.stdout)
            self.assertFalse(blocked_payload["clean"])

        usage = run_cli()
        self.assertEqual(2, usage.returncode, "usage CLI did not exit two")
        usage_payload = json.loads(usage.stdout)
        self.assertEqual(
            ["audit.invalid_usage"],
            [item["code"] for item in usage_payload["findings"]],
        )

        help_result = run_cli("--help")
        self.assertEqual(2, help_result.returncode)
        self.assertEqual(
            ["audit.invalid_usage"],
            [item["code"] for item in json.loads(help_result.stdout)["findings"]],
        )

    def test_cli_rejects_policy_outside_repository_without_reading_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "repo"
            root.mkdir()
            init_repo(root)
            (root / "README.md").write_text("public\n", encoding="utf-8")
            commit_all(root, "clean")
            private_email = "private-person" + "@example.test"
            external = parent / "outside.json"
            external.write_text(private_email, encoding="utf-8")

            result = run_cli(
                "worktree", "--root", str(root), "--policy", str(external)
            )
            self.assertEqual(2, result.returncode)
            payload = json.loads(result.stdout)
            self.assertEqual(
                ["audit.invalid_usage"],
                [item["code"] for item in payload["findings"]],
            )
            self.assertNotIn(private_email, result.stdout)

    def test_option_like_ref_cannot_bypass_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "README.md").write_text("public\n", encoding="utf-8")
            commit_all(root, "clean")

            result = run_cli("history", "--root", str(root), "--ref=--all")
            self.assertNotEqual(0, result.returncode)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["clean"])

    def test_cli_internal_error_is_content_free(self):
        self.assertTrue(SCRIPT.is_file(), "audit module is missing")
        marker = "missing-ref-marker"
        result = run_cli("history", "--root", str(ROOT), "--ref", marker)
        self.assertEqual(1, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(
            ["audit.internal_error"],
            [item["code"] for item in payload["findings"]],
        )
        self.assertFalse(marker in result.stdout, "internal error echoed input")

    def test_skill_links_maintainer_audit_and_security_policy_is_complete(self):
        skill = (ROOT / "skills" / "researchhelm" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn(
            "[Audit a release without echoing matches](scripts/audit_release.py)",
            skill,
        )
        self.assertIn("ordinary research", skill)
        headings = [
            line
            for line in security.splitlines()
            if line.startswith("# Security Policy") or line.startswith("## ")
        ]
        self.assertEqual(
            [
                "# Security Policy",
                "## Supported Version",
                "## Credential and Privacy Boundary",
                "## Reporting a Vulnerability",
                "## Incident Response",
                "## Security Claims",
            ],
            headings,
        )
        for phrase in (
            "GitHub Private Vulnerability Reporting",
            "public issues",
            "rotate the credential or revoke the session",
            "separate explicit authorization",
            "absolute security",
        ):
            self.assertIn(phrase, security)


if __name__ == "__main__":
    unittest.main()
