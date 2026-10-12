#!/usr/bin/env python3
"""Audit that Gridlock static mesh image nodes read UV_Source_Render."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


RENDER_UV_LAYER = "UV_Source_Render"

TARGET_OBJECT_NAMES = [
    "bsp_gridlock_road_b_SMesh__26847",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "MS_Neutral_Sedan_SMesh__27672",
    "SDStitchingProxy_2755_StaticMesh__27221",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
    "SDStitchingProxy_2661_StaticMesh__27170",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    return parser.parse_args(passthrough)


def object_is_visible(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    return all(not coll.hide_viewport and not coll.hide_render for coll in obj.users_collection)


def material_is_inline(material: bpy.types.Material | None) -> bool:
    if material is None:
        return False
    return (
        material.name.startswith("INLINE_PROXY__")
        or material.name.startswith("INLINE_ASSET_NATIVE__")
        or "inline_proxy_material_repair" in material
        or "inline_asset_material_repair" in material
    )


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [
        node
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)
    ]


def linked_uv_maps_for_image_node(node: bpy.types.Node) -> list[str]:
    vector_input = node.inputs.get("Vector")
    if vector_input is None:
        return []
    maps: list[str] = []
    for link in vector_input.links:
        source = link.from_node
        if source.bl_idname == "ShaderNodeUVMap":
            maps.append(str(getattr(source, "uv_map", "")))
        else:
            maps.append(source.bl_idname)
    return maps


def audit_material(material: bpy.types.Material | None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for node in image_nodes(material):
        rows.append(
            {
                "image_node": node.name,
                "image": Path(bpy.path.abspath(node.image.filepath)).name if getattr(node, "image", None) else "",
                "linked_uv_maps": linked_uv_maps_for_image_node(node),
            }
        )
    bad = [
        row
        for row in rows
        if rows and RENDER_UV_LAYER not in row["linked_uv_maps"]
    ]
    return {
        "image_node_count": len(rows),
        "image_nodes_linked_to_render_uv": len(rows) - len(bad),
        "bad_image_nodes": bad,
        "rows": rows,
    }


def main() -> int:
    args = parse_args()
    checked_slots = 0
    bad_slots: list[dict[str, Any]] = []
    render_uv_objects = 0
    target_audit: dict[str, Any] = {}

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not object_is_visible(obj):
            continue
        if obj.data.uv_layers.get(RENDER_UV_LAYER) is None:
            continue
        render_uv_objects += 1
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material_is_inline(material):
                continue
            material_audit = audit_material(material)
            if not material_audit["image_node_count"]:
                continue
            checked_slots += 1
            if material_audit["bad_image_nodes"]:
                bad_slots.append(
                    {
                        "object": obj.name,
                        "material": material.name,
                        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
                        "bad_image_nodes": material_audit["bad_image_nodes"],
                    }
                )

    for name in TARGET_OBJECT_NAMES:
        obj = bpy.data.objects.get(name)
        if obj is None:
            target_audit[name] = {"exists": False}
            continue
        rows = []
        for slot in obj.material_slots:
            material = slot.material
            rows.append(
                {
                    "material": material.name if material else "",
                    "inline_material": material_is_inline(material),
                    "audit": audit_material(material),
                }
            )
        target_audit[name] = {
            "exists": True,
            "static_mesh_path": obj.get("ue_static_mesh_path", ""),
            "visible": object_is_visible(obj),
            "uv_layers": [layer.name for layer in obj.data.uv_layers] if obj.type == "MESH" else [],
            "active_uv": obj.data.uv_layers.active.name if obj.type == "MESH" and obj.data.uv_layers.active else "",
            "materials": rows,
        }

    proof = {
        "blend_path": bpy.data.filepath,
        "render_uv_layer": RENDER_UV_LAYER,
        "visible_objects_with_render_uv": render_uv_objects,
        "checked_non_inline_image_material_slots": checked_slots,
        "bad_non_inline_image_material_slots": len(bad_slots),
        "bad_slot_samples": bad_slots[:80],
        "target_audit": target_audit,
        "status": "gridlock_render_uv_link_audit_complete",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0 if not bad_slots else 1


if __name__ == "__main__":
    raise SystemExit(main())
