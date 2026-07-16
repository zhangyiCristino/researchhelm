import importlib.util
import hashlib
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Optional
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "sanitize_export.py"
VALID = ROOT / "tests" / "fixtures" / "minimal-valid-run"


def load_module():
    spec = importlib.util.spec_from_file_location("sanitize_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_token() -> str:
    return "sk" + "-proj-" + ("A" * 48)


def public_artifact_payload(name: str) -> bytes:
    if name == "experiment.py":
        return b'print("demo")\n'
    if name == "experiment-config.json":
        value = {
            "schema_version": "1.0",
            "record_type": "experiment-config",
            "run_id": "synthetic-public-run",
            "contract_hash": "a" * 64,
            "dataset": {},
            "split": {},
            "features": {},
            "training": {},
            "pilot": {},
            "future_full": {},
            "metrics": {},
            "privacy": {},
        }
    elif name == "split-manifest.json":
        value = {
            "schema_version": "1.0",
            "record_type": "split-manifest",
            "dataset_sha256": "b" * 64,
            "algorithm": {},
            "conditions": {},
            "aggregate_counts": {},
            "partition_hashes": {},
            "limitations": [],
        }
    elif name == "metrics-summary.json":
        value = {
            "schema_version": "1.0",
            "record_type": "metrics-summary",
            "run_id": "synthetic-public-run",
            "status": "pilot-complete",
            "aggregate_metrics": {},
            "uncertainty": {},
            "guardrails": {},
            "runtime": {},
            "limitations": [],
            "artifact_hashes": {},
        }
    elif name == "requirements-lock.txt":
        return b"numpy==1.26.4\ntorch==2.6.0+cu124\n"
    elif name == "ATTRIBUTION.md":
        return (
            "# Attribution\n"
            "- Dataset: Covertype\n"
            "- Source: https://archive.ics.uci.edu/dataset/31/covertype\n"
            "- DOI: 10.24432/C50K5N\n"
            "- License: CC BY 4.0\n"
            "- Retrieved: 2026-07-15\n"
            f"- Data SHA-256: {'d' * 64}\n"
        ).encode()
    else:
        raise AssertionError("unknown synthetic public artifact")
    return (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")


class SanitizeExportTests(unittest.TestCase):
    def _run_with_public_artifact(
        self,
        module,
        tmp: str,
        *,
        name: str = "metrics-summary.json",
        kind: str = "metrics-summary",
        payload: Optional[bytes] = None,
        frozen: bool = True,
        sha256: Optional[str] = None,
    ) -> tuple[Path, Path]:
        if payload is None:
            payload = public_artifact_payload(name)
        run = Path(tmp) / "run"
        shutil.copytree(VALID, run)
        source = run / "artifacts" / "public" / name
        source.parent.mkdir(parents=True)
        source.write_bytes(payload)
        manifest_path = run / "artifact-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"].append(
            {
                "artifact_id": "public-artifact-001",
                "path": f"artifacts/public/{name}",
                "kind": kind,
                "sha256": sha256 or hashlib.sha256(payload).hexdigest(),
                "producing_run": "minimal-valid-run",
                "frozen": frozen,
            }
        )
        index = len(manifest["artifacts"]) - 1
        slash = "/"
        pointer_root = slash + "artifacts" + slash + str(index) + slash
        manifest["field_sensitivity"][pointer_root + "path"] = "public"
        manifest["field_sensitivity"][pointer_root + "kind"] = "public"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        output = Path(tmp) / "public"
        return run, output

    def test_public_export_copies_only_frozen_hash_matched_allowlisted_text(self):
        module = load_module()
        self.assertEqual(
            {
                "experiment-code": "experiment.py",
                "experiment-config": "experiment-config.json",
                "requirements-lock": "requirements-lock.txt",
                "split-manifest": "split-manifest.json",
                "metrics-summary": "metrics-summary.json",
                "attribution": "ATTRIBUTION.md",
            },
            {
                kind: rule["basename"]
                for kind, rule in module.PUBLIC_ARTIFACT_RULES.items()
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(module, tmp)
            (run / "artifacts" / "raw").mkdir(parents=True)
            (run / "artifacts" / "raw" / "dataset.bin").write_bytes(b"raw")
            (run / "artifacts" / "checkpoint.bin").write_bytes(b"checkpoint")

            report = module.sanitize_public_run(run, output)

            self.assertEqual(1, report["artifacts_exported"])
            self.assertEqual(
                public_artifact_payload("metrics-summary.json"),
                (output / "artifacts" / "public" / "metrics-summary.json").read_bytes(),
            )
            self.assertFalse((output / "artifacts" / "raw").exists())
            self.assertFalse((output / "artifacts" / "checkpoint.bin").exists())
            exported = json.loads(
                (output / "artifact-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "artifacts/public/metrics-summary.json",
                exported["artifacts"][1]["path"],
            )

    def test_each_allowlisted_public_artifact_kind_can_be_exported(self):
        module = load_module()
        cases = (
            ("experiment.py", "experiment-code"),
            ("experiment-config.json", "experiment-config"),
            ("requirements-lock.txt", "requirements-lock"),
            ("split-manifest.json", "split-manifest"),
            ("metrics-summary.json", "metrics-summary"),
            ("ATTRIBUTION.md", "attribution"),
        )
        for name, kind in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                payload = public_artifact_payload(name)
                run, output = self._run_with_public_artifact(
                    module, tmp, name=name, kind=kind, payload=payload
                )
                report = module.sanitize_public_run(run, output)
                self.assertEqual(1, report["artifacts_exported"])
                self.assertEqual(
                    payload,
                    (output / "artifacts" / "public" / name).read_bytes(),
                )

    def test_unfrozen_public_artifact_is_not_copied(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(
                module, tmp, frozen=False
            )
            report = module.sanitize_public_run(run, output)
            self.assertEqual(0, report["artifacts_exported"])
            self.assertFalse((output / "artifacts").exists())

    def test_duplicate_public_artifact_destination_is_rejected(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(module, tmp)
            manifest_path = run / "artifact-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            duplicate = dict(manifest["artifacts"][1])
            duplicate["artifact_id"] = "public-artifact-duplicate"
            manifest["artifacts"].append(duplicate)
            index = len(manifest["artifacts"]) - 1
            slash = "/"
            pointer_root = slash + "artifacts" + slash + str(index) + slash
            manifest["field_sensitivity"][pointer_root + "path"] = "public"
            manifest["field_sensitivity"][pointer_root + "kind"] = "public"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)
            self.assertFalse(output.exists())

    def test_unfrozen_unknown_public_artifact_is_rejected(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(
                module,
                tmp,
                name="checkpoint.bin",
                kind="checkpoint",
                payload=b"not exported",
                frozen=False,
            )

            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)
            self.assertFalse(output.exists())

    def test_project_private_public_artifact_declaration_is_rejected(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(module, tmp)
            manifest_path = run / "artifact-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            slash = "/"
            pointer = slash + "artifacts" + slash + "1" + slash + "path"
            manifest["field_sensitivity"][pointer] = (
                "project-private"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)
            self.assertFalse(output.exists())

    def test_public_artifact_rejects_unsafe_or_unreproducible_content(self):
        module = load_module()
        synthetic_jwt = (
            "eyJ" + ("A" * 24) + "." + ("B" * 32) + "." + ("C" * 32)
        )
        cases = (
            ("unknown-kind", {"kind": "checkpoint"}),
            (
                "unknown-name",
                {
                    "name": "results.json",
                    "payload": public_artifact_payload("metrics-summary.json"),
                },
            ),
            ("hash-drift", {"sha256": "0" * 64}),
            ("binary", {"name": "requirements-lock.txt", "kind": "requirements-lock", "payload": b"a\x00b"}),
            ("malformed-json", {"payload": b"{not-json}\n"}),
            (
                "credential",
                {"payload": json.dumps({"value": synthetic_token()}).encode()},
            ),
            (
                "personal-path",
                {
                    "payload": (
                        '{"path":"C:'
                        + "\\\\"
                        + "Users\\\\synthetic\\\\run" + '"}\n'
                    ).encode()
                },
            ),
            (
                "environment-dump",
                {
                    "name": "requirements-lock.txt",
                    "kind": "requirements-lock",
                    "payload": b"PATH=relative-bin\nHOME=relative-home\nUSER=synthetic\n",
                },
            ),
            (
                "codex-oauth-assignment",
                {
                    "name": "requirements-lock.txt",
                    "kind": "requirements-lock",
                    "payload": ("CODEX_ACCESS_TOKEN=" + synthetic_jwt + "\n").encode(),
                },
            ),
            (
                "json-access-token",
                {"payload": json.dumps({"access_token": synthetic_jwt}).encode()},
            ),
            (
                "json-refresh-token",
                {"payload": json.dumps({"refresh_token": synthetic_jwt}).encode()},
            ),
            (
                "json-environment-dump",
                {"payload": b'{"PATH":"relative-bin","HOME":"relative-home"}\n'},
            ),
            (
                "raw-rows-in-metrics",
                {"payload": b'{"raw_rows":[[1,2],[3,4]]}\n'},
            ),
            (
                "base64-checkpoint-in-attribution",
                {
                    "name": "ATTRIBUTION.md",
                    "kind": "attribution",
                    "payload": ("# Attribution\n" + ("A" * 1024) + "\n").encode(),
                },
            ),
            (
                "malformed-python",
                {
                    "name": "experiment.py",
                    "kind": "experiment-code",
                    "payload": b"this is not valid python ?\n",
                },
            ),
        )
        for label, kwargs in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                run, output = self._run_with_public_artifact(module, tmp, **kwargs)
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)
                self.assertFalse(output.exists())

    def test_public_artifact_rejects_hardlink_to_outside_run(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(module, tmp)
            source = run / "artifacts" / "public" / "metrics-summary.json"
            payload = source.read_bytes()
            external = Path(tmp) / "outside-run.json"
            external.write_bytes(payload)
            source.unlink()
            try:
                os.link(external, source)
            except OSError as error:
                self.skipTest("hard links are unavailable: " + type(error).__name__)
            self.assertGreater(source.stat().st_nlink, 1)

            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)
            self.assertFalse(output.exists())

    def test_public_json_rejects_row_payload_hidden_in_aggregate_section(self):
        module = load_module()
        value = json.loads(public_artifact_payload("metrics-summary.json"))
        value["aggregate_metrics"] = {
            "values": [[1, 2, 3], [4, 5, 6]]
        }
        payload = (json.dumps(value) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(
                module, tmp, payload=payload
            )
            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)
            self.assertFalse(output.exists())

    def test_public_json_rejects_duplicate_keys_and_row_objects(self):
        module = load_module()
        valid = json.loads(public_artifact_payload("metrics-summary.json"))
        suffix = json.dumps(
            {
                key: value
                for key, value in valid.items()
                if key != "aggregate_metrics"
            },
            sort_keys=True,
        )[1:]
        duplicate = (
            '{"aggregate_metrics":{"row001":{"f1":0.5}},'
            + '"aggregate_metrics":{},'
            + suffix
        ).encode("utf-8")
        nested_row = dict(valid)
        nested_row["aggregate_metrics"] = {"row001": {"f1": 0.5}}
        cases = (
            ("duplicate-key", duplicate),
            ("row-object", (json.dumps(nested_row) + "\n").encode()),
        )
        for label, payload in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                run, output = self._run_with_public_artifact(
                    module, tmp, payload=payload
                )
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)
                self.assertFalse(output.exists())

    def test_public_artifact_rejects_split_encoded_or_literal_payloads(self):
        module = load_module()
        encoded_lines = "\n".join("A" * 76 for _ in range(10))
        python_literals = "payload = [\n" + "\n".join(
            repr("B" * 100) + "," for _ in range(20)
        ) + "\n]\n"
        cases = (
            (
                "attribution-encoded-lines",
                "ATTRIBUTION.md",
                "attribution",
                ("# Attribution\n" + encoded_lines + "\n").encode(),
            ),
            (
                "requirements-encoded-comments",
                "requirements-lock.txt",
                "requirements-lock",
                (
                    "numpy==1.26.4\n"
                    + "\n".join("# " + ("C" * 76) for _ in range(20))
                    + "\n"
                ).encode(),
            ),
            (
                "python-split-literals",
                "experiment.py",
                "experiment-code",
                python_literals.encode(),
            ),
        )
        for label, name, kind, payload in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                run, output = self._run_with_public_artifact(
                    module, tmp, name=name, kind=kind, payload=payload
                )
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)
                self.assertFalse(output.exists())

    def test_public_reader_anchors_every_parent_directory_by_handle(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("dir_fd=", source)
        self.assertIn("GetFinalPathNameByHandleW", source)
        self.assertNotIn("source.read_bytes()", source)

    def test_oauth_finding_never_echoes_synthetic_value(self):
        module = load_module()
        synthetic_jwt = (
            "eyJ" + ("D" * 24) + "." + ("E" * 32) + "." + ("F" * 32)
        )
        payload = ("CODEX_ACCESS_TOKEN=" + synthetic_jwt + "\n").encode()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(
                module,
                tmp,
                name="requirements-lock.txt",
                kind="requirements-lock",
                payload=payload,
            )
            with self.assertRaises(module.SecurityViolation) as raised:
                module.sanitize_public_run(run, output)
            serialized = json.dumps(
                [item.__dict__ for item in raised.exception.findings]
            )
            self.assertNotIn(synthetic_jwt, serialized)
            self.assertFalse(output.exists())

    def test_public_artifact_rejects_oversize_sources(self):
        module = load_module()
        limit = module.PUBLIC_ARTIFACT_RULES["attribution"]["max_bytes"]
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(
                module,
                tmp,
                name="ATTRIBUTION.md",
                kind="attribution",
                payload=b"A" * (limit + 1),
            )
            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)

    def test_public_artifact_rejects_symlink_or_reparse_sources(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(module, tmp)
            with patch.object(
                module, "_is_reparse_or_symlink", return_value=True
            ):
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)

    def test_public_artifact_rejects_absolute_and_parent_traversal_paths(self):
        module = load_module()
        for unsafe_path in (
            "artifacts/public/../metrics-summary.json",
            "C:" + "/" + "synthetic/metrics-summary.json",
        ):
            with self.subTest(path_kind=unsafe_path.split("/", 1)[0]), tempfile.TemporaryDirectory() as tmp:
                run, output = self._run_with_public_artifact(module, tmp)
                manifest_path = run / "artifact-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["artifacts"][1]["path"] = unsafe_path
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)

    def test_json_artifact_hash_maps_require_bounded_sha256_values(self):
        module = load_module()
        invalid_payloads = []
        metrics = json.loads(public_artifact_payload("metrics-summary.json"))
        metrics["artifact_hashes"] = {"model": "f" * 63}
        invalid_payloads.append(("metrics-summary.json", "metrics-summary", metrics))
        split = json.loads(public_artifact_payload("split-manifest.json"))
        split["partition_hashes"] = {"train": "g" * 64}
        invalid_payloads.append(("split-manifest.json", "split-manifest", split))
        split = json.loads(public_artifact_payload("split-manifest.json"))
        split["algorithm"] = {
            "split_hashes": {
                f"split-{index}": "a" * 64 for index in range(65)
            }
        }
        invalid_payloads.append(("split-manifest.json", "split-manifest", split))
        for index, (name, kind, value) in enumerate(invalid_payloads):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                payload = (json.dumps(value) + "\n").encode()
                run, output = self._run_with_public_artifact(
                    module, tmp, name=name, kind=kind, payload=payload
                )
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)

        valid_payloads = []
        metrics = json.loads(public_artifact_payload("metrics-summary.json"))
        metrics["artifact_hashes"] = {"config": "A" * 64}
        valid_payloads.append(("metrics-summary.json", "metrics-summary", metrics))
        split = json.loads(public_artifact_payload("split-manifest.json"))
        split["partition_hashes"] = {"train": "B" * 64}
        split["algorithm"] = {"split_hashes": {"seed-101": "c" * 64}}
        valid_payloads.append(("split-manifest.json", "split-manifest", split))
        for name, kind, value in valid_payloads:
            with tempfile.TemporaryDirectory() as tmp:
                payload = (json.dumps(value) + "\n").encode()
                run, output = self._run_with_public_artifact(
                    module, tmp, name=name, kind=kind, payload=payload
                )
                module.sanitize_public_run(run, output)

    def test_json_artifact_rejects_large_or_cross_element_encoded_text_lists(self):
        module = load_module()
        encoded = base64.b64encode(b"private checkpoint material").decode()
        uneven_encoded = base64.b64encode(
            b"private checkpoint material" * 8
        ).decode()
        invalid_payloads = (
            ["safe text " * 60, "more text " * 60],
            [encoded[: len(encoded) // 2], encoded[len(encoded) // 2 :]],
            [uneven_encoded[:40], uneven_encoded[40:]],
        )
        for index, values in enumerate(invalid_payloads):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                value = json.loads(public_artifact_payload("metrics-summary.json"))
                value["limitations"] = values
                payload = (json.dumps(value) + "\n").encode()
                run, output = self._run_with_public_artifact(
                    module, tmp, payload=payload
                )
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)

    def test_attribution_uses_closed_small_format_and_allows_minimal_uci_record(self):
        module = load_module()
        valid = (
            "# Attribution\n"
            "- Dataset: Covertype\n"
            "- Source: https://archive.ics.uci.edu/dataset/31/covertype\n"
            "- DOI: 10.24432/C50K5N\n"
            "- License: CC BY 4.0\n"
            "- Retrieved: 2026-07-15\n"
            f"- Data SHA-256: {'d' * 64}\n"
        ).encode()
        with tempfile.TemporaryDirectory() as tmp:
            run, output = self._run_with_public_artifact(
                module,
                tmp,
                name="ATTRIBUTION.md",
                kind="attribution",
                payload=valid,
            )
            module.sanitize_public_run(run, output)

        encoded = base64.b64encode(b"private checkpoint material").decode()
        invalid_values = (
            "# Attribution\n- Dataset: Covertype\n- Source: https://archive.ics.uci.edu/dataset/31/covertype\n- License: CC BY 4.0\n- Notes: private material\n",
            f"# Attribution\n- Dataset: {encoded}\n- Source: https://archive.ics.uci.edu/dataset/31/covertype\n- License: CC BY 4.0\n",
            (
                "# Attribution\n"
                f"- Dataset: {encoded[:20]}\n"
                "- Source: https://archive.ics.uci.edu/dataset/31/covertype\n"
                f"- License: {encoded[20:]}\n"
            ),
            "# Attribution\nprivate\ncheckpoint\nmaterial\n",
        )
        for index, text_value in enumerate(invalid_values):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as tmp:
                run, output = self._run_with_public_artifact(
                    module,
                    tmp,
                    name="ATTRIBUTION.md",
                    kind="attribution",
                    payload=text_value.encode(),
                )
                with self.assertRaises(module.SecurityViolation):
                    module.sanitize_public_run(run, output)

    def test_high_confidence_credential_is_rejected_without_echo(self):
        module = load_module()
        token = synthetic_token()
        header = "Authorization" + ": " + "Bearer "
        findings = module.scan_text(header + token, "event:4")
        self.assertIn(
            "credential.authorization_header", {item.code for item in findings}
        )
        self.assertNotIn(token, json.dumps([item.__dict__ for item in findings]))

    def test_credential_in_member_name_is_rejected_without_echo(self):
        module = load_module()
        token = synthetic_token()
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            token: "safe synthetic value",
            "field_sensitivity": {"/" + token: "public"},
        }
        findings = module.scan_value(record)
        self.assertIn("credential.openai_token", {item.code for item in findings})
        self.assertNotIn(token, json.dumps([item.__dict__ for item in findings]))

    def test_classification_pointer_gets_full_privacy_scan_without_echo(self):
        module = load_module()
        email = "synthetic-pointer" + "@" + "example.invalid"
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            "summary": "safe synthetic summary",
            "field_sensitivity": {
                "/" + "summary": "public",
                "/" + email: "public",
            },
        }
        findings = module.scan_value(record)
        self.assertIn("privacy.email", {item.code for item in findings})
        serialized = json.dumps([item.__dict__ for item in findings])
        self.assertFalse(email in serialized)

    def test_detector_matrix_is_complete_and_never_echoes_matches(self):
        module = load_module()
        samples = (
            (
                "credential.private_key",
                "-----BEGIN " + "PRIVATE KEY" + "-----",
            ),
            ("credential.anthropic_token", "sk" + "-ant-" + ("B" * 40)),
            ("credential.github_token", "gh" + "p_" + ("C" * 36)),
            ("credential.aws_access_key", "AK" + "IA" + ("D" * 16)),
            (
                "credential.generic_assignment",
                "api_" + "key=" + ("E" * 24),
            ),
            ("credential.session_cookie", "session" + "=" + ("F" * 20)),
            (
                "credential.url_userinfo",
                "https"
                + ":"
                + "/"
                + "/"
                + "user"
                + ":"
                + ("G" * 20)
                + "@"
                + "example.invalid/path",
            ),
            ("privacy.email", "synthetic" + "@" + "example.invalid"),
            (
                "privacy.mac_address",
                ":".join(("02", "00", "00", "00", "00", "01")),
            ),
            ("privacy.host_or_user", "host" + "=synthetic-node"),
            ("privacy.device_id", "device_" + "id=synthetic-device"),
            (
                "privacy.absolute_path",
                "path=" + "\\\\" + "synthetic-host\\share\\file",
            ),
            ("privacy.local_ip", ".".join(("10", "1", "2", "3"))),
        )
        for expected_code, sample in samples:
            with self.subTest(code=expected_code):
                findings = module.scan_text(sample, "state")
                self.assertIn(expected_code, {item.code for item in findings})
                serialized = json.dumps([item.__dict__ for item in findings])
                self.assertFalse(sample in serialized)

        noreply = "synthetic" + "@" + "users.noreply.github.com"
        codes = {item.code for item in module.scan_text(noreply, "state")}
        self.assertNotIn("privacy.email", codes)

    def test_machine_identity_and_absolute_paths_are_not_public(self):
        module = load_module()
        local_ip = ".".join(("192", "168", "1", "42"))
        backslash = "\\"
        text = (
            "host"
            + "=lab-pc-17 path=C:"
            + backslash
            + "Users"
            + backslash
            + "local-user"
            + backslash
            + "project local="
            + local_ip
        )
        codes = {item.code for item in module.scan_text(text, "brief")}
        self.assertTrue(
            {"privacy.absolute_path", "privacy.local_ip"}.issubset(codes)
        )

    def test_general_absolute_paths_and_file_urls_are_not_public(self):
        module = load_module()
        slash = "/"
        backslash = "\\"
        samples = (
            "path=D:" + backslash + "work" + backslash + "synthetic-project",
            "path=" + slash + "tmp/synthetic-project",
            "uri=" + "file" + ":" + slash * 3 + "home/synthetic/project",
        )
        for sample in samples:
            with self.subTest(kind=sample.split("=", 1)[0]):
                codes = {item.code for item in module.scan_text(sample, "state")}
                self.assertIn("privacy.absolute_path", codes)

    def test_forward_slash_windows_and_punctuated_posix_paths_are_not_public(self):
        module = load_module()
        slash = "/"
        samples = (
            "path=D:" + slash + "work/synthetic-project",
            "path=(" + slash + "tmp/synthetic-project" + ")",
        )
        for sample in samples:
            with self.subTest(kind=sample.split("=", 1)[0]):
                findings = module.scan_text(sample, "state")
                self.assertIn(
                    "privacy.absolute_path", {item.code for item in findings}
                )
                serialized = json.dumps([item.__dict__ for item in findings])
                self.assertFalse(sample in serialized)

    def test_unknown_hash_named_string_still_requires_classification(self):
        module = load_module()
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            "unrecognized_hash": "0" * 64,
            "field_sensitivity": {},
        }
        codes = {item.code for item in module.scan_value(record)}
        self.assertIn("privacy.missing_classification", codes)

    def test_non_string_classification_has_stable_invalid_code(self):
        module = load_module()
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            "summary": "safe synthetic summary",
            "field_sensitivity": {"/" + "summary": {}},
        }
        codes = {item.code for item in module.scan_value(record)}
        self.assertIn("privacy.invalid_classification", codes)

    def test_non_string_record_type_does_not_break_security_scan(self):
        module = load_module()
        record = {
            "schema_version": "1.0",
            "record_type": [],
            "summary": "safe synthetic summary",
            "field_sensitivity": {"/" + "summary": "public"},
        }
        self.assertEqual([], module.scan_value(record))

    def test_structural_allowlist_is_pointer_specific(self):
        module = load_module()
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            "metadata": {"status": "synthetic status text"},
            "field_sensitivity": {},
        }
        codes = {item.code for item in module.scan_value(record)}
        self.assertIn("privacy.missing_classification", codes)

    def test_pointer_type_mismatch_does_not_emit_cascade_classification(self):
        module = load_module()
        record = {
            "schema_version": "1.0",
            "record_type": "experiment",
            "environment": {"runtime": {}},
            "field_sensitivity": {"/" + "environment/runtime": "public"},
        }
        codes = {item.code for item in module.scan_value(record)}
        self.assertNotIn("privacy.invalid_classification", codes)

    def test_stale_child_of_valid_scalar_is_reported_without_pointer_echo(self):
        module = load_module()
        record = json.loads(
            (VALID / "experiment-ledger.jsonl").read_text(encoding="utf-8")
        )
        stale_pointer = "/environment/runtime/" + "synthetic-child"
        record["field_sensitivity"][stale_pointer] = "public"

        findings = module.scan_value(record)
        self.assertIn(
            "privacy.classification_path_missing",
            {item.code for item in findings},
        )
        serialized = json.dumps([item.__dict__ for item in findings])
        self.assertFalse(stale_pointer in serialized)

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            shutil.copytree(VALID, run)
            (run / "experiment-ledger.jsonl").write_text(
                json.dumps(record) + "\n", encoding="utf-8"
            )
            validator = module._load_validator_module()
            loaded, parsing_findings = validator.load_run(run)
            validation_findings = validator.validate_loaded(
                run, loaded, parsing_findings
            )
        self.assertIn(
            "privacy.classification_path_missing",
            {item.code for item in validation_findings},
        )
        validation_payload = json.dumps(
            [item.__dict__ for item in validation_findings]
        )
        self.assertFalse(stale_pointer in validation_payload)

    def test_structural_allowlist_is_record_type_specific(self):
        module = load_module()
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            "content_hash": "0" * 64,
            "field_sensitivity": {},
        }
        codes = {item.code for item in module.scan_value(record)}
        self.assertIn("privacy.missing_classification", codes)

    def test_public_export_keeps_public_and_drops_project_private_fields(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            report = module.sanitize_public_run(VALID, output)
            self.assertEqual([], report["findings"])
            exported = json.loads(
                (output / "research-brief.json").read_text(encoding="utf-8")
            )
            self.assertIn("public_summary", exported)
            self.assertNotIn("private_question", exported)

    def test_export_repairs_artifact_path_and_its_public_classification(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            shutil.copytree(VALID, run)
            source = run / "artifact-manifest.json"
            manifest = json.loads(source.read_text(encoding="utf-8"))
            manifest["field_sensitivity"]["/" + "artifacts/0/path"] = (
                "project-private"
            )
            source.write_text(json.dumps(manifest), encoding="utf-8")

            output = Path(tmp) / "public"
            module.sanitize_public_run(run, output)
            exported = json.loads(
                (output / "artifact-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "artifacts/artifact-001", exported["artifacts"][0]["path"]
            )
            self.assertEqual(
                "public",
                exported["field_sensitivity"]["/" + "artifacts/0/path"],
            )

            validator = module._load_validator_module()
            loaded, parsing_findings = validator.load_run(output)
            validation_findings = validator.validate_loaded(
                output, loaded, parsing_findings
            )
            self.assertEqual([], validation_findings)
            self.assertEqual([], module._scan_loaded(loaded))

    def test_public_export_validates_and_writes_one_source_snapshot(self):
        module = load_module()
        reads = {filename: 0 for filename in module.REQUIRED_FILES}
        original_read_text = Path.read_text

        def tracked_read_text(path, *args, **kwargs):
            if path.parent == VALID and path.name in reads:
                reads[path.name] += 1
            return original_read_text(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            Path, "read_text", tracked_read_text
        ):
            module.sanitize_public_run(VALID, Path(tmp) / "public")
        self.assertEqual({1}, set(reads.values()))

    def test_public_export_refuses_secret_instead_of_redacting_it(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            for source in VALID.iterdir():
                if source.is_file():
                    (run / source.name).write_bytes(source.read_bytes())
            brief = json.loads(
                (run / "research-brief.json").read_text(encoding="utf-8")
            )
            brief["public_summary"] = synthetic_token()
            (run / "research-brief.json").write_text(
                json.dumps(brief), encoding="utf-8"
            )
            output = Path(tmp) / "public"
            output.mkdir()
            marker = output / "marker.txt"
            marker.write_text("unchanged", encoding="utf-8")
            with self.assertRaises(module.SecurityViolation):
                module.sanitize_public_run(run, output)
            self.assertEqual("unchanged", marker.read_text(encoding="utf-8"))
            self.assertEqual([], list(Path(tmp).glob(".public.tmp-*")))

    def test_public_export_cli_uses_exit_two_for_missing_run(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = module.main(
                    ["public-export", str(missing), str(Path(tmp) / "public")]
                )
        self.assertEqual(2, exit_code)
        self.assertNotIn(str(missing), output.getvalue())

    def test_cli_usage_error_does_not_echo_unknown_credential_argument(self):
        module = load_module()
        token = synthetic_token()
        unknown = "--" + "token=" + token
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                exit_code = module.main(["scan-state", str(VALID), unknown])
            except SystemExit as error:
                exit_code = error.code
        self.assertEqual(2, exit_code)
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertFalse(any(value in combined for value in (unknown, token)))

    def test_caller_supplied_locations_are_normalized_without_echo(self):
        module = load_module()
        token = synthetic_token()
        backslash = "\\"
        unsafe_locations = (
            "C:"
            + backslash
            + "Users"
            + backslash
            + "synthetic-user"
            + backslash
            + "run",
            "file" + ":///home/synthetic-user/run",
            "where=" + token,
            "arbitrary caller text",
        )
        record = {
            "schema_version": "1.0",
            "record_type": "research-brief",
            "summary": token,
            "field_sensitivity": {"/" + "summary": "public"},
        }
        for index, location in enumerate(unsafe_locations):
            with self.subTest(index=index):
                findings = module.scan_text(token, location)
                findings.extend(module.scan_value(record, location))
                serialized = json.dumps([item.__dict__ for item in findings])
                self.assertFalse(
                    any(value in serialized for value in (location, token))
                )
        allowed = module.scan_text(token, "event:4")
        self.assertEqual({"event:4"}, {item.location for item in allowed})


if __name__ == "__main__":
    unittest.main()
