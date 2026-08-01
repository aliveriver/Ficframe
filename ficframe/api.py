from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .characters import build_character_cards
from .config_store import public_config, write_env_file
from .continuity import initial_state
from .io import read_text, write_json, write_text
from .llm_pipeline import polish_shot_prompt, summarize_scene_with_llm
from .models import Shot, to_dict
from .providers import OpenAICompatibleProvider, ProviderError, effective_image_provider
from .qa import annotate_shots
from .render import render_illustrated_novel, render_prompts, render_storyboard
from .segmenter import segment_novel
from .storyboard import build_storyboard


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RUNS = ROOT / "outputs" / "web-runs"
ENV_FILE = ROOT / ".env"
RUNS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FicFrame API")
app.mount("/assets", StaticFiles(directory=WEB), name="assets")
app.mount("/runs", StaticFiles(directory=RUNS), name="runs")


class ImageRequest(BaseModel):
    shot: dict[str, Any]
    run_id: str = "manual"
    size: str = "1024x1024"


class VlmRequest(BaseModel):
    image_path: str
    shot: dict[str, Any]


class ConfigRequest(BaseModel):
    values: dict[str, str]


class CharacterPreviewRequest(BaseModel):
    text: str


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
            "image": effective_image_provider(config.image),
        },
    }


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {"values": public_config(ENV_FILE, reveal_keys=False)}


@app.post("/api/config")
def save_config(request: ConfigRequest) -> dict[str, Any]:
    write_env_file(ENV_FILE, request.values)
    return {"ok": True, "values": public_config(ENV_FILE, reveal_keys=False)}


@app.post("/api/characters/preview")
def preview_characters(request: CharacterPreviewRequest) -> dict[str, Any]:
    cards = build_character_cards(request.text)
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
    return payload


@app.post("/api/images")
def generate_image(request: ImageRequest) -> dict[str, Any]:
    shot = Shot(**request.shot)
    provider = OpenAICompatibleProvider()
    target = RUNS / request.run_id / "images" / f"{shot.id}.png"
    try:
        references = reference_paths_for_shot(request.run_id, shot)
        provider.image(shot.positive_prompt, target, size=request.size, reference_images=references)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    image_url = f"/runs/{request.run_id}/images/{shot.id}.png"
    update_shot_image(request.run_id, shot.id, str(target), image_url)
    return {"image_path": str(target), "image_url": image_url}


@app.post("/api/images/batch")
def generate_all_images(request: dict[str, Any]) -> dict[str, Any]:
    run_id = str(request.get("run_id", "manual"))
    size = str(request.get("size", "1024x1024"))
    shots = [Shot(**shot) for shot in request.get("shots", [])]
    results = []
    provider = OpenAICompatibleProvider()
    for shot in shots:
        target = RUNS / run_id / "images" / f"{shot.id}.png"
        try:
            references = reference_paths_for_shot(run_id, shot)
            provider.image(shot.positive_prompt, target, size=size, reference_images=references)
            image_url = f"/runs/{run_id}/images/{shot.id}.png"
            update_shot_image(run_id, shot.id, str(target), image_url)
            results.append({"shot_id": shot.id, "ok": True, "image_path": str(target), "image_url": image_url})
        except ProviderError as exc:
            results.append({"shot_id": shot.id, "ok": False, "error": str(exc)})
    return {"results": results}


@app.get("/api/export/{run_id}.md", response_class=PlainTextResponse)
def export_markdown(run_id: str) -> str:
    pipeline_path = RUNS / run_id / "pipeline.json"
    novel_path = RUNS / run_id / "novel.md"
    if not pipeline_path.exists():
        raise HTTPException(status_code=404, detail="run 不存在")
    if not novel_path.exists():
        raise HTTPException(status_code=404, detail="小说原文不存在")
    payload = json.loads(read_text(pipeline_path))
    shots = [Shot(**shot) for shot in payload.get("shots", [])]
    markdown = render_illustrated_novel(
        read_text(novel_path),
        payload.get("scenes", []),
        shots,
        run_id,
    )
    write_text(RUNS / run_id / "illustrated_novel.md", markdown)
    return markdown


@app.post("/api/vlm")
async def vlm_check(
    image: Annotated[UploadFile, File()],
    shot_json: Annotated[str, Form()],
) -> dict[str, Any]:
    shot = json.loads(shot_json)
    image_bytes = await image.read()
    mime_type = image.content_type or mimetypes.guess_type(image.filename or "")[0] or "image/png"
    prompt = (
        "你是小说配图质检员。请检查这张图是否符合分镜。"
        "输出 JSON，字段为 pass(boolean), score(0-100), issues(array), fixes(array), observed(string)。\n"
        f"分镜：{json.dumps(shot, ensure_ascii=False)}"
    )
    try:
        raw = OpenAICompatibleProvider().vision(prompt, image_bytes, mime_type)
        data = json.loads(raw)
    except (ProviderError, json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data


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
