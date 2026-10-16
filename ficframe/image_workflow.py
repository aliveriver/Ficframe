"""Image generation, reference binding and version persistence, independent of HTTP."""
from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .image_reference_workflow import purpose_prompt, reference_failure, reference_preflight, reference_rejected, visual_paths
from .logging_utils import get_logger
from .models import Shot, to_dict
from .providers import ProviderError
from .run_repository import RunNotFoundError, RunRepository
from .visual_preset_workflow import SELECTION_FIELDS, bind_run_defaults, resolve_generation
from .visual_presets import VisualPresetStore


logger = get_logger("images")


class ImageSelectionError(ValueError):
    """A requested shot or image version is absent from the run."""


def image_target_for_generation(run_dir: Path, shot_id: str, has_current: bool) -> Path:
    if not isinstance(shot_id, str) or not shot_id or shot_id in {".", ".."} or any(char in shot_id for char in '<>:"/\\|?*'):
        raise ValueError("非法分镜 ID")
    name = f"{shot_id}_{uuid4().hex}.png" if has_current else f"{shot_id}.png"
    return run_dir / "images" / name


def image_url_for_path(run_id: str, path: Path) -> str:
    return f"/runs/{run_id}/images/{path.name}"


def versioned_url_for_path(image_url: str, path: Path) -> str:
    version = path.stat().st_mtime_ns if path.exists() else time.time_ns()
    return f"{strip_version_query(image_url)}?v={version}"


def strip_version_query(url: str) -> str:
    return url.split("?", 1)[0]


def reference_regions_for_characters(shot: Shot, character_names: list[str]) -> list[list[float] | None]:
    by_name = {str(item.get("character")): item.get("region") for item in shot.character_layout
               if isinstance(item, dict) and item.get("character")}
    return [by_name.get(name) if isinstance(by_name.get(name), list) else None for name in character_names]


def reference_image_entries(repository: RunRepository, run_id: str, shot: Shot) -> list[tuple[str, list[Path]]]:
    run_dir = repository.run_dir(run_id)
    payload = repository.load(run_id, required=False)
    characters = {str(item["name"]): item for item in payload.get("characters", [])
                  if isinstance(item, dict) and item.get("name")}
    entries = []
    prefix = f"/runs/{run_id}/"
    for name in dict.fromkeys(shot.characters):
        paths = []
        for reference in characters.get(name, {}).get("reference_images", []):
            url = str(reference).split(" (", 1)[0]
            if url.startswith(prefix):
                path = (run_dir / url.removeprefix(prefix)).resolve()
                if run_dir in path.parents and path.is_file():
                    paths.append(path)
        if paths:
            entries.append((name, list(dict.fromkeys(paths))))
    return entries


class ImageWorkflow:
    def __init__(self, repository: RunRepository, store: VisualPresetStore,
                 reference_entries: Callable[[str, Shot], list[tuple[str, list[Path]]]]):
        self.repository = repository
        self.store = store
        self.reference_entries = reference_entries

    def visual_prompt(self, run_id: str, shot: Shot) -> tuple[str, str, dict[str, Any]]:
        if not self.repository.exists(run_id):
            return resolve_generation(self.store, {}, shot)
        # Binding snapshots do not change the Markdown projections.
        with self.repository.transaction(run_id, render=False) as payload:
            payload["visual_presets"] = bind_run_defaults(self.store, payload)
            result = resolve_generation(self.store, payload, shot)
            for item in payload.get("shots", []):
                if item.get("id") == shot.id:
                    item.update({key: to_dict(getattr(shot, key)) for key in SELECTION_FIELDS})
                    break
        return result

    def inputs(self, provider: Any, run_id: str, shot: Shot, size: str):
        prompt, negative, snapshot = self.visual_prompt(run_id, shot)
        entries = self.reference_entries(run_id, shot)
        groups = [group for _, group in entries]
        identities = [path for group in groups for path in group]
        preflight = reference_preflight(self.store, provider, snapshot, len(identities), size)
        if not preflight["ok"]:
            raise ValueError(preflight["message"])
        paths = visual_paths(self.store, snapshot)
        kwargs = {"reference_images": identities, "reference_image_groups": groups,
                  "reference_regions": reference_regions_for_characters(shot, [name for name, _ in entries]),
                  "regional_guidance": shot.regional_guidance}
        kwargs.update({f"{kind}_reference_images": images for kind, images in paths.items() if images})
        prompt = purpose_prompt(prompt, len(identities), len(paths["style"]), len(paths["composition"]))
        snapshot["positive_prompt"] = prompt
        if any(paths.values()):
            kwargs["reference_roles_embedded"] = True
            snapshot["reference_delivery"] = {"identity_count": len(identities), "style_count": len(paths["style"]),
                                              "composition_count": len(paths["composition"]), "capability": preflight,
                                              "order": ["identity", "style", "composition"]}
        return prompt, negative, snapshot, kwargs

    def current_image(self, run_id: str, shot_id: str) -> dict[str, Any] | None:
        payload = self.repository.load(run_id, required=False)
        for shot in payload.get("shots", []):
            if shot.get("id") == shot_id and (shot.get("image_url") or shot.get("image_path")):
                return {"image_url": shot.get("image_url"), "image_path": shot.get("image_path")}
        return None

    def update_image(self, run_id: str, shot_id: str, image_path: str, image_url: str,
                     activate: bool = True, visual_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with self.repository.transaction(run_id) as payload:
                shot = next((item for item in payload.get("shots", []) if item.get("id") == shot_id), None)
                if shot is None:
                    return {}
                versions = shot.setdefault("image_versions", [])
                known_urls = {item.get("image_url") for item in versions if isinstance(item, dict)}
                old_url, old_path = shot.get("image_url"), shot.get("image_path")
                if old_url and old_path and old_url not in known_urls:
                    path = Path(str(old_path))
                    versions.append({"image_path": old_path, "image_url": old_url,
                                     "created_at": int(path.stat().st_mtime) if path.exists() else int(time.time())})
                    known_urls.add(old_url)
                if image_url not in known_urls:
                    version = {"image_path": image_path, "image_url": image_url, "created_at": int(time.time())}
                    if isinstance(visual_snapshot, dict):
                        version["visual_preset_snapshot"] = deepcopy(visual_snapshot)
                    versions.append(version)
                if isinstance(visual_snapshot, dict):
                    shot["last_generation_visual_snapshot"] = deepcopy(visual_snapshot)
                if activate:
                    shot.update(image_path=image_path, image_url=image_url)
                return {"shot_id": shot_id, "image_path": shot.get("image_path"),
                        "image_url": shot.get("image_url"), "image_versions": versions}
        except RunNotFoundError:
            return {}

    def activate_version(self, run_id: str, shot_id: str, image_url: str) -> dict[str, Any]:
        with self.repository.transaction(run_id) as payload:
            shot = next((item for item in payload.get("shots", []) if item.get("id") == shot_id), None)
            if shot is None:
                raise ImageSelectionError("未找到该分镜")
            versions = shot.get("image_versions", [])
            version = next((item for item in versions if isinstance(item, dict)
                            and strip_version_query(str(item.get("image_url") or "")) == strip_version_query(image_url)), None)
            if version is None:
                raise ImageSelectionError("未找到该图片版本")
            shot.update(image_url=version.get("image_url"), image_path=version.get("image_path"))
            return {"shot_id": shot_id, "image_path": shot.get("image_path"),
                    "image_url": versioned_url_for_path(str(shot.get("image_url")), Path(str(shot.get("image_path")))),
                    "raw_image_url": shot.get("image_url"), "image_versions": versions}

    def generate_item(self, provider: Any, run_id: str, shot: Shot, target: Path, size: str,
                      retry_count: int = 0, activate: bool = True, *, mode: str = "batch") -> dict[str, Any]:
        retry_count = max(0, retry_count)
        prompt, negative, snapshot, kwargs = self.inputs(provider, run_id, shot, size)
        last_error = ""
        for attempt in range(1, retry_count + 2):
            try:
                purpose = f"image:{mode}:{run_id}:{shot.id}" + (f":attempt{attempt}" if mode == "batch" else "")
                provider.image(prompt, target, size=size, negative_prompt=negative, **kwargs, purpose=purpose)
                image_url = image_url_for_path(run_id, target)
                saved = self.update_image(run_id, shot.id, str(target), image_url, activate, snapshot)
                logger.info("image completed run_id=%s shot_id=%s attempt=%s activated=%s", run_id, shot.id, attempt, activate)
                return {"shot_id": shot.id, "ok": True, "attempts": attempt,
                        "image_path": str(target), "image_url": versioned_url_for_path(image_url, target),
                        "raw_image_url": image_url, "activated": activate,
                        "image_versions": saved.get("image_versions", []), "visual_preset_snapshot": snapshot,
                        "visual_prompt": prompt, "visual_negative_prompt": negative}
            except ProviderError as exc:
                last_error = reference_failure(self.store, provider, size, exc) if kwargs.get("reference_roles_embedded") else str(exc)
                logger.warning("image failed run_id=%s shot_id=%s attempt=%s error=%s", run_id, shot.id, attempt, last_error)
                if kwargs.get("reference_roles_embedded") and reference_rejected(exc):
                    break
                if attempt <= retry_count:
                    time.sleep(min(2 * attempt, 6))
        return {"shot_id": shot.id, "ok": False, "attempts": attempt, "error": last_error}

    def generate_single(self, provider: Any, run_id: str, shot: Shot, *, size: str, overwrite: bool,
                        activate: bool | None) -> dict[str, Any]:
        current = self.current_image(run_id, shot.id)
        target = image_target_for_generation(self.repository.run_dir(run_id), shot.id, bool(current))
        if current and not overwrite:
            return {"image_path": current.get("image_path"),
                    "image_url": current.get("image_url") or f"/runs/{run_id}/images/{shot.id}.png",
                    "skipped": True, "activated": True}
        result = self.generate_item(provider, run_id, shot, target, size,
                                    activate=activate if activate is not None else not bool(current), mode="single")
        if not result["ok"]:
            raise ProviderError(result["error"])
        return {key: value for key, value in result.items() if key not in {"shot_id", "ok", "attempts"}}
