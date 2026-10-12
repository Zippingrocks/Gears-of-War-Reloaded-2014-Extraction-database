#!/usr/bin/env python3
"""Production hardening pass for Reloaded MP_Gridlock visual families 1-6.

This pass is intentionally post-repair: it assumes the native StaticMesh UV
breakthrough and the existing sky, lighting, water, and alpha passes have run.
It tightens the still-special Blender shader families and writes a proof audit
so new exports cannot silently regress into pink/white planes or visible source
diagnostic BSP.
"""

from __future__ import annotations

import argparse
import csv
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


MAP_ROOT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12"
)
SCENE_DIR = MAP_ROOT / "Blender_Scene_2026_08_12"
TEXTURE_CACHE = MAP_ROOT / "Material_Texture_Cache"
TEXTURE_MANIFEST = TEXTURE_CACHE / "gowreloaded_mp_gridlock_material_texture_export_manifest.csv"
PNG_MAP = MAP_ROOT / "Texture_Section_UV_Validation_2026_08_13" / "gridlock_full_material_cache_png_rows_extended_2026_08_15.json"
NO_DIFFUSE_CSV = MAP_ROOT / "Texture_Section_UV_Validation_2026_08_13" / "gridlock_no_diffuse_sections.csv"
ALIAS = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\_gridlock_water_native_alias_20260815")
VIS = Path(r"C:\Users\Bilbo\.codex\visualizations\2026\06\28\019f0bba-7647-7e82-9b57-7c1574085478")

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
DIAGNOSTIC_COLLECTION = "00_DIAGNOSTICS_HIDDEN_Gameplay_Collision_Hitmesh_NotVisual"
CAMERA_COLLECTION = "Cameras_Render_Proof"
LOOSE_COLLECTION = "00_SCENE_ROOT_REHOMED"
VISUAL_SD_COLLECTION = "StaticMesh_SDStitchingProxy_Context_Repaired"
STATIC_RENDER_UV = "UV_Source_Render"
MODEL2_POLICY_PATH = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")

DEFAULT_PROOF = SCENE_DIR / "gridlock_visual_accuracy_1_to_6_pass_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_visual_accuracy_1_to_6_pass_2026_08_15.png"
DEFAULT_PREVIEW = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_visual_accuracy_1_to_6_latest.png")

PUDDLE_MATERIAL = "MAT__Gridlock_Puddles_GameView_Wet_Reflective_Final"
PUDDLE_COLLISION_MATERIAL = "MAT__Gridlock_Puddle_Collision_Hidden_Diagnostic"
GODRAY_MATERIAL = "MAT__FX_Nature_Delta__Godray_Translucent_GameView_Final"
SD_MATERIAL = "MAT__MP_Gridlock_STITCHINGDATA__Context_Blend_GameView_Final"
WINDOW_HIT_MATERIAL = "MAT__Delta_Window_Hitmesh_Hidden_Diagnostic"
ASH_MATERIAL = "MAT__Gridlock_Ash_Debris_Alpha_GameView_Final"

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
    "splat",
)
FOLIAGE_TOKENS = ("grass", "foliage", "ivy", "leaf", "leaves", "vine", "bush")
ASH_TOKENS = ("debris_ashes", "ashes", "ash_")
WATER_TOKENS = ("water", "puddle", "ocean", "factoryocean")
SKY_TOKENS = ("sky", "skydome", "skybox", "backdrop")
DIAGNOSTIC_TOKENS = ("hitmesh", "collision", "physmat", "blockedvolume", "blockingvolume")
NON_VISUAL_COLLECTION_TOKENS = ("diagnostic", "collision", "hitmesh", "source_renderable_bsp_hidden")


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


model2_policy = load_module(MODEL2_POLICY_PATH, "gowr_gridlock_model2_visual_policy")


def read_no_diffuse_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def norm_local_path(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(str(Path(path).resolve(strict=False)))
    except Exception:
        return os.path.normcase(path)


def read_texture_manifest(path: Path = TEXTURE_MANIFEST) -> dict[str, str]:
    rows: dict[str, str] = {}
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = str(row.get("texture_key") or "").split("#", 1)[0].lower()
            dds = str(row.get("dds_path") or "")
            if key and dds and Path(dds).exists():
                rows[key] = dds
    return rows


def read_png_lookup(path: Path = PNG_MAP) -> dict[str, str]:
    lookup: dict[str, str] = {}
    if not path.exists():
        return lookup
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return lookup
    rows = payload if isinstance(payload, list) else payload.get("rows", [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = norm_local_path(str(row.get("source") or row.get("dds") or ""))
        png = str(row.get("png") or "")
        if source and png and Path(png).exists():
            lookup[source] = png
    return lookup


def manifest_texture_path(texture_rows: dict[str, str], png_lookup: dict[str, str], key: str) -> str:
    dds = texture_rows.get(key.lower(), "")
    if not dds:
        return ""
    return png_lookup.get(norm_local_path(dds), dds)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")


def safe_setattr(owner: Any, prop: str, value: Any) -> bool:
    if not hasattr(owner, prop):
        return False
    try:
        setattr(owner, prop, value)
        return True
    except Exception:
        return False


def set_enum(owner: Any, prop: str, preferred: list[str]) -> str:
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
                pass
    return str(getattr(owner, prop, ""))


def get_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    owner = parent or bpy.context.scene.collection
    if collection.name not in owner.children:
        owner.children.link(collection)
    return collection


def root_collection() -> bpy.types.Collection:
    return get_collection(ROOT_COLLECTION)


def link_once(collection: bpy.types.Collection, obj: bpy.types.Object) -> None:
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def unlink_from_collection(collection: bpy.types.Collection, obj: bpy.types.Object) -> None:
    try:
        collection.objects.unlink(obj)
    except Exception:
        pass


def object_text(obj: bpy.types.Object) -> str:
    parts = [
        obj.name,
        str(obj.get("ue_static_mesh_path") or ""),
        str(obj.get("ue_actor_class") or ""),
        str(obj.get("ue_actor_name") or ""),
        str(obj.get("gridlock_source_family") or ""),
    ]
    for slot in obj.material_slots:
        mat = slot.material
        if mat is not None:
            parts.append(mat.name)
            parts.append(str(mat.get("ue_material_path") or ""))
            parts.append(str(mat.get("gridlock_source_material_family") or ""))
    return " ".join(parts).lower()


def material_text(mat: bpy.types.Material | None) -> str:
    if mat is None:
        return ""
    return " ".join(
        [
            mat.name,
            str(mat.get("ue_material_path") or ""),
            str(mat.get("gridlock_source_material_family") or ""),
            str(mat.get("gridlock_source_texture") or ""),
        ]
    ).lower()


def collection_names(obj: bpy.types.Object) -> list[str]:
    return [collection.name for collection in obj.users_collection]


def is_in_hidden_diagnostic_collection(obj: bpy.types.Object) -> bool:
    return any(any(token in collection.name.lower() for token in NON_VISUAL_COLLECTION_TOKENS) for collection in obj.users_collection)


def active_source_render_uv(obj: bpy.types.Object) -> str:
    if obj.type != "MESH":
        return ""
    mesh = obj.data
    for name in (STATIC_RENDER_UV, "UV_Source_BSP_RenderTexCoord", "UV_Source_BSP_Surface", "UV0_Source_InlineCard"):
        uv = mesh.uv_layers.get(name)
        if uv is None:
            continue
        mesh.uv_layers.active = uv
        try:
            uv.active_render = True
        except Exception:
            pass
        return name
    return ""


def load_image(path: Path | str | None, colorspace: str = "sRGB") -> bpy.types.Image | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        img = bpy.data.images.load(str(p), check_existing=True)
    except Exception:
        return None
    try:
        img.colorspace_settings.name = colorspace
    except Exception:
        pass
    try:
        img.alpha_mode = "STRAIGHT"
    except Exception:
        pass
    return img


def clear_nodes(mat: bpy.types.Material) -> tuple[bpy.types.Nodes, bpy.types.NodeLinks]:
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for node in list(nodes):
        nodes.remove(node)
    return nodes, mat.node_tree.links


def principled_socket(bsdf: bpy.types.Node, names: tuple[str, ...]) -> bpy.types.NodeSocket | None:
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_principled(bsdf: bpy.types.Node, names: tuple[str, ...], value: Any) -> None:
    sock = principled_socket(bsdf, names)
    if sock is None:
        return
    try:
        sock.default_value = value
    except Exception:
        pass


def set_material_alpha_mode(mat: bpy.types.Material, *, alpha: float, shadow: str = "NONE", method: str = "BLEND") -> None:
    safe_setattr(mat, "use_backface_culling", False)
    safe_setattr(mat, "show_transparent_back", True)
    set_enum(mat, "blend_method", [method, "HASHED", "BLEND", "DITHERED"])
    set_enum(mat, "surface_render_method", ["BLENDED", "DITHERED"])
    set_enum(mat, "shadow_method", [shadow, "HASHED", "NONE"])
    mat.diffuse_color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], alpha)


def make_principled_material(
    name: str,
    base: tuple[float, float, float, float],
    *,
    alpha: float = 1.0,
    roughness: float = 0.55,
    metallic: float = 0.0,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
    blend: str = "OPAQUE",
) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (base[0], base[1], base[2], alpha)
    safe_setattr(mat, "use_backface_culling", False)
    set_enum(mat, "blend_method", [blend, "OPAQUE", "HASHED", "BLEND", "DITHERED"])
    if blend != "OPAQUE":
        set_material_alpha_mode(mat, alpha=alpha, method=blend)
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (560, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (280, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), base)
    set_principled(bsdf, ("Alpha",), alpha)
    set_principled(bsdf, ("Roughness",), roughness)
    set_principled(bsdf, ("Metallic",), metallic)
    if emission is not None:
        set_principled(bsdf, ("Emission Color", "Emission"), emission)
        set_principled(bsdf, ("Emission Strength",), emission_strength)
    return mat


def add_noise_to_principled(
    mat: bpy.types.Material,
    bsdf: bpy.types.Node,
    *,
    scale: float,
    detail: float,
    roughness: float,
    color_a: tuple[float, float, float, float],
    color_b: tuple[float, float, float, float],
    strength: float = 0.12,
) -> None:
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-880, 80)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-650, 80)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-420, 80)
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    noise.inputs["Roughness"].default_value = roughness
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-170, 80)
    ramp.color_ramp.elements[0].position = 0.22
    ramp.color_ramp.elements[0].color = color_a
    ramp.color_ramp.elements[1].position = 0.92
    ramp.color_ramp.elements[1].color = color_b
    bump = nodes.new("ShaderNodeBump")
    bump.location = (20, -210)
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = 0.065
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], principled_socket(bsdf, ("Base Color",)))
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    normal_socket = principled_socket(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(bump.outputs["Normal"], normal_socket)


def make_puddle_material() -> bpy.types.Material:
    mat = bpy.data.materials.get(PUDDLE_MATERIAL) or bpy.data.materials.new(PUDDLE_MATERIAL)
    mat.diffuse_color = (0.045, 0.055, 0.052, 0.58)
    safe_setattr(mat, "use_screen_refraction", True)
    safe_setattr(mat, "use_backface_culling", False)
    set_enum(mat, "blend_method", ["BLEND", "HASHED", "DITHERED"])
    set_enum(mat, "surface_render_method", ["BLENDED", "DITHERED"])
    set_enum(mat, "shadow_method", ["NONE", "HASHED"])
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (880, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (585, 0)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-920, 120)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-700, 120)
    mapping.inputs["Scale"].default_value[0] = 1.8
    mapping.inputs["Scale"].default_value[1] = 1.8
    mapping.inputs["Location"].default_value[0] = 0.0
    mapping.inputs["Location"].default_value[1] = 0.0
    mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
    mapping.inputs["Location"].default_value[0] = 0.10
    mapping.inputs["Location"].default_value[1] = -0.04
    mapping.inputs["Location"].keyframe_insert("default_value", frame=180)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-465, 120)
    noise.inputs["Scale"].default_value = 32.0
    noise.inputs["Detail"].default_value = 12.0
    noise.inputs["Roughness"].default_value = 0.58
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-230, 120)
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = (0.015, 0.020, 0.022, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.105, 0.130, 0.120, 1.0)
    bump = nodes.new("ShaderNodeBump")
    bump.location = (255, -225)
    bump.inputs["Strength"].default_value = 0.052
    bump.inputs["Distance"].default_value = 0.035
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], principled_socket(bsdf, ("Base Color",)))
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled_socket(bsdf, ("Normal",)))
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Alpha",), 0.58)
    set_principled(bsdf, ("Roughness",), 0.045)
    set_principled(bsdf, ("Metallic",), 0.0)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.95)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.48)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.035)
    set_principled(bsdf, ("Transmission Weight", "Transmission"), 0.035)
    mat["gridlock_special_shader_family"] = "puddle_wet_reflective"
    mat["gridlock_native_gap_policy"] = "No diffuse texture in source validation; use wet reflective procedural shader, keep actual plane geometry/placement."
    return mat


def make_godray_material() -> bpy.types.Material:
    mat = bpy.data.materials.get(GODRAY_MATERIAL) or bpy.data.materials.new(GODRAY_MATERIAL)
    mat.diffuse_color = (0.62, 0.68, 0.60, 0.18)
    set_material_alpha_mode(mat, alpha=0.18, shadow="NONE", method="BLEND")
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (650, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (410, 70)
    emission.inputs["Color"].default_value = (0.62, 0.68, 0.60, 1.0)
    emission.inputs["Strength"].default_value = 0.18
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (410, -130)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (175, 0)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-520, 0)
    noise.inputs["Scale"].default_value = 5.0
    noise.inputs["Detail"].default_value = 8.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-275, 0)
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.22, 0.22, 0.22, 1.0)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(noise.outputs["Fac"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    mat["gridlock_special_shader_family"] = "godray_translucent_emissive"
    mat["gridlock_native_gap_policy"] = "Native material references no bound diffuse; keep mesh as translucent atmospheric light shaft."
    return mat


def make_sd_material() -> bpy.types.Material:
    mat = bpy.data.materials.get(SD_MATERIAL) or bpy.data.materials.new(SD_MATERIAL)
    mat.diffuse_color = (0.215, 0.218, 0.204, 1.0)
    set_enum(mat, "blend_method", ["OPAQUE"])
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (740, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (460, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.215, 0.218, 0.204, 1.0))
    set_principled(bsdf, ("Roughness",), 0.78)
    add_noise_to_principled(
        mat,
        bsdf,
        scale=42.0,
        detail=14.0,
        roughness=0.62,
        color_a=(0.105, 0.108, 0.102, 1.0),
        color_b=(0.365, 0.355, 0.325, 1.0),
        strength=0.10,
    )
    mat["gridlock_special_shader_family"] = "sd_stitching_proxy_context_blend"
    mat["gridlock_native_gap_policy"] = "Source validation has proxy geometry with no material binding; render as neutral context stitch instead of white/pink debug surfaces."
    return mat


def make_ash_material() -> bpy.types.Material:
    mat = bpy.data.materials.get(ASH_MATERIAL) or bpy.data.materials.new(ASH_MATERIAL)
    mat.diffuse_color = (0.055, 0.052, 0.047, 0.42)
    set_material_alpha_mode(mat, alpha=0.42, shadow="HASHED", method="HASHED")
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (820, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (560, 0)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-880, 70)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-650, 70)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-420, 70)
    noise.inputs["Scale"].default_value = 56.0
    noise.inputs["Detail"].default_value = 13.0
    noise.inputs["Roughness"].default_value = 0.62
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-170, 70)
    ramp.color_ramp.elements[0].position = 0.38
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 0.0)
    ramp.color_ramp.elements[1].position = 0.83
    ramp.color_ramp.elements[1].color = (0.12, 0.11, 0.095, 0.72)
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], principled_socket(bsdf, ("Base Color",)))
    links.new(ramp.outputs["Alpha"], principled_socket(bsdf, ("Alpha",)))
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Roughness",), 0.92)
    mat["gridlock_special_shader_family"] = "ash_debris_alpha_card"
    return mat


def make_textured_alpha_material(
    name: str,
    diffuse_path: str,
    normal_path: str = "",
    specular_path: str = "",
    *,
    alpha: float = 0.72,
    roughness: float = 0.82,
) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (0.55, 0.55, 0.50, alpha)
    set_material_alpha_mode(mat, alpha=alpha, shadow="HASHED", method="HASHED")
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (820, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (540, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.55, 0.55, 0.50, alpha))
    set_principled(bsdf, ("Alpha",), alpha)
    set_principled(bsdf, ("Roughness",), roughness)
    uv = nodes.new("ShaderNodeUVMap")
    uv.location = (-760, 80)
    uv.uv_map = STATIC_RENDER_UV
    diffuse = load_image(diffuse_path, "sRGB")
    if diffuse is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-510, 120)
        tex.image = diffuse
        tex.extension = "CLIP"
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], principled_socket(bsdf, ("Base Color",)))
        links.new(tex.outputs["Alpha"], principled_socket(bsdf, ("Alpha",)))
        mat["gridlock_native_diffuse_texture"] = diffuse_path
    normal = load_image(normal_path, "Non-Color") if normal_path else None
    if normal is not None:
        ntex = nodes.new("ShaderNodeTexImage")
        ntex.location = (-510, -160)
        ntex.image = normal
        ntex.extension = "CLIP"
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (230, -190)
        nmap.inputs["Strength"].default_value = 0.42
        links.new(uv.outputs["UV"], ntex.inputs["Vector"])
        links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], principled_socket(bsdf, ("Normal",)))
        mat["gridlock_native_normal_texture"] = normal_path
    if specular_path:
        mat["gridlock_native_specular_texture"] = specular_path
    mat["gridlock_special_shader_family"] = "texture_backed_alpha_card"
    return mat


def orphan_card_family_keys(text: str) -> tuple[str, str, str, str, float]:
    if "asphalt_decal_damage_01a" in text:
        return ("Gridlock_Asphalt_Damage_01a", "delta_gridlock_01.asphalt_decal_damage_01a_delta_tex", "delta_gridlock_01.asphalt_decal_damage_01a_delta_normal", "delta_gridlock_01.asphalt_decal_damage_01a_delta_specular", 0.62)
    if "asphalt_decal_damage_02a" in text:
        return ("Gridlock_Asphalt_Damage_02a", "delta_gridlock_01.asphalt_decal_damage_02a_delta_tex", "delta_gridlock_01.asphalt_decal_damage_02a_delta_normal", "delta_gridlock_01.asphalt_decal_damage_02a_delta_specular", 0.62)
    if "bulletin_board" in text:
        return ("Gridlock_Bulletin_Board_01a", "delta_gridlock_01.decals.bulletin_board_01a_delta_tex", "delta_gridlock_01.decals.bulletin_board_01a_delta_normal", "delta_gridlock_01.decals.bulletin_board_01a_delta_specular", 0.88)
    if "poster" in text:
        return ("Gridlock_Posters_01a", "delta_gridlock_01.decals.posters_01a_delta_tex", "delta_gridlock_01.decals.posters_01a_delta_normal", "delta_gridlock_01.decals.posters_01a_delta_specular", 0.88)
    if "debris_ashes" in text or "ash_" in text:
        return ("Gridlock_Debris_Ashes_01a", "delta_gridlock_01.debris_ashes_01a_delta_tex", "delta_gridlock_01.debris_ashes_01a_delta_normal", "delta_gridlock_01.debris_ashes_01a_delta_specular", 0.46)
    if "grass_adams" in text:
        return ("Gridlock_Grass_Adams", "delta_gridlock_01.grass_adams_delta_tex", "delta_gridlock_01.grass_adams_delta_normal", "delta_gridlock_01.grass_adams_delta_specular", 0.70)
    if "foliage_grass_clumped_01a" in text:
        return ("Gridlock_Foliage_Grass_Clumped_01a", "neutral_trees.foliage_grass_clumped_01a_delta_tex", "neutral_trees.foliage_grass_clumped_01a_delta_normal", "neutral_trees.foliage_grass_clumped_01a_delta_specular", 0.70)
    if "foliage_grass_clumped_01b" in text:
        return ("Gridlock_Foliage_Grass_Clumped_01b", "neutral_trees.foliage_grass_clumped_01b_delta_tex", "", "", 0.70)
    if "foliage_ivy_01a" in text or "ivy_01a" in text:
        return ("Gridlock_Foliage_Ivy_01a", "neutral_trees.foliage_ivy_01a_delta_tex", "neutral_trees.foliage_ivy_01a_delta_normal", "neutral_trees.foliage_ivy_01a_delta_specular", 0.70)
    if "foliage_ivy_01b" in text or "ivy_01b" in text:
        return ("Gridlock_Foliage_Ivy_01b", "cog_foliage.foliage_ivy_01b_delta_tex", "cog_foliage.foliage_ivy_01b_delta_normal", "", 0.70)
    return ("Gridlock_Generic_Alpha_Card", "", "", "", 0.58)


def materialize_orphan_alpha_cards(texture_rows: dict[str, str], png_lookup: dict[str, str]) -> dict[str, Any]:
    repaired: list[dict[str, Any]] = []
    fallback: list[str] = []
    generic = make_principled_material(
        "MAT__Gridlock_Generic_Alpha_Card_Fallback_Final",
        (0.20, 0.19, 0.17, 0.52),
        alpha=0.52,
        roughness=0.86,
        blend="HASHED",
    )
    set_material_alpha_mode(generic, alpha=0.52, shadow="HASHED", method="HASHED")
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render or is_in_hidden_diagnostic_collection(obj):
            continue
        if obj.material_slots and any(slot.material is not None for slot in obj.material_slots):
            continue
        text = object_text(obj)
        if not any(token in text for token in DECAL_TOKENS + FOLIAGE_TOKENS + ASH_TOKENS):
            continue
        family, diffuse_key, normal_key, specular_key, alpha = orphan_card_family_keys(text)
        diffuse = manifest_texture_path(texture_rows, png_lookup, diffuse_key)
        normal = manifest_texture_path(texture_rows, png_lookup, normal_key) if normal_key else ""
        specular = manifest_texture_path(texture_rows, png_lookup, specular_key) if specular_key else ""
        if diffuse:
            mat = make_textured_alpha_material(
                f"MAT__{family}__NativeAlphaCard_Final",
                diffuse,
                normal,
                specular,
                alpha=alpha,
                roughness=0.84,
            )
        else:
            mat = generic
            fallback.append(obj.name)
        assign_material(obj, mat)
        active_source_render_uv(obj)
        obj.show_transparent = True
        obj["gridlock_orphan_alpha_card_repaired_2026_08_15"] = family
        repaired.append({"object": obj.name, "family": family, "material": mat.name, "diffuse": diffuse})
    return {"orphan_alpha_cards_repaired": len(repaired), "texture_backed": len(repaired) - len(fallback), "fallback": len(fallback), "fallback_sample": fallback[:40], "sample": repaired[:60]}


def repair_named_overlay_static_materials(texture_rows: dict[str, str], png_lookup: dict[str, str]) -> dict[str, Any]:
    repaired: list[dict[str, Any]] = []
    vent_diffuse = manifest_texture_path(texture_rows, png_lookup, "cog_city_architecture.vent_01_delta_tex")
    vent_normal = manifest_texture_path(texture_rows, png_lookup, "cog_city_architecture.vent_01_delta_normal")
    vent_spec = manifest_texture_path(texture_rows, png_lookup, "cog_city_architecture.vent_01_delta_specular")
    signage_diffuse = manifest_texture_path(texture_rows, png_lookup, "signage_paint.signage_paint_tex")
    vent_mat = None
    signage_mat = None
    if vent_diffuse:
        vent_mat = make_textured_alpha_material(
            "MAT__COG_City_Architecture__Vent_01_Delta_Native_Final",
            vent_diffuse,
            vent_normal,
            vent_spec,
            alpha=1.0,
            roughness=0.72,
        )
        set_enum(vent_mat, "blend_method", ["OPAQUE"])
        vent_mat["gridlock_named_overlay_repair"] = "Vent_01/Vent_02 share the decoded COG_City_Architecture.Vent_01 Delta texture family."
    if signage_diffuse:
        signage_mat = make_textured_alpha_material(
            "MAT__Signage_Paint__Signage_Paint_Tex_Native_Final",
            signage_diffuse,
            "",
            "",
            alpha=0.82,
            roughness=0.88,
        )
        signage_mat["gridlock_named_overlay_repair"] = "Signage_Paint visible paint overlays use the decoded Signage_Paint.Signage_Paint_Tex texture."
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render or is_in_hidden_diagnostic_collection(obj):
            continue
        text = object_text(obj)
        if ("vent_01" in text or "vent_02" in text) and vent_mat is not None:
            if not obj.material_slots or not any(slot.material is not None for slot in obj.material_slots):
                assign_material(obj, vent_mat)
                active_source_render_uv(obj)
                obj["gridlock_named_overlay_repaired_2026_08_15"] = "vent_native_texture"
                repaired.append({"object": obj.name, "material": vent_mat.name, "family": "vent_native_texture"})
        elif "signage_paint" in text and signage_mat is not None:
            if not any(material_has_image(slot.material) for slot in obj.material_slots if slot.material):
                assign_material(obj, signage_mat)
                active_source_render_uv(obj)
                obj.show_transparent = True
                obj["gridlock_named_overlay_repaired_2026_08_15"] = "signage_paint_native_texture"
                repaired.append({"object": obj.name, "material": signage_mat.name, "family": "signage_paint_native_texture"})
    return {"named_overlay_static_materials_repaired": len(repaired), "vent_texture_found": bool(vent_diffuse), "signage_texture_found": bool(signage_diffuse), "sample": repaired[:40]}


def unhide_visual_object(obj: bpy.types.Object, collection_name: str) -> None:
    visual = get_collection(collection_name, root_collection())
    link_once(visual, obj)
    for collection in list(obj.users_collection):
        if collection.name == DIAGNOSTIC_COLLECTION:
            unlink_from_collection(collection, obj)
    obj.hide_viewport = False
    obj.hide_render = False
    obj.hide_select = False
    obj.display_type = "TEXTURED"


def assign_material(obj: bpy.types.Object, mat: bpy.types.Material, *, replace: bool = True) -> None:
    if obj.type != "MESH":
        return
    if replace:
        obj.data.materials.clear()
    if mat.name not in [slot.material.name for slot in obj.material_slots if slot.material]:
        obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0


def objects_matching(tokens: tuple[str, ...]) -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if obj.type == "MESH" and any(token in object_text(obj) for token in tokens)]


def hide_non_visual_object(obj: bpy.types.Object, reason: str, mat: bpy.types.Material | None = None) -> dict[str, Any]:
    before = collection_names(obj)
    diag = get_collection(DIAGNOSTIC_COLLECTION, root_collection())
    link_once(diag, obj)
    for collection in list(obj.users_collection):
        if collection.name != diag.name:
            unlink_from_collection(collection, obj)
    if mat is not None:
        assign_material(obj, mat)
    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_select = True
    obj.display_type = "WIRE"
    obj["gridlock_visual_layer_policy"] = "hidden_non_visual_gameplay_or_collision_proxy"
    obj["gridlock_visual_layer_reason"] = reason
    diag.hide_viewport = True
    diag.hide_render = True
    return {"object": obj.name, "before_collections": before, "after_collections": collection_names(obj), "reason": reason}


def apply_remaining_shader_families(no_diffuse_rows: list[dict[str, str]]) -> dict[str, Any]:
    puddle_mat = make_puddle_material()
    puddle_collision_mat = make_principled_material(
        PUDDLE_COLLISION_MATERIAL,
        (0.05, 0.12, 0.16, 0.20),
        alpha=0.20,
        roughness=0.35,
        blend="BLEND",
    )
    godray_mat = make_godray_material()
    sd_mat = make_sd_material()
    window_mat = make_principled_material(
        WINDOW_HIT_MATERIAL,
        (0.70, 0.84, 0.94, 0.18),
        alpha=0.18,
        roughness=0.20,
        blend="BLEND",
    )
    ash_mat = make_ash_material()

    counts: dict[str, Any] = {
        "puddles_materialized": [],
        "puddle_collisions_hidden": [],
        "window_hitmeshes_hidden": [],
        "godrays_materialized": [],
        "sd_stitching_proxies_materialized": [],
        "ashes_materialized": [],
    }

    wanted_sd_names = {
        str(row.get("asset_object_name") or "").lower()
        for row in no_diffuse_rows
        if "sdstitchingproxy" in str(row.get("asset_object_name") or "").lower()
    }
    wanted_sd_names.update(
        {
            "sdstitchingproxy_2661_staticmesh",
            "sdstitchingproxy_2550_staticmesh",
            "sdstitchingproxy_2377_staticmesh",
            "sdstitchingproxy_2378_staticmesh",
            "sdstitchingproxy_2381_staticmesh",
            "sdstitchingproxy_2409_staticmesh",
            "sdstitchingproxy_2755_staticmesh",
        }
    )

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        text = object_text(obj)
        active_source_render_uv(obj)

        if "sdstitchingproxy" in text:
            unhide_visual_object(obj, VISUAL_SD_COLLECTION)
            assign_material(obj, sd_mat)
            obj["gridlock_special_shader_family"] = "sd_stitching_proxy_context_blend"
            counts["sd_stitching_proxies_materialized"].append(obj.name)
            continue
        if "puddlecollision" in text or ("puddle" in text and "collision" in text):
            counts["puddle_collisions_hidden"].append(
                hide_non_visual_object(obj, "Puddle collision/physics proxy, not a visible water surface.", puddle_collision_mat)
            )
            continue
        if "hitmesh" in text and "sdstitchingproxy" not in text:
            counts["window_hitmeshes_hidden"].append(
                hide_non_visual_object(obj, "Window/hitmesh gameplay proxy, not visible glass/building artwork.", window_mat)
            )
            continue
        if "puddle" in text and not is_in_hidden_diagnostic_collection(obj):
            assign_material(obj, puddle_mat)
            obj.show_transparent = True
            obj["gridlock_special_shader_family"] = "puddle_wet_reflective"
            counts["puddles_materialized"].append(obj.name)
            continue
        if "godray" in text and not is_in_hidden_diagnostic_collection(obj):
            assign_material(obj, godray_mat)
            obj.show_transparent = True
            obj["gridlock_special_shader_family"] = "godray_translucent_emissive"
            counts["godrays_materialized"].append(obj.name)
            continue
        if "sdstitchingproxy" in text and not is_in_hidden_diagnostic_collection(obj):
            base = obj.name.split(".")[0].lower()
            if base in wanted_sd_names or "sdstitchingproxy" in base:
                assign_material(obj, sd_mat)
                obj["gridlock_special_shader_family"] = "sd_stitching_proxy_context_blend"
                counts["sd_stitching_proxies_materialized"].append(obj.name)
            continue
        if any(token in text for token in ASH_TOKENS) and not is_in_hidden_diagnostic_collection(obj):
            assign_material(obj, ash_mat)
            obj.show_transparent = True
            obj["gridlock_special_shader_family"] = "ash_debris_alpha_card"
            counts["ashes_materialized"].append(obj.name)

    return counts


def material_has_image(mat: bpy.types.Material | None) -> bool:
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return False
    return any(node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None) is not None for node in mat.node_tree.nodes)


def reinforce_alpha_materials() -> dict[str, Any]:
    changed: list[str] = []
    png_nodes_fixed = 0
    for mat in bpy.data.materials:
        text = material_text(mat)
        if any(token in text for token in SKY_TOKENS + WATER_TOKENS):
            continue
        if any(token in text for token in DECAL_TOKENS + FOLIAGE_TOKENS + ASH_TOKENS):
            set_material_alpha_mode(mat, alpha=min(float(mat.diffuse_color[3]), 0.72), shadow="HASHED", method="HASHED")
            if mat.use_nodes and mat.node_tree is not None:
                bsdf = next((node for node in mat.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled"), None)
                if bsdf is not None:
                    set_principled(bsdf, ("Alpha",), min(float(mat.diffuse_color[3]), 0.72))
                    set_principled(bsdf, ("Roughness",), max(float(principled_socket(bsdf, ("Roughness",)).default_value), 0.68) if principled_socket(bsdf, ("Roughness",)) else 0.68)
                for node in mat.node_tree.nodes:
                    if node.bl_idname != "ShaderNodeTexImage":
                        continue
                    img = getattr(node, "image", None)
                    if img is None:
                        continue
                    path = str(getattr(img, "filepath", "") or "").lower()
                    if path.endswith(".dds"):
                        png = path[:-4] + ".png"
                        loaded = load_image(png, "Non-Color" if any(t in png for t in ("normal", "mask", "alpha", "opacity")) else "sRGB")
                        if loaded is not None:
                            node.image = loaded
                            png_nodes_fixed += 1
            mat["gridlock_alpha_reinforced_2026_08_15"] = True
            changed.append(mat.name)
    return {"materials_reinforced": len(changed), "sample": changed[:40], "dds_nodes_swapped_to_png": png_nodes_fixed}


def ensure_water_and_vista_state() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        text = object_text(obj)
        if "factoryocean" not in text and "ocean" not in text and "water" not in text:
            continue
        if "puddlecollision" in text or "collision" in text:
            continue
        obj.hide_viewport = False
        obj.hide_render = False
        obj.show_transparent = True
        active_source_render_uv(obj)
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            lower = material_text(mat)
            if "ocean" in lower or "water" in lower or "puddle" in lower:
                safe_setattr(mat, "use_screen_refraction", True)
                set_enum(mat, "blend_method", ["BLEND", "HASHED", "DITHERED"])
                set_enum(mat, "surface_render_method", ["BLENDED", "DITHERED"])
                mat["gridlock_water_vista_hardened_2026_08_15"] = True
        rows.append(
            {
                "object": obj.name,
                "materials": [slot.material.name for slot in obj.material_slots if slot.material],
                "location": [round(float(v), 4) for v in obj.location],
            }
        )
    return {"water_or_vista_objects_visible": len(rows), "sample": rows[:40]}


def configure_lighting_post() -> dict[str, Any]:
    scene = bpy.context.scene
    set_enum(scene.render, "engine", ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"])
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        safe_setattr(eevee, "use_gtao", True)
        safe_setattr(eevee, "gtao_distance", 4.0)
        safe_setattr(eevee, "gtao_factor", 1.15)
        safe_setattr(eevee, "use_bloom", True)
        safe_setattr(eevee, "bloom_intensity", 0.035)
        safe_setattr(eevee, "bloom_radius", 4.0)
        safe_setattr(eevee, "shadow_cube_size", "2048")
        safe_setattr(eevee, "shadow_cascade_size", "2048")
        safe_setattr(eevee, "taa_render_samples", 96)
        safe_setattr(eevee, "taa_samples", 64)
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.color = (0.030, 0.037, 0.044)
    safe_setattr(scene.view_settings, "view_transform", "Filmic")
    safe_setattr(scene.view_settings, "look", "Medium High Contrast")
    scene.view_settings.exposure = 0.24
    scene.view_settings.gamma = 1.0
    scene.frame_start = 1
    scene.frame_end = max(scene.frame_end, 180)
    scene.frame_set(min(max(scene.frame_current, 72), scene.frame_end))
    return {
        "render_engine": scene.render.engine,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": round(float(scene.view_settings.exposure), 4),
        "gamma": round(float(scene.view_settings.gamma), 4),
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "light_count": sum(1 for obj in bpy.data.objects if obj.type == "LIGHT"),
    }


def configure_sky_vista() -> dict[str, Any]:
    rows = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        text = object_text(obj)
        if not any(token in text for token in SKY_TOKENS):
            continue
        if "preserved" in text or "native decoded skydome preserved" in str(obj.get("gridlock_skybox_repair") or "").lower():
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            set_enum(mat, "blend_method", ["OPAQUE"])
            mat.diffuse_color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], 1.0)
            mat["gridlock_sky_vista_hardened_2026_08_15"] = True
        obj.hide_viewport = False
        obj.hide_render = False
        obj.display_type = "TEXTURED"
        rows.append({"object": obj.name, "materials": [slot.material.name for slot in obj.material_slots if slot.material]})
    return {"visible_sky_or_backdrop_objects": len(rows), "sample": rows[:20]}


def clean_scene_root_objects() -> dict[str, Any]:
    root = bpy.context.scene.collection
    root_parent = root_collection()
    camera_collection = get_collection(CAMERA_COLLECTION, root_parent)
    loose_collection = get_collection(LOOSE_COLLECTION, root_parent)
    moved: list[dict[str, Any]] = []
    for obj in list(root.objects):
        target = camera_collection if obj.type == "CAMERA" else loose_collection
        link_once(target, obj)
        unlink_from_collection(root, obj)
        obj["gridlock_scene_root_rehomed_2026_08_15"] = target.name
        moved.append({"object": obj.name, "type": obj.type, "target_collection": target.name})
    return {"direct_scene_root_objects_before_moved": len(moved), "moved": moved[:80], "direct_scene_root_objects_after": len(root.objects)}


def object_visible(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render and not is_in_hidden_diagnostic_collection(obj)


def audit_staticmesh_delta() -> dict[str, Any]:
    visible = [obj for obj in bpy.data.objects if object_visible(obj)]
    uv_source_render = []
    no_material = []
    no_image_material = []
    negative_scale = []
    direct_model_visible = []
    special_family_visible = []
    for obj in visible:
        uv = active_source_render_uv(obj)
        if uv:
            uv_source_render.append({"object": obj.name, "uv": uv})
        if not obj.material_slots or all(slot.material is None for slot in obj.material_slots):
            no_material.append(obj.name)
        elif not any(material_has_image(slot.material) for slot in obj.material_slots if slot.material):
            text = object_text(obj)
            if not any(token in text for token in WATER_TOKENS + SKY_TOKENS + ("godray", "sdstitchingproxy", "fog", "atmosphere") + ASH_TOKENS):
                no_image_material.append(obj.name)
        if float(obj.scale.x) < 0 or float(obj.scale.y) < 0 or float(obj.scale.z) < 0:
            negative_scale.append(
                {"object": obj.name, "scale": [round(float(obj.scale.x), 6), round(float(obj.scale.y), 6), round(float(obj.scale.z), 6)]}
            )
        if obj.name.lower().startswith("model_") and "__mp_gridlock.war__" in obj.name.lower():
            direct_model_visible.append(obj.name)
        if obj.get("gridlock_special_shader_family"):
            special_family_visible.append({"object": obj.name, "family": obj.get("gridlock_special_shader_family")})
    return {
        "visible_meshes": len(visible),
        "uv_source_render_or_equivalent_active": len(uv_source_render),
        "uv_source_render_sample": uv_source_render[:40],
        "visible_no_material_count": len(no_material),
        "visible_no_material_sample": no_material[:40],
        "visible_no_image_material_count": len(no_image_material),
        "visible_no_image_material_sample": no_image_material[:40],
        "negative_scale_count": len(negative_scale),
        "negative_scale_sample": negative_scale[:40],
        "visible_direct_model_objects_count": len(direct_model_visible),
        "visible_direct_model_objects": direct_model_visible,
        "visible_special_family_count": len(special_family_visible),
        "visible_special_family_sample": special_family_visible[:60],
    }


def visible_mesh_for_bounds(obj: bpy.types.Object) -> bool:
    if not object_visible(obj):
        return False
    text = object_text(obj)
    return not any(token in text for token in SKY_TOKENS + ("fog_mp_gridlock",))


def scene_bounds() -> dict[str, Any]:
    meshes = [obj for obj in bpy.data.objects if visible_mesh_for_bounds(obj)]
    if not meshes:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0], "radius": 100.0}
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in meshes:
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
        "min": [round(float(v), 6) for v in mins],
        "max": [round(float(v), 6) for v in maxs],
        "center": [round(float(v), 6) for v in center],
        "extent": [round(float(v), 6) for v in extent],
        "radius": round(radius, 6),
    }


def ensure_camera(bounds: dict[str, Any]) -> bpy.types.Object:
    center = Vector(bounds["center"])
    radius = max(float(bounds["radius"]), 1.0)
    camera = bpy.data.objects.get("CAM_Gridlock_Visual_Accuracy_1_to_6")
    if camera is None:
        camera_data = bpy.data.cameras.new("CAM_Gridlock_Visual_Accuracy_1_to_6")
        camera = bpy.data.objects.new("CAM_Gridlock_Visual_Accuracy_1_to_6", camera_data)
        bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((-radius * 0.62, -radius * 0.84, radius * 0.46))
    target = center + Vector((0.0, 0.0, radius * 0.035))
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 24
    camera.data.clip_end = max(10000.0, radius * 6.0)
    camera.data.clip_start = 0.1
    bpy.context.scene.camera = camera
    return camera


def render_preview(render_out: Path, preview_copy: Path) -> dict[str, Any]:
    bounds = scene_bounds()
    camera = ensure_camera(bounds)
    scene = bpy.context.scene
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.film_transparent = False
    scene.render.filepath = str(render_out)
    render_out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    preview_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(render_out, preview_copy)
    return {
        "render_out": str(render_out),
        "preview_copy": str(preview_copy),
        "camera": camera.name,
        "camera_location": [round(float(v), 6) for v in camera.location],
        "bounds": bounds,
        "render_exists": render_out.exists(),
        "preview_exists": preview_copy.exists(),
    }


def main() -> None:
    args = parse_args()
    no_diffuse_rows = read_no_diffuse_rows(NO_DIFFUSE_CSV)
    texture_rows = read_texture_manifest(TEXTURE_MANIFEST)
    png_lookup = read_png_lookup(PNG_MAP)

    shader_counts = apply_remaining_shader_families(no_diffuse_rows)
    alpha_counts = reinforce_alpha_materials()
    orphan_alpha_counts = materialize_orphan_alpha_cards(texture_rows, png_lookup)
    named_overlay_counts = repair_named_overlay_static_materials(texture_rows, png_lookup)
    water_counts = ensure_water_and_vista_state()
    lighting_counts = configure_lighting_post()
    sky_counts = configure_sky_vista()
    model2_result = model2_policy.apply_model2_visual_policy(
        bpy,
        reason="Gridlock 1-6 production visual pass keeps source-renderable Model_2 hidden in diagnostic layer.",
    )
    root_cleanup = clean_scene_root_objects()
    audit = audit_staticmesh_delta()
    render = render_preview(Path(args.render_out), Path(args.preview_copy)) if args.render_proof else {}

    proof = {
        "status": "gridlock_visual_accuracy_1_to_6_pass_complete",
        "blend_path": bpy.data.filepath,
        "no_diffuse_csv": str(NO_DIFFUSE_CSV),
        "no_diffuse_rows": len(no_diffuse_rows),
        "steps": {
            "1_remaining_shader_families": shader_counts,
            "2_water_vista_water": water_counts,
            "3_lighting_post_process": lighting_counts,
            "4_skybox_vista_integration": sky_counts,
            "5_decals_grime_grass_ashes": {
                "alpha_reinforcement": alpha_counts,
                "orphan_alpha_cards": orphan_alpha_counts,
                "named_overlay_static_materials": named_overlay_counts,
            },
            "6_staticmesh_delta_audit": audit,
        },
        "model2_policy": model2_result,
        "render": render,
    }
    write_json(Path(args.proof_out), proof)
    bpy.context.scene["gridlock_visual_accuracy_1_to_6_proof"] = str(Path(args.proof_out))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
