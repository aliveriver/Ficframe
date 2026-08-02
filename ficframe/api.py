from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .characters import build_character_cards
from .config_store import public_config, public_provider_config, read_provider_config, write_env_file, write_provider_config
from .continuity import initial_state
from .io import read_text, write_json, write_text
from .llm_pipeline import polish_shot_prompt, summarize_scene_with_llm
from .logging_utils import build_log_bundle, get_logger, redact, setup_logging
from .models import Shot, to_dict
from .providers import OpenAICompatibleProvider, ProviderError, build_url, effective_image_provider
from .qa import annotate_shots
from .render import render_illustrated_novel, render_prompts, render_storyboard
from .segmenter import segment_novel
from .storyboard import build_storyboard


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RUNS = ROOT / "outputs" / "web-runs"
ENV_FILE = ROOT / ".env"
PROVIDERS_FILE = ROOT / ".ficframe" / "providers.json"
RUNS.mkdir(parents=True, exist_ok=True)
LOGS = setup_logging(ROOT)
logger = get_logger("api")

app = FastAPI(title="FicFrame API")
app.mount("/assets", StaticFiles(directory=WEB), name="assets")
app.mount("/runs", StaticFiles(directory=RUNS), name="runs")


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


class ConfigRequest(BaseModel):
    values: dict[str, str]


class ProvidersRequest(BaseModel):
    config: dict[str, Any]


class ProviderTestRequest(BaseModel):
    source: dict[str, Any]


class CharacterPreviewRequest(BaseModel):
    text: str


class LogBundleRequest(BaseModel):
    run_id: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    config = OpenAICompatibleProvider().config
    return {
        "ok": True,
        "keys": {
            "llm": bool(config.llm.api_key),
            "image": bool(config.image.api_key),
        },
        "base_urls": {
            "llm": config.llm.base_url,
            "image": config.image.base_url,
        },
        "models": {
            "llm": config.llm.model,
            "image": config.image.model,
        },
        "providers": {
            "image": effective_image_provider(config.image),
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


@app.post("/api/logs/export")
def export_logs(request: LogBundleRequest) -> FileResponse:
    config = public_provider_config(PROVIDERS_FILE, ENV_FILE)
    bundle = build_log_bundle(ROOT, config=config, active_run_id=request.run_id)
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
    write_provider_config(PROVIDERS_FILE, ENV_FILE, request.config)
    sources = request.config.get("sources", []) if isinstance(request.config, dict) else []
    logger.info("providers saved source_count=%s active=%s", len(sources), redact(request.config.get("active", {})))
    return {"ok": True, "config": public_provider_config(PROVIDERS_FILE, ENV_FILE)}


@app.post("/api/providers/test")
def test_provider(request: ProviderTestRequest) -> dict[str, Any]:
    source = hydrate_provider_secret(request.source)
    base_url = str(source.get("base_url") or "").strip().rstrip("/")
    api_key = str(source.get("api_key") or "").strip()
    if not base_url:
        logger.warning("provider test failed reason=missing_base source=%s", redact(source))
        raise HTTPException(status_code=400, detail="请先填写请求地址")
    if not api_key:
        logger.warning("provider test failed reason=missing_key source=%s", redact(source))
        raise HTTPException(status_code=400, detail="请先填写 API key")

    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.perf_counter()
    model_url = build_url(base_url, "models")
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(model_url, headers=headers)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code < 400:
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                count = len(data.get("data", [])) if isinstance(data, dict) and isinstance(data.get("data"), list) else None
                result = {
                    "ok": True,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": f"/models 可达{f'，模型数 {count}' if count is not None else ''}",
                }
                logger.info("provider test ok source_id=%s kind=%s provider=%s status=%s latency_ms=%s", source.get("id"), source.get("kind"), source.get("provider"), response.status_code, latency_ms)
                return result
            if response.status_code not in {404, 405}:
                result = {
                    "ok": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": response.text[:500] or response.reason_phrase,
                }
                logger.warning("provider test http_error source_id=%s status=%s latency_ms=%s message=%s", source.get("id"), response.status_code, latency_ms, result["message"])
                return result

            fallback = client.get(base_url, headers=headers)
            fallback_latency_ms = int((time.perf_counter() - started) * 1000)
            result = {
                "ok": fallback.status_code < 500,
                "status_code": fallback.status_code,
                "latency_ms": fallback_latency_ms,
                "message": "服务可达，但该供应商可能不支持 /models" if fallback.status_code < 500 else fallback.text[:500],
            }
            logger.info("provider test fallback source_id=%s status=%s latency_ms=%s ok=%s", source.get("id"), fallback.status_code, fallback_latency_ms, result["ok"])
            return result
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("provider test exception source_id=%s error=%s", source.get("id"), exc)
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": str(exc),
        }


@app.post("/api/characters/preview")
def preview_characters(request: CharacterPreviewRequest) -> dict[str, Any]:
    cards = build_character_cards(request.text)
    logger.info("characters preview character_count=%s text_length=%s", len(cards), len(request.text))
    return {"characters": to_dict(cards)}


@app.post("/api/pipeline")
async def pipeline(
    novel: Annotated[UploadFile, File()],
    characters: Annotated[UploadFile, File()],
    reference_images: Annotated[list[UploadFile] | None, File()] = None,
    reference_bindings: Annotated[str | None, Form()] = None,
    max_shots: Annotated[int, Form()] = 8,
    use_llm: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    run_id = str(int(time.time()))
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    novel_text = (await novel.read()).decode("utf-8-sig")
    character_text = (await characters.read()).decode("utf-8-sig")
    logger.info(
        "pipeline started run_id=%s novel=%s characters=%s reference_images=%s max_shots=%s use_llm=%s",
        run_id,
        novel.filename,
        characters.filename,
        len(reference_images or []),
        max_shots,
        use_llm,
    )
    write_text(run_dir / "novel.md", novel_text)
    write_text(run_dir / "characters.md", character_text)

    cards = build_character_cards(character_text)
    bindings = parse_reference_bindings(reference_bindings)
    if reference_images:
        refs_dir = run_dir / "references"
        refs_dir.mkdir(parents=True, exist_ok=True)
        for upload in reference_images:
            filename = Path(upload.filename or "reference.png").name
            target = refs_dir / filename
            target.write_bytes(await upload.read())
            url = f"/runs/{run_id}/references/{filename}"
            binding = bindings.get(filename, {})
            bind_reference_image(cards, filename, url, binding)
            logger.info("reference image saved run_id=%s filename=%s binding=%s", run_id, filename, redact(binding))
    scenes = segment_novel(novel_text, cards)
    provider = OpenAICompatibleProvider() if use_llm else None
    if provider:
        scenes = [summarize_scene_with_llm(scene, provider) for scene in scenes]
    state = initial_state(cards)
    shots, state = build_storyboard(scenes, cards, state, max_shots=max_shots)
    annotate_shots(shots, cards)
    if provider:
        shots = [polish_shot_prompt(shot, cards, provider) for shot in shots]

    payload = {
        "run_id": run_id,
        "characters": to_dict(cards),
        "scenes": to_dict(scenes),
        "shots": to_dict(shots),
        "continuity": to_dict(state),
    }
    write_json(run_dir / "pipeline.json", payload)
    write_json(run_dir / "continuity.json", payload["continuity"])
    write_text(run_dir / "storyboard.md", render_storyboard(shots))
    write_text(run_dir / "prompts.md", render_prompts(shots))
    logger.info("pipeline completed run_id=%s character_count=%s scene_count=%s shot_count=%s", run_id, len(cards), len(scenes), len(shots))
    return payload


@app.post("/api/images")
def generate_image(request: ImageRequest) -> dict[str, Any]:
    shot = Shot(**request.shot)
    provider = OpenAICompatibleProvider()
    target = RUNS / request.run_id / "images" / f"{shot.id}.png"
    if target.exists() and not request.overwrite:
        image_url = f"/runs/{request.run_id}/images/{shot.id}.png"
        update_shot_image(request.run_id, shot.id, str(target), image_url)
        logger.info("image generation skipped existing run_id=%s shot_id=%s path=%s", request.run_id, shot.id, target)
        return {"image_path": str(target), "image_url": image_url, "skipped": True}
    try:
        references = reference_paths_for_shot(request.run_id, shot)
        logger.info("image generation started run_id=%s shot_id=%s size=%s reference_count=%s", request.run_id, shot.id, request.size, len(references))
        provider.image(shot.positive_prompt, target, size=request.size, reference_images=references)
    except ProviderError as exc:
        logger.warning("image generation failed run_id=%s shot_id=%s error=%s", request.run_id, shot.id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    image_url = f"/runs/{request.run_id}/images/{shot.id}.png"
    update_shot_image(request.run_id, shot.id, str(target), image_url)
    logger.info("image generation completed run_id=%s shot_id=%s path=%s", request.run_id, shot.id, target)
    return {"image_path": str(target), "image_url": image_url}


@app.post("/api/images/batch")
def generate_all_images(request: dict[str, Any]) -> dict[str, Any]:
    run_id = str(request.get("run_id", "manual"))
    size = str(request.get("size", "1024x1024"))
    retry_count = max(0, int(request.get("retry_count", 0)))
    skip_existing = bool(request.get("skip_existing", True))
    shots = [Shot(**shot) for shot in request.get("shots", [])]
    results = []
    provider = OpenAICompatibleProvider()
    logger.info("batch image generation started run_id=%s shot_count=%s size=%s retry_count=%s skip_existing=%s", run_id, len(shots), size, retry_count, skip_existing)
    for shot in shots:
        target = RUNS / run_id / "images" / f"{shot.id}.png"
        if skip_existing and target.exists():
            image_url = f"/runs/{run_id}/images/{shot.id}.png"
            update_shot_image(run_id, shot.id, str(target), image_url)
            results.append({"shot_id": shot.id, "ok": True, "skipped": True, "image_path": str(target), "image_url": image_url})
            logger.info("batch image item skipped existing run_id=%s shot_id=%s", run_id, shot.id)
            continue
        result = generate_batch_image_item(provider, run_id, shot, target, size, retry_count)
        results.append(result)
    logger.info("batch image generation completed run_id=%s ok_count=%s total=%s", run_id, len([item for item in results if item["ok"]]), len(results))
    write_json(RUNS / run_id / "image_results.json", {"run_id": run_id, "size": size, "retry_count": retry_count, "skip_existing": skip_existing, "results": results})
    return {"results": results}


def generate_batch_image_item(
    provider: OpenAICompatibleProvider,
    run_id: str,
    shot: Shot,
    target: Path,
    size: str,
    retry_count: int,
) -> dict[str, Any]:
    references = reference_paths_for_shot(run_id, shot)
    last_error = ""
    for attempt in range(retry_count + 1):
        try:
            provider.image(shot.positive_prompt, target, size=size, reference_images=references)
            image_url = f"/runs/{run_id}/images/{shot.id}.png"
            update_shot_image(run_id, shot.id, str(target), image_url)
            logger.info("batch image item completed run_id=%s shot_id=%s reference_count=%s attempt=%s", run_id, shot.id, len(references), attempt + 1)
            return {"shot_id": shot.id, "ok": True, "attempts": attempt + 1, "image_path": str(target), "image_url": image_url}
        except ProviderError as exc:
            last_error = str(exc)
            logger.warning("batch image item failed run_id=%s shot_id=%s attempt=%s error=%s", run_id, shot.id, attempt + 1, exc)
            if attempt < retry_count:
                time.sleep(min(2 * (attempt + 1), 6))
    return {"shot_id": shot.id, "ok": False, "attempts": retry_count + 1, "error": last_error}


@app.get("/api/export/{run_id}.md", response_class=PlainTextResponse)
def export_markdown(run_id: str) -> str:
    result = build_exported_novel(run_id)
    return result["markdown"]


@app.get("/api/export/{run_id}")
def export_markdown_info(run_id: str) -> dict[str, Any]:
    result = build_exported_novel(run_id)
    return {
        "ok": True,
        "markdown_path": result["markdown_path"],
        "markdown_url": result["markdown_url"],
    }


def build_exported_novel(run_id: str) -> dict[str, str]:
    pipeline_path = RUNS / run_id / "pipeline.json"
    novel_path = RUNS / run_id / "novel.md"
    if not pipeline_path.exists():
        logger.warning("export failed run_id=%s reason=missing_pipeline", run_id)
        raise HTTPException(status_code=404, detail="run 不存在")
    if not novel_path.exists():
        logger.warning("export failed run_id=%s reason=missing_novel", run_id)
        raise HTTPException(status_code=404, detail="小说原文不存在")
    payload = json.loads(read_text(pipeline_path))
    shots = [Shot(**shot) for shot in payload.get("shots", [])]
    markdown = render_illustrated_novel(
        read_text(novel_path),
        payload.get("scenes", []),
        shots,
        run_id,
    )
    markdown_path = RUNS / run_id / "illustrated_novel.md"
    write_text(markdown_path, markdown)
    logger.info("export completed run_id=%s markdown_path=%s", run_id, markdown_path)
    return {
        "markdown": markdown,
        "markdown_path": str(markdown_path),
        "markdown_url": f"/runs/{run_id}/illustrated_novel.md",
    }


def update_shot_image(run_id: str, shot_id: str, image_path: str, image_url: str) -> None:
    pipeline_path = RUNS / run_id / "pipeline.json"
    if not pipeline_path.exists():
        return
    payload = json.loads(read_text(pipeline_path))
    for shot in payload.get("shots", []):
        if shot.get("id") == shot_id:
            shot["image_path"] = image_path
            shot["image_url"] = image_url
    write_json(pipeline_path, payload)


def reference_paths_for_shot(run_id: str, shot: Shot) -> list[Path]:
    pipeline_path = RUNS / run_id / "pipeline.json"
    if not pipeline_path.exists():
        return []
    payload = json.loads(read_text(pipeline_path))
    paths: list[Path] = []
    for character in payload.get("characters", []):
        if character.get("name") not in shot.characters:
            continue
        for reference in character.get("reference_images", []):
            url = str(reference).split(" (", 1)[0]
            prefix = f"/runs/{run_id}/"
            if url.startswith(prefix):
                local_path = RUNS / run_id / url.removeprefix(prefix)
                if local_path.exists():
                    paths.append(local_path)
    return list(dict.fromkeys(paths))


def parse_reference_bindings(raw: str | None) -> dict[str, dict[str, str]]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in data:
        if isinstance(item, dict) and item.get("filename"):
            result[str(item["filename"])] = {str(key): str(value) for key, value in item.items() if value is not None}
    return result


def bind_reference_image(cards: list[Any], filename: str, url: str, binding: dict[str, str]) -> None:
    enabled = binding.get("enabled", "true").lower() != "false"
    if not enabled:
        return
    target_name = binding.get("character", "").strip()
    ref_type = binding.get("type", "").strip()
    note = binding.get("note", "").strip()
    value = url
    if ref_type or note:
        meta = "；".join(item for item in [ref_type, note] if item)
        value = f"{url} ({meta})"
    if target_name:
        for card in cards:
            if card.name == target_name:
                card.reference_images.append(value)
                return
    stem = Path(filename).stem.lower()
    for card in cards:
        names = [card.name, *card.aliases]
        if any(name and name.lower() in stem for name in names):
            card.reference_images.append(value)
            return
    if len(cards) == 1:
        cards[0].reference_images.append(value)


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
