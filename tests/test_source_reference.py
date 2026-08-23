from __future__ import annotations

import unittest

from ficframe.source_reference import (
    build_description_source_ref,
    build_novel_source_ref,
    resolve_source_ref,
    source_ref_from_legacy,
)


class SourceReferenceTests(unittest.TestCase):
    def test_exact_reference_keeps_verified_coordinates(self) -> None:
        novel = "前文\n目标段落\n后文"
        start = novel.index("目标段落")
        reference = build_novel_source_ref(novel, start, start + len("目标段落"))

        resolved = resolve_source_ref(novel, reference)

        self.assertEqual(resolved["status"], "exact")
        self.assertEqual(resolved["quote"], "目标段落")
        self.assertEqual(novel[resolved["start"]:resolved["end"]], resolved["quote"])

    def test_context_anchors_relocate_repeated_quote(self) -> None:
        original = "甲前缀目标乙后缀\n丙前缀目标丁后缀"
        start = original.index("目标", original.index("丙前缀"))
        reference = build_novel_source_ref(original, start, start + len("目标"))
        changed = "新增内容\n" + original

        resolved = resolve_source_ref(changed, reference)

        self.assertEqual(resolved["status"], "relocated")
        self.assertEqual(changed[resolved["start"]:resolved["end"]], "目标")
        self.assertGreater(resolved["start"], start)

    def test_unresolved_reference_is_not_falsely_highlighted(self) -> None:
        resolved = resolve_source_ref("完全不同的正文", {"kind": "novel", "quote": "已删除段落"})

        self.assertEqual(resolved["status"], "unresolved")
        self.assertEqual(resolved["quote"], "已删除段落")

    def test_description_reference_is_distinct_from_novel(self) -> None:
        reference = build_description_source_ref("补一个雨夜转场")

        self.assertEqual(reference["kind"], "description")
        self.assertEqual(reference["status"], "description")
        self.assertIsNone(reference["start"])

    def test_legacy_scene_text_can_migrate(self) -> None:
        novel = "章节标题\n\n她站在车站。"
        reference = source_ref_from_legacy({"text": "她站在车站。"}, novel)

        self.assertEqual(reference["status"], "exact")
        self.assertEqual(reference["quote"], "她站在车站。")


if __name__ == "__main__":
    unittest.main()
