#!/usr/bin/env python3
"""Hide Gridlock Model_2 from the visual layer while preserving source proof."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy  # type: ignore


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
DIAG_COLLECTION = "00_DIAGNOSTICS_SourceRenderable_BSP_Hidden_PendingExactUE3Shader"
VIS_DIFF_PROOF = SCENE_DIR / "gridlock_model2_visibility_diff_image_compare_2026_08_15.json"
COMPONENT_PROOF = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\BSP_Confidence\gridlock_modelcomponent_visibility_probe_2026_08_15.json"
)
COMPONENT_REF_PROOF = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\BSP_Confidence\gridlock_model2_modelcomponent_ref_probe_2026_08_15.json"
)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", default=str(SCENE_DIR / "gridlock_model2_hidden_as_redundant_bsp_2026_08_15.json"))
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def get_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def link_once(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def set_layer_collection_state(name: str, hide: bool) -> None:
    def walk(layer_collection: bpy.types.LayerCollection) -> None:
        if layer_collection.collection.name == name:
            layer_collection.hide_viewport = hide
        for child in layer_collection.children:
            walk(child)

    for view_layer in bpy.context.scene.view_layers:
        walk(view_layer.layer_collection)


def make_backup() -> str:
    filepath = Path(bpy.data.filepath)
    if not filepath.exists():
        return ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = filepath.with_name(f"{filepath.stem}.before_hide_redundant_model2_bsp_{stamp}{filepath.suffix}")
    shutil.copy2(filepath, backup)
    return str(backup)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    args = parse_args()
    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None:
        raise RuntimeError(f"missing {MODEL2_OBJECT}")
    before = {
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_select": bool(obj.hide_select),
        "collections": [collection.name for collection in obj.users_collection],
    }
    collection = get_collection(DIAG_COLLECTION)
    link_once(obj, collection)
    collection.hide_viewport = True
    collection.hide_render = True
    collection["purpose"] = (
        "Source-renderable Model_2 BSP kept for proof, but hidden from the visual Gridlock layer because "
        "static/SD mesh shell carries the visible map and Model_2's exact UE3 shader/UV path is unresolved."
    )
    set_layer_collection_state(DIAG_COLLECTION, hide=True)

    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"
    obj["gridlock_visual_layer_policy"] = "hidden_redundant_source_renderable_bsp_pending_exact_ue3_shader"
    obj["gridlock_model2_source_truth"] = (
        "Referenced by 39 ModelComponents with no explicit hidden tag; material refs resolve to "
        "COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT. Workbench A/B render shows hiding changes only ~0.017% of pixels."
    )
    obj["gridlock_model2_visibility_diff_proof"] = str(VIS_DIFF_PROOF)
    obj["gridlock_model2_component_visibility_proof"] = str(COMPONENT_PROOF)
    obj["gridlock_model2_component_material_ref_proof"] = str(COMPONENT_REF_PROOF)

    after = {
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_select": bool(obj.hide_select),
        "collections": [collection.name for collection in obj.users_collection],
    }
    proof = {
        "status": "model2_hidden_from_visual_layer_preserved_as_source_renderable_bsp",
        "blend_path": bpy.data.filepath,
        "backup_before_save": "" if args.no_save else make_backup(),
        "object": MODEL2_OBJECT,
        "diagnostic_collection": DIAG_COLLECTION,
        "before": before,
        "after": after,
        "source_confirmation": {
            "modelcomponent_visibility_probe": str(COMPONENT_PROOF),
            "modelcomponent_ref_probe": str(COMPONENT_REF_PROOF),
            "component_count": 39,
            "explicit_hidden_tag_hits": 0,
            "material_paths": ["COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT"],
        },
        "visual_confirmation": read_json(VIS_DIFF_PROOF),
        "policy": (
            "This is not deleted and not classified as non-source. It is source-renderable BSP evidence, "
            "hidden from the main visual export because its current Blender shader/UV reconstruction is inaccurate "
            "and the scene remains visually intact without it."
        ),
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_model2_visual_layer_policy"] = str(out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(out), "backup": proof["backup_before_save"], "after": after}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
