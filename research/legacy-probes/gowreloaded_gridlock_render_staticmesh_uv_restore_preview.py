#!/usr/bin/env python3
"""Render a non-mutating preview of the Gridlock StaticMesh UV restore."""

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


TARGETS = [
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
    parser.add_argument("--targets", nargs="*", default=TARGETS)
    return parser.parse_args(argv)


def vec(values: Vector) -> list[float]:
    return [round(float(values.x), 6), round(float(values.y), 6), round(float(values.z), 6)]


def visible_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render


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
    if not math.isfinite(mins.x):
        mins = Vector((-100.0, -100.0, -10.0))
        maxs = Vector((100.0, 100.0, 80.0))
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    radius = max(float(extent.x), float(extent.y), float(extent.z), 10.0) * 0.5
    return {"min": vec(mins), "max": vec(maxs), "center": vec(center), "extent": vec(extent), "radius": round(radius, 6)}


def collect_preview_objects(target_names: list[str]) -> tuple[list[bpy.types.Object], list[str]]:
    seed = [bpy.data.objects[name] for name in target_names if name in bpy.data.objects and visible_mesh(bpy.data.objects[name])]
    missing = [name for name in target_names if name not in bpy.data.objects]
    hidden = [name for name in target_names if name in bpy.data.objects and not visible_mesh(bpy.data.objects[name])]
    if not seed:
        seed = [obj for obj in bpy.context.scene.objects if visible_mesh(obj) and obj.get("ue_static_mesh_path")][:80]
    seed_bounds = object_bounds(seed)
    center = Vector(seed_bounds["center"])
    radius = max(float(seed_bounds["radius"]) * 1.75, 85.0)
    nearby: list[bpy.types.Object] = []
    for obj in bpy.context.scene.objects:
        if not visible_mesh(obj):
            continue
        obj_center = obj.matrix_world @ Vector(obj.bound_box[0])
        for corner in obj.bound_box[1:]:
            obj_center += obj.matrix_world @ Vector(corner)
        obj_center /= 8.0
        if (obj_center - center).length <= radius:
            nearby.append(obj)
    return nearby or seed, missing + [f"{name} (hidden)" for name in hidden]


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    scene.render.resolution_x = 2200
    scene.render.resolution_y = 1100
    scene.render.film_transparent = False
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        try:
            scene.render.engine = "BLENDER_EEVEE"
        except Exception:
            pass
    if hasattr(scene, "eevee"):
        eevee = scene.eevee
        for prop, value in (
            ("taa_render_samples", 32),
            ("use_gtao", True),
            ("gtao_distance", 6.0),
            ("gtao_factor", 0.8),
            ("use_bloom", False),
        ):
            if hasattr(eevee, prop):
                try:
                    setattr(eevee, prop, value)
                except Exception:
                    pass
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.025, 0.028, 0.03)
    return {"engine": str(scene.render.engine), "resolution": [scene.render.resolution_x, scene.render.resolution_y]}


def configure_camera(objects: list[bpy.types.Object]) -> dict[str, Any]:
    bounds = object_bounds(objects)
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    data = bpy.data.cameras.get("CAM_MP_Gridlock_StaticMeshUVRestore_Preview") or bpy.data.cameras.new(
        "CAM_MP_Gridlock_StaticMeshUVRestore_Preview"
    )
    camera = bpy.data.objects.get(data.name) or bpy.data.objects.new(data.name, data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.62, -radius * 0.78, radius * 0.44))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    data.lens = 24.0
    data.clip_start = 0.05
    data.clip_end = max(180000.0, radius * 30.0)
    bpy.context.scene.camera = camera
    return {"camera": camera.name, "location": vec(camera.location), "target": bounds["center"], "lens": data.lens, "bounds": bounds}


def uv_route_summary(objects: list[bpy.types.Object]) -> dict[str, Any]:
    missing_render_uv = []
    linked_images = 0
    image_nodes = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        if obj.data.uv_layers.get("UV_Source_Render") is None and obj.get("ue_static_mesh_path"):
            missing_render_uv.append(obj.name)
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes or mat.node_tree is None:
                continue
            for node in mat.node_tree.nodes:
                if node.bl_idname != "ShaderNodeTexImage":
                    continue
                image_nodes += 1
                vector = node.inputs.get("Vector")
                if vector is not None and vector.links and vector.links[0].from_node.bl_idname == "ShaderNodeUVMap":
                    if getattr(vector.links[0].from_node, "uv_map", "") == "UV_Source_Render":
                        linked_images += 1
    return {
        "preview_object_count": len(objects),
        "missing_uv_source_render": missing_render_uv[:80],
        "image_nodes": image_nodes,
        "image_nodes_linked_to_uv_source_render": linked_images,
    }


def main() -> int:
    args = parse_args()
    render_out = Path(args.render_out)
    proof_out = Path(args.proof_out)
    render_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.parent.mkdir(parents=True, exist_ok=True)

    objects, unavailable_targets = collect_preview_objects(args.targets)
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
        "unavailable_targets": unavailable_targets,
        "render": render,
        "camera": camera,
        "uv_route_summary": uv_route_summary(objects),
        "note": "Render-only validation; script does not save the blend.",
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"render_out": str(render_out), "proof_out": str(proof_out), "uv_route_summary": proof["uv_route_summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
