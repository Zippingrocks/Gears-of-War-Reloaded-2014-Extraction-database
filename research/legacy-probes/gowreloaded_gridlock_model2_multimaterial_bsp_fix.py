#!/usr/bin/env python3
"""Repair Gridlock Model_2 BSP material assignment from native FBspSurf refs.

This is intentionally scoped to the single visible BSP object:
Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from collections import Counter
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
DEFAULT_PROOF = SCENE_DIR / "gridlock_model2_multimaterial_bsp_fix_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_model2_multimaterial_bsp_fix_2026_08_15.png"
DEFAULT_PREVIEW = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_model2_multimaterial_bsp_fix_latest.png")

RENDERBUFFER_FIX = Path(__file__).with_name("gowreloaded_gridlock_model2_renderbuffer_delta_fix.py")
MODEL2_POLICY = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")

UNIT_SCALE = 0.01
SURF_RECORD_SIZE = 68
MODEL2_EXPORT_INDEX = 11515
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL2_MESH_NAME = "BSP__MP_Gridlock.war__11515__Model_2__REAL_RENDER_BUFFER_MULTIMATERIAL"
MODEL2_RENDER_UV = "UV_Source_BSP_RenderTexCoord"
MODEL2_SHADOW_UV = "UV_Source_BSP_ShadowTexCoord"
NULL_MATERIAL_PATH = "__NULL_BSP_SURF_MATERIAL__"

NON_COLOR_TOKENS = (
    "normal",
    "_nrm",
    "nrm_",
    "specular",
    "_spec",
    "roughness",
    "mask",
    "opacity",
    "alpha",
)


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", default=str(DEFAULT_DECOMPRESSED))
    parser.add_argument("--material-cache", default=str(DEFAULT_MATERIAL_CACHE))
    parser.add_argument("--png-map", default=str(DEFAULT_PNG_MAP))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--show-model2-diagnostic", action="store_true")
    return parser.parse_args(passthrough)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


basefix = load_module(RENDERBUFFER_FIX, "gowr_gridlock_model2_renderbuffer_base_for_multimaterial")
model2_policy = load_module(MODEL2_POLICY, "gowr_gridlock_model2_visual_policy")
probe = basefix.probe


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")


def i32(data: bytes, off: int) -> int:
    return probe.i32(data, off)


def norm_path(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(str(Path(path).resolve(strict=False)))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def load_png_map(path: Path) -> dict[str, str]:
    rows = read_json(path)
    source_rows = rows if isinstance(rows, list) else rows.get("rows", [])
    out: dict[str, str] = {}
    for row in source_rows:
        if not isinstance(row, dict) or row.get("status") != "converted":
            continue
        source = norm_path(str(row.get("source") or ""))
        png = str(row.get("png") or "")
        if source and png and Path(png).exists():
            out[source] = png
    return out


def png_for_source(path: str, png_by_source: dict[str, str]) -> str:
    if not path:
        return ""
    direct = png_by_source.get(norm_path(path), "")
    if direct and Path(direct).exists():
        return direct
    guess = str(Path(path).with_suffix(".png"))
    return guess if Path(guess).exists() else ""


def image_is_non_color(path: str, image_name: str = "") -> bool:
    text = f"{path} {image_name}".lower()
    return any(token in text for token in NON_COLOR_TOKENS)


def load_image(path: str, non_color: bool = False) -> bpy.types.Image | None:
    if not path or not Path(path).exists():
        return None
    image = bpy.data.images.load(path, check_existing=True)
    try:
        image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    except Exception:
        pass
    try:
        image.alpha_mode = "STRAIGHT"
    except Exception:
        pass
    return image


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_principled_value(bsdf: bpy.types.Node, names: tuple[str, ...], value: Any) -> None:
    socket = principled_input(bsdf, names)
    if socket is not None and not socket.links:
        socket.default_value = value


def clear_nodes(material: bpy.types.Material) -> None:
    if material.node_tree is None:
        return
    for node in list(material.node_tree.nodes):
        material.node_tree.nodes.remove(node)


def set_enum_value(owner: Any, prop: str, values: list[str]) -> str:
    if not hasattr(owner, prop):
        return ""
    try:
        valid = {item.identifier for item in owner.bl_rna.properties[prop].enum_items}
    except Exception:
        valid = set(values)
    for value in values:
        if value not in valid:
            continue
        try:
            setattr(owner, prop, value)
            return value
        except Exception:
            pass
    return str(getattr(owner, prop, ""))


def binding_role(binding: dict[str, Any], role: str) -> dict[str, Any]:
    roles = binding.get("roles")
    if not isinstance(roles, dict):
        return {}
    wanted = role.lower()
    for key, value in roles.items():
        if str(key).strip().lower() == wanted and isinstance(value, dict):
            return value
    return {}


def hashed_color(text: str) -> tuple[float, float, float, float]:
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).digest()
    return (
        0.28 + digest[0] / 255.0 * 0.32,
        0.28 + digest[1] / 255.0 * 0.32,
        0.28 + digest[2] / 255.0 * 0.32,
        1.0,
    )


def safe_name(text: str, limit: int = 115) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in text)
    return clean[:limit].strip("._") or "unnamed"


def ue_to_blender(position: list[float] | tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = (float(position[0]), float(position[1]), float(position[2]))
    return (y * UNIT_SCALE, -x * UNIT_SCALE, z * UNIT_SCALE)


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> bool:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return False
    for idx, candidate in enumerate(mesh.uv_layers):
        if candidate.name == layer_name:
            mesh.uv_layers.active_index = idx
            break
    try:
        layer.active_render = True
    except Exception:
        pass
    return True


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


def load_model2_render_source(decompressed: Path) -> dict[str, Any]:
    base = probe.base
    virt, names, imports, exports, _ref_short_name, ref_path = base.load_package_tables(decompressed)
    row, lm, decoded = base.decode_model2(virt, names, imports, exports, ref_path)
    nodes = base.read_nodes_raw(virt, row, lm)
    visible_nodes = [node for node in nodes if int(node["num_vertices"]) >= 3 and int(node["i_vertex_index"]) >= 0]
    required_vertices = max((int(node["i_vertex_index"]) + int(node["num_vertices"]) for node in visible_nodes), default=0)
    tail = base.fvert_tail(virt, row, lm)
    parsed_tail = probe.parse_known_ue3_tail(virt, row, tail, required_vertices)
    candidates = [
        candidate
        for candidate in parsed_tail.get("vertex_buffer_candidates", [])
        if candidate.get("ok") and int(candidate.get("stride") or 0) == 36 and int(candidate.get("count") or 0) >= required_vertices
    ]
    if not candidates:
        raise RuntimeError("Model_2 native FModelVertexBuffer was not found")
    candidate = candidates[0]
    serial = int(row["serial_offset"])
    data_abs = serial + int(candidate["data_rel"])
    count = int(candidate["count"])
    vertices = [probe.read_deprecated_vertex(virt, data_abs + idx * 36) for idx in range(count)]
    return {
        "virt": virt,
        "row": row,
        "landmarks": lm,
        "decoded": decoded,
        "nodes": nodes,
        "visible_nodes": visible_nodes,
        "required_vertices": required_vertices,
        "parsed_tail": parsed_tail,
        "vertex_buffer": candidate,
        "vertices": vertices,
        "ref_path": ref_path,
    }


def surf_material(source: dict[str, Any], surf_index: int) -> dict[str, Any]:
    if surf_index < 0:
        return {"surf_index": surf_index, "material_ref": 0, "material_path": NULL_MATERIAL_PATH}
    virt = source["virt"]
    row = source["row"]
    lm = source["landmarks"]
    serial = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    surf_count = i32(virt, serial + surf_rel + 4)
    if surf_index >= surf_count:
        return {"surf_index": surf_index, "material_ref": 0, "material_path": NULL_MATERIAL_PATH, "reason": "surf_index_oob"}
    surf_abs = serial + surf_rel + 8 + surf_index * SURF_RECORD_SIZE
    material_ref = i32(virt, surf_abs)
    if not material_ref:
        return {"surf_index": surf_index, "material_ref": 0, "material_path": NULL_MATERIAL_PATH}
    try:
        material_path = str(source["ref_path"](material_ref))
    except Exception:
        material_path = NULL_MATERIAL_PATH
    return {"surf_index": surf_index, "material_ref": material_ref, "material_path": material_path or NULL_MATERIAL_PATH}


def build_faces_and_materials(source: dict[str, Any]) -> dict[str, Any]:
    vertex_count = len(source["vertices"])
    faces: list[tuple[int, int, int]] = []
    face_material_paths: list[str] = []
    skipped: list[dict[str, Any]] = []
    node_materials: list[dict[str, Any]] = []
    material_cache: dict[int, dict[str, Any]] = {}
    for node in source["nodes"]:
        start = int(node.get("i_vertex_index", -1))
        num_vertices = int(node.get("num_vertices", 0))
        if num_vertices < 3:
            continue
        if start < 0 or start + num_vertices > vertex_count:
            skipped.append({"node_index": node.get("node_index"), "i_vertex_index": start, "num_vertices": num_vertices})
            continue
        surf_index = int(node.get("i_surf", -1))
        mat = material_cache.get(surf_index)
        if mat is None:
            mat = surf_material(source, surf_index)
            material_cache[surf_index] = mat
        material_path = str(mat["material_path"])
        node_materials.append({"node_index": node.get("node_index"), "surf_index": surf_index, "material_path": material_path, "num_vertices": num_vertices})
        polygon = [start + local for local in range(num_vertices)]
        for local in range(1, num_vertices - 1):
            faces.append((polygon[0], polygon[local], polygon[local + 1]))
            face_material_paths.append(material_path)
    return {
        "faces": faces,
        "face_material_paths": face_material_paths,
        "node_materials": node_materials,
        "skipped_nodes": skipped,
    }


def find_binding(material_cache: dict[str, Any], material_path: str) -> dict[str, Any]:
    if not material_path or material_path == NULL_MATERIAL_PATH:
        return {}
    direct = material_cache.get(material_path.lower())
    if isinstance(direct, dict):
        return direct
    short = material_path.rsplit(".", 1)[-1].lower()
    for key, value in material_cache.items():
        if not isinstance(value, dict):
            continue
        if key.rsplit(".", 1)[-1].lower() == short:
            return value
    return {}


def make_bsp_material(material_path: str, binding: dict[str, Any], png_by_source: dict[str, str], slot: int) -> bpy.types.Material:
    if material_path == NULL_MATERIAL_PATH:
        name = f"BSP_NATIVE__NULL_SURF_MATERIAL__slot_{slot:03d}"
    else:
        name = "BSP_NATIVE__" + safe_name(material_path.replace(".", "__"), 120)
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = hashed_color(material_path)
    clear_nodes(material)
    assert material.node_tree is not None
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (620, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (360, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    set_principled_value(bsdf, ("Base Color",), material.diffuse_color)
    set_principled_value(bsdf, ("Roughness",), 0.84)
    set_principled_value(bsdf, ("Metallic",), 0.0)
    set_principled_value(bsdf, ("Specular IOR Level", "Specular"), 0.24)
    set_principled_value(bsdf, ("Alpha",), 1.0)

    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "Model2_BSP_NativeRenderUV"
    uv_node.label = MODEL2_RENDER_UV
    uv_node.location = (-780, -20)
    uv_node.uv_map = MODEL2_RENDER_UV

    diffuse = binding_role(binding, "diffuse")
    normal = binding_role(binding, "normal")
    specular = binding_role(binding, "specular")
    diffuse_dds = str(diffuse.get("dds_path") or "")
    normal_dds = str(normal.get("dds_path") or "")
    specular_dds = str(specular.get("dds_path") or "")
    diffuse_png = png_for_source(diffuse_dds, png_by_source)
    normal_png = png_for_source(normal_dds, png_by_source)
    specular_png = png_for_source(specular_dds, png_by_source)

    base_input = principled_input(bsdf, ("Base Color",))
    normal_input = principled_input(bsdf, ("Normal",))
    spec_input = principled_input(bsdf, ("Specular IOR Level", "Specular"))
    diffuse_image = load_image(diffuse_png or diffuse_dds, non_color=False)
    normal_image = load_image(normal_png or normal_dds, non_color=True)
    specular_image = load_image(specular_png or specular_dds, non_color=True)
    if diffuse_image is not None and base_input is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "BSP_Diffuse_NativeRenderUV"
        tex.label = diffuse.get("texture_full_path", "BSP diffuse")
        tex.location = (-500, 150)
        tex.image = diffuse_image
        tex.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], base_input)
    if normal_image is not None and normal_input is not None:
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.name = "BSP_Normal_NativeRenderUV"
        tex_n.label = normal.get("texture_full_path", "BSP normal")
        tex_n.location = (-500, -120)
        tex_n.image = normal_image
        tex_n.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex_n.inputs["Vector"])
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "BSP_NormalMap"
        normal_map.location = (-120, -120)
        if "Strength" in normal_map.inputs:
            normal_map.inputs["Strength"].default_value = 0.16
        links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], normal_input)
    if specular_image is not None and spec_input is not None:
        tex_s = nodes.new("ShaderNodeTexImage")
        tex_s.name = "BSP_Specular_NativeRenderUV"
        tex_s.label = specular.get("texture_full_path", "BSP specular")
        tex_s.location = (-500, -380)
        tex_s.image = specular_image
        tex_s.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex_s.inputs["Vector"])
        if "Alpha" in tex_s.outputs:
            links.new(tex_s.outputs["Alpha"], spec_input)

    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])
    material["source_material_path"] = material_path
    material["source_material_export_index"] = int(binding.get("export_index") or 0) if binding else 0
    material["texture_coordinate_uv_map"] = MODEL2_RENDER_UV
    material["gridlock_model2_multimaterial_bsp_fix"] = "FBspSurf.Material per BSP surface, texture nodes linked to native render TexCoord"
    material["decoded_diffuse_dds"] = diffuse_dds
    material["decoded_normal_dds"] = normal_dds
    material["decoded_specular_dds"] = specular_dds
    material["viewport_diffuse_png_alias"] = diffuse_png
    material["viewport_normal_png_alias"] = normal_png
    material["viewport_specular_png_alias"] = specular_png
    material["binding_found"] = bool(binding)
    return material


def make_multimaterial_mesh(source: dict[str, Any], face_data: dict[str, Any], materials: list[bpy.types.Material], material_slot_by_path: dict[str, int]) -> tuple[bpy.types.Mesh, tuple[float, float, float], dict[str, Any]]:
    vertices = source["vertices"]
    faces = face_data["faces"]
    face_material_paths = face_data["face_material_paths"]
    blender_points = [ue_to_blender(vertex["position"]) for vertex in vertices]
    used_indices = sorted({idx for face in faces for idx in face})
    used_points = [blender_points[idx] for idx in used_indices] if used_indices else blender_points
    mins = [min(point[axis] for point in used_points) for axis in range(3)]
    maxs = [max(point[axis] for point in used_points) for axis in range(3)]
    center = tuple((mins[axis] + maxs[axis]) * 0.5 for axis in range(3))
    local_points = [(point[0] - center[0], point[1] - center[1], point[2] - center[2]) for point in blender_points]

    mesh = bpy.data.meshes.new(MODEL2_MESH_NAME)
    mesh.from_pydata(local_points, [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    for material in materials:
        mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.use_smooth = False
        polygon.material_index = material_slot_by_path[face_material_paths[polygon.index]]

    render_layer = mesh.uv_layers.new(name=MODEL2_RENDER_UV)
    shadow_layer = mesh.uv_layers.new(name=MODEL2_SHADOW_UV)
    render_values: list[tuple[float, float]] = []
    shadow_values: list[tuple[float, float]] = []
    for loop in mesh.loops:
        vertex = vertices[loop.vertex_index]
        uv = (float(vertex["texcoord"][0]), float(vertex["texcoord"][1]))
        shadow = (float(vertex["shadow_texcoord"][0]), float(vertex["shadow_texcoord"][1]))
        render_layer.data[loop.index].uv = uv
        shadow_layer.data[loop.index].uv = shadow
        render_values.append(uv)
        shadow_values.append(shadow)
    set_active_uv(mesh, MODEL2_RENDER_UV)

    mesh["ue_export_index"] = MODEL2_EXPORT_INDEX
    mesh["ue_full_path"] = str(source["row"].get("full_path") or "")
    mesh["decode_status"] = str(source["decoded"].get("status") or "")
    mesh["gridlock_bsp_mesh_source"] = "FBspNode.iVertexIndex fan triangles over native FModelVertexBuffer.Position"
    mesh["gridlock_bsp_surface_uv_layer"] = MODEL2_RENDER_UV
    mesh["gridlock_bsp_lightmap_uv_layer"] = MODEL2_SHADOW_UV
    mesh["gridlock_bsp_material_source"] = "FBspSurf.Material per native BSP surface"
    mesh["gridlock_bsp_render_vertex_count"] = len(vertices)
    mesh["gridlock_bsp_render_vertexbuffer_data_rel"] = int(source["vertex_buffer"]["data_rel"])
    mesh["gridlock_bsp_render_vertexbuffer_stride"] = int(source["vertex_buffer"]["stride"])

    return mesh, center, {
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "used_vertex_count": len(used_indices),
        "material_slot_count": len(materials),
        "polygon_material_indices": dict(Counter(str(poly.material_index) for poly in mesh.polygons)),
        "bounds": {"min": mins, "max": maxs, "center": list(center)},
        "render_uv_stats": stats_uv(render_values),
        "shadow_uv_stats": stats_uv(shadow_values),
        "skipped_node_count": len(face_data["skipped_nodes"]),
        "skipped_nodes_sample": face_data["skipped_nodes"][:20],
    }


def make_backup() -> str:
    filepath = Path(bpy.data.filepath)
    if not filepath.exists():
        return ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = filepath.with_name(filepath.stem + f".before_model2_multimaterial_{timestamp}" + filepath.suffix)
    shutil.copy2(filepath, backup)
    return str(backup)


def update_model2(source: dict[str, Any], material_cache: dict[str, Any], png_by_source: dict[str, str]) -> dict[str, Any]:
    face_data = build_faces_and_materials(source)
    material_counts = Counter(face_data["face_material_paths"])
    ordered_paths = [path for path, _count in material_counts.most_common()]
    material_slot_by_path = {path: idx for idx, path in enumerate(ordered_paths)}
    materials: list[bpy.types.Material] = []
    material_rows: list[dict[str, Any]] = []
    for slot, material_path in enumerate(ordered_paths):
        binding = find_binding(material_cache, material_path)
        material = make_bsp_material(material_path, binding, png_by_source, slot)
        materials.append(material)
        material_rows.append(
            {
                "slot": slot,
                "material_path": material_path,
                "triangle_count": int(material_counts[material_path]),
                "binding_found": bool(binding),
                "material": material.name,
                "diffuse_png": material.get("viewport_diffuse_png_alias", ""),
                "normal_png": material.get("viewport_normal_png_alias", ""),
            }
        )
    mesh, center, mesh_info = make_multimaterial_mesh(source, face_data, materials, material_slot_by_path)
    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None:
        obj = bpy.data.objects.new(MODEL2_OBJECT, mesh)
        bpy.context.scene.collection.objects.link(obj)
        replaced_mesh = ""
    else:
        old_mesh = obj.data if obj.type == "MESH" else None
        replaced_mesh = old_mesh.name if old_mesh is not None else ""
        obj.data = mesh
        if old_mesh is not None:
            old_mesh["superseded_by_model2_multimaterial_fix"] = mesh.name
            old_mesh.use_fake_user = True

    obj.location = center
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"
    for stale_key in (
        "gridlock_model2_bsp_uv_policy",
        "gridlock_model2_detail_gap",
    ):
        if stale_key in obj:
            del obj[stale_key]
    obj["ue_class"] = "Model"
    obj["ue_package"] = "MP_Gridlock.war"
    obj["ue_export_index"] = MODEL2_EXPORT_INDEX
    obj["ue_full_path"] = str(source["row"].get("full_path") or "")
    obj["decode_status"] = str(source["decoded"].get("status") or "")
    obj["gridlock_bsp_render_classification"] = "source_native_main_bsp_render_vertexbuffer_multimaterial"
    obj["gridlock_bsp_surface_uv_layer"] = MODEL2_RENDER_UV
    obj["gridlock_bsp_lightmap_uv_layer"] = MODEL2_SHADOW_UV
    obj["gridlock_bsp_material_source"] = "FBspSurf.Material per BSP surface"
    obj["gridlock_model2_bsp_fix"] = "native FModelVertexBuffer render TexCoord plus per-surface FBspSurf material slots"

    return {
        "status": "rebuilt_model2_with_native_render_vertices_and_per_surface_materials",
        "object": obj.name,
        "mesh": mesh.name,
        "replaced_mesh": replaced_mesh,
        "location": [float(v) for v in obj.location],
        "dimensions": [float(v) for v in obj.dimensions],
        "mesh_info": mesh_info,
        "source": {
            "export_index": MODEL2_EXPORT_INDEX,
            "full_path": source["row"].get("full_path", ""),
            "required_vertices_from_nodes": source["required_vertices"],
            "vertex_buffer": {
                "mode": source["vertex_buffer"].get("mode"),
                "stride": source["vertex_buffer"].get("stride"),
                "rel": source["vertex_buffer"].get("rel"),
                "data_rel": source["vertex_buffer"].get("data_rel"),
                "count": source["vertex_buffer"].get("count"),
                "remaining_bytes_after_data": source["vertex_buffer"].get("remaining_bytes_after_data"),
            },
            "tail_steps": source["parsed_tail"].get("steps", []),
        },
        "materials": material_rows,
        "material_summary": {
            "unique_material_paths": len(ordered_paths),
            "unbound_material_paths": sum(1 for row in material_rows if not row["binding_found"]),
            "top_materials": material_rows[:30],
            "null_material_triangles": int(material_counts.get(NULL_MATERIAL_PATH, 0)),
        },
        "node_material_samples": face_data["node_materials"][:80],
    }


def object_world_bounds(obj: bpy.types.Object) -> dict[str, Any]:
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
    radius = max(float(extent.x), float(extent.y), float(extent.z), 1.0) * 0.5
    return {
        "min": [float(mins.x), float(mins.y), float(mins.z)],
        "max": [float(maxs.x), float(maxs.y), float(maxs.z)],
        "center": [float(center.x), float(center.y), float(center.z)],
        "extent": [float(extent.x), float(extent.y), float(extent.z)],
        "radius": radius,
    }


def configure_camera() -> dict[str, Any]:
    scene = bpy.context.scene
    obj = bpy.data.objects[MODEL2_OBJECT]
    bounds = object_world_bounds(obj)
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    camera_data = bpy.data.cameras.get("CAM_MP_Gridlock_Model2_Multimaterial_Proof") or bpy.data.cameras.new("CAM_MP_Gridlock_Model2_Multimaterial_Proof")
    camera = bpy.data.objects.get("CAM_MP_Gridlock_Model2_Multimaterial_Proof") or bpy.data.objects.new("CAM_MP_Gridlock_Model2_Multimaterial_Proof", camera_data)
    if not camera.users_collection:
        scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.55, -radius * 0.78, radius * 0.42))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 26.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = max(150000.0, radius * 22.0)
    scene.camera = camera
    return {"camera": camera.name, "location": [float(v) for v in camera.location], "target": bounds["center"], "lens": camera_data.lens, "bounds": bounds}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.25
    scene.view_settings.gamma = 1.0
    return {"engine": scene.render.engine, "resolution": [scene.render.resolution_x, scene.render.resolution_y], "view_transform": scene.view_settings.view_transform, "look": scene.view_settings.look, "exposure": scene.view_settings.exposure}


def render_to(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return {"path": str(path), "ok": path.exists(), "size": path.stat().st_size if path.exists() else 0}


def copy_preview(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> int:
    args = parse_args()
    backup_path = "" if args.no_backup or args.no_save else make_backup()
    source = load_model2_render_source(Path(args.decompressed))
    material_cache = read_json(Path(args.material_cache))
    png_by_source = load_png_map(Path(args.png_map))
    result = update_model2(source, material_cache, png_by_source)
    if args.show_model2_diagnostic:
        obj = bpy.data.objects.get(MODEL2_OBJECT)
        if obj is not None:
            obj.hide_viewport = False
            obj.hide_render = False
            obj.hide_select = False
            obj.display_type = "TEXTURED"
        model2_policy_result = {"status": "diagnostic_visible_requested", "object": MODEL2_OBJECT}
    else:
        model2_policy_result = model2_policy.apply_model2_visual_policy(
            bpy,
            bpy.data.objects.get(MODEL2_OBJECT),
            reason="model2_multimaterial_bsp_fix",
        )
    render_config = configure_render()
    camera = configure_camera()
    render_result: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof and not args.show_model2_diagnostic:
        render_result = {"render_requested": True, "status": "skipped_hidden_model2_visual_policy", "reason": "Use --show-model2-diagnostic only for isolated shader research."}
    elif args.render_proof:
        render_result = render_to(Path(args.render_out))
        render_result["preview_copy"] = str(Path(args.preview_copy))
        render_result["preview_copied"] = copy_preview(Path(args.render_out), Path(args.preview_copy))

    proof = {
        "blend_path": bpy.data.filepath,
        "backup_before_save": backup_path,
        "status": "gridlock_model2_multimaterial_bsp_fix_applied",
        "scope": "Only Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP is touched, and it is hidden by default as diagnostic source proof; visible staticmesh/Delta objects are not edited by this pass.",
        "inputs": {
            "decompressed": str(Path(args.decompressed)),
            "material_cache": str(Path(args.material_cache)),
            "png_map": str(Path(args.png_map)),
            "png_alias_count": len(png_by_source),
        },
        "model2": result,
        "model2_visual_policy": model2_policy_result,
        "camera": camera,
        "render_config": render_config,
        "render": render_result,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "mesh_datablocks": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
    }
    out = Path(args.proof_out)
    write_json(out, proof)
    bpy.context.scene["gridlock_model2_multimaterial_bsp_fix"] = proof["status"]
    bpy.context.scene["gridlock_model2_multimaterial_bsp_fix_proof"] = str(out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(out), "backup": backup_path, "model2": result["mesh_info"], "materials": result["material_summary"], "render": render_result}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
