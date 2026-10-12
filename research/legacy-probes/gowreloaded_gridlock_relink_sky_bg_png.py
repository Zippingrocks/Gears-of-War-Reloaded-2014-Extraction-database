#!/usr/bin/env python3
"""Relink the Gridlock sky backdrop material from DDS to a converted PNG."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


SKY_DDS_TOKEN = "skydome_gridlock_bg_01"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--png", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def image_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    except Exception:
        return str(image.filepath or "")


def main() -> int:
    args = parse_args()
    png_path = Path(args.png)
    image = bpy.data.images.load(str(png_path), check_existing=True)
    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass

    repaired: list[dict[str, Any]] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None or not material.use_nodes or material.node_tree is None:
                continue
            for node in material.node_tree.nodes:
                if node.bl_idname != "ShaderNodeTexImage" or not getattr(node, "image", None):
                    continue
                before = image_path(node.image)
                if SKY_DDS_TOKEN not in before.lower() or not before.lower().endswith(".dds"):
                    continue
                node.image = image
                material["gridlock_sky_bg_png"] = str(png_path)
                repaired.append({"object": obj.name, "material": material.name, "node": node.name, "before": before, "after": str(png_path)})

    proof = {
        "blend_path": bpy.data.filepath,
        "png": str(png_path),
        "repaired_nodes": repaired,
        "status": "sky_bg_png_relinked" if repaired else "no_sky_bg_dds_nodes_found",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"repaired_nodes": len(repaired), "status": proof["status"]}, indent=2))
    if repaired and not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
