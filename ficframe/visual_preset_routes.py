from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Callable

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .features import visual_preset_kinds
from .models import Shot, to_dict
from .run_repository import RunNotFoundError
from .visual_presets import MAX_REFERENCE_BYTES, MAX_REFERENCE_COUNT, normalize_vlm_draft, validate_reference_bytes
from .visual_preset_analysis import analyze_references
from .visual_preset_workflow import SELECTION_FIELDS, bind_run_defaults, bind_shot, resolve_generation
from .image_reference_workflow import capability, probe_references, reference_preflight, purpose_prompt
from .storyboard_visual_guidance import prompt_style_pending, STYLE_UPDATE_MESSAGE


class VisualPresetRequest(BaseModel):
    name: str
    type: str
    positive: str = ""
    negative: str = ""
    vlm_analysis: dict[str, Any] = Field(default_factory=dict)
    reference_paths: list[str] = Field(default_factory=list)
    reference_mode: str = "text"


class VisualPresetUpdateRequest(BaseModel):
    name: str | None = None
    positive: str | None = None
    negative: str | None = None
    vlm_analysis: dict[str, Any] | None = None
    reference_paths: list[str] | None = None
    reference_mode: str | None = None


class RunVisualPresetsRequest(BaseModel):
    run_id: str
    style_id: str | None = None
    composition_id: str | None = None
    style_reference_mode: str | None = None
    composition_reference_mode: str | None = None
    refresh: bool = False


class VisualPreviewRequest(BaseModel):
    shot: dict[str, Any]
    size: str = "1024x1024"


class ShotVisualPresetsRequest(VisualPreviewRequest):
    refresh: bool = False


class ReferenceProbeRequest(BaseModel):
    confirmed: bool = False
    reference_count: int = Field(default=2, ge=2, le=32)
    size: str = Field(default="1024x1024", min_length=1, max_length=32)


@dataclass(frozen=True)
class VisualPresetDependencies:
    store: Callable[[], Any]
    repository: Callable[[], Any]
    task_manager: Callable[[], Any]
    provider: Callable[[], Any]
    reference_entries: Callable[..., Any] = lambda *_: []


class VisualPresetController:
    def __init__(self, dependencies: VisualPresetDependencies):
        self.dependencies = dependencies
        self.router = APIRouter(tags=["visual-presets"])
        for path, handler, methods in (
            ("/api/visual-presets", self.list_presets, ["GET"]),
            ("/api/visual-presets", self.create_preset, ["POST"]),
            ("/api/visual-presets/analyze", self.analyze, ["POST"]),
            ("/api/visual-presets/analyze-task", self.analyze_task, ["POST"]),
            ("/api/visual-presets/upload", self.upload, ["POST"]),
            ("/api/image-reference-capability", self.reference_capability, ["GET"]),
            ("/api/image-reference-test-task", self.reference_test_task, ["POST"]),
            ("/api/visual-presets/reference/{zone}/{owner}/{filename}", self.reference, ["GET"]),
            ("/api/visual-presets/{preset_id}", self.get_preset, ["GET"]),
            ("/api/visual-presets/{preset_id}", self.update_preset, ["PATCH"]),
            ("/api/visual-presets/{preset_id}", self.delete_preset, ["DELETE"]),
            ("/api/runs/{run_id}/visual-presets", self.save_defaults, ["POST"]),
            ("/api/runs/{run_id}/visual-preview", self.preview, ["POST"]),
            ("/api/runs/{run_id}/shots/{shot_id}/visual-presets", self.save_shot_selection, ["POST"]),
        ):
            self.router.add_api_route(path, handler, methods=methods, status_code=202 if path.endswith("-task") else 200)

    def list_presets(self, preset_type: str | None = None) -> dict[str, Any]:
        try:
            kinds = visual_preset_kinds()
            if preset_type:
                self._require_enabled(preset_type)
            return {"presets": [item for item in self.dependencies.store().list(preset_type) if item["type"] in kinds],
                    "enabled_types": kinds}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @staticmethod
    def _require_enabled(kind: str) -> None:
        if kind.strip().lower() == "composition" and "composition" not in visual_preset_kinds():
            raise HTTPException(404, "该功能暂未开放")

    def get_preset(self, preset_id: str) -> dict[str, Any]:
        try:
            item = self.dependencies.store().get(preset_id)
            if not item:
                raise HTTPException(404, "预设不存在")
            self._require_enabled(item["type"])
            return item
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def create_preset(self, request: VisualPresetRequest) -> dict[str, Any]:
        self._require_enabled(request.type)
        try:
            store = self.dependencies.store()
            result = store.create(name=request.name, preset_type=request.type, positive=request.positive,
                                  negative=request.negative, vlm_analysis=request.vlm_analysis, reference_paths=request.reference_paths,
                                  reference_mode=request.reference_mode)
            # Keep draft references: task results and another pending editor may
            # still refer to them. No automatic destructive garbage collection.
            return result
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def update_preset(self, preset_id: str, request: VisualPresetUpdateRequest) -> dict[str, Any]:
        self.get_preset(preset_id)
        try:
            return self.dependencies.store().update(preset_id, request.model_dump(exclude_unset=True, exclude_none=True))
        except KeyError as exc:
            raise HTTPException(404, "预设不存在") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def delete_preset(self, preset_id: str) -> dict[str, Any]:
        self.get_preset(preset_id)
        try:
            self.dependencies.store().delete(preset_id)
            return {"ok": True, "id": preset_id}
        except KeyError as exc:
            raise HTTPException(404, "预设不存在") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def reference(self, zone: str, owner: str, filename: str) -> FileResponse:
        try:
            return FileResponse(self.dependencies.store().reference_path(f"{zone}/{owner}/{filename}"))
        except ValueError as exc:
            raise HTTPException(404, "参考图不存在") from exc

    async def _uploads(self, kind: str, uploads: list[UploadFile]) -> list[tuple[str, bytes, str | None]]:
        self._require_enabled(kind)
        try:
            normalize_vlm_draft(kind, {})
            if not 1 <= len(uploads) <= MAX_REFERENCE_COUNT:
                raise ValueError("请上传 1 至 8 张参考图")
            result = []
            for upload in uploads:
                content = await upload.read(MAX_REFERENCE_BYTES + 1)
                name = str(upload.filename or "reference.png").replace("\\", "/").split("/")[-1]
                validate_reference_bytes(name, content, upload.content_type)
                result.append((name, content, upload.content_type))
            return result
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    async def analyze(self, preset_type: Annotated[str, Form()], reference_images: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        files = await self._uploads(preset_type, reference_images)
        return analyze_references(self.dependencies.store(), self.dependencies.provider(), preset_type, files, "visual_preset:analyze")

    async def upload(self, preset_type: Annotated[str, Form()], reference_images: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        files = await self._uploads(preset_type, reference_images)
        paths = self.dependencies.store().save_draft_references([(name, content) for name, content, _ in files])
        return {"type": preset_type.strip().lower(), "reference_mode": "image", "reference_paths": paths}

    def reference_capability(self, size: str = "1024x1024") -> dict[str, Any]:
        return capability(self.dependencies.store(), self.dependencies.provider(), size)

    def reference_test_task(self, request: ReferenceProbeRequest) -> dict[str, Any]:
        if not request.confirmed:
            raise HTTPException(400, "实际多图测试会调用图片供应商并可能计费，请先确认。")
        store, provider = self.dependencies.store(), self.dependencies.provider()
        def work(reporter):
            reporter.update("测试多图参考", 10, "仅使用内置色块图片，测试接口接受能力，不上传用户小说或参考图")
            return probe_references(store, provider, request.reference_count, request.size)
        task = self.dependencies.task_manager().submit("analysis", "image_reference_probe", work, message="多图参考测试已进入队列")
        return {"task_id": task["task_id"], "task": task}

    async def analyze_task(self, preset_type: Annotated[str, Form()], reference_images: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        files = await self._uploads(preset_type, reference_images)
        def work(reporter):
            reporter.update("分析参考图", 20, "正在提炼视觉规范")
            result = analyze_references(self.dependencies.store(), self.dependencies.provider(), preset_type, files, "visual_preset:analyze_task")
            reporter.update("整理草稿", 90, "分析完成，请检查草稿状态并确认")
            return result
        task = self.dependencies.task_manager().submit("analysis", "visual_preset_analysis", work, message="参考图分析已进入队列")
        return {"task_id": task["task_id"], "task": task}

    def save_defaults(self, run_id: str, request: RunVisualPresetsRequest) -> dict[str, Any]:
        if request.run_id != run_id:
            raise HTTPException(400, "run_id 不一致")
        try:
            store = self.dependencies.store()
            with self.dependencies.repository().transaction(run_id) as payload:
                defaults = bind_run_defaults(store, payload, request.model_dump(), refresh=request.refresh)
                payload["visual_presets"] = defaults
                for index, item in enumerate(payload.get("shots", [])):
                    shot = Shot(**item)
                    # Only inherited categories follow an explicitly changed run default.
                    payload["shots"][index] = to_dict(bind_shot(store, shot, defaults, item))
                result = {"run_id": run_id, "visual_presets": defaults, "shots": payload.get("shots", [])}
            return result
        except RunNotFoundError as exc:
            raise HTTPException(404, "run 不存在") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def preview(self, run_id: str, request: VisualPreviewRequest) -> dict[str, Any]:
        try:
            payload = self.dependencies.repository().load(run_id)
            shot = Shot(**request.shot)
            store = self.dependencies.store()
            positive, negative, snapshot = resolve_generation(store, payload, shot)
            identity_count = sum(len(group) for _, group in self.dependencies.reference_entries(run_id, shot))
            preflight = reference_preflight(store, self.dependencies.provider(), snapshot, identity_count, request.size)
            positive = purpose_prompt(positive, identity_count, preflight.get("style_count", 0), preflight.get("composition_count", 0))
            snapshot["positive_prompt"] = positive
            return {"positive_prompt": positive, "negative_prompt": negative, "visual_preset_snapshot": snapshot, "reference_preflight": preflight,
                    "prompt_style_pending": prompt_style_pending(shot),
                    "prompt_style_message": STYLE_UPDATE_MESSAGE if prompt_style_pending(shot) else ""}
        except RunNotFoundError as exc:
            raise HTTPException(404, "run 不存在") from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def save_shot_selection(self, run_id: str, shot_id: str, request: ShotVisualPresetsRequest) -> dict[str, Any]:
        try:
            with self.dependencies.repository().transaction(run_id) as payload:
                old = next((item for item in payload.get("shots", []) if item.get("id") == shot_id), None)
                if old is None:
                    raise HTTPException(404, "分镜不存在")
                shot = Shot(**old)
                for kind in visual_preset_kinds():
                    for field in ("mode", "id"):
                        key = f"{kind}_preset_{field}"
                        if key in request.shot:
                            setattr(shot, key, request.shot[key])
                    key = f"{kind}_reference_mode"
                    if key in request.shot:
                        setattr(shot, key, request.shot[key])
                store = self.dependencies.store()
                payload["visual_presets"] = bind_run_defaults(store, payload)
                bind_shot(store, shot, payload["visual_presets"], old, refresh=request.refresh)
                for key in SELECTION_FIELDS:
                    old[key] = to_dict(getattr(shot, key))
                old["prompt_style_snapshot"] = shot.prompt_style_snapshot
                return {"shot": old}
        except RunNotFoundError as exc:
            raise HTTPException(404, "run 不存在") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
