#!/usr/bin/env python3
"""Audit Gridlock BSP Model placement/origin state inside a Blender scene."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


DEFAULT_TARGETS = [
    "Model_5__MP_Gridlock.war__11545",
    "Model_27__MP_Gridlock.war__11527",
    "Model_313__MP_Gridlock.war__11531",
    "Model_195__MP_Gridlock.war__11514",
    "Model_26__MP_Gridlock.war__11526",
    "Model_14__MP_Gridlock.war__11506",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--bsp-instance-csv", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--targets", default=",".join(DEFAULT_TARGETS))
    return parser.parse_args(passthrough)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def object_name_from_row(row: dict[str, str]) -> str:
    export_index = int(row.get("export_index") or 0)
    return f"{row.get('object_name', 'Model')}__{row.get('package', '')}__{export_index:05d}"


def vec3(values: Any) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


def polygon_used_local_bounds(mesh: bpy.types.Mesh) -> tuple[Vector, Vector, Vector, int]:
    used_indices: set[int] = set()
    for polygon in mesh.polygons:
        used_indices.update(polygon.vertices)
    if not used_indices:
        zero = Vector((0.0, 0.0, 0.0))
        return zero, zero, zero, 0

    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for index in used_indices:
        co = mesh.vertices[index].co
        mins.x = min(mins.x, co.x)
        mins.y = min(mins.y, co.y)
        mins.z = min(mins.z, co.z)
        maxs.x = max(maxs.x, co.x)
        maxs.y = max(maxs.y, co.y)
        maxs.z = max(maxs.z, co.z)
    center = (mins + maxs) * 0.5
    return mins, maxs, center, len(used_indices)


def all_vertex_local_bounds(mesh: bpy.types.Mesh) -> tuple[Vector, Vector, Vector]:
    if not mesh.vertices:
        zero = Vector((0.0, 0.0, 0.0))
        return zero, zero, zero
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for vertex in mesh.vertices:
        co = vertex.co
        mins.x = min(mins.x, co.x)
        mins.y = min(mins.y, co.y)
        mins.z = min(mins.z, co.z)
        maxs.x = max(maxs.x, co.x)
        maxs.y = max(maxs.y, co.y)
        maxs.z = max(maxs.z, co.z)
    center = (mins + maxs) * 0.5
    return mins, maxs, center


def is_visible_final(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    return all(not coll.hide_viewport and not coll.hide_render for coll in obj.users_collection)


def object_audit(object_name: str, row: dict[str, str] | None = None) -> dict[str, Any]:
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"object_name": object_name, "exists": False, "source_row_found": row is not None}
    if obj.type != "MESH" or not obj.data:
        return {"object_name": object_name, "exists": True, "type": obj.type}

    mesh = obj.data
    used_mins, used_maxs, used_center, used_count = polygon_used_local_bounds(mesh)
    all_mins, all_maxs, all_center = all_vertex_local_bounds(mesh)
    world_used_center = obj.matrix_world @ used_center
    world_all_center = obj.matrix_world @ all_center
    source_origin = None
    source_extent = None
    if row:
        source_origin = [row.get("origin_x", ""), row.get("origin_y", ""), row.get("origin_z", "")]
        source_extent = [row.get("extent_x", ""), row.get("extent_y", ""), row.get("extent_z", "")]
    return {
        "object_name": object_name,
        "exists": True,
        "type": obj.type,
        "collections": sorted(coll.name for coll in obj.users_collection),
        "visible_final": is_visible_final(obj),
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "location": vec3(obj.location),
        "polygon_used_local_center": vec3(used_center),
        "all_vertex_local_center": vec3(all_center),
        "polygon_used_world_center": vec3(world_used_center),
        "all_vertex_world_center": vec3(world_all_center),
        "polygon_used_local_bounds": {"min": vec3(used_mins), "max": vec3(used_maxs)},
        "all_vertex_local_bounds": {"min": vec3(all_mins), "max": vec3(all_maxs)},
        "polygon_used_vertex_count": used_count,
        "all_vertex_count": len(mesh.vertices),
        "polygon_count": len(mesh.polygons),
        "material_slots": [slot.material.name for slot in obj.material_slots if slot.material],
        "bsp_model_origin_repair_applied": str(obj.get("bsp_model_origin_repair_applied", "")),
        "bsp_model_owner_type": str(obj.get("bsp_model_owner_type", "")),
        "bsp_model_owner_path": str(obj.get("bsp_model_owner_path", "")),
        "bsp_visibility_layer": str(obj.get("bsp_visibility_layer", "")),
        "source_origin_ue": source_origin,
        "source_extent_ue": source_extent,
    }


def main() -> int:
    args = parse_args()
    rows = read_csv(Path(args.bsp_instance_csv))
    rows_by_object = {object_name_from_row(row): row for row in rows}
    direct_rows = [
        row
        for row in rows
        if row.get("owner_type") == "PersistentLevel_direct_model"
    ]
    direct_objects = [
        object_name_from_row(row)
        for row in direct_rows
        if bpy.data.objects.get(object_name_from_row(row)) is not None
    ]
    target_names = [name.strip() for name in args.targets.split(",") if name.strip()]

    location_clusters: Counter[str] = Counter()
    collection_counts: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()
    unrepaired_direct: list[str] = []
    nonzero_used_centers: list[str] = []

    for object_name in direct_objects:
        obj = bpy.data.objects[object_name]
        used_mins, used_maxs, used_center, _used_count = polygon_used_local_bounds(obj.data)
        location_clusters[str(vec3(obj.location))] += 1
        owner_counts[str(obj.get("bsp_model_owner_type", "")) or rows_by_object[object_name].get("owner_type", "")] += 1
        for coll in obj.users_collection:
            collection_counts[coll.name] += 1
        if str(obj.get("bsp_model_origin_repair_applied", "")).lower() != "true":
            unrepaired_direct.append(object_name)
        if used_center.length > 0.0001:
            nonzero_used_centers.append(object_name)

    proof = {
        "blend_path": bpy.data.filepath,
        "bsp_instance_csv": str(Path(args.bsp_instance_csv)),
        "summary": {
            "atlas_rows": len(rows),
            "persistent_level_direct_model_rows": len(direct_rows),
            "persistent_level_direct_model_objects_in_scene": len(direct_objects),
            "persistent_level_direct_unrepaired_count": len(unrepaired_direct),
            "persistent_level_direct_nonzero_polygon_center_count": len(nonzero_used_centers),
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
        "direct_collection_counts": dict(collection_counts.most_common()),
        "direct_owner_counts": dict(owner_counts.most_common()),
        "direct_location_clusters": dict(location_clusters.most_common(12)),
        "targets": [object_audit(name, rows_by_object.get(name)) for name in target_names],
        "unrepaired_direct_samples": unrepaired_direct[:40],
        "nonzero_polygon_center_samples": nonzero_used_centers[:40],
        "status": "bsp_model_placement_audit_complete",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
