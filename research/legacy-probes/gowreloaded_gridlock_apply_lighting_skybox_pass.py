#!/usr/bin/env python3
"""Apply the serious MP_Gridlock lighting, fog, and source skybox pass.

This script is intentionally scene-side: it does not rebuild geometry or touch
source decode outputs. It updates the current Blender file with a tracked
environment rig using the decoded Gridlock skydome assets when available.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


MAP_ROOT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12"
)
DEFAULT_TEXTURE_CACHE = MAP_ROOT / "Material_Texture_Cache"
DEFAULT_PROOF = MAP_ROOT / "Blender_Scene_2026_08_12" / "gridlock_lighting_skybox_pass_2026_08_14.json"
DEFAULT_RENDER = MAP_ROOT / "Blender_Scene_2026_08_12" / "gridlock_lighting_skybox_pass_2026_08_14.png"

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
SKY_MATERIAL = "MAT__SkyDomes__skydome_gridlock_bg_01__SourceTextured_Emission"
FOG_MATERIAL = "MAT_MP_Gridlock_Atmospheric_Fog_SourceInformed"
SOURCE_NOTE = (
    "Source-informed Blender reconstruction pass. Reloaded static/baked "
    "lighting data is not fully decoded here, so helper lights are tracked as "
    "environment reconstruction aids rather than native light actors."
)

GENERATED_ENV_OBJECT_PREFIXES = (
    "SUN_MP_Gridlock_",
    "AREA_MP_Gridlock_",
    "POINT_MP_Gridlock_",
    "FOG_MP_Gridlock_",
    "CAM_MP_Gridlock_Environment_Proof",
)

OLD_HELPER_NAMES = {
    "SUN_MP_Gridlock_Decoded_Directional_Approx",
    "AREA_MP_Gridlock_Readability_Fill",
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-cache", default=str(DEFAULT_TEXTURE_CACHE))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default="")
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


def find_root_collection() -> bpy.types.Collection:
    return get_collection(ROOT_COLLECTION)


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


def vec3(values: Vector | tuple[float, float, float] | list[float]) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def object_is_visible_for_bounds(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH":
        return False
    if obj.hide_viewport or obj.hide_render:
        return False
    lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
    if "skydome" in lower or "skybox" in lower or lower.startswith("fog_mp_gridlock"):
        return False
    return True


def compute_scene_bounds() -> dict[str, Any]:
    mesh_objects = [obj for obj in bpy.data.objects if object_is_visible_for_bounds(obj)]
    if not mesh_objects:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0], "radius": 50.0}

    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in mesh_objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x)
            mins.y = min(mins.y, world.y)
            mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x)
            maxs.y = max(maxs.y, world.y)
            maxs.z = max(maxs.z, world.z)
    center = (mins + maxs) * 0.5
    extents = maxs - mins
    radius = max(float(extents.x), float(extents.y), float(extents.z), 1.0) * 0.5
    return {"min": vec3(mins), "max": vec3(maxs), "center": vec3(center), "radius": round(radius, 6)}


def find_texture_rows(texture_cache: Path) -> dict[str, dict[str, Any]]:
    manifest = texture_cache / "gowreloaded_mp_gridlock_material_texture_export_manifest.csv"
    rows = {}
    for row in read_csv(manifest):
        key = str(row.get("texture_key") or row.get("texture") or row.get("name") or "").lower()
        path = Path(row.get("dds_path") or row.get("path") or "")
        if not key or not path.exists():
            continue
        rows[key] = {
            "key": key,
            "dds_path": str(path),
            "width": row.get("width", ""),
            "height": row.get("height", ""),
            "pixel_format": row.get("pixel_format", ""),
            "tfc_path": row.get("tfc_path", ""),
            "tfc_offset": row.get("tfc_offset", ""),
        }

    if rows:
        return rows

    texture_dir = texture_cache / "textures_dds"
    for path in texture_dir.glob("*skydome_gridlock*.dds"):
        rows[path.stem.lower()] = {
            "key": path.stem.lower(),
            "dds_path": str(path),
            "width": "",
            "height": "",
            "pixel_format": "",
            "tfc_path": "",
            "tfc_offset": "",
        }
    return rows


def select_gridlock_sky_textures(texture_cache: Path) -> dict[str, dict[str, Any]]:
    rows = find_texture_rows(texture_cache)
    wanted = {
        "background": "skydome_gridlock_bg_01_delta_tex",
        "sphere": "skydome_gridlock_bg_sphere_01_delta_tex",
        "mask": "skydome_gridlock_masks_01_delta_tex",
    }
    selected: dict[str, dict[str, Any]] = {}
    for role, token in wanted.items():
        for key, row in rows.items():
            if token in key:
                selected[role] = row
                break
    return selected


def load_image(path_text: str, colorspace: str = "sRGB") -> bpy.types.Image | None:
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
        image.colorspace_settings.name = colorspace
    except Exception:
        pass
    return image


def sky_uv_layer(sky_objects: list[bpy.types.Object]) -> str:
    priority = ("UV_Source_Render", "UV0", "UV_Half_Offset4", "UV_Half_Offset8")
    for obj in sky_objects:
        if obj.type != "MESH":
            continue
        for name in priority:
            if obj.data.uv_layers.get(name):
                return name
        if obj.data.uv_layers:
            return obj.data.uv_layers[0].name
    return ""


def make_sky_material(textures: dict[str, dict[str, Any]], uv_layer: str) -> dict[str, Any]:
    material = bpy.data.materials.get(SKY_MATERIAL) or bpy.data.materials.new(SKY_MATERIAL)
    material.use_nodes = True
    material.diffuse_color = (0.42, 0.47, 0.50, 1.0)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "BLENDED", "OPAQUE"])

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (520, 0)
    emission = nodes.new(type="ShaderNodeEmission")
    emission.location = (270, 0)
    if "Strength" in emission.inputs:
        emission.inputs["Strength"].default_value = 0.82
    if "Color" in emission.inputs:
        emission.inputs["Color"].default_value = (0.42, 0.48, 0.52, 1.0)
    links.new(emission.outputs["Emission"], out.inputs["Surface"])

    chosen_role = "background" if "background" in textures else "sphere" if "sphere" in textures else "mask" if "mask" in textures else ""
    chosen_image = load_image(textures.get(chosen_role, {}).get("dds_path", "")) if chosen_role else None
    if chosen_image:
        image_node = nodes.new(type="ShaderNodeTexImage")
        image_node.location = (-20, 70)
        image_node.image = chosen_image
        image_node.extension = "REPEAT"
        if uv_layer:
            uv_node = nodes.new(type="ShaderNodeUVMap")
            uv_node.location = (-260, 70)
            uv_node.uv_map = uv_layer
            links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])
        links.new(image_node.outputs["Color"], emission.inputs["Color"])

    material["gridlock_source_material_path"] = "SkyDomes.skydome_gridlock_bg_01_MAT"
    material["gridlock_skybox_status"] = "native_decoded_texture_assigned" if chosen_image else "texture_missing_fallback_color"
    material["gridlock_skybox_selected_role"] = chosen_role
    material["gridlock_skybox_selected_texture"] = textures.get(chosen_role, {}).get("dds_path", "") if chosen_role else ""
    material["gridlock_skybox_uv_layer"] = uv_layer
    return {
        "material": material.name,
        "selected_role": chosen_role,
        "selected_texture": material["gridlock_skybox_selected_texture"],
        "selected_image_loaded": bool(chosen_image),
        "uv_layer": uv_layer,
        "available_texture_roles": sorted(textures),
    }


def collect_sky_objects(root: bpy.types.Collection, textures: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sky_collection = get_collection("Skybox", root)
    sky_objects: list[bpy.types.Object] = []
    for obj in bpy.data.objects:
        lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
        if "skydome_gridlock" not in lower and "skydomes.skydome" not in lower and "skybox" not in lower:
            continue
        if obj.type != "MESH":
            continue
        sky_objects.append(obj)

    if not sky_objects:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=360.0, location=(0.0, 0.0, 32.0))
        dome = bpy.context.object
        dome.name = "SKYBOX_MP_Gridlock_Procedural_Fallback_SourceTracked"
        dome.data.name = "SKYBOX_MP_Gridlock_Procedural_Fallback_SourceTracked_Mesh"
        dome["native_export"] = "Fallback only: decoded SkyDomes.skydome_gridlock_bg_01_SMesh instance was not found in this blend"
        sky_objects.append(dome)

    uv_layer = sky_uv_layer(sky_objects)
    material_summary = make_sky_material(textures, uv_layer)
    material = bpy.data.materials[material_summary["material"]]

    assigned = []
    for obj in sky_objects:
        obj.data.materials.clear()
        obj.data.materials.append(material)
        obj.hide_viewport = False
        obj.hide_render = False
        safe_setattr(obj, "visible_shadow", False)
        obj["gridlock_skybox_source_instance"] = True
        obj["gridlock_skybox_material_pass"] = "source_textured_emission"
        obj["gridlock_skybox_source_material_path"] = "SkyDomes.skydome_gridlock_bg_01_MAT"
        obj["gridlock_skybox_source_texture"] = material_summary["selected_texture"]
        obj["gridlock_skybox_note"] = "Actual decoded Gridlock skydome object/material family when present; emission shader used so sky is not lit by local lamps."
        link_object(sky_collection, obj)
        unlink_from_scene_root(obj)
        assigned.append(
            {
                "object": obj.name,
                "mesh": obj.data.name,
                "ue_static_mesh_path": str(obj.get("ue_static_mesh_path") or ""),
                "uv_layers": [layer.name for layer in obj.data.uv_layers],
            }
        )

    return {
        "sky_objects_found": len(assigned),
        "sky_objects": assigned,
        "sky_material": material_summary,
    }


def remove_old_generated_environment() -> list[str]:
    removed: list[str] = []
    for obj in list(bpy.data.objects):
        if obj.type not in {"LIGHT", "CAMERA", "MESH"}:
            continue
        if obj.name in OLD_HELPER_NAMES or any(obj.name.startswith(prefix) for prefix in GENERATED_ENV_OBJECT_PREFIXES):
            if obj.type == "MESH" and not obj.name.startswith("FOG_MP_Gridlock_"):
                continue
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    for light in list(bpy.data.lights):
        if light.name in OLD_HELPER_NAMES or any(light.name.startswith(prefix) for prefix in GENERATED_ENV_OBJECT_PREFIXES):
            bpy.data.lights.remove(light)
    return removed


def aim_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - Vector(obj.location)
    if direction.length <= 0.0001:
        return
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def new_light(name: str, light_type: str, collection: bpy.types.Collection) -> bpy.types.Object:
    data = bpy.data.lights.new(name, light_type)
    obj = bpy.data.objects.new(name, data)
    link_object(collection, obj)
    obj["gridlock_lighting_pass"] = "source_informed_environment_reconstruction"
    obj["native_decode_status"] = "source_informed_not_a_decoded_native_light_actor"
    obj["render_note"] = SOURCE_NOTE
    return obj


def configure_light_shadow(light: bpy.types.Light) -> None:
    safe_setattr(light, "use_shadow", True)
    safe_setattr(light, "use_contact_shadow", True)
    safe_setattr(light, "contact_shadow_distance", 8.0)
    safe_setattr(light, "contact_shadow_bias", 0.02)


def create_lighting(root: bpy.types.Collection, bounds: dict[str, Any]) -> dict[str, Any]:
    lighting = get_collection("Lighting", root)
    env = get_collection("Source_Informed_Environment", lighting)
    center = Vector(bounds["center"])
    radius = max(float(bounds["radius"]), 35.0)
    zmin = float(bounds["min"][2])

    sun = new_light("SUN_MP_Gridlock_WarmLowKey_SourceInformed", "SUN", env)
    sun.location = center + Vector((-radius * 0.95, -radius * 0.62, radius * 0.92))
    aim_at(sun, center)
    sun.data.energy = 2.05
    sun.data.color = (1.0, 0.74, 0.48)
    safe_setattr(sun.data, "angle", math.radians(3.5))
    configure_light_shadow(sun.data)
    sun["direction_policy"] = "warm low-angle key chosen to match Gridlock's dusk warzone skybox direction/read."

    sky_fill = new_light("AREA_MP_Gridlock_CoolSkyFill_SourceInformed", "AREA", env)
    sky_fill.location = center + Vector((radius * 0.14, radius * 0.22, radius * 0.74))
    aim_at(sky_fill, center)
    sky_fill.data.energy = 520.0
    sky_fill.data.size = radius * 1.9
    sky_fill.data.color = (0.43, 0.52, 0.68)
    configure_light_shadow(sky_fill.data)
    sky_fill["direction_policy"] = "large cool fill stands in for sky/baked ambient contribution."

    bounce = new_light("AREA_MP_Gridlock_DirtyStreetBounce_SourceInformed", "AREA", env)
    bounce.location = center + Vector((radius * 0.38, -radius * 0.26, max(4.0, zmin + 4.5)))
    aim_at(bounce, center + Vector((0.0, 0.0, radius * 0.16)))
    bounce.data.energy = 130.0
    bounce.data.size = radius * 1.35
    bounce.data.color = (0.68, 0.51, 0.36)
    configure_light_shadow(bounce.data)
    bounce["direction_policy"] = "low warm bounce to keep street rubble and vehicles in the Gears contrast range."

    accents = []
    accent_specs = [
        ("POINT_MP_Gridlock_RubbleAmberAccent_A", Vector((-0.34, -0.18, 0.07)), 125.0, 14.0),
        ("POINT_MP_Gridlock_RubbleAmberAccent_B", Vector((0.28, 0.24, 0.06)), 95.0, 12.0),
        ("POINT_MP_Gridlock_ArchShadowCoolAccent", Vector((0.10, -0.42, 0.16)), 70.0, 18.0),
    ]
    for name, rel, energy, size in accent_specs:
        obj = new_light(name, "POINT", env)
        obj.location = center + Vector((rel.x * radius, rel.y * radius, rel.z * radius))
        obj.data.energy = energy
        obj.data.shadow_soft_size = size
        obj.data.color = (0.95, 0.55, 0.25) if "Amber" in name else (0.36, 0.45, 0.62)
        configure_light_shadow(obj.data)
        obj["direction_policy"] = "subtle map-read accent for baked-light reconstruction; not a weapon/pickup/native actor."
        accents.append(obj.name)

    lights = [sun.name, sky_fill.name, bounce.name, *accents]
    return {
        "lighting_collection": env.name,
        "source_informed_lights_created": lights,
        "decoded_light_actor_status": "no native PointLight/SpotLight/DirectionalLight rows were exposed by current actor property probe",
    }


def configure_world_and_render(bounds: dict[str, Any]) -> dict[str, Any]:
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    world.color = (0.018, 0.021, 0.025)
    nodes = world.node_tree.nodes
    bg = nodes.get("Background")
    if bg:
        if "Color" in bg.inputs:
            bg.inputs["Color"].default_value = (0.026, 0.032, 0.039, 1.0)
        if "Strength" in bg.inputs:
            bg.inputs["Strength"].default_value = 0.18

    mist = world.mist_settings
    mist.use_mist = True
    radius = max(float(bounds["radius"]), 35.0)
    mist.start = radius * 0.22
    mist.depth = radius * 2.0
    mist.intensity = 0.10
    set_enum_value(mist, "falloff", ["QUADRATIC", "INVERSE_QUADRATIC", "LINEAR"])

    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100

    eevee = getattr(scene, "eevee", None)
    eevee_settings: dict[str, Any] = {}
    if eevee:
        for prop, value in (
            ("taa_render_samples", 64),
            ("taa_samples", 32),
            ("use_gtao", True),
            ("gtao_distance", 18.0),
            ("gtao_factor", 1.35),
            ("use_bloom", True),
            ("bloom_intensity", 0.035),
            ("bloom_radius", 3.5),
            ("use_volumetric_lights", True),
            ("volumetric_tile_size", "4"),
            ("volumetric_samples", 96),
        ):
            if safe_setattr(eevee, prop, value):
                eevee_settings[prop] = value

    view = scene.view_settings
    view_transform = set_enum_value(view, "view_transform", ["Filmic", "AgX", "Standard"])
    look = set_enum_value(view, "look", ["Medium High Contrast", "High Contrast", "Medium High Contrast", "None"])
    view.exposure = -0.08
    view.gamma = 1.0

    return {
        "world_color": [0.018, 0.021, 0.025],
        "world_background_strength": 0.18,
        "mist": {
            "use_mist": True,
            "start": round(mist.start, 6),
            "depth": round(mist.depth, 6),
            "intensity": round(mist.intensity, 6),
            "falloff": getattr(mist, "falloff", ""),
        },
        "render_engine": scene.render.engine,
        "eevee_settings_applied": eevee_settings,
        "view_transform": view_transform,
        "look": look,
        "exposure": view.exposure,
        "gamma": view.gamma,
    }


def create_fog_volume(root: bpy.types.Collection, bounds: dict[str, Any]) -> dict[str, Any]:
    collection = get_collection("Environment_Fog_Sky", root)
    center = Vector(bounds["center"])
    mins = Vector(bounds["min"])
    maxs = Vector(bounds["max"])
    extents = maxs - mins
    radius = max(float(bounds["radius"]), 35.0)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center + Vector((0.0, 0.0, radius * 0.08)))
    fog = bpy.context.object
    fog.name = "FOG_MP_Gridlock_SourceInformed_Atmosphere"
    fog.data.name = "FOG_MP_Gridlock_SourceInformed_Atmosphere_Mesh"
    fog.dimensions = (
        max(float(extents.x) * 1.28, radius * 1.8),
        max(float(extents.y) * 1.28, radius * 1.8),
        max(float(extents.z) * 1.35, radius * 0.95),
    )
    bpy.context.view_layer.objects.active = fog
    try:
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    except Exception:
        pass
    fog.display_type = "WIRE"
    fog.hide_select = True
    fog["gridlock_environment_pass"] = "source_informed_fog_volume"
    fog["native_decode_status"] = "source_informed_not_decoded_native_exponential_height_fog"
    fog["render_note"] = SOURCE_NOTE

    material = bpy.data.materials.get(FOG_MATERIAL) or bpy.data.materials.new(FOG_MATERIAL)
    material.use_nodes = True
    material.diffuse_color = (0.28, 0.34, 0.39, 0.18)
    set_enum_value(material, "blend_method", ["BLEND", "DITHERED"])
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (260, 0)
    volume = nodes.new(type="ShaderNodeVolumeScatter")
    volume.location = (0, 0)
    if "Color" in volume.inputs:
        volume.inputs["Color"].default_value = (0.30, 0.36, 0.42, 1.0)
    radius = max(float(bounds["radius"]), 35.0)
    density = max(0.000018, min(0.000075, 0.16 / max(radius * 1.8, 1.0)))
    if "Density" in volume.inputs:
        volume.inputs["Density"].default_value = density
    links.new(volume.outputs["Volume"], out.inputs["Volume"])
    material["gridlock_fog_pass"] = "source_informed_smoky_street_atmosphere"
    material["gridlock_fog_density"] = density
    fog.data.materials.clear()
    fog.data.materials.append(material)
    link_object(collection, fog)
    unlink_from_scene_root(fog)
    return {
        "fog_volume_object": fog.name,
        "fog_material": material.name,
        "fog_density": round(density, 8),
        "fog_dimensions": vec3(fog.dimensions),
        "fog_location": vec3(fog.location),
    }


def create_environment_camera(root: bpy.types.Collection, bounds: dict[str, Any]) -> dict[str, Any]:
    collection = get_collection("Cameras", root)
    center = Vector(bounds["center"])
    radius = max(float(bounds["radius"]), 35.0)
    cam_data = bpy.data.cameras.new("CAM_MP_Gridlock_Environment_Proof")
    cam = bpy.data.objects.new("CAM_MP_Gridlock_Environment_Proof", cam_data)
    cam.location = center + Vector((-radius * 0.62, -radius * 0.86, radius * 0.42))
    aim_at(cam, center + Vector((0.0, 0.0, radius * 0.03)))
    cam.data.lens = 23.0
    cam.data.clip_start = 0.05
    cam.data.clip_end = radius * 8.0
    cam["gridlock_environment_pass"] = "proof_camera_for_lighting_skybox_validation"
    cam["native_decode_status"] = "validation_camera_not_native_game_camera"
    link_object(collection, cam)
    bpy.context.scene.camera = cam
    return {"camera": cam.name, "location": vec3(cam.location), "lens": cam.data.lens, "clip_end": cam.data.clip_end}


def render_still(render_out: Path) -> dict[str, Any]:
    ensure_dir(render_out)
    scene = bpy.context.scene
    scene.render.filepath = str(render_out)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        return {"render_path": str(render_out), "render_ok": False, "render_error": str(exc)}
    return {
        "render_path": str(render_out),
        "render_ok": render_out.exists() and render_out.stat().st_size > 0,
        "render_size": render_out.stat().st_size if render_out.exists() else 0,
    }


def main() -> int:
    args = parse_args()
    texture_cache = Path(args.texture_cache)
    proof_out = Path(args.proof_out)
    render_out = Path(args.render_out) if args.render_out else DEFAULT_RENDER

    root = find_root_collection()
    removed = remove_old_generated_environment()
    bounds = compute_scene_bounds()
    textures = select_gridlock_sky_textures(texture_cache)
    sky_summary = collect_sky_objects(root, textures)
    lighting_summary = create_lighting(root, bounds)
    world_summary = configure_world_and_render(bounds)
    fog_summary = create_fog_volume(root, bounds)
    camera_summary = create_environment_camera(root, bounds)

    scene = bpy.context.scene
    scene["gridlock_environment_lighting_skybox_pass"] = "applied"
    scene["gridlock_environment_lighting_skybox_proof"] = str(proof_out)
    scene["gridlock_skybox_status"] = (
        "source texture assigned from SkyDomes.skydome_gridlock_bg_01_MAT family"
        if sky_summary["sky_material"]["selected_image_loaded"]
        else "skybox fallback color; native sky texture failed to load"
    )
    scene["gridlock_lighting_status"] = "source-informed warm key/cool sky/fog rig applied; native baked lightmaps still not decoded"
    scene["gridlock_environment_note"] = SOURCE_NOTE

    render_summary: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_summary = render_still(render_out)

    proof = {
        "blend_path": bpy.data.filepath,
        "texture_cache": str(texture_cache),
        "proof_path": str(proof_out),
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "status": "lighting_skybox_environment_pass_applied",
        "source_note": SOURCE_NOTE,
        "removed_old_generated_environment_objects": removed,
        "scene_bounds": bounds,
        "sky": sky_summary,
        "lighting": lighting_summary,
        "world_render": world_summary,
        "fog": fog_summary,
        "camera": camera_summary,
        "render": render_summary,
        "counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "light_objects": sum(1 for obj in bpy.data.objects if obj.type == "LIGHT"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
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
