#!/usr/bin/env python3
"""Render a wide Gridlock preview after the BSP visibility truth pass."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
DEFAULT_RENDER = SCENE_DIR / "gridlock_bsp_visibility_truth_preview_2026_08_15.png"
DEFAULT_PROOF = SCENE_DIR / "gridlock_bsp_visibility_truth_preview_2026_08_15.json"
DEFAULT_COPY = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_bsp_visibility_truth_preview_latest.png")


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--preview-copy", default=str(DEFAULT_COPY))
    return parser.parse_args(argv)


def object_visible(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    if obj.type != "MESH":
        return False
    if not obj.visible_get():
        return False
    return True


def visible_bounds() -> dict[str, Any]:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    count = 0
    for obj in bpy.data.objects:
        if not object_visible(obj):
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x)
            mins.y = min(mins.y, world.y)
            mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x)
            maxs.y = max(maxs.y, world.y)
            maxs.z = max(maxs.z, world.z)
            count += 1
    if count == 0:
        mins = Vector((-20.0, -20.0, -2.0))
        maxs = Vector((20.0, 20.0, 20.0))
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    return {
        "min": [float(mins.x), float(mins.y), float(mins.z)],
        "max": [float(maxs.x), float(maxs.y), float(maxs.z)],
        "center": [float(center.x), float(center.y), float(center.z)],
        "extent": [float(extent.x), float(extent.y), float(extent.z)],
        "radius": max(float(extent.x), float(extent.y), float(extent.z), 1.0) * 0.5,
    }


def ensure_light(name: str, kind: str, location: tuple[float, float, float], energy: float) -> bpy.types.Object:
    data = bpy.data.lights.get(name)
    if data is None:
        data = bpy.data.lights.new(name, kind)
    data.energy = energy
    if kind == "SUN":
        data.angle = 0.08
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def configure_camera(bounds: dict[str, Any]) -> dict[str, Any]:
    scene = bpy.context.scene
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    data = bpy.data.cameras.get("CAM_MP_Gridlock_BSP_Truth_Wide") or bpy.data.cameras.new("CAM_MP_Gridlock_BSP_Truth_Wide")
    cam = bpy.data.objects.get("CAM_MP_Gridlock_BSP_Truth_Wide") or bpy.data.objects.new("CAM_MP_Gridlock_BSP_Truth_Wide", data)
    if not cam.users_collection:
        scene.collection.objects.link(cam)
    cam.location = center + Vector((-radius * 0.72, -radius * 1.02, radius * 0.58))
    direction = center - Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    data.type = "ORTHO"
    data.ortho_scale = max(float(bounds["extent"][0]), float(bounds["extent"][1])) * 0.92
    data.clip_start = 0.05
    data.clip_end = max(10000.0, radius * 18.0)
    scene.camera = cam
    return {"camera": cam.name, "location": [float(v) for v in cam.location], "target": bounds["center"], "ortho_scale": data.ortho_scale}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 2200
    scene.render.resolution_y = 1100
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.55
    scene.view_settings.gamma = 1.0
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.color = (0.16, 0.17, 0.18)
    sun = ensure_light("SUN_MP_Gridlock_GameReadable_Key", "SUN", (-30.0, -45.0, 80.0), 4.4)
    sun.rotation_euler = (0.83, -0.08, -0.62)
    fill = ensure_light("AREA_MP_Gridlock_GameReadable_Fill", "AREA", (0.0, -25.0, 38.0), 620.0)
    fill.data.size = 42.0
    return {
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
    }


def main() -> int:
    args = parse_args()
    bounds = visible_bounds()
    camera = configure_camera(bounds)
    render = configure_render()
    render_out = Path(args.render_out)
    render_out.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(render_out)
    bpy.ops.render.render(write_still=True)
    copied = False
    copy_path = Path(args.preview_copy)
    if render_out.exists():
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(render_out, copy_path)
        copied = True
    proof = {
        "status": "rendered_bsp_visibility_truth_preview",
        "blend_path": bpy.data.filepath,
        "render": str(render_out),
        "preview_copy": str(copy_path),
        "preview_copied": copied,
        "bounds": bounds,
        "camera": camera,
        "render_config": render,
        "visible_model_objects": [
            obj.name
            for obj in bpy.data.objects
            if obj.name.startswith("Model_") and obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render
        ],
    }
    proof_out = Path(args.proof_out)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"render": str(render_out), "preview": str(copy_path), "visible_model_objects": proof["visible_model_objects"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
