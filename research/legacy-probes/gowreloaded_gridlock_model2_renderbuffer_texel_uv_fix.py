#!/usr/bin/env python3
"""Apply native BSP texel projection to Gridlock Model_2 render-buffer mesh.

The current best Model_2 geometry comes from the cooked FModelVertexBuffer
(5579 vertices). The older texel projection pass used shared FBsp point indices,
which no longer match that render-buffer mesh. This pass keeps the render-buffer
geometry and computes FBspSurf texture projection from each render vertex's
source UE position.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
DEFAULT_DECOMPRESSED = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\MP_Gridlock.decompressed.war"
)
DEFAULT_MATERIAL_CACHE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\gowreloaded_mp_gridlock_material_texture_bindings.json"
)
DEFAULT_PNG_MAP = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\gridlock_full_material_cache_png_rows_extended_2026_08_15.json"
)
DEFAULT_PROOF = SCENE_DIR / "gridlock_model2_renderbuffer_texel_uv_fix_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_model2_renderbuffer_texel_uv_fix_2026_08_15.png"
DEFAULT_PREVIEW = Path(
    r"C:\Users\Bilbo\.codex\visualizations\2026\06\28\019f0bba-7647-7e82-9b57-7c1574085478\gridlock_model2_renderbuffer_texel_uv_fix_latest.png"
)

RENDERBUFFER_FIX = Path(__file__).with_name("gowreloaded_gridlock_model2_renderbuffer_delta_fix.py")
TEXEL_FIX = Path(__file__).with_name("gowreloaded_gridlock_model2_bsp_texel_uv_fix.py")
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
TEXEL_UV_LAYER = "UV_Source_BSP_MaterialTexel"
TEXEL_NO_FLIP_LAYER = "UV_Source_BSP_MaterialTexel_NoVFlip"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", default=str(DEFAULT_DECOMPRESSED))
    parser.add_argument("--material-cache", default=str(DEFAULT_MATERIAL_CACHE))
    parser.add_argument("--png-map", default=str(DEFAULT_PNG_MAP))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--allow-retired-texel-route", action="store_true")
    return parser.parse_args(argv)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rb = load_module(RENDERBUFFER_FIX, "gowr_gridlock_model2_renderbuffer_for_texel")
texel = load_module(TEXEL_FIX, "gowr_gridlock_model2_texel_projection_for_renderbuffer")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")


def ensure_uv_layer(mesh: bpy.types.Mesh, name: str) -> bpy.types.MeshUVLoopLayer:
    layer = mesh.uv_layers.get(name)
    if layer is None:
        mesh.uv_layers.new(name=name)
        layer = mesh.uv_layers.get(name)
    if layer is None:
        raise RuntimeError(f"could not create UV layer {name} on {mesh.name}")
    return layer


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> None:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == layer_name:
            mesh.uv_layers.active_index = index
            break
    try:
        layer.active_render = True
    except Exception:
        pass


def stats_uv(values: list[tuple[float, float]]) -> dict[str, Any]:
    finite = [(u, v) for u, v in values if math.isfinite(u) and math.isfinite(v)]
    if not finite:
        return {"count": len(values), "finite": 0}
    us = [u for u, _v in finite]
    vs = [v for _u, v in finite]
    return {
        "count": len(values),
        "finite": len(finite),
        "min": [min(us), min(vs)],
        "max": [max(us), max(vs)],
        "span": [max(us) - min(us), max(vs) - min(vs)],
        "sample": [[round(u, 6), round(v, 6)] for u, v in finite[:12]],
    }


def polygon_node_stream(nodes: list[dict[str, Any]], vertex_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    triangle_index = 0
    for node in nodes:
        start = int(node.get("i_vertex_index", -1))
        num_vertices = int(node.get("num_vertices", 0))
        surf_index = int(node.get("i_surf", -1))
        if num_vertices < 3:
            continue
        if start < 0 or start + num_vertices > vertex_count:
            continue
        polygon = [start + local for local in range(num_vertices)]
        for local in range(1, num_vertices - 1):
            rows.append(
                {
                    "triangle_index": triangle_index,
                    "surf_index": surf_index,
                    "vertices": [polygon[0], polygon[local], polygon[local + 1]],
                    "node_index": node.get("node_index"),
                }
            )
            triangle_index += 1
    return rows


def apply_renderbuffer_texel_uv(obj: bpy.types.Object, source: dict[str, Any], texture: dict[str, Any]) -> dict[str, Any]:
    mesh = obj.data
    if len(mesh.polygons) == 0:
        raise RuntimeError("Model_2 mesh has no polygons")
    vertices = source["vertices"]
    triangles = polygon_node_stream(source["nodes"], len(vertices))
    if len(triangles) < len(mesh.polygons):
        raise RuntimeError(f"native triangle stream too short: {len(triangles)} < {len(mesh.polygons)}")

    width, height = (float(texture["diffuse_size"][0]), float(texture["diffuse_size"][1]))
    layer = ensure_uv_layer(mesh, TEXEL_UV_LAYER)
    no_flip_layer = ensure_uv_layer(mesh, TEXEL_NO_FLIP_LAYER)

    values: list[tuple[float, float]] = []
    no_flip_values: list[tuple[float, float]] = []
    missing_mapping = 0
    missing_vertices = 0
    mismatched_loop_vertices = 0
    surface_counts: dict[str, int] = {}
    mapping_cache: dict[int, dict[str, Any] | None] = {}

    for poly_index, poly in enumerate(mesh.polygons):
        triangle = triangles[poly_index]
        surf_index = int(triangle["surf_index"])
        if surf_index not in mapping_cache:
            mapping_cache[surf_index] = texel.surf_mapping(source["virt"], source["row"], source["landmarks"], surf_index)
        mapping = mapping_cache[surf_index]
        if mapping is None:
            missing_mapping += len(poly.loop_indices)
            continue
        expected = [int(v) for v in triangle["vertices"]]
        for corner, loop_index in enumerate(poly.loop_indices):
            vertex_index = int(mesh.loops[loop_index].vertex_index)
            if corner < len(expected) and vertex_index != expected[corner]:
                mismatched_loop_vertices += 1
            if vertex_index < 0 or vertex_index >= len(vertices):
                missing_vertices += 1
                continue
            point = vertices[vertex_index]["position"]
            uv = texel.uv_pair(point, mapping, width, height, flip_v=True)
            uv_no_flip = texel.uv_pair(point, mapping, width, height, flip_v=False)
            layer.data[loop_index].uv = uv
            no_flip_layer.data[loop_index].uv = uv_no_flip
            values.append(uv)
            no_flip_values.append(uv_no_flip)
            surface_counts[str(surf_index)] = surface_counts.get(str(surf_index), 0) + 1

    set_active_uv(mesh, TEXEL_UV_LAYER)
    mesh["gridlock_bsp_surface_uv_layer"] = TEXEL_UV_LAYER
    mesh["gridlock_bsp_surface_uv_source"] = (
        "FBspSurf pBase@8 TextureU@16 TextureV@20 projected from native FModelVertexBuffer.Position, "
        f"normalized by native diffuse dimensions {texture['diffuse_size']}"
    )
    mesh["gridlock_model2_renderbuffer_texel_uv_fix"] = "all Model_2 render-buffer loops projected through native BSP texel-space UVs"
    obj["gridlock_bsp_surface_uv_layer"] = TEXEL_UV_LAYER
    obj["gridlock_model2_bsp_fix"] = "render-buffer geometry with native BSP material texel UV projection"
    obj["gridlock_model2_bsp_uv_policy"] = mesh["gridlock_bsp_surface_uv_source"]
    mesh.update(calc_edges=False)

    return {
        "layer": TEXEL_UV_LAYER,
        "loops_written": len(values),
        "missing_mapping_loops": missing_mapping,
        "missing_vertex_loops": missing_vertices,
        "mismatched_loop_vertices": mismatched_loop_vertices,
        "surface_count": len(surface_counts),
        "top_surfaces": sorted(surface_counts.items(), key=lambda item: item[1], reverse=True)[:20],
        "uv_stats": stats_uv(values),
        "uv_no_flip_stats": stats_uv(no_flip_values),
    }


def object_bounds(obj: bpy.types.Object) -> dict[str, Any]:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for corner in obj.bound_box:
        world = obj.matrix_world @ Vector(corner)
        mins.x = min(mins.x, world.x)
        mins.y = min(mins.y, world.y)
        mins.z = min(mins.z, world.z)
        maxs.x = max(maxs.x, world.x)
        maxs.y = max(maxs.y, world.y)
        maxs.z = max(maxs.z, world.z)
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    radius = max(float(extent.x), float(extent.y), float(extent.z), 25.0) * 0.5
    return {
        "min": [float(mins.x), float(mins.y), float(mins.z)],
        "max": [float(maxs.x), float(maxs.y), float(maxs.z)],
        "center": [float(center.x), float(center.y), float(center.z)],
        "extent": [float(extent.x), float(extent.y), float(extent.z)],
        "radius": radius,
    }


def render_preview(obj: bpy.types.Object, render_out: Path, preview_copy: str) -> dict[str, Any]:
    scene = bpy.context.scene
    previous = {item.name: bool(item.hide_render) for item in scene.objects if item.type == "MESH"}
    for item in scene.objects:
        if item.type == "MESH":
            item.hide_render = item != obj
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(render_out)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.035, 0.038, 0.04)

    bounds = object_bounds(obj)
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    camera_data = bpy.data.cameras.get("CAM_MP_Gridlock_Model2_RenderBufferTexel") or bpy.data.cameras.new(
        "CAM_MP_Gridlock_Model2_RenderBufferTexel"
    )
    camera = bpy.data.objects.get(camera_data.name) or bpy.data.objects.new(camera_data.name, camera_data)
    if not camera.users_collection:
        scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.75, -radius * 0.92, radius * 0.58))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 28.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = max(120000.0, radius * 32.0)
    scene.camera = camera
    bpy.ops.render.render(write_still=True)
    if preview_copy:
        preview = Path(preview_copy)
        preview.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(render_out, preview)
    for name, hide in previous.items():
        item = bpy.data.objects.get(name)
        if item is not None:
            item.hide_render = hide
    return {
        "path": str(render_out),
        "ok": render_out.exists(),
        "size": render_out.stat().st_size if render_out.exists() else 0,
        "preview_copy": preview_copy,
        "bounds": bounds,
    }


def main() -> int:
    args = parse_args()
    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    if not args.allow_retired_texel_route:
        proof = {
            "status": "blocked_retired_model2_texel_route",
            "reason": (
                "UV_Source_BSP_MaterialTexel was proven to smear the live main BSP. "
                "Use gowreloaded_gridlock_model2_main_bsp_native_uv_repair.py for production; "
                "rerun this diagnostic only with --allow-retired-texel-route."
            ),
            "safe_repair_script": "tools/gowreloaded_gridlock_model2_main_bsp_native_uv_repair.py",
            "would_touch": MODEL2_OBJECT,
            "retired_uv_layers": [TEXEL_UV_LAYER, TEXEL_NO_FLIP_LAYER],
        }
        write_json(proof_out, proof)
        print(json.dumps({"proof_out": str(proof_out), "status": proof["status"]}, indent=2, ensure_ascii=True))
        return 0

    backup = ""
    if not args.no_save and bpy.data.filepath:
        source_blend = Path(bpy.data.filepath)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_blend.with_name(f"{source_blend.stem}.before_model2_renderbuffer_texel_uv_{stamp}{source_blend.suffix}")
        shutil.copyfile(source_blend, backup_path)
        backup = str(backup_path)

    source = rb.load_model2_render_source(Path(args.decompressed))
    material_cache = read_json(Path(args.material_cache))
    png_by_source = texel.load_png_map(Path(args.png_map))
    texture = texel.material_texture_info(material_cache, png_by_source)

    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"missing Model_2 mesh object: {MODEL2_OBJECT}")

    uv_result = apply_renderbuffer_texel_uv(obj, source, texture)
    material_result = texel.relink_or_rebuild_model2_material(obj, texture)

    render_result = {"status": "skipped"}
    if args.render_proof:
        render_result = render_preview(obj, Path(args.render_out), args.preview_copy)

    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)

    proof = {
        "blend_path": bpy.data.filepath,
        "backup": backup,
        "policy": "Keep cooked FModelVertexBuffer geometry; project each render vertex through native FBspSurf texture axes and material texture dimensions.",
        "source": {
            "vertex_count": len(source["vertices"]),
            "node_count": len(source["nodes"]),
            "required_vertices": source["required_vertices"],
            "vertex_buffer": {
                "stride": source["vertex_buffer"].get("stride"),
                "data_rel": source["vertex_buffer"].get("data_rel"),
                "count": source["vertex_buffer"].get("count"),
            },
        },
        "texture": {
            "material_path": texture.get("material_path"),
            "diffuse_size": texture.get("diffuse_size"),
            "diffuse_png": texture.get("diffuse_png"),
            "normal_png": texture.get("normal_png"),
        },
        "uv": uv_result,
        "material": material_result,
        "render": render_result,
    }
    write_json(proof_out, proof)
    print(json.dumps({"proof_out": str(proof_out), "backup": backup, "uv": uv_result, "render": render_result}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
