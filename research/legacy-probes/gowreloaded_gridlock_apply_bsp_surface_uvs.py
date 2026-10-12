#!/usr/bin/env python3
"""Apply source BSP surface-projected UVs to MP_Gridlock direct Model meshes."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import struct
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore


BSP_CONFIDENCE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)
UV_LAYER = "UV_Source_BSP_Surface"
BSP_UV_SCALE = 128.0
MODEL_INDEX_RE = re.compile(r"^Model_.+__MP_Gridlock\.war__(\d+)$", re.IGNORECASE)


def install_fake_lz4() -> None:
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")

    def _unused_decompress(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("compressed package decode is not used by this decompressed-package Blender pass")

    block_module.decompress = _unused_decompress  # type: ignore[attr-defined]
    lz4_module.block = block_module  # type: ignore[attr-defined]
    sys.modules.setdefault("lz4", lz4_module)
    sys.modules.setdefault("lz4.block", block_module)


def load_bsp_module():
    install_fake_lz4()
    spec = importlib.util.spec_from_file_location("gowr_bsp_confidence", BSP_CONFIDENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load BSP confidence module: {BSP_CONFIDENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_bsp_confidence"] = module
    spec.loader.exec_module(module)
    return module


bsp = load_bsp_module()
heavy = bsp.heavy


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def vec3(data: bytes, off: int) -> list[float]:
    return [f32(data, off), f32(data, off + 4), f32(data, off + 8)]


def dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def read_vecs(virt: bytes, serial_offset: int, rel: int, count: int) -> list[list[float]]:
    return [vec3(virt, serial_offset + rel + idx * 12) for idx in range(count)]


def finish_uv(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return value / BSP_UV_SCALE


def surf_mapping(virt: bytes, row: dict[str, Any], lm: dict[str, Any], surf_index: int) -> dict[str, Any] | None:
    serial_offset = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    if surf_index < 0:
        return None
    surf_count = i32(virt, serial_offset + surf_rel + 4)
    if surf_index >= surf_count:
        return None
    surf_abs = serial_offset + surf_rel + 8 + surf_index * bsp.SURF_RECORD_SIZE
    points = read_vecs(virt, serial_offset, int(lm["points"]["data_rel"]), int(lm["points"]["count"]))
    vectors = read_vecs(virt, serial_offset, int(lm["vectors"]["data_rel"]), int(lm["vectors"]["count"]))

    pbase_index = i32(virt, surf_abs + 8)
    normal_index = i32(virt, surf_abs + 12)
    texture_u_index = i32(virt, surf_abs + 16)
    texture_v_index = i32(virt, surf_abs + 20)
    if not (0 <= pbase_index < len(points) and 0 <= texture_u_index < len(vectors) and 0 <= texture_v_index < len(vectors)):
        return None
    return {
        "base": points[pbase_index],
        "u": vectors[texture_u_index],
        "v": vectors[texture_v_index],
        "normal_index": normal_index,
        "pbase_index": pbase_index,
        "texture_u_index": texture_u_index,
        "texture_v_index": texture_v_index,
    }


def build_triangle_surface_uvs(virt: bytes, row: dict[str, Any], lm: dict[str, Any], decoded: dict[str, Any]) -> list[dict[str, Any]]:
    points = decoded.get("points") or []
    result: list[dict[str, Any]] = []
    triangle_cursor = 0
    for node, polygon in zip(decoded.get("nodes", []), decoded.get("polygons", []), strict=False):
        surf_index = int(node.get("i_surf", -1))
        mapping = surf_mapping(virt, row, lm, surf_index)
        if mapping is None:
            for _ in range(max(0, len(polygon) - 2)):
                result.append({"triangle_index": triangle_cursor, "surf_index": surf_index, "uv_by_point": {}})
                triangle_cursor += 1
            continue
        base = mapping["base"]
        u_axis = mapping["u"]
        v_axis = mapping["v"]
        uv_by_point: dict[int, tuple[float, float]] = {}
        for point_index in polygon:
            if 0 <= point_index < len(points):
                delta = sub(points[point_index], base)
                uv_by_point[point_index] = (finish_uv(dot(delta, u_axis)), 1.0 - finish_uv(dot(delta, v_axis)))
        for _ in range(max(0, len(polygon) - 2)):
            result.append(
                {
                    "triangle_index": triangle_cursor,
                    "surf_index": surf_index,
                    "uv_by_point": uv_by_point,
                    "mapping": {
                        "pbase_index": mapping["pbase_index"],
                        "texture_u_index": mapping["texture_u_index"],
                        "texture_v_index": mapping["texture_v_index"],
                    },
                }
            )
            triangle_cursor += 1
    return result


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> None:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return
    mesh.uv_layers.active = layer
    try:
        layer.active_render = True
    except Exception:
        pass


def apply_uv_to_object(obj: bpy.types.Object, tri_uvs: list[dict[str, Any]]) -> dict[str, Any]:
    mesh = obj.data
    layer = mesh.uv_layers.get(UV_LAYER)
    created = False
    if layer is None:
        layer = mesh.uv_layers.new(name=UV_LAYER)
        created = True
    loops_written = 0
    missing_polygons = 0
    missing_points = 0
    span_values: list[tuple[float, float]] = []
    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index >= len(tri_uvs):
            missing_polygons += 1
            continue
        uv_by_point = tri_uvs[poly_index].get("uv_by_point") or {}
        for loop_index in poly.loop_indices:
            point_index = int(mesh.loops[loop_index].vertex_index)
            uv = uv_by_point.get(point_index)
            if uv is None:
                missing_points += 1
                continue
            layer.data[loop_index].uv = uv
            span_values.append(uv)
            loops_written += 1
    set_active_uv(mesh, UV_LAYER)
    mesh["gridlock_bsp_surface_uv_layer"] = UV_LAYER
    mesh["gridlock_bsp_surface_uv_source"] = "FBspSurf pBase@8 TextureU@16 TextureV@20, scaled by 128 Unreal units per repeat"
    mesh.update(calc_edges=False)
    if span_values:
        us = [value[0] for value in span_values]
        vs = [value[1] for value in span_values]
        span = [max(us) - min(us), max(vs) - min(vs)]
    else:
        span = [0.0, 0.0]
    return {
        "status": "created" if created else "updated",
        "loops_written": loops_written,
        "missing_polygons": missing_polygons,
        "missing_point_loops": missing_points,
        "uv_span": span,
    }


def material_image_nodes(material: bpy.types.Material) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]


def relink_material_to_bsp_uv(material: bpy.types.Material) -> int:
    if material is None or not material.use_nodes or material.node_tree is None:
        return 0
    image_nodes = material_image_nodes(material)
    if not image_nodes:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    uv_node = nodes.get("Source_BSP_SurfaceUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_BSP_SurfaceUV"
        uv_node.label = "Source BSP Surface UV"
        uv_node.location = (-980, -260)
    try:
        uv_node.uv_map = UV_LAYER
    except Exception:
        pass
    uv_output = uv_node.outputs.get("UV")
    if uv_output is None:
        return 0
    linked = 0
    for image_node in image_nodes:
        vector_input = image_node.inputs.get("Vector")
        if vector_input is None:
            continue
        for existing in list(vector_input.links):
            links.remove(existing)
        links.new(uv_output, vector_input)
        linked += 1
    material["texture_coordinate_uv_map"] = UV_LAYER
    material["gridlock_bsp_surface_uv_relink"] = "image nodes linked to FBspSurf source-projected UV layer"
    return linked


def model_export_index(obj: bpy.types.Object) -> int | None:
    match = MODEL_INDEX_RE.match(obj.name)
    if not match:
        return None
    return int(match.group(1))


def main() -> int:
    args = parse_args()
    package = Path(args.decompressed)
    virt = package.read_bytes()
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])

    results: dict[str, Any] = {}
    updated_meshes: set[bpy.types.Mesh] = set()
    materials: set[bpy.types.Material] = set()
    skipped = Counter()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        export_index = model_export_index(obj)
        if export_index is None:
            continue
        if export_index <= 0 or export_index > len(exports):
            skipped["bad_export_index"] += 1
            continue
        row = exports[export_index - 1]
        if row.get("class_name") != "Model":
            skipped["not_model_export"] += 1
            continue
        lm = bsp.decode_landmarks(virt, names, imports, exports, ref_path, row)
        if not lm:
            skipped["missing_landmarks"] += 1
            continue
        decoded = bsp.decode_model_faces(virt, row, lm)
        if decoded.get("status") not in {"bsp_model_faces_decoded", "bsp_model_faces_decoded_zero_bounds"}:
            skipped[f"decode_status:{decoded.get('status')}"] += 1
            continue
        tri_uvs = build_triangle_surface_uvs(virt, row, lm, decoded)
        result = apply_uv_to_object(obj, tri_uvs)
        obj["gridlock_bsp_surface_uv_repair"] = "source-native FBspSurf projection applied"
        obj["gridlock_bsp_surface_uv_full_path"] = row.get("full_path", "")
        updated_meshes.add(obj.data)
        for slot in obj.material_slots:
            if slot.material is not None:
                materials.add(slot.material)
        if len(results) < 80:
            results[obj.name] = {
                "export_index": export_index,
                "full_path": row.get("full_path", ""),
                "surf_count": decoded.get("surf_count"),
                "node_count": len(decoded.get("nodes", [])),
                "triangle_count": len(decoded.get("triangles", [])),
                **result,
            }

    linked_materials = 0
    linked_image_nodes = 0
    for material in materials:
        linked = relink_material_to_bsp_uv(material)
        if linked:
            linked_materials += 1
            linked_image_nodes += linked

    proof = {
        "blend_path": bpy.data.filepath,
        "decompressed_package": str(package),
        "uv_layer": UV_LAYER,
        "bsp_uv_scale": BSP_UV_SCALE,
        "summary": {
            "updated_model_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH" and model_export_index(obj) is not None and obj.data in updated_meshes),
            "updated_mesh_datablocks": len(updated_meshes),
            "linked_bsp_materials": linked_materials,
            "linked_bsp_image_nodes": linked_image_nodes,
            "skipped": dict(skipped),
        },
        "sample_results": results,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "mesh_datablocks": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_bsp_surface_uv_repair"] = "direct Model BSP meshes have source FBspSurf projected UVs"
    bpy.context.scene["gridlock_bsp_surface_uv_repair_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
