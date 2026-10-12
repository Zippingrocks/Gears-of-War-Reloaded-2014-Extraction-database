#!/usr/bin/env python3
"""Fix MP_Gridlock Model_2 BSP texture projection using source texture dimensions.

The earlier Model_2 BSP pass decoded FBspSurf pBase/TextureU/TextureV correctly
but normalized the projected coordinates by a fixed 128 Unreal-unit repeat. For
Gridlock's native EphyraCity_Stairtech01 material, the source diffuse and normal
textures are 2048x2048. Keeping the source surface axes and normalizing by the
actual material texture dimensions prevents the main shell from being wildly
over-tiled in Blender while preserving the native BSP projection.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import struct
import sys
import types
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


BSP_CONFIDENCE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)

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
DEFAULT_PROOF = SCENE_DIR / "gridlock_model2_bsp_texel_uv_fix_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_model2_bsp_texel_uv_fix_2026_08_15.png"
DEFAULT_PREVIEW = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_model2_bsp_texel_uv_fix_latest.png")

MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL2_EXPORT_INDEX = 11515
MODEL2_MATERIAL_KEY = "cog_city_ephyra3.ephyracity_stairtech01_pe_mat"
OLD_UV_LAYER = "UV_Source_BSP_Surface"
TEXEL_UV_LAYER = "UV_Source_BSP_MaterialTexel"
TEXEL_NO_FLIP_LAYER = "UV_Source_BSP_MaterialTexel_NoVFlip"
OLD_SCALE = 128.0
NON_COLOR_TOKENS = ("normal", "_nrm", "roughness", "specular", "_spec", "mask", "alpha", "opacity")
MODEL_PREFIX = "Model_"


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


def install_fake_lz4() -> None:
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")

    def _unused_decompress(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("this pass uses the already decompressed .war package")

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
    return load_module(BSP_CONFIDENCE, "gowr_gridlock_bsp_confidence_model2_texel")


bsp = load_bsp_module()
heavy = bsp.heavy


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


def abspath(path: str) -> str:
    try:
        return str(Path(bpy.path.abspath(path)).resolve(strict=False))
    except Exception:
        return str(Path(path).resolve(strict=False))


def load_png_map(path: Path) -> dict[str, str]:
    rows = read_json(path)
    source_rows = rows if isinstance(rows, list) else rows.get("rows", [])
    png_by_source: dict[str, str] = {}
    for row in source_rows:
        if not isinstance(row, dict) or row.get("status") != "converted":
            continue
        source = norm_path(str(row.get("source") or ""))
        png = str(row.get("png") or "")
        if source and png and Path(png).exists():
            png_by_source[source] = png
    return png_by_source


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


def length(v: list[float]) -> float:
    return math.sqrt(dot(v, v))


def read_vecs(virt: bytes, serial_offset: int, rel: int, count: int) -> list[list[float]]:
    return [vec3(virt, serial_offset + rel + idx * 12) for idx in range(count)]


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
        raise RuntimeError(f"export {export_index} is {row.get('class_name')}, not Model")
    return row


def decode_model2(virt: bytes, exports: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    row = model_row(exports, MODEL2_EXPORT_INDEX)
    lm = bsp.find_model_landmarks(virt, row)
    decoded = bsp.decode_model_faces(virt, row, lm)
    if not decoded.get("triangles"):
        raise RuntimeError(f"Model_2 did not decode visible BSP triangles: {decoded.get('status')}")
    return row, lm, decoded


def binding_role(binding: dict[str, Any], role: str) -> dict[str, Any]:
    roles = binding.get("roles")
    if not isinstance(roles, dict):
        return {}
    value = roles.get(role)
    return value if isinstance(value, dict) else {}


def png_for_dds(dds_path: str, png_by_source: dict[str, str]) -> str:
    if not dds_path:
        return ""
    direct = png_by_source.get(norm_path(dds_path), "")
    if direct and Path(direct).exists():
        return direct
    guess = str(Path(dds_path).with_suffix(".png"))
    return guess if Path(guess).exists() else ""


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


def image_is_non_color(path: str, image_name: str = "") -> bool:
    text = f"{path} {image_name}".lower()
    return any(token in text for token in NON_COLOR_TOKENS)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_principled_value(bsdf: bpy.types.Node, names: tuple[str, ...], value: Any) -> None:
    socket = principled_input(bsdf, names)
    if socket is not None and not socket.links:
        socket.default_value = value


def set_enum_value(owner: Any, prop: str, values: list[str]) -> str:
    if not hasattr(owner, prop):
        return ""
    try:
        enum = owner.bl_rna.properties[prop].enum_items
        valid = {item.identifier for item in enum}
    except Exception:
        valid = set(values)
    for value in values:
        if value in valid:
            try:
                setattr(owner, prop, value)
                return value
            except Exception:
                continue
    return str(getattr(owner, prop, ""))


def material_texture_info(material_cache: dict[str, Any], png_by_source: dict[str, str]) -> dict[str, Any]:
    binding = material_cache.get(MODEL2_MATERIAL_KEY)
    if not isinstance(binding, dict):
        raise RuntimeError(f"missing material cache binding: {MODEL2_MATERIAL_KEY}")
    diffuse = binding_role(binding, "diffuse")
    normal = binding_role(binding, "normal")
    diffuse_dds = str(diffuse.get("dds_path") or "")
    normal_dds = str(normal.get("dds_path") or "")
    diffuse_width = int(diffuse.get("dds_width") or diffuse.get("width") or 2048)
    diffuse_height = int(diffuse.get("dds_height") or diffuse.get("height") or 2048)
    normal_width = int(normal.get("dds_width") or normal.get("width") or diffuse_width)
    normal_height = int(normal.get("dds_height") or normal.get("height") or diffuse_height)
    if diffuse_width <= 0 or diffuse_height <= 0:
        diffuse_width, diffuse_height = 2048, 2048
    return {
        "binding": binding,
        "material_path": str(binding.get("material_path") or "COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT"),
        "diffuse_dds": diffuse_dds,
        "normal_dds": normal_dds,
        "diffuse_png": png_for_dds(diffuse_dds, png_by_source),
        "normal_png": png_for_dds(normal_dds, png_by_source),
        "diffuse_size": [diffuse_width, diffuse_height],
        "normal_size": [normal_width, normal_height],
        "missing_referenced_textures": binding.get("missing_referenced_textures", []),
        "referenced_textures": binding.get("referenced_textures", []),
    }


def surf_abs_offset(row: dict[str, Any], lm: dict[str, Any], surf_index: int) -> int:
    serial_offset = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    surf_count = i32(virt_global, serial_offset + surf_rel + 4)
    if surf_index < 0 or surf_index >= surf_count:
        raise IndexError(surf_index)
    return serial_offset + surf_rel + 8 + surf_index * bsp.SURF_RECORD_SIZE


virt_global = b""


def surf_mapping(
    virt: bytes,
    row: dict[str, Any],
    lm: dict[str, Any],
    surf_index: int,
    pbase_rel: int = 8,
    u_rel: int = 16,
    v_rel: int = 20,
) -> dict[str, Any] | None:
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
    pbase_index = i32(virt, surf_abs + pbase_rel)
    normal_index = i32(virt, surf_abs + 12)
    texture_u_index = i32(virt, surf_abs + u_rel)
    texture_v_index = i32(virt, surf_abs + v_rel)
    if not (0 <= pbase_index < len(points) and 0 <= texture_u_index < len(vectors) and 0 <= texture_v_index < len(vectors)):
        return None
    return {
        "base": points[pbase_index],
        "u": vectors[texture_u_index],
        "v": vectors[texture_v_index],
        "pbase_index": pbase_index,
        "normal_index": normal_index,
        "texture_u_index": texture_u_index,
        "texture_v_index": texture_v_index,
    }


def safe_uv(value: float, divisor: float) -> float:
    if not math.isfinite(value) or divisor == 0.0:
        return 0.0
    return value / divisor


def uv_pair(
    point: list[float],
    mapping: dict[str, Any],
    width: float,
    height: float,
    flip_v: bool = True,
) -> tuple[float, float]:
    delta = sub(point, mapping["base"])
    u_value = safe_uv(dot(delta, mapping["u"]), width)
    v_raw = safe_uv(dot(delta, mapping["v"]), height)
    return (u_value, 1.0 - v_raw if flip_v else v_raw)


def old_uv_pair(point: list[float], mapping: dict[str, Any], flip_v: bool = True) -> tuple[float, float]:
    delta = sub(point, mapping["base"])
    u_value = safe_uv(dot(delta, mapping["u"]), OLD_SCALE)
    v_raw = safe_uv(dot(delta, mapping["v"]), OLD_SCALE)
    return (u_value, 1.0 - v_raw if flip_v else v_raw)


def build_triangle_surface_uvs(
    virt: bytes,
    row: dict[str, Any],
    lm: dict[str, Any],
    decoded: dict[str, Any],
    width: float,
    height: float,
    flip_v: bool,
    old_policy: bool = False,
) -> list[dict[str, Any]]:
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
        uv_by_point: dict[int, tuple[float, float]] = {}
        for point_index in polygon:
            if 0 <= point_index < len(points):
                if old_policy:
                    uv_by_point[point_index] = old_uv_pair(points[point_index], mapping, flip_v=flip_v)
                else:
                    uv_by_point[point_index] = uv_pair(points[point_index], mapping, width, height, flip_v=flip_v)
        for _ in range(max(0, len(polygon) - 2)):
            result.append({"triangle_index": triangle_cursor, "surf_index": surf_index, "uv_by_point": uv_by_point})
            triangle_cursor += 1
    return result


def write_uv_layer(obj: bpy.types.Object, layer_name: str, tri_uvs: list[dict[str, Any]]) -> dict[str, Any]:
    mesh = obj.data
    layer = mesh.uv_layers.get(layer_name)
    created = False
    if layer is None:
        layer = mesh.uv_layers.new(name=layer_name)
        created = True
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
    if values:
        us = [value[0] for value in values]
        vs = [value[1] for value in values]
        uv_min = [min(us), min(vs)]
        uv_max = [max(us), max(vs)]
        uv_span = [uv_max[0] - uv_min[0], uv_max[1] - uv_min[1]]
    else:
        uv_min = [0.0, 0.0]
        uv_max = [0.0, 0.0]
        uv_span = [0.0, 0.0]
    return {
        "layer": layer_name,
        "status": "created" if created else "updated",
        "loops_written": loops_written,
        "missing_polygons": missing_polygons,
        "missing_point_loops": missing_points,
        "uv_min": uv_min,
        "uv_max": uv_max,
        "uv_span": uv_span,
    }


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> None:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return
    mesh.uv_layers.active = layer
    try:
        layer.active_render = True
    except Exception:
        pass


def relink_or_rebuild_model2_material(obj: bpy.types.Object, texture: dict[str, Any]) -> dict[str, Any]:
    mesh = obj.data
    material = mesh.materials[0] if mesh.materials and mesh.materials[0] else None
    if material is None:
        material = bpy.data.materials.new("BSP_NATIVE__COG_City_Ephyra3__EphyraCity_Stairtech01_PE_MAT")
        mesh.materials.append(material)
    material.use_nodes = True
    if material.node_tree is None:
        raise RuntimeError(f"material has no node tree: {material.name}")
    nodes = material.node_tree.nodes
    for node in list(nodes):
        nodes.remove(node)
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (640, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (360, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    set_principled_value(bsdf, ("Base Color",), (0.46, 0.45, 0.41, 1.0))
    set_principled_value(bsdf, ("Roughness",), 0.86)
    set_principled_value(bsdf, ("Metallic",), 0.0)
    set_principled_value(bsdf, ("Specular IOR Level", "Specular"), 0.18)
    set_principled_value(bsdf, ("Alpha",), 1.0)

    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "Model2_BSP_MaterialTexelUV"
    uv_node.label = TEXEL_UV_LAYER
    uv_node.location = (-780, 0)
    uv_node.uv_map = TEXEL_UV_LAYER

    diffuse_path = str(texture.get("diffuse_png") or texture.get("diffuse_dds") or "")
    normal_path = str(texture.get("normal_png") or texture.get("normal_dds") or "")
    diffuse_image = load_image(diffuse_path, non_color=False)
    normal_image = load_image(normal_path, non_color=True)

    linked_nodes: list[str] = []
    base_input = principled_input(bsdf, ("Base Color",))
    normal_input = principled_input(bsdf, ("Normal",))
    if diffuse_image is not None and base_input is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "Model2_BSP_Diffuse_MaterialTexel"
        tex.label = "EphyraCity_Stairtech01_PE_Tex"
        tex.location = (-500, 120)
        tex.image = diffuse_image
        tex.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], base_input)
        linked_nodes.append(tex.name)
    if normal_image is not None and normal_input is not None:
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.name = "Model2_BSP_Normal_MaterialTexel"
        tex_n.label = "EphyraCity_Stairtech01_PE_Normal"
        tex_n.location = (-500, -150)
        tex_n.image = normal_image
        tex_n.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex_n.inputs["Vector"])
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "Model2_BSP_SourceNormal"
        normal_map.location = (-120, -130)
        if "Strength" in normal_map.inputs:
            normal_map.inputs["Strength"].default_value = 0.18
        links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], normal_input)
        linked_nodes.extend([tex_n.name, normal_map.name])

    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])
    material.diffuse_color = (0.46, 0.45, 0.41, 1.0)
    material["source_material_path"] = texture.get("material_path", "")
    material["decoded_diffuse_dds"] = texture.get("diffuse_dds", "")
    material["decoded_normal_dds"] = texture.get("normal_dds", "")
    material["viewport_diffuse_png_alias"] = texture.get("diffuse_png", "")
    material["viewport_normal_png_alias"] = texture.get("normal_png", "")
    material["gridlock_model2_bsp_uv_policy"] = (
        "FBspSurf pBase@8 TextureU@16 TextureV@20 normalized by native diffuse dimensions "
        f"{texture.get('diffuse_size')}, replacing the old fixed 128uu repeat"
    )
    material["gridlock_model2_missing_detail_normal"] = "COG_City_BaseMaterials.COG_City_BaseMat_Crackle3_CP_DetailNormal"
    material["gridlock_model2_missing_detail_tiling"] = 15.0
    material["gridlock_model2_detail_policy"] = (
        "source graph references this detail normal at tiling 15, but it is not in the current Gridlock cache; "
        "kept documented rather than substituting a fake texture"
    )
    obj["gridlock_model2_bsp_uv_policy"] = material["gridlock_model2_bsp_uv_policy"]
    mesh["gridlock_bsp_surface_uv_layer"] = TEXEL_UV_LAYER
    mesh["gridlock_bsp_surface_uv_source"] = material["gridlock_model2_bsp_uv_policy"]
    set_active_uv(mesh, TEXEL_UV_LAYER)
    for polygon in mesh.polygons:
        polygon.material_index = 0
    mesh.update(calc_edges=False)
    return {
        "material": material.name,
        "uv_node": uv_node.name,
        "uv_node_layer": uv_node.uv_map,
        "linked_nodes": linked_nodes,
        "diffuse_path": diffuse_path,
        "normal_path": normal_path,
    }


def quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "p10": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
    values = sorted(values)

    def q(frac: float) -> float:
        idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * frac))))
        return float(values[idx])

    return {"min": float(values[0]), "p10": q(0.1), "median": q(0.5), "p90": q(0.9), "max": float(values[-1])}


def surface_probe(virt: bytes, row: dict[str, Any], lm: dict[str, Any], decoded: dict[str, Any], width: float, height: float) -> dict[str, Any]:
    points = decoded.get("points") or []
    old_spans_u: list[float] = []
    old_spans_v: list[float] = []
    new_spans_u: list[float] = []
    new_spans_v: list[float] = []
    u_lengths: list[float] = []
    v_lengths: list[float] = []
    samples: list[dict[str, Any]] = []
    seen = set()
    for node, polygon in zip(decoded.get("nodes", []), decoded.get("polygons", []), strict=False):
        surf_index = int(node.get("i_surf", -1))
        if surf_index in seen:
            continue
        seen.add(surf_index)
        mapping = surf_mapping(virt, row, lm, surf_index)
        if mapping is None:
            continue
        u_lengths.append(length(mapping["u"]))
        v_lengths.append(length(mapping["v"]))
        old_uvs = [old_uv_pair(points[idx], mapping) for idx in polygon if 0 <= idx < len(points)]
        new_uvs = [uv_pair(points[idx], mapping, width, height) for idx in polygon if 0 <= idx < len(points)]
        if len(old_uvs) >= 2:
            old_us = [uv[0] for uv in old_uvs]
            old_vs = [uv[1] for uv in old_uvs]
            new_us = [uv[0] for uv in new_uvs]
            new_vs = [uv[1] for uv in new_uvs]
            old_spans_u.append(max(old_us) - min(old_us))
            old_spans_v.append(max(old_vs) - min(old_vs))
            new_spans_u.append(max(new_us) - min(new_us))
            new_spans_v.append(max(new_vs) - min(new_vs))
        if len(samples) < 12:
            samples.append(
                {
                    "surf_index": surf_index,
                    "pbase_index": mapping["pbase_index"],
                    "normal_index": mapping["normal_index"],
                    "texture_u_index": mapping["texture_u_index"],
                    "texture_v_index": mapping["texture_v_index"],
                    "u_axis_length": length(mapping["u"]),
                    "v_axis_length": length(mapping["v"]),
                }
            )
    return {
        "unique_surface_count": len(seen),
        "axis_lengths": {"u": quantiles(u_lengths), "v": quantiles(v_lengths)},
        "old_fixed_128_face_uv_span": {"u": quantiles(old_spans_u), "v": quantiles(old_spans_v)},
        "new_texture_dimension_face_uv_span": {"u": quantiles(new_spans_u), "v": quantiles(new_spans_v)},
        "expected_span_reduction": [width / OLD_SCALE, height / OLD_SCALE],
        "samples": samples,
    }


def visible_direct_model_audit() -> dict[str, Any]:
    visible = [
        obj.name
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj.name.startswith(MODEL_PREFIX)
        and "__MP_Gridlock.war__" in obj.name
        and not obj.hide_viewport
        and not obj.hide_render
    ]
    return {
        "visible_direct_model_count": len(visible),
        "visible_direct_model_samples": visible[:80],
        "only_model2_visible": visible == [MODEL2_OBJECT],
    }


def model2_bounds(obj: bpy.types.Object) -> dict[str, Any]:
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
        "radius": float(radius),
    }


def configure_camera(obj: bpy.types.Object) -> dict[str, Any]:
    scene = bpy.context.scene
    bounds = model2_bounds(obj)
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    cam_data = bpy.data.cameras.get("CAM_MP_Gridlock_Model2_TexelUV_Proof") or bpy.data.cameras.new("CAM_MP_Gridlock_Model2_TexelUV_Proof")
    camera = bpy.data.objects.get("CAM_MP_Gridlock_Model2_TexelUV_Proof") or bpy.data.objects.new("CAM_MP_Gridlock_Model2_TexelUV_Proof", cam_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.55, -radius * 0.42, radius * 0.28))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 30.0
    cam_data.clip_start = 0.05
    cam_data.clip_end = max(150000.0, radius * 20.0)
    scene.camera = camera
    return {"camera": camera.name, "location": [float(v) for v in camera.location], "target": bounds["center"], "lens": cam_data.lens, "bounds": bounds}


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
            "gtao_factor": 0.70,
        }.items():
            if hasattr(eevee, prop):
                try:
                    setattr(eevee, prop, value)
                except Exception:
                    pass
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.18
    scene.view_settings.gamma = 1.0
    return {
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
    }


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
    if not args.allow_retired_texel_route:
        proof = {
            "status": "blocked_retired_model2_bsp_texel_route",
            "reason": (
                "This older FBspSurf texel route was proven to smear Model_2 in Blender. "
                "The production visual layer keeps Model_2 hidden as diagnostic source proof."
            ),
            "safe_policy_script": "tools/gowreloaded_gridlock_model2_visual_policy.py",
            "safe_hardening_script": "tools/gowreloaded_gridlock_bsp_visibility_truth_pass.py",
            "would_touch": MODEL2_OBJECT,
            "retired_uv_layers": [TEXEL_UV_LAYER, TEXEL_NO_FLIP_LAYER],
        }
        write_json(Path(args.proof_out), proof)
        print(json.dumps({"proof_out": str(Path(args.proof_out)), "status": proof["status"]}, indent=2, ensure_ascii=True))
        return 0

    material_cache = read_json(Path(args.material_cache))
    png_by_source = load_png_map(Path(args.png_map))
    texture = material_texture_info(material_cache, png_by_source)
    global virt_global
    virt, _names, _imports, exports, _ref_short_name, _ref_path = load_package_tables(Path(args.decompressed))
    virt_global = virt
    row, lm, decoded = decode_model2(virt, exports)

    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"missing Blender object: {MODEL2_OBJECT}")
    mesh = obj.data
    old_layer_before = mesh.uv_layers.get(OLD_UV_LAYER)
    old_layer_was_present = old_layer_before is not None
    width, height = [float(value) for value in texture["diffuse_size"]]
    tri_uvs_texel = build_triangle_surface_uvs(virt, row, lm, decoded, width, height, flip_v=True)
    tri_uvs_texel_no_flip = build_triangle_surface_uvs(virt, row, lm, decoded, width, height, flip_v=False)
    uv_texel = write_uv_layer(obj, TEXEL_UV_LAYER, tri_uvs_texel)
    uv_texel_no_flip = write_uv_layer(obj, TEXEL_NO_FLIP_LAYER, tri_uvs_texel_no_flip)
    if not old_layer_was_present:
        old_uvs = build_triangle_surface_uvs(virt, row, lm, decoded, width, height, flip_v=True, old_policy=True)
        old_layer_result = write_uv_layer(obj, OLD_UV_LAYER, old_uvs)
    else:
        old_layer_result = {"layer": OLD_UV_LAYER, "status": "preserved_existing_layer"}

    material_result = relink_or_rebuild_model2_material(obj, texture)
    probe = surface_probe(virt, row, lm, decoded, width, height)
    direct_model_audit = visible_direct_model_audit()
    camera = configure_camera(obj)
    render_config = configure_render()
    render_result: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_result = render_to(Path(args.render_out))
        render_result["preview_copy"] = str(Path(args.preview_copy))
        render_result["preview_copied"] = copy_preview(Path(args.render_out), Path(args.preview_copy))

    proof = {
        "status": "gridlock_model2_bsp_texel_uv_fix_applied",
        "blend_path": bpy.data.filepath,
        "source_package": str(Path(args.decompressed)),
        "material_cache": str(Path(args.material_cache)),
        "png_map": str(Path(args.png_map)),
        "object": obj.name,
        "mesh": mesh.name,
        "source_model": {
            "export_index": MODEL2_EXPORT_INDEX,
            "full_path": row.get("full_path", ""),
            "decode_status": decoded.get("status", ""),
            "point_count": len(decoded.get("points") or []),
            "polygon_count": len(decoded.get("polygons") or []),
            "triangle_count": len(decoded.get("triangles") or []),
            "surface_record_size": bsp.SURF_RECORD_SIZE,
            "surface_offsets_used": {"material": 0, "pBase": 8, "normal": 12, "TextureU": 16, "TextureV": 20},
        },
        "texture": {
            "material_path": texture.get("material_path"),
            "diffuse_size": texture.get("diffuse_size"),
            "normal_size": texture.get("normal_size"),
            "diffuse_dds": texture.get("diffuse_dds"),
            "diffuse_png": texture.get("diffuse_png"),
            "normal_dds": texture.get("normal_dds"),
            "normal_png": texture.get("normal_png"),
            "referenced_textures": texture.get("referenced_textures"),
            "missing_referenced_textures": texture.get("missing_referenced_textures"),
        },
        "policy_change": {
            "previous": f"FBspSurf projected coordinates divided by fixed {OLD_SCALE:g} Unreal units per repeat",
            "current": f"FBspSurf projected coordinates divided by native diffuse dimensions {int(width)}x{int(height)}",
            "active_uv_layer": TEXEL_UV_LAYER,
            "preserved_old_uv_layer": OLD_UV_LAYER,
        },
        "uv_layers": {
            "old_layer": old_layer_result,
            "texel_flip_v": uv_texel,
            "texel_no_flip_v": uv_texel_no_flip,
            "active": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
        },
        "material": material_result,
        "surface_probe": probe,
        "visible_direct_model_audit": direct_model_audit,
        "camera": camera,
        "render_config": render_config,
        "render": render_result,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for scene_obj in bpy.data.objects if scene_obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }
    scene = bpy.context.scene
    scene["gridlock_model2_bsp_texel_uv_fix"] = proof["status"]
    scene["gridlock_model2_bsp_texel_uv_fix_proof"] = str(Path(args.proof_out))
    write_json(Path(args.proof_out), proof)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(Path(args.proof_out)), "uv": proof["uv_layers"], "material": material_result, "render": render_result}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
