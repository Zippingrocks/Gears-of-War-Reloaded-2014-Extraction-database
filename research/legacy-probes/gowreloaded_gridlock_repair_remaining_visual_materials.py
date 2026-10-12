#!/usr/bin/env python3
"""Repair remaining Gridlock visual-material buckets.

This pass does not claim source-native BSP material binding. It gives the
remaining visible placeholder/approximation classes proper PNG-backed Blender
materials so they render cleanly and are auditable instead of showing as flat
debug colors/no-image materials.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Callable

import bpy  # type: ignore


BSP_MATERIAL = "DECODED_BSP_Model_NativeFaces_NoBSPTextureBindingYet"
WINDOWPANE_MATERIAL = "Delta_Window_Hitmeshes01.windowpane_hitmesh_Delta_MAT"
GODRAY_MATERIAL = "FX_Nature_Delta.Materials.godray_01_Delta_MAT"
WATER_MATERIAL = "MAT_MP_Gridlock_Water_Decoded_Approx"
WATER_SPRAY_MATERIAL = "MAT_MP_Gridlock_WaterSpray_Marker"
FLOOR_PUDDLE_MATERIAL = "MAT_MP_Gridlock_Floor_Puddle_VertexColor_Approx"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, pixel: Callable[[int, int], tuple[int, int, int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(pixel(x, y))
        rows.append(bytes(row))
    data = b"".join(rows)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(data, 9))
        + png_chunk(b"IEND", b"")
    )
    if not path.exists() or path.read_bytes() != payload:
        path.write_bytes(payload)


def hash_noise(x: int, y: int, seed: int) -> float:
    value = (x * 374761393 + y * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFF) / 65535.0


def make_bsp_pixel(x: int, y: int) -> tuple[int, int, int, int]:
    n = hash_noise(x, y, 31)
    crack = 1.0 if abs(((x * 3 + y * 7) % 83) - 41) < 1.2 or abs(((x * 11 - y * 5) % 109) - 54) < 0.9 else 0.0
    stain = 0.5 + 0.5 * math.sin(x * 0.17) * math.cos(y * 0.09)
    base = 96 + 34 * n + 18 * stain - 46 * crack
    return (clamp_byte(base * 0.92), clamp_byte(base * 0.90), clamp_byte(base * 0.84), 255)


def make_glass_pixel(x: int, y: int) -> tuple[int, int, int, int]:
    streak = 0.55 + 0.45 * math.sin(x * 0.31 + math.sin(y * 0.08) * 2.0)
    grime = hash_noise(x // 2, y // 3, 72)
    alpha = 72 + 48 * streak + 28 * grime
    return (clamp_byte(84 + 18 * streak), clamp_byte(112 + 28 * streak), clamp_byte(125 + 32 * streak), clamp_byte(alpha))


def make_godray_pixel(x: int, y: int) -> tuple[int, int, int, int]:
    cx = abs((x + 0.5) / 96.0 - 0.5) * 2.0
    fade_x = max(0.0, 1.0 - cx**1.8)
    fade_y = max(0.0, 1.0 - y / 191.0)
    dust = 0.65 + 0.35 * hash_noise(x, y, 19)
    alpha = 145 * fade_x * fade_y * dust
    return (198, 188, 150, clamp_byte(alpha))


def make_water_pixel(x: int, y: int) -> tuple[int, int, int, int]:
    wave_a = math.sin((x + y * 0.45) * 0.23)
    wave_b = math.sin((x * 0.24 - y * 0.18) + math.sin(y * 0.06))
    foam = max(0.0, wave_a * 0.5 + wave_b * 0.5 - 0.62)
    n = hash_noise(x, y, 95)
    return (
        clamp_byte(34 + 30 * foam + 10 * n),
        clamp_byte(86 + 46 * foam + 18 * n),
        clamp_byte(96 + 58 * foam + 22 * n),
        clamp_byte(150 + 42 * foam),
    )


def make_spray_pixel(x: int, y: int) -> tuple[int, int, int, int]:
    dx = (x + 0.5) / 128.0 - 0.5
    dy = (y + 0.5) / 128.0 - 0.5
    radius = math.sqrt(dx * dx + dy * dy)
    mist = max(0.0, 1.0 - radius * 2.15)
    streak = max(0.0, math.sin((x * 0.19 + y * 0.41)) * 0.5 + 0.5)
    alpha = 180 * (mist**1.65) * (0.72 + 0.28 * streak)
    return (184, 221, 229, clamp_byte(alpha))


def make_puddle_pixel(x: int, y: int) -> tuple[int, int, int, int]:
    ripple = 0.5 + 0.5 * math.sin(x * 0.18 + math.sin(y * 0.07) * 2.8)
    oil = 0.5 + 0.5 * math.sin(x * 0.055 + y * 0.13)
    n = hash_noise(x, y, 117)
    return (
        clamp_byte(38 + 16 * ripple + 18 * oil),
        clamp_byte(47 + 22 * ripple + 14 * n),
        clamp_byte(45 + 18 * ripple + 22 * oil),
        clamp_byte(178 + 42 * ripple),
    )


def ensure_textures(asset_dir: Path) -> dict[str, Path]:
    texture_dir = asset_dir / "remaining_visual_material_textures"
    specs = {
        "bsp": ("gridlock_bsp_concrete_review_overlay.png", 128, 128, make_bsp_pixel),
        "glass": ("gridlock_windowpane_smoky_glass_overlay.png", 96, 96, make_glass_pixel),
        "godray": ("gridlock_godray_soft_alpha_overlay.png", 96, 192, make_godray_pixel),
        "water": ("gridlock_water_wave_overlay.png", 128, 128, make_water_pixel),
        "spray": ("gridlock_water_spray_mist_overlay.png", 128, 128, make_spray_pixel),
        "puddle": ("gridlock_floor_puddle_oily_overlay.png", 128, 128, make_puddle_pixel),
    }
    out: dict[str, Path] = {}
    for key, (name, width, height, func) in specs.items():
        path = texture_dir / name
        write_png(path, width, height, func)
        out[key] = path
    return out


def clear_nodes(nodes: bpy.types.Nodes) -> None:
    for node in list(nodes):
        nodes.remove(node)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_input(bsdf: bpy.types.Node, names: tuple[str, ...], value: Any) -> None:
    socket = principled_input(bsdf, names)
    if socket is not None:
        socket.default_value = value


def load_image(path: Path) -> bpy.types.Image:
    abs_path = str(path.resolve(strict=False))
    for image in bpy.data.images:
        if bpy.path.abspath(image.filepath) == abs_path:
            return image
    image = bpy.data.images.load(abs_path)
    image.filepath = abs_path
    try:
        image.alpha_mode = "STRAIGHT"
    except Exception:
        pass
    return image


def material_object_count(material_name: str) -> int:
    count = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if any(slot.material and slot.material.name == material_name for slot in obj.material_slots):
            count += 1
    return count


def is_visible_final(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    return all(not coll.hide_viewport and not coll.hide_render for coll in obj.users_collection)


def visible_object_count(material_name: str) -> int:
    count = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not is_visible_final(obj):
            continue
        if any(slot.material and slot.material.name == material_name for slot in obj.material_slots):
            count += 1
    return count


def make_texture_material(
    name: str,
    image_path: Path,
    diffuse: tuple[float, float, float, float],
    alpha: float,
    style: str,
    source_status: str,
) -> dict[str, Any]:
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.diffuse_color = diffuse
    material.use_nodes = True
    material["gridlock_remaining_visual_repair"] = style
    material["source_binding_status"] = source_status
    material["viewport_png_alias"] = str(image_path.resolve(strict=False))
    material["visual_texture_role"] = "approximation_overlay_png"
    try:
        material.blend_method = "BLEND" if alpha < 1.0 else "OPAQUE"
    except Exception:
        pass
    try:
        material.surface_render_method = "BLENDED" if alpha < 1.0 else "DITHERED"
    except Exception:
        pass
    try:
        material.show_transparent_back = True
    except Exception:
        pass
    try:
        material.use_screen_refraction = style in {"windowpane", "water", "puddle"}
    except Exception:
        pass

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    clear_nodes(nodes)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (430, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (140, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-760, 75)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-565, 70)
    image = nodes.new("ShaderNodeTexImage")
    image.location = (-345, 72)
    image.image = load_image(image_path)
    try:
        image.extension = "CLIP" if style in {"godray", "spray"} else "REPEAT"
    except Exception:
        pass
    links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], image.inputs["Vector"])
    base_socket = principled_input(bsdf, ("Base Color",))
    alpha_socket = principled_input(bsdf, ("Alpha",))
    if base_socket is not None:
        links.new(image.outputs["Color"], base_socket)
    if alpha_socket is not None and alpha < 1.0 and "Alpha" in image.outputs:
        links.new(image.outputs["Alpha"], alpha_socket)
    set_input(bsdf, ("Alpha",), alpha)
    set_input(bsdf, ("Metallic",), 0.0)

    if style == "bsp":
        set_input(bsdf, ("Roughness",), 0.86)
        bump = nodes.new("ShaderNodeBump")
        bump.location = (-55, -260)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-335, -245)
        noise.inputs["Scale"].default_value = 38.0
        noise.inputs["Detail"].default_value = 7.0
        noise.inputs["Roughness"].default_value = 0.58
        bump.inputs["Strength"].default_value = 0.055
        bump.inputs["Distance"].default_value = 0.06
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        normal_socket = principled_input(bsdf, ("Normal",))
        if normal_socket is not None:
            links.new(bump.outputs["Normal"], normal_socket)
    elif style == "windowpane":
        set_input(bsdf, ("Roughness",), 0.18)
        set_input(bsdf, ("Specular IOR Level", "Specular"), 0.82)
        set_input(bsdf, ("Transmission Weight", "Transmission"), 0.18)
    elif style == "godray":
        set_input(bsdf, ("Roughness",), 0.35)
        set_input(bsdf, ("Emission Color",), (0.78, 0.70, 0.48, 1.0))
        set_input(bsdf, ("Emission Strength",), 1.35)
    elif style == "water":
        set_input(bsdf, ("Roughness",), 0.08)
        set_input(bsdf, ("Specular IOR Level", "Specular"), 0.96)
        set_input(bsdf, ("Transmission Weight", "Transmission"), 0.26)
        set_input(bsdf, ("Alpha",), alpha)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-335, -250)
        noise.inputs["Scale"].default_value = 54.0
        noise.inputs["Detail"].default_value = 12.0
        noise.inputs["Roughness"].default_value = 0.52
        bump = nodes.new("ShaderNodeBump")
        bump.location = (-55, -250)
        bump.inputs["Strength"].default_value = 0.075
        bump.inputs["Distance"].default_value = 0.045
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        normal_socket = principled_input(bsdf, ("Normal",))
        if normal_socket is not None:
            links.new(bump.outputs["Normal"], normal_socket)
        location_socket = mapping.inputs.get("Location")
        if location_socket is not None:
            location_socket.default_value[0] = 0.0
            location_socket.default_value[1] = 0.0
            location_socket.keyframe_insert("default_value", frame=1)
            location_socket.default_value[0] = 0.85
            location_socket.default_value[1] = -0.32
            location_socket.keyframe_insert("default_value", frame=180)
            material["animated_preview"] = "mapping drift keyframed frames 1-180 for water motion"
    elif style == "spray":
        set_input(bsdf, ("Roughness",), 0.22)
        set_input(bsdf, ("Emission Color",), (0.50, 0.72, 0.78, 1.0))
        set_input(bsdf, ("Emission Strength",), 0.45)
    elif style == "puddle":
        set_input(bsdf, ("Roughness",), 0.04)
        set_input(bsdf, ("Specular IOR Level", "Specular"), 0.98)
        set_input(bsdf, ("Coat Weight", "Clearcoat"), 0.45)
        set_input(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.08)

    return {
        "material": material.name,
        "texture": str(image_path.resolve(strict=False)),
        "style": style,
        "source_binding_status": source_status,
        "visible_objects_using_material": visible_object_count(name),
        "total_objects_using_material": material_object_count(name),
        "image_nodes": sum(1 for node in nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)),
    }


def main() -> int:
    args = parse_args()
    asset_dir = Path(args.asset_dir)
    proof_out = Path(args.proof_out)
    textures = ensure_textures(asset_dir)
    repairs = [
        make_texture_material(
            BSP_MATERIAL,
            textures["bsp"],
            (0.43, 0.41, 0.35, 1.0),
            1.0,
            "bsp",
            "native_bsp_geometry_decoded_but_face_uv_material_binding_not_yet_decoded",
        ),
        make_texture_material(
            WINDOWPANE_MATERIAL,
            textures["glass"],
            (0.26, 0.38, 0.44, 0.34),
            0.34,
            "windowpane",
            "source_material_path_known_no_decoded_texture_binding_visual_glass_overlay",
        ),
        make_texture_material(
            GODRAY_MATERIAL,
            textures["godray"],
            (0.74, 0.68, 0.47, 0.30),
            0.30,
            "godray",
            "source_material_path_known_effect_material_approximated_with_alpha_overlay",
        ),
        make_texture_material(
            WATER_MATERIAL,
            textures["water"],
            (0.07, 0.16, 0.18, 0.58),
            0.58,
            "water",
            "decoded_water_geometry_with_visual_wave_overlay_and_animated_mapping",
        ),
        make_texture_material(
            WATER_SPRAY_MATERIAL,
            textures["spray"],
            (0.65, 0.82, 0.90, 0.62),
            0.62,
            "spray",
            "particle_emitter_marker_visualized_with_alpha_mist_overlay",
        ),
        make_texture_material(
            FLOOR_PUDDLE_MATERIAL,
            textures["puddle"],
            (0.12, 0.15, 0.13, 0.64),
            0.64,
            "puddle",
            "floor_puddle_visual_approximation_with_png_overlay",
        ),
    ]

    bpy.context.scene.frame_start = min(int(bpy.context.scene.frame_start or 1), 1)
    bpy.context.scene.frame_end = max(int(bpy.context.scene.frame_end or 1), 180)
    bpy.context.scene["gridlock_remaining_visual_materials_repair"] = "PNG-backed shaders applied to BSP/windowpane/godray/water/spray/puddle buckets"
    bpy.context.scene["gridlock_remaining_visual_materials_repair_proof"] = str(proof_out)

    proof = {
        "blend_path": bpy.data.filepath,
        "asset_dir": str(asset_dir),
        "textures": {key: str(path.resolve(strict=False)) for key, path in textures.items()},
        "repairs": repairs,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
        "status": "gridlock_remaining_visual_material_buckets_repaired",
    }
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
