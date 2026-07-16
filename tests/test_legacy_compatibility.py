import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README_FILES = (ROOT / "README.md", ROOT / "README.zh-CN.md")


class LegacyCompatibilityTests(unittest.TestCase):
    def test_claude_plugin_identity_matches_v3_rename(self):
        plugin = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        market = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("researchhelm", plugin["name"])
        self.assertEqual("researchhelm", market["name"])
        self.assertEqual("researchhelm", market["plugins"][0]["name"])
        self.assertEqual("./", market["plugins"][0]["source"])

    def test_v3_version_is_consistent(self):
        plugin = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        market = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("3.0.0", plugin["version"])
        self.assertEqual("3.0.0", market["plugins"][0]["version"])

    def test_every_readme_documents_the_legacy_identity_migration(self):
        commands = (
            "/plugin marketplace add zhangyiCristino/autoresearch-skill",
            "/plugin install autoresearch@autoresearch-skill",
            "git clone https://github.com/zhangyiCristino/autoresearch-skill.git",
            "cp -r autoresearch-skill/skills/autoresearch ~/.claude/skills/",
            "npx skills add zhangyiCristino/autoresearch-skill --skill autoresearch",
            "npx skills use zhangyiCristino/autoresearch-skill@autoresearch",
            "/autoresearch",
            "mv .autoresearch .researchhelm",
        )
        for path in README_FILES:
            text = path.read_text(encoding="utf-8")
            for command in commands:
                self.assertIn(command, text, f"{path.name}: {command}")

    def test_readmes_do_not_make_unproved_universal_claims(self):
        forbidden = (
            "works with every agent",
            "supports all agents",
            "absolutely secure",
            "zero risk",
            "first AI scientist",
            "best AI scientist",
            "only AI scientist",
            "兼容所有 Agent",
            "支持所有 Agent",
            "绝对安全",
            "零风险",
            "首个 AI 科学家",
            "最佳 AI 科学家",
            "唯一 AI 科学家",
        )
        for path in README_FILES:
            text = path.read_text(encoding="utf-8")
            for phrase in forbidden:
                self.assertNotIn(phrase, text)

    def test_readmes_are_utf8_and_do_not_contain_known_mojibake(self):
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("中文说明", english)
        for phrase in ("人主导科研", "安装路径已验证", "原生测试", "社区报告"):
            self.assertIn(phrase, chinese)
        for signal in ("涓", "鈫", "銆", "锛", "浣", "鐨"):
            self.assertNotIn(signal, english + chinese)

    def test_product_story_names_boundaries_and_third_party_installer(self):
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        for text in (english, chinese):
            self.assertIn(
                "npx skills add zhangyiCristino/researchhelm --skill researchhelm",
                text,
            )
            self.assertIn(
                "npx skills use zhangyiCristino/researchhelm@researchhelm",
                text,
            )
            self.assertIn("https://github.com/vercel-labs/skills", text)
            for label in (
                "Standard-validated",
                "Install-path verified",
                "Native-tested",
                "Portable-tested",
                "Community-reported",
            ):
                self.assertIn(label, text)
        self.assertIn("not an autonomous ai scientist", english.lower())
        self.assertIn("third-party community installer", english)
        self.assertIn("不是自主 AI 科学家", chinese)
        self.assertIn("第三方社区安装器", chinese)
        self.assertIn("安装路径已验证不等于原生支持", chinese)
        self.assertIn("社区报告不等于维护者独立复现", chinese)
        self.assertIn(
            "未获批准时拒绝越过人类决策门后安全退出", chinese
        )

    def test_security_policy_is_linked_without_exposing_contact_data(self):
        for path in README_FILES:
            self.assertIn("SECURITY.md", path.read_text(encoding="utf-8"))
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        for heading in (
            "# Security Policy",
            "## Supported Version",
            "## Credential and Privacy Boundary",
            "## Reporting a Vulnerability",
            "## Incident Response",
            "## Security Claims",
        ):
            self.assertIn(heading, policy)
        self.assertIn("GitHub Private Vulnerability Reporting", policy)
        self.assertNotIn("@gmail.com", policy)
        self.assertNotIn("@qq.com", policy)
        self.assertNotIn("@163.com", policy)


if __name__ == "__main__":
    unittest.main()
