#!/usr/bin/env python3
"""Prepare Blender-safe textures for Gridlock Model_2's source BSP material."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
TEXTURE_CACHE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\textures_dds"
)
DETAIL_FALLBACK = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\04_SOURCE_EVIDENCE\PC\GOW4_2016_PC\01_GENERATED_HOS_EXPORTS\EXPORT\Game\Legacy\Delta\packages\COG_City_BaseMaterials\COG_City_BaseMat_Crackle3_CP_DetailNormal.png"
)

DIFFUSE_DDS = TEXTURE_CACHE / "T_COG_City_Ephyra3.EphyraCity_Stairtech01_PE_Tex__2048x2048_PF_DXT1_f15fba3873e3.dds"
NORMAL_DDS = TEXTURE_CACHE / "T_COG_City_Ephyra3.EphyraCity_Stairtech01_PE_Normal__2048x2048_PF_DXT1_30df884b4ae0.dds"


def stats(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGBA")
    stat = ImageStat.Stat(image)
    return {
        "path": str(path),
        "size": list(image.size),
        "mode": image.mode,
        "mean": [round(float(value), 4) for value in stat.mean],
        "stddev": [round(float(value), 4) for value in stat.stddev],
        "extrema": [[int(lo), int(hi)] for lo, hi in stat.extrema],
    }


def convert_diffuse(src: Path, dst: Path) -> dict[str, Any]:
    image = Image.open(src).convert("RGBA")
    image.save(dst)
    return {"src": str(src), "dst": str(dst), "conversion": "dds_rgba_to_png_srgb", "stats": stats(dst)}


def convert_normal_directx_to_opengl(src: Path, dst: Path) -> dict[str, Any]:
    image = Image.open(src).convert("RGBA")
    r, g, b, a = image.split()
    g = g.point(lambda value: 255 - value)
    out = Image.merge("RGBA", (r, g, b, a))
    out.save(dst)
    return {
        "src": str(src),
        "dst": str(dst),
        "conversion": "normal_map_green_channel_inverted_for_blender_opengl",
        "source_stats": stats(src),
        "output_stats": stats(dst),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(SCENE_DIR / "model2_source_shader_textures"))
    parser.add_argument("--proof-out", default=str(SCENE_DIR / "gridlock_model2_source_shader_textures_2026_08_15.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path in (DIFFUSE_DDS, NORMAL_DDS, DETAIL_FALLBACK) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing required source texture(s): {missing}")

    diffuse = out_dir / "EphyraCity_Stairtech01_PE_Tex__source_diffuse.png"
    normal = out_dir / "EphyraCity_Stairtech01_PE_Normal__OpenGL_Gflip.png"
    detail = out_dir / "crackle3_detail_ogl.png"

    proof = {
        "status": "prepared",
        "policy": (
            "Diffuse is converted losslessly from the Reloaded Gridlock material-cache DDS. "
            "The main normal is a Reloaded Gridlock TC_Normalmap DDS converted from DirectX to Blender/OpenGL green. "
            "The Crackle3 detail normal is source-referenced by Reloaded MP_Gridlock but missing from the local Reloaded cache; "
            "this uses the same asset name from the GOW4 Legacy Delta export as an explicitly labeled fallback."
        ),
        "outputs": {
            "diffuse": convert_diffuse(DIFFUSE_DDS, diffuse),
            "main_normal_opengl": convert_normal_directx_to_opengl(NORMAL_DDS, normal),
            "detail_normal_fallback_opengl": convert_normal_directx_to_opengl(DETAIL_FALLBACK, detail),
        },
    }
    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"status": "prepared", "proof_out": str(proof_out), "out_dir": str(out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
