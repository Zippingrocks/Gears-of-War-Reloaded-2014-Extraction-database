#!/usr/bin/env python3
"""Repair Gridlock BSP Model object origins/organization in an existing blend.

The Reloaded BSP OBJ exporter writes PersistentLevel Model vertices in decoded
world coordinates. The first Blender builder kept those mesh coordinates on
identity objects, which leaves many Model_* object origins piled together even
though the polygons are source-placed. This rebases each BSP Model mesh around
its decoded bounds center while preserving exact world-space polygon positions.
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


TARGET_OBJECT = "Model_313__MP_Gridlock.war__11531"


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


def object_name_from_row(row: dict[str, str]) -> str:
    package = row.get("package", "")
    export_index = int(row.get("export_index") or 0)
    return f"{row.get('object_name', 'Model')}__{package}__{export_index:05d}"


def mesh_local_bounds(mesh: bpy.types.Mesh) -> tuple[Vector, Vector, Vector]:
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


def rebase_origin_to_bounds_center(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    mins_before, maxs_before, center_local = mesh_local_bounds(mesh)
    old_world = obj.matrix_world.copy()
    world_center = old_world @ center_local
    distance_before = float(obj.location.length)

    if str(obj.get("bsp_model_origin_repair_applied", "")).lower() == "true":
        return {
            "status": "already_repaired",
            "origin_before": [round(float(v), 6) for v in obj.location],
            "origin_after": [round(float(v), 6) for v in obj.location],
            "local_bounds_center_before": [round(float(v), 6) for v in center_local],
            "local_bounds_center_after": [0.0, 0.0, 0.0],
            "origin_distance_before": round(distance_before, 6),
        }

    if center_local.length > 0.000001:
        for vertex in mesh.vertices:
            vertex.co -= center_local
        mesh.update(calc_edges=False)
        new_world = old_world.copy()
        new_world.translation = world_center
        obj.matrix_world = new_world

    mins_after, maxs_after, center_after = mesh_local_bounds(mesh)
    obj["bsp_model_origin_repair_applied"] = "true"
    obj["bsp_model_origin_repair"] = "world-coordinate BSP vertices rebased to object-local bounds center; visible polygons preserved"
    obj["bsp_model_origin_before_blender"] = json.dumps([round(float(v), 8) for v in old_world.translation])
    obj["bsp_model_origin_after_blender"] = json.dumps([round(float(v), 8) for v in obj.matrix_world.translation])
    obj["bsp_model_local_bounds_before"] = json.dumps(
        {
            "min": [round(float(v), 8) for v in mins_before],
            "max": [round(float(v), 8) for v in maxs_before],
            "center": [round(float(v), 8) for v in center_local],
        },
        ensure_ascii=True,
    )
    obj["bsp_model_local_bounds_after"] = json.dumps(
        {
            "min": [round(float(v), 8) for v in mins_after],
            "max": [round(float(v), 8) for v in maxs_after],
            "center": [round(float(v), 8) for v in center_after],
        },
        ensure_ascii=True,
    )
    return {
        "status": "rebased",
        "origin_before": [round(float(v), 6) for v in old_world.translation],
        "origin_after": [round(float(v), 6) for v in obj.matrix_world.translation],
        "local_bounds_center_before": [round(float(v), 6) for v in center_local],
        "local_bounds_center_after": [round(float(v), 6) for v in center_after],
        "origin_distance_before": round(distance_before, 6),
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
        if collection != target and collection.name == "BSP_Model":
            collection.objects.unlink(obj)
    return target.name


def main() -> int:
    args = parse_args()
    rows = read_csv(Path(args.bsp_instance_csv))
    rows_by_object = {object_name_from_row(row): row for row in rows}
    repaired = 0
    already = 0
    missing: list[str] = []
    samples: list[dict[str, Any]] = []
    target_audit: dict[str, Any] = {}
    owner_counts: dict[str, int] = {}

    for object_name, row in rows_by_object.items():
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            if row.get("owner_type") == "PersistentLevel_direct_model":
                missing.append(object_name)
            continue
        if obj.type != "MESH" or not obj.data:
            continue
        owner_type = row.get("owner_type") or "Unknown"
        owner_counts[owner_type] = owner_counts.get(owner_type, 0) + 1
        result = rebase_origin_to_bounds_center(obj)
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
        if result["status"] == "rebased":
            repaired += 1
        elif result["status"] == "already_repaired":
            already += 1
        if len(samples) < 16 or object_name == TARGET_OBJECT:
            samples.append(
                {
                    "object_name": object_name,
                    "export_index": row.get("export_index", ""),
                    "owner_type": owner_type,
                    "collection": collection_name,
                    **result,
                }
            )
        if object_name == TARGET_OBJECT:
            target_audit = {
                "object_name": object_name,
                "export_index": row.get("export_index", ""),
                "full_path": row.get("full_path", ""),
                "owner_type": owner_type,
                "owner_path": row.get("owner_path", ""),
                "collection": collection_name,
                "source_origin_ue": [row.get("origin_x", ""), row.get("origin_y", ""), row.get("origin_z", "")],
                "source_extent_ue": [row.get("extent_x", ""), row.get("extent_y", ""), row.get("extent_z", "")],
                **result,
            }

    proof = {
        "blend_path": bpy.data.filepath,
        "bsp_instance_csv": str(Path(args.bsp_instance_csv)),
        "repair_policy": "BSP Model polygons were already decoded in world space; rebase object origins to source bounds centers and preserve polygon world positions.",
        "summary": {
            "atlas_rows": len(rows),
            "scene_bsp_objects_matched": repaired + already,
            "rebased_objects": repaired,
            "already_repaired_objects": already,
            "missing_persistent_direct_models": missing,
            "owner_counts_in_scene": owner_counts,
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
        "target_audit": target_audit,
        "samples": samples,
    }
    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if repaired or already else 1


if __name__ == "__main__":
    raise SystemExit(main())
