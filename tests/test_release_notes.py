from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.release_notes import extract_notes, release_version, render_release_notes


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_exact_version_without_unreleased_or_older_content(self) -> None:
        changelog = """# 更新日志
## [Unreleased]
- 尚未发布
## [1.3.1] - 2026-10-16
### 修复
- 修复导出
## [1.3.0]
- 旧功能
"""
        self.assertEqual(extract_notes(changelog, "1.3.1"), "### 修复\n- 修复导出")

    def test_does_not_confuse_a_version_with_a_longer_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "found 0"):
            extract_notes("## [1.3.10]\n- 更新", "1.3.1")

    def test_ignores_headings_in_fenced_examples(self) -> None:
        changelog = "## [1.3.1]\n- 示例\n```md\n## [1.3.0]\n示例中的标题\n```\n## [1.3.0]\n- 真正的旧版本\n"
        notes = extract_notes(changelog, "1.3.1")
        self.assertIn("示例中的标题", notes)
        self.assertNotIn("真正的旧版本", notes)

    def test_duplicate_version_sections_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "found 2"):
            extract_notes("## [1.3.1]\n- A\n## [v1.3.1]\n- B\n", "1.3.1")

    def test_empty_description_is_rejected(self) -> None:
        for content in ("", "### 修复\n", "<!-- 待填写 -->"):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "no update description"):
                extract_notes(f"## [1.3.1]\n{content}\n## [1.3.0]\n- 旧版本", "1.3.1")

    def test_release_body_uses_matching_platform_package_names(self) -> None:
        body = render_release_notes("1.3.1", "- 修复导出")
        for suffix in ("windows-x64-setup.exe", "windows-x64-portable.zip", "linux-x86_64.run", "linux-x86_64.tar.gz"):
            self.assertIn(f"FicFrame-1.3.1-{suffix}", body)
        self.assertIn("- 修复导出", body)
        self.assertIn("SHA256SUMS", body)
        self.assertNotIn("1.3.0", body)


class ReleaseVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "ficframe").mkdir()
        (self.root / "pyproject.toml").write_text('[project]\nname = "ficframe"\nversion = "1.3.1"\n', encoding="utf-8")
        (self.root / "ficframe" / "__init__.py").write_text('__version__ = "1.3.1"\n', encoding="utf-8")
        (self.root / "uv.lock").write_text(
            'version = 1\n[[package]]\nname = "another-package"\nversion = "9.0.0"\n'
            '[[package]]\nname = "ficframe"\nversion = "1.3.1"\nsource = { editable = "." }\n',
            encoding="utf-8",
        )

    def test_checks_local_package_in_lockfile(self) -> None:
        self.assertEqual(release_version(self.root), "1.3.1")
        self.assertEqual(release_version(self.root, "1.3.1"), "1.3.1")

    def test_manual_version_must_match_and_omit_v(self) -> None:
        for requested in ("1.3.2", "v1.3.1"):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, "does not match"):
                release_version(self.root, requested)

    def test_inconsistent_version_is_rejected(self) -> None:
        (self.root / "ficframe" / "__init__.py").write_text('__version__ = "1.3.0"\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Version mismatch"):
            release_version(self.root)

    def test_missing_lockfile_package_is_rejected(self) -> None:
        (self.root / "uv.lock").write_text('version = 1\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Expected one ficframe package"):
            release_version(self.root)


if __name__ == "__main__":
    unittest.main()
