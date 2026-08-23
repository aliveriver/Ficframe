from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .continuity import initial_state
from .models import CharacterCard, Scene, Shot, to_dict
from .providers import ProviderError
from .run_repository import RunNotFoundError, RunRepository
from .segmenter import detect_characters, detect_location, detect_mood, detect_time, make_summary, priority, visual_type
from .storyboard import scene_to_shot
from .source_reference import build_description_source_ref, sync_legacy_source_fields
from .storyboard_workflow import (
    StoryboardRevisionError,
    archive_storyboard_versions,
    normalize_novel_text,
    normalize_source_reference,
    revise_storyboard_items,
    storyboard_message,
    storyboard_snapshot,
)


class StoryboardSaveRequest(BaseModel):
    run_id: str
    shots: list[dict[str, Any]] = Field(default_factory=list)


class StoryboardGenerateRequest(BaseModel):
    run_id: str
    source_ref: dict[str, Any] | None = None
    source_text: str = ""
    source_start: int | None = None
    source_end: int | None = None
    description: str = ""
    insert_after: str | None = None


class StoryboardFeedbackRequest(BaseModel):
    run_id: str
    content: str


class StoryboardPromptFeedbackRequest(BaseModel):
    run_id: str
    content: str


class StoryboardRegenerateRequest(BaseModel):
    run_id: str
    shot_ids: list[str] = Field(default_factory=list)


class StoryboardVersionRequest(BaseModel):
    run_id: str
    shot_id: str
    version_id: str


class StoryboardPromptRequest(BaseModel):
    run_id: str
    shot_id: str


@dataclass(frozen=True)
class StoryboardDependencies:
    repository: Callable[[], RunRepository]
    require_llm_provider: Callable[[], Any]
    parse_character_payload: Callable[[list[dict[str, Any]]], list[CharacterCard]]
    generate_or_revise_shot: Callable[..., Shot]
    respond_to_feedback: Callable[..., dict[str, Any]]
    polish_prompt: Callable[..., Shot]
    logger: Any


class StoryboardController:
    def __init__(self, dependencies: StoryboardDependencies):
        self.dependencies = dependencies
        self.router = APIRouter(prefix="/api/storyboard", tags=["storyboard"])
        self.router.add_api_route("/save", self.save_storyboard, methods=["POST"])
        self.router.add_api_route("/generate", self.generate_storyboard_shot, methods=["POST"])
        self.router.add_api_route("/feedback", self.storyboard_feedback, methods=["POST"])
        self.router.add_api_route("/prompt-feedback", self.storyboard_prompt_feedback, methods=["POST"])
        self.router.add_api_route("/regenerate", self.regenerate_storyboard, methods=["POST"])
        self.router.add_api_route("/version", self.restore_storyboard_version, methods=["POST"])
        self.router.add_api_route("/prompt", self.regenerate_storyboard_prompt, methods=["POST"])

    def save_storyboard(self, request: StoryboardSaveRequest) -> dict[str, Any]:
        with self._transaction(request.run_id) as payload:
            existing = {str(item.get("id")): item for item in payload.get("shots", []) if isinstance(item, dict)}
            saved: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in request.shots:
                shot = Shot(**item)
                if not shot.id or shot.id in seen:
                    raise HTTPException(status_code=400, detail="分镜 ID 不能为空或重复")
                seen.add(shot.id)
                old = existing.get(shot.id, {})
                for field in ["image_path", "image_url", "image_versions"]:
                    if field in old:
                        setattr(shot, field, old[field])
                saved.append(to_dict(shot))
            saved_by_id = {str(item.get("id")): item for item in saved}
            changed_items = [
                item for shot_id, item in existing.items()
                if shot_id not in saved_by_id or storyboard_snapshot(item) != storyboard_snapshot(saved_by_id[shot_id])
            ]
            if changed_items:
                archive_storyboard_versions(payload, changed_items, reason="保存修改或删除前的版本", source="manual_edit")
            payload["shots"] = saved
            result = self._storyboard_result(payload, shots=saved)
        self.dependencies.logger.info("storyboard saved run_id=%s shot_count=%s", request.run_id, len(saved))
        return result

    def generate_storyboard_shot(self, request: StoryboardGenerateRequest) -> dict[str, Any]:
        provider = self.dependencies.require_llm_provider()
        repository = self.dependencies.repository()
        novel_path = repository.novel_path(request.run_id)
        if not novel_path.exists():
            raise HTTPException(status_code=404, detail="未找到小说原文")
        novel_text = normalize_novel_text(novel_path.read_text(encoding="utf-8-sig"))
        try:
            source_ref = normalize_source_reference(
                novel_text, request.source_text, request.source_start, request.source_end, request.source_ref
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        description = request.description.strip()
        source_text = str(source_ref.get("quote") or "") if source_ref.get("kind") == "novel" else ""
        source_start = source_ref.get("start") if source_text else None
        source_end = source_ref.get("end") if source_text else None
        if not source_text and not description:
            raise HTTPException(status_code=400, detail="请在小说中选择一段文字，或填写画面描述")

        with self._transaction(request.run_id) as payload:
            cards = self.dependencies.parse_character_payload(payload.get("characters", []))
            number = self._safe_int(payload.get("next_shot_number"), len(payload.get("shots", [])) + 1)
            payload["next_shot_number"] = number + 1
            basis = source_text or description
            characters = detect_characters(basis, cards)
            scene = Scene(
                id=f"manual_scene_{number:02d}",
                chapter="手动添加",
                index=len(payload.get("scenes", [])) + 1,
                text=basis,
                summary=make_summary(basis),
                characters=characters,
                location=detect_location(basis),
                time=detect_time(basis),
                mood=detect_mood(basis),
                visual_type=visual_type(basis, characters),
                visual_priority=priority(basis),
                source_start=source_start,
                source_end=source_end,
                source_ref=source_ref if source_text else build_description_source_ref(description),
            )
            shot = scene_to_shot(scene, cards, initial_state(cards), number, payload.get("difference_analysis"))
            shot.generation_mode = "novel" if source_text else "description"
            shot.generation_description = description
            if not source_text:
                shot.source_text = ""
                shot.source_excerpt = description
                shot.source_ref = build_description_source_ref(description)
            else:
                shot.source_ref = source_ref
            try:
                shot = self.dependencies.generate_or_revise_shot(
                    shot,
                    cards,
                    provider,
                    feedback_history=payload.get("storyboard_messages", []),
                    purpose=f"storyboard:{request.run_id}:generate:{shot.id}",
                )
            except (ProviderError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=502, detail=f"LLM 生成分镜失败：{exc}") from exc
            shot_data = to_dict(shot)
            sync_legacy_source_fields(shot_data, shot.source_ref)
            payload.setdefault("scenes", []).append(to_dict(scene))
            shots = payload.setdefault("shots", [])
            insert_index = len(shots)
            if request.insert_after:
                matched = next((index for index, item in enumerate(shots) if item.get("id") == request.insert_after), None)
                if matched is not None:
                    insert_index = matched + 1
            shots.insert(insert_index, shot_data)
            result = {"ok": True, "shot": shot_data, "shots": shots}
        self.dependencies.logger.info("storyboard shot generated run_id=%s shot_id=%s mode=%s", request.run_id, shot.id, shot.generation_mode)
        return result

    def storyboard_feedback(self, request: StoryboardFeedbackRequest) -> dict[str, Any]:
        content = request.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="反馈内容不能为空")
        provider = self.dependencies.require_llm_provider()
        with self._transaction(request.run_id) as payload:
            messages = payload.setdefault("storyboard_messages", [])
            messages.append(storyboard_message("user", content))
            shots = [Shot(**item) for item in payload.get("shots", [])]
            cards = self.dependencies.parse_character_payload(payload.get("characters", []))
            try:
                decision = self.dependencies.respond_to_feedback(
                    shots, messages, cards, provider, purpose=f"storyboard:{request.run_id}:feedback"
                )
            except (ProviderError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=502, detail=f"LLM 反馈失败：{exc}") from exc
            target_ids = set(decision.get("shot_ids", [])) if decision.get("action") == "regenerate" else set()
            assistant_message = storyboard_message("assistant", str(decision.get("reply") or "已记录这条反馈。"))
            assistant_message.update({
                "action": decision.get("action", "none"),
                "shot_ids": sorted(target_ids),
                "reason": str(decision.get("reason") or ""),
            })
            messages.append(assistant_message)
            if target_ids:
                archive_storyboard_versions(
                    payload,
                    [item for item in payload.get("shots", []) if item.get("id") in target_ids],
                    reason=str(decision.get("reason") or "Agent 根据用户反馈决定重新生成"),
                    source="agent_feedback",
                )
                try:
                    payload["shots"] = revise_storyboard_items(
                        payload.get("shots", []),
                        target_ids,
                        cards,
                        provider,
                        messages,
                        purpose_prefix=f"storyboard:{request.run_id}:auto_regenerate",
                        revise_shot=self.dependencies.generate_or_revise_shot,
                    )
                except StoryboardRevisionError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                assistant_message["content"] = (
                    f"{assistant_message['content']}\n\n已自动重新生成：{', '.join(sorted(target_ids))}。原有图片及图片版本均已保留。"
                )
            result = {
                **self._storyboard_result(payload),
                "decision": decision,
                "regenerated_shot_ids": sorted(target_ids),
            }
        self.dependencies.logger.info(
            "storyboard feedback decision run_id=%s action=%s shot_ids=%s",
            request.run_id,
            decision.get("action", "none"),
            sorted(target_ids),
        )
        return result

    def storyboard_prompt_feedback(self, request: StoryboardPromptFeedbackRequest) -> dict[str, Any]:
        content = request.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Prompt 反馈内容不能为空")
        with self._transaction(request.run_id) as payload:
            messages = payload.setdefault("prompt_feedback_messages", [])
            messages.append(storyboard_message("user", content))
            result = {"ok": True, "prompt_feedback_messages": messages}
        return result

    def regenerate_storyboard(self, request: StoryboardRegenerateRequest) -> dict[str, Any]:
        provider = self.dependencies.require_llm_provider()
        target_ids = set(request.shot_ids)
        if not target_ids:
            raise HTTPException(status_code=400, detail="请选择要重新生成的分镜")
        with self._transaction(request.run_id) as payload:
            cards = self.dependencies.parse_character_payload(payload.get("characters", []))
            unknown = target_ids - {str(item.get("id")) for item in payload.get("shots", [])}
            if unknown:
                raise HTTPException(status_code=404, detail=f"未找到分镜：{', '.join(sorted(unknown))}")
            archive_storyboard_versions(
                payload,
                [item for item in payload.get("shots", []) if item.get("id") in target_ids],
                reason="用户手动触发重新生成",
                source="manual_regenerate",
            )
            try:
                revised = revise_storyboard_items(
                    payload.get("shots", []),
                    target_ids,
                    cards,
                    provider,
                    payload.get("storyboard_messages", []),
                    purpose_prefix=f"storyboard:{request.run_id}:regenerate",
                    revise_shot=self.dependencies.generate_or_revise_shot,
                )
            except StoryboardRevisionError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            payload["shots"] = revised
            messages = payload.setdefault("storyboard_messages", [])
            messages.append(storyboard_message("assistant", f"已按当前对话反馈重新生成 {len(target_ids)} 条分镜；原有图片及图片版本均已保留。"))
            result = self._storyboard_result(payload, shots=revised)
        self.dependencies.logger.info("storyboard regenerated run_id=%s shot_ids=%s", request.run_id, sorted(target_ids))
        return result

    def restore_storyboard_version(self, request: StoryboardVersionRequest) -> dict[str, Any]:
        with self._transaction(request.run_id) as payload:
            versions = payload.get("storyboard_versions", {}).get(request.shot_id, [])
            version = next((item for item in versions if item.get("version_id") == request.version_id), None)
            if not version:
                raise HTTPException(status_code=404, detail="未找到该分镜历史版本")
            current_index = next(
                (index for index, item in enumerate(payload.get("shots", [])) if item.get("id") == request.shot_id),
                None,
            )
            if current_index is None:
                raise HTTPException(status_code=404, detail="当前分镜已不存在，暂不能直接恢复")
            current = payload["shots"][current_index]
            archive_storyboard_versions(payload, [current], reason="恢复历史版本前的当前版本", source="version_restore")
            restored = Shot(**version.get("shot", {}))
            restored.id = request.shot_id
            restored.image_path = current.get("image_path")
            restored.image_url = current.get("image_url")
            restored.image_versions = current.get("image_versions", [])
            payload["shots"][current_index] = to_dict(restored)
            result = {
                **self._storyboard_result(payload),
                "shot": to_dict(restored),
            }
        self.dependencies.logger.info(
            "storyboard version restored run_id=%s shot_id=%s version_id=%s",
            request.run_id,
            request.shot_id,
            request.version_id,
        )
        return result

    def regenerate_storyboard_prompt(self, request: StoryboardPromptRequest) -> dict[str, Any]:
        provider = self.dependencies.require_llm_provider()
        with self._transaction(request.run_id) as payload:
            cards = self.dependencies.parse_character_payload(payload.get("characters", []))
            target_index = next(
                (index for index, item in enumerate(payload.get("shots", [])) if item.get("id") == request.shot_id),
                None,
            )
            if target_index is None:
                raise HTTPException(status_code=404, detail="未找到该分镜")
            current = payload["shots"][target_index]
            archive_storyboard_versions(payload, [current], reason="LLM 重建生图 Prompt 前的版本", source="llm_prompt")
            shot = Shot(**current)
            try:
                updated = self.dependencies.polish_prompt(
                    shot,
                    cards,
                    provider,
                    purpose=f"storyboard:{request.run_id}:prompt:{request.shot_id}",
                    feedback_history=payload.get("prompt_feedback_messages", []),
                )
            except (ProviderError, json.JSONDecodeError, TypeError) as exc:
                raise HTTPException(status_code=502, detail=f"LLM Prompt 重建失败：{exc}") from exc
            payload["shots"][target_index] = to_dict(updated)
            result = {
                **self._storyboard_result(payload),
                "shot": to_dict(updated),
            }
        return result

    @contextmanager
    def _transaction(self, run_id: str):
        try:
            with self.dependencies.repository().transaction(run_id) as payload:
                yield payload
        except (RunNotFoundError, ValueError) as exc:
            status = 404 if isinstance(exc, RunNotFoundError) else 400
            raise HTTPException(status_code=status, detail="run 不存在" if status == 404 else str(exc)) from exc

    @staticmethod
    def _storyboard_result(payload: dict[str, Any], *, shots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "ok": True,
            "shots": shots if shots is not None else payload.get("shots", []),
            "storyboard_messages": payload.get("storyboard_messages", []),
            "prompt_feedback_messages": payload.get("prompt_feedback_messages", []),
            "storyboard_versions": payload.get("storyboard_versions", {}),
        }

    @staticmethod
    def _safe_int(value: object, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback
