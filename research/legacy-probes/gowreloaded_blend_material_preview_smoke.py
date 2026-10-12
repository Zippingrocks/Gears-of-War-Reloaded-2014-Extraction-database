#!/usr/bin/env python3
"""UI smoke test: switch any 3D view to Material Preview, redraw, and quit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    return parser.parse_args(passthrough)


def main() -> None:
    args = parse_args()
    switched = 0
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "MATERIAL"
                    switched += 1
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=4)
    proof = {
        "blend_path": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "view3d_spaces_switched_to_material_preview": switched,
        "objects": len(bpy.data.objects),
        "images": len(bpy.data.images),
        "dds_images": sum(1 for image in bpy.data.images if bpy.path.abspath(image.filepath).lower().endswith(".dds")),
        "png_images": sum(1 for image in bpy.data.images if bpy.path.abspath(image.filepath).lower().endswith(".png")),
        "status": "material_preview_redraw_completed",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))
    bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
