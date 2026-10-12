#!/usr/bin/env python3
"""Harden Gridlock BSP visibility and keep the rendered BSP path honest.

The direct PersistentLevel Model_* chunks are decoded source/CSG brush data with
null BSP material refs. They are useful proof, but they are not the cooked
rendered shell and should not be visible or selectable in the normal Blender
scene. Model_2 is source-renderable proof, but A/B render validation shows it is
not useful as the visible Blender shell, so it is hidden as a diagnostic too.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy  # type: ignore


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
BLEND = SCENE_DIR / "MP_Gridlock_Reloaded_native_scene.blend"
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL_RE = re.compile(r"^Model_\d+__MP_Gridlock\.war__\d+", re.IGNORECASE)
HIDDEN_CSG_COLLECTION = "00_DIAGNOSTICS_HIDDEN_Source_CSG_Brushes_Not_Game_Rendered"
MODEL2_POLICY_PATH = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


model2_policy = load_module(MODEL2_POLICY_PATH, "gowr_gridlock_model2_visual_policy")


def parse_args() -> argparse.Namespace:
    argv = []
    import sys

    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1 :]
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", default=str(SCENE_DIR / "gridlock_bsp_visibility_truth_pass_2026_08_15.json"))
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def get_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def unlink_from_collection(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    try:
        collection.objects.unlink(obj)
    except Exception:
        pass


def link_once(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def set_layer_collection_state(name: str, hide: bool, exclude: bool = False) -> None:
    def walk(layer_collection: bpy.types.LayerCollection) -> None:
        if layer_collection.collection.name == name:
            layer_collection.hide_viewport = hide
            layer_collection.exclude = exclude
        for child in layer_collection.children:
            walk(child)

    for view_layer in bpy.context.scene.view_layers:
        walk(view_layer.layer_collection)


def material_images(material: bpy.types.Material | None) -> list[dict[str, str]]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    rows: list[dict[str, str]] = []
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        vector = node.inputs.get("Vector")
        vector_link = ""
        if vector is not None and vector.links:
            link = vector.links[0]
            vector_link = f"{link.from_node.name}:{link.from_socket.name}"
        rows.append(
            {
                "node": node.name,
                "label": str(getattr(node, "label", "")),
                "image": image.name if image else "",
                "filepath": bpy.path.abspath(image.filepath) if image else "",
                "vector_link": vector_link,
            }
        )
    return rows


def uv_stats(mesh: bpy.types.Mesh) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for layer in mesh.uv_layers:
        values = [(float(loop.uv[0]), float(loop.uv[1])) for loop in layer.data]
        if not values:
            out[layer.name] = {"loops": 0}
            continue
        us = [u for u, _v in values]
        vs = [v for _u, v in values]
        out[layer.name] = {
            "loops": len(values),
            "min": [min(us), min(vs)],
            "max": [max(us), max(vs)],
            "span": [max(us) - min(us), max(vs) - min(vs)],
            "sample": [[round(u, 6), round(v, 6)] for u, v in values[:8]],
        }
    return out


def model2_state() -> dict[str, Any]:
    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None or obj.type != "MESH":
        return {"exists": False}
    mesh = obj.data
    active_render = next((layer.name for layer in mesh.uv_layers if getattr(layer, "active_render", False)), "")
    return {
        "exists": True,
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_select": bool(obj.hide_select),
        "mesh": mesh.name,
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
        "active_render_uv": active_render,
        "materials": [
            {
                "slot": index,
                "name": slot.material.name if slot.material else "",
                "source_material_path": str(slot.material.get("source_material_path", "")) if slot.material else "",
                "ue_material_path": str(slot.material.get("ue_material_path", "")) if slot.material else "",
                "texture_coordinate_uv_map": str(slot.material.get("texture_coordinate_uv_map", "")) if slot.material else "",
                "images": material_images(slot.material),
            }
            for index, slot in enumerate(obj.material_slots)
        ],
        "polygon_material_indices": {
            str(index): sum(1 for poly in mesh.polygons if poly.material_index == index)
            for index in sorted({poly.material_index for poly in mesh.polygons})
        },
        "uv_stats": uv_stats(mesh),
        "custom_props": {key: obj[key] for key in obj.keys()},
    }


def make_backup() -> str:
    filepath = Path(bpy.data.filepath)
    if not filepath.exists():
        return ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = filepath.with_name(f"{filepath.stem}.before_bsp_visibility_truth_{stamp}{filepath.suffix}")
    shutil.copy2(filepath, backup)
    return str(backup)


def main() -> int:
    args = parse_args()
    hidden_collection = get_collection(HIDDEN_CSG_COLLECTION)
    hidden_rows: list[dict[str, Any]] = []
    visible_before: list[str] = []
    for obj in list(bpy.data.objects):
        if not MODEL_RE.match(obj.name) or obj.name == MODEL2_OBJECT:
            continue
        was_visible = not obj.hide_viewport and not obj.hide_render
        if was_visible:
            visible_before.append(obj.name)
        old_collections = [collection.name for collection in obj.users_collection]
        link_once(obj, hidden_collection)
        for collection in list(obj.users_collection):
            if collection.name != HIDDEN_CSG_COLLECTION:
                unlink_from_collection(obj, collection)
        obj.hide_viewport = True
        obj.hide_render = True
        obj.hide_select = True
        obj.display_type = "WIRE"
        obj["game_render_visibility"] = "disabled_source_csg_not_cooked_rendered_bsp"
        obj["gridlock_bsp_visibility_truth_pass"] = "kept as hidden diagnostic proof only; not part of normal visible map"
        hidden_rows.append(
            {
                "object": obj.name,
                "old_collections": old_collections,
                "new_collections": [collection.name for collection in obj.users_collection],
                "hide_viewport": bool(obj.hide_viewport),
                "hide_render": bool(obj.hide_render),
                "hide_select": bool(obj.hide_select),
            }
        )

    hidden_collection.hide_viewport = True
    hidden_collection.hide_render = True
    hidden_collection["purpose"] = "Decoded source CSG/brush Model_* diagnostics. Hidden from normal Gridlock render because FBspSurf.Material refs are null/non-rendered."
    set_layer_collection_state(HIDDEN_CSG_COLLECTION, hide=True, exclude=False)

    model2 = bpy.data.objects.get(MODEL2_OBJECT)
    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        model2,
        reason="bsp_visibility_truth_pass",
    )
    if model2 is not None and model2.type == "MESH":
        model2["gridlock_bsp_visibility_truth_pass"] = (
            "source-renderable diagnostic proof only; hidden from normal visual layer with source CSG Model_* chunks"
        )

    visible_model_objects = [
        obj.name
        for obj in bpy.data.objects
        if MODEL_RE.match(obj.name) and not obj.hide_viewport and not obj.hide_render
    ]
    proof = {
        "status": "bsp_visibility_truth_pass_applied",
        "blend_path": bpy.data.filepath,
        "backup_before_save": "" if args.no_save else make_backup(),
        "hidden_source_csg_collection": HIDDEN_CSG_COLLECTION,
        "source_csg_objects_hardened": len(hidden_rows),
        "source_csg_visible_before": visible_before,
        "visible_model_objects_after": visible_model_objects,
        "model2": model2_state(),
        "model2_visual_policy": model2_policy_result,
        "policy": {
            "source_csg": "Model_* direct BSP chunks with null material refs are hidden diagnostics, not the game-rendered map shell.",
            "model2": "Model_2 is source-renderable, but hidden from the visual layer because A/B render proof showed it is redundant and visually harmful in Blender.",
            "visible_bsp": "No direct PersistentLevel Model_* BSP chunk is visible by default; the playable shell is carried by resolved static/Delta/BSP visual assets.",
        },
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_bsp_visibility_truth_pass"] = str(out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(out), "visible_model_objects_after": visible_model_objects, "source_csg_objects_hardened": len(hidden_rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
