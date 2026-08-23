from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ficframe import api
from ficframe.models import Shot, to_dict
from ficframe.segmenter import segment_novel


def sample_shot() -> Shot:
    return Shot(
        id="shot_01",
        scene_id="ch01_scene_01",
        title="清晨 - 车站 - 远景",
        source_excerpt="她站在车站。",
        characters=[],
        location="车站",
        time="清晨",
        mood=["安静"],
        camera="wide shot",
        composition="subject on the left",
        visual_goal="表现启程前的安静",
        continuity_notes=[],
        positive_prompt="Scene: quiet station",
        negative_prompt="extra people",
        source_text="她站在车站。",
        source_start=8,
        source_end=15,
        image_path="C:/run/images/shot_01.png",
        image_url="/runs/123/images/shot_01.png",
        image_versions=[{"image_path": "C:/run/images/shot_01.png", "image_url": "/runs/123/images/shot_01.png"}],
    )


class StoryboardWorkflowTests(unittest.TestCase):
    def test_scene_source_span_maps_back_to_original_novel(self) -> None:
        novel = "# 第一章\n\n第一段。\n\n第二段。\n"
        scenes = segment_novel(novel, [])
        self.assertEqual(len(scenes), 1)
        scene = scenes[0]
        self.assertIsNotNone(scene.source_start)
        self.assertIsNotNone(scene.source_end)
        source = novel[scene.source_start : scene.source_end]
        self.assertEqual(source, "第一段。\n\n第二段。")

    def test_old_run_source_fields_are_backfilled(self) -> None:
        novel = "# 第一章\n\n她站在车站。\n"
        payload = {
            "scenes": [{"id": "ch01_scene_01", "text": "她站在车站。"}],
            "shots": [{"id": "shot_01", "scene_id": "ch01_scene_01", "source_excerpt": "她站在车站。"}],
        }
        changed = api.backfill_storyboard_sources(payload, novel)
        self.assertTrue(changed)
        shot = payload["shots"][0]
        self.assertEqual(shot["source_text"], "她站在车站。")
        self.assertEqual(novel[shot["source_start"] : shot["source_end"]], shot["source_text"])

    def test_old_run_crlf_source_offsets_are_normalized(self) -> None:
        novel = "前文\n\n原文段落\n\n后文"
        payload = {
            "scenes": [],
            "shots": [
                {
                    "id": "shot_01",
                    "scene_id": "scene_01",
                    "source_text": "原文段落\r\n",
                    "source_start": 4,
                    "source_end": 9,
                }
            ],
        }
        self.assertTrue(api.backfill_storyboard_sources(payload, novel))
        self.assertEqual(payload["shots"][0]["source_text"], "原文段落\n")

    def test_old_run_crcrlf_novel_text_keeps_source_offsets_highlightable(self) -> None:
        novel = "前文\r\r\n\r\r\n原文段落\r\r\n\r\r\n后文"
        payload = {
            "scenes": [],
            "shots": [
                {
                    "id": "shot_01",
                    "scene_id": "scene_01",
                    "source_text": "原文段落\n\n",
                    "source_start": 4,
                    "source_end": 14,
                }
            ],
        }
        normalized = api.normalize_novel_text(novel)
        self.assertEqual(normalized, "前文\n\n原文段落\n\n后文")
        self.assertTrue(api.backfill_storyboard_sources(payload, normalized))
        shot = payload["shots"][0]
        self.assertEqual(normalized[shot["source_start"] : shot["source_end"]], shot["source_text"])

    def test_save_keeps_existing_image_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            original = sample_shot()
            (run_dir / "pipeline.json").write_text(
                json.dumps({"run_id": "123", "shots": [to_dict(original)]}, ensure_ascii=False), encoding="utf-8"
            )
            edited = to_dict(original)
            edited["title"] = "修改后的标题"
            edited["image_path"] = None
            edited["image_url"] = None
            edited["image_versions"] = []
            with patch.object(api, "RUNS", runs):
                result = api.save_storyboard(api.StoryboardSaveRequest(run_id="123", shots=[edited]))
            saved = result["shots"][0]
            self.assertEqual(saved["title"], "修改后的标题")
            self.assertEqual(saved["image_url"], original.image_url)
            self.assertEqual(saved["image_versions"], original.image_versions)
            history = result["storyboard_versions"]["shot_01"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["shot"]["title"], original.title)

    def test_regeneration_changes_text_but_preserves_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            original = sample_shot()
            payload = {
                "run_id": "123",
                "characters": [],
                "shots": [to_dict(original)],
                "storyboard_messages": [{"role": "user", "content": "远景很好，请保留"}],
            }
            (run_dir / "pipeline.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            def revise(shot, *_args, **_kwargs):
                shot.visual_goal = "调整后的画面目标"
                return shot

            with (
                patch.object(api, "RUNS", runs),
                patch.object(api, "require_llm_provider", return_value=object()),
                patch.object(api, "generate_or_revise_shot_with_llm", side_effect=revise),
            ):
                result = api.regenerate_storyboard(
                    api.StoryboardRegenerateRequest(run_id="123", shot_ids=["shot_01"])
                )
            revised = result["shots"][0]
            self.assertEqual(revised["visual_goal"], "调整后的画面目标")
            self.assertEqual(revised["image_url"], original.image_url)
            self.assertEqual(revised["image_versions"], original.image_versions)
            self.assertEqual(result["storyboard_versions"]["shot_01"][0]["source"], "manual_regenerate")

    def test_feedback_agent_can_automatically_regenerate_selected_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            original = sample_shot()
            payload = {"run_id": "123", "characters": [], "shots": [to_dict(original)], "storyboard_messages": []}
            (run_dir / "pipeline.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            def revise(shot, *_args, **_kwargs):
                shot.camera = "close-up"
                return shot

            decision = {
                "reply": "这个问题需要调整，我会立即重生成 shot_01。",
                "action": "regenerate",
                "shot_ids": ["shot_01"],
                "reason": "用户明确要求把景别改为特写",
            }
            with (
                patch.object(api, "RUNS", runs),
                patch.object(api, "require_llm_provider", return_value=object()),
                patch.object(api, "respond_to_storyboard_feedback", return_value=decision),
                patch.object(api, "generate_or_revise_shot_with_llm", side_effect=revise),
            ):
                result = api.storyboard_feedback(
                    api.StoryboardFeedbackRequest(run_id="123", content="shot_01 改成特写")
                )
            self.assertEqual(result["regenerated_shot_ids"], ["shot_01"])
            self.assertEqual(result["shots"][0]["camera"], "close-up")
            self.assertEqual(result["shots"][0]["image_url"], original.image_url)
            self.assertEqual(result["storyboard_versions"]["shot_01"][0]["source"], "agent_feedback")
            self.assertEqual(result["storyboard_messages"][-1]["action"], "regenerate")

    def test_feedback_agent_can_decide_no_regeneration_is_needed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            original = sample_shot()
            payload = {"run_id": "123", "characters": [], "shots": [to_dict(original)], "storyboard_messages": []}
            (run_dir / "pipeline.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            decision = {"reply": "谢谢，这一镜保持不变。", "action": "none", "shot_ids": [], "reason": "纯表扬"}
            with (
                patch.object(api, "RUNS", runs),
                patch.object(api, "require_llm_provider", return_value=object()),
                patch.object(api, "respond_to_storyboard_feedback", return_value=decision),
                patch.object(api, "generate_or_revise_shot_with_llm") as revise,
            ):
                result = api.storyboard_feedback(
                    api.StoryboardFeedbackRequest(run_id="123", content="这一镜很好，请保留")
                )
            revise.assert_not_called()
            self.assertEqual(result["regenerated_shot_ids"], [])
            self.assertEqual(result["shots"][0]["title"], original.title)

    def test_restore_storyboard_version_keeps_current_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            original = sample_shot()
            edited = to_dict(original)
            edited["title"] = "第二版标题"
            payload = {
                "run_id": "123",
                "shots": [edited],
                "storyboard_versions": {
                    "shot_01": [
                        {
                            "version_id": "sv_old",
                            "created_at": 1,
                            "reason": "修改前",
                            "source": "manual_edit",
                            "shot": api.storyboard_snapshot(to_dict(original)),
                        }
                    ]
                },
            }
            (run_dir / "pipeline.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(api, "RUNS", runs):
                result = api.restore_storyboard_version(
                    api.StoryboardVersionRequest(run_id="123", shot_id="shot_01", version_id="sv_old")
                )
            self.assertEqual(result["shot"]["title"], original.title)
            self.assertEqual(result["shot"]["image_url"], original.image_url)
            self.assertEqual(len(result["storyboard_versions"]["shot_01"]), 2)

            current_version = next(
                item for item in result["storyboard_versions"]["shot_01"]
                if item["shot"]["title"] == "第二版标题"
            )
            with patch.object(api, "RUNS", runs):
                restored_current = api.restore_storyboard_version(
                    api.StoryboardVersionRequest(
                        run_id="123", shot_id="shot_01", version_id=current_version["version_id"]
                    )
                )
            self.assertEqual(restored_current["shot"]["title"], "第二版标题")
            self.assertEqual(len(restored_current["storyboard_versions"]["shot_01"]), 2)

            with patch.object(api, "RUNS", runs):
                restored_original_again = api.restore_storyboard_version(
                    api.StoryboardVersionRequest(run_id="123", shot_id="shot_01", version_id="sv_old")
                )
            self.assertEqual(restored_original_again["shot"]["title"], original.title)
            self.assertEqual(len(restored_original_again["storyboard_versions"]["shot_01"]), 2)

    def test_llm_prompt_regeneration_archives_storyboard_and_keeps_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            original = sample_shot()
            prompt_feedback = [{"role": "user", "content": "保留构图，改成雨夜霓虹"}]
            payload = {
                "run_id": "123",
                "characters": [],
                "shots": [to_dict(original)],
                "storyboard_messages": [{"role": "user", "content": "把分镜改成特写"}],
                "prompt_feedback_messages": prompt_feedback,
            }
            (run_dir / "pipeline.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            captured = {}

            def polish(shot, *_args, **kwargs):
                captured["positive_prompt"] = shot.positive_prompt
                captured["negative_prompt"] = shot.negative_prompt
                captured["feedback_history"] = kwargs.get("feedback_history")
                shot.positive_prompt = "Scene: revised prompt"
                shot.negative_prompt = "extra people, duplicate character"
                return shot

            with (
                patch.object(api, "RUNS", runs),
                patch.object(api, "require_llm_provider", return_value=object()),
                patch.object(api, "polish_shot_prompt", side_effect=polish),
            ):
                result = api.regenerate_storyboard_prompt(
                    api.StoryboardPromptRequest(run_id="123", shot_id="shot_01")
                )
            self.assertEqual(result["shot"]["positive_prompt"], "Scene: revised prompt")
            self.assertEqual(result["shot"]["image_url"], original.image_url)
            self.assertEqual(result["storyboard_versions"]["shot_01"][0]["source"], "llm_prompt")
            self.assertEqual(captured["positive_prompt"], original.positive_prompt)
            self.assertEqual(captured["negative_prompt"], original.negative_prompt)
            self.assertEqual(captured["feedback_history"], prompt_feedback)

    def test_prompt_feedback_is_saved_separately_from_storyboard_agent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runs = Path(temp)
            run_dir = runs / "123"
            run_dir.mkdir()
            payload = {
                "run_id": "123",
                "shots": [to_dict(sample_shot())],
                "storyboard_messages": [{"role": "user", "content": "分镜反馈"}],
            }
            (run_dir / "pipeline.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch.object(api, "RUNS", runs):
                result = api.storyboard_prompt_feedback(
                    api.StoryboardPromptFeedbackRequest(run_id="123", content="加强负向手部约束")
                )
            self.assertEqual(result["prompt_feedback_messages"][-1]["content"], "加强负向手部约束")
            saved = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["storyboard_messages"], payload["storyboard_messages"])
            self.assertEqual(saved["prompt_feedback_messages"][-1]["content"], "加强负向手部约束")


if __name__ == "__main__":
    unittest.main()
