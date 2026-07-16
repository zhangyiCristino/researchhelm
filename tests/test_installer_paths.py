import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = ROOT / "skills" / "researchhelm" / "SKILL.md"
PINNED_PACKAGE = "skills@1.5.16"
REPOSITORY = "zhangyiCristino/researchhelm"
PROJECT_TARGETS = (
    "universal",
    "cursor",
    "gemini-cli",
    "opencode",
    "github-copilot",
    "cline",
    "roo",
    "windsurf",
    "pi",
)
COPIED_SOURCE_KEYS = ("PATH", "CI", "NO_COLOR")
GENERATED_ENV_KEYS = {
    "HOME",
    "USERPROFILE",
    "TMP",
    "TEMP",
    "TMPDIR",
    "npm_config_cache",
    "npm_config_userconfig",
    "npm_config_globalconfig",
    "npm_config_prefix",
    "npm_config_yes",
}


def build_isolated_environment(root: Path, source_get=os.environ.get):
    home = root / "home"
    work = root / "work"
    temp = root / "temp"
    cache = root / "npm-cache"
    prefix = root / "npm-prefix"
    config = root / "npm-config"
    for directory in (home, work, temp, cache, prefix, config):
        directory.mkdir(parents=True, exist_ok=True)
    user_config = config / "user.npmrc"
    global_config = config / "global.npmrc"
    user_config.write_text("", encoding="utf-8")
    global_config.write_text("", encoding="utf-8")
    (home / ".gitconfig").write_text("", encoding="utf-8")

    environment = {}
    source_keys = COPIED_SOURCE_KEYS
    if os.name == "nt":
        source_keys += ("SystemRoot",)
    for key in source_keys:
        value = source_get(key)
        if value:
            environment[key] = value
    redirected = {
        "HOME": home,
        "USERPROFILE": home,
        "TMP": temp,
        "TEMP": temp,
        "TMPDIR": temp,
        "npm_config_cache": cache,
        "npm_config_userconfig": user_config,
        "npm_config_globalconfig": global_config,
        "npm_config_prefix": prefix,
        "npm_config_yes": "true",
    }
    environment.update({key: str(value) for key, value in redirected.items()})
    return environment, work


def find_in_path(name: str, path_value: str, suffixes: tuple[str, ...]):
    for raw_directory in path_value.split(os.pathsep):
        if not raw_directory:
            continue
        directory = Path(raw_directory)
        for suffix in suffixes:
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def resolve_npx_launcher(path_value: str, *, windows: bool):
    suffixes = (".exe", ".cmd", ".bat", "") if windows else ("",)
    executable = find_in_path("npx", path_value, suffixes)
    if executable is None:
        return None
    if not windows:
        return [str(executable)]

    install_root = executable.parent
    node = install_root / "node.exe"
    cli = install_root / "node_modules" / "npm" / "bin" / "npx-cli.js"
    if not node.is_file() or not cli.is_file():
        return None
    return [str(node), str(cli)]


class InstallerEnvironmentContractTests(unittest.TestCase):
    def test_subprocess_environment_copies_only_the_explicit_allowlist(self):
        source = {
            "PATH": "allowlisted-path",
            "CI": "true",
            "NO_COLOR": "1",
            "UNLISTED_VALUE": "must-not-copy",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            environment, work = build_isolated_environment(
                root, source_get=source.get
            )
            self.assertEqual(
                set(COPIED_SOURCE_KEYS) | GENERATED_ENV_KEYS,
                set(environment),
            )
            self.assertTrue(work.is_relative_to(root))
            for key in GENERATED_ENV_KEYS - {"npm_config_yes"}:
                self.assertTrue(Path(environment[key]).is_relative_to(root))

    def test_executable_resolution_uses_only_the_passed_path(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            executable = directory / "npx.cmd"
            executable.write_text("", encoding="utf-8")
            self.assertEqual(
                executable,
                find_in_path("npx", str(directory), (".cmd", "")),
            )

    @unittest.skipUnless(os.name == "nt", "Windows-only runtime environment")
    def test_windows_copies_only_systemroot_as_platform_runtime_state(self):
        windows_root = "C:" + "\\" + "Windows"
        source = {
            "PATH": "allowlisted-path",
            "CI": "true",
            "NO_COLOR": "1",
            "SystemRoot": windows_root,
            "ComSpec": windows_root + "\\" + "System32\\cmd.exe",
            "WINDIR": windows_root,
            "SYSTEMDRIVE": "C:",
            "UNLISTED_VALUE": "must-not-copy",
        }
        requested = []

        def source_get(key):
            requested.append(key)
            return source.get(key)

        with tempfile.TemporaryDirectory() as raw:
            environment, _ = build_isolated_environment(
                Path(raw), source_get=source_get
            )

        self.assertEqual(windows_root, environment.get("SystemRoot"))
        self.assertEqual(
            {"PATH", "CI", "NO_COLOR", "SystemRoot"},
            set(requested),
        )
        for key in ("ComSpec", "WINDIR", "SYSTEMDRIVE", "UNLISTED_VALUE"):
            self.assertNotIn(key, environment)

    @unittest.skipUnless(os.name == "nt", "Windows-only npx launcher")
    def test_windows_launcher_uses_node_and_cli_from_resolved_npx_root(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            install = root / "node-install"
            other = root / "other"
            cli = install / "node_modules" / "npm" / "bin" / "npx-cli.js"
            cli.parent.mkdir(parents=True)
            other.mkdir()
            npx = install / "npx.cmd"
            node = install / "node.exe"
            npx.write_text("", encoding="utf-8")
            node.write_text("", encoding="utf-8")
            cli.write_text("", encoding="utf-8")
            (other / "node.exe").write_text("", encoding="utf-8")

            command = resolve_npx_launcher(
                os.pathsep.join((str(install), str(other))), windows=True
            )

            self.assertEqual([str(node), str(cli)], command)

    @unittest.skipUnless(os.name == "nt", "Windows-only npx launcher")
    def test_windows_launcher_rejects_missing_fixed_relative_cli(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "npx.cmd").write_text("", encoding="utf-8")
            (root / "node.exe").write_text("", encoding="utf-8")

            self.assertIsNone(resolve_npx_launcher(str(root), windows=True))

    @unittest.skipUnless(os.name == "nt", "Windows-only npx launcher")
    def test_windows_launcher_never_executes_npx_executable_directly(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cli = root / "node_modules" / "npm" / "bin" / "npx-cli.js"
            cli.parent.mkdir(parents=True)
            npx = root / "npx.exe"
            node = root / "node.exe"
            npx.write_text("", encoding="utf-8")
            node.write_text("", encoding="utf-8")
            cli.write_text("", encoding="utf-8")

            self.assertTrue(
                resolve_npx_launcher(str(root), windows=True)
                == [str(node), str(cli)],
                "Windows launcher did not use the fixed direct-node pair",
            )


@unittest.skipUnless(
    os.environ.get("RUN_INSTALLER_TESTS") == "1",
    "installer tests are opt-in",
)
class InstallerPathTests(unittest.TestCase):
    def setUp(self):
        self.outer = tempfile.TemporaryDirectory()
        self.outer_path = Path(self.outer.name)
        self.sandbox = self.outer_path / "sandbox"
        self.sandbox.mkdir()
        self.sentinel = self.outer_path / "outside-sentinel.txt"
        self.sentinel.write_text("unchanged", encoding="utf-8")
        self.expected_hash = hashlib.sha256(
            CANONICAL_SKILL.read_bytes()
        ).hexdigest()

    def tearDown(self):
        self.outer.cleanup()

    def _layout(self, name):
        root = self.sandbox / name
        environment, work = build_isolated_environment(root)
        path_value = environment.get("PATH", "")
        prefix = resolve_npx_launcher(path_value, windows=os.name == "nt")
        self.assertIsNotNone(
            prefix, "npx launcher is unavailable on allowlisted PATH"
        )
        return root, environment, work, prefix

    def _run(self, command, environment, work):
        result = subprocess.run(
            command,
            cwd=work,
            env=environment,
            input="",
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        self.assertEqual(
            0,
            result.returncode,
            f"isolated installer command exited {result.returncode}",
        )
        self.assertEqual("unchanged", self.sentinel.read_text(encoding="utf-8"))
        self.assertEqual(
            {"sandbox", "outside-sentinel.txt"},
            {path.name for path in self.outer_path.iterdir()},
        )
        return result

    def _assert_installed_hash(self, root, work):
        home = root / "home"
        candidates = [
            path
            for base in (work, home)
            for path in base.rglob("SKILL.md")
            if path.parent.name == "researchhelm"
        ]
        self.assertTrue(candidates, "installed researchhelm SKILL.md not found")
        sandbox = self.sandbox.resolve(strict=True)
        for candidate in candidates:
            self.assertTrue(candidate.resolve(strict=True).is_relative_to(sandbox))
        hashes = {
            hashlib.sha256(candidate.read_bytes()).hexdigest()
            for candidate in candidates
        }
        self.assertIn(self.expected_hash, hashes)

    def _install(self, name, target, *, copy, global_scope=False):
        root, environment, work, prefix = self._layout(name)
        command = [
            *prefix,
            PINNED_PACKAGE,
            "add",
            REPOSITORY,
            "--skill",
            "researchhelm",
            "--agent",
            target,
        ]
        if copy:
            command.append("--copy")
        if global_scope:
            command.append("--global")
        command.append("-y")
        self._run(command, environment, work)
        self._assert_installed_hash(root, work)

    def test_isolated_launcher_reports_version(self):
        _, environment, work, prefix = self._layout("launcher")
        result = self._run([*prefix, "--version"], environment, work)
        version = result.stdout.strip()
        self.assertTrue(
            version and any(character.isdigit() for character in version),
            "isolated npx launcher did not return a version",
        )

    def test_project_copy_targets(self):
        for target in PROJECT_TARGETS:
            with self.subTest(target=target):
                self._install(f"copy-{target}", target, copy=True)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux-only symlink check")
    def test_linux_default_symlink_and_global_copy(self):
        self._install("symlink-universal", "universal", copy=False)
        self._install(
            "global-copy-universal",
            "universal",
            copy=True,
            global_scope=True,
        )

    def test_use_without_installation_references_canonical_skill(self):
        root, environment, work, prefix = self._layout("use")
        result = self._run(
            [
                *prefix,
                PINNED_PACKAGE,
                "use",
                REPOSITORY,
                "--skill",
                "researchhelm",
            ],
            environment,
            work,
        )
        output = result.stdout + result.stderr
        self.assertTrue(
            "researchhelm" in output.lower() and "SKILL.md" in output,
            "generated prompt did not reference the canonical skill",
        )


if __name__ == "__main__":
    unittest.main()
