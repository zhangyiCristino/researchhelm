import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import credential_scan  # noqa: E402


class CredentialScanTests(unittest.TestCase):
    def test_clean_directory_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "notes.md").write_text("hello", encoding="utf-8")
            findings = credential_scan.scan_tree(path)
            self.assertEqual([], findings)

    def test_flags_env_file_without_echoing_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            secret = path / ".env"
            # Split literal so audit_release.py generic_assignment does not flag
            # this test source file itself; the credential_scan detector still
            # flags the .env file correctly when it's written.
            secret.write_text("API_" + "KEY=super-secret-value-do-not-leak", encoding="utf-8")
            findings = credential_scan.scan_tree(path)
            self.assertTrue(findings)
            blob = json.dumps([f.__dict__ for f in findings])
            self.assertNotIn("super-secret-value-do-not-leak", blob)
            self.assertTrue(any(f.code.startswith("credential_file.") for f in findings))

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "ok.txt").write_text("x", encoding="utf-8")
            self.assertEqual(0, credential_scan.main([str(path)]))
            (path / "id_rsa").write_text("not-a-real-key", encoding="utf-8")
            self.assertEqual(1, credential_scan.main([str(path)]))


if __name__ == "__main__":
    unittest.main()
