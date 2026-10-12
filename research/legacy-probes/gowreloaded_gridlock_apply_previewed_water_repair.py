#!/usr/bin/env python3
"""Apply a previewed Gridlock water visual repair.

This pass keeps the decoded Reloaded water mesh placements intact and replaces
the old generated-overlay water look with a Blender material driven by the
source-native Gridlock water DDS textures that are currently decoded.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import struct
import sys
import zlib
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
WATER_COLLECTION = "Water"
WATER_VIS_COLLECTION = "Water_GameView_Visuals"
SPRAY_VIS_COLLECTION = "WaterSpray_GameView_Billboards"

OCEAN_MATERIAL = "MAT__FX_MP_GridlockWater__Ocean_Gridlock_GameView"
PUDDLE_MATERIAL = "MAT__MP_Gridlock__FloorPuddle_GameView"
SPRAY_MATERIAL = "MAT__FX_MP_GridlockWater__WallSprayMist_GameView"

DEFAULT_PROOF = SCENE_DIR / "gridlock_water_gameview_repair_2026_08_14.json"
DEFAULT_RENDER = SCENE_DIR / "gridlock_water_gameview_repair_2026_08_14.png"
DEFAULT_PREVIEW_COPY = VIS_PREVIEW_DIR / "gridlock_water_preview_latest.png"

DDS_FALLBACKS: list[dict[str, Any]] = []


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-cache", default=str(TEXTURE_CACHE))
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--render-out", default=str(DEFAULT_RENDER))
    parser.add_argument("--preview-copy", default=str(DEFAULT_PREVIEW_COPY))
    parser.add_argument("--render-proof", action="store_true")
    return parser.parse_args(argv)


def ensure_parent(path: Path) -> None:
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



def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png_rgba(path: Path, width: int, height: int, rgba: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    stride = width * 4
    for y in range(height):
        rows.append(b"\x00" + rgba[y * stride : (y + 1) * stride])
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + png_chunk(b"IEND", b"")
    )
    if not path.exists() or path.read_bytes() != payload:
        path.write_bytes(payload)


def rgb565(value: int) -> tuple[int, int, int]:
    r = ((value >> 11) & 31) * 255 // 31
    g = ((value >> 5) & 63) * 255 // 63
    b = (value & 31) * 255 // 31
    return r, g, b


def blend_rgb(a: tuple[int, int, int], b: tuple[int, int, int], aw: int, bw: int, div: int) -> tuple[int, int, int]:
    return (
        (a[0] * aw + b[0] * bw) // div,
        (a[1] * aw + b[1] * bw) // div,
        (a[2] * aw + b[2] * bw) // div,
    )


def decode_color_block(block: bytes, force_four_color: bool) -> list[tuple[int, int, int, int]]:
    c0, c1, _bits = struct.unpack_from("<HHI", block, 0)
    p0 = rgb565(c0)
    p1 = rgb565(c1)
    if force_four_color or c0 > c1:
        return [(*p0, 255), (*p1, 255), (*blend_rgb(p0, p1, 2, 1, 3), 255), (*blend_rgb(p0, p1, 1, 2, 3), 255)]
    return [(*p0, 255), (*p1, 255), (*blend_rgb(p0, p1, 1, 1, 2), 255), (0, 0, 0, 0)]


def decode_dxt1_block(block: bytes) -> list[tuple[int, int, int, int]]:
    palette = decode_color_block(block, True)
    bits = struct.unpack_from("<I", block, 4)[0]
    pixels = []
    for idx in range(16):
        pixels.append(palette[(bits >> (idx * 2)) & 3])
    return pixels


def decode_alpha_palette(a0: int, a1: int) -> list[int]:
    palette = [a0, a1]
    if a0 > a1:
        palette.extend([(6 * a0 + a1) // 7, (5 * a0 + 2 * a1) // 7, (4 * a0 + 3 * a1) // 7])
        palette.extend([(3 * a0 + 4 * a1) // 7, (2 * a0 + 5 * a1) // 7, (a0 + 6 * a1) // 7])
    else:
        palette.extend([(4 * a0 + a1) // 5, (3 * a0 + 2 * a1) // 5, (2 * a0 + 3 * a1) // 5, (a0 + 4 * a1) // 5, 0, 255])
    return palette


def decode_dxt5_block(block: bytes) -> list[tuple[int, int, int, int]]:
    a0 = block[0]
    a1 = block[1]
    alpha_bits = int.from_bytes(block[2:8], "little")
    alphas = decode_alpha_palette(a0, a1)
    color_palette = decode_color_block(block[8:16], True)
    color_bits = struct.unpack_from("<I", block, 12)[0]
    pixels = []
    for idx in range(16):
        color = color_palette[(color_bits >> (idx * 2)) & 3]
        alpha = alphas[(alpha_bits >> (idx * 3)) & 7]
        pixels.append((color[0], color[1], color[2], alpha))
    return pixels


def read_file_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        if sys.platform.startswith("win") and not str(path).startswith("\\\\?\\"):
            return Path("\\\\?\\" + str(path)).read_bytes()
        raise


def decode_dds_to_png(dds_path: Path) -> Path | None:
    data = read_file_bytes(dds_path)
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    height = int.from_bytes(data[12:16], "little")
    width = int.from_bytes(data[16:20], "little")
    fourcc = data[84:88]
    if width <= 0 or height <= 0:
        return None
    if fourcc not in {b"DXT1", b"DXT5"}:
        DDS_FALLBACKS.append({"dds": str(dds_path), "decoded": False, "reason": "unsupported_fourcc", "fourcc": fourcc.decode("ascii", "replace")})
        return None
    block_size = 8 if fourcc == b"DXT1" else 16
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    expected_size = 128 + blocks_x * blocks_y * block_size
    if len(data) < expected_size:
        DDS_FALLBACKS.append({"dds": str(dds_path), "decoded": False, "reason": "truncated_dds", "fourcc": fourcc.decode("ascii", "replace")})
        return None
    rgba = bytearray(width * height * 4)
    offset = 128
    for by in range(blocks_y):
        for bx in range(blocks_x):
            block = data[offset : offset + block_size]
            offset += block_size
            pixels = decode_dxt1_block(block) if fourcc == b"DXT1" else decode_dxt5_block(block)
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    continue
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    dst = (y * width + x) * 4
                    rgba[dst : dst + 4] = bytes(pixels[py * 4 + px])
    out_dir = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\_gridlock_water_png_20260814")
    safe_name = dds_path.stem
    safe_name = safe_name.replace("T_FX_MP_GridlockWater_Delta.Textures.", "water_")
    safe_name = safe_name.replace("__1024x1024_PF_DXT1_", "__dxt1_")
    safe_name = safe_name.replace("__1024x1024_PF_DXT5_", "__dxt5_")
    safe_name = safe_name[:96]
    png_path = out_dir / (safe_name + ".png")
    write_png_rgba(png_path, width, height, bytes(rgba))
    DDS_FALLBACKS.append({"dds": str(dds_path), "png": str(png_path), "decoded": True, "fourcc": fourcc.decode("ascii", "replace"), "width": width, "height": height})
    return png_path

def load_image(path_text: str | Path | None, colorspace: str = "sRGB") -> bpy.types.Image | None:
    if not path_text:
        return None
    path = Path(path_text)
    water_dds = path.suffix.lower() == ".dds" and "fx_mp_gridlockwater_delta" in path.name.lower()
    if not water_dds and not path.exists():
        return None
    if water_dds:
        png_path = decode_dds_to_png(path)
        if png_path is not None and png_path.exists():
            path = png_path
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
        if path.suffix.lower() == ".dds":
            png_path = decode_dds_to_png(path)
            if png_path is not None and png_path.exists():
                return load_image(png_path, colorspace)
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


def find_water_textures(texture_cache: Path) -> dict[str, Any]:
    textures_dir = texture_cache / "textures_dds"
    found: dict[str, dict[str, str]] = {}
    roles = {
        "occlusion": "mp_gridlock_occlusion",
        "normal_hi": "gridlock_normals_hi_freq",
        "normal_lo": "gridlock_normals_lo_freq",
        "fine_mist": "fine_mist_2x2",
        "foam_coarse": "foam02_coarse",
        "foam_medium": "foam02_medium",
        "foam_fine": "foam02_fine",
        "gridlock_foam": "mp_gridlock_foam",
        "foam_proximity": "mp_gridlock_foam_proximity",
        "cusp_hi_02": "gridlock_cusp_hi_freq_02",
        "cusp_hi_03": "gridlock_cusp_hi_freq_03",
        "foam_hi_02": "gridlock_foam_hi_freq_02",
        "foam_hi_03": "gridlock_foam_hi_freq_03",
    }
    if textures_dir.exists():
        for path in textures_dir.glob("*.dds"):
            lower = path.name.lower()
            if "fx_mp_gridlockwater_delta" not in lower:
                continue
            for role, token in roles.items():
                if token in lower and role not in found:
                    found[role] = {"path": str(path), "name": path.name}

    sky_bg = None
    for path in textures_dir.glob("*skydome_gridlock_bg_01*dds") if textures_dir.exists() else []:
        sky_bg = str(path)
        break

    binding_rows = []
    for row in read_csv(texture_cache / "gowreloaded_mp_gridlock_material_texture_bindings.csv"):
        material = (row.get("material_path") or row.get("object_path") or "").lower()
        if "fx_mp_gridlockwater_delta.materials" not in material:
            continue
        binding_rows.append(
            {
                "export_index": row.get("export_index", ""),
                "class_name": row.get("class_name", ""),
                "object_path": row.get("material_path", "") or row.get("object_path", ""),
                "status": row.get("binding_status", "") or row.get("status", ""),
                "parent_material": row.get("parent_material_path", "") or row.get("parent_material", ""),
                "referenced_textures": row.get("referenced_textures", ""),
                "diffuse_texture": row.get("diffuse_texture", ""),
                "diffuse_dds": row.get("diffuse_dds", ""),
                "normal_texture": row.get("normal_texture", ""),
                "normal_dds": row.get("normal_dds", ""),
                "texture_cube": row.get("texture_cube", ""),
                "unresolved_textures": row.get("missing_referenced_textures", "") or row.get("unresolved_textures", ""),
            }
        )

    expected = sorted(
        {
            texture.strip()
            for row in binding_rows
            for texture in (row.get("referenced_textures", "") or "").split(";")
            if texture.strip()
        }
    )
    present_tokens = {role: data["path"] for role, data in found.items()}
    missing_expected = []
    for expected_texture in expected:
        token = expected_texture.split(".")[-1].lower()
        role = next((role_name for role_name, role_token in roles.items() if role_token == token), "")
        if role and role in found:
            continue
        if "skydome_cubemap" in expected_texture.lower():
            missing_expected.append(expected_texture + " (TextureCube referenced; individual DDS cube output not present in current water cache)")
        elif "fx_utility_delta.textures.noise_simple_01" in expected_texture.lower():
            missing_expected.append(expected_texture + " (utility noise texture referenced; not in current water package DDS set)")
        elif token:
            missing_expected.append(expected_texture)

    return {
        "present": present_tokens,
        "sky_background": sky_bg or "",
        "expected_from_native_materials": expected,
        "missing_from_current_cache": missing_expected,
        "native_binding_rows": binding_rows,
        "dds_decode_fallbacks": DDS_FALLBACKS,
    }


def clear_nodes(material: bpy.types.Material) -> tuple[bpy.types.Nodes, bpy.types.NodeLinks]:
    material.use_nodes = True
    nodes = material.node_tree.nodes
    for node in list(nodes):
        nodes.remove(node)
    return nodes, material.node_tree.links


def setup_transparent_material(material: bpy.types.Material, alpha: float) -> dict[str, str]:
    material.diffuse_color = (0.035, 0.115, 0.130, alpha)
    safe_setattr(material, "use_backface_culling", False)
    safe_setattr(material, "show_transparent_back", True)
    safe_setattr(material, "use_screen_refraction", True)
    blend = set_enum_value(material, "blend_method", ["BLEND", "HASHED", "DITHERED"])
    surface = set_enum_value(material, "surface_render_method", ["BLENDED", "DITHERED"])
    return {"blend_method": blend, "surface_render_method": surface}


def set_mapping_defaults(mapping: bpy.types.Node, scale: tuple[float, float, float], loc_a: tuple[float, float, float], loc_b: tuple[float, float, float]) -> None:
    scale_socket = mapping.inputs.get("Scale")
    if scale_socket is not None:
        scale_socket.default_value[0] = scale[0]
        scale_socket.default_value[1] = scale[1]
        scale_socket.default_value[2] = scale[2]
    loc_socket = mapping.inputs.get("Location")
    if loc_socket is None:
        return
    loc_socket.default_value[0] = loc_a[0]
    loc_socket.default_value[1] = loc_a[1]
    loc_socket.default_value[2] = loc_a[2]
    loc_socket.keyframe_insert("default_value", frame=1)
    loc_socket.default_value[0] = loc_b[0]
    loc_socket.default_value[1] = loc_b[1]
    loc_socket.default_value[2] = loc_b[2]
    loc_socket.keyframe_insert("default_value", frame=180)


def make_ocean_material(texture_info: dict[str, Any]) -> dict[str, Any]:
    paths = texture_info["present"]
    material = bpy.data.materials.get(OCEAN_MATERIAL) or bpy.data.materials.new(OCEAN_MATERIAL)
    render_props = setup_transparent_material(material, 0.74)
    material["gridlock_water_repair"] = "source_native_reloaded_water_dds_nodes"
    material["source_material_family"] = (
        "FX_MP_GridlockWater_Delta.Materials.BASEMAT_Ocean_MAT_delta / Ocean_MIC_delta / "
        "Ocean_Static_MIC_delta / Ocean_Dynamic_MIC_delta"
    )
    material["decoded_texture_roles"] = json.dumps(paths, ensure_ascii=True)
    material["known_missing_texture_roles"] = json.dumps(texture_info["missing_from_current_cache"], ensure_ascii=True)

    occlusion = load_image(paths.get("occlusion"), "sRGB")
    normal_hi = load_image(paths.get("normal_hi"), "Non-Color")
    normal_lo = load_image(paths.get("normal_lo"), "Non-Color")
    sky_bg = load_image(texture_info.get("sky_background"), "sRGB")

    nodes, links = clear_nodes(material)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (1000, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (720, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    set_principled(bsdf, ("Base Color",), (0.030, 0.105, 0.120, 1.0))
    set_principled(bsdf, ("Alpha",), 0.74)
    set_principled(bsdf, ("Metallic",), 0.0)
    set_principled(bsdf, ("Roughness",), 0.035)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.98)
    set_principled(bsdf, ("Transmission Weight", "Transmission"), 0.18)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.38)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.045)
    set_principled(bsdf, ("IOR",), 1.333)

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-1050, 150)

    base_output = None
    if occlusion is not None:
        mapping_occ = nodes.new("ShaderNodeMapping")
        mapping_occ.name = "Gridlock_OcclusionMask_Mapping_Animated"
        mapping_occ.label = "Gridlock occlusion / foam mask drift"
        mapping_occ.location = (-825, 230)
        set_mapping_defaults(mapping_occ, (1.0, 1.0, 1.0), (0.0, 0.0, 0.0), (0.045, -0.028, 0.0))
        tex_occ = nodes.new("ShaderNodeTexImage")
        tex_occ.name = "Reloaded_mp_gridlock_occlusion"
        tex_occ.label = "mp_gridlock_occlusion"
        tex_occ.location = (-600, 230)
        tex_occ.image = occlusion
        tex_occ.extension = "REPEAT"
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.name = "Gridlock_Water_Occlusion_ColorRamp"
        ramp.location = (-350, 210)
        ramp.color_ramp.elements[0].position = 0.08
        ramp.color_ramp.elements[0].color = (0.018, 0.052, 0.056, 1.0)
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = (0.235, 0.355, 0.330, 1.0)
        links.new(texcoord.outputs["Generated"], mapping_occ.inputs["Vector"])
        links.new(mapping_occ.outputs["Vector"], tex_occ.inputs["Vector"])
        links.new(tex_occ.outputs["Color"], ramp.inputs["Fac"])
        base_output = ramp.outputs["Color"]

    if sky_bg is not None:
        env = nodes.new("ShaderNodeTexEnvironment")
        env.name = "Gridlock_Sky_Reflection_Approx"
        env.label = "Sky reflection from decoded Gridlock sky"
        env.location = (-350, -55)
        env.image = sky_bg
        hue = nodes.new("ShaderNodeHueSaturation")
        hue.location = (-120, -55)
        if "Saturation" in hue.inputs:
            hue.inputs["Saturation"].default_value = 0.45
        if "Value" in hue.inputs:
            hue.inputs["Value"].default_value = 0.30
        links.new(texcoord.outputs["Reflection"], env.inputs["Vector"])
        links.new(env.outputs["Color"], hue.inputs["Color"])
        if base_output is not None:
            mix = nodes.new("ShaderNodeMixRGB")
            mix.name = "Gridlock_Water_BasePlusSkyReflection"
            mix.blend_type = "SCREEN"
            mix.inputs["Fac"].default_value = 0.23
            mix.location = (170, 120)
            links.new(base_output, mix.inputs["Color1"])
            links.new(hue.outputs["Color"], mix.inputs["Color2"])
            base_output = mix.outputs["Color"]
        else:
            base_output = hue.outputs["Color"]

    if base_output is not None and principled_socket(bsdf, ("Base Color",)):
        links.new(base_output, bsdf.inputs["Base Color"])

    normal_output = None
    mapping_hi = None
    if normal_hi is not None:
        mapping_hi = nodes.new("ShaderNodeMapping")
        mapping_hi.name = "Gridlock_NormalHi_Mapping_Animated"
        mapping_hi.label = "hi-frequency water normal drift"
        mapping_hi.location = (-825, -260)
        set_mapping_defaults(mapping_hi, (8.0, 8.0, 1.0), (0.0, 0.0, 0.0), (0.62, -0.20, 0.0))
        tex_hi = nodes.new("ShaderNodeTexImage")
        tex_hi.name = "Reloaded_gridlock_normals_hi_freq"
        tex_hi.label = "gridlock_normals_hi_freq"
        tex_hi.location = (-600, -260)
        tex_hi.image = normal_hi
        tex_hi.extension = "REPEAT"
        links.new(texcoord.outputs["Generated"], mapping_hi.inputs["Vector"])
        links.new(mapping_hi.outputs["Vector"], tex_hi.inputs["Vector"])
        normal_output = tex_hi.outputs["Color"]

    if normal_lo is not None:
        mapping_lo = nodes.new("ShaderNodeMapping")
        mapping_lo.name = "Gridlock_NormalLo_Mapping_Animated"
        mapping_lo.label = "low-frequency swell normal drift"
        mapping_lo.location = (-825, -505)
        set_mapping_defaults(mapping_lo, (2.2, 2.2, 1.0), (0.0, 0.0, 0.0), (-0.18, 0.34, 0.0))
        tex_lo = nodes.new("ShaderNodeTexImage")
        tex_lo.name = "Reloaded_gridlock_normals_lo_freq"
        tex_lo.label = "gridlock_normals_lo_freq"
        tex_lo.location = (-600, -505)
        tex_lo.image = normal_lo
        tex_lo.extension = "REPEAT"
        links.new(texcoord.outputs["Generated"], mapping_lo.inputs["Vector"])
        links.new(mapping_lo.outputs["Vector"], tex_lo.inputs["Vector"])
        if normal_output is not None:
            mix_norm = nodes.new("ShaderNodeMixRGB")
            mix_norm.name = "Gridlock_Water_HiLo_Normal_Blend"
            mix_norm.blend_type = "OVERLAY"
            mix_norm.inputs["Fac"].default_value = 0.42
            mix_norm.location = (-325, -350)
            links.new(normal_output, mix_norm.inputs["Color1"])
            links.new(tex_lo.outputs["Color"], mix_norm.inputs["Color2"])
            normal_output = mix_norm.outputs["Color"]
        else:
            normal_output = tex_lo.outputs["Color"]

    if normal_output is not None and principled_socket(bsdf, ("Normal",)):
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "Gridlock_Water_SourceNormalMap"
        normal_map.location = (145, -345)
        normal_map.inputs["Strength"].default_value = 0.34
        links.new(normal_output, normal_map.inputs["Color"])
        noise = nodes.new("ShaderNodeTexNoise")
        noise.name = "Gridlock_Water_MicroRipple_Noise"
        noise.location = (140, -575)
        noise.inputs["Scale"].default_value = 85.0
        noise.inputs["Detail"].default_value = 14.0
        noise.inputs["Roughness"].default_value = 0.56
        bump = nodes.new("ShaderNodeBump")
        bump.name = "Gridlock_Water_MicroRipple_Bump"
        bump.location = (430, -405)
        bump.inputs["Strength"].default_value = 0.018
        bump.inputs["Distance"].default_value = 0.035
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(normal_map.outputs["Normal"], bump.inputs["Normal"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    material["animated_preview"] = "source water texture mappings are keyframed frames 1-180"
    material["source_texture_occlusion"] = paths.get("occlusion", "")
    material["source_texture_normal_hi"] = paths.get("normal_hi", "")
    material["source_texture_normal_lo"] = paths.get("normal_lo", "")
    material["reflection_source"] = texture_info.get("sky_background", "")
    return {
        "material": material.name,
        "render_props": render_props,
        "loaded_images": {
            "occlusion": occlusion is not None,
            "normal_hi": normal_hi is not None,
            "normal_lo": normal_lo is not None,
            "sky_reflection": sky_bg is not None,
        },
        "node_count": len(material.node_tree.nodes),
    }


def make_puddle_material(texture_info: dict[str, Any]) -> dict[str, Any]:
    paths = texture_info["present"]
    material = bpy.data.materials.get(PUDDLE_MATERIAL) or bpy.data.materials.new(PUDDLE_MATERIAL)
    setup_transparent_material(material, 0.62)
    material.diffuse_color = (0.040, 0.070, 0.065, 0.62)
    material["gridlock_water_repair"] = "floor_puddle_uses_gridlock_occlusion_and_water_normals"

    occlusion = load_image(paths.get("occlusion"), "sRGB")
    normal_hi = load_image(paths.get("normal_hi"), "Non-Color")
    nodes, links = clear_nodes(material)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (760, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (470, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.045, 0.075, 0.065, 1.0))
    set_principled(bsdf, ("Alpha",), 0.62)
    set_principled(bsdf, ("Roughness",), 0.025)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.98)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.55)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.035)
    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.location = (-610, 110)
    if occlusion is not None:
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-405, 100)
        set_mapping_defaults(mapping, (1.5, 1.5, 1.0), (0.0, 0.0, 0.0), (0.025, 0.02, 0.0))
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-190, 100)
        tex.image = occlusion
        tex.extension = "REPEAT"
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.location = (55, 95)
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0.018, 0.026, 0.024, 1.0)
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = (0.155, 0.205, 0.175, 1.0)
        links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    if normal_hi and principled_socket(bsdf, ("Normal",)):
        mapping_n = nodes.new("ShaderNodeMapping")
        mapping_n.location = (-405, -165)
        set_mapping_defaults(mapping_n, (5.0, 5.0, 1.0), (0.0, 0.0, 0.0), (0.21, -0.09, 0.0))
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.location = (-190, -165)
        tex_n.image = normal_hi
        tex_n.extension = "REPEAT"
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (65, -165)
        nmap.inputs["Strength"].default_value = 0.18
        links.new(texcoord.outputs["Generated"], mapping_n.inputs["Vector"])
        links.new(mapping_n.outputs["Vector"], tex_n.inputs["Vector"])
        links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return {"material": material.name, "loaded_images": {"occlusion": occlusion is not None, "normal_hi": bool(normal_hi)}}


def make_spray_material(texture_info: dict[str, Any]) -> dict[str, Any]:
    paths = texture_info["present"]
    material = bpy.data.materials.get(SPRAY_MATERIAL) or bpy.data.materials.new(SPRAY_MATERIAL)
    setup_transparent_material(material, 0.54)
    material.diffuse_color = (0.50, 0.68, 0.70, 0.54)
    material["gridlock_water_repair"] = "fine_mist_2x2_billboard_visualization_for_native_wall_spray_emitters"
    mist = load_image(paths.get("fine_mist"), "sRGB")
    nodes, links = clear_nodes(material)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (535, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (250, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), (0.46, 0.62, 0.64, 1.0))
    set_principled(bsdf, ("Alpha",), 0.42)
    set_principled(bsdf, ("Roughness",), 0.42)
    set_principled(bsdf, ("Emission Color",), (0.26, 0.45, 0.47, 1.0))
    set_principled(bsdf, ("Emission Strength",), 0.22)
    if mist is not None:
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.location = (-510, 65)
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-280, 65)
        tex.image = mist
        tex.extension = "CLIP"
        links.new(texcoord.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if "Alpha" in tex.outputs and principled_socket(bsdf, ("Alpha",)):
            links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    return {"material": material.name, "loaded_images": {"fine_mist": mist is not None}}


def object_material_text(obj: bpy.types.Object) -> str:
    names = []
    for slot in obj.material_slots:
        if slot.material:
            names.append(slot.material.name)
    return " ".join(names)


def object_search_text(obj: bpy.types.Object) -> str:
    pieces = [
        obj.name,
        obj.data.name if getattr(obj, "data", None) else "",
        str(obj.get("ue_static_mesh_path") or ""),
        str(obj.get("ue_actor_class") or ""),
        str(obj.get("ue_template_path") or ""),
        object_material_text(obj),
        " ".join(coll.name for coll in obj.users_collection),
    ]
    return " ".join(pieces).lower()


def is_visible_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render


def is_water_surface(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH":
        return False
    text = object_search_text(obj)
    include = (
        "factoryocean" in text
        or "gridlockwater" in text
        or "gridlock_water" in text
        or "water_stmesh" in text
        or "water_skmesh" in text
        or "ocean_gridlock" in text
        or "ocean_static_mic" in text
        or "ocean_dynamic_mic" in text
        or "mat_mp_gridlock_water_decoded_approx" in text
    )
    exclude = (
        "spray" in text
        or "emitter" in text
        or "marker" in text
        or "puddle" in text
        or "collision" in text
        or "hitmesh" in text
    )
    return include and not exclude


def is_floor_puddle(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH":
        return False
    text = object_search_text(obj)
    return "floor_puddle" in text or "puddle_vertexcolormesh" in text


def is_spray_marker(obj: bpy.types.Object) -> bool:
    text = object_search_text(obj)
    if "gameviewmist" in text:
        return False
    return obj.type == "MESH" and ("p_wall_spray" in text or "watersprayemittermarkers" in text or obj.name.startswith("FX_Emitter_"))


def mesh_world_bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
    if not objects:
        return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0], "center": [0.0, 0.0, 0.0], "radius": 64.0}
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
    radius = max(float(extent.x), float(extent.y), float(extent.z), 1.0) * 0.5
    return {"min": vec3(mins), "max": vec3(maxs), "center": vec3(center), "radius": round(radius, 6)}


def replace_materials(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    if obj.data.materials:
        for idx in range(len(obj.data.materials)):
            obj.data.materials[idx] = material
    else:
        obj.data.materials.append(material)


def add_water_modifiers(obj: bpy.types.Object) -> dict[str, Any]:
    for polygon in obj.data.polygons:
        polygon.use_smooth = True

    max_dim = max(float(obj.dimensions.x), float(obj.dimensions.y), 1.0)
    added = []
    if len(obj.data.vertices) < 900 and "GRIDLOCK_Water_View_Subdivide" not in obj.modifiers:
        sub = obj.modifiers.new("GRIDLOCK_Water_View_Subdivide", "SUBSURF")
        safe_setattr(sub, "levels", 1)
        safe_setattr(sub, "render_levels", 1)
        added.append(sub.name)

    wave_a = obj.modifiers.get("GRIDLOCK_Water_GameView_Wave_A")
    if wave_a is None:
        wave_a = obj.modifiers.new("GRIDLOCK_Water_GameView_Wave_A", "WAVE")
        added.append(wave_a.name)
    safe_setattr(wave_a, "height", min(max(max_dim * 0.00022, 0.018), 0.16))
    safe_setattr(wave_a, "width", min(max(max_dim * 0.035, 8.0), 55.0))
    safe_setattr(wave_a, "speed", 0.18)
    safe_setattr(wave_a, "narrowness", 1.4)
    safe_setattr(wave_a, "use_x", True)
    safe_setattr(wave_a, "use_y", True)

    wave_b = obj.modifiers.get("GRIDLOCK_Water_GameView_Wave_B")
    if wave_b is None:
        wave_b = obj.modifiers.new("GRIDLOCK_Water_GameView_Wave_B", "WAVE")
        added.append(wave_b.name)
    safe_setattr(wave_b, "height", min(max(max_dim * 0.00011, 0.010), 0.08))
    safe_setattr(wave_b, "width", min(max(max_dim * 0.018, 4.0), 28.0))
    safe_setattr(wave_b, "speed", -0.11)
    safe_setattr(wave_b, "narrowness", 2.0)
    safe_setattr(wave_b, "use_x", True)
    safe_setattr(wave_b, "use_y", False)

    obj["gridlock_water_repair"] = "source-native water material assigned; viewport/render wave modifiers added for Blender game-view motion"
    obj["gridlock_water_animation"] = "material mappings plus wave modifiers animate over frames 1-180"
    return {"object": obj.name, "vertices": len(obj.data.vertices), "dimensions": vec3(obj.dimensions), "modifiers_added_or_refreshed": added}


def apply_materials(root: bpy.types.Collection, materials: dict[str, str]) -> dict[str, Any]:
    water_coll = get_collection(WATER_COLLECTION, root)
    visual_coll = get_collection(WATER_VIS_COLLECTION, water_coll)
    ocean = bpy.data.materials[materials["ocean"]]
    puddle = bpy.data.materials[materials["puddle"]]

    water_objects = [obj for obj in bpy.data.objects if is_water_surface(obj)]
    puddle_objects = [obj for obj in bpy.data.objects if is_floor_puddle(obj)]
    spray_markers = [obj for obj in bpy.data.objects if is_spray_marker(obj)]

    applied_water = []
    for obj in water_objects:
        obj.hide_viewport = False
        obj.hide_render = False
        replace_materials(obj, ocean)
        link_object(visual_coll, obj)
        unlink_from_scene_root(obj)
        applied_water.append(add_water_modifiers(obj))

    applied_puddles = []
    for obj in puddle_objects:
        replace_materials(obj, puddle)
        obj.hide_viewport = False
        obj.hide_render = False
        link_object(visual_coll, obj)
        unlink_from_scene_root(obj)
        obj["gridlock_water_repair"] = "floor puddle material upgraded from generated overlay to Gridlock water texture family"
        applied_puddles.append({"object": obj.name, "dimensions": vec3(obj.dimensions), "material": puddle.name})

    return {
        "water_objects": applied_water,
        "puddle_objects": applied_puddles,
        "spray_markers": [{"object": obj.name, "location": vec3(obj.location), "dimensions": vec3(obj.dimensions)} for obj in spray_markers],
    }


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.frame_start = min(int(scene.frame_start or 1), 1)
    scene.frame_end = max(int(scene.frame_end or 1), 180)
    scene.frame_set(72)
    try:
        scene.eevee.taa_render_samples = 96
    except Exception:
        pass
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
        scene.view_settings.exposure = -0.05
        scene.view_settings.gamma = 1.0
    except Exception:
        pass
    return {"engine": scene.render.engine, "frame": scene.frame_current, "resolution": [scene.render.resolution_x, scene.render.resolution_y]}


def water_preview_target(water_objects: list[dict[str, Any]]) -> Vector:
    preferred = bpy.data.objects.get("gridlockWater_stMesh_ma_SMesh_gridlock_water_SMESH__26438")
    if preferred is not None:
        bounds = mesh_world_bounds([preferred])
        return Vector(bounds["center"]) + Vector((0.0, 0.0, 8.0))
    objects = [bpy.data.objects[row["object"]] for row in water_objects if bpy.data.objects.get(row["object"])]
    bounds = mesh_world_bounds(objects)
    return Vector(bounds["center"]) + Vector((0.0, 0.0, 8.0))


def make_camera(root: bpy.types.Collection, water_objects: list[dict[str, Any]]) -> dict[str, Any]:
    target = water_preview_target(water_objects)
    camera = bpy.data.objects.get("CAM_MP_Gridlock_Water_Preview")
    if camera is None:
        cam_data = bpy.data.cameras.new("CAM_MP_Gridlock_Water_Preview")
        camera = bpy.data.objects.new("CAM_MP_Gridlock_Water_Preview", cam_data)
        link_object(get_collection("Cameras", root), camera)
    camera.location = target + Vector((-168.0, -236.0, 72.0))
    direction = target - Vector(camera.location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 24
    camera.data.clip_start = 0.05
    camera.data.clip_end = 220000.0
    bpy.context.scene.camera = camera
    unlink_from_scene_root(camera)
    return {"camera": camera.name, "location": vec3(camera.location), "target": vec3(target), "lens": camera.data.lens}


def create_spray_billboards(root: bpy.types.Collection, marker_rows: list[dict[str, Any]], spray_material_name: str, camera_name: str) -> dict[str, Any]:
    for obj in list(bpy.data.objects):
        if "_GameViewMist_GameViewMist" in obj.name:
            bpy.data.objects.remove(obj, do_unlink=True)
    spray_coll = get_collection(SPRAY_VIS_COLLECTION, get_collection(WATER_COLLECTION, root))
    spray_material = bpy.data.materials[spray_material_name]
    camera = bpy.data.objects.get(camera_name)
    created = []
    hidden_markers = []
    for row in marker_rows:
        marker = bpy.data.objects.get(row["object"])
        if marker is None:
            continue
        marker.hide_viewport = True
        marker.hide_render = True
        marker["gridlock_water_repair"] = "native spray emitter marker preserved hidden; game-view mist billboard created"
        hidden_markers.append(marker.name)

        billboard_name = marker.name + "_GameViewMist"
        billboard = bpy.data.objects.get(billboard_name)
        if billboard is None:
            mesh = bpy.data.meshes.new(billboard_name + "_Mesh")
            half = 6.0
            verts = [(-half, 0.0, -half), (half, 0.0, -half), (half, 0.0, half), (-half, 0.0, half)]
            faces = [(0, 1, 2, 3)]
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            uv = mesh.uv_layers.new(name="UVMap")
            coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for loop, coord in zip(mesh.polygons[0].loop_indices, coords):
                uv.data[loop].uv = coord
            billboard = bpy.data.objects.new(billboard_name, mesh)
            link_object(spray_coll, billboard)
        else:
            link_object(spray_coll, billboard)
        billboard.location = marker.location + Vector((0.0, 0.0, 2.5))
        if camera is not None:
            direction = Vector(camera.location) - Vector(billboard.location)
            if direction.length > 0:
                billboard.rotation_euler = direction.to_track_quat("Y", "Z").to_euler()
        billboard.data.materials.clear()
        billboard.data.materials.append(spray_material)
        billboard.hide_viewport = False
        billboard.hide_render = False
        billboard["gridlock_water_repair"] = "fine_mist_2x2 visual billboard for decoded P_wall_spray emitter"
        billboard["source_marker"] = marker.name
        unlink_from_scene_root(billboard)
        created.append({"object": billboard.name, "source_marker": marker.name, "location": vec3(billboard.location)})
    return {"billboards": created, "hidden_native_markers": hidden_markers}


def render_still(path: Path) -> dict[str, Any]:
    ensure_parent(path)
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
    ensure_parent(dst)
    shutil.copyfile(src, dst)
    return {"preview_copy": str(dst), "copied": True, "size": dst.stat().st_size}


def direct_scene_root_objects() -> list[str]:
    return [obj.name for obj in bpy.context.scene.collection.objects]


def main() -> int:
    args = parse_args()
    root = get_collection(ROOT_COLLECTION)
    texture_info = find_water_textures(Path(args.texture_cache))
    ocean_summary = make_ocean_material(texture_info)
    puddle_summary = make_puddle_material(texture_info)
    spray_summary = make_spray_material(texture_info)

    materials = {"ocean": OCEAN_MATERIAL, "puddle": PUDDLE_MATERIAL, "spray": SPRAY_MATERIAL}
    applied = apply_materials(root, materials)
    render_config = configure_render()
    camera_summary = make_camera(root, applied["water_objects"])
    spray_visuals = create_spray_billboards(root, applied["spray_markers"], SPRAY_MATERIAL, camera_summary["camera"])

    scene = bpy.context.scene
    scene["gridlock_water_status"] = "source_native_water_dds_materials_applied_with_animated_blender_game_view"
    scene["gridlock_water_preview_path"] = str(args.preview_copy)
    scene["gridlock_water_repair_proof"] = str(args.proof_out)

    render_summary = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        render_summary = render_still(Path(args.render_out))
        render_summary.update(copy_preview(Path(args.render_out), Path(args.preview_copy)))

    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_water_gameview_repair_applied",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "reason": "Water now uses decoded Reloaded Gridlock water DDS inputs instead of the prior generated placeholder overlay; exact UE3 foam/cubemap graph remains documented as missing from current cache.",
        "textures": texture_info,
        "materials": {
            "ocean": ocean_summary,
            "puddle": puddle_summary,
            "spray": spray_summary,
        },
        "applied": applied,
        "spray_visuals": spray_visuals,
        "render_config": render_config,
        "camera": camera_summary,
        "render": render_summary,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "direct_scene_root_objects": direct_scene_root_objects(),
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
