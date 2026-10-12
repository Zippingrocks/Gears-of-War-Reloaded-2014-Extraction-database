#!/usr/bin/env python3
"""Audit the live Gridlock Blender scene for texture/material repair status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


TARGET = "SDStitchingProxy_2661_StaticMesh__27170"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    return parser.parse_args(passthrough)


def material_images(material: bpy.types.Material | None) -> list[str]:
    if material is None or not material.use_nodes:
        return []
    images: list[str] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            images.append(str(Path(node.image.filepath).resolve(strict=False)))
    return images


def material_uv_maps(material: bpy.types.Material | None) -> list[str]:
    if material is None or not material.use_nodes:
        return []
    maps: list[str] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeUVMap":
            maps.append(str(getattr(node, "uv_map", "") or ""))
    return maps


def is_debug_color(material: bpy.types.Material | None) -> bool:
    if material is None:
        return False
    r, g, b, _a = material.diffuse_color
    return (r > 0.85 and b > 0.85 and g < 0.65) or (g > 0.85 and r < 0.65 and b < 0.65)


def mesh_entry(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data if obj.type == "MESH" else None
    mats = [slot.material for slot in obj.material_slots if slot.material]
    return {
        "object": obj.name,
        "mesh": mesh.name if mesh else "",
        "polygons": len(mesh.polygons) if mesh else 0,
        "vertices": len(mesh.vertices) if mesh else 0,
        "uv_layers": [layer.name for layer in mesh.uv_layers] if mesh else [],
        "active_uv": mesh.uv_layers.active.name if mesh and mesh.uv_layers.active else "",
        "materials": [mat.name for mat in mats],
        "material_images": {mat.name: material_images(mat) for mat in mats},
        "material_uv_maps": {mat.name: material_uv_maps(mat) for mat in mats},
        "debug_color_materials": [mat.name for mat in mats if is_debug_color(mat)],
        "custom_props": {key: obj[key] for key in obj.keys()},
    }


def main() -> int:
    args = parse_args()
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    image_paths = [str(Path(img.filepath).resolve(strict=False)) for img in bpy.data.images if img.filepath]
    material_image_counts = {
        mat.name: len(material_images(mat))
        for mat in bpy.data.materials
        if mat
    }
    no_image_materials = sorted(name for name, count in material_image_counts.items() if count == 0)
    debug_materials = sorted(mat.name for mat in bpy.data.materials if is_debug_color(mat))
    mesh_objects_with_no_material = sorted(obj.name for obj in mesh_objects if not obj.material_slots)
    mesh_objects_with_untextured_slots = []
    for obj in mesh_objects:
        bad = []
        for slot in obj.material_slots:
            if slot.material and len(material_images(slot.material)) == 0:
                bad.append(slot.material.name)
        if bad:
            mesh_objects_with_untextured_slots.append({"object": obj.name, "materials": sorted(set(bad))})
    target_obj = bpy.data.objects.get(TARGET)
    proof = {
        "blend_path": bpy.data.filepath,
        "objects": len(bpy.data.objects),
        "mesh_objects": len(mesh_objects),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "dds_images": sum(1 for path in image_paths if path.lower().endswith(".dds")),
        "png_images": sum(1 for path in image_paths if path.lower().endswith(".png")),
        "no_image_material_count": len(no_image_materials),
        "no_image_material_samples": no_image_materials[:80],
        "debug_material_count": len(debug_materials),
        "debug_material_samples": debug_materials[:80],
        "mesh_objects_with_no_material_count": len(mesh_objects_with_no_material),
        "mesh_objects_with_no_material_samples": mesh_objects_with_no_material[:80],
        "mesh_objects_with_untextured_slot_count": len(mesh_objects_with_untextured_slots),
        "mesh_objects_with_untextured_slot_samples": mesh_objects_with_untextured_slots[:80],
        "target": mesh_entry(target_obj) if target_obj else None,
        "status": "scene_texture_audit_complete",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True)[:8000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
