#!/usr/bin/env python3
"""Render only selected Gridlock texture-problem targets without saving."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


DEFAULT_TARGETS = [
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2550_StaticMesh__27112",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP",
]


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-out", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--preview-copy", default="")
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    return parser.parse_args(argv)


def visible_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render


def vec(v: Vector) -> list[float]:
    return [round(float(v.x), 6), round(float(v.y), 6), round(float(v.z), 6)]


def bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
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
    if not math.isfinite(mins.x):
        mins = Vector((-50.0, -50.0, 0.0))
        maxs = Vector((50.0, 50.0, 60.0))
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    radius = max(float(extent.x), float(extent.y), float(extent.z), 25.0) * 0.5
    return {"min": vec(mins), "max": vec(maxs), "center": vec(center), "extent": vec(extent), "radius": round(radius, 6)}


def select_targets(names: list[str]) -> tuple[list[bpy.types.Object], list[str]]:
    objects: list[bpy.types.Object] = []
    unavailable: list[str] = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            unavailable.append(f"{name} (missing)")
        elif not visible_mesh(obj):
            unavailable.append(f"{name} (hidden)")
        else:
            objects.append(obj)
    if not objects:
        objects = [obj for obj in bpy.context.scene.objects if visible_mesh(obj) and obj.get("ue_static_mesh_path")][:12]
    return objects, unavailable


def isolate(objects: list[bpy.types.Object]) -> dict[str, Any]:
    keep = set(objects)
    changed = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        desired_hide = obj not in keep
        if obj.hide_render != desired_hide:
            obj.hide_render = desired_hide
            changed += 1
    return {"render_visible_mesh_objects": len(keep), "hide_render_changes": changed}


def configure_camera(objects: list[bpy.types.Object]) -> dict[str, Any]:
    b = bounds(objects)
    center = Vector(b["center"])
    radius = float(b["radius"])
    data = bpy.data.cameras.get("CAM_MP_Gridlock_IsolatedTextureTargets") or bpy.data.cameras.new(
        "CAM_MP_Gridlock_IsolatedTextureTargets"
    )
    cam = bpy.data.objects.get(data.name) or bpy.data.objects.new(data.name, data)
    if not cam.users_collection:
        bpy.context.scene.collection.objects.link(cam)
    cam.location = center + Vector((-radius * 0.72, -radius * 0.92, radius * 0.52))
    direction = center - Vector(cam.location)
    if direction.length > 0:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    data.lens = 28.0
    data.clip_start = 0.05
    data.clip_end = max(120000.0, radius * 30.0)
    bpy.context.scene.camera = cam
    return {"camera": cam.name, "location": vec(cam.location), "target": b["center"], "lens": data.lens, "bounds": b}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.035, 0.038, 0.04)
    return {"engine": str(scene.render.engine), "resolution": [scene.render.resolution_x, scene.render.resolution_y]}


def uv_summary(objects: list[bpy.types.Object]) -> dict[str, Any]:
    rows = []
    for obj in objects:
        mesh = obj.data
        rows.append(
            {
                "object": obj.name,
                "mesh": mesh.name,
                "uv_layers": [layer.name for layer in mesh.uv_layers],
                "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
                "repo_uvstream_payload": mesh.get("gridlock_repo_uvstream_payload", ""),
                "materials": [slot.material.name for slot in obj.material_slots if slot.material],
            }
        )
    return {"objects": rows}


def main() -> int:
    args = parse_args()
    render_out = Path(args.render_out)
    proof_out = Path(args.proof_out)
    render_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    objects, unavailable = select_targets(args.targets)
    isolation = isolate(objects)
    render = configure_render()
    camera = configure_camera(objects)
    bpy.context.scene.render.filepath = str(render_out)
    bpy.ops.render.render(write_still=True)
    if args.preview_copy:
        preview = Path(args.preview_copy)
        preview.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(render_out, preview)
    proof = {
        "blend_path": bpy.data.filepath,
        "render_out": str(render_out),
        "preview_copy": args.preview_copy,
        "targets": args.targets,
        "unavailable_targets": unavailable,
        "isolation": isolation,
        "render": render,
        "camera": camera,
        "uv_summary": uv_summary(objects),
        "note": "In-memory isolated render only; the blend is not saved.",
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"render_out": str(render_out), "proof_out": str(proof_out), "isolation": isolation}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
