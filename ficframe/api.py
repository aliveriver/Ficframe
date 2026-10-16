from __future__ import annotations

import asyncio
import io
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .characters import build_character_cards
from .character_diff import analyze_character_differences
from .comfyui import ComfyUIError, normalize_comfyui_base_url
from .config_store import public_config, public_provider_config, read_provider_config, write_env_file, write_provider_config
from .export import build_export_bundle
from .io import read_text, write_json, write_text
from .llm_pipeline import (
    enhance_character_cards_with_llm,
    extract_character_cards_with_llm_detailed,
    generate_or_revise_shot_with_llm,
    polish_shot_prompt,
    respond_to_storyboard_feedback,
)
from .logging_utils import build_log_bundle, get_logger, redact, setup_logging
from .models import CharacterCard, Shot, to_dict
from .pipeline import build_story_payload, polish_shots_with_llm
from .providers import OpenAICompatibleProvider, ProviderError, effective_image_provider
from . import provider_probe

from .prompt_bank import analyze_reference_visuals, build_character_prompt_bank
from .render import normalize_html_settings
from .runtime_paths import env_file, outputs_root, providers_file, resource_root, user_data_root, visual_presets_root, web_root
from .visual_presets import VisualPresetStore
from .visual_preset_workflow import bind_defaults, bind_shot, bind_storyboard_shot
from .visual_preset_routes import VisualPresetController, VisualPresetDependencies
from .image_workflow import (
    ImageSelectionError, ImageWorkflow, image_target_for_generation, image_url_for_path,
    reference_image_entries, reference_regions_for_characters, strip_version_query, versioned_url_for_path,
)
from .payloads import (
    available_reference_filename, bind_reference_image, dedupe_cards, parse_character_payload,
    parse_json_list, parse_manual_characters, parse_prepared_characters, parse_reference_bindings,
    parse_scene_payload, prompt_bank_status_text, safe_int, safe_optional_int, safe_string_dict,
    safe_string_list, take_reference_binding,
)
from .storyboard_workflow import backfill_storyboard_sources, normalize_novel_text, storyboard_snapshot
from .run_repository import RunNotFoundError, RunRepository
from .storyboard_routes import (
    StoryboardController,
    StoryboardDependencies,
    StoryboardFeedbackRequest,
    StoryboardGenerateRequest,
    StoryboardPromptFeedbackRequest,
    StoryboardPromptRequest,
    StoryboardRegenerateRequest,
    StoryboardSaveRequest,
    StoryboardVersionRequest,
)
from .task_manager import TaskManager, TaskReporter


# 保留旧模块常量，兼容外部调用方和历史测试。
COMFYUI_CLI_PORT = provider_probe.COMFYUI_CLI_PORT
COMFYUI_DESKTOP_DEFAULT_PORT = provider_probe.COMFYUI_DESKTOP_DEFAULT_PORT
COMFYUI_DESKTOP_PORT_SPAN = provider_probe.COMFYUI_DESKTOP_PORT_SPAN

RESOURCE_ROOT = resource_root()
ROOT = user_data_root()
WEB = web_root()
RUNS = outputs_root() / "web-runs"
ENV_FILE = env_file()
PROVIDERS_FILE = providers_file()
RUNS.mkdir(parents=True, exist_ok=True)
LOGS = setup_logging(ROOT)
logger = get_logger("api")

app = FastAPI(title="FicFrame API")
app.mount("/assets", StaticFiles(directory=WEB), name="assets")
app.mount("/runs", StaticFiles(directory=RUNS), name="runs")


def run_directory(run_id: str) -> Path:
    try:
        return get_run_repository().run_dir(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_RUN_REPOSITORIES: dict[str, RunRepository] = {}
_TASK_MANAGERS: dict[str, TaskManager] = {}
_VISUAL_PRESET_STORE: VisualPresetStore | None = None
_VISUAL_TASK_MANAGERS: dict[str, TaskManager] = {}


def get_run_repository() -> RunRepository:
    """每个解析后的根目录共用一个 repository，并兼容测试替换的根目录。"""
    key = str(Path(RUNS).resolve())
    repository = _RUN_REPOSITORIES.get(key)
    if repository is None:
        repository = RunRepository(RUNS)
        _RUN_REPOSITORIES[key] = repository
    return repository


def get_task_manager() -> TaskManager:
    """让任务管理器和当前 run repository 共用持久化边界。"""
    repository = get_run_repository()
    key = str(repository.root)
    manager = _TASK_MANAGERS.get(key)
    if manager is None:
        manager = TaskManager(repository)
        _TASK_MANAGERS[key] = manager
    return manager


def get_visual_preset_store() -> VisualPresetStore:
    global _VISUAL_PRESET_STORE
    root = visual_presets_root()
    if _VISUAL_PRESET_STORE is None or _VISUAL_PRESET_STORE.root.resolve() != root.resolve():
        _VISUAL_PRESET_STORE = VisualPresetStore(root)
    return _VISUAL_PRESET_STORE


def get_visual_task_manager() -> TaskManager:
    root = get_visual_preset_store().root / "analysis-tasks"
    key = str(root.resolve())
    if key not in _VISUAL_TASK_MANAGERS:
        _VISUAL_TASK_MANAGERS[key] = TaskManager(RunRepository(root))
    return _VISUAL_TASK_MANAGERS[key]


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request failed method=%s path=%s", request.method, request.url.path)
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    if request.url.path.startswith("/api/"):
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


class ImageRequest(BaseModel):
    shot: dict[str, Any]
    run_id: str = "manual"
    size: str = "1024x1024"
    overwrite: bool = True
    activate: bool | None = None


class ImageVersionRequest(BaseModel):
    run_id: str
    shot_id: str
    image_url: str


class ConfigRequest(BaseModel):
    values: dict[str, str]


class ProvidersRequest(BaseModel):
    config: dict[str, Any]


class ProviderTestRequest(BaseModel):
    source: dict[str, Any]


class CharacterPreviewRequest(BaseModel):
    text: str
    use_llm: bool = False


class CharacterLlmRequest(BaseModel):
    text: str = ""
    characters: list[dict[str, Any]] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    pending_reference_image_count: int = 0


class LogBundleRequest(BaseModel):
    run_id: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(WEB / "favicon.ico", media_type="image/vnd.microsoft.icon")


@app.get("/api/health")
def health() -> dict[str, Any]:
    config = OpenAICompatibleProvider().config
    image_provider = effective_image_provider(config.image)
    image_options = config.image_options or {}
    image_ready = bool(config.image.api_key)
    if image_provider == "comfyui":
        image_ready = bool(config.image.base_url and image_options.get("workflow_json"))
    return {
        "ok": True,
        "keys": {
            "llm": bool(config.llm.api_key),
            "image": image_ready,
            "vlm": bool(config.vlm.api_key),
        },
        "base_urls": {
            "llm": config.llm.base_url,
            "image": config.image.base_url,
            "vlm": config.vlm.base_url,
        },
        "models": {
            "llm": config.llm.model,
            "image": config.image.model,
            "vlm": config.vlm.model,
        },
        "providers": {
            "image": image_provider,
        },
    }


@app.get("/api/logs")
def get_logs() -> dict[str, Any]:
    files = []
    for path in sorted(LOGS.glob("*.log*"), key=lambda item: item.stat().st_mtime, reverse=True):
        files.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "modified_at": int(path.stat().st_mtime),
            }
        )
    return {"files": files}


@app.get("/api/runs")
def list_runs() -> dict[str, Any]:
    return {"runs": get_run_repository().list_runs(limit=20)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    repository = get_run_repository()
    try:
        payload = repository.load(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="未找到该 run") from exc
    novel_path = repository.novel_path(run_id)
    if novel_path.exists() and backfill_storyboard_sources(payload, normalize_novel_text(read_text(novel_path))):
        repository.save(run_id, payload)
    return payload


@app.get("/api/runs/{run_id}/novel", response_class=PlainTextResponse)
def get_run_novel(run_id: str) -> str:
    novel_path = run_directory(run_id) / "novel.md"
    if not novel_path.exists():
        raise HTTPException(status_code=404, detail="未找到小说原文")
    return normalize_novel_text(read_text(novel_path))


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    try:
        return get_task_manager().get(task_id)
    except KeyError as exc:
        try:
            return get_visual_task_manager().get(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="未找到该任务") from exc


@app.get("/api/runs/{run_id}/tasks")
def list_run_tasks(run_id: str) -> dict[str, Any]:
    try:
        get_run_repository().run_dir(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tasks": get_task_manager().list_for_run(run_id)}


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, Any]:
    try:
        return get_task_manager().cancel(task_id)
    except KeyError as exc:
        try:
            return get_visual_task_manager().cancel(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="未找到该任务") from exc
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/logs/export")
def export_logs(request: LogBundleRequest) -> FileResponse:
    config = public_provider_config(PROVIDERS_FILE, ENV_FILE)
    bundle = build_log_bundle(ROOT, config=config, active_run_id=request.run_id, resource_root=RESOURCE_ROOT)
    logger.info("log bundle exported path=%s run_id=%s", bundle, request.run_id or "")
    return FileResponse(bundle, filename=bundle.name, media_type="application/zip")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "values": public_config(ENV_FILE, reveal_keys=False),
        "providers": public_provider_config(PROVIDERS_FILE, ENV_FILE),
    }


@app.post("/api/config")
def save_config(request: ConfigRequest) -> dict[str, Any]:
    write_env_file(ENV_FILE, request.values)
    logger.info("legacy config saved keys=%s", ",".join(sorted(request.values.keys())))
    return {"ok": True, "values": public_config(ENV_FILE, reveal_keys=False)}


@app.get("/api/providers")
def get_providers() -> dict[str, Any]:
    return {"config": public_provider_config(PROVIDERS_FILE, ENV_FILE)}


@app.post("/api/providers")
def save_providers(request: ProvidersRequest) -> dict[str, Any]:
    for source in request.config.get("sources", []):
        if not isinstance(source, dict) or str(source.get("provider") or "").lower() != "comfyui":
            continue
        try:
            source["base_url"] = normalize_comfyui_base_url(str(source.get("base_url") or ""))
        except ComfyUIError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_provider_config(PROVIDERS_FILE, ENV_FILE, request.config)
    sources = request.config.get("sources", []) if isinstance(request.config, dict) else []
    logger.info("providers saved source_count=%s active=%s", len(sources), redact(request.config.get("active", {})))
    return {"ok": True, "config": public_provider_config(PROVIDERS_FILE, ENV_FILE)}


@app.post("/api/providers/test")
def test_provider(request: ProviderTestRequest) -> dict[str, Any]:
    source = hydrate_provider_secret(request.source)
    try:
        return provider_probe.test_provider_connection(
            source,
            logger=logger,
            comfyui_test=test_comfyui_provider,
        )
    except ValueError as exc:
        logger.warning("provider test rejected source=%s error=%s", redact(source), exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def test_comfyui_provider(base_url: str, api_key: str = "") -> dict[str, Any]:
    return provider_probe.test_comfyui_connection(
        base_url,
        api_key,
        discover_endpoints=discover_local_comfyui_endpoints,
    )


def discover_local_comfyui_endpoints(base_path: str) -> tuple[str, ...]:
    return provider_probe.discover_local_comfyui_endpoints(base_path)


def desktop_comfyui_server_target(base_path: str) -> tuple[str, int]:
    return provider_probe.desktop_comfyui_server_target(base_path)


def local_tcp_port_open(host: str, port: int) -> bool:
    return provider_probe.local_tcp_port_open(host, port)


probe_runtime_endpoint = provider_probe.probe_runtime_endpoint
build_runtime_probe_payload = provider_probe.build_runtime_probe_payload


@app.post("/api/characters/preview")
def preview_characters(request: CharacterPreviewRequest) -> dict[str, Any]:
    logger.info("characters preview started use_llm=%s text_length=%s", request.use_llm, len(request.text))
    cards = build_character_cards(request.text)
    difference_analysis = analyze_character_differences(cards, None)
    logger.info(
        "characters preview completed use_llm=%s character_count=%s text_length=%s difference_pair_count=%s",
        request.use_llm,
        len(cards),
        len(request.text),
        len(difference_analysis.get("pairs", [])),
    )
    return {
        "characters": to_dict(cards),
        "difference_analysis": difference_analysis,
        "llm_requested": False,
        "llm_status": "本地规则",
    }


@app.post("/api/characters/llm/extract")
def llm_extract_characters(request: CharacterLlmRequest) -> dict[str, Any]:
    logger.info("characters llm extract started text_length=%s", len(request.text))
    provider = OpenAICompatibleProvider()
    if not provider.config.llm.api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API key")
    local_cards = build_character_cards(request.text)
    cards, status = extract_character_cards_with_llm_detailed(request.text, provider, purpose="button:llm_extract_characters")
    if not cards:
        logger.warning("characters llm extract fallback=local status=%s local_character_count=%s", status, len(local_cards))
        cards = local_cards
        status = f"未替换本地结果：{status}"
    difference_analysis = analyze_character_differences(cards, None)
    logger.info("characters llm extract completed status=%s character_count=%s", status, len(cards))
    return {
        "characters": to_dict(cards),
        "difference_analysis": difference_analysis,
        "llm_status": status,
    }


@app.post("/api/characters/llm/enhance")
def llm_enhance_characters(request: CharacterLlmRequest) -> dict[str, Any]:
    logger.info("characters llm enhance started character_count=%s", len(request.characters))
    provider = OpenAICompatibleProvider()
    if not provider.config.llm.api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API key")
    cards = parse_character_payload(request.characters)
    cards = enhance_character_cards_with_llm(cards, provider, purpose="button:llm_enhance_characters")
    logger.info("characters llm enhance completed character_count=%s", len(cards))
    return {"characters": to_dict(cards), "llm_status": f"已增强 {len(cards)} 个角色"}


@app.post("/api/characters/llm/prompt-bank")
def llm_prompt_bank(request: CharacterLlmRequest) -> dict[str, Any]:
    logger.info(
        "characters llm prompt bank started character_count=%s scene_count=%s text_length=%s",
        len(request.characters),
        len(request.scenes),
        len(request.text),
    )
    provider = OpenAICompatibleProvider()
    if not provider.config.llm.api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API key")
    cards = parse_character_payload(request.characters)
    scenes = parse_scene_payload(request.scenes)
    result = build_character_prompt_bank(cards, scenes, provider, purpose="button:llm_prompt_bank")
    logger.info(
        "characters llm prompt bank completed character_count=%s mode=%s llm_error=%s",
        len(cards),
        result.mode,
        result.llm_error,
    )
    status = prompt_bank_status_text(result, len(cards))
    missing_reference_visuals = sum(1 for card in cards if card.reference_images and not card.reference_visuals)
    if request.pending_reference_image_count or missing_reference_visuals:
        status += "；注意：当前独立按钮不会上传新参考图，需先跑一次含参考图的生成分镜/VLM 分析后，Prompt Bank 才能贴合参考图"
    return {"characters": to_dict(cards), "llm_status": status, "llm_prompt_bank_mode": result.mode, "llm_error": result.llm_error}


@app.post("/api/characters/prompt-bank/local")
def local_prompt_bank(request: CharacterLlmRequest) -> dict[str, Any]:
    logger.info("characters local prompt bank started character_count=%s scene_count=%s", len(request.characters), len(request.scenes))
    cards = parse_character_payload(request.characters)
    scenes = parse_scene_payload(request.scenes)
    for card in cards:
        card.reference_visuals = []
        card.identity_prompt = ""
        card.negative_identity_prompt = ""
        card.appearance_states = []
    result = build_character_prompt_bank(cards, scenes, None, purpose="button:local_prompt_bank")
    logger.info("characters local prompt bank completed character_count=%s mode=%s", len(cards), result.mode)
    return {
        "characters": to_dict(cards),
        "llm_status": f"已改用本地规则生成 {len(cards)} 个角色 Prompt Bank",
        "llm_prompt_bank_mode": result.mode,
        "llm_error": result.llm_error,
    }


@app.post("/api/characters/llm/prompt-bank/references")
async def llm_prompt_bank_with_references(
    characters: Annotated[str, Form()],
    scenes: Annotated[str, Form()] = "[]",
    reference_bindings: Annotated[str | None, Form()] = None,
    reference_images: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, Any]:
    logger.info(
        "characters llm prompt bank with references started reference_images=%s characters_text_length=%s scenes_text_length=%s",
        len(reference_images or []),
        len(characters),
        len(scenes),
    )
    provider = OpenAICompatibleProvider()
    if not provider.config.llm.api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API key")
    cards = parse_character_payload(parse_json_list(characters))
    scene_cards = parse_scene_payload(parse_json_list(scenes))
    run_id = f"prompt-bank-{int(time.time())}"
    run_dir = RUNS / run_id
    refs_dir = run_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)
    bindings = parse_reference_bindings(reference_bindings)
    for upload in reference_images or []:
        original_filename = Path(upload.filename or "reference.png").name
        filename = available_reference_filename(refs_dir, original_filename)
        target = refs_dir / filename
        target.write_bytes(await upload.read())
        url = f"/runs/{run_id}/references/{filename}"
        binding = take_reference_binding(bindings, original_filename)
        bind_reference_image(cards, original_filename, url, binding)
        logger.info("prompt bank reference image saved run_id=%s filename=%s stored_filename=%s binding=%s", run_id, original_filename, filename, redact(binding))

    vlm_status = ""
    if reference_images and provider.config.vlm.api_key:
        analyze_reference_visuals(cards, run_dir, provider, purpose=f"button:{run_id}:vlm_reference_visuals")
        analyzed_count = sum(len(card.reference_visuals) for card in cards)
        if analyzed_count:
            reviewed_count = sum(
                1
                for card in cards
                for item in card.reference_visuals
                if isinstance(item, dict) and item.get("llm_reviewed")
            )
            suffix = f"，其中 {reviewed_count} 组已由 LLM 审查" if reviewed_count else ""
            vlm_status = f"已先用 VLM 分析参考图（提取到 {analyzed_count} 组视觉事实{suffix}）"
        else:
            vlm_status = "已尝试 VLM 分析参考图，但未提取到视觉事实，请检查 VLM 模型是否支持图片输入"
    elif reference_images:
        vlm_status = "未配置 VLM API key，参考图已绑定但无法先做视觉分析"

    result = build_character_prompt_bank(cards, scene_cards, provider, purpose="button:llm_prompt_bank")
    status = prompt_bank_status_text(result, len(cards))
    if vlm_status:
        status = f"{vlm_status}；{status}"
    logger.info(
        "characters llm prompt bank with references completed character_count=%s reference_images=%s mode=%s llm_error=%s",
        len(cards),
        len(reference_images or []),
        result.mode,
        result.llm_error,
    )
    return {
        "characters": to_dict(cards),
        "llm_status": status,
        "llm_prompt_bank_mode": result.mode,
        "llm_error": result.llm_error,
        "run_id": run_id,
    }


@app.post("/api/characters/llm/diff")
def llm_character_diff(request: CharacterLlmRequest) -> dict[str, Any]:
    logger.info("characters llm diff started character_count=%s", len(request.characters))
    provider = OpenAICompatibleProvider()
    if not provider.config.llm.api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API key")
    cards = parse_character_payload(request.characters)
    difference_analysis = analyze_character_differences(cards, provider, purpose="button:llm_character_diff")
    logger.info("characters llm diff completed character_count=%s pair_count=%s", len(cards), len(difference_analysis.get("pairs", [])))
    return {"difference_analysis": difference_analysis, "llm_status": "已完成角色差异分析"}


@app.post("/api/pipeline")
async def pipeline(
    novel: Annotated[UploadFile, File()],
    characters: Annotated[UploadFile, File()],
    reference_images: Annotated[list[UploadFile] | None, File()] = None,
    reference_bindings: Annotated[str | None, Form()] = None,
    manual_characters: Annotated[str | None, Form()] = None,
    prepared_characters: Annotated[str | None, Form()] = None,
    max_shots: Annotated[int, Form()] = 8,
    use_llm: Annotated[bool, Form()] = False,
    llm_profile: Annotated[str, Form()] = "fast",
    llm_concurrency: Annotated[int, Form()] = 3,
    run_id: Annotated[str | None, Form()] = None,
    style_id: Annotated[str | None, Form()] = None,
    style_reference_mode: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    run_id = run_id or str(int(time.time()))
    repository = get_run_repository()
    run_dir = repository.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    novel_text = normalize_novel_text((await novel.read()).decode("utf-8-sig"))
    character_text = (await characters.read()).decode("utf-8-sig")
    if not novel_text.strip():
        logger.warning("pipeline rejected empty novel filename=%s", novel.filename)
        raise HTTPException(status_code=400, detail="小说文件为空，请重新选择包含正文的小说 Markdown")
    if not character_text.strip():
        logger.warning("pipeline rejected empty characters filename=%s", characters.filename)
        raise HTTPException(status_code=400, detail="人设文件为空，请重新选择包含角色设定的 Markdown")
    store = get_visual_preset_store()
    try:
        visual_defaults = bind_defaults(store, {"style_id": style_id, "style_reference_mode": style_reference_mode},
                                       {"composition_id": None})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "pipeline started run_id=%s novel=%s characters=%s reference_images=%s max_shots=%s use_llm=%s llm_profile=%s llm_concurrency=%s",
        run_id,
        novel.filename,
        characters.filename,
        len(reference_images or []),
        max_shots,
        use_llm,
        llm_profile,
        llm_concurrency,
    )
    write_text(run_dir / "novel.md", novel_text)
    write_text(run_dir / "characters.md", character_text)

    prepared_cards = parse_prepared_characters(prepared_characters)
    cards = dedupe_cards(prepared_cards) if prepared_cards else build_character_cards(character_text)
    provider = OpenAICompatibleProvider() if use_llm else None
    full_llm = bool(provider and llm_profile == "full")
    fast_llm = bool(provider and llm_profile != "full")
    if full_llm and not prepared_cards:
        llm_cards, extraction_status = extract_character_cards_with_llm_detailed(character_text, provider, purpose=f"pipeline:{run_id}:extract_characters")
        if llm_cards:
            cards = llm_cards
            logger.info("pipeline llm character extraction applied run_id=%s character_count=%s", run_id, len(cards))
        else:
            logger.warning("pipeline llm character extraction fallback=local run_id=%s status=%s", run_id, extraction_status)
    cards.extend(parse_manual_characters(manual_characters))
    cards = dedupe_cards(cards)
    if full_llm and not prepared_cards:
        cards = enhance_character_cards_with_llm(cards, provider, purpose=f"pipeline:{run_id}:enhance_characters")
    elif fast_llm:
        logger.info("pipeline fast llm reused prepared/local characters run_id=%s prepared_character_count=%s", run_id, len(prepared_cards))
    bindings = parse_reference_bindings(reference_bindings)
    if reference_images:
        refs_dir = run_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        for upload in reference_images:
            original_filename = Path(upload.filename or "reference.png").name
            filename = available_reference_filename(refs_dir, original_filename)
            target = refs_dir / filename
            target.write_bytes(await upload.read())
            url = f"/runs/{run_id}/references/{filename}"
            binding = take_reference_binding(bindings, original_filename)
            bind_reference_image(cards, original_filename, url, binding)
            logger.info("reference image saved run_id=%s filename=%s stored_filename=%s binding=%s", run_id, original_filename, filename, redact(binding))
    if reference_images:
        vlm_provider = provider or OpenAICompatibleProvider()
        if vlm_provider.config.vlm.api_key:
            analyze_reference_visuals(cards, run_dir, vlm_provider, purpose=f"pipeline:{run_id}:vlm_reference_visuals")
    payload = {
        **build_story_payload(novel_text, cards, max_shots=max_shots, provider=provider if full_llm else None,
                              run_id=run_id, llm_concurrency=llm_concurrency, fast_llm=fast_llm),
        "run_id": run_id,
        "storyboard_messages": [], "prompt_feedback_messages": [], "storyboard_versions": {},
        "visual_presets": visual_defaults,
        "html_settings": normalize_html_settings(),
    }
    payload["shots"] = [to_dict(bind_shot(store, Shot(**item), visual_defaults)) for item in payload["shots"]]
    payload["next_shot_number"] = len(payload["shots"]) + 1
    repository.save(run_id, payload)
    logger.info("pipeline completed run_id=%s character_count=%s scene_count=%s shot_count=%s", run_id, len(cards), len(payload["scenes"]), len(payload["shots"]))
    return payload


@app.post("/api/pipeline/task", status_code=status.HTTP_202_ACCEPTED)
async def create_pipeline_task(
    novel: Annotated[UploadFile, File()],
    characters: Annotated[UploadFile, File()],
    reference_images: Annotated[list[UploadFile] | None, File()] = None,
    reference_bindings: Annotated[str | None, Form()] = None,
    manual_characters: Annotated[str | None, Form()] = None,
    prepared_characters: Annotated[str | None, Form()] = None,
    max_shots: Annotated[int, Form()] = 8,
    use_llm: Annotated[bool, Form()] = False,
    llm_profile: Annotated[str, Form()] = "fast",
    llm_concurrency: Annotated[int, Form()] = 3,
    style_id: Annotated[str | None, Form()] = None,
    style_reference_mode: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """读取上传内容后立即返回，后台任务不再依赖请求生命周期。"""
    run_id = f"{int(time.time())}_{time.time_ns() % 1_000_000}"
    novel_data = await novel.read()
    character_data = await characters.read()
    reference_data = [
        (Path(upload.filename or "reference.png").name, await upload.read())
        for upload in (reference_images or [])
    ]

    def work(reporter: TaskReporter) -> dict[str, Any]:
        reporter.update("准备输入", 5, "正在校验小说、人设和参考图")
        novel_upload = UploadFile(filename=novel.filename or "novel.md", file=io.BytesIO(novel_data))
        character_upload = UploadFile(filename=characters.filename or "characters.md", file=io.BytesIO(character_data))
        refs = [UploadFile(filename=name, file=io.BytesIO(content)) for name, content in reference_data]
        reporter.update("生成分镜", 15, "正在解析小说并调用配置的 LLM/VLM")
        result = asyncio.run(pipeline(
            novel_upload, character_upload, refs, reference_bindings, manual_characters,
            prepared_characters, max_shots, use_llm, llm_profile, llm_concurrency, run_id,
            style_id=style_id, style_reference_mode=style_reference_mode,
        ))
        reporter.update("保存 run", 95, "分镜已生成，正在刷新持久化投影")
        return {"run_id": result["run_id"], "shot_count": len(result.get("shots", []))}

    task = get_task_manager().submit(run_id, "pipeline", work, message="完整工作流已进入队列")
    return {"task_id": task["task_id"], "run_id": run_id, "task": task}


def save_storyboard(request: StoryboardSaveRequest) -> dict[str, Any]:
    return get_storyboard_controller().save_storyboard(request)


def generate_storyboard_shot(request: StoryboardGenerateRequest) -> dict[str, Any]:
    return get_storyboard_controller().generate_storyboard_shot(request)


def storyboard_feedback(request: StoryboardFeedbackRequest) -> dict[str, Any]:
    return get_storyboard_controller().storyboard_feedback(request)


def storyboard_prompt_feedback(request: StoryboardPromptFeedbackRequest) -> dict[str, Any]:
    return get_storyboard_controller().storyboard_prompt_feedback(request)


def regenerate_storyboard(request: StoryboardRegenerateRequest) -> dict[str, Any]:
    return get_storyboard_controller().regenerate_storyboard(request)


def restore_storyboard_version(request: StoryboardVersionRequest) -> dict[str, Any]:
    return get_storyboard_controller().restore_storyboard_version(request)


def regenerate_storyboard_prompt(request: StoryboardPromptRequest) -> dict[str, Any]:
    return get_storyboard_controller().regenerate_storyboard_prompt(request)


def _submit_storyboard_task(run_id: str, kind: str, action: Any, message: str) -> dict[str, Any]:
    def work(reporter: TaskReporter) -> dict[str, Any]:
        reporter.update("调用 LLM", 20, message)
        result = action()
        reporter.update("保存分镜", 90, "正在保存分镜、历史版本和对话记录")
        return result

    task = get_task_manager().submit(run_id, kind, work, message=message)
    return {"task_id": task["task_id"], "run_id": run_id, "task": task}


@app.post("/api/storyboard/generate-task", status_code=status.HTTP_202_ACCEPTED)
def create_storyboard_generate_task(request: StoryboardGenerateRequest) -> dict[str, Any]:
    return _submit_storyboard_task(
        request.run_id, "storyboard_generate",
        lambda: generate_storyboard_shot(request), "正在根据原文引用或文本描述生成分镜",
    )


@app.post("/api/storyboard/feedback-task", status_code=status.HTTP_202_ACCEPTED)
def create_storyboard_feedback_task(request: StoryboardFeedbackRequest) -> dict[str, Any]:
    return _submit_storyboard_task(
        request.run_id, "storyboard_feedback",
        lambda: storyboard_feedback(request), "分镜 Agent 正在分析反馈并判断是否需要重新生成",
    )


@app.post("/api/storyboard/regenerate-task", status_code=status.HTTP_202_ACCEPTED)
def create_storyboard_regenerate_task(request: StoryboardRegenerateRequest) -> dict[str, Any]:
    return _submit_storyboard_task(
        request.run_id, "storyboard_regenerate",
        lambda: regenerate_storyboard(request), "正在结合分镜 Agent 反馈重新生成分镜",
    )


@app.post("/api/storyboard/prompt-task", status_code=status.HTTP_202_ACCEPTED)
def create_storyboard_prompt_task(request: StoryboardPromptRequest) -> dict[str, Any]:
    return _submit_storyboard_task(
        request.run_id, "prompt_regenerate",
        lambda: regenerate_storyboard_prompt(request), "正在结合独立 Prompt 反馈重建生图 Prompt",
    )


def get_storyboard_controller() -> StoryboardController:
    # 在请求时解析回调，使测试和本地集成可以替换 provider，
    # 而无需重新构建 FastAPI 应用。
    return StoryboardController(
        StoryboardDependencies(
            repository=get_run_repository,
            require_llm_provider=require_llm_provider,
            parse_character_payload=parse_character_payload,
            generate_or_revise_shot=lambda *args, **kwargs: generate_or_revise_shot_with_llm(*args, **kwargs),
            respond_to_feedback=lambda *args, **kwargs: respond_to_storyboard_feedback(*args, **kwargs),
            polish_prompt=lambda *args, **kwargs: polish_shot_prompt(*args, **kwargs),
            logger=logger,
            bind_visual_presets=lambda shot, payload, old: bind_storyboard_shot(get_visual_preset_store(), shot, payload, old),
        )
    )


def require_llm_provider() -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider()
    if not provider.config.llm.api_key:
        raise HTTPException(status_code=400, detail="未配置 LLM API key")
    return provider


def get_image_workflow() -> ImageWorkflow:
    return ImageWorkflow(get_run_repository(), get_visual_preset_store(), reference_image_entries_for_shot)


def visual_prompt_for_generation(run_id: str, shot: Shot) -> tuple[str, str, dict[str, Any]]:
    try:
        return get_image_workflow().visual_prompt(run_id, shot)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def record_visual_generation(run_id: str, shot: Shot, visual_snapshot: dict[str, Any]) -> None:
    """Legacy Python entrypoint; image persistence now commits this atomically."""
    try:
        with get_run_repository().transaction(run_id, render=False) as payload:
            for item in payload.get("shots", []):
                if item.get("id") == shot.id:
                    item["last_generation_visual_snapshot"] = deepcopy(visual_snapshot)
                    break
    except RunNotFoundError:
        pass


def image_generation_inputs(provider: Any, run_id: str, shot: Shot, size: str):
    try:
        return get_image_workflow().inputs(provider, run_id, shot, size)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/images")
def generate_image(request: ImageRequest) -> dict[str, Any]:
    try:
        return get_image_workflow().generate_single(
            OpenAICompatibleProvider(), request.run_id, Shot(**request.shot),
            size=request.size, overwrite=request.overwrite, activate=request.activate,
        )
    except (ValueError, ProviderError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/images/version")
def select_image_version(request: ImageVersionRequest) -> dict[str, Any]:
    payload = activate_shot_image(request.run_id, request.shot_id, request.image_url)
    logger.info("image version activated run_id=%s shot_id=%s image_url=%s", request.run_id, request.shot_id, request.image_url)
    return payload


@app.post("/api/images/task", status_code=status.HTTP_202_ACCEPTED)
def create_image_task(request: ImageRequest) -> dict[str, Any]:
    def work(reporter: TaskReporter) -> dict[str, Any]:
        reporter.update("调用图片 API", 15, f"正在生成 {request.shot.get('id', '')} 的图片")
        result = generate_image(request)
        reporter.update("保存图片版本", 90, "正在更新图片及版本记录")
        return result

    task = get_task_manager().submit(request.run_id, "image", work, message="图片生成已进入队列")
    return {"task_id": task["task_id"], "run_id": request.run_id, "task": task}


@app.post("/api/images/batch")
def generate_all_images(request: dict[str, Any]) -> dict[str, Any]:
    return _generate_all_images(request)


def _generate_all_images(request: dict[str, Any], reporter: TaskReporter | None = None) -> dict[str, Any]:
    run_id = str(request.get("run_id", "manual"))
    run_dir = run_directory(run_id)
    size = str(request.get("size", "1024x1024"))
    retry_count = max(0, int(request.get("retry_count", 0)))
    skip_existing = bool(request.get("skip_existing", True))
    shots = [Shot(**shot) for shot in request.get("shots", [])]
    results = []
    reference_error = ""
    provider = OpenAICompatibleProvider()
    logger.info("batch image generation started run_id=%s shot_count=%s size=%s retry_count=%s skip_existing=%s", run_id, len(shots), size, retry_count, skip_existing)
    total = max(1, len(shots))
    for index, shot in enumerate(shots, start=1):
        if reporter is not None:
            progress = 10 + int((index - 1) * 80 / total)
            reporter.update("调用图片 API", progress, f"正在处理 {shot.id}（{index}/{len(shots)}）")
        current = current_shot_image(run_id, shot.id)
        if skip_existing and current:
            results.append(
                {
                    "shot_id": shot.id,
                    "ok": True,
                    "skipped": True,
                    "image_path": current.get("image_path"),
                    "image_url": current.get("image_url"),
                    "activated": True,
                }
            )
            logger.info("batch image item skipped existing run_id=%s shot_id=%s", run_id, shot.id)
            continue
        if reference_error:
            results.append({"shot_id": shot.id, "ok": False, "attempts": 0,
                            "error": f"本批次已停止：{reference_error}"})
            continue
        try:
            target = image_target_for_generation(run_dir, shot.id, bool(current))
            result = generate_batch_image_item(provider, run_id, shot, target, size, retry_count, activate=not bool(current))
        except (HTTPException, ValueError) as exc:
            # A stale selection must not discard successful results of other shots.
            result = {"shot_id": shot.id, "ok": False, "attempts": 0,
                      "error": str(exc.detail if isinstance(exc, HTTPException) else exc)}
        if result.get("reference_rejected"):
            # Stop this batch on an explicit rejection; a later request can retry directly.
            reference_error = result["error"]
        results.append(result)
    logger.info("batch image generation completed run_id=%s ok_count=%s total=%s", run_id, len([item for item in results if item["ok"]]), len(results))
    write_json(run_dir / "image_results.json", {"run_id": run_id, "size": size, "retry_count": retry_count, "skip_existing": skip_existing, "results": results})
    return {"results": results}


@app.post("/api/images/batch-task", status_code=status.HTTP_202_ACCEPTED)
def create_batch_image_task(request: dict[str, Any]) -> dict[str, Any]:
    run_id = str(request.get("run_id", "manual"))
    shots = list(request.get("shots", []))

    def work(reporter: TaskReporter) -> dict[str, Any]:
        reporter.update("调用图片 API", 10, f"准备生成 {len(shots)} 张图片")
        result = _generate_all_images(request, reporter)
        reporter.update("保存图片版本", 95, "批量图片结果已保存")
        return result

    task = get_task_manager().submit(run_id, "image_batch", work, message="批量图片生成已进入队列")
    return {"task_id": task["task_id"], "run_id": run_id, "task": task}


def generate_batch_image_item(
    provider: OpenAICompatibleProvider, run_id: str, shot: Shot, target: Path,
    size: str, retry_count: int, activate: bool,
) -> dict[str, Any]:
    return get_image_workflow().generate_item(provider, run_id, shot, target, size, retry_count, activate)


@app.get("/api/export/{run_id}.md", response_class=PlainTextResponse)
def export_markdown(run_id: str) -> str:
    result = build_exported_novel(run_id)
    return result["markdown"]


@app.get("/api/export/{run_id}.html", response_class=HTMLResponse)
def export_html(run_id: str) -> str:
    result = build_exported_novel(run_id)
    return result["html"]


@app.get("/api/export/{run_id}.zip")
def export_zip(run_id: str) -> FileResponse:
    result = build_exported_novel(run_id)
    zip_path = Path(result["zip_path"])
    return FileResponse(
        zip_path,
        filename=f"illustrated_novel-{run_id}.zip",
        media_type="application/zip",
    )


@app.get("/api/export/{run_id}")
def export_markdown_info(run_id: str) -> dict[str, Any]:
    result = build_exported_novel(run_id)
    return {
        "ok": True,
        "markdown_path": result["markdown_path"],
        "markdown_url": result["markdown_url"],
        "export_markdown_url": result["export_markdown_url"],
        "html_path": result["html_path"],
        "html_url": result["html_url"],
        "export_html_url": result["export_html_url"],
        "export_dir": result["export_dir"],
        "images_dir": result["images_dir"],
        "images_url": result["images_url"],
        "manifest_path": result["manifest_path"],
        "manifest_url": result["manifest_url"],
        "theme_path": result["theme_path"],
        "theme_url": result["theme_url"],
        "zip_path": result["zip_path"],
        "zip_url": result["zip_url"],
        "html_settings": result["html_settings"],
        "manifest": result["manifest"],
    }


def build_exported_novel(run_id: str) -> dict[str, Any]:
    repository = get_run_repository()
    run_dir = run_directory(run_id)
    novel_path = run_dir / "novel.md"
    try:
        payload = repository.load(run_id)
    except RunNotFoundError as exc:
        logger.warning("export failed run_id=%s reason=missing_pipeline", run_id)
        raise HTTPException(status_code=404, detail="run 不存在") from exc
    if not novel_path.exists():
        logger.warning("export failed run_id=%s reason=missing_novel", run_id)
        raise HTTPException(status_code=404, detail="小说原文不存在")
    shots = [Shot(**shot) for shot in payload.get("shots", [])]
    bundle = build_export_bundle(
        run_dir,
        run_id,
        read_text(novel_path),
        payload.get("scenes", []),
        shots,
        payload.get("html_settings"),
    )
    logger.info(
        "export completed run_id=%s markdown_path=%s export_dir=%s zip_path=%s image_count=%s",
        run_id,
        bundle.markdown_path,
        bundle.export_dir,
        bundle.zip_path,
        bundle.manifest.get("image_count", 0),
    )
    return {"markdown": bundle.markdown, "html": bundle.html, **bundle.info()}


def current_shot_image(run_id: str, shot_id: str) -> dict[str, Any] | None:
    return get_image_workflow().current_image(run_id, shot_id)


def update_shot_image(
    run_id: str, shot_id: str, image_path: str, image_url: str,
    activate: bool = True, visual_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return get_image_workflow().update_image(run_id, shot_id, image_path, image_url, activate, visual_snapshot)


def activate_shot_image(run_id: str, shot_id: str, image_url: str) -> dict[str, Any]:
    try:
        return get_image_workflow().activate_version(run_id, shot_id, image_url)
    except RunNotFoundError as exc:
        raise HTTPException(404, "run 不存在") from exc
    except ImageSelectionError as exc:
        raise HTTPException(404, str(exc)) from exc


def clean_image_url(run_id: str, shot_id: str) -> str:
    return f"/runs/{run_id}/images/{shot_id}.png"


def versioned_image_url(run_id: str, shot_id: str, target: Path) -> str:
    return versioned_url_for_path(clean_image_url(run_id, shot_id), target)


def reference_image_entries_for_shot(run_id: str, shot: Shot) -> list[tuple[str, list[Path]]]:
    return reference_image_entries(get_run_repository(), run_id, shot)


def reference_image_groups_for_shot(run_id: str, shot: Shot) -> list[list[Path]]:
    return [group for _, group in reference_image_entries_for_shot(run_id, shot)]


def reference_paths_for_shot(run_id: str, shot: Shot) -> list[Path]:
    return [path for group in reference_image_groups_for_shot(run_id, shot) for path in group]


def hydrate_provider_secret(source: dict[str, Any]) -> dict[str, Any]:
    item = dict(source)
    api_key = str(item.get("api_key") or "")
    if api_key.strip() and "..." not in api_key and api_key != "****":
        return item
    source_id = str(item.get("id") or "")
    for stored in read_provider_config(PROVIDERS_FILE, ENV_FILE).get("sources", []):
        if str(stored.get("id") or "") == source_id:
            item["api_key"] = stored.get("api_key") or ""
            break
    return item


# 在兼容依赖定义完成后注册功能 router。controller 负责 HTTP endpoint；
# 上方保留的函数为现有调用方和测试提供稳定的 Python API。
_storyboard_http_controller = get_storyboard_controller()
app.include_router(_storyboard_http_controller.router)
app.include_router(VisualPresetController(VisualPresetDependencies(
    store=lambda: get_visual_preset_store(),
    repository=lambda: get_run_repository(),
    task_manager=lambda: get_visual_task_manager(),
    provider=lambda: OpenAICompatibleProvider(),
    reference_entries=lambda run_id, shot: reference_image_entries_for_shot(run_id, shot),
)).router)
