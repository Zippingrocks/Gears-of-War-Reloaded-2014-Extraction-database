#!/usr/bin/env python3
"""Refine MP_Gridlock water by splitting close water, vista ocean, and waterfront mesh.

The earlier water pass overmatched object names and put waterfront architecture
and far FactoryOcean planes onto the same material as the close Gridlock water.
This pass restores those buckets separately and renders proof previews.
"""

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


MAP_ROOT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12"
)
SCENE_DIR = MAP_ROOT / "Blender_Scene_2026_08_12"
PNG_CACHE = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\_gridlock_tex_native_png_20260813")
WATER_PNG_CACHE = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\_gridlock_water_png_20260814")
NATIVE_WATER_PNG = SCENE_DIR / "native_water_ocean_decode_2026_08_15" / "png"
NATIVE_WATER_ALIAS = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\_gridlock_water_native_alias_20260815")
TEXTURE_DDS = MAP_ROOT / "Material_Texture_Cache" / "textures_dds"
SKY_BG_DDS = TEXTURE_DDS / "T_SkyDomes.skydome_gridlock_bg_01_Delta_Tex__2048x1024_PF_DXT1_606312fd77ee.dds"
VIS_PREVIEW_DIR = Path(
    r"C:\Users\Bilbo\.codex\visualizations\2026\06\28\019f0bba-7647-7e82-9b57-7c1574085478"
)

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
WATER_COLLECTION = "Water"
WATERFRONT_MATERIAL_PREFIX = "MAT__Delta_Gridlock_01__bsp_gridlock_waterfront"
CLOSE_WATER_MATERIAL = "MAT__FX_MP_GridlockWater__CloseWater_GameView_v2"
VISTA_OCEAN_MATERIAL = "MAT__FX_Ocean_Delta__FactoryOcean_Vista_GameView"
PUDDLE_MATERIAL = "MAT__MP_Gridlock__FloorPuddle_GameView_v2"

DEFAULT_PROOF = SCENE_DIR / "gridlock_water_vista_split_refine_2026_08_15.json"
DEFAULT_CLOSE_RENDER = SCENE_DIR / "gridlock_close_water_refine_2026_08_15.png"
DEFAULT_VISTA_RENDER = SCENE_DIR / "gridlock_vista_water_refine_2026_08_15.png"
DEFAULT_CLOSE_PREVIEW = VIS_PREVIEW_DIR / "gridlock_close_water_refine_latest.png"
DEFAULT_VISTA_PREVIEW = VIS_PREVIEW_DIR / "gridlock_vista_water_refine_latest.png"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--close-render-out", default=str(DEFAULT_CLOSE_RENDER))
    parser.add_argument("--vista-render-out", default=str(DEFAULT_VISTA_RENDER))
    parser.add_argument("--close-preview-copy", default=str(DEFAULT_CLOSE_PREVIEW))
    parser.add_argument("--vista-preview-copy", default=str(DEFAULT_VISTA_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    return parser.parse_args(argv)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def vec3(values: Vector | tuple[float, float, float] | list[float]) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def safe_setattr(owner: Any, prop: str, value: Any) -> bool:
    if not hasattr(owner, prop):
        return False
    try:
        setattr(owner, prop, value)
        return True
    except Exception:
        return False


def set_enum_value(owner: Any, prop: str, preferred: list[str]) -> str:
    if not hasattr(owner, prop):
        return ""
    try:
        available = {item.identifier for item in owner.bl_rna.properties[prop].enum_items}
    except Exception:
        available = set()
    for value in preferred:
        if not available or value in available:
            try:
                setattr(owner, prop, value)
                return str(getattr(owner, prop))
            except Exception:
                continue
    return str(getattr(owner, prop, ""))


def get_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    owner = parent or bpy.context.scene.collection
    if collection.name not in owner.children:
        owner.children.link(collection)
    return collection


def link_object(collection: bpy.types.Collection, obj: bpy.types.Object) -> None:
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def unlink_from_scene_root(obj: bpy.types.Object) -> None:
    root = bpy.context.scene.collection
    if obj.name in root.objects:
        root.objects.unlink(obj)


def find_png(*tokens: str) -> Path | None:
    roots = [
        NATIVE_WATER_ALIAS,
        NATIVE_WATER_PNG,
        SCENE_DIR / "textures_native_png_source_named",
        PNG_CACHE,
        SCENE_DIR / "reconstructed_bc5_normals",
        WATER_PNG_CACHE,
    ]
    lowered = [token.lower() for token in tokens if token]
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.png"):
            name = path.name.lower()
            if all(token in name for token in lowered):
                return path
    return None


def load_image(path: Path | None, colorspace: str) -> bpy.types.Image | None:
    if path is None or not path.exists():
        return None
    resolved = str(path.resolve(strict=False))
    for image in bpy.data.images:
        if bpy.path.abspath(image.filepath) == resolved:
            try:
                image.colorspace_settings.name = colorspace
            except Exception:
                pass
            return image
    try:
        image = bpy.data.images.load(resolved, check_existing=True)
    except Exception:
        return None
    image.filepath = resolved
    try:
        image.colorspace_settings.name = colorspace
    except Exception:
        pass
    try:
        image.alpha_mode = "STRAIGHT"
    except Exception:
        pass
    return image


def principled_socket(bsdf: bpy.types.Node, names: tuple[str, ...]) -> bpy.types.NodeSocket | None:
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_principled(bsdf: bpy.types.Node, names: tuple[str, ...], value: Any) -> None:
    socket = principled_socket(bsdf, names)
    if socket is not None:
        try:
            socket.default_value = value
        except Exception:
            pass


def clear_nodes(material: bpy.types.Material) -> tuple[bpy.types.Nodes, bpy.types.NodeLinks]:
    material.use_nodes = True
    nodes = material.node_tree.nodes
    for node in list(nodes):
        nodes.remove(node)
    return nodes, material.node_tree.links


def make_static_material(
    name: str,
    diffuse: Path | None,
    normal: Path | None,
    specular: Path | None,
    roughness: float,
    normal_strength: float,
) -> dict[str, Any]:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = (0.62, 0.60, 0.54, 1.0)
    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])
    safe_setattr(material, "show_transparent_back", False)
    nodes, links = clear_nodes(material)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (820, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (540, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Roughness",), roughness)
    set_principled(bsdf, ("Metallic",), 0.0)
    set_principled(bsdf, ("Alpha",), 1.0)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.42)
    uv = nodes.new("ShaderNodeTexCoord")
    uv.location = (-760, 120)

    images = {"diffuse": None, "normal": None, "specular": None}
    diffuse_img = load_image(diffuse, "sRGB")
    images["diffuse"] = str(diffuse) if diffuse is not None and diffuse.exists() else ""
    if diffuse_img is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-500, 160)
        tex.image = diffuse_img
        tex.extension = "REPEAT"
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    spec_img = load_image(specular, "Non-Color")
    images["specular"] = str(specular) if specular is not None and specular.exists() else ""
    if spec_img is not None:
        tex_s = nodes.new("ShaderNodeTexImage")
        tex_s.location = (-500, -80)
        tex_s.image = spec_img
        tex_s.extension = "REPEAT"
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (-250, -80)
        ramp.color_ramp.elements[0].position = 0.08
        ramp.color_ramp.elements[0].color = (roughness, roughness, roughness, 1.0)
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = (max(0.18, roughness * 0.55), max(0.18, roughness * 0.55), max(0.18, roughness * 0.55), 1.0)
        links.new(uv.outputs["UV"], tex_s.inputs["Vector"])
        links.new(tex_s.outputs["Color"], ramp.inputs["Fac"])
        rough_socket = principled_socket(bsdf, ("Roughness",))
        if rough_socket is not None:
            links.new(ramp.outputs["Color"], rough_socket)

    normal_img = load_image(normal, "Non-Color")
    images["normal"] = str(normal) if normal is not None and normal.exists() else ""
    if normal_img is not None and principled_socket(bsdf, ("Normal",)):
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.location = (-500, -300)
        tex_n.image = normal_img
        tex_n.extension = "REPEAT"
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (-220, -290)
        nmap.inputs["Strength"].default_value = normal_strength
        links.new(uv.outputs["UV"], tex_n.inputs["Vector"])
        links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    material["gridlock_water_vista_split"] = "waterfront_restored_from_textured_asset_pack_mtl"
    material["source_images"] = json.dumps(images, ensure_ascii=True)
    return {"material": material.name, "images": images, "node_count": len(nodes)}


def make_close_water_material() -> dict[str, Any]:
    occ = find_png("mp_gridlock_occlusion")
    n_hi = find_png("gridlock_normals_hi_freq")
    n_lo = find_png("gridlock_normals_lo_freq")
    foam = find_png("mp_gridlock_foam__")
    foam_prox = find_png("mp_gridlock_foam_proximity")
    foam_coarse = find_png("foam02_coarse")
    foam_medium = find_png("foam02_medium")
    foam_fine = find_png("foam02_fine")
    cusp_02 = find_png("gridlock_cusp_hi_freq_02")
    cusp_03 = find_png("gridlock_cusp_hi_freq_03")
    foam_hi_02 = find_png("gridlock_foam_hi_freq_02")
    foam_hi_03 = find_png("gridlock_foam_hi_freq_03")
    noise = find_png("noise_simple_01")
    sky = find_png("close_gridlock_skydome_cube_equirect__") or find_png("close_gridlock_skydome_cube_equirect") or SKY_BG_DDS
    material = bpy.data.materials.get(CLOSE_WATER_MATERIAL) or bpy.data.materials.new(CLOSE_WATER_MATERIAL)
    material.diffuse_color = (0.032, 0.066, 0.060, 0.62)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    safe_setattr(material, "use_screen_refraction", True)
    set_enum_value(material, "blend_method", ["BLEND", "HASHED", "DITHERED"])
    set_enum_value(material, "surface_render_method", ["BLENDED", "DITHERED"])
    nodes, links = clear_nodes(material)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (1100, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (810, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.022, 0.054, 0.050, 1.0))
    set_principled(bsdf, ("Alpha",), 0.62)
    set_principled(bsdf, ("Roughness",), 0.082)
    set_principled(bsdf, ("Metallic",), 0.0)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.92)
    set_principled(bsdf, ("Transmission Weight", "Transmission"), 0.09)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.36)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.052)
    set_principled(bsdf, ("IOR",), 1.333)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-1280, 120)
    base_rgb = nodes.new("ShaderNodeRGB")
    base_rgb.location = (-740, 150)
    base_rgb.outputs["Color"].default_value = (0.020, 0.052, 0.050, 1.0)
    base_out = base_rgb.outputs["Color"]

    def add_layer(path: Path | None, label: str, scale: float, fac: float, blend: str, low: tuple[float, float, float, float], high: tuple[float, float, float, float], y: float, animate: tuple[float, float] | None = None) -> None:
        nonlocal base_out
        image = load_image(path, "sRGB")
        if image is None:
            return
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-1040, y)
        mapping.inputs["Scale"].default_value[0] = scale
        mapping.inputs["Scale"].default_value[1] = scale
        if animate is not None:
            mapping.inputs["Location"].default_value[0] = 0.0
            mapping.inputs["Location"].default_value[1] = 0.0
            mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
            mapping.inputs["Location"].default_value[0] = animate[0]
            mapping.inputs["Location"].default_value[1] = animate[1]
            mapping.inputs["Location"].keyframe_insert("default_value", frame=180)
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-800, y)
        tex.image = image
        tex.extension = "REPEAT"
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (-550, y)
        ramp.label = label
        ramp.color_ramp.elements[0].position = 0.16
        ramp.color_ramp.elements[0].color = low
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = high
        mix = nodes.new("ShaderNodeMixRGB")
        mix.location = (-240, y)
        mix.blend_type = blend
        mix.inputs["Fac"].default_value = fac
        links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], ramp.inputs["Fac"])
        links.new(base_out, mix.inputs["Color1"])
        links.new(ramp.outputs["Color"], mix.inputs["Color2"])
        base_out = mix.outputs["Color"]

    add_layer(occ, "native mp_gridlock_occlusion", 1.0, 0.20, "ADD", (0.006, 0.018, 0.020, 1), (0.100, 0.145, 0.120, 1), 330)
    add_layer(foam_prox, "native shoreline foam proximity", 1.0, 0.34, "SCREEN", (0.0, 0.0, 0.0, 1), (0.50, 0.58, 0.48, 1), 110)
    add_layer(foam, "native water foam", 1.8, 0.22, "SCREEN", (0.0, 0.0, 0.0, 1), (0.33, 0.42, 0.36, 1), -105, (0.09, -0.05))
    # Keep secondary decoded masks recorded in source_images, but don't load all of them into the proof render graph.
    # The full 28/28 native decode proof remains on disk; this graph stays under Blender's GPU image budget.

    sky_img = load_image(sky, "sRGB")
    if sky_img is not None:
        env = nodes.new("ShaderNodeTexEnvironment")
        env.location = (-520, 560)
        env.image = sky_img
        hue = nodes.new("ShaderNodeHueSaturation")
        hue.location = (-285, 560)
        hue.inputs["Saturation"].default_value = 0.48
        hue.inputs["Value"].default_value = 0.20
        mix_sky = nodes.new("ShaderNodeMixRGB")
        mix_sky.location = (330, 200)
        mix_sky.blend_type = "SCREEN"
        mix_sky.inputs["Fac"].default_value = 0.26
        links.new(coord.outputs["Reflection"], env.inputs["Vector"])
        links.new(env.outputs["Color"], hue.inputs["Color"])
        links.new(base_out, mix_sky.inputs["Color1"])
        links.new(hue.outputs["Color"], mix_sky.inputs["Color2"])
        base_out = mix_sky.outputs["Color"]

    links.new(base_out, bsdf.inputs["Base Color"])

    hi_img = load_image(n_hi, "Non-Color")
    lo_img = load_image(n_lo, "Non-Color")
    normal_out = None
    if hi_img is not None:
        mapping_hi = nodes.new("ShaderNodeMapping")
        mapping_hi.location = (-800, -2070)
        mapping_hi.inputs["Scale"].default_value[0] = 5.4
        mapping_hi.inputs["Scale"].default_value[1] = 5.4
        mapping_hi.inputs["Location"].default_value[0] = 0.0
        mapping_hi.inputs["Location"].default_value[1] = 0.0
        mapping_hi.inputs["Location"].keyframe_insert("default_value", frame=1)
        mapping_hi.inputs["Location"].default_value[0] = 0.31
        mapping_hi.inputs["Location"].default_value[1] = -0.15
        mapping_hi.inputs["Location"].keyframe_insert("default_value", frame=180)
        tex_hi = nodes.new("ShaderNodeTexImage")
        tex_hi.location = (-560, -2070)
        tex_hi.image = hi_img
        tex_hi.extension = "REPEAT"
        links.new(coord.outputs["Generated"], mapping_hi.inputs["Vector"])
        links.new(mapping_hi.outputs["Vector"], tex_hi.inputs["Vector"])
        normal_out = tex_hi.outputs["Color"]
    if lo_img is not None:
        mapping_lo = nodes.new("ShaderNodeMapping")
        mapping_lo.location = (-800, -2290)
        mapping_lo.inputs["Scale"].default_value[0] = 1.8
        mapping_lo.inputs["Scale"].default_value[1] = 1.8
        mapping_lo.inputs["Location"].default_value[0] = 0.0
        mapping_lo.inputs["Location"].default_value[1] = 0.0
        mapping_lo.inputs["Location"].keyframe_insert("default_value", frame=1)
        mapping_lo.inputs["Location"].default_value[0] = -0.12
        mapping_lo.inputs["Location"].default_value[1] = 0.19
        mapping_lo.inputs["Location"].keyframe_insert("default_value", frame=180)
        tex_lo = nodes.new("ShaderNodeTexImage")
        tex_lo.location = (-560, -2290)
        tex_lo.image = lo_img
        tex_lo.extension = "REPEAT"
        links.new(coord.outputs["Generated"], mapping_lo.inputs["Vector"])
        links.new(mapping_lo.outputs["Vector"], tex_lo.inputs["Vector"])
        if normal_out is not None:
            mix_n = nodes.new("ShaderNodeMixRGB")
            mix_n.location = (-285, -2180)
            mix_n.blend_type = "OVERLAY"
            mix_n.inputs["Fac"].default_value = 0.34
            links.new(normal_out, mix_n.inputs["Color1"])
            links.new(tex_lo.outputs["Color"], mix_n.inputs["Color2"])
            normal_out = mix_n.outputs["Color"]
        else:
            normal_out = tex_lo.outputs["Color"]
    if normal_out is not None and principled_socket(bsdf, ("Normal",)):
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (430, -820)
        nmap.inputs["Strength"].default_value = 0.20
        links.new(normal_out, nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    images = {
        "occlusion": str(occ or ""),
        "normal_hi": str(n_hi or ""),
        "normal_lo": str(n_lo or ""),
        "foam": str(foam or ""),
        "foam_proximity": str(foam_prox or ""),
        "foam_coarse": str(foam_coarse or ""),
        "foam_medium": str(foam_medium or ""),
        "foam_fine": str(foam_fine or ""),
        "cusp_02": str(cusp_02 or ""),
        "cusp_03": str(cusp_03 or ""),
        "foam_hi_02": str(foam_hi_02 or ""),
        "foam_hi_03": str(foam_hi_03 or ""),
        "noise": str(noise or ""),
        "sky_equirect_or_fallback": str(sky or ""),
    }
    material["gridlock_water_vista_split"] = "close water uses full native GridlockWater foam/cusp/noise/occlusion/skydome decode"
    material["source_images"] = json.dumps(images, ensure_ascii=True)
    return {"material": material.name, "images": images, "node_count": len(nodes)}


def make_vista_ocean_material() -> dict[str, Any]:
    normal = find_png("T_OceanFoam_Delta_Normal", "BC5") or find_png("T_OceanFoam_Delta_Normal")
    foam = find_png("T_OceanFoam__")
    cloud = find_png("T_CloudTile_Delta")
    sky = find_png("vista_factory_ocean_cube_equirect__") or find_png("vista_factory_ocean_cube_equirect") or SKY_BG_DDS
    material = bpy.data.materials.get(VISTA_OCEAN_MATERIAL) or bpy.data.materials.new(VISTA_OCEAN_MATERIAL)
    material.diffuse_color = (0.030, 0.066, 0.078, 0.70)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    safe_setattr(material, "use_screen_refraction", True)
    set_enum_value(material, "blend_method", ["BLEND", "HASHED", "DITHERED"])
    set_enum_value(material, "surface_render_method", ["BLENDED", "DITHERED"])
    nodes, links = clear_nodes(material)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (980, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (700, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.026, 0.058, 0.070, 1.0))
    set_principled(bsdf, ("Alpha",), 0.70)
    set_principled(bsdf, ("Roughness",), 0.038)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.98)
    set_principled(bsdf, ("Transmission Weight", "Transmission"), 0.045)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.50)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.034)
    set_principled(bsdf, ("IOR",), 1.333)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-1020, 100)
    base = nodes.new("ShaderNodeRGB")
    base.location = (-640, 110)
    base.outputs["Color"].default_value = (0.024, 0.056, 0.068, 1.0)
    base_out = base.outputs["Color"]

    def add_vista_layer(path: Path | None, label: str, scale: float, fac: float, blend: str, high: tuple[float, float, float, float], y: float, animate: tuple[float, float] | None = None) -> None:
        nonlocal base_out
        image = load_image(path, "sRGB")
        if image is None:
            return
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-800, y)
        mapping.inputs["Scale"].default_value[0] = scale
        mapping.inputs["Scale"].default_value[1] = scale
        if animate is not None:
            mapping.inputs["Location"].default_value[0] = 0.0
            mapping.inputs["Location"].default_value[1] = 0.0
            mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
            mapping.inputs["Location"].default_value[0] = animate[0]
            mapping.inputs["Location"].default_value[1] = animate[1]
            mapping.inputs["Location"].keyframe_insert("default_value", frame=180)
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-560, y)
        tex.image = image
        tex.extension = "REPEAT"
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (-310, y)
        ramp.label = label
        ramp.color_ramp.elements[0].position = 0.24
        ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = high
        mix = nodes.new("ShaderNodeMixRGB")
        mix.location = (30, y)
        mix.blend_type = blend
        mix.inputs["Fac"].default_value = fac
        links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], ramp.inputs["Fac"])
        links.new(base_out, mix.inputs["Color1"])
        links.new(ramp.outputs["Color"], mix.inputs["Color2"])
        base_out = mix.outputs["Color"]

    add_vista_layer(foam, "native FactoryOcean foam", 2.2, 0.22, "SCREEN", (0.30, 0.39, 0.36, 1), 350, (0.07, -0.06))
    add_vista_layer(cloud, "native cloud tile modulation", 0.85, 0.12, "OVERLAY", (0.12, 0.17, 0.16, 1), 130, (-0.04, 0.02))

    sky_img = load_image(sky, "sRGB")
    if sky_img is not None:
        env = nodes.new("ShaderNodeTexEnvironment")
        env.location = (-560, 590)
        env.image = sky_img
        hue = nodes.new("ShaderNodeHueSaturation")
        hue.location = (-305, 590)
        hue.inputs["Saturation"].default_value = 0.52
        hue.inputs["Value"].default_value = 0.30
        mix = nodes.new("ShaderNodeMixRGB")
        mix.location = (320, 160)
        mix.blend_type = "SCREEN"
        mix.inputs["Fac"].default_value = 0.38
        links.new(coord.outputs["Reflection"], env.inputs["Vector"])
        links.new(env.outputs["Color"], hue.inputs["Color"])
        links.new(base_out, mix.inputs["Color1"])
        links.new(hue.outputs["Color"], mix.inputs["Color2"])
        base_out = mix.outputs["Color"]
    links.new(base_out, bsdf.inputs["Base Color"])

    normal_img = load_image(normal, "Non-Color")
    if normal_img is not None and principled_socket(bsdf, ("Normal",)):
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-800, -210)
        mapping.inputs["Scale"].default_value[0] = 2.8
        mapping.inputs["Scale"].default_value[1] = 2.8
        mapping.inputs["Location"].default_value[0] = 0.0
        mapping.inputs["Location"].default_value[1] = 0.0
        mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
        mapping.inputs["Location"].default_value[0] = 0.13
        mapping.inputs["Location"].default_value[1] = -0.085
        mapping.inputs["Location"].keyframe_insert("default_value", frame=180)
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-555, -210)
        tex.image = normal_img
        tex.extension = "REPEAT"
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (140, -210)
        nmap.inputs["Strength"].default_value = 0.145
        links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    images = {"normal": str(normal or ""), "foam": str(foam or ""), "cloud_tile": str(cloud or ""), "factory_ocean_cube": str(sky or "")}
    material["gridlock_water_vista_split"] = "FactoryOcean vista water uses native MIC_Ocean_Gridlock foam/cloud/normal/cubemap decode"
    material["source_images"] = json.dumps(images, ensure_ascii=True)
    return {"material": material.name, "images": images, "node_count": len(nodes)}


def make_puddle_material() -> dict[str, Any]:
    occ = find_png("water_mp_gridlock_occlusion")
    n_hi = find_png("water_gridlock_normals_hi_freq")
    material = bpy.data.materials.get(PUDDLE_MATERIAL) or bpy.data.materials.new(PUDDLE_MATERIAL)
    material.diffuse_color = (0.040, 0.055, 0.048, 0.50)
    safe_setattr(material, "show_transparent_back", True)
    safe_setattr(material, "use_screen_refraction", True)
    set_enum_value(material, "blend_method", ["BLEND", "HASHED"])
    set_enum_value(material, "surface_render_method", ["BLENDED", "DITHERED"])
    nodes, links = clear_nodes(material)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (650, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (385, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.035, 0.050, 0.044, 1.0))
    set_principled(bsdf, ("Alpha",), 0.50)
    set_principled(bsdf, ("Roughness",), 0.030)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.90)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.48)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.055)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-550, 110)
    occ_img = load_image(occ, "sRGB")
    if occ_img is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-315, 110)
        tex.image = occ_img
        tex.extension = "REPEAT"
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (-80, 110)
        ramp.color_ramp.elements[0].color = (0.018, 0.025, 0.022, 1.0)
        ramp.color_ramp.elements[1].color = (0.100, 0.125, 0.100, 1.0)
        links.new(coord.outputs["Generated"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    n_img = load_image(n_hi, "Non-Color")
    if n_img is not None and principled_socket(bsdf, ("Normal",)):
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.location = (-315, -150)
        tex_n.image = n_img
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (-70, -150)
        nmap.inputs["Strength"].default_value = 0.09
        links.new(coord.outputs["Generated"], tex_n.inputs["Vector"])
        links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return {"material": material.name, "images": {"occlusion": str(occ or ""), "normal": str(n_hi or "")}, "node_count": len(nodes)}


def remove_water_modifiers(obj: bpy.types.Object) -> list[str]:
    removed = []
    for mod in list(obj.modifiers):
        if "Water" in mod.name or "GRIDLOCK_Water" in mod.name:
            removed.append(mod.name)
            obj.modifiers.remove(mod)
    return removed


def set_wave_modifier(obj: bpy.types.Object, height: float, width: float, speed: float) -> None:
    wave = obj.modifiers.get("GRIDLOCK_Water_Subtle_SurfaceMotion")
    if wave is None:
        wave = obj.modifiers.new("GRIDLOCK_Water_Subtle_SurfaceMotion", "WAVE")
    safe_setattr(wave, "height", height)
    safe_setattr(wave, "width", width)
    safe_setattr(wave, "speed", speed)
    safe_setattr(wave, "narrowness", 1.6)
    safe_setattr(wave, "use_x", True)
    safe_setattr(wave, "use_y", True)


def apply_buckets(materials: dict[str, Any]) -> dict[str, Any]:
    root = get_collection(ROOT_COLLECTION)
    water_root = get_collection(WATER_COLLECTION, root)
    waterfront_coll = get_collection("Waterfront_Restored_StaticMesh", water_root)
    close_coll = get_collection("Close_Gridlock_Water", water_root)
    vista_coll = get_collection("Vista_FactoryOcean", water_root)

    applied: dict[str, Any] = {"waterfront": [], "close_water": [], "vista_ocean": [], "puddles": []}
    waterfront_mats = [bpy.data.materials[row["material"]] for row in materials["waterfront"]]
    close_mat = bpy.data.materials[CLOSE_WATER_MATERIAL]
    vista_mat = bpy.data.materials[VISTA_OCEAN_MATERIAL]
    puddle_mat = bpy.data.materials[PUDDLE_MATERIAL]

    for obj in bpy.data.objects:
        text = " ".join(
            [
                obj.name,
                getattr(obj.data, "name", ""),
                str(obj.get("ue_static_mesh_path") or ""),
                " ".join(coll.name for coll in obj.users_collection),
            ]
        ).lower()
        if obj.type != "MESH":
            continue
        if "bsp_gridlock_waterfront_smesh_delta" in text:
            while len(obj.data.materials) < len(waterfront_mats):
                obj.data.materials.append(waterfront_mats[len(obj.data.materials)])
            for index, material in enumerate(waterfront_mats):
                obj.data.materials[index] = material
            removed = remove_water_modifiers(obj)
            obj.hide_render = False
            obj.hide_viewport = False
            obj["gridlock_water_vista_split"] = "restored_as_static_waterfront_mesh_not_liquid"
            link_object(waterfront_coll, obj)
            unlink_from_scene_root(obj)
            applied["waterfront"].append({"object": obj.name, "material_slots": [mat.name for mat in waterfront_mats], "removed_modifiers": removed})
        elif "factoryocean1" in text or "fx_ocean_delta.meshes.factoryocean" in text:
            if obj.data.materials:
                for idx in range(len(obj.data.materials)):
                    obj.data.materials[idx] = vista_mat
            else:
                obj.data.materials.append(vista_mat)
            remove_water_modifiers(obj)
            set_wave_modifier(obj, 0.030, 92.0, 0.035)
            obj.hide_render = False
            obj.hide_viewport = False
            obj["gridlock_water_vista_split"] = "vista_ocean_fx_ocean_delta_material"
            link_object(vista_coll, obj)
            unlink_from_scene_root(obj)
            applied["vista_ocean"].append({"object": obj.name, "dimensions": vec3(obj.dimensions), "material": vista_mat.name})
        elif "gridlockwater" in text or "gridlock_water_" in text:
            if "spray" in text or "marker" in text or "p_wall_spray" in text:
                continue
            if obj.data.materials:
                for idx in range(len(obj.data.materials)):
                    obj.data.materials[idx] = close_mat
            else:
                obj.data.materials.append(close_mat)
            remove_water_modifiers(obj)
            set_wave_modifier(obj, 0.035 if max(obj.dimensions.x, obj.dimensions.y) > 100 else 0.018, 18.0, 0.075)
            obj.hide_render = False
            obj.hide_viewport = False
            obj["gridlock_water_vista_split"] = "close_gridlock_water_material"
            link_object(close_coll, obj)
            unlink_from_scene_root(obj)
            applied["close_water"].append({"object": obj.name, "dimensions": vec3(obj.dimensions), "material": close_mat.name})
        elif "floor_puddle" in text and "collision" not in text:
            if obj.data.materials:
                for idx in range(len(obj.data.materials)):
                    obj.data.materials[idx] = puddle_mat
            else:
                obj.data.materials.append(puddle_mat)
            obj.hide_render = False
            obj.hide_viewport = False
            obj["gridlock_water_vista_split"] = "floor_puddle_subtle_shader"
            applied["puddles"].append({"object": obj.name, "material": puddle_mat.name})

    return applied


def mesh_bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
    if not objects:
        return {"min": [0, 0, 0], "max": [0, 0, 0], "center": [0, 0, 0], "radius": 64.0}
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
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    return {"min": vec3(mins), "max": vec3(maxs), "center": vec3(center), "radius": max(extent.x, extent.y, extent.z) * 0.5}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.frame_start = min(int(scene.frame_start or 1), 1)
    scene.frame_end = max(int(scene.frame_end or 1), 180)
    scene.frame_set(72)
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
        scene.view_settings.exposure = -0.06
        scene.view_settings.gamma = 1.0
    except Exception:
        pass
    return {"engine": scene.render.engine, "frame": scene.frame_current}


def make_camera(name: str, objects: list[bpy.types.Object], offset: Vector, lens: float) -> dict[str, Any]:
    root = get_collection(ROOT_COLLECTION)
    bounds = mesh_bounds(objects)
    target = Vector(bounds["center"])
    camera = bpy.data.objects.get(name)
    if camera is None:
        cam_data = bpy.data.cameras.new(name)
        camera = bpy.data.objects.new(name, cam_data)
        link_object(get_collection("Cameras", root), camera)
    camera.location = target + offset
    direction = target - Vector(camera.location)
    if direction.length > 0:
        camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = lens
    camera.data.clip_start = 0.05
    camera.data.clip_end = 220000.0
    unlink_from_scene_root(camera)
    return {"camera": camera.name, "location": vec3(camera.location), "target": vec3(target), "lens": camera.data.lens, "bounds": bounds}


def render(path: Path, camera_name: str) -> dict[str, Any]:
    ensure_parent(path)
    bpy.context.scene.camera = bpy.data.objects[camera_name]
    bpy.context.scene.render.filepath = str(path)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        return {"path": str(path), "ok": False, "error": str(exc)}
    return {"path": str(path), "ok": path.exists() and path.stat().st_size > 0, "size": path.stat().st_size if path.exists() else 0}


def copy_preview(src: Path, dst: Path) -> dict[str, Any]:
    if not src.exists():
        return {"preview": str(dst), "copied": False}
    ensure_parent(dst)
    shutil.copyfile(src, dst)
    return {"preview": str(dst), "copied": True, "size": dst.stat().st_size}


def scene_root_objects() -> list[str]:
    return [obj.name for obj in bpy.context.scene.collection.objects]


def main() -> int:
    args = parse_args()
    waterfront_specs = [
        (
            "s0_wall_whitebrick",
            PNG_CACHE / "T_Delta_Gridlock_01.wall_material_whitebrick_01a_Delta_Tex__2048x2048_PF_DXT5_21c22f2bd4a7.png",
            PNG_CACHE / "T_Delta_Gridlock_01.wall_material_whitebrick_01b_Delta_Normal__2048x2048_PF_DXN_fc7ddfba9fbb.png",
            PNG_CACHE / "T_Delta_Gridlock_01.wall_material_whitebrick_01b_Delta_Specular__1024x1024_PF_DXT5_57d9f5e1ed51.png",
            0.72,
            0.24,
        ),
        (
            "s1_grass_adams",
            PNG_CACHE / "T_Delta_Gridlock_01.grass_adams_Delta_Tex__1024x1024_PF_DXT1_a76f662df66e.png",
            PNG_CACHE / "T_Delta_Gridlock_01.grass_adams_Delta_Normal__1024x1024_PF_DXN_747487876ceb.png",
            PNG_CACHE / "T_Delta_Gridlock_01.grass_adams_Delta_Specular__512x512_PF_DXT5_77e998bd6894.png",
            0.88,
            0.18,
        ),
        (
            "s2_floor_metal",
            PNG_CACHE / "T_Delta_Gridlock_01.floor_metal_01a_Delta_Tex__2048x2048_PF_DXT1_9fbe5cdf6907.png",
            PNG_CACHE / "T_Delta_Gridlock_01.floor_metal_01a_Delta_Normal__2048x2048_PF_DXN_ee92ed604135.png",
            PNG_CACHE / "T_Delta_Gridlock_01.floor_metal_01a_Delta_Specular__1024x1024_PF_DXT5_56040e2927de.png",
            0.34,
            0.20,
        ),
        (
            "s3_tile_dirty_broken",
            PNG_CACHE / "T_Delta_Gridlock_01.tilefloor_concrete_dirty_01_Delta_Tex__2048x2048_PF_DXT5_d73fe47c37aa.png",
            PNG_CACHE / "T_Delta_Gridlock_01.tilefloor_concrete_broken_01_Delta_Normal__2048x2048_PF_DXN_20d4ab5fdaba.png",
            PNG_CACHE / "T_Delta_Gridlock_01.tilefloor_concrete_broken_01_Delta_Specular__1024x1024_PF_DXT5_3aa1d53d6b4b.png",
            0.68,
            0.18,
        ),
        (
            "s4_concrete_grungy",
            PNG_CACHE / "T_Delta_Gridlock_01.concrete_grungy01_Delta_Tex__2048x2048_PF_DXT1_f13be71067fc.png",
            PNG_CACHE / "T_Delta_Gridlock_01.concrete_grungy01_Delta_Normal__2048x2048_PF_DXN_b12cfb0e0775.png",
            PNG_CACHE / "T_Delta_Gridlock_01.concrete_grungy01_Delta_Specular__1024x1024_PF_DXT5_d80f020adbd1.png",
            0.76,
            0.18,
        ),
    ]
    waterfront_materials = [
        make_static_material(f"{WATERFRONT_MATERIAL_PREFIX}__{name}", diffuse, normal, spec, roughness, normal_strength)
        for name, diffuse, normal, spec, roughness, normal_strength in waterfront_specs
    ]
    close_summary = make_close_water_material()
    vista_summary = make_vista_ocean_material()
    puddle_summary = make_puddle_material()
    applied = apply_buckets({"waterfront": waterfront_materials, "close": close_summary, "vista": vista_summary, "puddle": puddle_summary})
    render_config = configure_render()

    close_objs = [bpy.data.objects[row["object"]] for row in applied["close_water"] if row["object"] in bpy.data.objects]
    vista_objs = [bpy.data.objects[row["object"]] for row in applied["vista_ocean"] if row["object"] in bpy.data.objects]
    close_camera = make_camera("CAM_MP_Gridlock_CloseWater_Refine_Preview", close_objs, Vector((-145.0, -210.0, 74.0)), 28.0)
    vista_camera = make_camera("CAM_MP_Gridlock_VistaWater_Refine_Preview", vista_objs, Vector((-520.0, -720.0, 210.0)), 28.0)

    render_summary: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        close_render = render(Path(args.close_render_out), close_camera["camera"])
        close_render.update(copy_preview(Path(args.close_render_out), Path(args.close_preview_copy)))
        vista_render = render(Path(args.vista_render_out), vista_camera["camera"])
        vista_render.update(copy_preview(Path(args.vista_render_out), Path(args.vista_preview_copy)))
        render_summary.update({"close": close_render, "vista": vista_render})

    bpy.context.scene["gridlock_water_vista_split_status"] = "close water, vista ocean, and waterfront mesh are separated"
    bpy.context.scene["gridlock_water_vista_split_proof"] = str(args.proof_out)

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_water_vista_split_refined",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "reason": "Previous water pass overmatched waterfront architecture and vista FactoryOcean planes. This pass restores waterfront as static mesh, assigns FX_Ocean_Delta vista ocean separately, and keeps GridlockWater material on close water only.",
        "materials": {
            "waterfront": waterfront_materials,
            "close_water": close_summary,
            "vista_ocean": vista_summary,
            "puddle": puddle_summary,
        },
        "applied": applied,
        "cameras": {"close": close_camera, "vista": vista_camera},
        "render_config": render_config,
        "render": render_summary,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "direct_scene_root_objects": scene_root_objects(),
        },
    }
    proof_out = Path(args.proof_out)
    ensure_parent(proof_out)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
