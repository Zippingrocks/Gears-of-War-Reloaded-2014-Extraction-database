#!/usr/bin/env python3
"""Audit the current MP_Gridlock blend for visible texture failure classes.

This runs inside Blender. It deliberately focuses on things the earlier
green-light audits can miss: visible Model_* BSP leftovers, inline proxy cards
that are using a mask/specular texture as their apparent diffuse, and image
materials that are not driven by the intended render UV layer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore


RENDER_UV_LAYER = "UV_Source_Render"
MODEL_RE = re.compile(r"^Model_\d+__MP_Gridlock\.war__\d+", re.IGNORECASE)
BAD_DIFFUSE_TOKENS = ("specular", "normal", "_mask", "mask_", "opacity", "alpha")


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    return parser.parse_args(passthrough)


def visible(obj: bpy.types.Object) -> bool:
    return not bool(obj.hide_viewport or obj.hide_render)


def image_rows(material: bpy.types.Material | None) -> list[dict[str, Any]]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    rows: list[dict[str, Any]] = []
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        linked_uv_maps: list[str] = []
        vector = node.inputs.get("Vector")
        if vector is not None:
            for link in vector.links:
                src = link.from_node
                if src.bl_idname == "ShaderNodeUVMap":
                    linked_uv_maps.append(str(getattr(src, "uv_map", "")))
        rows.append(
            {
                "node": node.name,
                "label": node.label,
                "image": image.name if image else "",
                "filepath": image.filepath if image else "",
                "colorspace": image.colorspace_settings.name if image else "",
                "linked_uv_maps": sorted(set(linked_uv_maps)),
            }
        )
    return rows


def material_row(material: bpy.types.Material | None) -> dict[str, Any]:
    if material is None:
        return {"material": "", "missing": True}
    rows = image_rows(material)
    image_names = " ".join(row["image"].lower() for row in rows)
    diffuse_candidates = [
        row
        for row in rows
        if "diffuse" in row["node"].lower()
        or "diffuse" in row["label"].lower()
        or "_tex" in row["image"].lower()
        or "delta_tex" in row["image"].lower()
    ]
    only_bad_images = bool(rows) and all(any(token in row["image"].lower() for token in BAD_DIFFUSE_TOKENS) for row in rows)
    non_render_uv = [
        row
        for row in rows
        if row["linked_uv_maps"] and RENDER_UV_LAYER not in row["linked_uv_maps"]
    ]
    return {
        "material": material.name,
        "ue_material_path": material.get("ue_material_path", ""),
        "source_material_path": material.get("source_material_path", ""),
        "decoded_diffuse_dds": material.get("decoded_diffuse_dds", ""),
        "texture_coordinate_uv_map": material.get("texture_coordinate_uv_map", ""),
        "image_count": len(rows),
        "image_names": [row["image"] for row in rows],
        "has_diffuse_candidate": bool(diffuse_candidates),
        "only_mask_spec_normal_images": only_bad_images,
        "non_render_uv_image_nodes": non_render_uv,
        "image_rows": rows,
        "inline_material": material.name.startswith("INLINE_PROXY__"),
        "image_name_blob": image_names[:500],
    }


def uv_stats(mesh: bpy.types.Mesh, layer_name: str) -> dict[str, Any]:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return {"exists": False}
    values = [(float(data.uv.x), float(data.uv.y)) for data in layer.data]
    if not values:
        return {"exists": True, "count": 0}
    us = [uv[0] for uv in values]
    vs = [uv[1] for uv in values]
    outside = sum(1 for u, v in values if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0))
    return {
        "exists": True,
        "count": len(values),
        "unique_rounded": len({(round(u, 4), round(v, 4)) for u, v in values}),
        "u_min": round(min(us), 6),
        "u_max": round(max(us), 6),
        "v_min": round(min(vs), 6),
        "v_max": round(max(vs), 6),
        "outside_0_1_ratio": round(outside / max(1, len(values)), 6),
    }


def object_row(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data if obj.type == "MESH" else None
    materials = [material_row(slot.material) for slot in obj.material_slots]
    return {
        "object": obj.name,
        "type": obj.type,
        "visible": visible(obj),
        "collection_names": [col.name for col in obj.users_collection],
        "mesh": mesh.name if mesh else "",
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
        "mesh_ue_full_path": mesh.get("ue_full_path", "") if mesh else "",
        "mesh_source_class": mesh.get("source_class", "") if mesh else "",
        "uv_layers": [layer.name for layer in mesh.uv_layers] if mesh else [],
        "active_uv": mesh.uv_layers.active.name if mesh and mesh.uv_layers.active else "",
        "uv_source_render": uv_stats(mesh, RENDER_UV_LAYER) if mesh else {},
        "polygon_count": len(mesh.polygons) if mesh else 0,
        "material_slot_count": len(obj.material_slots),
        "materials": materials,
    }


def main() -> int:
    args = parse_args()
    visible_meshes = [obj for obj in bpy.data.objects if obj.type == "MESH" and visible(obj)]
    visible_models = [obj for obj in visible_meshes if MODEL_RE.match(obj.name)]
    hidden_models = [obj for obj in bpy.data.objects if obj.type == "MESH" and MODEL_RE.match(obj.name) and not visible(obj)]

    textured_but_suspect: list[dict[str, Any]] = []
    inline_suspect: list[dict[str, Any]] = []
    non_render_uv: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    for obj in visible_meshes:
        obj_suspect = False
        inline_obj_suspect = False
        non_render_obj = False
        for slot in obj.material_slots:
            mat = material_row(slot.material)
            if mat.get("inline_material") and mat.get("only_mask_spec_normal_images"):
                inline_obj_suspect = True
            if mat.get("image_count") and not mat.get("has_diffuse_candidate") and mat.get("only_mask_spec_normal_images"):
                obj_suspect = True
            if mat.get("non_render_uv_image_nodes"):
                non_render_obj = True
        if obj_suspect and len(textured_but_suspect) < 80:
            textured_but_suspect.append(object_row(obj))
        if inline_obj_suspect and len(inline_suspect) < 80:
            inline_suspect.append(object_row(obj))
        if non_render_obj and len(non_render_uv) < 80:
            non_render_uv.append(object_row(obj))
        if obj_suspect:
            counters["visible_textured_but_mask_spec_only"] += 1
        if inline_obj_suspect:
            counters["visible_inline_mask_spec_only"] += 1
        if non_render_obj:
            counters["visible_non_render_uv_materials"] += 1

    proof = {
        "blend_path": bpy.data.filepath,
        "summary": {
            "visible_meshes": len(visible_meshes),
            "visible_model_star": len(visible_models),
            "hidden_model_star": len(hidden_models),
            **dict(counters),
        },
        "visible_model_star_objects": [object_row(obj) for obj in visible_models[:120]],
        "hidden_model_star_names": [obj.name for obj in hidden_models[:200]],
        "textured_but_suspect_samples": textured_but_suspect,
        "inline_suspect_samples": inline_suspect,
        "non_render_uv_samples": non_render_uv,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
