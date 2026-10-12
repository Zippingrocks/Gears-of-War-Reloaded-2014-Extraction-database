#!/usr/bin/env python3
"""Repair MP_Gridlock skybox after the placeholder/visible-shell passes.

This pass fixes two mistakes:
1. The visible-shell pass scaled the source skydome down, which made it visible
   but distorted the background like a nearby prop.
2. The exported MTL/binding cache classified the skydome mask as diffuse, so a
   naive material uses the mask instead of the real sky textures.

The repair restores the native skydome transform, extends Blender clipping, and
builds a conservative UE3-style sky material from the decoded bg/sphere/mask
textures using normalized native UV payload layers.
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
TEXTURE_CACHE = MAP_ROOT / "Material_Texture_Cache"
SCENE_DIR = MAP_ROOT / "Blender_Scene_2026_08_12"
DEFAULT_PROOF = SCENE_DIR / "gridlock_skybox_game_accurate_repair_2026_08_14.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_skybox_game_accurate_repair_2026_08_14.png"

ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
SKYBOX_MATERIAL = "MAT__SkyDomes__skydome_gridlock_bg_01__UE3GraphApprox"
SOURCE_MATERIAL = "SkyDomes.skydome_gridlock_bg_01_MAT"
UV0_LAYER_CANDIDATES = ("UV0_Source_UE3StaticVertex", "UV0_Source_UE3", "UV_Source_Render")
UV1_LAYER_CANDIDATES = ("UV1_Source_UE3", "UV_Source_Lightmap", "UV_Float_Offset0")


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-cache", default=str(TEXTURE_CACHE))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
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


def matrix_rows(matrix: Matrix) -> list[list[float]]:
    return [[round(float(value), 8) for value in row] for row in matrix]


def sky_objects() -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for obj in bpy.data.objects:
        lower = (obj.name + " " + str(obj.get("ue_static_mesh_path") or "")).lower()
        if obj.type == "MESH" and ("skydome_gridlock_bg_01" in lower or "skydomes.skydome_gridlock" in lower):
            result.append(obj)
    return result


def choose_uv(mesh: bpy.types.Mesh, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if mesh.uv_layers.get(name):
            return name
    return mesh.uv_layers[0].name if mesh.uv_layers else ""


def uv_stats(mesh: bpy.types.Mesh, layer_name: str) -> dict[str, Any]:
    layer = mesh.uv_layers.get(layer_name)
    if not layer:
        return {"layer": layer_name, "exists": False}
    us = [float(data.uv.x) for data in layer.data]
    vs = [float(data.uv.y) for data in layer.data]
    return {
        "layer": layer_name,
        "exists": True,
        "count": len(layer.data),
        "u_min": round(min(us), 8),
        "u_max": round(max(us), 8),
        "v_min": round(min(vs), 8),
        "v_max": round(max(vs), 8),
        "outside_0_1": sum(1 for u, v in zip(us, vs) if u < -1e-5 or u > 1.00001 or v < -1e-5 or v > 1.00001),
    }


def find_textures(texture_cache: Path) -> dict[str, dict[str, str]]:
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


def node_image(nodes: bpy.types.Nodes, name: str, image: bpy.types.Image | None, location: tuple[int, int]) -> bpy.types.Node:
    node = nodes.new(type="ShaderNodeTexImage")
    node.name = name
    node.label = name
    node.location = location
    node.extension = "REPEAT"
    if image:
        node.image = image
    return node


def node_uv(nodes: bpy.types.Nodes, layer: str, location: tuple[int, int]) -> bpy.types.Node | None:
    if not layer:
        return None
    node = nodes.new(type="ShaderNodeUVMap")
    node.name = f"UV__{layer}"
    node.label = layer
    node.location = location
    node.uv_map = layer
    return node


def make_sky_material(textures: dict[str, dict[str, str]], uv0: str, uv1: str) -> dict[str, Any]:
    bg_image = load_image(textures.get("background", {}).get("dds_path", ""))
    sphere_image = load_image(textures.get("sphere", {}).get("dds_path", ""))
    mask_image = load_image(textures.get("mask", {}).get("dds_path", ""), "Non-Color")

    material = bpy.data.materials.get(SKYBOX_MATERIAL) or bpy.data.materials.new(SKYBOX_MATERIAL)
    material.use_nodes = True
    material.diffuse_color = (0.36, 0.43, 0.49, 1.0)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    set_enum_value(material, "blend_method", ["OPAQUE"])
    set_enum_value(material, "surface_render_method", ["DITHERED", "OPAQUE"])

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (770, 0)
    emission = nodes.new(type="ShaderNodeEmission")
    emission.location = (540, 0)
    if "Strength" in emission.inputs:
        emission.inputs["Strength"].default_value = 0.82
    links.new(emission.outputs["Emission"], out.inputs["Surface"])

    uv0_node = node_uv(nodes, uv0, (-760, 130))
    uv1_node = node_uv(nodes, uv1 or uv0, (-760, -90))
    bg = node_image(nodes, "Sky_BG_01_Delta", bg_image, (-510, 125))
    sphere = node_image(nodes, "Sky_BG_Sphere_01_Delta", sphere_image, (-510, -95))
    mask = node_image(nodes, "Sky_Masks_01_Delta", mask_image, (-510, -315))
    if uv0_node:
        links.new(uv0_node.outputs["UV"], bg.inputs["Vector"])
        links.new(uv0_node.outputs["UV"], mask.inputs["Vector"])
    if uv1_node:
        links.new(uv1_node.outputs["UV"], sphere.inputs["Vector"])

    separate = nodes.new(type="ShaderNodeSeparateColor")
    separate.location = (-255, -315)
    links.new(mask.outputs["Color"], separate.inputs["Color"])

    mix = nodes.new(type="ShaderNodeMix")
    mix.location = (30, 35)
    try:
        mix.data_type = "RGBA"
        mix.factor_mode = "UNIFORM"
    except Exception:
        pass
    # Green channel is the strongest sky-region mask in the decoded texture.
    if "Factor" in mix.inputs:
        links.new(separate.outputs["Green"], mix.inputs["Factor"])
    color_a = mix.inputs.get("A") or mix.inputs.get("Color A")
    color_b = mix.inputs.get("B") or mix.inputs.get("Color B")
    if color_a:
        links.new(bg.outputs["Color"], color_a)
    if color_b:
        links.new(sphere.outputs["Color"], color_b)

    desat = nodes.new(type="ShaderNodeHueSaturation")
    desat.location = (295, 35)
    if "Saturation" in desat.inputs:
        desat.inputs["Saturation"].default_value = 0.88
    if "Value" in desat.inputs:
        desat.inputs["Value"].default_value = 0.82
    mix_output = mix.outputs.get("Result") or mix.outputs.get("Color")
    if mix_output:
        links.new(mix_output, desat.inputs["Color"])
    links.new(desat.outputs["Color"], emission.inputs["Color"])

    material["gridlock_skybox_repair"] = "native_transform_ue3_graph_approx"
    material["gridlock_source_material_path"] = SOURCE_MATERIAL
    material["gridlock_material_graph_evidence"] = (
        "Native graph has bg/sphere/mask texture samples, texture coords, component masks, lerps, "
        "multiplies, desaturation, and constants. Blender material approximates that with "
        "BG(UV0), Sphere(UV1), mask-green lerp, desaturation/value trim, emission."
    )
    material["gridlock_uv0_layer"] = uv0
    material["gridlock_uv1_layer"] = uv1
    material["gridlock_bg_texture"] = textures.get("background", {}).get("dds_path", "")
    material["gridlock_sphere_texture"] = textures.get("sphere", {}).get("dds_path", "")
    material["gridlock_mask_texture"] = textures.get("mask", {}).get("dds_path", "")
    return {
        "material": material.name,
        "uv0_layer": uv0,
        "uv1_layer": uv1,
        "bg_loaded": bool(bg_image),
        "sphere_loaded": bool(sphere_image),
        "mask_loaded": bool(mask_image),
        "bg_texture": material["gridlock_bg_texture"],
        "sphere_texture": material["gridlock_sphere_texture"],
        "mask_texture": material["gridlock_mask_texture"],
    }


def restore_native_transform(obj: bpy.types.Object) -> dict[str, Any]:
    before = {
        "location": vec3(obj.location),
        "rotation_euler": vec3(obj.rotation_euler),
        "scale": vec3(obj.scale),
        "dimensions": vec3(obj.dimensions),
        "matrix_world": matrix_rows(obj.matrix_world),
    }
    matrix_text = obj.get("gridlock_skybox_original_matrix_world_before_visible_fit", "")
    restored = False
    if matrix_text:
        try:
            rows = json.loads(str(matrix_text))
            obj.matrix_world = Matrix(rows)
            restored = True
        except Exception as exc:
            obj["gridlock_skybox_native_restore_error"] = str(exc)
    else:
        loc_text = obj.get("gridlock_skybox_original_location_before_visible_fit", "")
        scale_text = obj.get("gridlock_skybox_original_scale_before_visible_fit", "")
        if loc_text and scale_text:
            obj.location = Vector(json.loads(str(loc_text)))
            obj.scale = Vector(json.loads(str(scale_text)))
            restored = True
    bpy.context.view_layer.update()
    obj["gridlock_skybox_repair"] = "native_transform_restored_after_bad_visible_fit"
    obj["gridlock_skybox_bad_fit_transform_before_repair"] = json.dumps(before, ensure_ascii=True)
    obj["gridlock_skybox_transform_policy"] = "Use decoded native collection matrix; visibility handled via clip distances, not dome rescaling."
    after = {
        "location": vec3(obj.location),
        "rotation_euler": vec3(obj.rotation_euler),
        "scale": vec3(obj.scale),
        "dimensions": vec3(obj.dimensions),
        "matrix_world": matrix_rows(obj.matrix_world),
    }
    return {"object": obj.name, "restored_from_saved_native_matrix": restored, "before": before, "after": after}


def configure_world_and_clip() -> dict[str, Any]:
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    world.color = (0.018, 0.022, 0.027)
    nodes = world.node_tree.nodes
    nodes.clear()
    out = nodes.new(type="ShaderNodeOutputWorld")
    bg = nodes.new(type="ShaderNodeBackground")
    bg.location = (-220, 0)
    out.location = (0, 0)
    bg.inputs["Color"].default_value = (0.018, 0.022, 0.027, 1.0)
    bg.inputs["Strength"].default_value = 0.08
    world.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    world["gridlock_skybox_repair"] = "solid dark world; visible sky supplied by decoded skydome mesh, not environment texture hack"

    camera_clip = []
    for camera in bpy.data.cameras:
        camera.clip_start = 0.05
        camera.clip_end = max(float(camera.clip_end), 150000.0)
        camera_clip.append({"camera": camera.name, "clip_end": camera.clip_end})

    view_clip_updated = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.clip_start = 0.05
                space.clip_end = max(float(space.clip_end), 150000.0)
                view_clip_updated += 1

    return {
        "world_policy": "decoded skydome object renders the sky; world only prevents black fallback",
        "camera_clip": camera_clip,
        "view_3d_spaces_clip_updated": view_clip_updated,
    }


def render_still(path: Path) -> dict[str, Any]:
    ensure_dir(path)
    scene = bpy.context.scene
    scene.render.filepath = str(path)
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
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
    objects = sky_objects()
    textures = find_textures(texture_cache)
    object_rows = []
    material_summary: dict[str, Any] = {}
    if objects:
        mesh = objects[0].data
        uv0 = choose_uv(mesh, UV0_LAYER_CANDIDATES)
        uv1 = choose_uv(mesh, UV1_LAYER_CANDIDATES)
        material_summary = make_sky_material(textures, uv0, uv1)
        material = bpy.data.materials[material_summary["material"]]
        for obj in objects:
            link_object(sky_collection, obj)
            unlink_from_scene_root(obj)
            transform_row = restore_native_transform(obj)
            obj.data.materials.clear()
            obj.data.materials.append(material)
            obj.hide_viewport = False
            obj.hide_render = False
            obj.show_in_front = False
            safe_setattr(obj, "visible_shadow", False)
            obj["gridlock_skybox_material_policy"] = "UE3 graph approximation using BG/Sphere/Mask textures; mask is not treated as diffuse."
            object_rows.append(
                {
                    **transform_row,
                    "uv_stats": {
                        "bad_uv0_layer": uv_stats(obj.data, "UV0"),
                        "chosen_uv0": uv_stats(obj.data, uv0),
                        "chosen_uv1": uv_stats(obj.data, uv1),
                    },
                }
            )

    env_summary = configure_world_and_clip()
    scene = bpy.context.scene
    scene["gridlock_skybox_repair"] = "native_transform_and_ue3_graph_approx_applied"
    scene["gridlock_skybox_status"] = "native scale restored; bg/sphere/mask graph approx; viewport/camera clipping extended"
    scene["gridlock_skybox_proof"] = str(proof_out)

    render_summary = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_summary = render_still(render_out)

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_skybox_game_accurate_repair_applied",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "source_material": SOURCE_MATERIAL,
        "problem_fixed": [
            "removed fitted tiny skydome shell distortion by restoring decoded native matrix",
            "stopped using SkyDomes.skydome_gridlock_masks_01_Delta_Tex as diffuse/base sky",
            "uses normalized UE3 UV payload layers instead of broken imported UV0",
            "extended Blender camera and viewport clipping so native-scale sky remains visible",
        ],
        "textures": textures,
        "material": material_summary,
        "sky_objects": object_rows,
        "environment": env_summary,
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
