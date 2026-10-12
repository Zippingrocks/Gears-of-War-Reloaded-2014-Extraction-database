#!/usr/bin/env python3
"""Force the decoded MP_Gridlock skybox to be visible in Blender.

The decoded skydome is source-present, but its native dimensions can put the
surface far beyond ordinary Blender viewport clipping. This pass preserves the
original transform as object metadata, then fits the same decoded skydome mesh
around the reconstructed map at a practical game-view radius.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Matrix, Vector  # type: ignore


MAP_ROOT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12"
)
DEFAULT_TEXTURE_CACHE = MAP_ROOT / "Material_Texture_Cache"
DEFAULT_SCENE_DIR = MAP_ROOT / "Blender_Scene_2026_08_12"
DEFAULT_PROOF = DEFAULT_SCENE_DIR / "gridlock_visible_skybox_fix_2026_08_14.json"
DEFAULT_RENDER = DEFAULT_SCENE_DIR / "gridlock_visible_skybox_fix_2026_08_14.png"

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
SKYBOX_MATERIAL = "MAT__SkyDomes__skydome_gridlock_bg_01__VisibleSkybox_UV0"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-cache", default=str(DEFAULT_TEXTURE_CACHE))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--render-proof", action="store_true")
    return parser.parse_args(argv)


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def vec3(values: Vector | list[float] | tuple[float, float, float]) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def matrix_rows(matrix: Matrix) -> list[list[float]]:
    return [[round(float(value), 8) for value in row] for row in matrix]


def safe_setattr(obj: Any, name: str, value: Any) -> bool:
    if not hasattr(obj, name):
        return False
    try:
        setattr(obj, name, value)
        return True
    except Exception:
        return False


def set_enum_value(owner: Any, prop: str, preferred: list[str]) -> str:
    if not hasattr(owner, prop):
        return ""
    try:
        enum_items = owner.bl_rna.properties[prop].enum_items
        available = {item.identifier for item in enum_items}
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


def object_is_bounds_mesh(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
        return False
    lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
    skip_tokens = ("skydome", "skybox", "fog_mp_gridlock", "sourceinformed_atmosphere")
    return not any(token in lower for token in skip_tokens)


def object_bounds(obj: bpy.types.Object) -> tuple[Vector, Vector]:
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
    return mins, maxs


def object_bounds_center(obj: bpy.types.Object) -> Vector:
    mins, maxs = object_bounds(obj)
    return (mins + maxs) * 0.5


def scene_bounds() -> dict[str, Any]:
    meshes = [obj for obj in bpy.data.objects if object_is_bounds_mesh(obj)]
    if not meshes:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0], "radius": 1200.0}
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in meshes:
        obj_min, obj_max = object_bounds(obj)
        mins.x = min(mins.x, obj_min.x)
        mins.y = min(mins.y, obj_min.y)
        mins.z = min(mins.z, obj_min.z)
        maxs.x = max(maxs.x, obj_max.x)
        maxs.y = max(maxs.y, obj_max.y)
        maxs.z = max(maxs.z, obj_max.z)
    center = (mins + maxs) * 0.5
    extents = maxs - mins
    radius = max(float(extents.x), float(extents.y), float(extents.z), 1.0) * 0.5
    return {"min": vec3(mins), "max": vec3(maxs), "center": vec3(center), "radius": round(radius, 6)}


def find_skybox_textures(texture_cache: Path) -> dict[str, dict[str, str]]:
    manifest = texture_cache / "gowreloaded_mp_gridlock_material_texture_export_manifest.csv"
    rows: dict[str, dict[str, str]] = {}
    for row in read_csv(manifest):
        key = str(row.get("texture_key") or row.get("texture") or row.get("name") or "").lower()
        path = row.get("dds_path") or row.get("path") or ""
        if not key or not path or not Path(path).exists():
            continue
        for role, token in {
            "background": "skydome_gridlock_bg_01_delta_tex",
            "sphere": "skydome_gridlock_bg_sphere_01_delta_tex",
            "mask": "skydome_gridlock_masks_01_delta_tex",
        }.items():
            if token in key and role not in rows:
                rows[role] = {
                    "key": key,
                    "dds_path": path,
                    "width": row.get("width", ""),
                    "height": row.get("height", ""),
                    "pixel_format": row.get("pixel_format", ""),
                }
    if rows:
        return rows
    texture_dir = texture_cache / "textures_dds"
    for path in texture_dir.glob("*skydome_gridlock*.dds"):
        name = path.name.lower()
        role = "background" if "bg_01_delta" in name else "sphere" if "bg_sphere" in name else "mask" if "masks" in name else ""
        if role:
            rows[role] = {"key": path.stem.lower(), "dds_path": str(path), "width": "", "height": "", "pixel_format": ""}
    return rows


def load_image(path_text: str) -> bpy.types.Image | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        return None
    try:
        image = bpy.data.images.load(str(path), check_existing=True)
    except Exception:
        return None
    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    return image


def make_visible_skybox_material(textures: dict[str, dict[str, str]], uv_layer: str) -> dict[str, Any]:
    material = bpy.data.materials.get(SKYBOX_MATERIAL) or bpy.data.materials.new(SKYBOX_MATERIAL)
    material.use_nodes = True
    material.diffuse_color = (0.50, 0.55, 0.58, 1.0)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (520, 0)
    emission = nodes.new(type="ShaderNodeEmission")
    emission.location = (285, 0)
    if "Strength" in emission.inputs:
        emission.inputs["Strength"].default_value = 1.05
    if "Color" in emission.inputs:
        emission.inputs["Color"].default_value = (0.48, 0.53, 0.57, 1.0)
    links.new(emission.outputs["Emission"], out.inputs["Surface"])

    chosen_role = "background" if "background" in textures else "sphere" if "sphere" in textures else "mask" if "mask" in textures else ""
    image = load_image(textures.get(chosen_role, {}).get("dds_path", "")) if chosen_role else None
    if image:
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.location = (0, 90)
        tex.image = image
        tex.extension = "REPEAT"
        if uv_layer:
            uv = nodes.new(type="ShaderNodeUVMap")
            uv.location = (-255, 90)
            uv.uv_map = uv_layer
            links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], emission.inputs["Color"])

    material["gridlock_visible_skybox_fix"] = "uv0_emission_source_texture"
    material["gridlock_source_material_path"] = "SkyDomes.skydome_gridlock_bg_01_MAT"
    material["gridlock_selected_texture_role"] = chosen_role
    material["gridlock_selected_texture_path"] = textures.get(chosen_role, {}).get("dds_path", "") if chosen_role else ""
    material["gridlock_selected_uv_layer"] = uv_layer
    return {
        "material": material.name,
        "selected_role": chosen_role,
        "selected_texture": material["gridlock_selected_texture_path"],
        "image_loaded": bool(image),
        "uv_layer": uv_layer,
    }


def find_sky_objects() -> list[bpy.types.Object]:
    out: list[bpy.types.Object] = []
    for obj in bpy.data.objects:
        lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
        if obj.type == "MESH" and ("skydome_gridlock" in lower or "skydomes.skydome_gridlock" in lower):
            out.append(obj)
    return out


def preserve_original_transform(obj: bpy.types.Object) -> None:
    if "gridlock_skybox_original_matrix_world_before_visible_fit" in obj:
        return
    obj["gridlock_skybox_original_location_before_visible_fit"] = json.dumps(vec3(obj.location), ensure_ascii=True)
    obj["gridlock_skybox_original_scale_before_visible_fit"] = json.dumps(vec3(obj.scale), ensure_ascii=True)
    obj["gridlock_skybox_original_dimensions_before_visible_fit"] = json.dumps(vec3(obj.dimensions), ensure_ascii=True)
    obj["gridlock_skybox_original_matrix_world_before_visible_fit"] = json.dumps(matrix_rows(obj.matrix_world), ensure_ascii=True)


def fit_skybox_object(obj: bpy.types.Object, bounds: dict[str, Any], material: bpy.types.Material) -> dict[str, Any]:
    preserve_original_transform(obj)
    before = {
        "location": vec3(obj.location),
        "scale": vec3(obj.scale),
        "dimensions": vec3(obj.dimensions),
        "bounds_center": vec3(object_bounds_center(obj)),
    }

    center = Vector(bounds["center"])
    radius = max(float(bounds["radius"]), 1200.0)
    target_center = center + Vector((0.0, 0.0, radius * 0.08))
    target_diameter = max(radius * 2.85, 7600.0)
    current_diameter = max(float(obj.dimensions.x), float(obj.dimensions.y), float(obj.dimensions.z), 1.0)
    scale_factor = target_diameter / current_diameter

    obj.scale = (obj.scale.x * scale_factor, obj.scale.y * scale_factor, obj.scale.z * scale_factor)
    bpy.context.view_layer.update()
    recentered_delta = target_center - object_bounds_center(obj)
    obj.location = obj.location + recentered_delta
    bpy.context.view_layer.update()

    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj.hide_viewport = False
    obj.hide_render = False
    safe_setattr(obj, "visible_shadow", False)
    obj.display_type = "TEXTURED"
    obj.show_name = False
    obj["gridlock_visible_skybox_fix"] = "source skydome fitted to scene bounds for Blender viewport/render visibility"
    obj["gridlock_visible_skybox_target_diameter"] = target_diameter
    obj["gridlock_visible_skybox_target_center"] = json.dumps(vec3(target_center), ensure_ascii=True)
    obj["gridlock_visible_skybox_uv_policy"] = "UV0 used for skydome material; prop/building UV_Source_Render policy is intentionally not applied to skybox."

    after = {
        "location": vec3(obj.location),
        "scale": vec3(obj.scale),
        "dimensions": vec3(obj.dimensions),
        "bounds_center": vec3(object_bounds_center(obj)),
    }
    return {
        "object": obj.name,
        "mesh": obj.data.name,
        "before": before,
        "after": after,
        "target_diameter": round(target_diameter, 6),
        "scale_factor": round(scale_factor, 8),
    }


def configure_world_background(textures: dict[str, dict[str, str]]) -> dict[str, Any]:
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    bg = nodes.get("Background")
    if bg:
        if "Strength" in bg.inputs:
            bg.inputs["Strength"].default_value = 0.22
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = (0.030, 0.036, 0.043, 1.0)
    role = "sphere" if "sphere" in textures else "background" if "background" in textures else ""
    image = load_image(textures.get(role, {}).get("dds_path", "")) if role else None
    env_status = "solid_background_only"
    if image and bg:
        env = nodes.new(type="ShaderNodeTexEnvironment")
        env.location = (-320, -150)
        env.image = image
        links.new(env.outputs["Color"], bg.inputs["Color"])
        env_status = "source_texture_environment_background"
    world.color = (0.030, 0.036, 0.043)
    world["gridlock_visible_skybox_fix"] = env_status
    world["gridlock_visible_skybox_source_texture"] = textures.get(role, {}).get("dds_path", "") if role else ""
    return {"world_background_status": env_status, "world_texture_role": role, "world_texture_loaded": bool(image)}


def render_still(path: Path) -> dict[str, Any]:
    ensure_dir(path)
    scene = bpy.context.scene
    scene.render.filepath = str(path)
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        return {"render_path": str(path), "render_ok": False, "render_error": str(exc)}
    return {
        "render_path": str(path),
        "render_ok": path.exists() and path.stat().st_size > 0,
        "render_size": path.stat().st_size if path.exists() else 0,
    }


def main() -> int:
    args = parse_args()
    texture_cache = Path(args.texture_cache)
    proof_out = Path(args.proof_out)
    render_out = Path(args.render_out)
    root = get_collection(ROOT_COLLECTION)
    sky_collection = get_collection("Skybox", root)

    bounds = scene_bounds()
    textures = find_skybox_textures(texture_cache)
    sky_objects = find_sky_objects()
    uv_layer = "UV0"
    for obj in sky_objects:
        if not obj.data.uv_layers.get(uv_layer):
            uv_layer = obj.data.uv_layers[0].name if obj.data.uv_layers else ""
            break
    material_summary = make_visible_skybox_material(textures, uv_layer)
    material = bpy.data.materials[material_summary["material"]]
    fit_rows = []
    for obj in sky_objects:
        link_object(sky_collection, obj)
        unlink_from_scene_root(obj)
        fit_rows.append(fit_skybox_object(obj, bounds, material))

    world_summary = configure_world_background(textures)
    scene = bpy.context.scene
    scene["gridlock_visible_skybox_fix"] = "applied"
    scene["gridlock_visible_skybox_proof"] = str(proof_out)
    scene["gridlock_skybox_status"] = "visible source skydome fitted to Blender scene bounds and source texture assigned on UV0"

    render_summary = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_summary = render_still(render_out)

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "visible_skybox_fix_applied",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "scene_bounds": bounds,
        "texture_cache": str(texture_cache),
        "textures": textures,
        "material": material_summary,
        "sky_objects_found": len(sky_objects),
        "skybox_fit": fit_rows,
        "world": world_summary,
        "render": render_summary,
        "counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "light_objects": sum(1 for obj in bpy.data.objects if obj.type == "LIGHT"),
            "direct_scene_root_objects": len(bpy.context.scene.collection.objects),
        },
    }
    ensure_dir(proof_out)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
