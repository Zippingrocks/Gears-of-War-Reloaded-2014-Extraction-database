#!/usr/bin/env python3
"""Restore Gridlock StaticMesh render UVs from GoWU/UE3 native UV streams.

This intentionally avoids the statistical UV candidate scorer. Gears Ultimate /
Reloaded StaticMeshes serialize FStaticMeshUVStream3 as:

    NumTexCoords, ItemSize, NumVerts, bUseFullPrecisionUVs, BulkSerialize(...)

The UV payload item then stores tangent/color prefix data followed by texcoords.
For the common Gridlock two-channel half-precision layout that makes UV0 start
at byte 12 and UV1 at byte 16 inside each item.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import struct
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


RENDER_UV_LAYER = "UV_Source_Render"
NATIVE_UV0_LAYER = "UV0_Source_GoWU_Native"
NATIVE_UV1_LAYER = "UV1_Source_GoWU_Native"
MATERIAL_SUFFIX = "__GOWU_NativeUV"

DEFAULT_TARGETS = [
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2550_StaticMesh__27112",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
    "SDStitchingProxy_2409_StaticMesh__27021",
    "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP",
]


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--decompressed-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--render-out", default="")
    parser.add_argument("--preview-copy", default="")
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    return parser.parse_args(argv)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_json_field(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def f16(data: bytes, off: int) -> float:
    return struct.unpack_from("<e", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def package_bytes(package_dir: Path, package_name: str, cache: dict[str, bytes]) -> bytes:
    key = package_name.lower()
    if key in cache:
        return cache[key]
    stem = Path(package_name).stem
    suffix = Path(package_name).suffix or ".war"
    candidates = [
        package_dir / package_name,
        package_dir / f"{stem}.decompressed{suffix}",
        package_dir / f"{stem}.decompressed.war",
    ]
    for candidate in candidates:
        if candidate.exists():
            cache[key] = candidate.read_bytes()
            return cache[key]
    raise FileNotFoundError(f"no decompressed package for {package_name} under {package_dir}")


def clean_key(text: Any) -> str:
    return str(text or "").strip().lower()


def static_mesh_key_for_mesh(mesh: bpy.types.Mesh) -> str:
    return clean_key(mesh.get("ue_full_path", ""))


def static_mesh_key_for_object(obj: bpy.types.Object) -> str:
    return clean_key(obj.get("ue_static_mesh_path", "")) or (
        static_mesh_key_for_mesh(obj.data) if obj.type == "MESH" else ""
    )


def detect_gowu_uv_stream(data: bytes, row: dict[str, str]) -> dict[str, Any] | None:
    geom = parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    item_size = int(static_vertex.get("element_size") or 0)
    item_count = int(static_vertex.get("count") or 0)
    data_rel = int(static_vertex.get("data_rel") or 0)
    serial_offset = int(row["serial_offset"])
    raw_base = serial_offset + data_rel
    if item_size <= 0 or item_count <= 0 or raw_base <= 0:
        return None

    candidates: list[dict[str, Any]] = []
    if raw_base >= 12 and raw_base + 12 <= len(data):
        num_texcoords = i32(data, raw_base - 12)
        meta_item_size = i32(data, raw_base - 8)
        meta_count = i32(data, raw_base - 4)
        full_precision = i32(data, raw_base)
        bulk_item_size = i32(data, raw_base + 4)
        bulk_count = i32(data, raw_base + 8)
        score = 0
        if 1 <= num_texcoords <= 8:
            score += 3
        if meta_item_size == item_size and bulk_item_size == item_size:
            score += 4
        if meta_count == item_count and bulk_count == item_count:
            score += 4
        if full_precision in {0, 1}:
            score += 2
        if score >= 13:
            candidates.append(
                {
                    "layout": "gowu_fstaticmeshuvstream3_data_rel_at_full_precision_flag",
                    "metadata_abs": raw_base - 12,
                    "payload_abs": raw_base + 12,
                    "num_texcoords": num_texcoords,
                    "item_size": item_size,
                    "item_count": item_count,
                    "use_full_precision_uvs": bool(full_precision),
                    "score": score,
                }
            )

    if raw_base >= 16 and raw_base + 8 <= len(data):
        num_texcoords = i32(data, raw_base - 16)
        meta_item_size = i32(data, raw_base - 12)
        meta_count = i32(data, raw_base - 8)
        full_precision = i32(data, raw_base - 4)
        bulk_item_size = i32(data, raw_base)
        bulk_count = i32(data, raw_base + 4)
        score = 0
        if 1 <= num_texcoords <= 8:
            score += 3
        if meta_item_size == item_size and bulk_item_size == item_size:
            score += 4
        if meta_count == item_count and bulk_count == item_count:
            score += 4
        if full_precision in {0, 1}:
            score += 2
        if score >= 13:
            candidates.append(
                {
                    "layout": "gowu_fstaticmeshuvstream3_data_rel_at_bulk_header",
                    "metadata_abs": raw_base - 16,
                    "payload_abs": raw_base + 8,
                    "num_texcoords": num_texcoords,
                    "item_size": item_size,
                    "item_count": item_count,
                    "use_full_precision_uvs": bool(full_precision),
                    "score": score,
                }
            )

    if not candidates:
        return None

    stream = max(candidates, key=lambda item: item["score"])
    pair_size = 8 if stream["use_full_precision_uvs"] else 4
    prefix = int(stream["item_size"]) - int(stream["num_texcoords"]) * pair_size
    if prefix < 0:
        return None
    stream["uv_pair_size"] = pair_size
    stream["uv_prefix_bytes"] = prefix
    stream["uv_offsets"] = [prefix + index * pair_size for index in range(int(stream["num_texcoords"]))]
    return stream


def read_stream_uv(data: bytes, stream: dict[str, Any], vertex_index: int, channel: int, flip_v: bool = True) -> tuple[float, float] | None:
    if vertex_index < 0 or vertex_index >= int(stream["item_count"]):
        return None
    if channel < 0 or channel >= int(stream["num_texcoords"]):
        return None
    off = int(stream["payload_abs"]) + vertex_index * int(stream["item_size"]) + int(stream["uv_offsets"][channel])
    if stream["use_full_precision_uvs"]:
        if off + 8 > len(data):
            return None
        u = f32(data, off)
        v = f32(data, off + 4)
    else:
        if off + 4 > len(data):
            return None
        u = f16(data, off)
        v = f16(data, off + 2)
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (float(u), float(1.0 - v if flip_v else v))


def uv_stats(layer: bpy.types.MeshUVLoopLayer) -> dict[str, Any]:
    values: list[tuple[float, float]] = []
    for item in layer.data:
        u = float(item.uv[0])
        v = float(item.uv[1])
        if math.isfinite(u) and math.isfinite(v):
            values.append((u, v))
    if not values:
        return {"loops": len(layer.data), "valid": 0}
    us = [uv[0] for uv in values]
    vs = [uv[1] for uv in values]
    unique = len({(round(u, 5), round(v, 5)) for u, v in values})
    return {
        "loops": len(layer.data),
        "valid": len(values),
        "unique_rounded": unique,
        "min": [round(min(us), 8), round(min(vs), 8)],
        "max": [round(max(us), 8), round(max(vs), 8)],
        "span": [round(max(us) - min(us), 8), round(max(vs) - min(vs), 8)],
        "sample": [[round(u, 6), round(v, 6)] for u, v in values[:8]],
    }


def ensure_uv_layer(mesh: bpy.types.Mesh, name: str) -> bpy.types.MeshUVLoopLayer:
    layer = mesh.uv_layers.get(name)
    if layer is None:
        mesh.uv_layers.new(name=name)
        layer = mesh.uv_layers.get(name)
    if layer is None:
        raise RuntimeError(f"could not create UV layer {name} on {mesh.name}")
    return layer


def optional_uv_layer(mesh: bpy.types.Mesh, name: str) -> bpy.types.MeshUVLoopLayer | None:
    layer = mesh.uv_layers.get(name)
    if layer is not None:
        return layer
    try:
        mesh.uv_layers.new(name=name)
    except Exception:
        return None
    return mesh.uv_layers.get(name)


def set_render_layer(mesh: bpy.types.Mesh, name: str) -> None:
    layer = mesh.uv_layers.get(name)
    if layer is None:
        return
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == name:
            mesh.uv_layers.active_index = index
            break
    try:
        layer.active_render = True
    except Exception:
        pass


def apply_mesh_uv(mesh: bpy.types.Mesh, row: dict[str, str], stream: dict[str, Any], data: bytes) -> dict[str, Any]:
    render_layer = ensure_uv_layer(mesh, RENDER_UV_LAYER)
    uv0_layer = optional_uv_layer(mesh, NATIVE_UV0_LAYER) or render_layer
    uv1_layer = optional_uv_layer(mesh, NATIVE_UV1_LAYER) if int(stream["num_texcoords"]) > 1 else None

    before = uv_stats(render_layer)
    loops_written = 0
    uv1_written = 0
    missing_loops = 0
    for loop in mesh.loops:
        index = int(loop.vertex_index)
        uv0 = read_stream_uv(data, stream, index, 0)
        if uv0 is None:
            missing_loops += 1
            continue
        render_layer.data[loop.index].uv = uv0
        uv0_layer.data[loop.index].uv = uv0
        loops_written += 1
        if uv1_layer is not None:
            uv1 = read_stream_uv(data, stream, index, 1)
            if uv1 is not None:
                uv1_layer.data[loop.index].uv = uv1
                uv1_written += 1

    set_render_layer(mesh, RENDER_UV_LAYER)
    mesh["gridlock_render_uv_layer"] = RENDER_UV_LAYER
    mesh["gridlock_gowu_native_uv_restore"] = json.dumps(
        {
            "layout": stream["layout"],
            "num_texcoords": stream["num_texcoords"],
            "use_full_precision_uvs": stream["use_full_precision_uvs"],
            "item_size": stream["item_size"],
            "item_count": stream["item_count"],
            "uv_offsets": stream["uv_offsets"],
            "source": "UEViewer GAME_GoWU FStaticMeshUVStream3/FStaticMeshUVItem3 layout",
        },
        ensure_ascii=True,
    )
    mesh.update(calc_edges=False)
    return {
        "mesh": mesh.name,
        "full_path": row.get("full_path", ""),
        "layout": stream["layout"],
        "num_texcoords": stream["num_texcoords"],
        "use_full_precision_uvs": stream["use_full_precision_uvs"],
        "item_size": stream["item_size"],
        "item_count": stream["item_count"],
        "uv_offsets": stream["uv_offsets"],
        "loops_written": loops_written,
        "uv1_loops_written": uv1_written,
        "missing_loops": missing_loops,
        "before": before,
        "after": uv_stats(render_layer),
    }


def material_has_images(material: bpy.types.Material | None) -> bool:
    if material is None or not material.use_nodes or material.node_tree is None:
        return False
    return any(node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None) for node in material.node_tree.nodes)


def is_staticmesh_material_candidate(material: bpy.types.Material | None) -> bool:
    if material is None:
        return False
    if material.name.startswith(("INLINE_PROXY__", "INLINE_ASSET_NATIVE__", "DECAL_", "BSP__")):
        return False
    return material_has_images(material)


def relink_material_to_uv(material: bpy.types.Material) -> int:
    if not material.use_nodes or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_nodes = [node for node in nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]
    if not image_nodes:
        return 0
    uv_node = nodes.get("Source_StaticMesh_GoWU_NativeUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_GoWU_NativeUV"
        uv_node.label = "Source StaticMesh GoWU Native UV"
        uv_node.location = (-980, -220)
    try:
        uv_node.uv_map = RENDER_UV_LAYER
    except Exception:
        pass
    output = uv_node.outputs.get("UV")
    if output is None:
        return 0
    linked = 0
    for image_node in image_nodes:
        vector_input = image_node.inputs.get("Vector")
        if vector_input is None:
            continue
        for link in list(vector_input.links):
            links.remove(link)
        links.new(output, vector_input)
        linked += 1
    material["texture_coordinate_uv_map"] = RENDER_UV_LAYER
    material["gridlock_gowu_native_uv_material"] = "texture image nodes routed to source-native UV_Source_Render"
    return linked


def native_uv_material(original: bpy.types.Material, cache: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if original.name.endswith(MATERIAL_SUFFIX):
        relink_material_to_uv(original)
        return original
    if original.name in cache:
        return cache[original.name]
    clone_name = original.name + MATERIAL_SUFFIX
    material = bpy.data.materials.get(clone_name)
    if material is None:
        material = original.copy()
        material.name = clone_name
    material["gridlock_gowu_native_uv_clone_source"] = original.name
    relink_material_to_uv(material)
    cache[original.name] = material
    return material


def assign_staticmesh_materials(touched_keys: set[str]) -> dict[str, Any]:
    cache: dict[str, bpy.types.Material] = {}
    touched_objects = 0
    assigned_slots = 0
    skipped_slots = Counter()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        key = static_mesh_key_for_object(obj)
        if key not in touched_keys:
            continue
        object_touched = False
        for slot in obj.material_slots:
            material = slot.material
            if not is_staticmesh_material_candidate(material):
                skipped_slots["not_image_or_excluded"] += 1
                continue
            assert material is not None
            replacement = native_uv_material(material, cache)
            if slot.material != replacement:
                slot.material = replacement
                assigned_slots += 1
                object_touched = True
        if object_touched:
            touched_objects += 1
    return {
        "touched_objects": touched_objects,
        "assigned_slots": assigned_slots,
        "clone_count": len(cache),
        "skipped_slots": dict(skipped_slots),
    }


def visible_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render


def vec(v: Vector) -> list[float]:
    return [round(float(v.x), 6), round(float(v.y), 6), round(float(v.z), 6)]


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
        mins = Vector((-50.0, -50.0, 0.0))
        maxs = Vector((50.0, 50.0, 60.0))
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    radius = max(float(extent.x), float(extent.y), float(extent.z), 25.0) * 0.5
    return {"min": vec(mins), "max": vec(maxs), "center": vec(center), "extent": vec(extent), "radius": round(radius, 6)}


def configure_render(objects: list[bpy.types.Object], render_out: Path) -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.035, 0.038, 0.04)

    bounds = object_bounds(objects)
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    camera_data = bpy.data.cameras.get("CAM_MP_Gridlock_GoWU_NativeUV_Targets") or bpy.data.cameras.new(
        "CAM_MP_Gridlock_GoWU_NativeUV_Targets"
    )
    camera = bpy.data.objects.get(camera_data.name) or bpy.data.objects.new(camera_data.name, camera_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.72, -radius * 0.92, radius * 0.56))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 28.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = max(120000.0, radius * 32.0)
    scene.camera = camera
    scene.render.filepath = str(render_out)
    return {
        "engine": str(scene.render.engine),
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "camera": camera.name,
        "camera_location": vec(camera.location),
        "bounds": bounds,
    }


def isolate_for_preview(target_names: list[str]) -> tuple[list[bpy.types.Object], dict[str, Any]]:
    targets: list[bpy.types.Object] = []
    unavailable: list[str] = []
    for name in target_names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            unavailable.append(f"{name} (missing)")
        elif not visible_mesh(obj):
            unavailable.append(f"{name} (hidden)")
        else:
            targets.append(obj)
    if not targets:
        targets = [obj for obj in bpy.context.scene.objects if visible_mesh(obj) and obj.get("ue_static_mesh_path")][:14]
    keep = set(targets)
    changed = 0
    previous: dict[str, bool] = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        previous[obj.name] = bool(obj.hide_render)
        desired = obj not in keep
        if obj.hide_render != desired:
            obj.hide_render = desired
            changed += 1
    return targets, {"targets_rendered": [obj.name for obj in targets], "unavailable": unavailable, "hide_render_changes": changed, "previous_hide_render": previous}


def restore_hide_render(state: dict[str, Any]) -> None:
    previous = state.get("previous_hide_render") or {}
    for name, value in previous.items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_render = bool(value)


def render_preview(args: argparse.Namespace) -> dict[str, Any]:
    if args.no_render:
        return {"status": "skipped"}
    render_out = Path(args.render_out) if args.render_out else Path(args.proof_out).with_suffix(".png")
    render_out.parent.mkdir(parents=True, exist_ok=True)
    objects, isolation = isolate_for_preview(args.targets)
    render = configure_render(objects, render_out)
    bpy.ops.render.render(write_still=True)
    if args.preview_copy:
        preview = Path(args.preview_copy)
        preview.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(render_out, preview)
    restore_hide_render(isolation)
    return {
        "status": "rendered",
        "render_out": str(render_out),
        "preview_copy": args.preview_copy,
        "isolation": {key: value for key, value in isolation.items() if key != "previous_hide_render"},
        "render": render,
    }


def main() -> int:
    args = parse_args()
    clean_csv = Path(args.clean_csv)
    package_dir = Path(args.decompressed_dir)
    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)

    backup_path = ""
    if not args.no_save and bpy.data.filepath:
        source = Path(bpy.data.filepath)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = source.with_name(f"{source.stem}.before_gowu_native_uv_restore_{stamp}{source.suffix}")
        shutil.copyfile(source, backup)
        backup_path = str(backup)

    rows = {clean_key(row.get("full_path")): row for row in read_csv_rows(clean_csv)}
    package_cache: dict[str, bytes] = {}

    mesh_results: list[dict[str, Any]] = []
    touched_keys: set[str] = set()
    skipped = Counter()
    layouts = Counter()
    offsets = Counter()

    for mesh in bpy.data.meshes:
        key = static_mesh_key_for_mesh(mesh)
        if not key:
            skipped["missing_mesh_ue_full_path"] += 1
            continue
        row = rows.get(key)
        if row is None:
            skipped["missing_clean_row"] += 1
            continue
        if row.get("extract_status") != "bulk_position_index":
            skipped[f"status:{row.get('extract_status', '')}"] += 1
            continue
        data = package_bytes(package_dir, row["package"], package_cache)
        stream = detect_gowu_uv_stream(data, row)
        if stream is None:
            skipped["no_gowu_uv_stream"] += 1
            continue
        result = apply_mesh_uv(mesh, row, stream, data)
        mesh_results.append(result)
        touched_keys.add(key)
        layouts[str(stream["layout"])] += 1
        offsets[str(stream["uv_offsets"])] += 1

    material_result = assign_staticmesh_materials(touched_keys)
    preview = render_preview(args)

    if not args.no_save:
        source = Path(bpy.data.filepath)
        bpy.ops.wm.save_as_mainfile(filepath=str(source))

    proof = {
        "blend_path": bpy.data.filepath,
        "clean_csv": str(clean_csv),
        "decompressed_dir": str(package_dir),
        "basis": [
            "UEViewer GAME_GoWU clamps version for FStaticMeshUVItem3.",
            "FStaticMeshUVStream3 stores NumTexCoords, ItemSize, NumVerts, bUseFullPrecisionUVs, then BulkSerialize payload.",
            "Texcoords are read from the tail of each FStaticMeshUVItem3 item after tangent/color prefix bytes.",
        ],
        "summary": {
            "mode": "no_save" if args.no_save else "saved",
            "updated_mesh_datablocks": len(mesh_results),
            "touched_staticmesh_asset_keys": len(touched_keys),
            "layouts": dict(layouts),
            "uv_offsets": dict(offsets),
            "material_result": material_result,
            "skipped": dict(skipped),
            "backup_path": backup_path,
        },
        "mesh_samples": mesh_results[:80],
        "target_objects": args.targets,
        "preview": preview,
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(proof_out), "summary": proof["summary"], "preview": preview}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
