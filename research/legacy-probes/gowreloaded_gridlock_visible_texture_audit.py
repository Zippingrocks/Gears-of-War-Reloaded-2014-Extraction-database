#!/usr/bin/env python3
"""Visible-object texture audit for the Gridlock Blender scene."""

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


def material_images(material: bpy.types.Material | None) -> list[str]:
    if material is None or not material.use_nodes:
        return []
    out: list[str] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            out.append(str(Path(node.image.filepath).resolve(strict=False)))
    return out


def is_visible_final(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    return all(not coll.hide_viewport and not coll.hide_render for coll in obj.users_collection)


def is_debug_color(material: bpy.types.Material | None) -> bool:
    if material is None:
        return False
    r, g, b, _a = material.diffuse_color
    return (r > 0.85 and b > 0.85 and g < 0.65) or (g > 0.85 and r < 0.65 and b < 0.65)


def main() -> int:
    args = parse_args()
    visible_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and is_visible_final(obj)]
    hidden_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not is_visible_final(obj)]
    untextured_rows: list[dict[str, Any]] = []
    material_counter: Counter[str] = Counter()
    debug_rows: list[dict[str, Any]] = []
    for obj in visible_meshes:
        bad: list[str] = []
        debug: list[str] = []
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            if not material_images(mat):
                bad.append(mat.name)
                material_counter[mat.name] += 1
            if is_debug_color(mat):
                debug.append(mat.name)
        if bad:
            untextured_rows.append(
                {
                    "object": obj.name,
                    "materials": sorted(set(bad)),
                    "ue_static_mesh_path": obj.get("ue_static_mesh_path", ""),
                    "bsp_full_path": obj.get("bsp_model_full_path", ""),
                    "bsp_visibility_layer": obj.get("bsp_visibility_layer", ""),
                }
            )
        if debug:
            debug_rows.append({"object": obj.name, "materials": sorted(set(debug))})
    target = bpy.data.objects.get("SDStitchingProxy_2661_StaticMesh__27170")
    proof = {
        "blend_path": bpy.data.filepath,
        "visible_mesh_objects": len(visible_meshes),
        "hidden_mesh_objects": len(hidden_meshes),
        "visible_untextured_mesh_object_count": len(untextured_rows),
        "visible_untextured_material_counts": dict(material_counter.most_common()),
        "visible_untextured_samples": untextured_rows[:120],
        "visible_debug_color_mesh_object_count": len(debug_rows),
        "visible_debug_color_samples": debug_rows[:80],
        "images": len(bpy.data.images),
        "dds_images": sum(1 for img in bpy.data.images if bpy.path.abspath(img.filepath).lower().endswith(".dds")),
        "png_images": sum(1 for img in bpy.data.images if bpy.path.abspath(img.filepath).lower().endswith(".png")),
        "target_proxy": {
            "exists": bool(target),
            "materials": [slot.material.name for slot in target.material_slots if slot.material] if target else [],
            "uv_layers": [layer.name for layer in target.data.uv_layers] if target and target.type == "MESH" else [],
            "active_uv": target.data.uv_layers.active.name if target and target.type == "MESH" and target.data.uv_layers.active else "",
            "image_paths": [
                image
                for slot in target.material_slots
                if slot.material
                for image in material_images(slot.material)
            ]
            if target
            else [],
        },
        "status": "visible_texture_audit_complete",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True)[:10000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
