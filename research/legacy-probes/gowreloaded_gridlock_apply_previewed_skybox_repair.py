#!/usr/bin/env python3
"""Apply a previewed, robust Gridlock skybox repair.

The native Reloaded skydome mesh and material evidence are preserved, but the
visible Blender sky is driven by a clean equirectangular game-view backdrop
using the decoded Reloaded Gridlock sky texture. This avoids the broken
mask-as-diffuse path and the currently incomplete UE3 material graph decode.
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
SCENE_DIR = MAP_ROOT / "Blender_Scene_2026_08_12"
TEXTURE_CACHE = MAP_ROOT / "Material_Texture_Cache"
VIS_PREVIEW_DIR = Path(
    r"C:\Users\Bilbo\.codex\visualizations\2026\06\28\019f0bba-7647-7e82-9b57-7c1574085478"
)

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
SKY_COLLECTION = "Skybox"
BACKDROP_OBJECT = "SKYBOX_MP_Gridlock_GameView_Backdrop_Equirect"
BACKDROP_MATERIAL = "MAT__SkyDomes__skydome_gridlock_bg_01__GameView_Equirect"
NATIVE_PRESERVED_COLLECTION = "Decoded_Native_Skydome_Preserved"
DEFAULT_PROOF = SCENE_DIR / "gridlock_skybox_previewed_repair_2026_08_14.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_skybox_previewed_repair_2026_08_14.png"
DEFAULT_PREVIEW_COPY = VIS_PREVIEW_DIR / "gridlock_skybox_preview_latest.png"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-cache", default=str(TEXTURE_CACHE))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW_COPY))
    parser.add_argument("--render-proof", action="store_true")
    return parser.parse_args(argv)


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
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


def vec3(values: Vector | tuple[float, float, float] | list[float]) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def visible_mesh_for_bounds(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
        return False
    lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
    skip = ("skydome", "skybox", "fog_mp_gridlock", "atmosphere")
    return not any(token in lower for token in skip)


def scene_bounds() -> dict[str, Any]:
    meshes = [obj for obj in bpy.data.objects if visible_mesh_for_bounds(obj)]
    if not meshes:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0], "radius": 2500.0}
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
    extents = maxs - mins
    radius = max(float(extents.x), float(extents.y), float(extents.z), 1.0) * 0.5
    return {"min": vec3(mins), "max": vec3(maxs), "center": vec3(center), "radius": round(radius, 6)}


def find_sky_textures(texture_cache: Path) -> dict[str, dict[str, str]]:
    manifest = texture_cache / "gowreloaded_mp_gridlock_material_texture_export_manifest.csv"
    wanted = {
        "background": "skydome_gridlock_bg_01_delta_tex",
        "sphere": "skydome_gridlock_bg_sphere_01_delta_tex",
        "mask": "skydome_gridlock_masks_01_delta_tex",
    }
    rows: dict[str, dict[str, str]] = {}
    for row in read_csv(manifest):
        key = str(row.get("texture_key") or "").lower()
        dds = row.get("dds_path") or ""
        if not dds or not Path(dds).exists():
            continue
        for role, token in wanted.items():
            if role not in rows and token in key:
                rows[role] = {
                    "key": key,
                    "dds_path": dds,
                    "width": row.get("width", ""),
                    "height": row.get("height", ""),
                    "pixel_format": row.get("pixel_format", ""),
                }
    if rows:
        return rows
    for path in (texture_cache / "textures_dds").glob("*skydome_gridlock*.dds"):
        lower = path.name.lower()
        role = "background" if "bg_01_delta" in lower else "sphere" if "bg_sphere" in lower else "mask" if "masks" in lower else ""
        if role:
            rows[role] = {"key": path.stem.lower(), "dds_path": str(path), "width": "", "height": "", "pixel_format": ""}
    return rows


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


def make_equirect_material(textures: dict[str, dict[str, str]]) -> dict[str, Any]:
    bg_path = textures.get("background", {}).get("dds_path", "")
    bg_image = load_image(bg_path)
    material = bpy.data.materials.get(BACKDROP_MATERIAL) or bpy.data.materials.new(BACKDROP_MATERIAL)
    material.use_nodes = True
    material.diffuse_color = (0.28, 0.36, 0.44, 1.0)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (560, 0)
    emission = nodes.new(type="ShaderNodeEmission")
    emission.location = (325, 0)
    if "Strength" in emission.inputs:
        emission.inputs["Strength"].default_value = 0.78
    if "Color" in emission.inputs:
        emission.inputs["Color"].default_value = (0.28, 0.36, 0.44, 1.0)
    links.new(emission.outputs["Emission"], out.inputs["Surface"])

    if bg_image:
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.name = "Reloaded_Gridlock_BG_01_Equirect"
        tex.label = "Reloaded Gridlock BG 01"
        tex.location = (-160, 60)
        tex.image = bg_image
        tex.extension = "REPEAT"
        uv = nodes.new(type="ShaderNodeUVMap")
        uv.location = (-390, 60)
        uv.uv_map = "UVMap"
        hue = nodes.new(type="ShaderNodeHueSaturation")
        hue.location = (95, 60)
        if "Saturation" in hue.inputs:
            hue.inputs["Saturation"].default_value = 0.92
        if "Value" in hue.inputs:
            hue.inputs["Value"].default_value = 0.74
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], hue.inputs["Color"])
        links.new(hue.outputs["Color"], emission.inputs["Color"])

    material["gridlock_skybox_repair"] = "game_view_equirect_backdrop"
    material["gridlock_source_texture"] = bg_path
    material["gridlock_source_material_family"] = "SkyDomes.skydome_gridlock_bg_01_MAT / decoded Reloaded Gridlock sky texture family"
    material["gridlock_reason"] = "Use the 2048x1024 Reloaded BG texture as a stable equirectangular Blender sky; preserve native skydome separately until exact UE3 material graph is decoded."
    return {"material": material.name, "bg_texture": bg_path, "bg_loaded": bool(bg_image)}


def preserve_native_skydome(root: bpy.types.Collection) -> dict[str, Any]:
    sky = get_collection(SKY_COLLECTION, root)
    preserved = get_collection(NATIVE_PRESERVED_COLLECTION, sky)
    rows = []
    for obj in bpy.data.objects:
        lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
        if obj.type != "MESH" or "skydome_gridlock_bg_01" not in lower:
            continue
        if obj.name == BACKDROP_OBJECT:
            continue
        obj.hide_render = True
        obj.hide_viewport = True
        obj["gridlock_skybox_repair"] = "native decoded skydome preserved but hidden from game-view sky because exact UE3 material graph is not yet reconstructed"
        obj["gridlock_skybox_preservation_policy"] = "Do not delete; source-native transform/mesh/material evidence retained for later exact graph decode."
        link_object(preserved, obj)
        unlink_from_scene_root(obj)
        rows.append(
            {
                "object": obj.name,
                "mesh": obj.data.name,
                "hide_viewport": obj.hide_viewport,
                "hide_render": obj.hide_render,
                "location": vec3(obj.location),
                "scale": vec3(obj.scale),
                "dimensions": vec3(obj.dimensions),
            }
        )
    return {"native_skydomes_preserved_hidden": rows}


def make_backdrop(root: bpy.types.Collection, bounds: dict[str, Any], material_name: str) -> dict[str, Any]:
    sky = get_collection(SKY_COLLECTION, root)
    material = bpy.data.materials[material_name]
    existing = bpy.data.objects.get(BACKDROP_OBJECT)
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)

    center = Vector(bounds["center"])
    radius = max(float(bounds["radius"]) * 8.0, 32000.0)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=160, ring_count=80, radius=radius, location=center)
    obj = bpy.context.object
    obj.name = BACKDROP_OBJECT
    obj.data.name = BACKDROP_OBJECT + "_Mesh"
    obj.data.materials.append(material)
    obj.rotation_euler[2] = math.radians(188.0)
    obj.hide_render = False
    obj.hide_viewport = False
    obj.display_type = "TEXTURED"
    obj.show_name = False
    safe_setattr(obj, "visible_shadow", False)
    obj["gridlock_skybox_repair"] = "active_game_view_equirect_backdrop"
    obj["gridlock_source_texture"] = material.get("gridlock_source_texture", "")
    obj["gridlock_accuracy_note"] = "Visual reconstruction skybox using decoded Reloaded Gridlock sky texture; native skydome mesh preserved hidden until exact UE3 material graph decode."
    link_object(sky, obj)
    unlink_from_scene_root(obj)
    return {"backdrop_object": obj.name, "radius": round(radius, 6), "location": vec3(obj.location), "rotation_z_degrees": 188.0, "material": material.name}


def configure_world(textures: dict[str, dict[str, str]]) -> dict[str, Any]:
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputWorld")
    out.location = (260, 0)
    bg = nodes.new(type="ShaderNodeBackground")
    bg.location = (20, 0)
    bg.inputs["Color"].default_value = (0.018, 0.024, 0.030, 1.0)
    bg.inputs["Strength"].default_value = 0.12
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    image = load_image(textures.get("background", {}).get("dds_path", ""))
    status = "solid_fallback_world"
    if image:
        env = nodes.new(type="ShaderNodeTexEnvironment")
        env.location = (-255, 60)
        env.image = image
        hue = nodes.new(type="ShaderNodeHueSaturation")
        hue.location = (-80, 60)
        if "Saturation" in hue.inputs:
            hue.inputs["Saturation"].default_value = 0.90
        if "Value" in hue.inputs:
            hue.inputs["Value"].default_value = 0.35
        links.new(env.outputs["Color"], hue.inputs["Color"])
        links.new(hue.outputs["Color"], bg.inputs["Color"])
        status = "source_texture_environment_backup"
    world["gridlock_skybox_repair"] = status
    return {"world_status": status, "world_texture": textures.get("background", {}).get("dds_path", "")}


def configure_camera_and_render(bounds: dict[str, Any]) -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
        scene.view_settings.exposure = -0.08
        scene.view_settings.gamma = 1.0
    except Exception:
        pass

    center = Vector(bounds["center"])
    radius = max(float(bounds["radius"]), 2500.0)
    camera = bpy.data.objects.get("CAM_MP_Gridlock_Skybox_Preview")
    if camera is None:
        cam_data = bpy.data.cameras.new("CAM_MP_Gridlock_Skybox_Preview")
        camera = bpy.data.objects.new("CAM_MP_Gridlock_Skybox_Preview", cam_data)
        get_collection("Cameras", get_collection(ROOT_COLLECTION)).objects.link(camera)
    camera.location = center + Vector((-radius * 0.36, -radius * 0.54, radius * 0.22))
    target = center + Vector((radius * 0.04, radius * 0.05, radius * 0.18))
    direction = target - Vector(camera.location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 20
    camera.data.clip_start = 0.05
    camera.data.clip_end = 220000.0
    scene.camera = camera
    for cam in bpy.data.cameras:
        cam.clip_end = max(float(cam.clip_end), 220000.0)

    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.clip_start = 0.05
                space.clip_end = max(float(space.clip_end), 220000.0)

    return {"camera": camera.name, "location": vec3(camera.location), "target": vec3(target), "clip_end": camera.data.clip_end}


def render_still(path: Path) -> dict[str, Any]:
    ensure_dir(path)
    scene = bpy.context.scene
    scene.render.filepath = str(path)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        return {"render_path": str(path), "render_ok": False, "render_error": str(exc)}
    return {"render_path": str(path), "render_ok": path.exists() and path.stat().st_size > 0, "render_size": path.stat().st_size if path.exists() else 0}


def copy_preview(src: Path, dst: Path) -> dict[str, Any]:
    if not src.exists():
        return {"preview_copy": str(dst), "copied": False, "reason": "source render missing"}
    ensure_dir(dst)
    dst.write_bytes(src.read_bytes())
    return {"preview_copy": str(dst), "copied": True, "size": dst.stat().st_size}


def main() -> int:
    args = parse_args()
    root = get_collection(ROOT_COLLECTION)
    bounds = scene_bounds()
    textures = find_sky_textures(Path(args.texture_cache))
    material = make_equirect_material(textures)
    preserved = preserve_native_skydome(root)
    backdrop = make_backdrop(root, bounds, material["material"])
    world = configure_world(textures)
    camera = configure_camera_and_render(bounds)

    scene = bpy.context.scene
    scene["gridlock_skybox_status"] = "previewed_game_view_backdrop_active; native skydome preserved hidden"
    scene["gridlock_skybox_preview_path"] = str(args.preview_copy)
    scene["gridlock_skybox_repair"] = "previewed_equirect_backdrop_from_decoded_reloaded_texture"

    render_summary = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_summary = render_still(Path(args.render_out))
        render_summary.update(copy_preview(Path(args.render_out), Path(args.preview_copy)))

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "previewed_skybox_repair_applied",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "reason": "Native skydome material graph is still incomplete in Blender; active sky is a game-view equirectangular backdrop from decoded Reloaded Gridlock sky texture, with native skydome preserved for future exact graph decode.",
        "scene_bounds": bounds,
        "textures": textures,
        "material": material,
        "preserved_native": preserved,
        "active_backdrop": backdrop,
        "world": world,
        "camera": camera,
        "render": render_summary,
        "counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "light_objects": sum(1 for obj in bpy.data.objects if obj.type == "LIGHT"),
            "direct_scene_root_objects": len(bpy.context.scene.collection.objects),
        },
    }
    proof_out = Path(args.proof_out)
    ensure_dir(proof_out)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
