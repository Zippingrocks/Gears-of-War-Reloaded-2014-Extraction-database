#!/usr/bin/env python3
"""Apply decoded MP_Gridlock native lighting/fog to the Reloaded Blender scene."""

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


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
DEFAULT_MANIFEST = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Native_Lighting_Probe_2026_08_15\gowreloaded_mp_gridlock_native_lighting_done_manifest.json"
)
DEFAULT_PROOF = SCENE_DIR / "gridlock_native_lighting_done_2026_08_15.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_native_lighting_done_2026_08_15.png"
DEFAULT_RENDER_WIDE = SCENE_DIR / "gridlock_native_lighting_done_wide_2026_08_15.png"
DEFAULT_PREVIEW_COPY = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_native_lighting_done_latest.png")
DEFAULT_PREVIEW_WIDE_COPY = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping\gridlock_native_lighting_done_wide_latest.png")

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--render-wide-out", default=str(DEFAULT_RENDER_WIDE))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW_COPY))
    parser.add_argument("--preview-wide-copy", default=str(DEFAULT_PREVIEW_WIDE_COPY))
    parser.add_argument("--render-proof", action="store_true")
    return parser.parse_args(argv)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")


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


def clear_collection_objects(collection: bpy.types.Collection) -> int:
    removed = 0
    for child in list(collection.children):
        removed += clear_collection_objects(child)
    for obj in list(collection.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    return removed


def remove_existing_environment_lights() -> list[str]:
    removed: list[str] = []
    for obj in list(bpy.data.objects):
        if obj.type == "LIGHT":
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
        elif obj.name.startswith("FOG_MP_Gridlock_NativeLighting"):
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    return removed


def object_is_visible_for_bounds(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
        return False
    text = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
    if "skydome" in text or "skybox" in text or obj.name.startswith("FOG_MP_Gridlock"):
        return False
    return True


def scene_bounds() -> dict[str, Any]:
    objs = [obj for obj in bpy.data.objects if object_is_visible_for_bounds(obj)]
    if not objs:
        return {"min": [0, 0, 0], "max": [0, 0, 0], "center": [0, 0, 0], "extent": [1, 1, 1], "radius": 1}
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objs:
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


def ue_to_blender_point(values: list[float] | tuple[float, float, float], unit_scale: float) -> Vector:
    x, y, z = values
    return Vector((float(y) * unit_scale, -float(x) * unit_scale, float(z) * unit_scale))


def ue_to_blender_vector(values: list[float] | tuple[float, float, float]) -> Vector:
    x, y, z = values
    vec = Vector((float(y), -float(x), float(z)))
    if vec.length <= 1e-8:
        return Vector((0.0, 0.0, -1.0))
    return vec.normalized()


def corrected_light_matrix(light: dict[str, Any], unit_scale: float) -> dict[str, Any]:
    values = (light.get("matrix") or {}).get("row_major") or []
    if len(values) < 16:
        return {"ok": False, "location": Vector((0, 0, 0)), "direction": Vector((0, 0, -1)), "ue_translation": None}
    ue_translation = [float(values[13]), float(values[14]), float(values[15])]
    basis_rows = [
        [float(values[1]), float(values[2]), float(values[3])],
        [float(values[5]), float(values[6]), float(values[7])],
        [float(values[9]), float(values[10]), float(values[11])],
    ]
    direction = ue_to_blender_vector(basis_rows[2])
    return {
        "ok": True,
        "ue_translation": ue_translation,
        "location": ue_to_blender_point(ue_translation, unit_scale),
        "direction": direction,
        "basis_rows": basis_rows,
    }


def light_color(light: dict[str, Any]) -> tuple[float, float, float]:
    rgb = (light.get("light_color") or {}).get("rgb_srgb")
    if isinstance(rgb, list) and len(rgb) >= 3:
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    return (1.0, 1.0, 1.0)


def set_light_common(data: bpy.types.Light, color: tuple[float, float, float], shadow: bool = True) -> None:
    data.color = color
    if hasattr(data, "use_shadow"):
        data.use_shadow = shadow
    if hasattr(data, "use_contact_shadow"):
        data.use_contact_shadow = True
    if hasattr(data, "contact_shadow_distance"):
        data.contact_shadow_distance = 150.0


def add_native_light(light: dict[str, Any], collection: bpy.types.Collection, unit_scale: float) -> dict[str, Any]:
    cls = light["class_name"]
    name = "LGT_NATIVE_" + light["object_name"]
    color = light_color(light)
    brightness = float(light.get("brightness") or 1.0)
    radius = light.get("radius")
    radius_bl = float(radius) * unit_scale if isinstance(radius, (int, float)) else 0.0

    if cls == "DirectionalLightComponent":
        data = bpy.data.lights.new(name, "SUN")
        data.energy = max(2.0, brightness * 0.78)
        set_light_common(data, color)
        obj = bpy.data.objects.new(name, data)
        # The cooked SLC exposes brightness/color for the directional light but
        # no transform matrix; this direction is the established Gridlock sun
        # direction from the prior sky/lighting proof pass.
        direction = Vector((-0.35, 0.42, -0.837)).normalized()
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        obj["native_direction_source"] = "DirectionalLightComponent exposes no CachedParentToWorld; uses source-informed Gridlock sun vector"
        loc = [0.0, 0.0, 0.0]
    elif cls == "SpotLightComponent":
        data = bpy.data.lights.new(name, "SPOT")
        energy = min(65000.0, max(80.0, brightness * max(radius_bl, 1.0) ** 1.35 * 135.0))
        data.energy = energy
        data.cutoff_distance = max(radius_bl, 1.0)
        outer = float(light.get("outer_cone_angle") or 45.0)
        data.spot_size = math.radians(min(175.0, max(8.0, outer * 2.0)))
        inner = light.get("inner_cone_angle")
        if isinstance(inner, (int, float)) and outer > 0:
            data.spot_blend = max(0.05, min(0.95, 1.0 - float(inner) / outer))
        else:
            data.spot_blend = 0.38
        data.shadow_soft_size = max(0.35, min(8.0, radius_bl * 0.025))
        set_light_common(data, color)
        mat = corrected_light_matrix(light, unit_scale)
        obj = bpy.data.objects.new(name, data)
        obj.location = mat["location"]
        obj.rotation_euler = mat["direction"].to_track_quat("-Z", "Y").to_euler()
        loc = [float(v) for v in obj.location]
    else:
        data = bpy.data.lights.new(name, "POINT")
        energy = min(30000.0, max(45.0, brightness * max(radius_bl, 1.0) ** 1.35 * 115.0))
        data.energy = energy
        data.cutoff_distance = max(radius_bl, 1.0)
        data.shadow_soft_size = max(0.45, min(12.0, radius_bl * 0.045))
        set_light_common(data, color)
        mat = corrected_light_matrix(light, unit_scale)
        obj = bpy.data.objects.new(name, data)
        obj.location = mat["location"]
        loc = [float(v) for v in obj.location]

    obj["ue_class"] = cls
    obj["ue_full_path"] = light.get("full_path", "")
    obj["ue_export_index"] = light.get("export_index", "")
    obj["ue_brightness"] = brightness
    obj["ue_radius"] = radius if radius is not None else ""
    obj["ue_color_fcolor_bgra_json"] = json.dumps((light.get("light_color") or {}).get("rgba8") or [])
    obj["native_export"] = "Decoded Reloaded MP_Gridlock StaticLightCollectionActor light component"
    link_object(collection, obj)
    unlink_from_scene_root(obj)
    return {
        "object": obj.name,
        "type": data.type,
        "class_name": cls,
        "energy": float(data.energy),
        "color": list(color),
        "location": loc,
        "cutoff_distance": float(getattr(data, "cutoff_distance", 0.0)),
        "source_path": light.get("full_path", ""),
    }


def add_baked_lightmap_compensation(collection: bpy.types.Collection, bounds: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    added = []

    sky_data = bpy.data.lights.new("AREA_MP_Gridlock_NativeLightmap_SkyFill_Compensation", "AREA")
    sky_data.energy = 5200.0
    sky_data.size = max(120.0, radius * 1.35)
    sky_data.color = (0.62, 0.68, 0.74)
    sky = bpy.data.objects.new(sky_data.name, sky_data)
    sky.location = center + Vector((0.0, 0.0, radius * 0.72))
    sky["native_export"] = "Compensates for 712 decoded UE3 LightMapTexture2D exports not yet bound as Blender surface lightmaps"
    link_object(collection, sky)
    unlink_from_scene_root(sky)
    added.append({"object": sky.name, "type": sky_data.type, "energy": sky_data.energy, "size": sky_data.size})

    bounce_data = bpy.data.lights.new("AREA_MP_Gridlock_NativeLightmap_DirtyBounce_Compensation", "AREA")
    bounce_data.energy = 1800.0
    bounce_data.size = max(90.0, radius * 0.85)
    bounce_data.color = (0.52, 0.49, 0.43)
    bounce = bpy.data.objects.new(bounce_data.name, bounce_data)
    bounce.location = center + Vector((0.0, 0.0, max(75.0, radius * 0.18)))
    bounce["native_export"] = "Low warm fill for baked street/building bounce present in UE3 static lightmaps"
    link_object(collection, bounce)
    unlink_from_scene_root(bounce)
    added.append({"object": bounce.name, "type": bounce_data.type, "energy": bounce_data.energy, "size": bounce_data.size})
    return added


def color_from_fog(fog: list[dict[str, Any]], key: str, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    for row in fog:
        decoded = row.get(f"{key}_decoded") or {}
        rgb = decoded.get("rgb_srgb")
        if isinstance(rgb, list) and len(rgb) >= 3:
            return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    return fallback


def add_native_fog(collection: bpy.types.Collection, bounds: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    fog_rows = manifest.get("fog") or []
    exp = next((row for row in fog_rows if row.get("class_name") == "ExponentialHeightFogComponent"), {})
    height = next((row for row in fog_rows if row.get("class_name") == "HeightFogComponent"), {})
    exp_props = exp.get("properties") or {}
    height_props = height.get("properties") or {}

    native_density = float(exp_props.get("FogDensity") or 0.1)
    native_max_opacity = float(exp_props.get("FogMaxOpacity") or 0.025)
    native_start = float(exp_props.get("StartDistance") or 4500.0)
    height_density = float(height_props.get("Density") or 0.00001)
    fog_color = color_from_fog(fog_rows, "LightColor", (0.65, 0.67, 0.62))

    mat = bpy.data.materials.get("MAT_MP_Gridlock_NativeLighting_Fog") or bpy.data.materials.new("MAT_MP_Gridlock_NativeLighting_Fog")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputMaterial")
    volume = nodes.new(type="ShaderNodeVolumePrincipled")
    if "Color" in volume.inputs:
        volume.inputs["Color"].default_value = (fog_color[0], fog_color[1], fog_color[2], 1.0)
    if "Density" in volume.inputs:
        volume.inputs["Density"].default_value = max(0.000008, min(0.000045, native_density * height_density * 12.0))
    links.new(volume.outputs["Volume"], out.inputs["Volume"])

    center = Vector(bounds["center"])
    extent = Vector(bounds["extent"])
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center + Vector((0.0, 0.0, extent.z * 0.08)))
    fog_obj = bpy.context.object
    fog_obj.name = "FOG_MP_Gridlock_NativeLighting_ExponentialHeightFog"
    fog_obj.dimensions = (max(1.0, extent.x * 1.25), max(1.0, extent.y * 1.25), max(1.0, extent.z * 1.15))
    fog_obj.data.materials.append(mat)
    fog_obj.display_type = "WIRE"
    fog_obj.hide_select = True
    fog_obj["native_export"] = "Decoded ExponentialHeightFog/HeightFog values approximated as Blender volume and mist"
    link_object(collection, fog_obj)
    unlink_from_scene_root(fog_obj)

    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.color = (0.034, 0.038, 0.041)
    if hasattr(bpy.context.scene, "use_mist"):
        bpy.context.scene.use_mist = True
    mist = world.mist_settings
    mist.use_mist = True
    mist.start = native_start * float(manifest.get("unit_scale") or 0.01)
    mist.depth = max(250.0, float(bounds["radius"]) * 1.8)
    mist.intensity = max(0.015, min(0.08, native_max_opacity * 1.8))
    mist.falloff = "QUADRATIC"
    return {
        "object": fog_obj.name,
        "native_fog_density": native_density,
        "native_height_density": height_density,
        "native_start_distance": native_start,
        "native_max_opacity": native_max_opacity,
        "blender_mist_start": mist.start,
        "blender_mist_depth": mist.depth,
        "blender_mist_intensity": mist.intensity,
    }


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
            "gtao_distance": 300.0,
            "gtao_factor": 0.82,
            "use_bloom": True,
        }.items():
            if hasattr(eevee, prop):
                try:
                    setattr(eevee, prop, value)
                except Exception:
                    pass
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.28
    scene.view_settings.gamma = 1.0
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.frame_set(72)
    return {
        "engine": scene.render.engine,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    }


def make_camera(name: str, bounds: dict[str, Any], wide: bool = False) -> bpy.types.Object:
    center = Vector(bounds["center"])
    radius = float(bounds["radius"])
    if wide:
        loc = center + Vector((-radius * 0.58, -radius * 0.86, radius * 0.48))
        lens = 22.0
    else:
        loc = center + Vector((-radius * 0.34, -radius * 0.55, radius * 0.32))
        lens = 28.0
    data = bpy.data.cameras.get(name) or bpy.data.cameras.new(name)
    cam = bpy.data.objects.get(name) or bpy.data.objects.new(name, data)
    cam.location = loc
    direction = center - loc
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    data.lens = lens
    data.clip_end = max(150000.0, radius * 12.0)
    data.dof.use_dof = False
    bpy.context.scene.camera = cam
    return cam


def render_to(path: Path, camera: bpy.types.Object) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.camera = camera
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
    manifest_path = Path(args.manifest)
    manifest = read_json(manifest_path)
    root = get_collection(ROOT_COLLECTION)
    lighting = get_collection("Lighting", root)
    native = get_collection("Native_StaticLightCollection_MP_Gridlock_SLC_0", lighting)
    fog_collection = get_collection("Native_Fog", lighting)
    removed_prior = remove_existing_environment_lights()
    removed_native = clear_collection_objects(native)
    removed_fog = clear_collection_objects(fog_collection)
    bounds = scene_bounds()
    unit_scale = float(manifest.get("unit_scale") or 0.01)

    applied = []
    for light in manifest.get("lights") or []:
        applied.append(add_native_light(light, native, unit_scale))
    compensation = add_baked_lightmap_compensation(native, bounds, manifest)
    fog = add_native_fog(fog_collection, bounds, manifest)
    render_config = configure_render()
    cam = make_camera("CAM_MP_Gridlock_NativeLighting_Done", bounds, wide=False)
    cam_wide = make_camera("CAM_MP_Gridlock_NativeLighting_Done_Wide", bounds, wide=True)

    render_result: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_result["main"] = render_to(Path(args.render_out), cam)
        render_result["wide"] = render_to(Path(args.render_wide_out), cam_wide)
        render_result["main"]["preview"] = str(Path(args.preview_copy))
        render_result["main"]["copied"] = copy_preview(Path(args.render_out), Path(args.preview_copy))
        render_result["wide"]["preview"] = str(Path(args.preview_wide_copy))
        render_result["wide"]["copied"] = copy_preview(Path(args.render_wide_out), Path(args.preview_wide_copy))

    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_native_lighting_done_applied",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "manifest": str(manifest_path),
        "native_counts": manifest.get("counts", {}),
        "removed_prior_light_objects": removed_prior,
        "removed_prior_native_objects": removed_native,
        "removed_prior_fog_objects": removed_fog,
        "scene_bounds": bounds,
        "unit_scale": unit_scale,
        "matrix_policy": "CachedParentToWorld uses leading homogeneous column; UE translation is row_major[13:16]; Blender location is (Y,-X,Z)*unit_scale",
        "spot_direction_policy": "Spotlights aim along corrected native basis row2 converted to Blender space",
        "applied_native_lights": applied,
        "baked_lightmap_compensation": {
            "reason": "MP_Gridlock exposes 712 native LightMapTexture2D exports; Blender scene does not yet bind UE3 baked lightmaps to surfaces, so these fill lights preserve game-like illumination instead of leaving the map dark.",
            "lights": compensation,
        },
        "fog": fog,
        "render_config": render_config,
        "render": render_result,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "light_objects": sum(1 for obj in bpy.data.objects if obj.type == "LIGHT"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "direct_scene_root_objects": len(bpy.context.scene.collection.objects),
        },
    }
    write_json(Path(args.proof_out), proof)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
