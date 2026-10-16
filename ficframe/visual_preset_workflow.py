"""Version-pinned visual selections and provider-independent prompt assembly."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .features import visual_preset_kinds
from .models import Shot, to_dict
from .visual_presets import VisualPresetStore, build_visual_prompt, preset_snapshot, validate_reference_mode

KINDS = ("style", "composition")
SELECTION_FIELDS = tuple(f"{kind}_preset_{field}" for kind in KINDS for field in ("id", "mode", "snapshot")) + tuple(f"{kind}_reference_mode" for kind in KINDS)


def select_snapshot(store: VisualPresetStore, kind: str, selected_id: str | None,
                    previous: dict[str, Any] | None = None, *, refresh: bool = False) -> dict[str, Any]:
    if not selected_id:
        return {}
    if not refresh and isinstance(previous, dict) and previous.get("id") == selected_id and previous.get("type") == kind:
        return deepcopy(previous)
    item = store.get(selected_id)
    if not item or item.get("type") != kind:
        raise ValueError(f"{kind} 预设不存在或类型不匹配，请重新选择")
    return deepcopy(preset_snapshot(item))


def bind_defaults(store: VisualPresetStore, selections: dict[str, Any], previous: dict[str, Any] | None = None,
                  *, refresh: bool = False) -> dict[str, Any]:
    previous = previous or {}
    # Preserve dormant bindings without resolving their presets or references.
    result: dict[str, Any] = deepcopy(previous)
    for kind in visual_preset_kinds():
        selected_id = selections.get(f"{kind}_id") or None
        result[f"{kind}_id"] = selected_id
        result[f"{kind}_snapshot"] = select_snapshot(store, kind, selected_id, previous.get(f"{kind}_snapshot"), refresh=refresh)
        fallback = previous.get(f"{kind}_reference_mode", "text") if selected_id == previous.get(f"{kind}_id") else result[f"{kind}_snapshot"].get("reference_mode", "text")
        result[f"{kind}_reference_mode"] = validate_reference_mode(selections.get(f"{kind}_reference_mode") or fallback)
        if result[f"{kind}_snapshot"]:
            result[f"{kind}_snapshot"]["reference_mode"] = result[f"{kind}_reference_mode"]
    return result


def bind_shot(store: VisualPresetStore, shot: Shot, defaults: dict[str, Any], previous: dict[str, Any] | None = None,
              *, refresh: bool = False) -> Shot:
    previous = previous or {}
    active_kinds = visual_preset_kinds()
    for kind in KINDS:
        if kind not in active_kinds:
            # Older or minimal clients may omit hidden controls when saving.
            for key in SELECTION_FIELDS:
                if key.startswith(f"{kind}_") and key in previous:
                    setattr(shot, key, deepcopy(previous[key]))
            continue
        mode = getattr(shot, f"{kind}_preset_mode") or "inherit"
        if mode not in {"inherit", "none", "preset"}:
            raise ValueError("规范选择必须是继承、指定预设或不使用")
        selected_id = getattr(shot, f"{kind}_preset_id")
        if mode == "preset":
            if not selected_id:
                raise ValueError("请指定预设 ID")
            old = previous.get(f"{kind}_preset_snapshot") if previous.get(f"{kind}_preset_mode", "inherit") == mode and previous.get(f"{kind}_preset_id") == selected_id else None
            snapshot = select_snapshot(store, kind, selected_id, old, refresh=refresh)
        elif mode == "inherit":
            selected_id = None
            snapshot = select_snapshot(store, kind, defaults.get(f"{kind}_id"), defaults.get(f"{kind}_snapshot"))
        else:
            selected_id = None
            snapshot = {}
        delivery = validate_reference_mode(getattr(shot, f"{kind}_reference_mode"), inherit=True)
        if snapshot:
            snapshot["reference_mode"] = validate_reference_mode(defaults.get(f"{kind}_reference_mode") if delivery == "inherit" else delivery)
        setattr(shot, f"{kind}_preset_mode", mode)
        setattr(shot, f"{kind}_preset_id", selected_id)
        setattr(shot, f"{kind}_preset_snapshot", snapshot)
    return shot


def bind_run_defaults(store: VisualPresetStore, payload: dict[str, Any], selections: dict[str, Any] | None = None,
                      *, refresh: bool = False) -> dict[str, Any]:
    """Preserve bindings from early ID-only runs when a snapshot is available."""
    previous = deepcopy(payload.get("visual_presets") or {})
    for kind in visual_preset_kinds():
        selected_id = previous.get(f"{kind}_id")
        if not selected_id or previous.get(f"{kind}_snapshot"):
            continue
        for item in payload.get("shots", []):
            if item.get(f"{kind}_preset_mode", "inherit") != "inherit":
                continue
            snapshot = item.get(f"{kind}_preset_snapshot") or item.get("last_generation_visual_snapshot", {}).get(kind)
            if isinstance(snapshot, dict) and snapshot.get("id") == selected_id and snapshot.get("type") == kind:
                previous[f"{kind}_snapshot"] = snapshot
                break
    return bind_defaults(store, previous if selections is None else selections, previous, refresh=refresh)


def bind_storyboard_shot(store: VisualPresetStore, shot: Shot, payload: dict[str, Any], previous: dict[str, Any]) -> Shot:
    payload["visual_presets"] = bind_run_defaults(store, payload)
    return bind_shot(store, shot, payload["visual_presets"], previous)


def resolve_generation(store: VisualPresetStore, payload: dict[str, Any], shot: Shot) -> tuple[str, str, dict[str, Any]]:
    defaults = bind_run_defaults(store, payload)
    previous = next((item for item in payload.get("shots", []) if item.get("id") == shot.id), to_dict(shot))
    bind_shot(store, shot, defaults, previous)
    active_kinds = visual_preset_kinds()
    snapshot = {kind: deepcopy(getattr(shot, f"{kind}_preset_snapshot")) if kind in active_kinds else {} for kind in KINDS}
    positive, negative = build_visual_prompt(shot.positive_prompt, shot.negative_prompt, snapshot["style"], snapshot["composition"])
    snapshot.update({"assembly_version": 2, "positive_prompt": positive, "negative_prompt": negative})
    return positive, negative, snapshot
