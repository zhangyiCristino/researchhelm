from __future__ import annotations

import base64
import errno
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest import mock
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "researchhelm" / "scripts" / "inspect_skill.py"
SAFE = ROOT / "tests" / "fixtures" / "skills" / "safe-skill"
RISKY = ROOT / "tests" / "fixtures" / "skills" / "risky-skill"
REPORT_KEYS = {
    "valid_skill",
    "frontmatter",
    "files",
    "tree_hash",
    "risks",
    "source",
    "revision",
}


def load_module():
    spec = importlib.util.spec_from_file_location("inspect_skill", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_skill(root: Path, frontmatter: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    content = frontmatter or (
        "---\nname: temporary-skill\n"
        "description: Use when exercising the local inspector.\n---\n"
    )
    (root / "SKILL.md").write_text(content, encoding="utf-8")


def synthetic_token(marker: str = "A") -> str:
    return "sk-" + (marker + "1_") * 12


def enable_posix_flags(testcase, module) -> None:
    patcher = mock.patch.multiple(
        module.os,
        O_DIRECTORY=0x10000,
        O_NOFOLLOW=0x20000,
        O_NONBLOCK=0x40000,
        O_NOCTTY=0x80000,
        create=True,
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)


def posix_metadata(
    *, device=1, inode=1, mode=stat.S_IFDIR, size=0, links=1
):
    return SimpleNamespace(
        st_dev=device,
        st_ino=inode,
        st_size=size,
        st_mtime_ns=1,
        st_ctime_ns=1,
        st_mode=mode,
        st_nlink=links,
    )


def scan_names(*names):
    iterator = mock.MagicMock()
    iterator.__enter__.return_value = iter(SimpleNamespace(name=name) for name in names)
    return iterator


class ExplodingList(list):
    def append(self, value):
        del value
        raise MemoryError("simulated")


@contextmanager
def posix_root_environment(
    module,
    opened,
    metadata=None,
    platform="linux",
    prepared=PurePosixPath("/" + "safe"),
):
    supports_everything = mock.MagicMock()
    supports_everything.__contains__.return_value = True
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(module.sys, "platform", platform))
        stack.enter_context(
            mock.patch.object(
                module, "_prepare_root_path", return_value=prepared
            )
        )
        stack.enter_context(
            mock.patch.object(module.os, "supports_dir_fd", supports_everything)
        )
        stack.enter_context(mock.patch.object(module.os, "supports_fd", supports_everything))
        stack.enter_context(
            mock.patch.multiple(
                module.os,
                O_DIRECTORY=0x10000,
                O_NOFOLLOW=0x20000,
                O_NONBLOCK=0x40000,
                O_NOCTTY=0x80000,
                create=True,
            )
        )
        stack.enter_context(mock.patch.object(module.os, "open", side_effect=opened))
        if metadata is not None:
            stack.enter_context(mock.patch.object(module.os, "fstat", return_value=metadata))
        yield


class InspectSkillTests(unittest.TestCase):
    def test_safe_skill_has_stable_minimal_report(self):
        module = load_module()
        first = module.inspect_skill(SAFE, "https://example.test/safe", "abc123")
        second = module.inspect_skill(SAFE, "https://example.test/safe", "abc123")

        self.assertEqual(REPORT_KEYS, set(first))
        self.assertTrue(first["valid_skill"])
        self.assertEqual("safe-skill", first["frontmatter"]["name"])
        self.assertEqual(first["tree_hash"], second["tree_hash"])
        self.assertEqual([], first["risks"])
        self.assertEqual("https://example.test/safe", first["source"])
        self.assertEqual("abc123", first["revision"])

    def test_executable_content_is_flagged_but_never_run(self):
        module = load_module()
        marker = RISKY / "EXECUTED"
        marker.unlink(missing_ok=True)

        report = module.inspect_skill(RISKY, None, None)

        self.assertFalse(marker.exists())
        self.assertIn("executable_content", {item["code"] for item in report["risks"]})

    def test_missing_file_root_and_missing_skill_are_invalid(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            missing = module.inspect_skill(temporary / "missing", None, None)
            file_root = temporary / "file-root"
            file_root.write_text("not a directory", encoding="utf-8")
            regular_file = module.inspect_skill(file_root, None, None)
            package = temporary / "package"
            package.mkdir()
            no_skill = module.inspect_skill(package, None, None)

        self.assertEqual(["invalid_root"], [item["code"] for item in missing["risks"]])
        self.assertEqual(["invalid_root"], [item["code"] for item in regular_file["risks"]])
        self.assertEqual(["missing_skill_file"], [item["code"] for item in no_skill["risks"]])
        self.assertFalse(missing["valid_skill"])
        self.assertFalse(regular_file["valid_skill"])
        self.assertFalse(no_skill["valid_skill"])

    def test_invalid_or_unsupported_frontmatter_is_unverified(self):
        module = load_module()
        samples = (
            "name: missing-delimiters\ndescription: Use when invalid.\n",
            "---\nname: missing-close\ndescription: Use when invalid.\n",
            "---\nname: duplicate\nname: duplicate\ndescription: Use when invalid.\n---\n",
            "---\nname: folded\ndescription: >\n  Use when YAML parsing is required.\n---\n",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            reports = []
            for index, sample in enumerate(samples):
                package = base / str(index)
                write_skill(package, sample)
                reports.append(module.inspect_skill(package, None, None))

        for report in reports:
            self.assertFalse(report["valid_skill"])
            self.assertIn(
                "frontmatter_unverified", {item["code"] for item in report["risks"]}
            )

    def test_symlinks_are_reported_once_without_being_followed(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            root = temporary / "skill"
            outside = temporary / "outside"
            write_skill(root)
            outside.mkdir()
            (outside / "outside.txt").write_text("outside", encoding="utf-8")
            without_links = module.inspect_skill(root, None, None)
            try:
                (root / "directory-link").symlink_to(outside, target_is_directory=True)
                (root / "file-link").symlink_to(outside / "outside.txt")
            except OSError:
                self.skipTest("symlinks unavailable")

            first = module.inspect_skill(root, None, None)
            second = module.inspect_skill(root, None, None)

        symlink_paths = [
            item["path"] for item in first["risks"] if item["code"] == "symlink"
        ]
        self.assertEqual(["directory-link", "file-link"], symlink_paths)
        self.assertEqual(first, second)
        self.assertFalse(first["valid_skill"])
        self.assertNotEqual(without_links["tree_hash"], first["tree_hash"])
        self.assertEqual(
            {"directory-link", "file-link"},
            {
                item["path"]
                for item in first["files"]
                if item.get("kind") == "link"
            },
        )
        self.assertNotIn("outside.txt", {item["path"] for item in first["files"]})

    def test_file_order_hash_and_risk_detection_are_deterministic(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            (root / "z.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
            (root / "a.bin").write_bytes(b"safe-prefix\x00binary")
            (root / "large.dat").write_bytes(b"x" * (module.MAX_INSPECTED_BYTES + 1))

            first = module.inspect_skill(root, None, None)
            second = module.inspect_skill(root, None, None)

        self.assertEqual(first, second)
        self.assertEqual(
            sorted(item["path"] for item in first["files"]),
            [item["path"] for item in first["files"]],
        )
        codes = {item["code"] for item in first["risks"]}
        self.assertTrue({"binary_content", "executable_content", "large_file"} <= codes)

    def test_tree_hash_changes_when_file_content_changes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            payload = root / "notes.txt"
            payload.write_text("first", encoding="utf-8")
            first = module.inspect_skill(root, None, None)["tree_hash"]
            payload.write_text("second", encoding="utf-8")
            second = module.inspect_skill(root, None, None)["tree_hash"]

        self.assertNotEqual(first, second)

    def test_large_file_is_bounded_unhashed_and_blocking(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            payload = root / "large.dat"
            payload.write_bytes(b"x" * (module.MAX_INSPECTED_BYTES + 1))
            report = module.inspect_skill(root, None, None)

        file_record = next(
            item for item in report["files"] if item["path"] == "large.dat"
        )
        self.assertIsNone(file_record["sha256"])
        self.assertFalse(report["valid_skill"])
        self.assertIn("large_file", {item["code"] for item in report["risks"]})

    def test_file_count_depth_and_total_byte_limits_fail_closed(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            (root / "extra.txt").write_text("extra", encoding="utf-8")
            deep = root / "one" / "two"
            deep.mkdir(parents=True)
            (deep / "leaf.txt").write_text("leaf", encoding="utf-8")

            with mock.patch.object(module, "MAX_FILES", 1):
                files_report = module.inspect_skill(root, None, None)
            with mock.patch.object(module, "MAX_DEPTH", 1):
                depth_report = module.inspect_skill(root, None, None)
            with mock.patch.object(module, "MAX_TOTAL_BYTES", 1):
                bytes_report = module.inspect_skill(root, None, None)

        self.assertIn("resource_limit_files", {r["code"] for r in files_report["risks"]})
        self.assertIn("resource_limit_depth", {r["code"] for r in depth_report["risks"]})
        self.assertIn("resource_limit_bytes", {r["code"] for r in bytes_report["risks"]})
        self.assertFalse(files_report["valid_skill"])
        self.assertFalse(depth_report["valid_skill"])
        self.assertFalse(bytes_report["valid_skill"])

    def test_encoded_credentials_are_blocked_without_echo_or_hash(self):
        module = load_module()
        token = synthetic_token("H")
        encoded_samples = (
            quote(token, safe=""),
            base64.b64encode(token.encode("utf-8")).decode("ascii"),
            token.encode("utf-16").decode("latin-1"),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            reports = []
            for index, sample in enumerate(encoded_samples):
                write_skill(root)
                payload = root / f"encoded-{index}.txt"
                if index == 2:
                    payload.write_bytes(sample.encode("latin-1"))
                else:
                    payload.write_text(sample, encoding="utf-8")
                reports.append(module.inspect_skill(root, None, None))
                payload.unlink()

        for index, report in enumerate(reports):
            serialized = json.dumps(report, sort_keys=True)
            self.assertFalse(report["valid_skill"], index)
            self.assertIn("sensitive_content", {r["code"] for r in report["risks"]})
            self.assertNotIn(token, serialized)
            record = next(item for item in report["files"] if item["path"].startswith("encoded-"))
            self.assertIsNone(record["sha256"])

    def test_execute_bits_and_extensionless_shebang_are_manifested(self):
        module = load_module()
        self.assertTrue(module._executable_status("runner", 0o100755, b"plain"))
        self.assertTrue(module._executable_status("runner", 0o100644, b"#!/bin/sh\n"))
        self.assertFalse(module._executable_status("notes", 0o100644, b"plain"))

        report = module.inspect_skill(SAFE, None, None)
        skill = next(item for item in report["files"] if item["path"] == "SKILL.md")
        self.assertIn("mode", skill)
        self.assertIn("executable", skill)

    def test_unc_and_device_roots_are_rejected_before_filesystem_calls(self):
        module = load_module()
        slash = "/"
        backslash = "\\"
        samples = (
            backslash * 2 + backslash.join(("server", "share", "skill")),
            slash * 2 + slash.join(("server", "share", "skill")),
            backslash * 2 + "?" + backslash + "C:" + backslash + "skill",
            backslash * 2 + "." + backslash + "C:" + backslash + "skill",
        )
        for sample in samples:
            with self.subTest(index=samples.index(sample)):
                with mock.patch.object(module.os.path, "abspath", side_effect=AssertionError):
                    with mock.patch.object(module.os, "lstat", side_effect=AssertionError):
                        with mock.patch.object(module.Path, "resolve", side_effect=AssertionError):
                            with self.assertRaises(module.UnsafeEntryError):
                                module._prepare_root_path(Path(sample))

    def test_windows_device_ads_and_trailing_components_are_lexically_rejected(self):
        module = load_module()
        backslash = "\\"
        samples = tuple(
            "C:" + backslash + "work" + backslash + name
            for name in (
                "COM1",
                "NUL.txt",
                "name:stream",
                "trailing.",
                "trailing ",
            )
        )
        for sample in samples:
            with self.subTest(index=samples.index(sample)):
                with mock.patch.object(module.os.path, "abspath", side_effect=AssertionError):
                    with mock.patch.object(module, "_windows_drive_type", side_effect=AssertionError):
                        with mock.patch.object(module, "_windows_open_handle", side_effect=AssertionError):
                            with self.assertRaises(module.UnsafeEntryError):
                                module._prepare_root_path(Path(sample))

    def test_sensitive_placeholder_counter_is_independent_of_safe_sort_order(self):
        module = load_module()
        token = synthetic_token("K")
        reports = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            for index, unsafe_name in enumerate(("000-" + token, "zzz-" + token)):
                root = base / str(index)
                write_skill(root)
                (root / unsafe_name).write_text("same", encoding="utf-8")
                reports.append(module.inspect_skill(root, None, None))

        self.assertEqual(reports[0]["files"], reports[1]["files"])
        self.assertEqual(reports[0]["tree_hash"], reports[1]["tree_hash"])
        self.assertEqual(
            ["entry=1"],
            [item["path"] for item in reports[0]["files"] if item["path"].startswith("entry=")],
        )

    def test_bounded_name_collection_consumes_at_most_limit_plus_one(self):
        module = load_module()
        self.assertTrue(hasattr(module, "_bounded_names"))
        consumed = 0

        def entries():
            nonlocal consumed
            for index in range(100):
                consumed += 1
                yield SimpleNamespace(name=f"entry-{index}")

        names, overflow = module._bounded_names(entries(), 2)

        self.assertTrue(overflow)
        self.assertEqual(3, consumed)
        self.assertEqual(("entry-0", "entry-1"), names)

    def test_posix_unsupported_entry_is_blocked_without_opening_it(self):
        module = load_module()
        state = module._new_state([])
        iterator = mock.MagicMock()
        iterator.__enter__.return_value = iter([SimpleNamespace(name="pipe")])
        unsupported = SimpleNamespace(st_mode=stat.S_IFIFO, st_nlink=1)
        directory = SimpleNamespace(
            st_dev=1,
            st_ino=1,
            st_size=0,
            st_mtime_ns=1,
            st_ctime_ns=1,
        )

        with mock.patch.object(module.sys, "platform", "darwin"), mock.patch.object(module.os, "scandir", return_value=iterator):
            with mock.patch.object(module.os, "stat", return_value=unsupported):
                with mock.patch.object(module.os, "fstat", return_value=directory):
                    with mock.patch.object(module.os, "O_DIRECTORY", 0x10000, create=True):
                        with mock.patch.object(module.os, "O_NOFOLLOW", 0x20000, create=True):
                            with mock.patch.object(module.os, "open", side_effect=AssertionError):
                                module._walk_posix(10, PurePosixPath(), 0, state)

        self.assertEqual(
            [{"code": "unsupported_entry", "path": "pipe"}], state["risks"]
        )
        self.assertEqual([module._placeholder("pipe", "unsupported")], state["files"])

    def test_posix_cross_device_directory_is_blocked_before_open_or_recursion(self):
        module = load_module()
        enable_posix_flags(self, module)
        state = module._new_state([])
        state["posix_root_dev"] = 1
        root_stat = posix_metadata()
        mounted_stat = posix_metadata(device=2, inode=2)

        with mock.patch.object(module.sys, "platform", "darwin"), mock.patch.object(module.os, "scandir", return_value=scan_names("mounted")):
            with mock.patch.object(module.os, "fstat", return_value=root_stat):
                with mock.patch.object(module.os, "stat", return_value=mounted_stat):
                    with mock.patch.object(module.os, "open", side_effect=AssertionError):
                        with mock.patch.object(
                            module, "_posix_open_child", side_effect=AssertionError, create=True
                        ):
                            module._walk_posix(10, PurePosixPath(), 0, state)

        self.assertEqual(
            [{"code": "unsupported_entry", "path": "mounted"}], state["risks"]
        )
        self.assertEqual(
            [module._placeholder("mounted", "unsupported")], state["files"]
        )
        self.assertEqual([], state["posix_fds"])

    def test_posix_post_open_device_mismatch_closes_without_recursion(self):
        module = load_module()
        enable_posix_flags(self, module)
        state = module._new_state([])
        state["posix_root_dev"] = 1
        root_stat = posix_metadata()
        before = posix_metadata(inode=2)
        after = posix_metadata(device=2, inode=2)

        with mock.patch.object(module.os, "scandir", return_value=scan_names("mounted")):
            with mock.patch.object(module.os, "fstat", side_effect=[root_stat, after]):
                with mock.patch.object(module.os, "stat", return_value=before):
                    with mock.patch.object(module.os, "open", return_value=11):
                        with mock.patch.object(
                            module, "_posix_open_child", return_value=11, create=True
                        ):
                            with mock.patch.object(module.os, "close") as close:
                                module._walk_posix(10, PurePosixPath(), 0, state)

        close.assert_called_once_with(11)
        self.assertEqual(0, state["open_count"])
        self.assertEqual([], state["posix_fds"])
        self.assertEqual(
            [{"code": "unsupported_entry", "path": "mounted"}], state["risks"]
        )

    def test_linux_no_xdev_rejection_blocks_same_device_bind_mount(self):
        module = load_module()
        enable_posix_flags(self, module)
        state = module._new_state([])
        state["posix_root_dev"] = 1
        metadata = posix_metadata(inode=2)

        with mock.patch.object(module.sys, "platform", "linux"):
            with mock.patch.object(module.os, "O_PATH", 0x40000, create=True):
                with mock.patch.object(module.os, "scandir", return_value=scan_names("bound")):
                    with mock.patch.object(module.os, "fstat", return_value=metadata):
                        with mock.patch.object(module.os, "stat", return_value=metadata):
                            with mock.patch.object(module.os, "open", side_effect=AssertionError):
                                with mock.patch.object(
                                    module,
                                    "_linux_openat2",
                                    side_effect=OSError(errno.EXDEV, "blocked"),
                                    create=True,
                                ):
                                    module._walk_posix(10, PurePosixPath(), 0, state)

        self.assertEqual(
            [{"code": "unsupported_entry", "path": "bound"}], state["risks"]
        )
        self.assertEqual([], state["posix_fds"])

    def test_linux_no_xdev_preflight_rejects_mount_before_stat(self):
        module = load_module()
        enable_posix_flags(self, module)
        state = module._new_state([])
        state["posix_root_dev"] = 1
        root = posix_metadata()
        path_flag = 0x40000

        with mock.patch.object(module.sys, "platform", "linux"):
            with mock.patch.object(module.os, "O_PATH", path_flag, create=True):
                with mock.patch.object(
                    module.os, "scandir", return_value=scan_names("mounted")
                ):
                    with mock.patch.object(module.os, "fstat", return_value=root):
                        with mock.patch.object(module.os, "stat", side_effect=AssertionError):
                            with mock.patch.object(
                                module,
                                "_linux_openat2",
                                side_effect=OSError(errno.EXDEV, "blocked"),
                            ) as secure_open:
                                module._walk_posix(10, PurePosixPath(), 0, state)

        self.assertEqual(
            [{"code": "unsupported_entry", "path": "mounted"}], state["risks"]
        )
        flags = secure_open.call_args.args[2]
        self.assertTrue(flags & path_flag)
        self.assertTrue(flags & module.os.O_NOFOLLOW)

    def test_posix_walk_records_non_root_directory_parent_binding(self):
        module = load_module()
        enable_posix_flags(self, module)
        state = module._new_state([])
        state["posix_root_dev"] = 1
        root_stat = posix_metadata()
        child_stat = posix_metadata(inode=2)

        def scan(descriptor):
            return scan_names("child") if descriptor == 10 else scan_names()

        with mock.patch.object(module.sys, "platform", "darwin"), mock.patch.object(module.os, "scandir", side_effect=scan):
            with mock.patch.object(
                module.os, "fstat", side_effect=lambda fd: root_stat if fd == 10 else child_stat
            ):
                with mock.patch.object(module.os, "stat", return_value=child_stat):
                    with mock.patch.object(module.os, "open", return_value=11):
                        with mock.patch.object(
                            module, "_posix_open_child", return_value=11, create=True
                        ):
                            module._walk_posix(10, PurePosixPath(), 0, state)

        child_record = next(
            item for item in state["posix_directories"] if item["fd"] == 11
        )
        self.assertEqual(10, child_record["parent_fd"])
        self.assertEqual("child", child_record["name"])

    def test_windows_open_handle_shares_read_only(self):
        module = load_module()
        kernel32 = mock.MagicMock()
        kernel32.CreateFileW.return_value = 123
        backslash = "\\"
        with mock.patch.object(module, "_windows_kernel32", return_value=kernel32):
            handle = module._windows_open_handle(
                Path("C:" + backslash + "safe" + backslash + "file")
            )

        self.assertEqual(123, handle)
        self.assertEqual(module._FILE_SHARE_READ, kernel32.CreateFileW.call_args.args[2])

    def test_windows_final_snapshot_uses_bounded_rescan_and_detects_name_change(self):
        module = load_module()
        self.assertTrue(hasattr(module, "_verify_windows_package"))
        info = {
            "attributes": module._FILE_ATTRIBUTE_DIRECTORY,
            "size": 0,
            "links": 1,
            "identity": 11,
            "write_time": 22,
        }
        state = module._new_state([])
        state["windows_directories"] = [
            {"path": Path("C:" + "\\safe"), "handle": 10, "initial": info, "names": ("SKILL.md",)}
        ]
        consumed = 0

        def changed_entries():
            nonlocal consumed
            for name in ("SKILL.md", "late.txt", "never-read.txt"):
                consumed += 1
                yield SimpleNamespace(name=name)

        iterator = mock.MagicMock()
        iterator.__enter__.return_value = changed_entries()
        with mock.patch.object(module, "_windows_info", return_value=info):
            with mock.patch.object(module.os, "scandir", return_value=iterator):
                with self.assertRaises(module.UnsafeEntryError) as raised:
                    module._verify_windows_package(state)

        self.assertEqual("identity_changed", raised.exception.code)
        self.assertEqual(2, consumed)

    def test_posix_final_snapshot_restats_file_by_parent_fd(self):
        module = load_module()
        self.assertTrue(hasattr(module, "_verify_posix_package"))
        initial_stat = SimpleNamespace(
            st_dev=1,
            st_ino=2,
            st_size=3,
            st_mtime_ns=4,
            st_ctime_ns=5,
        )
        changed_stat = SimpleNamespace(
            st_dev=1,
            st_ino=99,
            st_size=3,
            st_mtime_ns=4,
            st_ctime_ns=5,
        )
        state = module._new_state([])
        state["posix_files"] = [
            {
                "fd": 12,
                "parent_fd": 10,
                "name": "SKILL.md",
                "initial": module._posix_snapshot(initial_stat),
            }
        ]
        with mock.patch.object(module.os, "fstat", return_value=initial_stat):
            with mock.patch.object(module.os, "stat", return_value=changed_stat) as restat:
                with self.assertRaises(module.UnsafeEntryError) as raised:
                    module._verify_posix_package(state)

        self.assertEqual("identity_changed", raised.exception.code)
        restat.assert_called_once_with(
            "SKILL.md", dir_fd=10, follow_symlinks=False
        )

    def test_posix_verification_restats_children_and_files_before_root(self):
        module = load_module()
        root_stat = posix_metadata()
        child_stat = posix_metadata(inode=2)
        file_stat = posix_metadata(inode=3, mode=stat.S_IFREG, size=4)
        state = module._new_state([])
        state["posix_files"] = [
            {
                "fd": 12,
                "parent_fd": 11,
                "name": "SKILL.md",
                "initial": module._posix_snapshot(file_stat),
            }
        ]
        state["posix_directories"] = [
            {
                "fd": 10,
                "parent_fd": None,
                "name": None,
                "initial": module._posix_snapshot(root_stat),
                "names": ("child",),
            },
            {
                "fd": 11,
                "parent_fd": 10,
                "name": "child",
                "initial": module._posix_snapshot(child_stat),
                "names": ("SKILL.md",),
            },
        ]
        metadata = {10: root_stat, 11: child_stat, 12: file_stat}
        events = []

        def fstat(descriptor):
            events.append(("fstat", descriptor))
            return metadata[descriptor]

        def restat(name, *, dir_fd, follow_symlinks):
            events.append(("stat", dir_fd, name, follow_symlinks))
            return child_stat if name == "child" else file_stat

        def scan(descriptor):
            events.append(("scandir", descriptor))
            names = ("child",) if descriptor == 10 else ("SKILL.md",)
            return scan_names(*names)

        with mock.patch.object(module.os, "fstat", side_effect=fstat):
            with mock.patch.object(module.os, "stat", side_effect=restat):
                with mock.patch.object(module.os, "scandir", side_effect=scan):
                    module._verify_posix_package(state)

        self.assertEqual(
            [
                ("fstat", 12),
                ("stat", 11, "SKILL.md", False),
                ("fstat", 11),
                ("stat", 10, "child", False),
                ("scandir", 11),
                ("fstat", 10),
                ("scandir", 10),
            ],
            events,
        )

    @unittest.skipUnless(os.name == "nt", "Windows-only root handle logic")
    def test_windows_root_registration_base_exception_closes_new_handle(self):
        module = load_module()
        directory_info = {
            "attributes": module._FILE_ATTRIBUTE_DIRECTORY,
            "size": 0,
            "links": 1,
            "identity": 1,
            "write_time": 1,
        }
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(module, "_windows_drive_type", return_value=3))
            stack.enter_context(mock.patch.object(module, "_windows_open_handle", return_value=101))
            stack.enter_context(mock.patch.object(module, "_windows_info", return_value=directory_info))
            stack.enter_context(
                mock.patch.object(module, "_append_resource", side_effect=KeyboardInterrupt)
            )
            close = stack.enter_context(mock.patch.object(module, "_windows_close_handle"))
            with self.assertRaises(KeyboardInterrupt):
                module._open_windows_root(Path("C:" + "\\safe"))

        close.assert_called_once_with(101)

    def test_posix_root_registration_base_exception_closes_new_fd(self):
        module = load_module()
        with posix_root_environment(module, [10]):
            with mock.patch.object(module.os, "close") as close:
                with mock.patch.object(
                    module, "_append_resource", side_effect=KeyboardInterrupt
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        module._open_posix_root(Path("ignored"))

        close.assert_called_once_with(10)

    def test_linux_missing_openat2_fails_closed_and_closes_root_chain(self):
        module = load_module()
        metadata = posix_metadata(device=7)
        with posix_root_environment(module, [10, 11], metadata):
            with mock.patch.object(
                module, "_linux_openat2", side_effect=OSError(errno.ENOSYS, "missing")
            ):
                with mock.patch.object(module.os, "close") as close:
                    with self.assertRaises(module.UnsafeEntryError) as raised:
                        module._open_posix_root(Path("ignored"))

        self.assertEqual("unsupported_secure_traversal", raised.exception.code)
        self.assertEqual([mock.call(10)], close.call_args_list)

    def test_posix_root_preserves_unsupported_openat2_classification(self):
        module = load_module()
        metadata = posix_metadata()
        for prepared in (PurePosixPath("/" + "safe"), PurePosixPath("/")):
            with self.subTest(prepared=prepared):
                with posix_root_environment(
                    module, [10], metadata, prepared=prepared
                ):
                    with mock.patch.object(
                        module,
                        "_linux_openat2",
                        side_effect=module.UnsafeEntryError(
                            "unsupported_secure_traversal"
                        ),
                    ):
                        with self.assertRaises(module.UnsafeEntryError) as raised:
                            module._open_posix_root(Path("ignored"))

                self.assertEqual(
                    "unsupported_secure_traversal", raised.exception.code
                )

    def test_linux_openat2_uses_audited_syscall_and_no_xdev_resolve_flags(self):
        module = load_module()

        class FakeSyscall:
            restype = None

            def __init__(self):
                self.args = None

            def __call__(self, *args):
                self.args = args
                return 55

        syscall = FakeSyscall()
        libc = SimpleNamespace(syscall=syscall)
        with mock.patch.object(
            module.os, "uname", return_value=SimpleNamespace(machine="x86_64"), create=True
        ):
            with mock.patch.object(module.ctypes, "CDLL", return_value=libc):
                descriptor = module._linux_openat2(10, "child", 0x1234)

        self.assertEqual(55, descriptor)
        self.assertEqual(module._SYS_OPENAT2, syscall.args[0].value)
        self.assertEqual(10, syscall.args[1].value)
        self.assertEqual(b"child", syscall.args[2].value)
        how = syscall.args[3]._obj
        self.assertEqual(0x1234, how.flags)
        self.assertEqual(
            module._RESOLVE_NO_XDEV
            | module._RESOLVE_NO_MAGICLINKS
            | module._RESOLVE_NO_SYMLINKS
            | module._RESOLVE_BENEATH,
            how.resolve,
        )

    def test_linux_openat2_unknown_architecture_fails_closed_before_syscall(self):
        module = load_module()
        with mock.patch.object(
            module.os, "uname", return_value=SimpleNamespace(machine="unknown"), create=True
        ):
            with mock.patch.object(module.ctypes, "CDLL", side_effect=AssertionError):
                with self.assertRaises(module.UnsafeEntryError) as raised:
                    module._linux_openat2(10, "child", 0)

        self.assertEqual("unsupported_secure_traversal", raised.exception.code)

    def test_linux_openat2_preserves_errno_without_echoing_entry_name(self):
        module = load_module()
        syscall = mock.MagicMock(return_value=-1)
        libc = SimpleNamespace(syscall=syscall)
        with mock.patch.object(
            module.os, "uname", return_value=SimpleNamespace(machine="x86_64"), create=True
        ):
            with mock.patch.object(module.ctypes, "CDLL", return_value=libc):
                with mock.patch.object(module.ctypes, "get_errno", return_value=errno.EXDEV):
                    with self.assertRaises(OSError) as raised:
                        module._linux_openat2(10, "private-entry", 0)

        self.assertEqual(errno.EXDEV, raised.exception.errno)
        self.assertNotIn("private-entry", str(raised.exception))

    def test_linux_root_chain_uses_openat2_and_records_parent_bindings(self):
        module = load_module()
        metadata = posix_metadata()
        prepared = PurePosixPath("/" + "safe/skill")
        with posix_root_environment(module, [10], metadata, prepared=prepared):
            with mock.patch.object(
                module, "_linux_openat2", side_effect=[11, 12]
            ) as openat2:
                opened = module._open_posix_root(Path("ignored"))

        self.assertEqual([10, 11], opened["ancestors"])
        self.assertEqual(12, opened["handle"])
        self.assertEqual(1, opened["device"])
        self.assertEqual(
            [(None, None, 10), (10, "safe", 11), (11, "skill", 12)],
            [
                (item["parent_fd"], item["name"], item["fd"])
                for item in opened["root_chain"]
            ],
        )
        self.assertEqual(
            [mock.call(10, "safe", mock.ANY), mock.call(11, "skill", mock.ANY)],
            openat2.call_args_list,
        )

    def test_non_linux_posix_root_fails_closed_before_filesystem_open(self):
        module = load_module()
        enable_posix_flags(self, module)
        supports_everything = mock.MagicMock()
        supports_everything.__contains__.return_value = True
        with mock.patch.object(module.sys, "platform", "darwin"):
            with mock.patch.object(module.os, "supports_dir_fd", supports_everything):
                with mock.patch.object(module.os, "supports_fd", supports_everything):
                    with mock.patch.object(module.os, "open", side_effect=AssertionError):
                        with self.assertRaises(module.UnsafeEntryError) as raised:
                            module._open_posix_root(Path("ignored"))

        self.assertEqual("unsupported_secure_traversal", raised.exception.code)

    def test_posix_root_chain_verification_is_deepest_first_and_detects_swap(self):
        module = load_module()
        initial = posix_metadata()
        swapped = posix_metadata(inode=99)
        binding = (initial.st_dev, initial.st_ino, initial.st_mode, initial.st_nlink)
        opened = {
            "root_chain": [
                {"fd": 10, "parent_fd": None, "name": None, "initial": binding},
                {"fd": 11, "parent_fd": 10, "name": "safe", "initial": binding},
                {"fd": 12, "parent_fd": 11, "name": "skill", "initial": binding},
            ]
        }
        events = []

        def fstat(descriptor):
            events.append(("fstat", descriptor))
            return initial

        def restat(name, *, dir_fd, follow_symlinks):
            events.append(("stat", dir_fd, name, follow_symlinks))
            return swapped if name == "safe" else initial

        with mock.patch.object(module.os, "fstat", side_effect=fstat):
            with mock.patch.object(module.os, "stat", side_effect=restat):
                with self.assertRaises(module.UnsafeEntryError):
                    module._verify_posix_root_chain(opened)

        self.assertEqual(
            [("fstat", 11), ("stat", 10, "safe", False)], events
        )

    def test_posix_regular_reopen_is_nonblocking_and_rejects_type_link_or_mode_change(self):
        module = load_module()
        enable_posix_flags(self, module)
        before = posix_metadata(mode=stat.S_IFREG | 0o644, inode=2)
        changed = (
            posix_metadata(mode=stat.S_IFIFO | 0o644, inode=2),
            posix_metadata(mode=stat.S_IFREG | 0o644, inode=2, links=2),
            posix_metadata(mode=stat.S_IFREG | 0o600, inode=2),
        )
        for opened in changed:
            with self.subTest(mode=opened.st_mode, links=opened.st_nlink):
                state = module._new_state([])
                state["posix_root_dev"] = 1
                flags = []

                def open_child(name, value, parent_fd):
                    del name, parent_fd
                    flags.append(value)
                    return 11

                with ExitStack() as stack:
                    stack.enter_context(
                        mock.patch.object(module.os, "scandir", return_value=scan_names("file"))
                    )
                    stack.enter_context(
                        mock.patch.object(module.os, "fstat", side_effect=[posix_metadata(), opened])
                    )
                    stack.enter_context(
                        mock.patch.object(module, "_posix_entry_metadata", return_value=before)
                    )
                    stack.enter_context(
                        mock.patch.object(module, "_posix_open_child", side_effect=open_child)
                    )
                    close = stack.enter_context(mock.patch.object(module.os, "close"))
                    stack.enter_context(
                        mock.patch.object(module, "_read_open_file", side_effect=AssertionError)
                    )
                    with self.assertRaises(module.UnsafeEntryError):
                        module._walk_posix(10, PurePosixPath(), 0, state)

                self.assertTrue(flags[0] & module.os.O_NONBLOCK)
                if hasattr(module.os, "O_NOCTTY"):
                    self.assertTrue(flags[0] & module.os.O_NOCTTY)
                close.assert_called_once_with(11)

    def test_posix_snapshot_retains_mode_and_link_count(self):
        module = load_module()
        original = posix_metadata(mode=stat.S_IFREG | 0o644, links=1)
        self.assertNotEqual(
            module._posix_snapshot(original),
            module._posix_snapshot(posix_metadata(mode=stat.S_IFREG | 0o600, links=1)),
        )
        self.assertNotEqual(
            module._posix_snapshot(original),
            module._posix_snapshot(posix_metadata(mode=stat.S_IFREG | 0o644, links=2)),
        )

    def test_windows_extended_device_names_are_rejected_before_filesystem_and_at_entry_gate(self):
        module = load_module()
        backslash = "\\"
        samples = ("COM¹", "lpt².txt", "COM³.log", "CONIN$", "conout$.txt")
        for sample in samples:
            with self.subTest(sample=sample):
                with mock.patch.object(module.os.path, "abspath", side_effect=AssertionError):
                    with self.assertRaises(module.UnsafeEntryError):
                        module._prepare_root_path(
                            Path("C:" + backslash + "safe") / sample
                        )
                with mock.patch.object(module.os, "name", "nt"):
                    self.assertFalse(module._safe_entry_name(sample))

    def test_posix_root_probe_obeys_handle_budget_before_openat2(self):
        module = load_module()
        metadata = posix_metadata()
        with posix_root_environment(
            module, [10], metadata, prepared=PurePosixPath("/")
        ):
            with mock.patch.object(module, "MAX_FILES", 1):
                with mock.patch.object(module, "_linux_openat2") as probe:
                    with mock.patch.object(module.os, "close") as close:
                        with self.assertRaises(module.ResourceLimitError):
                            module._open_posix_root(Path("ignored"))

        probe.assert_not_called()
        close.assert_called_once_with(10)

    def test_close_posix_root_attempts_each_fd_after_one_close_error(self):
        module = load_module()
        root = {"handle": 12, "ancestors": [10, 11]}
        with mock.patch.object(
            module.os, "close", side_effect=[OSError("simulated"), None, None]
        ) as close:
            module._close_posix_root(root)

        self.assertEqual([mock.call(12), mock.call(11), mock.call(10)], close.call_args_list)

    def test_windows_handle_to_fd_registration_failure_closes_fd_and_rolls_back(self):
        module = load_module()
        state = module._new_state([])
        state["windows_fds"] = ExplodingList()
        directory_info = {
            "attributes": module._FILE_ATTRIBUTE_DIRECTORY,
            "size": 0,
            "links": 1,
            "identity": 10,
            "write_time": 1,
        }
        file_info = {
            "attributes": 0,
            "size": 1,
            "links": 1,
            "identity": 11,
            "write_time": 1,
        }
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(module.os, "scandir", return_value=scan_names("SKILL.md"))
            )
            stack.enter_context(
                mock.patch.object(module, "_windows_info", side_effect=[directory_info, file_info])
            )
            stack.enter_context(mock.patch.object(module, "_windows_open_handle", return_value=11))
            stack.enter_context(mock.patch.object(module, "_windows_handle_to_fd", return_value=12))
            close_fd = stack.enter_context(mock.patch.object(module.os, "close"))
            close_handle = stack.enter_context(mock.patch.object(module, "_windows_close_handle"))
            with self.assertRaises(MemoryError):
                module._walk_windows(
                    {"path": Path("C:" + "\\safe"), "handle": 10},
                    PurePosixPath(),
                    0,
                    state,
                )

        close_fd.assert_called_once_with(12)
        close_handle.assert_not_called()
        self.assertEqual(0, state["open_count"])

    def test_posix_child_registration_failure_closes_fd_and_rolls_back(self):
        module = load_module()
        enable_posix_flags(self, module)

        for mode in (stat.S_IFDIR, stat.S_IFREG):
            with self.subTest(mode=mode):
                state = module._new_state([])
                state["posix_root_dev"] = 1
                state["posix_fds"] = ExplodingList()
                root_stat = posix_metadata()
                child_stat = posix_metadata(inode=2, mode=mode)
                with ExitStack() as stack:
                    stack.enter_context(mock.patch.object(module.sys, "platform", "darwin"))
                    stack.enter_context(
                        mock.patch.object(module.os, "scandir", return_value=scan_names("child"))
                    )
                    stack.enter_context(
                        mock.patch.object(module.os, "fstat", side_effect=[root_stat, child_stat])
                    )
                    stack.enter_context(mock.patch.object(module.os, "stat", return_value=child_stat))
                    stack.enter_context(mock.patch.object(module, "_posix_open_child", return_value=11))
                    close = stack.enter_context(mock.patch.object(module.os, "close"))
                    with self.assertRaises(MemoryError):
                        module._walk_posix(10, PurePosixPath(), 0, state)

                close.assert_called_once_with(11)
                self.assertEqual(0, state["open_count"])

    def test_resources_remain_open_until_package_verification(self):
        module = load_module()
        verifier_name = (
            "_verify_windows_package" if os.name == "nt" else "_verify_posix_package"
        )
        self.assertTrue(hasattr(module, verifier_name))
        original = getattr(module, verifier_name)
        observed = []

        def verify_while_open(state):
            records = (
                state["windows_files"] if os.name == "nt" else state["posix_files"]
            )
            observed.extend(os.fstat(record["fd"]).st_size for record in records)
            return original(state)

        with mock.patch.object(module, verifier_name, verify_while_open):
            report = module.inspect_skill(SAFE, None, None)

        self.assertTrue(report["valid_skill"])
        self.assertTrue(observed)

    def test_windows_remote_drive_is_rejected_before_open(self):
        module = load_module()
        with mock.patch.object(module, "_windows_drive_type", return_value=4):
            with mock.patch.object(module, "_windows_open_handle", side_effect=AssertionError):
                with self.assertRaises(module.UnsafeEntryError):
                    module._open_windows_root(Path("C:" + "\\" + "safe"))

    @unittest.skipUnless(os.name == "nt", "Windows-only root handle logic")
    def test_root_component_handles_obey_max_files_before_open(self):
        module = load_module()
        directory_info = {
            "attributes": module._FILE_ATTRIBUTE_DIRECTORY,
            "size": 0,
            "links": 1,
            "identity": 1,
            "write_time": 1,
        }
        with mock.patch.object(module, "MAX_FILES", 1):
            with mock.patch.object(module, "_windows_drive_type", return_value=3):
                with mock.patch.object(module, "_windows_open_handle", return_value=101) as open_handle:
                    with mock.patch.object(module, "_windows_info", return_value=directory_info):
                        with mock.patch.object(module, "_windows_close_handle"):
                            with self.assertRaises(module.ResourceLimitError):
                                module._open_windows_root(
                                    Path("C:" + "\\" + "one" + "\\" + "two")
                                )

        open_handle.assert_not_called()

    def test_handle_budget_counts_root_and_package_handles_together(self):
        module = load_module()
        self.assertTrue(hasattr(module, "_reserve_handle"))
        state = module._new_state([])
        state["open_count"] = 2

        with mock.patch.object(module, "MAX_FILES", 2):
            with self.assertRaises(module.ResourceLimitError):
                module._reserve_handle(state)

    def test_unknown_platform_has_fixed_blocking_risk(self):
        module = load_module()
        with mock.patch.object(module.os, "name", "unsupported"):
            report = module.inspect_skill(SAFE, None, None)

        self.assertFalse(report["valid_skill"])
        self.assertEqual(
            [{"code": "unsupported_secure_traversal", "path": "."}],
            report["risks"],
        )

    def test_safe_source_and_immutable_revision_are_preserved(self):
        module = load_module()
        source = "https://example.test/fetched/skill"
        revision = "abc123"

        report = module.inspect_skill(SAFE, source, revision)

        self.assertTrue(report["valid_skill"])
        self.assertEqual(source, report["source"])
        self.assertEqual(revision, report["revision"])

    def test_unsafe_metadata_is_null_and_never_echoed(self):
        module = load_module()
        token = synthetic_token()
        source = "https://example.test/skill?access=" + token

        report = module.inspect_skill(SAFE, source, token)
        serialized = json.dumps(report, sort_keys=True)

        self.assertIsNone(report["source"])
        self.assertIsNone(report["revision"])
        self.assertFalse(report["valid_skill"])
        self.assertEqual(
            {("unsafe_revision", "revision"), ("unsafe_source", "source")},
            {(item["code"], item["path"]) for item in report["risks"]},
        )
        self.assertNotIn(token, serialized)
        self.assertNotIn(source, serialized)

    def test_unsafe_metadata_cli_never_echoes_input(self):
        token = synthetic_token("E")
        source = "https://example.test/skill?access=" + token

        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(SAFE),
                "--source",
                source,
                "--revision",
                token,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(1, completed.returncode)
        self.assertNotIn(token, completed.stdout + completed.stderr)
        self.assertNotIn(source, completed.stdout + completed.stderr)
        report = json.loads(completed.stdout)
        self.assertIsNone(report["source"])
        self.assertIsNone(report["revision"])

    def test_source_allowlist_rejects_non_https_userinfo_query_fragment_and_local_paths(self):
        module = load_module()
        token = synthetic_token("F")
        slash = "/"
        samples = (
            "http" + ":" + slash * 2 + "example.test/skill",
            "https"
            + ":"
            + slash * 2
            + "user"
            + ":"
            + "pass"
            + "@"
            + "example.test/skill",
            "https" + ":" + slash * 2 + "example.test/skill?ref=main",
            "https" + ":" + slash * 2 + "example.test/skill#main",
            "file" + ":" + slash * 3 + "home/private/skill",
            "https" + ":" + slash * 2 + "example.test/" + token,
        )

        for source in samples:
            with self.subTest(index=samples.index(source)):
                report = module.inspect_skill(SAFE, source, "abc123")
                self.assertIsNone(report["source"])
                self.assertIn(
                    "unsafe_source", {item["code"] for item in report["risks"]}
                )
                self.assertNotIn(source, json.dumps(report, sort_keys=True))

    def test_relative_path_safety_reuses_export_content_rules(self):
        module = load_module()
        token = synthetic_token("G")
        unsafe = (
            "notes/" + token + ".txt",
            "notes/" + quote(token, safe="") + ".txt",
            "notes/"
            + base64.b64encode(token.encode("utf-8")).decode("ascii")
            + ".txt",
            "C:" + "\\" + "Users" + "\\" + "private" + "\\skill.md",
            "/" + "home/private/skill.md",
            "owner-" + "person" + "@" + "example.test",
            ".." + "/" + "outside.txt",
        )

        for relative in unsafe:
            with self.subTest(index=unsafe.index(relative)):
                self.assertFalse(module._safe_relative_path(relative))

    def test_sensitive_filename_uses_ordinal_and_never_affects_tree_hash(self):
        module = load_module()
        reports = []
        tokens = (synthetic_token("A"), synthetic_token("B"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            for token in tokens:
                path = root / ("note-" + token + ".txt")
                path.write_text("same safe content", encoding="utf-8")
                reports.append(module.inspect_skill(root, None, None))
                path.unlink()

        for token, report in zip(tokens, reports):
            serialized = json.dumps(report, sort_keys=True)
            self.assertFalse(report["valid_skill"])
            self.assertNotIn(token, serialized)
            self.assertIn(
                "sensitive_path", {item["code"] for item in report["risks"]}
            )
            self.assertTrue(any(item["path"].startswith("entry=") for item in report["files"]))
        self.assertEqual(reports[0]["tree_hash"], reports[1]["tree_hash"])

    def test_sensitive_file_and_frontmatter_content_are_not_hashed_or_echoed(self):
        module = load_module()
        reports = []
        tokens = (synthetic_token("C"), synthetic_token("D"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            for token in tokens:
                write_skill(
                    root,
                    "---\nname: temporary-skill\n"
                    "description: Use when " + token + ".\n---\n",
                )
                (root / "notes.txt").write_text(token, encoding="utf-8")
                reports.append(module.inspect_skill(root, None, None))

        for token, report in zip(tokens, reports):
            serialized = json.dumps(report, sort_keys=True)
            self.assertFalse(report["valid_skill"])
            self.assertEqual({}, report["frontmatter"])
            self.assertNotIn(token, serialized)
            self.assertIn(
                "sensitive_content", {item["code"] for item in report["risks"]}
            )
            affected = {
                item["path"]: item for item in report["files"]
                if item["path"] in {"SKILL.md", "notes.txt"}
            }
            self.assertIsNone(affected["SKILL.md"]["sha256"])
            self.assertIsNone(affected["notes.txt"]["sha256"])
        self.assertEqual(reports[0]["tree_hash"], reports[1]["tree_hash"])

    def test_sensitive_shebang_cannot_change_manifest_or_tree_hash(self):
        module = load_module()
        token = synthetic_token("J")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            payload = root / "runner"
            payload.write_text(token, encoding="utf-8")
            plain = module.inspect_skill(root, None, None)
            payload.write_text("#!/bin/sh\n" + token, encoding="utf-8")
            shebang = module.inspect_skill(root, None, None)

        plain_record = next(item for item in plain["files"] if item["path"] == "runner")
        shebang_record = next(item for item in shebang["files"] if item["path"] == "runner")
        self.assertEqual(plain_record, shebang_record)
        self.assertEqual(plain["tree_hash"], shebang["tree_hash"])

    def test_sensitive_binary_marker_cannot_change_report_risks(self):
        module = load_module()
        token = synthetic_token("L").encode("utf-8")
        reports = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            payload = root / "notes.bin"
            for suffix in (b"A", b"\x00"):
                payload.write_bytes(token + suffix)
                reports.append(module.inspect_skill(root, None, None))

        self.assertEqual(reports[0]["files"], reports[1]["files"])
        self.assertEqual(reports[0]["tree_hash"], reports[1]["tree_hash"])
        self.assertEqual(reports[0]["risks"], reports[1]["risks"])
        self.assertNotIn("binary_content", {item["code"] for item in reports[1]["risks"]})

    def test_windows_stability_includes_attributes_and_link_count(self):
        module = load_module()
        original = {
            "attributes": module._FILE_ATTRIBUTE_DIRECTORY,
            "size": 0,
            "links": 1,
            "identity": 10,
            "write_time": 20,
        }

        changed_links = dict(original, links=2)
        changed_attributes = dict(
            original,
            attributes=module._FILE_ATTRIBUTE_DIRECTORY
            | module._FILE_ATTRIBUTE_REPARSE_POINT,
        )

        self.assertFalse(module._windows_stable(original, changed_links))
        self.assertFalse(module._windows_stable(original, changed_attributes))

    def test_file_identity_mismatch_is_rejected(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skill"
            write_skill(root)
            path = root / "SKILL.md"
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                with self.assertRaises(module.UnsafeEntryError):
                    module._read_open_file(
                        descriptor,
                        path.stat().st_size,
                        "SKILL.md",
                        0,
                        lambda: False,
                    )
            finally:
                os.close(descriptor)

    @unittest.skipUnless(os.name == "nt", "Windows-only root handle logic")
    def test_windows_parent_reparse_handle_is_rejected_and_closed(self):
        module = load_module()
        directory = module._FILE_ATTRIBUTE_DIRECTORY
        reparse = module._FILE_ATTRIBUTE_REPARSE_POINT

        def info(handle):
            return {
                "attributes": directory | (reparse if handle == 102 else 0),
                "size": 0,
                "links": 1,
                "identity": handle,
                "write_time": 0,
            }

        with mock.patch.object(module, "_windows_drive_type", return_value=3):
            with mock.patch.object(module, "_windows_open_handle", side_effect=[101, 102]):
                with mock.patch.object(module, "_windows_info", side_effect=info):
                    with mock.patch.object(module, "_windows_close_handle") as close:
                        with self.assertRaises(module.UnsafeEntryError):
                            module._open_windows_root(Path("C:" + "\\" + "parent\\skill"))

        self.assertEqual([mock.call(102), mock.call(101)], close.call_args_list)

    def test_root_traversal_and_parent_reparse_are_rejected(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            root = base / "parent" / "skill"
            write_skill(root)

            traversal = root / ".." / "skill"
            traversal_report = module.inspect_skill(traversal, None, None)
            self.assertFalse(traversal_report["valid_skill"])
            self.assertEqual(
                ["unsafe_root"],
                [item["code"] for item in traversal_report["risks"]],
            )

    def test_cli_returns_json_and_exit_codes_zero_one_two_without_echo(self):
        valid = subprocess.run(
            [sys.executable, str(SCRIPT), str(SAFE), "--revision", "abc123"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        invalid = subprocess.run(
            [sys.executable, str(SCRIPT), str(SAFE / "missing")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        sensitive = "--" + "api" + "-key=" + ("synthetic" * 4)
        usage = subprocess.run(
            [sys.executable, str(SCRIPT), str(SAFE), sensitive],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, valid.returncode)
        self.assertTrue(json.loads(valid.stdout)["valid_skill"])
        self.assertEqual(1, invalid.returncode)
        self.assertFalse(json.loads(invalid.stdout)["valid_skill"])
        self.assertEqual(2, usage.returncode)
        self.assertNotIn(sensitive, usage.stdout + usage.stderr)
        self.assertEqual("usage_error", json.loads(usage.stderr)["error"])

    def test_windows_py_launcher_can_run_the_cli(self):
        if os.name != "nt" or shutil.which("py") is None:
            self.skipTest("Windows py launcher unavailable")

        completed = subprocess.run(
            ["py", str(SCRIPT), str(SAFE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode)
        self.assertTrue(json.loads(completed.stdout)["valid_skill"])


if __name__ == "__main__":
    unittest.main()
