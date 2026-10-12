#!/usr/bin/env python3
"""Fix Gridlock Model_2 BSP with native render vertices and harden Delta SMeshes.

Runs inside Blender against the existing MP_Gridlock Reloaded scene.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
DEFAULT_BLEND = SCENE_DIR / "MP_Gridlock_Reloaded_native_scene.blend"
DEFAULT_DECOMPRESSED = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\MP_Gridlock.decompressed.war"
)
DEFAULT_MATERIAL_CACHE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\gowreloaded_mp_gridlock_material_texture_bindings.json"
)
DEFAULT_PNG_MAP = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\gridlock_full_material_cache_png_rows_extended_2026_08_15.json"
)
DEFAULT_RENDER_UV_PAYLOAD = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\gridlock_layout_render_uv_payload_restored_2026_08_14.json"
)
DEFAULT_PROOF = SCENE_DIR / "gridlock_model2_renderbuffer_delta_fix_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_model2_renderbuffer_delta_fix_2026_08_15.png"
DEFAULT_PREVIEW = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_model2_renderbuffer_delta_fix_latest.png")

PROBE_V2 = Path(__file__).with_name("gowreloaded_gridlock_model2_render_vertexbuffer_probe_v2.py")
UV_BREAKTHROUGH = Path(__file__).with_name("gowreloaded_gridlock_apply_render_uv_breakthrough.py")
MODEL2_POLICY = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")

UNIT_SCALE = 0.01
MODEL2_EXPORT_INDEX = 11515
MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL2_MESH_NAME = "BSP__MP_Gridlock.war__11515__Model_2__REAL_RENDER_BUFFER"
MODEL2_MATERIAL_KEY = "cog_city_ephyra3.ephyracity_stairtech01_pe_mat"
MODEL2_RENDER_UV = "UV_Source_BSP_RenderTexCoord"
MODEL2_SHADOW_UV = "UV_Source_BSP_ShadowTexCoord"
STATIC_RENDER_UV = "UV_Source_Render"
DELTA_MATERIAL_SUFFIX = "__Delta_SourceRenderUV"

SPECIAL_DELTA_EXCLUDE_TOKENS = (
    "fx_mp_gridlockwater_delta",
    "gridlockwater",
    "water",
    "ocean",
    "sky",
    "skydome",
    "skybox",
    "godray",
    "cloudshadow",
)
TRANSPARENT_TOKENS = (
    "decal",
    "grass",
    "foliage",
    "leaf",
    "vine",
    "shrub",
    "tree",
    "bush",
    "glass",
    "windowpane",
    "godray",
    "cloudshadow",
    "water",
    "ocean",
)
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
    parser.add_argument("--render-uv-payload", default=str(DEFAULT_RENDER_UV_PAYLOAD))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


probe = load_module(PROBE_V2, "gowr_gridlock_model2_render_vb_fix_probe_v2")
uvfix = load_module(UV_BREAKTHROUGH, "gowr_gridlock_render_uv_breakthrough_for_delta")
model2_policy = load_module(MODEL2_POLICY, "gowr_gridlock_model2_visual_policy")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")


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


def image_abs_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    except Exception:
        return str(getattr(image, "filepath", "") or "")


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


def ue_to_blender(position: list[float] | tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = (float(position[0]), float(position[1]), float(position[2]))
    return (y * UNIT_SCALE, -x * UNIT_SCALE, z * UNIT_SCALE)


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
        "tail": tail,
        "parsed_tail": parsed_tail,
        "vertex_buffer": candidate,
        "vertices": vertices,
    }


def model2_faces_from_nodes(nodes: list[dict[str, Any]], vertex_count: int) -> tuple[list[tuple[int, int, int]], list[dict[str, Any]]]:
    faces: list[tuple[int, int, int]] = []
    skipped: list[dict[str, Any]] = []
    for node in nodes:
        start = int(node.get("i_vertex_index", -1))
        num_vertices = int(node.get("num_vertices", 0))
        if num_vertices < 3:
            continue
        if start < 0 or start + num_vertices > vertex_count:
            skipped.append({"node_index": node.get("node_index"), "i_vertex_index": start, "num_vertices": num_vertices})
            continue
        polygon = [start + local for local in range(num_vertices)]
        for local in range(1, num_vertices - 1):
            faces.append((polygon[0], polygon[local], polygon[local + 1]))
    return faces, skipped


def make_model2_mesh(source: dict[str, Any]) -> tuple[bpy.types.Mesh, tuple[float, float, float], dict[str, Any]]:
    vertices = source["vertices"]
    faces, skipped = model2_faces_from_nodes(source["nodes"], len(vertices))
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
    for polygon in mesh.polygons:
        polygon.use_smooth = False

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
    mesh["gridlock_bsp_render_vertexbuffer_source"] = "UE3 cooked UModel FModelVertexBuffer, deprecated stride36 Position/TangentX/TangentZ/TexCoord/ShadowTexCoord"
    mesh["gridlock_bsp_render_vertex_count"] = len(vertices)
    mesh["gridlock_bsp_render_vertexbuffer_data_rel"] = int(source["vertex_buffer"]["data_rel"])
    mesh["gridlock_bsp_render_vertexbuffer_stride"] = int(source["vertex_buffer"]["stride"])

    return mesh, center, {
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "skipped_node_count": len(skipped),
        "skipped_nodes_sample": skipped[:20],
        "used_vertex_count": len(used_indices),
        "bounds": {"min": mins, "max": maxs, "center": list(center)},
        "render_uv_stats": stats_uv(render_values),
        "shadow_uv_stats": stats_uv(shadow_values),
    }


def make_model2_material(material_cache: dict[str, Any], png_by_source: dict[str, str]) -> bpy.types.Material:
    binding = material_cache.get(MODEL2_MATERIAL_KEY)
    if not isinstance(binding, dict):
        for key, value in material_cache.items():
            if "ephyracity_stairtech01_pe_mat" in str(key).lower() and isinstance(value, dict):
                binding = value
                break
    if not isinstance(binding, dict):
        raise RuntimeError(f"missing Model_2 material binding: {MODEL2_MATERIAL_KEY}")

    material_path = str(binding.get("material_path") or "COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT")
    safe_name = "BSP_NATIVE__" + material_path.replace(".", "__") + "__RenderVertexBuffer"
    material = bpy.data.materials.get(safe_name) or bpy.data.materials.new(safe_name)
    material.use_nodes = True
    material.diffuse_color = (0.48, 0.47, 0.43, 1.0)
    clear_nodes(material)
    assert material.node_tree is not None
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (620, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (360, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    set_principled_value(bsdf, ("Base Color",), (0.48, 0.47, 0.43, 1.0))
    set_principled_value(bsdf, ("Roughness",), 0.84)
    set_principled_value(bsdf, ("Metallic",), 0.0)
    set_principled_value(bsdf, ("Specular IOR Level", "Specular"), 0.22)
    set_principled_value(bsdf, ("Alpha",), 1.0)

    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "Model2_BSP_NativeRenderUV"
    uv_node.label = MODEL2_RENDER_UV
    uv_node.location = (-780, -20)
    uv_node.uv_map = MODEL2_RENDER_UV

    diffuse = binding_role(binding, "diffuse")
    normal = binding_role(binding, "normal")
    diffuse_dds = str(diffuse.get("dds_path") or "")
    normal_dds = str(normal.get("dds_path") or "")
    diffuse_png = png_for_source(diffuse_dds, png_by_source)
    normal_png = png_for_source(normal_dds, png_by_source)
    diffuse_path = diffuse_png or diffuse_dds
    normal_path = normal_png or normal_dds

    base_input = principled_input(bsdf, ("Base Color",))
    normal_input = principled_input(bsdf, ("Normal",))
    diffuse_image = load_image(diffuse_path, non_color=False)
    normal_image = load_image(normal_path, non_color=True)
    if diffuse_image is not None and base_input is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "Model2_BSP_Diffuse_NativeRenderUV"
        tex.label = diffuse.get("texture_full_path", "EphyraCity_Stairtech01_PE_Tex")
        tex.location = (-500, 120)
        tex.image = diffuse_image
        tex.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], base_input)
    if normal_image is not None and normal_input is not None:
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.name = "Model2_BSP_Normal_NativeRenderUV"
        tex_n.label = normal.get("texture_full_path", "EphyraCity_Stairtech01_PE_Normal")
        tex_n.location = (-500, -150)
        tex_n.image = normal_image
        tex_n.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex_n.inputs["Vector"])
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "Model2_BSP_NormalMap"
        normal_map.location = (-120, -130)
        if "Strength" in normal_map.inputs:
            normal_map.inputs["Strength"].default_value = 0.18
        links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], normal_input)

    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])
    material["source_material_path"] = material_path
    material["source_material_export_index"] = int(binding.get("export_index") or 0)
    material["decoded_diffuse_dds"] = diffuse_dds
    material["decoded_normal_dds"] = normal_dds
    material["viewport_diffuse_png_alias"] = diffuse_png
    material["viewport_normal_png_alias"] = normal_png
    material["texture_coordinate_uv_map"] = MODEL2_RENDER_UV
    material["gridlock_model2_bsp_fix"] = "rebuilt from native FModelVertexBuffer render TexCoord; no projected/editor-point UVs"
    material["gridlock_model2_missing_detail_normal"] = "COG_City_BaseMaterials.COG_City_BaseMat_Crackle3_CP_DetailNormal"
    material["gridlock_model2_missing_detail_tiling"] = 15.0
    return material


def update_model2_object(source: dict[str, Any], material_cache: dict[str, Any], png_by_source: dict[str, str]) -> dict[str, Any]:
    mesh, center, mesh_info = make_model2_mesh(source)
    material = make_model2_material(material_cache, png_by_source)
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = 0

    obj = bpy.data.objects.get(MODEL2_OBJECT)
    replaced_mesh = ""
    if obj is None:
        obj = bpy.data.objects.new(MODEL2_OBJECT, mesh)
        bpy.context.scene.collection.objects.link(obj)
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
    for stale_key in (
        "gridlock_model2_bsp_fix",
        "gridlock_model2_detail_gap",
        "gridlock_model2_bsp_uv_policy",
    ):
        if stale_key in obj:
            del obj[stale_key]
    obj["ue_class"] = "Model"
    obj["ue_package"] = "MP_Gridlock.war"
    obj["ue_export_index"] = MODEL2_EXPORT_INDEX
    obj["ue_full_path"] = str(source["row"].get("full_path") or "")
    obj["decode_status"] = str(source["decoded"].get("status") or "")
    obj["gridlock_bsp_render_classification"] = "source_native_main_bsp_render_vertexbuffer"
    obj["gridlock_bsp_surface_uv_layer"] = MODEL2_RENDER_UV
    obj["gridlock_bsp_lightmap_uv_layer"] = MODEL2_SHADOW_UV
    obj["gridlock_bsp_material_path"] = str(material.get("source_material_path") or "")
    obj["gridlock_model2_bsp_fix"] = "rebuilt from native FModelVertexBuffer render TexCoord; stale texel/projection UV policies retired"

    return {
        "status": "rebuilt_from_native_render_vertexbuffer",
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
        "material": {
            "name": material.name,
            "uv_layer": material.get("texture_coordinate_uv_map", ""),
            "diffuse_dds": material.get("decoded_diffuse_dds", ""),
            "normal_dds": material.get("decoded_normal_dds", ""),
            "diffuse_png": material.get("viewport_diffuse_png_alias", ""),
            "normal_png": material.get("viewport_normal_png_alias", ""),
        },
    }


def material_image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def material_text(material: bpy.types.Material | None, obj: bpy.types.Object | None = None) -> str:
    parts: list[str] = []
    if material is not None:
        parts.extend(
            [
                material.name,
                str(material.get("ue_material_path", "")),
                str(material.get("source_material_path", "")),
                str(material.get("decoded_diffuse_dds", "")),
                str(material.get("viewport_diffuse_png_alias", "")),
            ]
        )
        for node in material_image_nodes(material):
            image = getattr(node, "image", None)
            parts.extend([node.name, getattr(node, "label", ""), image.name if image else "", image_abs_path(image)])
    if obj is not None:
        parts.extend([obj.name, str(obj.get("ue_static_mesh_path", "")), str(obj.get("ue_full_path", ""))])
        if obj.type == "MESH":
            parts.append(str(obj.data.get("ue_full_path", "")))
    return " ".join(parts).lower()


def is_delta_map_staticmesh(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH" or not obj.get("ue_static_mesh_path"):
        return False
    if obj.hide_viewport or obj.hide_render:
        return False
    if obj.get("nonvisual_collision_reference_disabled"):
        return False
    if any("nonvisual" in collection.name.lower() or "collision_reference" in collection.name.lower() for collection in obj.users_collection):
        return False
    text = material_text(None, obj)
    smesh_delta = "delta_smesh" in text or "smesh_delta" in text
    delta_gridlock = "delta_gridlock_01" in text
    delta_material = False
    for slot in obj.material_slots:
        if "delta" in material_text(slot.material, obj):
            delta_material = True
            break
    if not (smesh_delta or delta_gridlock or delta_material):
        return False
    return not any(token in text for token in SPECIAL_DELTA_EXCLUDE_TOKENS)


def is_transparentish(material: bpy.types.Material, obj: bpy.types.Object) -> bool:
    text = material_text(material, obj)
    return any(token in text for token in TRANSPARENT_TOKENS)


def replace_dds_nodes_with_png(material: bpy.types.Material, png_by_source: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for node in material_image_nodes(material):
        image = getattr(node, "image", None)
        if image is None:
            continue
        old_path = image_abs_path(image)
        png = png_for_source(old_path, png_by_source)
        if not png:
            continue
        new_image = load_image(png, image_is_non_color(old_path, image.name))
        if new_image is None:
            continue
        node.image = new_image
        rows.append({"node": node.name, "old": old_path, "png": png})
    return rows


def relink_images_to_uv(material: bpy.types.Material, uv_layer: str) -> int:
    if not material.use_nodes or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    uv_node = nodes.get("Source_StaticMesh_RenderUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_RenderUV"
        uv_node.label = "Source StaticMesh Render UV"
        uv_node.location = (-820, -160)
    try:
        uv_node.uv_map = uv_layer
    except Exception:
        pass
    output = uv_node.outputs.get("UV")
    if output is None:
        return 0
    linked = 0
    for node in material_image_nodes(material):
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for existing in list(vector.links):
            links.remove(existing)
        links.new(output, vector)
        try:
            node.extension = "REPEAT"
        except Exception:
            pass
        image = getattr(node, "image", None)
        if image is not None:
            try:
                image.colorspace_settings.name = "Non-Color" if image_is_non_color(image_abs_path(image), image.name) else "sRGB"
            except Exception:
                pass
        linked += 1
    material["texture_coordinate_uv_map"] = uv_layer
    material["gridlock_delta_source_render_uv"] = "all texture image nodes routed to native StaticMesh UV_Source_Render"
    return linked


def tune_delta_material(material: bpy.types.Material, obj: bpy.types.Object, png_by_source: dict[str, str]) -> dict[str, Any]:
    material.use_nodes = True
    replaced = replace_dds_nodes_with_png(material, png_by_source)
    linked = relink_images_to_uv(material, STATIC_RENDER_UV)
    transparent = is_transparentish(material, obj)
    if transparent:
        set_enum_value(material, "blend_method", ["HASHED", "BLEND", "CLIP"])
        set_enum_value(material, "surface_render_method", ["BLENDED", "DITHERED"])
        try:
            material.show_transparent_back = True
        except Exception:
            pass
    else:
        set_enum_value(material, "blend_method", ["OPAQUE"])
        set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])
        try:
            material.show_transparent_back = False
        except Exception:
            pass
    if material.node_tree is not None:
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                alpha = principled_input(node, ("Alpha",))
                if alpha is not None and not transparent:
                    for link in list(alpha.links):
                        material.node_tree.links.remove(link)
                    alpha.default_value = 1.0
                rough = principled_input(node, ("Roughness",))
                if rough is not None and not rough.links:
                    rough.default_value = 0.82
                spec = principled_input(node, ("Specular IOR Level", "Specular"))
                if spec is not None and not spec.links:
                    spec.default_value = 0.26
            elif node.bl_idname == "ShaderNodeNormalMap" and "Strength" in node.inputs:
                node.inputs["Strength"].default_value = 0.20
    material["gridlock_delta_material_pass"] = "PNG alias relink + UV_Source_Render routing + viewport-safe blend/normal settings"
    return {
        "material": material.name,
        "transparent_policy": transparent,
        "dds_to_png": replaced,
        "texture_nodes_linked": linked,
        "blend_method": str(getattr(material, "blend_method", "")),
    }


def delta_clone_for(original: bpy.types.Material, cache: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if original.name.endswith(DELTA_MATERIAL_SUFFIX):
        return original
    if original.name in cache:
        return cache[original.name]
    clone_name = original.name + DELTA_MATERIAL_SUFFIX
    clone = bpy.data.materials.get(clone_name)
    if clone is None:
        clone = original.copy()
        clone.name = clone_name
    clone["gridlock_delta_clone_source_material"] = original.name
    cache[original.name] = clone
    return clone


def apply_delta_smesh_pass(png_by_source: dict[str, str], render_uv_payload: Path) -> dict[str, Any]:
    uv_summary = {
        "status": "skipped_obsolete_layout_payload",
        "reason": (
            "StaticMesh UV_Source_Render is owned by the repo-confirmed UE3 "
            "StaticMesh UV stream payload decoder. Reapplying the old layout "
            "payload can overwrite the solved UVs and reintroduce texture smear."
        ),
        "obsolete_payload": str(render_uv_payload),
        "authoritative_tool": "gowreloaded_gridlock_apply_repo_uvstream_payload.py",
    }
    material_summary = {"global_material_assignment": "skipped_for_idempotency_delta_slots_are_relinked_by_this_pass"}
    clone_cache: dict[str, bpy.types.Material] = {}
    touched: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    target_objects = [obj for obj in bpy.context.scene.objects if is_delta_map_staticmesh(obj)]
    for obj in target_objects:
        mesh = obj.data
        if mesh.uv_layers.get(STATIC_RENDER_UV) is None:
            skipped.append({"object": obj.name, "reason": "missing_UV_Source_Render", "static_mesh_path": obj.get("ue_static_mesh_path", "")})
            continue
        set_active_uv(mesh, STATIC_RENDER_UV)
        material_rows: list[dict[str, Any]] = []
        for slot in obj.material_slots:
            original = slot.material
            if original is None:
                continue
            if not material_image_nodes(original):
                material_rows.append({"material": original.name, "status": "no_image_nodes"})
                continue
            material = delta_clone_for(original, clone_cache)
            row = tune_delta_material(material, obj, png_by_source)
            slot.link = "OBJECT"
            slot.material = material
            material_rows.append(row)
        obj["gridlock_delta_smesh_fix"] = "native UV_Source_Render active; image nodes routed through render UV"
        obj["gridlock_delta_smesh_fix_payload"] = str(render_uv_payload)
        touched.append(
            {
                "object": obj.name,
                "static_mesh_path": obj.get("ue_static_mesh_path", ""),
                "mesh": mesh.name,
                "vertices": len(mesh.vertices),
                "polygons": len(mesh.polygons),
                "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
                "materials": material_rows,
            }
        )
    return {
        "render_uv_payload": str(render_uv_payload),
        "payload_uv_summary": uv_summary,
        "payload_material_summary": material_summary,
        "target_delta_object_count": len(target_objects),
        "touched_delta_object_count": len(touched),
        "skipped_delta_object_count": len(skipped),
        "unique_delta_material_clones": len(clone_cache),
        "touched_samples": touched[:160],
        "skipped_samples": skipped[:80],
    }


def object_world_bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
    visible = [obj for obj in objects if obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render]
    if not visible:
        visible = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render]
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in visible:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x)
            mins.y = min(mins.y, world.y)
            mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x)
            maxs.y = max(maxs.y, world.y)
            maxs.z = max(maxs.z, world.z)
    if mins.x == float("inf"):
        mins = Vector((-1.0, -1.0, -1.0))
        maxs = Vector((1.0, 1.0, 1.0))
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


def configure_camera(objects: list[bpy.types.Object]) -> dict[str, Any]:
    scene = bpy.context.scene
    bounds = object_world_bounds(objects)
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    camera_data = bpy.data.cameras.get("CAM_MP_Gridlock_RenderBuffer_Delta_Proof") or bpy.data.cameras.new("CAM_MP_Gridlock_RenderBuffer_Delta_Proof")
    camera = bpy.data.objects.get("CAM_MP_Gridlock_RenderBuffer_Delta_Proof") or bpy.data.objects.new("CAM_MP_Gridlock_RenderBuffer_Delta_Proof", camera_data)
    if not camera.users_collection:
        scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.48, -radius * 0.82, radius * 0.42))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 24.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = max(150000.0, radius * 22.0)
    scene.camera = camera
    return {"camera": camera.name, "location": [float(v) for v in camera.location], "target": bounds["center"], "lens": camera_data.lens, "bounds": bounds}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        eevee = scene.eevee
        for prop, value in {
            "taa_render_samples": 96,
            "taa_samples": 48,
            "use_gtao": True,
            "gtao_distance": 260.0,
            "gtao_factor": 0.72,
        }.items():
            if hasattr(eevee, prop):
                try:
                    setattr(eevee, prop, value)
                except Exception:
                    pass
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


def proof_objects(delta_summary: dict[str, Any]) -> list[bpy.types.Object]:
    names: set[str] = set()
    for row in delta_summary.get("touched_samples", [])[:80]:
        name = str(row.get("object") or "")
        if name:
            names.add(name)
    return [bpy.data.objects[name] for name in names if name in bpy.data.objects]


def main() -> int:
    args = parse_args()
    png_by_source = load_png_map(Path(args.png_map))
    material_cache = read_json(Path(args.material_cache))
    model2_source = load_model2_render_source(Path(args.decompressed))
    model2_result = update_model2_object(model2_source, material_cache, png_by_source)
    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        bpy.data.objects.get(MODEL2_OBJECT),
        reason="model2_renderbuffer_delta_fix",
    )
    delta_summary = apply_delta_smesh_pass(png_by_source, Path(args.render_uv_payload))

    objects = proof_objects(delta_summary)
    render_config = configure_render()
    camera = configure_camera(objects)
    render_result: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_result = render_to(Path(args.render_out))
        render_result["preview_copy"] = str(Path(args.preview_copy))
        render_result["preview_copied"] = copy_preview(Path(args.render_out), Path(args.preview_copy))

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_model2_native_renderbuffer_and_delta_smesh_fix_applied",
        "policy": {
            "model2": "BSP Model_2 may be rebuilt for source-native proof, then hidden by the shared visual-layer policy because it is redundant in Blender.",
            "static_delta_smesh": "Delta static meshes are forced through the previously proven UV_Source_Render native StaticMesh UV layer and PNG texture aliases.",
            "excluded_delta_specials": list(SPECIAL_DELTA_EXCLUDE_TOKENS),
        },
        "inputs": {
            "decompressed": str(Path(args.decompressed)),
            "material_cache": str(Path(args.material_cache)),
            "png_map": str(Path(args.png_map)),
            "png_alias_count": len(png_by_source),
            "render_uv_payload": str(Path(args.render_uv_payload)),
        },
        "model2": model2_result,
        "model2_visual_policy": model2_policy_result,
        "delta_smesh": delta_summary,
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
    bpy.context.scene["gridlock_model2_renderbuffer_delta_fix"] = proof["status"]
    bpy.context.scene["gridlock_model2_renderbuffer_delta_fix_proof"] = str(out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(out), "model2": model2_result["mesh_info"], "delta_summary": delta_summary | {"touched_samples": delta_summary.get("touched_samples", [])[:5]}, "render": render_result}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
