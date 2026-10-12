#!/usr/bin/env python3
"""Convert the remaining visible Gridlock sky DDS image to PNG and relink it."""

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
    parser.add_argument("--png-out-dir", required=True)
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


def visible_sky_nodes() -> list[tuple[bpy.types.Object, bpy.types.Material, bpy.types.Node, bpy.types.Image]]:
    rows: list[tuple[bpy.types.Object, bpy.types.Material, bpy.types.Node, bpy.types.Image]] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
            continue
        if "sky" not in obj.name.lower():
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None or not material.use_nodes or material.node_tree is None:
                continue
            for node in material.node_tree.nodes:
                if node.bl_idname != "ShaderNodeTexImage" or not getattr(node, "image", None):
                    continue
                image = node.image
                path = image_path(image)
                if SKY_DDS_TOKEN in path.lower() and path.lower().endswith(".dds"):
                    rows.append((obj, material, node, image))
    return rows


def convert_image(image: bpy.types.Image, out_dir: Path) -> Path:
    source = Path(image_path(image))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (source.stem + ".png")
    image.filepath_raw = str(out)
    image.file_format = "PNG"
    image.save()
    return out


def main() -> int:
    args = parse_args()
    rows = visible_sky_nodes()
    converted: dict[str, str] = {}
    repaired: list[dict[str, Any]] = []
    for obj, material, node, image in rows:
        before = image_path(image)
        if before not in converted:
            converted[before] = str(convert_image(image, Path(args.png_out_dir)))
        png_path = converted[before]
        replacement = bpy.data.images.load(png_path, check_existing=True)
        try:
            replacement.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        node.image = replacement
        material["gridlock_sky_dds_to_png"] = png_path
        repaired.append(
            {
                "object": obj.name,
                "material": material.name,
                "node": node.name,
                "before": before,
                "after": png_path,
            }
        )
    proof = {
        "blend_path": bpy.data.filepath,
        "converted_sources": converted,
        "repaired_nodes": repaired,
        "status": "sky_dds_converted_to_png" if repaired else "no_sky_dds_nodes_found",
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
