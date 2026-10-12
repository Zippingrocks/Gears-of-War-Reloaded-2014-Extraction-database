#!/usr/bin/env python3
"""Probe Blender loading of selected DDS texture files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


TEXTURES = [
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\textures_dds\T_COG_City_EBA_02.COG_City_EBA_FrontStairCase2_Clean_Delta_Tex__2048x2048_PF_DXT5_07c69c6624b8.dds",
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\textures_dds\T_Delta_Gridlock_01.tilefloor_concrete_dirty_01_Delta_Tex__2048x2048_PF_DXT5_d73fe47c37aa.dds",
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\textures_dds\T_COG_City_Architecture.COG_UndentedCar1_Frame_Delta_Delta_Tex__2048x2048_PF_DXT5_fe4bb6dc3e1e.dds",
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Texture_Cache\textures_dds\T_Neutral_Vehicles.vehicle_neutral_sedan_01a_Delta_Tex__2048x2048_PF_DXT5_18c14490ea91.dds",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--textures", nargs="*", default=TEXTURES)
    return parser.parse_args(passthrough)


def main() -> None:
    args = parse_args()
    rows = []
    for texture in args.textures:
        path = Path(texture)
        row = {
            "path": str(path),
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else 0,
            "loaded": False,
            "error": "",
            "image_name": "",
            "image_size": [],
            "image_filepath": "",
        }
        try:
            image = bpy.data.images.load(str(path), check_existing=True)
            row["loaded"] = image is not None
            row["image_name"] = image.name if image else ""
            row["image_size"] = list(image.size) if image else []
            row["image_filepath"] = image.filepath if image else ""
        except Exception as exc:
            row["error"] = repr(exc)
        rows.append(row)
    with Path(args.proof_out).open("w", encoding="utf-8") as handle:
        json.dump({"scene": bpy.data.filepath, "textures": rows}, handle, indent=2)


if __name__ == "__main__":
    main()
