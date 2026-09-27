from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ficframe import api
from ficframe.export import build_export_bundle
from ficframe.models import Shot
from ficframe.models import to_dict
from ficframe.render import normalize_html_layout, normalize_html_settings, render_html_document
from ficframe.run_repository import RunRepository


def make_shot(**overrides) -> Shot:
    values = {
        "id": "shot_01",
        "scene_id": "scene_01",
        "title": "夜晚 - 房间 - 特写",
        "source_excerpt": "她推开门。",
        "characters": [],
        "location": "房间",
        "time": "夜晚",
        "mood": ["安静"],
        "camera": "close-up",
        "composition": "centered",
        "visual_goal": "表现她推门时的迟疑",
        "continuity_notes": [],
        "positive_prompt": "quiet room",
        "negative_prompt": "extra people",
    }
    values.update(overrides)
    return Shot(**values)


class ExportTests(unittest.TestCase):
    def test_html_layout_accepts_custom_width_and_rejects_unsafe_width(self) -> None:
        self.assertEqual(
            normalize_html_layout({"position": "left", "width": "420px"}),
            {"position": "before", "alignment": "center", "wrap": "left", "width": "420px", "caption": ""},
        )
        self.assertEqual(normalize_html_layout({"width": "expression(alert(1))"})["width"], "100%")
        layout = normalize_html_layout({"alignment": "right", "wrap": "left"})
        self.assertEqual(layout["alignment"], "right")
        self.assertEqual(layout["wrap"], "left")

    def test_html_settings_accept_safe_custom_fonts_and_reject_css_injection(self) -> None:
        settings = normalize_html_settings({
            "body_font_name": "霞鹜文楷",
            "heading_font_name": "Noto Serif CJK SC",
        })
        self.assertEqual(settings["body_font_name"], "霞鹜文楷")
        self.assertEqual(settings["heading_font_name"], "Noto Serif CJK SC")
        self.assertEqual(normalize_html_settings({"body_font_name": "x; color:red"})["body_font_name"], "")

        document = render_html_document("正文。", "测试", settings)
        self.assertIn('font-family: "霞鹜文楷",', document)
        self.assertIn('font-family: "Noto Serif CJK SC",', document)

    def test_html_preserves_image_order_and_escapes_text(self) -> None:
        document = render_html_document(
            "# 标题\n\n![shot_01](images/shot.png)\n\n正文 <script>alert(1)</script>。",
            "测试 <标题>",
            {"font_size": 22, "text_align": "justify"},
            {"shot_01": {"position": "after", "alignment": "right", "wrap": "none", "width": "420px", "caption": "图 <注>"}},
        )
        self.assertIn("font-size: 22px", document)
        self.assertIn("text-align: justify", document)
        self.assertIn('style="width: 420px"', document)
        self.assertIn('data-shot-id="shot_01"', document)
        self.assertIn('data-position="after"', document)
        self.assertIn('data-alignment="right"', document)
        self.assertIn('data-wrap="none"', document)
        self.assertIn("正文 &lt;script&gt;alert(1)&lt;/script&gt;。", document)
        self.assertIn("图 &lt;注&gt;", document)
        self.assertLess(document.index("正文 &lt;script&gt;"), document.index('data-position="after"'))
        self.assertNotIn("<script>alert(1)</script>", document)

    def test_html_omits_empty_caption_and_renders_independent_alignment_and_wrap(self) -> None:
        document = render_html_document(
            "![shot_01](images/shot.png)\n\n正文。",
            "测试",
            image_layouts={
                "shot_01": {"position": "before", "alignment": "right", "wrap": "left", "width": "45%"}
            },
        )
        self.assertIn("image-align-right", document)
        self.assertIn("image-wrap-left", document)
        self.assertNotIn("<figcaption>", document)

    def test_builds_portable_markdown_directory_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run-1"
            image = run_dir / "images" / "shot_01.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fake png")
            shot = make_shot(
                image_path=str(image),
                image_url="/runs/run-1/images/shot_01.png",
                html_layout={"position": "right", "width": "50%", "caption": "门口"},
            )

            bundle = build_export_bundle(
                run_dir,
                "run-1",
                "# 第一章\n\n她推开门。\n",
                [{"id": "scene_01", "index": 1, "text": "她推开门。"}],
                [shot],
                {"font_size": 20, "text_align": "justify"},
            )

            self.assertIn("images/shot_01.png", bundle.markdown)
            self.assertIn('data-position="before"', bundle.html)
            self.assertIn('data-wrap="right"', bundle.html)
            self.assertIn('style="width: 50%"', bundle.html)
            self.assertIn("门口", bundle.html)
            self.assertIn("font-size: 20px", bundle.html)
            self.assertTrue((bundle.export_dir / "illustrated_novel.md").exists())
            self.assertTrue((bundle.export_dir / "images" / "shot_01.png").exists())
            self.assertTrue(bundle.manifest_path.exists())
            self.assertTrue(bundle.theme_path.exists())
            self.assertTrue(bundle.zip_path.exists())
            manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["image_count"], 1)
            self.assertEqual(manifest["images"][0]["path"], "images/shot_01.png")
            self.assertEqual(manifest["images"][0]["source_path"], "images/shot_01.png")
            self.assertNotIn(str(run_dir), json.dumps(manifest, ensure_ascii=False))

            with zipfile.ZipFile(bundle.zip_path) as archive:
                names = set(archive.namelist())
                self.assertEqual(
                    names,
                    {
                        "illustrated_novel.md",
                        "illustrated_novel.html",
                        "images/shot_01.png",
                        "manifest.json",
                        "THEME.md",
                        "theme.json",
                    },
                )
                self.assertIn("FicFrame 图文导出主题说明", archive.read("THEME.md").decode("utf-8"))

    def test_missing_image_is_reported_without_breaking_markdown_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shot = make_shot(image_url="/runs/run-1/images/missing.png")
            bundle = build_export_bundle(
                Path(directory) / "run-1",
                "run-1",
                "正文。",
                [],
                [shot],
            )
            self.assertIn("images/missing.png", bundle.markdown)
            self.assertEqual(bundle.manifest["image_count"], 0)
            self.assertEqual(bundle.manifest["missing_image_shot_ids"], ["shot_01"])
            with zipfile.ZipFile(bundle.zip_path) as archive:
                self.assertNotIn("images/missing.png", archive.namelist())

    def test_api_export_info_exposes_directory_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            run_dir = runs / "run-1"
            image = run_dir / "images" / "shot_01.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fake png")
            repository = RunRepository(runs)
            repository.save(
                "run-1",
                {
                    "shots": [
                        to_dict(
                            make_shot(
                                image_path=str(image),
                                image_url="/runs/run-1/images/shot_01.png",
                            )
                        )
                    ],
                    "scenes": [{"id": "scene_01", "index": 1, "text": "她推开门。"}],
                },
                render=False,
            )
            (run_dir / "novel.md").write_text("她推开门。", encoding="utf-8")
            api._RUN_REPOSITORIES.clear()
            with patch.object(api, "RUNS", runs):
                result = api.export_markdown_info("run-1")
                html = api.export_html("run-1")
            self.assertTrue(Path(result["manifest_path"]).exists())
            self.assertTrue(Path(result["html_path"]).exists())
            self.assertTrue(Path(result["zip_path"]).exists())
            self.assertEqual(result["zip_url"], "/api/export/run-1.zip")
            self.assertIn("<!doctype html>", html)


if __name__ == "__main__":
    unittest.main()
