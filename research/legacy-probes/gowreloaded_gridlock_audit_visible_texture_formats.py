#!/usr/bin/env python3
"""Audit image file formats used by visible Gridlock mesh materials."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    return parser.parse_args(passthrough)


def image_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    except Exception:
        return str(image.filepath or "")


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]


def main() -> int:
    args = parse_args()
    ext_counts: Counter[str] = Counter()
    material_counts: Counter[str] = Counter()
    dds_alias_samples: list[dict[str, Any]] = []
    non_png_samples: list[dict[str, Any]] = []
    visible_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render]

    for obj in visible_meshes:
        for slot_index, slot in enumerate(obj.material_slots):
            material = slot.material
            for node in image_nodes(material):
                path = image_path(getattr(node, "image", None))
                ext = Path(path).suffix.lower() or "<none>"
                ext_counts[ext] += 1
                if material is not None:
                    material_counts[material.name] += 1
                row = {
                    "object": obj.name,
                    "slot": slot_index,
                    "material": material.name if material else "",
                    "node": node.name,
                    "path": path,
                }
                if ext == ".dds" and "texture_aliases_dds" in path.lower() and len(dds_alias_samples) < 80:
                    dds_alias_samples.append(row)
                if ext != ".png" and len(non_png_samples) < 80:
                    non_png_samples.append(row)

    proof = {
        "blend_path": bpy.data.filepath,
        "visible_mesh_objects": len(visible_meshes),
        "image_node_extension_counts": dict(sorted(ext_counts.items())),
        "materials_with_image_nodes": len(material_counts),
        "dds_alias_sample_count": len(dds_alias_samples),
        "dds_alias_samples": dds_alias_samples,
        "non_png_samples": non_png_samples,
        "status": "visible_texture_format_audit_complete",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("visible_mesh_objects", "image_node_extension_counts", "dds_alias_sample_count", "status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
