#!/usr/bin/env python3
"""Render MP_Gridlock with and without Model_2 and measure the visual delta."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from array import array
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
DEFAULT_VISIBLE = SCENE_DIR / "gridlock_model2_visible_diff_source_visible_2026_08_15.png"
DEFAULT_HIDDEN = SCENE_DIR / "gridlock_model2_visible_diff_source_hidden_2026_08_15.png"
DEFAULT_PROOF = SCENE_DIR / "gridlock_model2_visibility_diff_render_2026_08_15.json"
DEFAULT_VISIBLE_COPY = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_model2_visible_for_diff_latest.png")
DEFAULT_HIDDEN_COPY = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_model2_hidden_for_diff_latest.png")


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--visible-out", default=str(DEFAULT_VISIBLE))
    parser.add_argument("--hidden-out", default=str(DEFAULT_HIDDEN))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--visible-copy", default=str(DEFAULT_VISIBLE_COPY))
    parser.add_argument("--hidden-copy", default=str(DEFAULT_HIDDEN_COPY))
    return parser.parse_args(argv)


def visible_meshes_for_bounds() -> list[bpy.types.Object]:
    out = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
            continue
        if "sky" in obj.name.lower() or "skydome" in obj.name.lower():
            continue
        extent = max(float(obj.dimensions.x), float(obj.dimensions.y), float(obj.dimensions.z))
        if extent > 10000.0:
            continue
        out.append(obj)
    return out


def object_bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x)
            mins.y = min(mins.y, world.y)
            mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x)
            maxs.y = max(maxs.y, world.y)
            maxs.z = max(maxs.z, world.z)
    if mins.x == float("inf"):
        mins = Vector((-80.0, -80.0, -5.0))
        maxs = Vector((80.0, 80.0, 50.0))
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    return {
        "min": [float(mins.x), float(mins.y), float(mins.z)],
        "max": [float(maxs.x), float(maxs.y), float(maxs.z)],
        "center": [float(center.x), float(center.y), float(center.z)],
        "extent": [float(extent.x), float(extent.y), float(extent.z)],
        "radius": max(float(extent.x), float(extent.y), float(extent.z), 1.0) * 0.5,
    }


def configure_scene() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_WORKBENCH" if "BLENDER_WORKBENCH" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1000
    scene.render.resolution_y = 562
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.55
    scene.view_settings.gamma = 1.0
    if hasattr(scene, "display"):
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_xray = False
        scene.display.shading.show_shadows = False
        scene.display.shading.show_cavity = True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.15, 0.16, 0.17)
    bounds = object_bounds(visible_meshes_for_bounds())
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    cam_data = bpy.data.cameras.get("CAM_MP_Gridlock_Model2_Diff") or bpy.data.cameras.new("CAM_MP_Gridlock_Model2_Diff")
    cam = bpy.data.objects.get(cam_data.name) or bpy.data.objects.new(cam_data.name, cam_data)
    if not cam.users_collection:
        scene.collection.objects.link(cam)
    cam.location = center + Vector((-radius * 0.62, -radius * 0.9, radius * 0.48))
    direction = center - Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(float(bounds["extent"][0]), float(bounds["extent"][1]), 80.0) * 0.74
    cam_data.clip_start = 0.05
    cam_data.clip_end = max(10000.0, radius * 20.0)
    scene.camera = cam
    return {
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "camera": cam.name,
        "camera_location": [float(v) for v in cam.location],
        "camera_ortho_scale": cam_data.ortho_scale,
        "bounds": bounds,
    }


def render_case(model2: bpy.types.Object, hidden: bool, path: Path) -> array:
    model2.hide_render = hidden
    model2.hide_viewport = hidden
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    pixels = array("f", bpy.data.images["Render Result"].pixels[:])
    return pixels


def compare_pixels(a: array, b: array) -> dict[str, Any]:
    if len(a) != len(b):
        return {"status": "pixel_buffer_size_mismatch", "visible_values": len(a), "hidden_values": len(b)}
    total = len(a)
    changed_channels = 0
    changed_pixels = 0
    sum_abs = 0.0
    max_abs = 0.0
    pixel_count = total // 4
    for px in range(pixel_count):
        pixel_changed = False
        base = px * 4
        for channel in range(3):
            diff = abs(float(a[base + channel]) - float(b[base + channel]))
            sum_abs += diff
            if diff > max_abs:
                max_abs = diff
            if diff > 1.0 / 255.0:
                changed_channels += 1
                pixel_changed = True
        if pixel_changed:
            changed_pixels += 1
    return {
        "pixel_count": pixel_count,
        "changed_pixels_gt_1_255": changed_pixels,
        "changed_pixel_fraction": changed_pixels / max(1, pixel_count),
        "changed_channels_gt_1_255": changed_channels,
        "mean_abs_rgb": sum_abs / max(1, pixel_count * 3),
        "max_abs_rgb": max_abs,
        "interpretation": (
            "Near-zero changed_pixel_fraction means hiding Model_2 has negligible visual impact from this camera; "
            "a large fraction means it is visually contributing and must be reconstructed rather than hidden."
        ),
    }


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> int:
    args = parse_args()
    model2 = bpy.data.objects.get(MODEL2_OBJECT)
    if model2 is None:
        raise RuntimeError(f"missing {MODEL2_OBJECT}")
    old_hide_viewport = bool(model2.hide_viewport)
    old_hide_render = bool(model2.hide_render)
    config = configure_scene()
    visible_out = Path(args.visible_out)
    hidden_out = Path(args.hidden_out)
    visible_out.parent.mkdir(parents=True, exist_ok=True)
    visible_pixels = render_case(model2, hidden=False, path=visible_out)
    hidden_pixels = render_case(model2, hidden=True, path=hidden_out)
    diff = compare_pixels(visible_pixels, hidden_pixels)
    model2.hide_viewport = old_hide_viewport
    model2.hide_render = old_hide_render
    proof = {
        "status": "model2_visibility_diff_rendered",
        "blend_path": bpy.data.filepath,
        "model2": MODEL2_OBJECT,
        "old_hide_viewport": old_hide_viewport,
        "old_hide_render": old_hide_render,
        "visible_render": str(visible_out),
        "hidden_render": str(hidden_out),
        "visible_copy": str(Path(args.visible_copy)),
        "hidden_copy": str(Path(args.hidden_copy)),
        "visible_copy_ok": copy_if_exists(visible_out, Path(args.visible_copy)),
        "hidden_copy_ok": copy_if_exists(hidden_out, Path(args.hidden_copy)),
        "render_config": config,
        "diff": diff,
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "diff": diff, "visible": str(visible_out), "hidden": str(hidden_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
