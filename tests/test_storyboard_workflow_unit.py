from __future__ import annotations

import unittest
import json

from ficframe.llm_pipeline import polish_shot_prompt
from ficframe.models import Shot, to_dict
from ficframe.storyboard_workflow import (
    MAX_STORYBOARD_VERSIONS,
    StoryboardRevisionError,
    archive_storyboard_versions,
    normalize_requested_source,
    normalize_novel_text,
    revise_storyboard_items,
)


def workflow_shot() -> Shot:
    return Shot(
        id="shot_01",
        scene_id="scene_01",
        title="初始版本",
        source_excerpt="原文",
        characters=[],
        location="房间",
        time="夜晚",
        mood=["平静"],
        camera="medium shot",
        composition="centered",
        visual_goal="初始目标",
        continuity_notes=[],
        positive_prompt="Scene: room",
        negative_prompt="extra people",
        image_path="images/shot_01.png",
        image_url="/runs/demo/images/shot_01.png",
        image_versions=[{"image_url": "/runs/demo/images/shot_01.png"}],
    )


class StoryboardWorkflowUnitTests(unittest.TestCase):
    def test_novel_coordinates_use_lf_line_endings(self) -> None:
        self.assertEqual(normalize_novel_text("第一行\r\n第二行\r第三行"), "第一行\n第二行\n第三行")

    def test_source_normalization_prefers_verified_offsets(self) -> None:
        novel = "前文\n被选中的段落\n后文"
        start = novel.index("被选中")
        end = start + len("被选中的段落")
        self.assertEqual(
            normalize_requested_source(novel, "被选中的段落", start, end),
            ("被选中的段落", start, end),
        )
        with self.assertRaises(ValueError):
            normalize_requested_source(novel, "不存在的段落", None, None)

    def test_version_archive_is_bounded_and_excludes_images(self) -> None:
        payload: dict = {}
        shot = to_dict(workflow_shot())
        for index in range(MAX_STORYBOARD_VERSIONS + 3):
            shot["title"] = f"版本 {index}"
            archive_storyboard_versions(payload, [shot], reason="测试", source="unit")
        history = payload["storyboard_versions"]["shot_01"]
        self.assertEqual(len(history), MAX_STORYBOARD_VERSIONS)
        self.assertNotIn("image_url", history[-1]["shot"])
        self.assertEqual(history[-1]["shot"]["title"], f"版本 {MAX_STORYBOARD_VERSIONS + 2}")

    def test_version_archive_removes_existing_duplicates_and_skips_same_snapshot(self) -> None:
        shot = to_dict(workflow_shot())
        snapshot = {key: value for key, value in shot.items() if key not in {"image_path", "image_url", "image_versions"}}
        payload = {
            "storyboard_versions": {
                "shot_01": [
                    {"version_id": "sv_first", "shot": snapshot, "source": "manual_edit"},
                    {"version_id": "sv_duplicate", "shot": snapshot, "source": "version_restore"},
                ]
            }
        }

        archive_storyboard_versions(payload, [shot], reason="再次恢复", source="version_restore")

        history = payload["storyboard_versions"]["shot_01"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["version_id"], "sv_first")

    def test_revision_boundary_restores_images_even_if_reviser_changes_them(self) -> None:
        original = workflow_shot()

        def malicious_reviser(shot, *_args, **_kwargs):
            shot.title = "新版本"
            shot.image_url = "/wrong.png"
            shot.image_versions = []
            return shot

        revised = revise_storyboard_items(
            [to_dict(original)],
            {original.id},
            [],
            object(),
            [],
            "unit",
            malicious_reviser,
        )[0]
        self.assertEqual(revised["title"], "新版本")
        self.assertEqual(revised["image_url"], original.image_url)
        self.assertEqual(revised["image_versions"], original.image_versions)

    def test_revision_error_identifies_failed_shot(self) -> None:
        original = workflow_shot()

        def failing_reviser(*_args, **_kwargs):
            raise RuntimeError("provider failed")

        with self.assertRaises(StoryboardRevisionError) as raised:
            revise_storyboard_items(
                [to_dict(original)],
                {original.id},
                [],
                object(),
                [],
                "unit",
                failing_reviser,
            )
        self.assertEqual(raised.exception.shot_id, original.id)

    def test_prompt_polish_receives_feedback_history(self) -> None:
        class CaptureProvider:
            def __init__(self):
                self.user_payload = None

            def text(self, _system, user, purpose=None):
                self.user_payload = json.loads(user)
                return json.dumps(
                    {
                        "positive_prompt": (
                            "Scene: quiet room with cinematic light. Composition: centered subject. "
                            "Characters: exactly one visible character. Style: detailed illustration."
                        ),
                        "negative_prompt": "extra people, duplicate character, wrong character identity",
                    }
                )

        provider = CaptureProvider()
        polish_shot_prompt(
            workflow_shot(),
            [],
            provider,
            feedback_history=[
                {"role": "user", "content": "保留安静情绪，但把构图改成更近的特写", "shot_ids": ["shot_01"]}
            ],
        )
        self.assertEqual(provider.user_payload["user_feedback_history"][0]["shot_ids"], ["shot_01"])
        self.assertIn("更近的特写", provider.user_payload["user_feedback_history"][0]["content"])


if __name__ == "__main__":
    unittest.main()
