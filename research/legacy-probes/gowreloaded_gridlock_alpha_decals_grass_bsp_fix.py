#!/usr/bin/env python3
"""Repair MP_Gridlock alpha-card materials and the native Model_2 BSP shader.

This pass is intentionally narrow. The StaticMesh UV breakthrough writes
UV_Source_Render correctly, so this script preserves those UVs and fixes the
remaining visual layer that made grass/decal/ash planes render as opaque slabs.
It also rebuilds the important source-native BSP Model_2 material using the
validated PNG aliases instead of raw DDS viewport paths.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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
DEFAULT_PNG_MAP = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\gridlock_full_material_cache_png_rows_extended_2026_08_15.json"
)
DEFAULT_MATERIAL_CACHE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\gowreloaded_mp_gridlock_material_texture_bindings.json"
)
DEFAULT_PROOF = SCENE_DIR / "gridlock_alpha_decals_grass_bsp_fix_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_alpha_decals_grass_bsp_fix_2026_08_15.png"
DEFAULT_PREVIEW = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_alpha_decals_grass_bsp_fix_latest.png")
MODEL2_POLICY_PATH = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")

MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL2_MATERIAL_KEY = "cog_city_ephyra3.ephyracity_stairtech01_pe_mat"
MODEL2_UV = "UV_Source_BSP_Surface"
STATIC_RENDER_UV = "UV_Source_Render"
INLINE_CARD_UV = "UV0_Source_InlineCard"

FOLIAGE_TOKENS = ("foliage", "grass", "ivy", "leaf", "vine", "bush")
def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


model2_policy = load_module(MODEL2_POLICY_PATH, "gowr_gridlock_model2_visual_policy")


DECAL_TOKENS = (
    "decal",
    "poster",
    "bulletin",
    "waterstain",
    "water_stain",
    "stain",
    "graffiti",
    "paintwall",
    "signage_paint",
    "asphalt_decal",
    "plane_decal",
    "blood",
)
ASH_TOKENS = ("debris_ashes", "ashes", "ash_")
SKIP_ALPHA_REPAIR_TOKENS = (
    "water",
    "ocean",
    "sky",
    "skydome",
    "skybox",
    "fog",
    "cloudshadow",
    "inline_masked_proxy",
)
NON_COLOR_IMAGE_TOKENS = (
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
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--png-map", default=str(DEFAULT_PNG_MAP))
    parser.add_argument("--material-cache", default=str(DEFAULT_MATERIAL_CACHE))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


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
        if not isinstance(row, dict):
            continue
        if row.get("status") != "converted":
            continue
        source = norm_path(str(row.get("source") or ""))
        png = str(row.get("png") or "")
        if source and png and Path(png).exists():
            png_by_source[source] = png
    return png_by_source


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


def texture_nodes(material: bpy.types.Material) -> list[bpy.types.Node]:
    if not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def find_principled(material: bpy.types.Material) -> bpy.types.Node | None:
    if not material.use_nodes or material.node_tree is None:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            return node
    return None


def material_output(material: bpy.types.Material) -> bpy.types.Node | None:
    if not material.use_nodes or material.node_tree is None:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeOutputMaterial":
            return node
    return None


def image_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    return abspath(str(getattr(image, "filepath", "") or ""))


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
    return any(token in text for token in NON_COLOR_IMAGE_TOKENS)


def replace_dds_nodes_with_png(material: bpy.types.Material, png_by_source: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in texture_nodes(material):
        image = getattr(node, "image", None)
        if image is None:
            continue
        old_path = image_path(image)
        png = png_by_source.get(norm_path(old_path), "")
        if not png:
            continue
        new_image = load_image(png, image_is_non_color(old_path, image.name))
        if new_image is None:
            continue
        node.image = new_image
        node["gridlock_png_alias_source_dds"] = old_path
        rows.append({"node": node.name, "old": old_path, "png": png})
    return rows


def material_text(material: bpy.types.Material, users: list[bpy.types.Object] | None = None) -> str:
    parts = [
        material.name,
        str(material.get("ue_material_path", "")),
        str(material.get("source_material_path", "")),
        str(material.get("source_diffuse_texture", "")),
        str(material.get("source_normal_texture", "")),
        str(material.get("decoded_diffuse_dds", "")),
        str(material.get("viewport_png_alias", "")),
    ]
    for node in texture_nodes(material):
        image = getattr(node, "image", None)
        if image is not None:
            parts.extend([image.name, image_path(image)])
    for obj in users or []:
        parts.extend(
            [
                obj.name,
                str(obj.get("ue_static_mesh_path", "")),
                str(obj.get("ue_full_path", "")),
                str(obj.get("gridlock_inline_masked_proxy_uv", "")),
            ]
        )
    return " ".join(parts).lower()


def classify_alpha_family(material: bpy.types.Material, users: list[bpy.types.Object]) -> str:
    text = material_text(material, users)
    if any(token in text for token in SKIP_ALPHA_REPAIR_TOKENS) and not any(token in text for token in ("decal", "poster", "bulletin", "grass", "foliage", "ashes")):
        return ""
    if any(token in text for token in FOLIAGE_TOKENS):
        return "foliage"
    if any(token in text for token in ASH_TOKENS):
        return "ash_decal"
    if any(token in text for token in DECAL_TOKENS):
        return "decal"
    return ""


def choose_base_texture_node(material: bpy.types.Material, bsdf: bpy.types.Node) -> bpy.types.Node | None:
    base_input = principled_input(bsdf, ("Base Color",))
    if base_input is not None:
        for link in base_input.links:
            if link.from_node.bl_idname == "ShaderNodeTexImage" and getattr(link.from_node, "image", None):
                return link.from_node
    candidates: list[bpy.types.Node] = []
    for node in texture_nodes(material):
        image = getattr(node, "image", None)
        if image is None:
            continue
        text = f"{node.name} {node.label} {image.name} {image_path(image)}".lower()
        if any(token in text for token in ("normal", "specular", "_spec", "roughness", "mask")):
            continue
        if any(token in text for token in ("diffuse", "_tex", "delta_tex", "base", "visual")):
            candidates.append(node)
    if candidates:
        return candidates[0]
    nodes = [node for node in texture_nodes(material) if getattr(node, "image", None)]
    return nodes[0] if nodes else None


def set_alpha_material_mode(material: bpy.types.Material, family: str) -> dict[str, Any]:
    if family == "foliage":
        blend = set_enum_value(material, "blend_method", ["HASHED", "CLIP", "BLEND"])
        surface = set_enum_value(material, "surface_render_method", ["DITHERED", "BLENDED"])
        material.diffuse_color = (0.42, 0.44, 0.32, 0.88)
        threshold = 0.34
    else:
        blend = set_enum_value(material, "blend_method", ["BLEND", "HASHED", "CLIP"])
        surface = set_enum_value(material, "surface_render_method", ["BLENDED", "DITHERED"])
        material.diffuse_color = (0.62, 0.60, 0.55, 0.78)
        threshold = 0.06 if family == "decal" else 0.10
    try:
        material.alpha_threshold = threshold
    except Exception:
        pass
    try:
        material.use_backface_culling = False
    except Exception:
        pass
    try:
        material.show_transparent_back = True
    except Exception:
        pass
    try:
        material.use_screen_refraction = False
    except Exception:
        pass
    return {"blend_method": blend, "surface_render_method": surface, "alpha_threshold": threshold}


def ensure_material_has_principled(material: bpy.types.Material) -> bpy.types.Node:
    material.use_nodes = True
    assert material.node_tree is not None
    bsdf = find_principled(material)
    if bsdf is not None:
        return bsdf
    output = material_output(material)
    if output is None:
        output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (420, 0)
    bsdf = material.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (140, 0)
    if "Surface" in output.inputs and "BSDF" in bsdf.outputs:
        material.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return bsdf


def repair_alpha_material(
    material: bpy.types.Material,
    users: list[bpy.types.Object],
    family: str,
    png_by_source: dict[str, str],
) -> dict[str, Any]:
    replaced = replace_dds_nodes_with_png(material, png_by_source)
    bsdf = ensure_material_has_principled(material)
    base_node = choose_base_texture_node(material, bsdf)
    row: dict[str, Any] = {
        "material": material.name,
        "family": family,
        "user_count": len(users),
        "user_samples": [obj.name for obj in users[:12]],
        "dds_to_png_relinks": replaced,
        "alpha_linked": False,
        "base_image": "",
        "base_image_channels": 0,
    }
    if base_node is None:
        row["reason"] = "no_base_texture_node"
        return row
    image = getattr(base_node, "image", None)
    row["base_image"] = image_path(image)
    row["base_image_channels"] = int(getattr(image, "channels", 0) or 0) if image is not None else 0
    if image is not None:
        try:
            image.alpha_mode = "STRAIGHT"
        except Exception:
            pass
    if "Alpha" not in base_node.outputs:
        row["reason"] = "base_texture_has_no_alpha_output"
        return row
    alpha_input = principled_input(bsdf, ("Alpha",))
    if alpha_input is None:
        row["reason"] = "principled_has_no_alpha_input"
        return row
    links = material.node_tree.links
    for link in list(alpha_input.links):
        links.remove(link)
    links.new(base_node.outputs["Alpha"], alpha_input)
    mode = set_alpha_material_mode(material, family)
    set_principled_value(bsdf, ("Roughness",), 0.92 if family in ("decal", "ash_decal") else 0.78)
    set_principled_value(bsdf, ("Metallic",), 0.0)
    material["gridlock_alpha_decal_grass_fix"] = "diffuse PNG alpha wired to Blender material alpha"
    material["gridlock_alpha_family"] = family
    material["gridlock_alpha_source_image"] = row["base_image"]
    material["gridlock_alpha_mode"] = json.dumps(mode)
    row.update(mode)
    row["alpha_linked"] = True
    return row


def material_users() -> dict[bpy.types.Material, list[bpy.types.Object]]:
    users: dict[bpy.types.Material, list[bpy.types.Object]] = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            users.setdefault(material, []).append(obj)
    return users


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


def rebuild_model2_bsp_material(material_cache: dict[str, Any], png_by_source: dict[str, str]) -> dict[str, Any]:
    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None or obj.type != "MESH":
        return {"status": "missing_object", "object": MODEL2_OBJECT}
    mesh = obj.data
    uv = mesh.uv_layers.get(MODEL2_UV)
    if uv is not None:
        mesh.uv_layers.active = uv
        try:
            uv.active_render = True
        except Exception:
            pass
    binding = material_cache.get(MODEL2_MATERIAL_KEY)
    if not isinstance(binding, dict):
        return {"status": "missing_material_cache_binding", "object": obj.name, "material_key": MODEL2_MATERIAL_KEY}

    diffuse = binding_role(binding, "diffuse")
    normal = binding_role(binding, "normal")
    diffuse_dds = str(diffuse.get("dds_path") or "")
    normal_dds = str(normal.get("dds_path") or "")
    diffuse_png = png_for_dds(diffuse_dds, png_by_source)
    normal_png = png_for_dds(normal_dds, png_by_source)

    material = obj.material_slots[0].material if obj.material_slots and obj.material_slots[0].material else None
    if material is None:
        material = bpy.data.materials.new("BSP_NATIVE__COG_City_Ephyra3__EphyraCity_Stairtech01_PE_MAT")
        mesh.materials.append(material)
    material.use_nodes = True
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
    uv_node.name = "Model2_BSP_SourceSurfaceUV"
    uv_node.label = MODEL2_UV
    uv_node.location = (-760, 0)
    uv_node.uv_map = MODEL2_UV

    base_input = principled_input(bsdf, ("Base Color",))
    normal_input = principled_input(bsdf, ("Normal",))
    diffuse_image_path = diffuse_png or diffuse_dds
    normal_image_path = normal_png or normal_dds
    diffuse_image = load_image(diffuse_image_path, non_color=False)
    normal_image = load_image(normal_image_path, non_color=True)

    if diffuse_image is not None and base_input is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "Model2_BSP_Diffuse_PNG_Alias"
        tex.label = "EphyraCity_Stairtech01_PE_Tex"
        tex.location = (-480, 120)
        tex.image = diffuse_image
        tex.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], base_input)
    if normal_image is not None and normal_input is not None:
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.name = "Model2_BSP_Normal_PNG_Alias"
        tex_n.label = "EphyraCity_Stairtech01_PE_Normal"
        tex_n.location = (-480, -150)
        tex_n.image = normal_image
        tex_n.extension = "REPEAT"
        links.new(uv_node.outputs["UV"], tex_n.inputs["Vector"])
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "Model2_BSP_SourceNormal"
        normal_map.location = (-120, -130)
        if "Strength" in normal_map.inputs:
            normal_map.inputs["Strength"].default_value = 0.28
        links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], normal_input)

    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])
    material.diffuse_color = (0.48, 0.47, 0.43, 1.0)
    material["source_material_path"] = binding.get("material_path", "COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT")
    material["source_material_export_index"] = int(binding.get("export_index") or 0)
    material["decoded_diffuse_dds"] = diffuse_dds
    material["decoded_normal_dds"] = normal_dds
    material["viewport_diffuse_png_alias"] = diffuse_png
    material["viewport_normal_png_alias"] = normal_png
    material["gridlock_model2_bsp_fix"] = "rebuilt from source material binding with UV_Source_BSP_Surface and PNG viewport aliases"
    material["gridlock_model2_missing_detail_normal"] = "COG_City_BaseMaterials.COG_City_BaseMat_Crackle3_CP_DetailNormal"
    material["gridlock_model2_missing_detail_tiling"] = 15.0
    material["gridlock_model2_detail_policy"] = "source graph references detail normal at tiling 15; exact texture remains missing from current Reloaded Gridlock cache, so no silent fake is inserted"
    obj["gridlock_model2_bsp_fix"] = material["gridlock_model2_bsp_fix"]
    obj["gridlock_model2_detail_gap"] = material["gridlock_model2_detail_policy"]

    for polygon in mesh.polygons:
        polygon.material_index = 0

    return {
        "status": "rebuilt",
        "object": obj.name,
        "material": material.name,
        "uv_layer_present": uv is not None,
        "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
        "diffuse_dds": diffuse_dds,
        "diffuse_png": diffuse_png,
        "normal_dds": normal_dds,
        "normal_png": normal_png,
        "missing_detail_normal": material["gridlock_model2_missing_detail_normal"],
        "missing_detail_tiling": 15.0,
        "polygon_count": len(mesh.polygons),
    }


def object_bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
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
        mins = Vector((-1, -1, -1))
        maxs = Vector((1, 1, 1))
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


def proof_target_objects(alpha_rows: list[dict[str, Any]]) -> list[bpy.types.Object]:
    names = {
        "debris_ashes_01a_notranslucency_SMesh__26839",
    }
    for row in alpha_rows:
        if row.get("family") in {"decal", "foliage", "ash_decal"}:
            for name in row.get("user_samples", []):
                names.add(str(name))
    objects = [bpy.data.objects[name] for name in names if name in bpy.data.objects]
    if len(objects) > 80:
        target = [bpy.data.objects[name] for name in ("debris_ashes_01a_notranslucency_SMesh__26839",) if name in bpy.data.objects]
        target.extend(objects[:25])
        return target
    return objects


def configure_camera(bounds: dict[str, Any]) -> dict[str, Any]:
    scene = bpy.context.scene
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    cam_data = bpy.data.cameras.get("CAM_MP_Gridlock_AlphaDecalBSP_Proof") or bpy.data.cameras.new("CAM_MP_Gridlock_AlphaDecalBSP_Proof")
    camera = bpy.data.objects.get("CAM_MP_Gridlock_AlphaDecalBSP_Proof") or bpy.data.objects.new("CAM_MP_Gridlock_AlphaDecalBSP_Proof", cam_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.42, -radius * 0.70, radius * 0.38))
    direction = center - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 24.0
    cam_data.clip_start = 0.05
    cam_data.clip_end = max(150000.0, radius * 20.0)
    scene.camera = camera
    return {"camera": camera.name, "location": [float(v) for v in camera.location], "target": bounds["center"], "lens": cam_data.lens}


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
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.28
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
    png_by_source = load_png_map(Path(args.png_map))
    material_cache = read_json(Path(args.material_cache))
    users = material_users()

    alpha_rows: list[dict[str, Any]] = []
    skipped_overlay: list[dict[str, Any]] = []
    for material, mat_users in users.items():
        family = classify_alpha_family(material, mat_users)
        if not family:
            continue
        text = material_text(material, mat_users)
        if material.get("gridlock_inline_masked_proxy_overlay_class") or "inline_proxy__" in material.name.lower():
            skipped_overlay.append(
                {
                    "material": material.name,
                    "family": family,
                    "reason": "preserved_existing_inline_overlay_shader",
                    "user_count": len(mat_users),
                }
            )
            continue
        alpha_rows.append(repair_alpha_material(material, mat_users, family, png_by_source))

    model2 = rebuild_model2_bsp_material(material_cache, png_by_source)
    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        bpy.data.objects.get(MODEL2_OBJECT),
        reason="alpha_decals_grass_bsp_fix",
    )
    target_objects = proof_target_objects(alpha_rows)
    bounds = object_bounds(target_objects)
    render_config = configure_render()
    camera = configure_camera(bounds)

    render_result: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_result = render_to(Path(args.render_out))
        render_result["preview_copy"] = str(Path(args.preview_copy))
        render_result["preview_copied"] = copy_preview(Path(args.render_out), Path(args.preview_copy))

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_alpha_decals_grass_bsp_fix_applied",
        "png_map": str(Path(args.png_map)),
        "png_alias_count": len(png_by_source),
        "policy": {
            "staticmesh_uv": "preserve UV_Source_Render; do not redo the solved staticmesh UV extraction",
            "grass_decals_ashes": "source diffuse PNG alpha is wired to Principled Alpha with masked/translucent material modes",
            "model2_bsp": "source-native material may be maintained for proof, but Model_2 remains hidden by the shared visual-layer policy",
            "model2_detail_normal": "COG_City_BaseMaterials.COG_City_BaseMat_Crackle3_CP_DetailNormal is source-referenced at tiling 15 but still missing from this extraction cache; no fake detail normal was silently inserted",
        },
        "summary": {
            "alpha_materials_repaired": sum(1 for row in alpha_rows if row.get("alpha_linked")),
            "alpha_materials_seen": len(alpha_rows),
            "alpha_user_objects": sum(int(row.get("user_count", 0)) for row in alpha_rows),
            "preserved_inline_overlays": len(skipped_overlay),
            "foliage_materials": sum(1 for row in alpha_rows if row.get("family") == "foliage"),
            "decal_materials": sum(1 for row in alpha_rows if row.get("family") == "decal"),
            "ash_decal_materials": sum(1 for row in alpha_rows if row.get("family") == "ash_decal"),
            "model2_status": model2.get("status"),
        },
        "target_debris_ashes_01a": next(
            (row for row in alpha_rows if "debris_ashes_01a_notranslucency_SMesh__26839" in row.get("user_samples", [])),
            {},
        ),
        "model2_bsp": model2,
        "model2_visual_policy": model2_policy_result,
        "alpha_rows_sample": alpha_rows[:160],
        "preserved_inline_overlays": skipped_overlay[:80],
        "camera": camera,
        "target_bounds": bounds,
        "render_config": render_config,
        "render": render_result,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }
    write_json(Path(args.proof_out), proof)
    scene = bpy.context.scene
    scene["gridlock_alpha_decals_grass_bsp_fix"] = proof["status"]
    scene["gridlock_alpha_decals_grass_bsp_fix_proof"] = str(Path(args.proof_out))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(Path(args.proof_out)), "summary": proof["summary"], "model2": model2, "render": render_result}, indent=2, ensure_ascii=True))
    return 0 if model2.get("status") == "rebuilt" else 1


if __name__ == "__main__":
    raise SystemExit(main())
