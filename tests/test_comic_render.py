from __future__ import annotations

import copy
import hashlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

from ficframe import comic_render as render


def png(color="red", size=(200, 200)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


def project():
    return {"schema_version": 1, "id": "demo", "title": "漫画测试", "lettering_mode": "text",
            "text_settings": {"dialogue": True, "narration": True, "sfx": True}, "pages": [
                {"id": "p1", "width": 300, "height": 400, "gutter": 0, "lettering_mode": "inherit", "panels": [
                    {"id": "panel1", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}, "current_image": "assets/a.png",
                     "crop": {"x": .5, "y": .5, "zoom": 1}, "lettering_mode": "inherit", "balloons": [
                         {"id": "b1", "kind": "dialogue", "text": "你好，世界！\n第二行", "rect": {"x": .1, "y": .1, "w": .8, "h": .5},
                          "font_size": 24, "line_spacing": 1.3, "writing_mode": "horizontal", "font": "noto", "tail": {"x": .8, "y": .8}, "show": True}]}]}]}


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


class ComicRenderTests(unittest.TestCase):
    def test_non_rectangular_panel_shapes_render_with_clipping(self):
        document = project()
        panel = document['pages'][0]['panels'][0]
        for shape in ('rounded', 'circle', 'diamond', 'hexagon'):
            panel['shape'] = shape
            image = render.render_page(document, document['pages'][0], {'assets/a.png': png()})
            self.assertEqual(image.size, (300, 400))

    def setUp(self):
        self.project = project()
        self.page = self.project["pages"][0]
        self.panel = self.page["panels"][0]
        self.balloon = self.panel["balloons"][0]
        self.assets = {"assets/a.png": png()}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive_files(self):
        path = render.archive_project(self.project, self.root, self.assets)
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def test_modes_and_no_mutation(self):
        original = copy.deepcopy(self.project)
        images = [render.render_page(self.project, self.page, self.assets, mode) for mode in ("text", "blank", "clean")]
        self.assertEqual(images[0].size, (300, 400))
        self.assertIsNotNone(ImageChops.difference(images[0], images[1]).getbbox())
        self.assertIsNotNone(ImageChops.difference(images[1], images[2]).getbbox())
        self.assertEqual(images[2].getpixel((150, 100)), (255, 0, 0))
        self.assertEqual(images[1].getpixel((150, 100)), (255, 255, 255))
        self.assertEqual(self.project, original)

    def test_inherited_modes_and_override(self):
        self.project["lettering_mode"] = "clean"
        self.page["lettering_mode"] = "blank"
        blank = render.render_page(self.project, self.page, self.assets)
        self.panel["lettering_mode"] = "text"
        text = render.render_page(self.project, self.page, self.assets)
        forced = render.render_page(self.project, self.page, self.assets, "blank")
        self.assertEqual(blank.tobytes(), forced.tobytes())
        self.assertNotEqual(blank.tobytes(), text.tobytes())

    def test_visibility_and_text_settings(self):
        clean = render.render_page(self.project, self.page, self.assets, "clean")
        self.project["text_settings"]["dialogue"] = False
        self.assertEqual(clean.tobytes(), render.render_page(self.project, self.page, self.assets).tobytes())
        self.project["text_settings"]["dialogue"] = True
        self.balloon["show"] = False
        self.assertEqual(clean.tobytes(), render.render_page(self.project, self.page, self.assets).tobytes())

    def test_crop_center_zoom_and_gutter(self):
        image = Image.new("RGB", (400, 200), "red")
        image.paste("blue", (200, 0, 400, 200))
        self.assets["assets/a.png"] = image
        self.page.update(width=100, height=100, gutter=10)
        self.panel["crop"].update(x=1, y=.5, zoom=2)
        output = render.render_page(self.project, self.page, self.assets, "clean")
        self.assertEqual(output.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(output.getpixel((50, 50)), (0, 0, 255))
        self.panel["crop"]["x"] = 0
        self.assertEqual(render.render_page(self.project, self.page, self.assets, "clean").getpixel((50, 50)), (255, 0, 0))

    def test_panel_border_and_corrupt_asset_error(self):
        output = render.render_page(self.project, self.page, self.assets, "clean")
        self.assertEqual(output.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(output.getpixel((299, 399)), (0, 0, 0))
        self.assets["assets/a.png"] = b"invalid image"
        with self.assertRaisesRegex(ValueError, "无法读取漫画素材图片"):
            render.render_page(self.project, self.page, self.assets)

    def test_vertical_punctuation_uses_vertical_forms(self):
        self.balloon.update(text="你好，世界！", writing_mode="vertical")
        layout = render._layout(self.balloon, 240, 200)
        glyphs = [position[0] for position in layout["positions"]]
        self.assertIn("︐", glyphs)
        self.assertIn("︕", glyphs)
        self.assertFalse(layout["overflow"])

    def test_tail_drawn_outside_balloon(self):
        with_tail = render.render_page(self.project, self.page, self.assets, "blank")
        del self.balloon["tail"]
        without_tail = render.render_page(self.project, self.page, self.assets, "blank")
        self.assertNotEqual(with_tail.getpixel((228, 300)), without_tail.getpixel((228, 300)))

    def test_chinese_horizontal_vertical_and_overflow(self):
        self.balloon["text"] = "中文" * 60 + "\n换行"
        for writing in ("horizontal", "vertical"):
            with self.subTest(writing=writing):
                self.balloon["writing_mode"] = writing
                warnings = render.inspect_text(self.project, self.page)
                self.assertEqual(warnings[0]["code"], "text_overflow")
                self.assertEqual(warnings[0]["balloon_id"], "b1")
                self.assertGreater(len(warnings[0]["lines"]), 1)
                self.assertEqual(render.render_page(self.project, self.page, self.assets).size, (300, 400))
        self.assertEqual(render.inspect_text(self.project, self.page, "clean"), [])

    def test_explicit_newlines_and_regular_font(self):
        layout = render._layout(self.balloon, 240, 200)
        self.assertEqual(layout["lines"], ["你好，世界！", "第二行"])
        self.assertEqual(layout["font"].getname(), ("Noto Sans SC", "Regular"))
        self.assertFalse(layout["overflow"])
        self.balloon["text"] = "a\n\nb"
        self.assertEqual(render._layout(self.balloon, 240, 200)["lines"], ["a", "", "b"])

    def test_regular_and_bold_fonts_render_differently(self):
        regular = render.render_page(self.project, self.page, self.assets)
        self.balloon["font"] = "noto-bold"
        bold = render.render_page(self.project, self.page, self.assets)
        self.assertEqual(render._font(24, "noto-bold").getname(), ("Noto Sans SC", "Bold"))
        self.assertEqual(render._font(24).getname(), ("Noto Sans SC", "Regular"))
        self.assertIsNotNone(ImageChops.difference(regular, bold).getbbox())
        self.assertIs(render._font(24, "noto-bold"), render._font(24, "noto-bold"))
        self.balloon["font"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "不支持的漫画字体"):
            render.render_page(self.project, self.page, self.assets)

    def test_text_cannot_paint_outside_its_rect(self):
        self.balloon["kind"] = "sfx"
        self.balloon["text"] = "中文" * 200
        self.balloon["font_size"] = 80
        output = render.render_page(self.project, self.page, self.assets)
        self.assertEqual(output.getpixel((280, 280)), (255, 0, 0))

    def test_missing_asset_and_unsafe_path_fail(self):
        for value in ("../outside.png", "C:/a.png", "assets\\a.png"):
            self.panel["current_image"] = value
            with self.assertRaises(ValueError):
                render.render_page(self.project, self.page, self.assets)
        self.panel["current_image"] = "assets/missing.png"
        with self.assertRaises(ValueError):
            render.render_page(self.project, self.page, self.assets)

    def test_invalid_dimensions_numbers_and_modes(self):
        for width in (0, 10**8, float("nan")):
            with self.subTest(width=width), self.assertRaises(ValueError):
                self.page["width"] = width
                render.render_page(self.project, self.page, self.assets)
        self.page["width"] = 300
        for mode in ("bad", "inherit"):
            with self.assertRaises(ValueError):
                render.render_page(self.project, self.page, self.assets, mode)

    def test_png_export_is_identical_to_preview(self):
        path = render.export_project(self.project, self.root, self.assets, "png")
        with zipfile.ZipFile(path) as archive:
            data = archive.read("pages/0001.png")
            output = Image.open(io.BytesIO(data))
            self.assertEqual(output.tobytes(), render.render_page(self.project, self.page, self.assets).tobytes())
            self.assertEqual(output.info["Title"], "漫画测试")
            metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["files"]["pages/0001.png"]["sha256"], hashlib.sha256(data).hexdigest())

    def test_multiple_pages_filter_order_and_pdf(self):
        second = copy.deepcopy(self.page)
        second["id"] = "p2"
        self.project["pages"].append(second)
        path = render.export_project(self.project, self.root, self.assets, "png", page_ids=["p2", "p1"])
        with zipfile.ZipFile(path) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["page_ids"], ["p1", "p2"])
            self.assertIn("pages/0002.png", archive.namelist())
        pdf = render.export_project(self.project, self.root, self.assets, "pdf")
        data = pdf.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertIn(b"/Count 2", data)
        for ids in ([], ["missing"], ["p1", "p1"]):
            with self.assertRaises(ValueError):
                render.export_project(self.project, self.root, self.assets, "png", page_ids=ids)

    def test_strip_segments_reconstruct_page_pixels(self):
        second = copy.deepcopy(self.page)
        second["id"] = "p2"
        self.project["pages"].append(second)
        with patch.object(render, "STRIP_MAX_HEIGHT", 250):
            path = render.export_project(self.project, self.root, self.assets, "strip", "clean")
        with zipfile.ZipFile(path) as archive:
            images = [Image.open(io.BytesIO(archive.read(name))) for name in sorted(archive.namelist()) if name.endswith(".png")]
            self.assertEqual([im.height for im in images], [250, 250, 250, 50])
            result = Image.new("RGB", (300, 800))
            y = 0
            for image in images:
                result.paste(image, (0, y))
                y += image.height
            self.assertEqual(result.crop((0, 0, 300, 400)).tobytes(), render.render_page(self.project, self.page, self.assets, "clean").tobytes())

    def test_archive_roundtrip_collects_history_references(self):
        self.panel["candidate_images"] = [{"path": "assets/old.png"}]
        self.panel["history"] = ["assets/version.png"]
        self.panel["generation_request"] = {"references": [{"asset_path": "assets/ref.png"}]}
        self.assets.update({name: png("green") for name in ("assets/old.png", "assets/version.png", "assets/ref.png")})
        original = copy.deepcopy(self.project)
        path = render.archive_project(self.project, self.root, self.assets)
        restored, assets = render.read_archive(path.read_bytes())
        self.assertEqual(restored, original)
        self.assertEqual(assets, self.assets)
        self.assertEqual(self.project, original)

    def test_archive_rejects_paths_and_collisions(self):
        files = self.archive_files()
        for path in ("../evil", "/evil", "C:/evil", "assets\\evil", "a//b", "a/./b", "a/../b", "CON.png", "a./x", "a\x00x"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                render.read_archive(zip_bytes({**files, path: b"x"}))
        with self.assertRaises(ValueError):
            render.read_archive(zip_bytes({**files, "PROJECT.JSON": files["project.json"]}))

    def test_archive_rejects_symlink_duplicate_and_corruption(self):
        files = self.archive_files()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, "outside")
        with self.assertRaises(ValueError):
            render.read_archive(output.getvalue())
        files["assets/a.png"] = b"corrupt"
        with self.assertRaises(ValueError):
            render.read_archive(zip_bytes(files))
        with self.assertRaises(ValueError):
            render.read_archive(b"not a zip")
        with self.assertRaises(ValueError):
            render.read_archive(zip_bytes({"project.json": b"{}"}))

    def test_archive_rejects_versions_and_duplicate_json_keys(self):
        files = self.archive_files()
        for key in ("project.json", "metadata.json"):
            document = json.loads(files[key])
            document["schema_version"] = 2
            with self.assertRaises(ValueError):
                render.read_archive(zip_bytes({**files, key: json.dumps(document).encode()}))
        with self.assertRaises(ValueError):
            render.read_archive(zip_bytes({**files, "project.json": b'{"schema_version":1,"schema_version":1,"pages":[]}'}))

    def test_archive_enforces_all_size_limits(self):
        data = zip_bytes(self.archive_files())
        for constant, limit in (("MAX_ARCHIVE_BYTES", 4), ("MAX_FILE_BYTES", 4), ("MAX_TOTAL_BYTES", 4), ("MAX_ARCHIVE_FILES", 1)):
            with self.subTest(constant=constant), patch.object(render, constant, limit), self.assertRaises(ValueError):
                render.read_archive(data)

    def test_archive_rejects_missing_and_extra_assets(self):
        files = self.archive_files()
        del files["assets/a.png"]
        with self.assertRaises(ValueError):
            render.read_archive(zip_bytes(files))
        self.panel["history"] = ["assets/missing.png"]
        with self.assertRaises(ValueError):
            render.archive_project(self.project, self.root, self.assets)


if __name__ == "__main__":
    unittest.main()
