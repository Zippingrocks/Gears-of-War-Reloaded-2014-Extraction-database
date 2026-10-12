#!/usr/bin/env python3
"""Force-decode native Gridlock water/ocean texture inputs by exact export path.

The broad material cache intentionally classifies unknown texture roles
conservatively. That left several real MP_Gridlock water inputs unused:
foam/cusp masks, cloud tile noise, and TextureCube face exports. This targeted
pass exports those known native Texture2D payloads and writes a small proof file
for the Blender water shader.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import struct
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


WORKSPACE = Path(r"C:\Users\Bilbo\Downloads\Gears Map Ripping")
HEAVY_PARSE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)
COOKED_ROOT = Path(r"D:\SteamLibrary\steamapps\common\Gears of War Reloaded\WarGame\CookedPC")
MAP_DIR = COOKED_ROOT / "Maps" / "MP_Maps"
MAP_ROOT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12"
)
SCENE_DIR = MAP_ROOT / "Blender_Scene_2026_08_12"
VISUAL_CSV = MAP_ROOT / "Heavy_Parse" / "gowreloaded_mp_gridlock_visual_reference_exports.csv"
DECOMPRESSED_WAR = MAP_ROOT / "Texture_Section_UV_Validation_2026_08_13" / "MP_Gridlock.decompressed.war"
DEFAULT_OUT_ROOT = SCENE_DIR / "native_water_ocean_decode_2026_08_15"

TEXTURE_CLASSES = {"Texture2D", "LightMapTexture2D", "ShadowMapTexture2D"}
SUPPORTED_FOURCC = {
    "PF_DXT1": b"DXT1",
    "PF_DXT3": b"DXT3",
    "PF_DXT5": b"DXT5",
    "PF_DXN": b"ATI2",
}


CLOSE_WATER_TEXTURES = [
    "FX_MP_GridlockWater_Delta.Textures.gridlock_normals_lo_freq",
    "FX_MP_GridlockWater_Delta.Textures.gridlock_normals_hi_freq",
    "FX_MP_GridlockWater_Delta.Textures.foam02_coarse",
    "FX_MP_GridlockWater_Delta.Textures.foam02_medium",
    "FX_MP_GridlockWater_Delta.Textures.foam02_fine",
    "FX_MP_GridlockWater_Delta.Textures.mp_gridlock_occlusion",
    "FX_MP_GridlockWater_Delta.Textures.mp_gridlock_foam",
    "FX_MP_GridlockWater_Delta.Textures.mp_gridlock_foam_proximity",
    "FX_MP_GridlockWater_Delta.Textures.gridlock_cusp_hi_freq_02",
    "FX_MP_GridlockWater_Delta.Textures.gridlock_cusp_hi_freq_03",
    "FX_MP_GridlockWater_Delta.Textures.gridlock_foam_hi_freq_02",
    "FX_MP_GridlockWater_Delta.Textures.gridlock_foam_hi_freq_03",
    "FX_Utility_Delta.Textures.noise_simple_01",
]

VISTA_OCEAN_TEXTURES = [
    "FX_Ocean_Delta.Textures.T_OceanFoam",
    "FX_Ocean_Delta.Textures.T_OceanFoam_Delta_Normal",
    "FX_Utility_Delta.Textures.T_CloudTile_Delta",
]

CUBE_FACE_PREFIXES = {
    "close_gridlock_skydome": "FX_MP_GridlockWater_Delta.Cubemaps.skydome_cubemap",
    "vista_factory_ocean": "FX_Ocean_Delta.Textures.FactoryOceanCube_Tex3",
}

EXPECTED_BUT_NOT_DIRECT_TEXTURE2D = [
    "FX_Utility_Delta.Textures.clouds_01",
    "FX_Water_Delta.Textures.EmbryStartCubemap_Tex",
    "FX_MP_GridlockWater_Delta.Cubemaps.skydome_cubemap",
    "FX_Ocean_Delta.Textures.FactoryOceanCube_Tex3",
]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def lz4_block_decompress(data: bytes, uncompressed_size: int) -> bytes:
    src = memoryview(data)
    pos = 0
    out = bytearray()
    while pos < len(src):
        token = int(src[pos])
        pos += 1
        literal_len = token >> 4
        if literal_len == 15:
            while True:
                if pos >= len(src):
                    raise ValueError("lz4 literal length overruns input")
                value = int(src[pos])
                pos += 1
                literal_len += value
                if value != 255:
                    break
        if pos + literal_len > len(src):
            raise ValueError("lz4 literal payload overruns input")
        out.extend(src[pos : pos + literal_len])
        pos += literal_len
        if pos >= len(src):
            break
        if pos + 2 > len(src):
            raise ValueError("lz4 match offset overruns input")
        match_offset = int(src[pos]) | (int(src[pos + 1]) << 8)
        pos += 2
        if match_offset <= 0 or match_offset > len(out):
            raise ValueError(f"invalid lz4 match offset {match_offset}")
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                if pos >= len(src):
                    raise ValueError("lz4 match length overruns input")
                value = int(src[pos])
                pos += 1
                match_len += value
                if value != 255:
                    break
        match_len += 4
        ref = len(out) - match_offset
        for _ in range(match_len):
            out.append(out[ref])
            ref += 1
    if len(out) != uncompressed_size:
        raise ValueError(f"lz4 decoded {len(out)} bytes, expected {uncompressed_size}")
    return bytes(out)


def install_lz4_stub() -> None:
    # The shared parser imports lz4.block; this shim gives it the raw block decoder it needs.
    if "lz4.block" in sys.modules:
        return
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")
    block_module.decompress = lz4_block_decompress  # type: ignore[attr-defined]
    lz4_module.block = block_module  # type: ignore[attr-defined]
    sys.modules.setdefault("lz4", lz4_module)
    sys.modules.setdefault("lz4.block", block_module)


def load_heavy_parser() -> Any:
    install_lz4_stub()
    return load_module("gowr_gridlock_heavy_parse_no_lz4", HEAVY_PARSE)


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def safe_stem(text: str, limit: int = 130) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text)
    while "__" in safe:
        safe = safe.replace("__", "_")
    digest = hashlib.sha1(text.lower().encode("utf-8")).hexdigest()[:10]
    return f"{safe[:limit]}__{digest}"


def png_for_texture(out_png: Path, full_path: str, dds_path: Path) -> Path:
    return out_png / f"T_{safe_stem(full_path)}{dds_path.suffix}.png"


def convert_dds_to_png(dds_path: Path, png_path: Path) -> dict[str, Any]:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(dds_path) as image:
        converted = image.convert("RGBA")
        converted.save(png_path, "PNG", optimize=True)
        return {
            "status": "converted",
            "png_path": str(png_path),
            "png_size": list(converted.size),
            "png_bytes": png_path.stat().st_size,
            "mode": converted.mode,
        }


def reconstruct_bc5_normal(png_path: Path, out_path: Path) -> dict[str, Any]:
    image = Image.open(png_path).convert("RGBA")
    source = np.asarray(image, dtype=np.uint8)
    rg = source[:, :, :2].astype(np.float32) / 255.0
    xy = rg * 2.0 - 1.0
    length_sq = np.clip(np.sum(xy * xy, axis=2), 0.0, 1.0)
    z = np.sqrt(1.0 - length_sq)
    out = np.empty_like(source)
    out[:, :, 0] = source[:, :, 0]
    out[:, :, 1] = source[:, :, 1]
    out[:, :, 2] = np.clip(np.rint(z * 255.0), 0, 255).astype(np.uint8)
    out[:, :, 3] = source[:, :, 3]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out, mode="RGBA").save(out_path, "PNG", optimize=True)
    return {
        "status": "bc5_reconstructed",
        "source_png": str(png_path),
        "reconstructed_png": str(out_path),
        "size": list(image.size),
        "source_blue_extrema": list(image.getextrema()[2]),
        "out_blue_extrema": list(Image.open(out_path).convert("RGBA").getextrema()[2]),
    }


def prop_value(tags: list[dict[str, Any]], base_name: str) -> Any:
    for tag in reversed(tags):
        if tag.get("base_name") == base_name:
            return tag.get("decoded")
    return None


def texture_filename(full_path: str, width: int, height: int, fmt: str) -> str:
    digest = hashlib.sha1(full_path.lower().encode("utf-8")).hexdigest()[:12]
    clean = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(full_path))
    clean = clean[:90].strip("._") or "unnamed"
    return f"T_{clean}__{width}x{height}_{fmt}_{digest}.dds"


def parse_texture_mips(virt: bytes, row: dict[str, Any], native_start_rel: int) -> dict[str, Any]:
    serial_offset = int(row["serial_offset"])
    serial_end = serial_offset + int(row["serial_size"])
    pos = serial_offset + native_start_rel
    if pos + 20 > serial_end:
        raise ValueError("texture native data is too short")
    prefix = virt[pos : pos + 12]
    pos += 12
    resource_offset = u32(virt, pos)
    pos += 4
    mip_count = i32(virt, pos)
    pos += 4
    if not 0 <= mip_count <= 32:
        raise ValueError(f"implausible mip_count {mip_count}")
    mips: list[dict[str, Any]] = []
    for mip_index in range(mip_count):
        if pos + 24 > serial_end:
            raise ValueError(f"mip {mip_index} header overruns export")
        flags = u32(virt, pos)
        uncompressed_size = i32(virt, pos + 4)
        stored_size = i32(virt, pos + 8)
        file_offset = i32(virt, pos + 12)
        pos += 16
        inline_offset = None
        if not (flags & 0x01) and stored_size > 0:
            inline_offset = pos
            pos += stored_size
        width = i32(virt, pos)
        height = i32(virt, pos + 4)
        pos += 8
        mips.append(
            {
                "mip_index": mip_index,
                "bulk_flags": flags,
                "bulk_flags_hex": f"0x{flags:08X}",
                "external": bool(flags & 0x01),
                "unused": bool(flags & 0x20),
                "compressed": bool(flags & 0x80),
                "uncompressed_size": uncompressed_size,
                "stored_size": stored_size,
                "file_offset": file_offset,
                "inline_offset": inline_offset,
                "width": width,
                "height": height,
            }
        )
    return {
        "prefix_hex": prefix.hex(),
        "resource_offset": resource_offset,
        "mip_count": mip_count,
        "mips": mips,
        "native_end_rel": pos - serial_offset,
        "trailing_size": serial_end - pos,
    }


def build_texture_inventory_from_decompressed() -> tuple[Any, bytes, list[dict[str, Any]]]:
    if not DECOMPRESSED_WAR.exists():
        raise FileNotFoundError(DECOMPRESSED_WAR)
    heavy = load_heavy_parser()
    virt = DECOMPRESSED_WAR.read_bytes()
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])

    textures: list[dict[str, Any]] = []
    for export in exports:
        if export["class_name"] not in TEXTURE_CLASSES or export["serial_size"] <= 0:
            continue
        try:
            scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, export, [4, 0])
            result = scan["result"]
            tags = result["tags"]
            if not result["ok"]:
                raise ValueError(result.get("error", "property scan failed"))
            fmt = prop_value(tags, "Format")
            size_x = prop_value(tags, "SizeX")
            size_y = prop_value(tags, "SizeY")
            cache_name = prop_value(tags, "TextureFileCacheName")
            source_path = prop_value(tags, "SourceFilePath")
            native = parse_texture_mips(virt, export, int(result["end_rel"]))
            textures.append(
                {
                    "package": "MP_Gridlock.war",
                    "package_path": str(DECOMPRESSED_WAR),
                    "export_index": export["index"],
                    "class_name": export["class_name"],
                    "object_name": export["object_short_name"],
                    "full_path": export["full_path"],
                    "format": fmt if isinstance(fmt, str) else str(fmt),
                    "size_x": size_x if isinstance(size_x, int) else "",
                    "size_y": size_y if isinstance(size_y, int) else "",
                    "texture_cache": cache_name if isinstance(cache_name, str) else "",
                    "cache_path": str(COOKED_ROOT / f"{cache_name}.tfc") if isinstance(cache_name, str) and cache_name else "",
                    "source_file_path": source_path if isinstance(source_path, str) else "",
                    "native": native,
                    "decode_status": "texture_mip_table_decoded_from_decompressed_gridlock",
                }
            )
        except Exception as exc:
            textures.append(
                {
                    "package": "MP_Gridlock.war",
                    "package_path": str(DECOMPRESSED_WAR),
                    "export_index": export["index"],
                    "class_name": export["class_name"],
                    "object_name": export["object_short_name"],
                    "full_path": export["full_path"],
                    "format": "",
                    "size_x": "",
                    "size_y": "",
                    "texture_cache": "",
                    "cache_path": "",
                    "source_file_path": "",
                    "native": {"error": str(exc)},
                    "decode_status": "texture_mip_table_failed_from_decompressed_gridlock",
                }
            )
    return heavy, virt, textures


def choose_mip(texture: dict[str, Any], max_texture_size: int) -> dict[str, Any] | None:
    candidates = [
        mip
        for mip in texture.get("native", {}).get("mips", [])
        if not mip.get("unused")
        and int(mip.get("stored_size") or 0) > 0
        and int(mip.get("width") or 0) > 0
        and int(mip.get("height") or 0) > 0
    ]
    if not candidates:
        return None
    within = [mip for mip in candidates if max(int(mip["width"]), int(mip["height"])) <= max_texture_size]
    pool = within or candidates
    return max(pool, key=lambda mip: int(mip["width"]) * int(mip["height"]))


def dds_header_fourcc(width: int, height: int, fourcc: bytes, data_size: int, mips: int = 1) -> bytes:
    flags = 0x0002100F
    caps = 0x1000
    if mips > 1:
        caps |= 0x400008
    header = bytearray()
    header += b"DDS "
    header += struct.pack("<I", 124)
    header += struct.pack("<I", flags)
    header += struct.pack("<I", height)
    header += struct.pack("<I", width)
    header += struct.pack("<I", data_size)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", mips)
    header += b"\0" * 44
    header += struct.pack("<I", 32)
    header += struct.pack("<I", 0x4)
    header += fourcc
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", caps)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    return bytes(header)


def dds_header_uncompressed(
    width: int,
    height: int,
    pitch_or_linear_size: int,
    pixel_flags: int,
    rgb_bit_count: int,
    r_mask: int,
    g_mask: int,
    b_mask: int,
    a_mask: int,
    mips: int = 1,
) -> bytes:
    flags = 0x0002100F
    caps = 0x1000
    if mips > 1:
        caps |= 0x400008
    header = bytearray()
    header += b"DDS "
    header += struct.pack("<I", 124)
    header += struct.pack("<I", flags)
    header += struct.pack("<I", height)
    header += struct.pack("<I", width)
    header += struct.pack("<I", pitch_or_linear_size)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", mips)
    header += b"\0" * 44
    header += struct.pack("<I", 32)
    header += struct.pack("<I", pixel_flags)
    header += b"\0\0\0\0"
    header += struct.pack("<I", rgb_bit_count)
    header += struct.pack("<I", r_mask)
    header += struct.pack("<I", g_mask)
    header += struct.pack("<I", b_mask)
    header += struct.pack("<I", a_mask)
    header += struct.pack("<I", caps)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    header += struct.pack("<I", 0)
    return bytes(header)


def expected_dxt_size(width: int, height: int, fmt: str) -> int:
    block = 8 if fmt == "PF_DXT1" else 16
    return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block


def export_texture_dds(
    heavy: Any,
    virt: bytes,
    texture: dict[str, Any],
    mip: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    fmt = str(texture.get("format") or "")
    width = int(mip["width"])
    height = int(mip["height"])
    stored_size = int(mip["stored_size"])
    uncompressed_size = int(mip["uncompressed_size"])
    if mip.get("external"):
        cache_path = Path(texture.get("cache_path") or "")
        if not cache_path.exists():
            return {"status": "missing_texture_cache", "cache_path": str(cache_path)}
        with cache_path.open("rb") as handle:
            handle.seek(int(mip["file_offset"]))
            blob = handle.read(stored_size)
        source_cache = str(cache_path)
    else:
        inline_offset = mip.get("inline_offset")
        if inline_offset is None:
            return {"status": "missing_inline_offset"}
        blob = virt[int(inline_offset) : int(inline_offset) + stored_size]
        source_cache = str(DECOMPRESSED_WAR)
    if len(blob) != stored_size:
        return {"status": "short_bulk_read", "read": len(blob), "expected": stored_size}
    if mip.get("compressed"):
        try:
            group = heavy.decode_group_at(blob, 0)
        except Exception as exc:
            return {"status": "compressed_bulk_decode_failed", "stored_size": stored_size, "error": repr(exc)}
        if not group:
            return {"status": "compressed_bulk_decode_failed", "stored_size": stored_size}
        payload = group["data"]
    else:
        payload = blob
    if fmt in SUPPORTED_FOURCC:
        expected_size = expected_dxt_size(width, height, fmt)
        header = dds_header_fourcc(width, height, SUPPORTED_FOURCC[fmt], len(payload), 1)
        expected_label = "expected_dxt_size"
    elif fmt == "PF_A8R8G8B8":
        expected_size = width * height * 4
        header = dds_header_uncompressed(
            width,
            height,
            width * 4,
            0x41,  # DDPF_RGB | DDPF_ALPHAPIXELS, little-endian A8R8G8B8 payload.
            32,
            0x00FF0000,
            0x0000FF00,
            0x000000FF,
            0xFF000000,
        )
        expected_label = "expected_argb8_size"
    elif fmt == "PF_G8":
        expected_size = width * height
        header = dds_header_uncompressed(
            width,
            height,
            width,
            0x20000,  # DDPF_LUMINANCE
            8,
            0x000000FF,
            0,
            0,
            0,
        )
        expected_label = "expected_g8_size"
    else:
        return {"status": "unsupported_format", "reason": fmt}
    if len(payload) != expected_size and len(payload) != uncompressed_size:
        return {
            "status": "payload_size_mismatch",
            "payload_size": len(payload),
            expected_label: expected_size,
            "uncompressed_size": uncompressed_size,
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    dds_path = out_dir / texture_filename(texture["full_path"], width, height, fmt)
    if not dds_path.exists():
        dds_path.write_bytes(header + payload)
    return {
        "status": "dds_exported",
        "dds_path": str(dds_path),
        "width": width,
        "height": height,
        "format": fmt,
        "mip_index": mip["mip_index"],
        "payload_size": len(payload),
        "source_cache": source_cache,
        "file_offset": mip.get("file_offset", ""),
        "inline_offset": mip.get("inline_offset", ""),
    }


def export_exact_texture(
    heavy: Any,
    virt: bytes,
    texture_by_path: dict[str, dict[str, Any]],
    full_path: str,
    out_dds: Path,
    out_png: Path,
    max_texture_size: int,
) -> dict[str, Any]:
    texture = texture_by_path.get(full_path.lower())
    row: dict[str, Any] = {
        "full_path": full_path,
        "found_texture_export": texture is not None,
        "export": {},
        "png": {},
        "normal_reconstruction": {},
    }
    if texture is None:
        row["status"] = "missing_texture_export"
        return row
    row.update(
        {
            "package": texture.get("package", ""),
            "export_index": texture.get("export_index", ""),
            "class_name": texture.get("class_name", ""),
            "object_name": texture.get("object_name", ""),
            "format": texture.get("format", ""),
            "size_x": texture.get("size_x", ""),
            "size_y": texture.get("size_y", ""),
            "texture_cache": texture.get("texture_cache", ""),
            "source_file_path": texture.get("source_file_path", ""),
            "decode_status": texture.get("decode_status", ""),
        }
    )
    mip = choose_mip(texture, max_texture_size)
    if not mip:
        row["status"] = "no_mip_selected"
        return row
    row["selected_mip"] = mip
    exported = export_texture_dds(heavy, virt, texture, mip, out_dds)
    row["export"] = exported
    if exported.get("status") != "dds_exported":
        row["status"] = "dds_export_failed"
        return row
    dds_path = Path(str(exported.get("dds_path", "")))
    try:
        png_path = png_for_texture(out_png, full_path, dds_path)
        png = convert_dds_to_png(dds_path, png_path)
        row["png"] = png
        if str(texture.get("format") or "") == "PF_DXN":
            recon_path = png_path.with_name(png_path.stem + "__BC5_reconstructed_OpenGL.png")
            row["normal_reconstruction"] = reconstruct_bc5_normal(png_path, recon_path)
    except Exception as exc:  # noqa: BLE001
        row["png"] = {"status": "conversion_failed", "error": repr(exc)}
    row["status"] = "decoded"
    return row


def make_cube_strip(name: str, faces: dict[int, Path], out_png: Path) -> dict[str, Any]:
    if set(faces) != set(range(6)):
        return {"status": "missing_faces", "present_faces": sorted(faces)}
    images = [Image.open(faces[index]).convert("RGBA") for index in range(6)]
    width = max(image.width for image in images)
    height = max(image.height for image in images)
    strip = Image.new("RGBA", (width * 6, height), (0, 0, 0, 255))
    for index, image in enumerate(images):
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.BICUBIC)
        strip.paste(image, (index * width, 0))
    out = out_png / f"{name}_cube_strip_posx_negx_posy_negy_posz_negz.png"
    strip.save(out, "PNG", optimize=True)
    return {"status": "created", "path": str(out), "size": list(strip.size), "face_size": [width, height]}


def make_equirect(name: str, faces: dict[int, Path], out_png: Path, width: int = 2048, height: int = 1024) -> dict[str, Any]:
    if set(faces) != set(range(6)):
        return {"status": "missing_faces", "present_faces": sorted(faces)}
    face_arrays = []
    for index in range(6):
        image = Image.open(faces[index]).convert("RGB")
        if image.size[0] != image.size[1]:
            side = min(image.size)
            image = image.resize((side, side), Image.Resampling.BICUBIC)
        face_arrays.append(np.asarray(image, dtype=np.uint8))
    side = face_arrays[0].shape[0]

    y, x = np.mgrid[0:height, 0:width]
    lon = (x / width) * (2.0 * math.pi) - math.pi
    lat = (0.5 - (y / height)) * math.pi
    cos_lat = np.cos(lat)
    dx = cos_lat * np.cos(lon)
    dy = cos_lat * np.sin(lon)
    dz = np.sin(lat)
    absx = np.abs(dx)
    absy = np.abs(dy)
    absz = np.abs(dz)

    face_index = np.zeros((height, width), dtype=np.int16)
    uc = np.zeros((height, width), dtype=np.float32)
    vc = np.zeros((height, width), dtype=np.float32)

    mask = (absx >= absy) & (absx >= absz) & (dx >= 0)
    face_index[mask] = 0
    uc[mask] = -dy[mask] / absx[mask]
    vc[mask] = -dz[mask] / absx[mask]

    mask = (absx >= absy) & (absx >= absz) & (dx < 0)
    face_index[mask] = 1
    uc[mask] = dy[mask] / absx[mask]
    vc[mask] = -dz[mask] / absx[mask]

    mask = (absy > absx) & (absy >= absz) & (dy >= 0)
    face_index[mask] = 2
    uc[mask] = dx[mask] / absy[mask]
    vc[mask] = -dz[mask] / absy[mask]

    mask = (absy > absx) & (absy >= absz) & (dy < 0)
    face_index[mask] = 3
    uc[mask] = -dx[mask] / absy[mask]
    vc[mask] = -dz[mask] / absy[mask]

    mask = (absz > absx) & (absz > absy) & (dz >= 0)
    face_index[mask] = 4
    uc[mask] = dy[mask] / absz[mask]
    vc[mask] = dx[mask] / absz[mask]

    mask = (absz > absx) & (absz > absy) & (dz < 0)
    face_index[mask] = 5
    uc[mask] = dy[mask] / absz[mask]
    vc[mask] = -dx[mask] / absz[mask]

    px = np.clip(((uc + 1.0) * 0.5 * (side - 1)).astype(np.int32), 0, side - 1)
    py = np.clip(((vc + 1.0) * 0.5 * (side - 1)).astype(np.int32), 0, side - 1)
    out = np.empty((height, width, 3), dtype=np.uint8)
    for index, face in enumerate(face_arrays):
        mask = face_index == index
        out[mask] = face[py[mask], px[mask]]

    out_path = out_png / f"{name}_cube_equirect_posx_negx_posy_negy_posz_negz.png"
    Image.fromarray(out, mode="RGB").save(out_path, "PNG", optimize=True)
    return {
        "status": "created",
        "path": str(out_path),
        "size": [width, height],
        "face_order_assumption": "CubemapFace0..5 = +X,-X,+Y,-Y,+Z,-Z",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--max-texture-size", type=int, default=2048)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_root = Path(args.out_root)
    out_dds = out_root / "dds"
    out_png = out_root / "png"
    out_dds.mkdir(parents=True, exist_ok=True)
    out_png.mkdir(parents=True, exist_ok=True)

    heavy, virt, textures = build_texture_inventory_from_decompressed()
    texture_by_path = {str(texture.get("full_path", "")).lower(): texture for texture in textures}

    target_paths = []
    target_paths.extend(CLOSE_WATER_TEXTURES)
    target_paths.extend(VISTA_OCEAN_TEXTURES)
    for prefix in CUBE_FACE_PREFIXES.values():
        target_paths.extend(f"{prefix}.CubemapFace{index}" for index in range(6))

    decoded: dict[str, dict[str, Any]] = {}
    for full_path in target_paths:
        decoded[full_path] = export_exact_texture(
            heavy,
            virt,
            texture_by_path,
            full_path,
            out_dds,
            out_png,
            int(args.max_texture_size),
        )

    cube_outputs: dict[str, Any] = {}
    for cube_name, prefix in CUBE_FACE_PREFIXES.items():
        faces: dict[int, Path] = {}
        for index in range(6):
            row = decoded.get(f"{prefix}.CubemapFace{index}", {})
            png_text = str(row.get("png", {}).get("png_path", ""))
            if png_text:
                png_path = Path(png_text)
                if png_path.is_file():
                    faces[index] = png_path
        cube_outputs[cube_name] = {
            "strip": make_cube_strip(cube_name, faces, out_png),
            "equirect": make_equirect(cube_name, faces, out_png),
        }

    missing = [
        path
        for path in EXPECTED_BUT_NOT_DIRECT_TEXTURE2D
        if path.lower() not in texture_by_path
    ]
    proof = {
        "status": "native_gridlock_water_ocean_textures_decoded",
        "target": "Gears of War Reloaded MP_Gridlock.war",
        "cooked_root": str(COOKED_ROOT),
        "map_dir": str(MAP_DIR),
        "visual_csv": str(VISUAL_CSV),
        "decompressed_war": str(DECOMPRESSED_WAR),
        "out_root": str(out_root),
        "dds_dir": str(out_dds),
        "png_dir": str(out_png),
        "decoded_count": sum(1 for row in decoded.values() if row.get("status") == "decoded"),
        "target_count": len(target_paths),
        "missing_or_failed": {path: row for path, row in decoded.items() if row.get("status") != "decoded"},
        "decoded": decoded,
        "cube_outputs": cube_outputs,
        "expected_non_direct_texture2d_refs": EXPECTED_BUT_NOT_DIRECT_TEXTURE2D,
        "expected_non_direct_texture2d_missing_exact_exports": missing,
        "notes": [
            "T_OceanFoam, T_CloudTile_Delta, close water foam/cusp masks, and cube faces are real MP_Gridlock Texture2D exports.",
            "The previous material cache skipped several of these as unknown role textures, so this pass exports them by exact full path.",
            "TextureCube refs are represented by their six Texture2D CubemapFace exports and an equirectangular helper generated for Blender.",
            "FX_Utility_Delta.Textures.clouds_01 is referenced by material graphs but does not appear as an exact Texture2D export in MP_Gridlock.war.",
        ],
    }
    proof_path = out_root / "gridlock_native_water_ocean_decode_2026_08_15.json"
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof": str(proof_path), "decoded": proof["decoded_count"], "targets": len(target_paths)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
