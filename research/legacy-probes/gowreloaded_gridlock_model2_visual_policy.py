#!/usr/bin/env python3
"""Shared visual-layer policy for Gridlock's source-renderable Model_2 BSP.

The source package proves Model_2 is referenced by ModelComponents and has a real
FBspSurf material ref, but Blender A/B renders proved it contributes almost
nothing to the visual Gridlock scene while its exact UE3 shader route remains
unresolved. Keep it as hidden source-native proof, not as visible map shell.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL_RE = re.compile(r"^Model_\d+__MP_Gridlock\.war__\d+", re.IGNORECASE)
DIAGNOSTIC_COLLECTION = "00_DIAGNOSTICS_SourceRenderable_BSP_Hidden_PendingExactUE3Shader"
POLICY_NAME = "hidden_redundant_source_renderable_bsp_pending_exact_ue3_shader"
DIFF_PROOF = SCENE_DIR / "gridlock_model2_visibility_diff_image_compare_2026_08_15.json"
HIDE_PROOF = SCENE_DIR / "gridlock_model2_hidden_as_redundant_bsp_2026_08_15.json"
COMPONENT_PROOF = SCENE_DIR / "gridlock_modelcomponent_visibility_probe_2026_08_15.json"
MODEL2_REF_PROOF = SCENE_DIR / "gridlock_model2_modelcomponent_ref_probe_2026_08_15.json"
SURFACE_PROOF = SCENE_DIR / "gridlock_model2_bsp_surface_probe_2026_08_15.json"


def _collection_names(obj: Any) -> list[str]:
    return [collection.name for collection in getattr(obj, "users_collection", [])]


def get_collection(bpy: Any, name: str) -> Any:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def link_once(obj: Any, collection: Any) -> None:
    if obj.name not in [item.name for item in collection.objects]:
        collection.objects.link(obj)


def unlink_from_collection(obj: Any, collection: Any) -> None:
    try:
        collection.objects.unlink(obj)
    except Exception:
        pass


def walk_layer_collections(layer_collection: Any):
    yield layer_collection
    for child in layer_collection.children:
        yield from walk_layer_collections(child)


def set_layer_collection_state(bpy: Any, name: str, hide: bool = True, exclude: bool = False) -> None:
    for view_layer in bpy.context.scene.view_layers:
        for layer_collection in walk_layer_collections(view_layer.layer_collection):
            if layer_collection.collection.name == name:
                layer_collection.hide_viewport = hide
                layer_collection.exclude = exclude


def set_native_uv_active(obj: Any) -> str:
    if obj is None or getattr(obj, "type", "") != "MESH":
        return ""
    mesh = obj.data
    for uv_name in ("UV_Source_BSP_RenderTexCoord", "UV_Source_BSP_Surface"):
        uv = mesh.uv_layers.get(uv_name)
        if uv is None:
            continue
        mesh.uv_layers.active = uv
        try:
            uv.active_render = True
        except Exception:
            pass
        return uv_name
    return ""


def visible_gridlock_model_objects(bpy: Any) -> list[str]:
    return [
        obj.name
        for obj in bpy.data.objects
        if MODEL_RE.match(obj.name) and not obj.hide_viewport and not obj.hide_render
    ]


def apply_model2_visual_policy(
    bpy: Any,
    obj: Any | None = None,
    *,
    reason: str = "",
    move_to_diagnostic_collection: bool = True,
) -> dict[str, Any]:
    if obj is None:
        obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None:
        return {"status": "missing", "object": MODEL2_OBJECT, "reason": reason}

    before_collections = _collection_names(obj)
    active_uv = set_native_uv_active(obj)
    diagnostic = get_collection(bpy, DIAGNOSTIC_COLLECTION)
    link_once(obj, diagnostic)

    if move_to_diagnostic_collection:
        for collection in list(obj.users_collection):
            if collection.name != DIAGNOSTIC_COLLECTION:
                unlink_from_collection(obj, collection)
        link_once(obj, diagnostic)

    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"
    obj["gridlock_visual_layer_policy"] = POLICY_NAME
    obj["gridlock_model2_source_truth"] = (
        "Referenced by 39 ModelComponents and material-backed in source, but hidden from the normal "
        "Blender visual layer because A/B render proof showed only ~0.017% pixel contribution and "
        "the exact UE3 BSP shader route is not needed for the game-accurate visible shell."
    )
    obj["gridlock_model2_policy_reason"] = reason
    obj["gridlock_model2_visibility_diff_proof"] = str(DIFF_PROOF)
    obj["gridlock_model2_hidden_policy_proof"] = str(HIDE_PROOF)
    obj["gridlock_model2_component_probe"] = str(COMPONENT_PROOF)
    obj["gridlock_model2_ref_probe"] = str(MODEL2_REF_PROOF)
    obj["gridlock_model2_surface_probe"] = str(SURFACE_PROOF)

    diagnostic.hide_viewport = True
    diagnostic.hide_render = True
    diagnostic["purpose"] = (
        "Hidden diagnostic source-renderable BSP underlay. Do not show in the default Gridlock "
        "visual layer unless explicitly doing a Model_2 shader research pass."
    )
    set_layer_collection_state(bpy, DIAGNOSTIC_COLLECTION, hide=True, exclude=False)

    return {
        "status": "applied",
        "object": obj.name,
        "policy": POLICY_NAME,
        "reason": reason,
        "active_uv_preserved": active_uv,
        "before_collections": before_collections,
        "after_collections": _collection_names(obj),
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_select": bool(obj.hide_select),
        "visible_gridlock_model_objects_after": visible_gridlock_model_objects(bpy),
    }


def write_policy_proof(bpy: Any, path: str | Path = HIDE_PROOF, *, reason: str = "") -> dict[str, Any]:
    result = apply_model2_visual_policy(bpy, reason=reason)
    proof = {
        "status": "gridlock_model2_visual_policy_applied",
        "blend_path": bpy.data.filepath,
        "policy_result": result,
        "visible_gridlock_model_objects_after": visible_gridlock_model_objects(bpy),
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_model2_visual_policy_proof"] = str(out)
    return proof
