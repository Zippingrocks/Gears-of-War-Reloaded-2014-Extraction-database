#!/usr/bin/env python3
"""Repair Gridlock BSP Model origins using rendered polygon bounds.

The first origin repair centered BSP Model objects with all decoded vertices.
Some Reloaded BSP exports carry unused points, so the rendered faces can still
sit offset from the object origin. This pass rebases each object around the
vertices actually referenced by polygons and preserves world-space geometry.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


TARGET_OBJECTS = {
    "Model_5__MP_Gridlock.war__11545",
    "Model_27__MP_Gridlock.war__11527",
    "Model_313__MP_Gridlock.war__11531",
    "Model_195__MP_Gridlock.war__11514",
    "Model_26__MP_Gridlock.war__11526",
    "Model_14__MP_Gridlock.war__11506",
}
REPAIR_VERSION = "polygon_used_bounds_v2_2026_08_14"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--bsp-instance-csv", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def object_name_from_row(row: dict[str, str]) -> str:
    export_index = int(row.get("export_index") or 0)
    return f"{row.get('object_name', 'Model')}__{row.get('package', '')}__{export_index:05d}"


def safe_collection_name(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text).strip("_") or "Unclassified"


def find_collection(name: str) -> bpy.types.Collection | None:
    for collection in bpy.data.collections:
        if collection.name == name:
            return collection
    return None


def get_child(parent: bpy.types.Collection, name: str) -> bpy.types.Collection:
    existing = parent.children.get(name)
    if existing:
        return existing
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def choose_bsp_parent() -> bpy.types.Collection:
    existing = find_collection("BSP_Model")
    if existing:
        return existing
    root = find_collection("MP_Gridlock_Reloaded_Native_Scene")
    if root:
        return get_child(root, "BSP_Model")
    return get_child(bpy.context.scene.collection, "BSP_Model")


def vec(values: Any) -> list[float]:
    return [round(float(values[0]), 6), round(float(values[1]), 6), round(float(values[2]), 6)]


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
    return mins, maxs, (mins + maxs) * 0.5


def polygon_used_local_bounds(mesh: bpy.types.Mesh) -> tuple[Vector, Vector, Vector, int]:
    used_indices: set[int] = set()
    for polygon in mesh.polygons:
        used_indices.update(polygon.vertices)
    if not used_indices:
        mins, maxs, center = all_vertex_local_bounds(mesh)
        return mins, maxs, center, 0

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
    return mins, maxs, (mins + maxs) * 0.5, len(used_indices)


def bounds_json(mins: Vector, maxs: Vector, center: Vector, used_count: int | None = None) -> str:
    payload: dict[str, Any] = {
        "min": [round(float(v), 8) for v in mins],
        "max": [round(float(v), 8) for v in maxs],
        "center": [round(float(v), 8) for v in center],
    }
    if used_count is not None:
        payload["used_vertex_count"] = used_count
    return json.dumps(payload, ensure_ascii=True)


def rebase_origin_to_polygon_center(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    used_mins_before, used_maxs_before, used_center_before, used_count_before = polygon_used_local_bounds(mesh)
    all_mins_before, all_maxs_before, all_center_before = all_vertex_local_bounds(mesh)
    old_world = obj.matrix_world.copy()
    world_center = old_world @ used_center_before

    if (
        str(obj.get("bsp_model_origin_repair_version", "")) == REPAIR_VERSION
        and used_center_before.length <= 0.000001
    ):
        return {
            "status": "already_repaired_v2",
            "origin_before": vec(old_world.translation),
            "origin_after": vec(old_world.translation),
            "polygon_used_local_center_before": vec(used_center_before),
            "polygon_used_local_center_after": vec(used_center_before),
            "all_vertex_local_center_before": vec(all_center_before),
            "all_vertex_local_center_after": vec(all_center_before),
            "polygon_used_vertex_count": used_count_before,
        }

    if used_center_before.length > 0.000001:
        for vertex in mesh.vertices:
            vertex.co -= used_center_before
        mesh.update(calc_edges=False)
        new_world = old_world.copy()
        new_world.translation = world_center
        obj.matrix_world = new_world

    used_mins_after, used_maxs_after, used_center_after, used_count_after = polygon_used_local_bounds(mesh)
    all_mins_after, all_maxs_after, all_center_after = all_vertex_local_bounds(mesh)

    obj["bsp_model_origin_repair_applied"] = "true"
    obj["bsp_model_origin_repair_version"] = REPAIR_VERSION
    obj["bsp_model_origin_repair"] = "BSP Model origin rebased to rendered polygon-used bounds center; world-space faces preserved"
    obj["bsp_model_origin_before_blender"] = json.dumps(vec(old_world.translation), ensure_ascii=True)
    obj["bsp_model_origin_after_blender"] = json.dumps(vec(obj.matrix_world.translation), ensure_ascii=True)
    obj["bsp_model_polygon_used_local_bounds_before"] = bounds_json(
        used_mins_before, used_maxs_before, used_center_before, used_count_before
    )
    obj["bsp_model_polygon_used_local_bounds_after"] = bounds_json(
        used_mins_after, used_maxs_after, used_center_after, used_count_after
    )
    obj["bsp_model_all_vertex_local_bounds_before"] = bounds_json(all_mins_before, all_maxs_before, all_center_before)
    obj["bsp_model_all_vertex_local_bounds_after"] = bounds_json(all_mins_after, all_maxs_after, all_center_after)

    return {
        "status": "rebased_v2" if used_center_before.length > 0.000001 else "tagged_repaired_v2",
        "origin_before": vec(old_world.translation),
        "origin_after": vec(obj.matrix_world.translation),
        "polygon_used_local_center_before": vec(used_center_before),
        "polygon_used_local_center_after": vec(used_center_after),
        "all_vertex_local_center_before": vec(all_center_before),
        "all_vertex_local_center_after": vec(all_center_after),
        "polygon_used_vertex_count": used_count_before,
    }


def link_to_owner_collection(obj: bpy.types.Object, owner_type: str) -> str:
    parent = choose_bsp_parent()
    if owner_type == "PersistentLevel_direct_model":
        target = get_child(parent, "PersistentLevel_Direct_Models_SourcePlaced")
    else:
        target = get_child(parent, f"NonRenderable_{safe_collection_name(owner_type)}")
    if obj.name not in target.objects:
        target.objects.link(obj)
    for collection in list(obj.users_collection):
        if collection != target and collection.name in {"BSP_Model", "BSP_Model_Visual_Candidates"}:
            collection.objects.unlink(obj)
    return target.name


def main() -> int:
    args = parse_args()
    rows = read_csv(Path(args.bsp_instance_csv))
    rows_by_object = {object_name_from_row(row): row for row in rows}
    repaired = 0
    already = 0
    tagged = 0
    missing_persistent: list[str] = []
    samples: list[dict[str, Any]] = []
    target_audits: list[dict[str, Any]] = []
    owner_counts: dict[str, int] = {}

    for object_name, row in rows_by_object.items():
        obj = bpy.data.objects.get(object_name)
        owner_type = row.get("owner_type") or "Unknown"
        if obj is None:
            if owner_type == "PersistentLevel_direct_model":
                missing_persistent.append(object_name)
            continue
        if obj.type != "MESH" or not obj.data:
            continue

        owner_counts[owner_type] = owner_counts.get(owner_type, 0) + 1
        result = rebase_origin_to_polygon_center(obj)
        collection_name = link_to_owner_collection(obj, owner_type)
        obj["bsp_model_owner_path"] = row.get("owner_path", "")
        obj["bsp_model_owner_type"] = owner_type
        obj["bsp_model_instance_atlas_source"] = str(Path(args.bsp_instance_csv))
        obj["bsp_model_source_bounds_ue"] = json.dumps(
            {
                "origin": [row.get("origin_x", ""), row.get("origin_y", ""), row.get("origin_z", "")],
                "extent": [row.get("extent_x", ""), row.get("extent_y", ""), row.get("extent_z", "")],
            },
            ensure_ascii=True,
        )

        if result["status"] == "rebased_v2":
            repaired += 1
        elif result["status"] == "already_repaired_v2":
            already += 1
        else:
            tagged += 1

        sample = {
            "object_name": object_name,
            "export_index": row.get("export_index", ""),
            "full_path": row.get("full_path", ""),
            "owner_type": owner_type,
            "collection": collection_name,
            "source_origin_ue": [row.get("origin_x", ""), row.get("origin_y", ""), row.get("origin_z", "")],
            "source_extent_ue": [row.get("extent_x", ""), row.get("extent_y", ""), row.get("extent_z", "")],
            **result,
        }
        if len(samples) < 16:
            samples.append(sample)
        if object_name in TARGET_OBJECTS:
            target_audits.append(sample)

    proof = {
        "blend_path": bpy.data.filepath,
        "bsp_instance_csv": str(Path(args.bsp_instance_csv)),
        "repair_version": REPAIR_VERSION,
        "repair_policy": "Rebase BSP Model object origins to bounds of vertices referenced by rendered polygons; preserve all world-space face positions; move direct models into BSP_Model/PersistentLevel_Direct_Models_SourcePlaced.",
        "summary": {
            "atlas_rows": len(rows),
            "scene_bsp_objects_matched": repaired + already + tagged,
            "rebased_v2_objects": repaired,
            "already_repaired_v2_objects": already,
            "tagged_repaired_v2_objects": tagged,
            "missing_persistent_direct_models": missing_persistent,
            "owner_counts_in_scene": owner_counts,
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
        "target_audits": sorted(target_audits, key=lambda item: item["object_name"]),
        "samples": samples,
    }
    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if repaired or already or tagged else 1


if __name__ == "__main__":
    raise SystemExit(main())
