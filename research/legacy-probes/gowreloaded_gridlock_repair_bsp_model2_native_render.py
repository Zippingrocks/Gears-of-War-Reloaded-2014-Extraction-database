#!/usr/bin/env python3
"""Promote Gridlock's native rendered BSP Model_2 and demote null-material source BSP scraps.

This runs inside Blender against the existing MP_Gridlock scene. The key source
truth is that many visible direct Model_* objects have FBspSurf.Material@0 == 0,
while TheWorld.PersistentLevel.Model_2 has real BSP surfaces and a native
material ref. Those source/null models are preserved for diagnostics, but no
longer participate in the visible rendered map.
"""

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
BUILDER_PATH = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_build_textured_blend_scene.py"
)
MODEL2_POLICY_PATH = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")

UV_LAYER = "UV_Source_BSP_Surface"
BSP_UV_SCALE = 128.0
UNIT_SCALE = 0.01
MAIN_MODEL_EXPORT_INDEX = 11515
MAIN_MODEL_OBJECT_NAME = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MAIN_MODEL_MESH_NAME = "BSP__MP_Gridlock.war__11515__Model_2__REAL_RENDERED"
MODEL_INDEX_RE = re.compile(r"^Model_.+__MP_Gridlock\.war__(\d+)", re.IGNORECASE)


def install_fake_lz4() -> None:
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")

    def _unused_decompress(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("compressed package decode is not used by this decompressed-package Blender pass")

    block_module.decompress = _unused_decompress  # type: ignore[attr-defined]
    lz4_module.block = block_module  # type: ignore[attr-defined]
    sys.modules.setdefault("lz4", lz4_module)
    sys.modules.setdefault("lz4.block", block_module)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_bsp_module():
    install_fake_lz4()
    return load_module(BSP_CONFIDENCE, "gowr_gridlock_bsp_confidence")


bsp = load_bsp_module()
heavy = bsp.heavy
builder = load_module(BUILDER_PATH, "gowr_gridlock_blend_builder")
model2_policy = load_module(MODEL2_POLICY_PATH, "gowr_gridlock_model2_visual_policy")


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", required=True)
    parser.add_argument("--material-cache", required=True)
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


def get_child_collection(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
    child = parent.children.get(name)
    if child is None:
        child = bpy.data.collections.new(name)
        parent.children.link(child)
    return child


def collection_path(path: list[str]) -> bpy.types.Collection:
    collection = bpy.context.scene.collection
    for part in path:
        collection = get_child_collection(collection, part)
    return collection


def clear_nodes(nodes: bpy.types.Nodes) -> None:
    for node in list(nodes):
        nodes.remove(node)


def load_package_tables(path: Path) -> tuple[bytes, list[str], list[dict[str, Any]], list[dict[str, Any]], Any, Any]:
    data = path.read_bytes()
    virt, _groups, _mode = heavy.rebuild_virtual_package(data)
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])
    return virt, names, imports, exports, ref_short_name, ref_path


def model_row(exports: list[dict[str, Any]], export_index: int) -> dict[str, Any]:
    if not (1 <= export_index <= len(exports)):
        raise RuntimeError(f"export index out of range: {export_index}")
    row = exports[export_index - 1]
    if row.get("class_name") != "Model":
        raise RuntimeError(f"export {export_index} is not a Model: {row.get('class_name')}")
    return row


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
            result.append({"triangle_index": triangle_cursor, "surf_index": surf_index, "uv_by_point": uv_by_point})
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


def apply_uv_to_mesh(mesh: bpy.types.Mesh, tri_uvs: list[dict[str, Any]]) -> dict[str, Any]:
    layer = mesh.uv_layers.get(UV_LAYER)
    if layer is None:
        layer = mesh.uv_layers.new(name=UV_LAYER)
    loops_written = 0
    missing_polygons = 0
    missing_points = 0
    values: list[tuple[float, float]] = []
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
            values.append(uv)
            loops_written += 1
    set_active_uv(mesh, UV_LAYER)
    mesh["gridlock_bsp_surface_uv_layer"] = UV_LAYER
    mesh["gridlock_bsp_surface_uv_source"] = "FBspSurf pBase@8 TextureU@16 TextureV@20 scaled by 128 Unreal units per repeat"
    mesh.update(calc_edges=False)
    if values:
        us = [value[0] for value in values]
        vs = [value[1] for value in values]
        span = [max(us) - min(us), max(vs) - min(vs)]
        uv_min = [min(us), min(vs)]
        uv_max = [max(us), max(vs)]
    else:
        span = [0.0, 0.0]
        uv_min = [0.0, 0.0]
        uv_max = [0.0, 0.0]
    return {
        "loops_written": loops_written,
        "missing_polygons": missing_polygons,
        "missing_point_loops": missing_points,
        "uv_min": uv_min,
        "uv_max": uv_max,
        "uv_span": span,
    }


def binding_role(binding: dict[str, Any], role: str) -> dict[str, Any]:
    roles = binding.get("roles")
    wanted = role.lower()
    if isinstance(roles, dict):
        for key, value in roles.items():
            if str(key).strip().lower() == wanted and isinstance(value, dict):
                return value
    return {}


def load_image(path: str, non_color: bool) -> bpy.types.Image | None:
    if not path:
        return None
    try:
        return builder.load_image(path, non_color=non_color)
    except Exception:
        return None


def link_uv_to_image(links: bpy.types.NodeLinks, uv_node: bpy.types.Node, image_node: bpy.types.Node) -> None:
    uv_output = uv_node.outputs.get("UV")
    vector_input = image_node.inputs.get("Vector")
    if uv_output is not None and vector_input is not None:
        links.new(uv_output, vector_input)


def make_bsp_material(material_path: str, binding: dict[str, Any]) -> bpy.types.Material:
    safe_name = "BSP_NATIVE__" + material_path.replace(".", "__")
    material = bpy.data.materials.get(safe_name)
    if material is None:
        material = bpy.data.materials.new(safe_name)
    material.use_nodes = True
    material.diffuse_color = builder.hashed_color(material_path)
    material["source_material_path"] = material_path
    material["source_material_export_index"] = int(binding.get("export_index") or 0)
    material["texture_binding_status"] = binding.get("binding_status", "")
    material["texture_binding_evidence"] = binding.get("binding_evidence", "")
    material["texture_coordinate_uv_map"] = UV_LAYER
    material["gridlock_bsp_material_source"] = "FBspSurf.Material@0 from TheWorld.PersistentLevel.Model_2"

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    clear_nodes(nodes)

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (380, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (120, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    base_input = builder.principled_input(bsdf, ("Base Color",))
    roughness_input = builder.principled_input(bsdf, ("Roughness",))
    metallic_input = builder.principled_input(bsdf, ("Metallic",))
    alpha_input = builder.principled_input(bsdf, ("Alpha",))
    normal_input = builder.principled_input(bsdf, ("Normal",))
    if roughness_input is not None:
        roughness_input.default_value = 0.74
    if metallic_input is not None:
        metallic_input.default_value = 0.0
    if alpha_input is not None:
        alpha_input.default_value = 1.0

    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "Source_BSP_SurfaceUV"
    uv_node.label = "Source BSP Surface UV"
    uv_node.location = (-820, -80)
    uv_node.uv_map = UV_LAYER

    diffuse = binding_role(binding, "diffuse")
    diffuse_path = str(diffuse.get("dds_path") or "").strip()
    diffuse_image = load_image(diffuse_path, non_color=False)
    if diffuse_image is not None and base_input is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "Decoded_Diffuse_DDS"
        tex.label = "Decoded Diffuse DDS"
        tex.location = (-520, 120)
        tex.image = diffuse_image
        tex.extension = "REPEAT"
        link_uv_to_image(links, uv_node, tex)
        links.new(tex.outputs["Color"], base_input)
        material["decoded_diffuse_dds"] = diffuse_path
        material["source_diffuse_texture"] = diffuse.get("texture_full_path", "")

    normal = binding_role(binding, "normal")
    normal_path = str(normal.get("dds_path") or "").strip()
    normal_image = load_image(normal_path, non_color=True)
    if normal_image is not None and normal_input is not None:
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.name = "Decoded_Normal_DDS"
        tex_n.label = "Decoded Normal DDS"
        tex_n.location = (-520, -120)
        tex_n.image = normal_image
        tex_n.extension = "REPEAT"
        link_uv_to_image(links, uv_node, tex_n)
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-160, -120)
        normal_map.inputs["Strength"].default_value = 0.45
        links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], normal_input)
        material["decoded_normal_dds"] = normal_path
        material["source_normal_texture"] = normal.get("texture_full_path", "")

    return material


def material_refs_for_model(
    virt: bytes,
    row: dict[str, Any],
    lm: dict[str, Any],
    decoded: dict[str, Any],
    ref_path,
) -> dict[str, Any]:
    serial_offset = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    surf_count = i32(virt, serial_offset + surf_rel + 4)
    used_surfs = sorted({int(node.get("i_surf", -1)) for node in decoded.get("nodes", []) if int(node.get("i_surf", -1)) >= 0})
    counter: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []
    null_count = 0
    for surf_index in used_surfs:
        if surf_index >= surf_count:
            continue
        surf_abs = serial_offset + surf_rel + 8 + surf_index * bsp.SURF_RECORD_SIZE
        ref = i32(virt, surf_abs)
        path = ""
        if ref:
            try:
                path = str(ref_path(ref))
            except Exception:
                path = ""
        else:
            null_count += 1
        if path:
            counter[path] += 1
        if len(samples) < 20:
            samples.append({"surf_index": surf_index, "material_ref": ref, "material_path": path})
    return {
        "used_surf_count": len(used_surfs),
        "null_material_surf_count": null_count,
        "material_counts": dict(counter),
        "samples": samples,
    }


def source_decode_for_model(
    virt: bytes,
    names: list[str],
    imports: list[dict[str, Any]],
    exports: list[dict[str, Any]],
    ref_path,
    export_index: int,
) -> dict[str, Any] | None:
    try:
        row = model_row(exports, export_index)
        lm = bsp.decode_landmarks(virt, names, imports, exports, ref_path, row)
        if lm is None:
            return None
        decoded = bsp.decode_model_faces(virt, row, lm)
        refs = material_refs_for_model(virt, row, lm, decoded, ref_path)
        return {"row": row, "landmarks": lm, "decoded": decoded, "material_refs": refs}
    except Exception as exc:
        return {"error": repr(exc)}


def ue_to_blender(value: list[float]) -> tuple[float, float, float]:
    return builder.ue_to_blender_vertex((float(value[0]), float(value[1]), float(value[2])), UNIT_SCALE)


def make_model2_mesh(decoded: dict[str, Any]) -> tuple[bpy.types.Mesh, tuple[float, float, float], dict[str, Any]]:
    points = decoded.get("points") or []
    triangles = decoded.get("triangles") or []
    blender_points = [ue_to_blender(point) for point in points]
    used_indices = sorted({idx for tri in triangles for idx in tri if 0 <= idx < len(blender_points)})
    if used_indices:
        used = [blender_points[idx] for idx in used_indices]
        mins = [min(point[axis] for point in used) for axis in range(3)]
        maxs = [max(point[axis] for point in used) for axis in range(3)]
        center = tuple((mins[axis] + maxs[axis]) / 2.0 for axis in range(3))
    else:
        mins = [0.0, 0.0, 0.0]
        maxs = [0.0, 0.0, 0.0]
        center = (0.0, 0.0, 0.0)
    local_points = [(point[0] - center[0], point[1] - center[1], point[2] - center[2]) for point in blender_points]
    mesh = bpy.data.meshes.new(MAIN_MODEL_MESH_NAME)
    mesh.from_pydata(local_points, [], triangles)
    mesh.update(calc_edges=True)
    bounds = {
        "used_vertex_count": len(used_indices),
        "min_blender": mins,
        "max_blender": maxs,
        "center_blender": list(center),
    }
    return mesh, center, bounds


def create_or_update_main_model(
    virt: bytes,
    row: dict[str, Any],
    lm: dict[str, Any],
    decoded: dict[str, Any],
    binding: dict[str, Any],
    material_path: str,
) -> dict[str, Any]:
    mesh, center, bounds = make_model2_mesh(decoded)
    tri_uvs = build_triangle_surface_uvs(virt, row, lm, decoded)
    uv_result = apply_uv_to_mesh(mesh, tri_uvs)
    material = make_bsp_material(material_path, binding)
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = 0

    obj = bpy.data.objects.get(MAIN_MODEL_OBJECT_NAME)
    replaced_mesh = ""
    if obj is None:
        obj = bpy.data.objects.new(MAIN_MODEL_OBJECT_NAME, mesh)
    else:
        old_mesh = obj.data if obj.type == "MESH" else None
        obj.data = mesh
        if old_mesh is not None and old_mesh.users == 0:
            replaced_mesh = old_mesh.name
            bpy.data.meshes.remove(old_mesh)
    obj.location = center
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"
    obj["ue_class"] = "Model"
    obj["ue_package"] = "MP_Gridlock.war"
    obj["ue_export_index"] = MAIN_MODEL_EXPORT_INDEX
    obj["ue_full_path"] = str(row.get("full_path") or "")
    obj["decode_status"] = str(decoded.get("status") or "")
    obj["gridlock_bsp_render_classification"] = "source_native_rendered_main_bsp_zero_bounds_model"
    obj["gridlock_bsp_material_path"] = material_path
    obj["gridlock_bsp_surface_uv_layer"] = UV_LAYER

    mesh["ue_export_index"] = MAIN_MODEL_EXPORT_INDEX
    mesh["ue_full_path"] = str(row.get("full_path") or "")
    mesh["decode_status"] = str(decoded.get("status") or "")
    mesh["gridlock_bsp_render_classification"] = "source_native_rendered_main_bsp_zero_bounds_model"

    target_collection = collection_path([model2_policy.DIAGNOSTIC_COLLECTION])
    if obj.name not in target_collection.objects:
        target_collection.objects.link(obj)
    if not obj.users_collection:
        bpy.context.scene.collection.objects.link(obj)

    return {
        "object": obj.name,
        "mesh": mesh.name,
        "replaced_mesh": replaced_mesh,
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "tri_uv_records": len(tri_uvs),
        "uv_result": uv_result,
        "location": list(obj.location),
        "dimensions": list(obj.dimensions),
        "bounds": bounds,
        "material": material.name,
        "diffuse_dds": material.get("decoded_diffuse_dds", ""),
        "normal_dds": material.get("decoded_normal_dds", ""),
    }


def object_export_index(obj: bpy.types.Object) -> int | None:
    match = MODEL_INDEX_RE.match(obj.name)
    if match:
        return int(match.group(1))
    value = obj.get("ue_export_index")
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def demote_null_material_direct_models(
    virt: bytes,
    names: list[str],
    imports: list[dict[str, Any]],
    exports: list[dict[str, Any]],
    ref_path,
) -> dict[str, Any]:
    target_collection = collection_path(["BSP_Model", "Source_CSG_Brushes_Not_Game_Rendered_NullMaterial"])
    demoted: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            continue
        export_index = object_export_index(obj)
        if export_index is None or export_index == MAIN_MODEL_EXPORT_INDEX:
            continue
        if "MP_Gridlock.war" not in obj.name and str(obj.get("ue_package", "")) != "MP_Gridlock.war":
            continue
        if not obj.name.lower().startswith("model_"):
            continue
        decoded_info = source_decode_for_model(virt, names, imports, exports, ref_path, export_index)
        if not decoded_info or decoded_info.get("error"):
            failed.append({"object": obj.name, "export_index": export_index, "error": decoded_info.get("error") if decoded_info else "decode_failed"})
            continue
        refs = decoded_info["material_refs"]
        material_counts = refs.get("material_counts") or {}
        if material_counts:
            kept.append({"object": obj.name, "export_index": export_index, "material_counts": material_counts})
            continue
        if obj.name not in target_collection.objects:
            target_collection.objects.link(obj)
        obj.hide_viewport = True
        obj.hide_render = True
        obj.display_type = "WIRE"
        obj["game_render_visibility"] = "disabled_native_FBspSurf_Material_at_0_is_null"
        obj["gridlock_bsp_source_brush_classification"] = "source_csg_or_collision_not_game_rendered"
        obj["gridlock_bsp_surface_material_refs"] = "none_at_FBspSurf.Material@0"
        demoted.append(
            {
                "object": obj.name,
                "export_index": export_index,
                "used_surf_count": refs.get("used_surf_count", 0),
                "null_material_surf_count": refs.get("null_material_surf_count", 0),
                "collections": sorted(collection.name for collection in obj.users_collection),
            }
        )
    return {
        "demoted_count": len(demoted),
        "demoted_samples": demoted[:80],
        "kept_count": len(kept),
        "kept_samples": kept[:80],
        "failed_count": len(failed),
        "failed_samples": failed[:40],
    }


def visible_direct_bsp_summary() -> dict[str, Any]:
    visible = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and not obj.hide_viewport
        and not obj.hide_render
        and obj.name.startswith("Model_")
        and "__MP_Gridlock.war__" in obj.name
    ]
    placeholder = []
    for obj in visible:
        material_names = [slot.material.name if slot.material else "" for slot in obj.material_slots]
        if any("NoBSPTextureBindingYet" in name or "DECODED_BSP_Model" in name for name in material_names):
            placeholder.append(obj.name)
    return {
        "visible_direct_model_count": len(visible),
        "visible_direct_model_samples": [obj.name for obj in visible[:80]],
        "visible_placeholder_direct_model_count": len(placeholder),
        "visible_placeholder_direct_model_samples": placeholder[:80],
    }


def main() -> int:
    args = parse_args()
    decompressed = Path(args.decompressed)
    material_cache_path = Path(args.material_cache)
    material_cache = json.loads(material_cache_path.read_text(encoding="utf-8"))

    virt, names, imports, exports, _ref_short_name, ref_path = load_package_tables(decompressed)
    main_info = source_decode_for_model(virt, names, imports, exports, ref_path, MAIN_MODEL_EXPORT_INDEX)
    if not main_info or main_info.get("error"):
        raise RuntimeError(f"could not decode main BSP model: {main_info}")
    row = main_info["row"]
    lm = main_info["landmarks"]
    decoded = main_info["decoded"]
    refs = main_info["material_refs"]
    material_counts = refs.get("material_counts") or {}
    if not material_counts:
        raise RuntimeError("Model_2 did not expose a FBspSurf.Material@0 material ref")
    material_path = max(material_counts, key=lambda key: material_counts[key])
    binding = material_cache.get(material_path.lower())
    if not isinstance(binding, dict):
        raise RuntimeError(f"missing material texture binding for {material_path}")

    main_result = create_or_update_main_model(virt, row, lm, decoded, binding, material_path)
    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        bpy.data.objects.get(MAIN_MODEL_OBJECT_NAME),
        reason="repair_bsp_model2_native_render",
    )
    demote_result = demote_null_material_direct_models(virt, names, imports, exports, ref_path)
    visible_summary = visible_direct_bsp_summary()

    proof = {
        "blend_path": bpy.data.filepath,
        "source_package": str(decompressed),
        "material_cache": str(material_cache_path),
        "classification_note": (
            "Model_2 is source-renderable because it has decoded BSP faces plus a native FBspSurf.Material@0 ref, "
            "but it is hidden from the normal visual layer because A/B render proof showed it is redundant in Blender. "
            "Direct Model_* objects with null FBspSurf.Material@0 are preserved but hidden from rendered view."
        ),
        "main_model_source": {
            "export_index": MAIN_MODEL_EXPORT_INDEX,
            "full_path": row.get("full_path", ""),
            "decode_status": decoded.get("status", ""),
            "point_count": len(decoded.get("points") or []),
            "triangle_count": len(decoded.get("triangles") or []),
            "material_refs": refs,
        },
        "main_model_scene": main_result,
        "model2_visual_policy": model2_policy_result,
        "demoted_null_material_direct_bsp": demote_result,
        "visible_direct_bsp_after": visible_summary,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }

    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(out), "main_model_scene": main_result, "visible_direct_bsp_after": visible_summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
