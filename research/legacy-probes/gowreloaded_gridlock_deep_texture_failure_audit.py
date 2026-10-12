#!/usr/bin/env python3
"""Deep audit for the remaining MP_Gridlock texture failures in Blender.

This is intentionally stricter than the earlier node-link audits: it compares
scene objects, source StaticMesh rows, section cache rows, material cache rows,
UV layers, and material node links in one proof file.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import bpy  # type: ignore


TARGET_NAMES = [
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "SDStitchingProxy_2409_StaticMesh__27021",
    "SDStitchingProxy_2755_StaticMesh__27221",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
    "Model_5__MP_Gridlock.war__11545",
    "Model_6__MP_Gridlock.war__11546",
    "Model_27__MP_Gridlock.war__11527",
    "Model_313__MP_Gridlock.war__11531",
    "Model_195__MP_Gridlock.war__11514",
    "Model_26__MP_Gridlock.war__11526",
    "Model_14__MP_Gridlock.war__11506",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--section-cache", required=True)
    parser.add_argument("--material-cache", required=True)
    parser.add_argument("--proof-out", required=True)
    return parser.parse_args(passthrough)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_name(name: str) -> str:
    return re.sub(r"\.\d{3}$", "", name)


def is_visible(obj: bpy.types.Object) -> bool:
    return not obj.hide_get() and not obj.hide_viewport and not obj.hide_render


def object_asset_key(obj: bpy.types.Object) -> str:
    return str(obj.get("ue_static_mesh_path", "") or obj.data.get("ue_full_path", "")).strip().lower()


def uv_stats(mesh: bpy.types.Mesh, layer_name: str) -> dict[str, Any]:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return {"exists": False}
    values = [(float(row.uv.x), float(row.uv.y)) for row in layer.data]
    finite = [(u, v) for u, v in values if math.isfinite(u) and math.isfinite(v)]
    if not finite:
        return {"exists": True, "valid": 0}
    us = [u for u, _v in finite]
    vs = [v for _u, v in finite]
    return {
        "exists": True,
        "valid": len(finite),
        "unique_rounded": len({(round(u, 4), round(v, 4)) for u, v in finite}),
        "u_min": round(min(us), 8),
        "u_max": round(max(us), 8),
        "v_min": round(min(vs), 8),
        "v_max": round(max(vs), 8),
        "span_u": round(max(us) - min(us), 8),
        "span_v": round(max(vs) - min(vs), 8),
        "outside_0_1_ratio": round(sum(1 for u, v in finite if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0) / len(finite), 6),
    }


def image_nodes(mat: bpy.types.Material | None) -> list[dict[str, Any]]:
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return []
    rows: list[dict[str, Any]] = []
    for node in mat.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        linked_uvs: list[str] = []
        linked_from: list[str] = []
        for link in mat.node_tree.links:
            if link.to_node == node and link.to_socket == node.inputs.get("Vector"):
                linked_from.append(link.from_node.bl_idname)
                if link.from_node.bl_idname == "ShaderNodeUVMap":
                    linked_uvs.append(str(getattr(link.from_node, "uv_map", "")))
                elif link.from_node.bl_idname == "ShaderNodeMapping":
                    for inner in mat.node_tree.links:
                        if inner.to_node == link.from_node and inner.to_socket == link.from_node.inputs.get("Vector"):
                            linked_from.append(f"Mapping<-{inner.from_node.bl_idname}")
                            if inner.from_node.bl_idname == "ShaderNodeUVMap":
                                linked_uvs.append(str(getattr(inner.from_node, "uv_map", "")))
        image = getattr(node, "image", None)
        rows.append(
            {
                "node": node.name,
                "label": node.label,
                "image": image.name if image else "",
                "filepath": image.filepath if image else "",
                "linked_from": linked_from,
                "linked_uv_maps": linked_uvs,
                "colorspace": image.colorspace_settings.name if image else "",
            }
        )
    return rows


def material_summary(mat: bpy.types.Material | None) -> dict[str, Any]:
    if mat is None:
        return {"material": None}
    return {
        "material": mat.name,
        "source_material_path": mat.get("ue_material_path", ""),
        "texture_coordinate_uv_map": mat.get("texture_coordinate_uv_map", ""),
        "gridlock_render_uv_clone_source_material": mat.get("gridlock_render_uv_clone_source_material", ""),
        "image_nodes": image_nodes(mat),
    }


def polygon_slot_counts(mesh: bpy.types.Mesh) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for poly in mesh.polygons:
        counts[str(poly.material_index)] += 1
    return dict(sorted(counts.items(), key=lambda row: int(row[0])))


def object_summary(obj: bpy.types.Object, clean_by_path: dict[str, dict[str, str]], section_cache: dict[str, Any], material_cache: dict[str, Any]) -> dict[str, Any]:
    key = object_asset_key(obj)
    clean = clean_by_path.get(key, {})
    section_entry = section_cache.get(key, {})
    expected_materials = [section.get("material_path", "") for section in section_entry.get("sections", [])]
    expected_bound = []
    for path in expected_materials:
        binding = material_cache.get(str(path).lower()) or {}
        roles = binding.get("roles") or {}
        expected_bound.append(
            {
                "material_path": path,
                "parent": binding.get("parent_material_path", ""),
                "diffuse": (roles.get("diffuse") or {}).get("texture_full_path", ""),
                "normal": (roles.get("normal") or {}).get("texture_full_path", ""),
                "specular": (roles.get("specular") or {}).get("texture_full_path", ""),
            }
        )
    mesh = obj.data
    return {
        "object": obj.name,
        "base_name": clean_name(obj.name),
        "visible": is_visible(obj),
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "type": obj.type,
        "mesh": mesh.name,
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
        "ue_full_path": mesh.get("ue_full_path", ""),
        "extract_status": clean.get("extract_status", ""),
        "static_vertex_element_size": (json.loads(clean.get("geometry_json", "{}") or "{}").get("static_vertex_buffer") or {}).get("element_size", ""),
        "material_slot_count": len(obj.material_slots),
        "material_slots": [material_summary(slot.material) for slot in obj.material_slots],
        "polygon_material_index_counts": polygon_slot_counts(mesh),
        "uv_layers": [layer.name for layer in mesh.uv_layers],
        "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
        "uv_stats": {layer.name: uv_stats(mesh, layer.name) for layer in mesh.uv_layers},
        "vertex_color_layers": [layer.name for layer in getattr(mesh, "color_attributes", [])],
        "section_cache_status": section_entry.get("status", ""),
        "section_layout": section_entry.get("layout_name", ""),
        "expected_section_materials": expected_bound,
    }


def main() -> int:
    args = parse_args()
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {row.get("full_path", "").lower(): row for row in clean_rows}
    section_cache = read_json(Path(args.section_cache))
    material_cache = read_json(Path(args.material_cache))

    scene_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    visible_model_leftovers = [
        obj.name
        for obj in scene_objects
        if is_visible(obj) and obj.name.startswith("Model_")
    ]
    visible_staticmesh_without_source_key = [
        obj.name
        for obj in scene_objects
        if is_visible(obj) and obj.get("ue_static_mesh_path", "") and object_asset_key(obj) not in clean_by_path
    ]

    by_clean: dict[str, list[bpy.types.Object]] = defaultdict(list)
    by_base: dict[str, list[bpy.types.Object]] = defaultdict(list)
    for obj in scene_objects:
        by_clean[clean_name(obj.name)].append(obj)
        if object_asset_key(obj):
            by_base[Path(str(obj.get("ue_static_mesh_path", "")).replace(".", "/")).name.lower()].append(obj)

    target_rows = []
    for target in TARGET_NAMES:
        matches = by_clean.get(clean_name(target), [])
        if not matches:
            matches = [obj for obj in scene_objects if clean_name(target).lower() in obj.name.lower()]
        target_rows.append(
            {
                "target": target,
                "matches": [object_summary(obj, clean_by_path, section_cache, material_cache) for obj in matches[:12]],
                "match_count": len(matches),
            }
        )

    uv_source_render_missing = [
        obj.name
        for obj in scene_objects
        if is_visible(obj) and obj.get("ue_static_mesh_path", "") and obj.data.uv_layers.get("UV_Source_Render") is None
    ]

    material_parent_counts: Counter[str] = Counter()
    material_samples_by_parent: dict[str, list[str]] = defaultdict(list)
    for mat_key, binding in material_cache.items():
        parent = str(binding.get("parent_material_path") or "")
        material_parent_counts[parent] += 1
        if len(material_samples_by_parent[parent]) < 8:
            material_samples_by_parent[parent].append(str(binding.get("material_path") or mat_key))

    proof = {
        "blend_path": bpy.data.filepath,
        "summary": {
            "mesh_objects": len(scene_objects),
            "visible_model_leftovers": len(visible_model_leftovers),
            "visible_staticmesh_without_source_key": len(visible_staticmesh_without_source_key),
            "visible_staticmesh_missing_uv_source_render": len(uv_source_render_missing),
            "material_cache_entries": len(material_cache),
            "section_cache_entries": len(section_cache),
        },
        "visible_model_leftovers": visible_model_leftovers[:200],
        "visible_staticmesh_without_source_key": visible_staticmesh_without_source_key[:100],
        "visible_staticmesh_missing_uv_source_render": uv_source_render_missing[:100],
        "targets": target_rows,
        "material_parent_counts": [
            {"parent": parent, "count": count, "samples": material_samples_by_parent[parent]}
            for parent, count in material_parent_counts.most_common(80)
        ],
        "status": "gridlock_deep_texture_failure_audit_complete",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
