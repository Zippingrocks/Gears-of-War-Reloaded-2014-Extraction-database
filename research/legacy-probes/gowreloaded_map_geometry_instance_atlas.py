#!/usr/bin/env python3
"""Build a source-native geometry/model instance atlas for a Reloaded map."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


SOURCE_ATLAS = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_geometry_instance_atlas.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_instance_atlas_src", SOURCE_ATLAS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load atlas source: {SOURCE_ATLAS}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


src = load_source()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def compact(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def parse_json(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def finite_vec3(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    out: list[float] = []
    for item in value[:3]:
        try:
            val = float(item)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(val):
            return None
        out.append(val)
    return out


def matrix3_determinant(matrix: list[float]) -> float | None:
    if not isinstance(matrix, list) or len(matrix) < 16:
        return None
    a = matrix
    return (
        a[0] * (a[5] * a[10] - a[6] * a[9])
        - a[1] * (a[4] * a[10] - a[6] * a[8])
        + a[2] * (a[4] * a[9] - a[5] * a[8])
    )


def matrix_tail_ok(matrix: list[float]) -> bool | None:
    if not isinstance(matrix, list) or len(matrix) < 16:
        return None
    return abs(float(matrix[15]) - 1.0) <= 1e-4


def signed_component_scale(row: dict[str, str]) -> list[float] | None:
    value = parse_json(row.get("component_scale3d_json", ""), None)
    return finite_vec3(value)


def placement_transform_proof(row: dict[str, str]) -> dict[str, Any]:
    matrix = parse_json(row.get("matrix_json", ""), [])
    scale = signed_component_scale(row)
    proof: dict[str, Any] = {
        "has_matrix": isinstance(matrix, list) and len(matrix) >= 16,
        "matrix_tail_ok": "",
        "matrix_det3": "",
        "matrix_handedness": "",
        "component_scale_has_negative_axis": "",
        "component_scale_zero_axis": "",
        "source_transform_mode": "collection_matrix" if isinstance(matrix, list) and len(matrix) >= 16 else "actor_tags",
    }
    if proof["has_matrix"]:
        det = matrix3_determinant(matrix)
        proof["matrix_tail_ok"] = matrix_tail_ok(matrix)
        if det is not None:
            proof["matrix_det3"] = round(det, 8)
            if det < -1e-6:
                proof["matrix_handedness"] = "mirrored"
            elif det > 1e-6:
                proof["matrix_handedness"] = "normal"
            else:
                proof["matrix_handedness"] = "degenerate"
    if scale is not None:
        proof["component_scale_has_negative_axis"] = any(axis < 0 for axis in scale)
        proof["component_scale_zero_axis"] = any(abs(axis) < 1e-6 for axis in scale)
    return proof


def build_atlas(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix

    asset_rows = read_csv(Path(args.asset_csv))
    placement_rows = read_csv(Path(args.placement_csv))
    bsp_rows = read_csv(Path(args.bsp_csv))

    asset_by_path = src.make_asset_index(asset_rows)
    package_summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "package": "",
            "staticmesh_asset_defs": 0,
            "staticmesh_asset_decoded": 0,
            "placement_rows": 0,
            "mesh_bound_placements": 0,
            "staticmeshactor_rows": 0,
            "staticmeshcollectionactor_rows": 0,
            "unique_mesh_paths": set(),
            "unique_actor_paths": set(),
            "unresolved_mesh_refs": set(),
            "transform_anomalies": 0,
            "mirrored_matrix_rows": 0,
            "negative_component_scale_rows": 0,
            "bsp_model_exports": 0,
            "bsp_face_models": 0,
            "bsp_empty_models": 0,
            "bsp_not_decoded": 0,
            "bsp_triangles": 0,
        }
    )

    for asset in asset_rows:
        pkg = asset.get("package", "")
        ps = package_summary[pkg]
        ps["package"] = pkg
        ps["staticmesh_asset_defs"] += 1
        if asset.get("extract_status") != "not_decoded":
            ps["staticmesh_asset_decoded"] += 1

    mesh_summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "static_mesh_path": "",
            "instance_count": 0,
            "staticmeshactor_count": 0,
            "staticmeshcollectionactor_count": 0,
            "packages": set(),
            "actor_paths": set(),
            "component_paths": set(),
            "material_override_rows": 0,
            "locations": src.bbox_empty(),
            "approx_bounds": src.bbox_empty(),
            "sample_actors": [],
            "mirrored_matrix_rows": 0,
            "negative_component_scale_rows": 0,
        }
    )

    instance_out: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    transform_proof_counter: Counter[str] = Counter()

    for idx, placement in enumerate(placement_rows, start=1):
        pkg = placement.get("package", "")
        mesh_path = placement.get("static_mesh_path", "")
        kind = placement.get("placement_kind", "")
        actor_path = placement.get("actor_path", "")
        component_path = placement.get("component_path", "")
        asset_defs = asset_by_path.get(mesh_path, [])
        asset = asset_defs[0] if asset_defs else None
        loc = src.placement_location(placement)
        scale_abs = src.placement_scale(placement)
        scale_signed = signed_component_scale(placement)
        flags = src.transform_flags(placement, asset)
        materials = parse_json(placement.get("materials_json", ""), {})
        has_material_overrides = isinstance(materials, (dict, list)) and len(materials) > 0
        proof = placement_transform_proof(placement)
        if proof["has_matrix"]:
            transform_proof_counter["matrix_rows"] += 1
        else:
            transform_proof_counter["actor_tag_rows"] += 1
        if proof["matrix_handedness"] == "mirrored":
            transform_proof_counter["mirrored_matrix_rows"] += 1
        if proof["matrix_handedness"] == "degenerate":
            transform_proof_counter["degenerate_matrix_rows"] += 1
        if proof["component_scale_has_negative_axis"] is True:
            transform_proof_counter["negative_component_scale_rows"] += 1
        if proof["component_scale_zero_axis"] is True:
            transform_proof_counter["zero_component_scale_rows"] += 1
        if proof["matrix_tail_ok"] is False:
            transform_proof_counter["bad_matrix_tail_rows"] += 1

        ps = package_summary[pkg]
        ps["package"] = pkg
        ps["placement_rows"] += 1
        if mesh_path:
            ps["mesh_bound_placements"] += 1
            ps["unique_mesh_paths"].add(mesh_path)
        if actor_path:
            ps["unique_actor_paths"].add(actor_path)
        if kind == "StaticMeshActor":
            ps["staticmeshactor_rows"] += 1
        if kind == "StaticMeshCollectionActor":
            ps["staticmeshcollectionactor_rows"] += 1
        if "unresolved_static_mesh_asset" in flags:
            ps["unresolved_mesh_refs"].add(mesh_path)
        if flags:
            ps["transform_anomalies"] += 1
        if proof["matrix_handedness"] == "mirrored":
            ps["mirrored_matrix_rows"] += 1
        if proof["component_scale_has_negative_axis"] is True:
            ps["negative_component_scale_rows"] += 1

        ms = mesh_summary[mesh_path]
        ms["static_mesh_path"] = mesh_path
        ms["instance_count"] += 1
        ms["packages"].add(pkg)
        ms["actor_paths"].add(actor_path)
        ms["component_paths"].add(component_path)
        if kind == "StaticMeshActor":
            ms["staticmeshactor_count"] += 1
        if kind == "StaticMeshCollectionActor":
            ms["staticmeshcollectionactor_count"] += 1
        if has_material_overrides:
            ms["material_override_rows"] += 1
        if proof["matrix_handedness"] == "mirrored":
            ms["mirrored_matrix_rows"] += 1
        if proof["component_scale_has_negative_axis"] is True:
            ms["negative_component_scale_rows"] += 1
        if loc is not None:
            src.bbox_add_point(ms["locations"], loc)
        aabb = src.approx_instance_aabb(placement, asset)
        if aabb:
            src.bbox_add_aabb(ms["approx_bounds"], aabb[0], aabb[1])
        if len(ms["sample_actors"]) < 5:
            ms["sample_actors"].append(actor_path or placement.get("actor_name", ""))

        instance_record = {
            "row_id": idx,
            "package": pkg,
            "placement_kind": kind,
            "actor_export_index": placement.get("actor_export_index", ""),
            "actor_name": placement.get("actor_name", ""),
            "actor_path": actor_path,
            "component_ref": placement.get("component_ref", ""),
            "component_path": component_path,
            "static_mesh_path": mesh_path,
            "asset_resolved": bool(asset),
            "asset_definition_count": len(asset_defs),
            "asset_source_file_path": asset.get("source_file_path", "") if asset else "",
            "asset_extract_status": asset.get("extract_status", "") if asset else "",
            "asset_vertex_count": asset.get("vertex_count", "") if asset else "",
            "asset_triangle_count": asset.get("triangle_count", "") if asset else "",
            "location_x": loc[0] if loc else "",
            "location_y": loc[1] if loc else "",
            "location_z": loc[2] if loc else "",
            "scale_x_abs": scale_abs[0] if scale_abs else "",
            "scale_y_abs": scale_abs[1] if scale_abs else "",
            "scale_z_abs": scale_abs[2] if scale_abs else "",
            "component_scale_x_signed": scale_signed[0] if scale_signed else "",
            "component_scale_y_signed": scale_signed[1] if scale_signed else "",
            "component_scale_z_signed": scale_signed[2] if scale_signed else "",
            "has_material_overrides": has_material_overrides,
            "source_transform_mode": proof["source_transform_mode"],
            "has_matrix": proof["has_matrix"],
            "matrix_tail_ok": proof["matrix_tail_ok"],
            "matrix_det3": proof["matrix_det3"],
            "matrix_handedness": proof["matrix_handedness"],
            "component_scale_has_negative_axis": proof["component_scale_has_negative_axis"],
            "transform_flags": ";".join(flags),
        }
        instance_out.append(instance_record)
        if flags:
            anomalies.append(instance_record)

    unique_mesh_rows: list[dict[str, Any]] = []
    for mesh_path, row in mesh_summary.items():
        asset_defs = asset_by_path.get(mesh_path, [])
        first_asset = asset_defs[0] if asset_defs else {}
        loc_box = src.bbox_finish(row["locations"])
        bounds_box = src.bbox_finish(row["approx_bounds"])
        unique_mesh_rows.append(
            {
                "static_mesh_path": mesh_path,
                "instance_count": row["instance_count"],
                "staticmeshactor_count": row["staticmeshactor_count"],
                "staticmeshcollectionactor_count": row["staticmeshcollectionactor_count"],
                "package_count": len(row["packages"]),
                "packages": ";".join(sorted(row["packages"])),
                "unique_actor_count": len(row["actor_paths"]),
                "unique_component_count": len(row["component_paths"]),
                "asset_resolved": bool(asset_defs),
                "asset_definition_count": len(asset_defs),
                "asset_source_file_path": first_asset.get("source_file_path", ""),
                "asset_extract_status": first_asset.get("extract_status", ""),
                "asset_vertex_count": first_asset.get("vertex_count", ""),
                "asset_triangle_count": first_asset.get("triangle_count", ""),
                "material_override_rows": row["material_override_rows"],
                "mirrored_matrix_rows": row["mirrored_matrix_rows"],
                "negative_component_scale_rows": row["negative_component_scale_rows"],
                "location_bbox_json": compact(loc_box),
                "approx_world_bounds_json": compact(bounds_box),
                "sample_actors": ";".join(row["sample_actors"]),
            }
        )
    unique_mesh_rows.sort(key=lambda item: (-as_int(item["instance_count"]), item["static_mesh_path"]))

    bsp_out: list[dict[str, Any]] = []
    bsp_owner_counter: Counter[str] = Counter()
    bsp_status_counter: Counter[str] = Counter()
    bsp_bounds_anomaly_rows: list[dict[str, Any]] = []
    for row in bsp_rows:
        pkg = row.get("package", "")
        status = row.get("status", "")
        full_path = row.get("full_path", "")
        owner_path, owner_type = src.owner_type_from_model_path(full_path)
        bounds = parse_json(row.get("bounds_json", ""), {})
        origin = src.vec_from_bounds(bounds, "origin") if isinstance(bounds, dict) else None
        extent = src.vec_from_bounds(bounds, "extent") if isinstance(bounds, dict) else None
        triangle_count = as_int(row.get("triangle_count"))
        ps = package_summary[pkg]
        ps["package"] = pkg
        ps["bsp_model_exports"] += 1
        if status.startswith("bsp_model_faces_decoded"):
            ps["bsp_face_models"] += 1
            ps["bsp_triangles"] += triangle_count
        elif status == "empty_model":
            ps["bsp_empty_models"] += 1
        else:
            ps["bsp_not_decoded"] += 1
        bsp_owner_counter[owner_type] += 1
        bsp_status_counter[status] += 1
        out_row = {
            "package": pkg,
            "export_index": row.get("export_index", ""),
            "object_name": row.get("object_name", ""),
            "full_path": full_path,
            "owner_path": owner_path,
            "owner_type": owner_type,
            "status": status,
            "point_count": row.get("point_count", ""),
            "node_count": row.get("node_count", ""),
            "polygon_count": row.get("polygon_count", ""),
            "triangle_count": row.get("triangle_count", ""),
            "used_point_count": row.get("used_point_count", ""),
            "bounds_error": row.get("bounds_error", ""),
            "origin_x": origin[0] if origin else "",
            "origin_y": origin[1] if origin else "",
            "origin_z": origin[2] if origin else "",
            "extent_x": extent[0] if extent else "",
            "extent_y": extent[1] if extent else "",
            "extent_z": extent[2] if extent else "",
            "notes": row.get("notes", ""),
        }
        bsp_out.append(out_row)
        if status not in {"bsp_model_faces_decoded", "bsp_model_faces_decoded_zero_bounds"}:
            bsp_bounds_anomaly_rows.append(out_row)

    package_rows: list[dict[str, Any]] = []
    for pkg, row in sorted(package_summary.items()):
        package_rows.append(
            {
                "package": pkg,
                "staticmesh_asset_defs": row["staticmesh_asset_defs"],
                "staticmesh_asset_decoded": row["staticmesh_asset_decoded"],
                "placement_rows": row["placement_rows"],
                "mesh_bound_placements": row["mesh_bound_placements"],
                "staticmeshactor_rows": row["staticmeshactor_rows"],
                "staticmeshcollectionactor_rows": row["staticmeshcollectionactor_rows"],
                "unique_mesh_path_count": len(row["unique_mesh_paths"]),
                "unique_actor_path_count": len(row["unique_actor_paths"]),
                "unresolved_unique_mesh_ref_count": len(row["unresolved_mesh_refs"]),
                "transform_anomaly_rows": row["transform_anomalies"],
                "mirrored_matrix_rows": row["mirrored_matrix_rows"],
                "negative_component_scale_rows": row["negative_component_scale_rows"],
                "bsp_model_exports": row["bsp_model_exports"],
                "bsp_face_models": row["bsp_face_models"],
                "bsp_empty_models": row["bsp_empty_models"],
                "bsp_not_decoded": row["bsp_not_decoded"],
                "bsp_triangles": row["bsp_triangles"],
            }
        )

    unresolved_rows = [row for row in unique_mesh_rows if not row["asset_resolved"] or row["static_mesh_path"] == ""]

    write_csv(
        out_dir / f"{prefix}_staticmesh_instance_rows.csv",
        instance_out,
        [
            "row_id",
            "package",
            "placement_kind",
            "actor_export_index",
            "actor_name",
            "actor_path",
            "component_ref",
            "component_path",
            "static_mesh_path",
            "asset_resolved",
            "asset_definition_count",
            "asset_source_file_path",
            "asset_extract_status",
            "asset_vertex_count",
            "asset_triangle_count",
            "location_x",
            "location_y",
            "location_z",
            "scale_x_abs",
            "scale_y_abs",
            "scale_z_abs",
            "component_scale_x_signed",
            "component_scale_y_signed",
            "component_scale_z_signed",
            "has_material_overrides",
            "source_transform_mode",
            "has_matrix",
            "matrix_tail_ok",
            "matrix_det3",
            "matrix_handedness",
            "component_scale_has_negative_axis",
            "transform_flags",
        ],
    )
    write_csv(
        out_dir / f"{prefix}_unique_staticmesh_summary.csv",
        unique_mesh_rows,
        [
            "static_mesh_path",
            "instance_count",
            "staticmeshactor_count",
            "staticmeshcollectionactor_count",
            "package_count",
            "packages",
            "unique_actor_count",
            "unique_component_count",
            "asset_resolved",
            "asset_definition_count",
            "asset_source_file_path",
            "asset_extract_status",
            "asset_vertex_count",
            "asset_triangle_count",
            "material_override_rows",
            "mirrored_matrix_rows",
            "negative_component_scale_rows",
            "location_bbox_json",
            "approx_world_bounds_json",
            "sample_actors",
        ],
    )
    write_csv(
        out_dir / f"{prefix}_top_staticmesh_instances.csv",
        unique_mesh_rows[:250],
        [
            "static_mesh_path",
            "instance_count",
            "staticmeshactor_count",
            "staticmeshcollectionactor_count",
            "package_count",
            "packages",
            "asset_source_file_path",
            "asset_vertex_count",
            "asset_triangle_count",
            "mirrored_matrix_rows",
            "negative_component_scale_rows",
            "sample_actors",
        ],
    )
    write_csv(
        out_dir / f"{prefix}_transform_anomalies.csv",
        anomalies,
        [
            "row_id",
            "package",
            "placement_kind",
            "actor_name",
            "actor_path",
            "component_path",
            "static_mesh_path",
            "asset_resolved",
            "location_x",
            "location_y",
            "location_z",
            "scale_x_abs",
            "scale_y_abs",
            "scale_z_abs",
            "component_scale_x_signed",
            "component_scale_y_signed",
            "component_scale_z_signed",
            "matrix_handedness",
            "transform_flags",
        ],
    )
    write_csv(
        out_dir / f"{prefix}_unresolved_staticmesh_refs.csv",
        unresolved_rows,
        ["static_mesh_path", "instance_count", "packages", "sample_actors", "asset_resolved", "asset_definition_count"],
    )
    write_csv(
        out_dir / f"{prefix}_bsp_model_instance_rows.csv",
        bsp_out,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "owner_path",
            "owner_type",
            "status",
            "point_count",
            "node_count",
            "polygon_count",
            "triangle_count",
            "used_point_count",
            "bounds_error",
            "origin_x",
            "origin_y",
            "origin_z",
            "extent_x",
            "extent_y",
            "extent_z",
            "notes",
        ],
    )
    write_csv(
        out_dir / f"{prefix}_package_geometry_summary.csv",
        package_rows,
        [
            "package",
            "staticmesh_asset_defs",
            "staticmesh_asset_decoded",
            "placement_rows",
            "mesh_bound_placements",
            "staticmeshactor_rows",
            "staticmeshcollectionactor_rows",
            "unique_mesh_path_count",
            "unique_actor_path_count",
            "unresolved_unique_mesh_ref_count",
            "transform_anomaly_rows",
            "mirrored_matrix_rows",
            "negative_component_scale_rows",
            "bsp_model_exports",
            "bsp_face_models",
            "bsp_empty_models",
            "bsp_not_decoded",
            "bsp_triangles",
        ],
    )

    anomaly_summary = Counter()
    for row in anomalies:
        for flag in str(row.get("transform_flags", "")).split(";"):
            if flag:
                anomaly_summary[flag] += 1

    totals = {
        "target": args.target,
        "generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "staticmesh_asset_rows": len(asset_rows),
        "unique_staticmesh_asset_paths": len(asset_by_path),
        "staticmesh_assets_decoded": sum(1 for row in asset_rows if row.get("extract_status") != "not_decoded"),
        "staticmesh_placement_rows": len(placement_rows),
        "mesh_bound_placement_rows": sum(1 for row in placement_rows if row.get("static_mesh_path")),
        "unique_placed_staticmesh_paths": len([row for row in unique_mesh_rows if row["static_mesh_path"]]),
        "unresolved_unique_staticmesh_refs": len([row for row in unresolved_rows if row["static_mesh_path"]]),
        "null_or_missing_staticmesh_rows": sum(1 for row in placement_rows if not row.get("static_mesh_path")),
        "placement_kind_counts": dict(Counter(row.get("placement_kind", "") for row in placement_rows)),
        "unique_actor_paths": len({row.get("actor_path", "") for row in placement_rows if row.get("actor_path", "")}),
        "unique_component_paths": len({row.get("component_path", "") for row in placement_rows if row.get("component_path", "")}),
        "transform_anomaly_rows": len(anomalies),
        "transform_anomaly_flag_counts": dict(anomaly_summary),
        "transform_proof_counts": dict(transform_proof_counter),
        "bsp_model_rows": len(bsp_rows),
        "bsp_status_counts": dict(bsp_status_counter),
        "bsp_owner_type_counts": dict(bsp_owner_counter),
        "bsp_triangles_decoded": sum(as_int(row.get("triangle_count")) for row in bsp_rows if row.get("status", "").startswith("bsp_model_faces_decoded")),
        "bsp_nondecoded_or_problem_rows": len(bsp_bounds_anomaly_rows),
        "output_files": {
            "manifest": f"{prefix}_geometry_instance_atlas_manifest.json",
            "report": f"{prefix}_geometry_instance_atlas_report.md",
            "instance_rows": f"{prefix}_staticmesh_instance_rows.csv",
            "unique_mesh_summary": f"{prefix}_unique_staticmesh_summary.csv",
            "top_instances": f"{prefix}_top_staticmesh_instances.csv",
            "transform_anomalies": f"{prefix}_transform_anomalies.csv",
            "unresolved_staticmesh_refs": f"{prefix}_unresolved_staticmesh_refs.csv",
            "bsp_model_instances": f"{prefix}_bsp_model_instance_rows.csv",
            "package_summary": f"{prefix}_package_geometry_summary.csv",
        },
        "source_inputs": {
            "asset_csv": str(Path(args.asset_csv)),
            "placement_csv": str(Path(args.placement_csv)),
            "bsp_csv": str(Path(args.bsp_csv)),
        },
    }

    top_lines = [
        f"| `{row['static_mesh_path']}` | {row['instance_count']} | {row['staticmeshcollectionactor_count']} | {row['staticmeshactor_count']} | {row['mirrored_matrix_rows']} |"
        for row in unique_mesh_rows[:20]
    ]
    owner_lines = [f"| `{owner}` | {count} |" for owner, count in bsp_owner_counter.most_common(12)]
    anomaly_lines = [f"| `{flag}` | {count} |" for flag, count in anomaly_summary.most_common()] or ["| none | 0 |"]
    proof_lines = [f"| `{key}` | {count} |" for key, count in transform_proof_counter.most_common()] or ["| none | 0 |"]

    report = f"""# Gears of War Reloaded - {args.target} Geometry Instance Atlas

Generated: {totals['generated_utc']}

## Scope

This atlas converts source-native Reloaded decode manifests into a map-level geometry placement proof. A StaticMesh instance row means one renderable placement: either a normal `StaticMeshActor` placement or a `StaticMeshCollectionActor` component/matrix placement.

## StaticMesh Coverage

- StaticMesh asset rows: {totals['staticmesh_asset_rows']}
- Unique StaticMesh asset paths: {totals['unique_staticmesh_asset_paths']}
- Decoded StaticMesh assets: {totals['staticmesh_assets_decoded']} / {totals['staticmesh_asset_rows']}
- StaticMesh placement rows: {totals['staticmesh_placement_rows']}
- Mesh-bound placement rows: {totals['mesh_bound_placement_rows']}
- Unique placed StaticMesh paths: {totals['unique_placed_staticmesh_paths']}
- Unresolved unique placed StaticMesh refs: {totals['unresolved_unique_staticmesh_refs']}
- Null/missing StaticMesh placement rows: {totals['null_or_missing_staticmesh_rows']}
- Unique actor paths with geometry rows: {totals['unique_actor_paths']}
- Unique component paths with geometry rows: {totals['unique_component_paths']}

Placement kind counts:

```json
{json.dumps(totals['placement_kind_counts'], indent=2, ensure_ascii=True)}
```

## Transform Proof

Collection instances retain their source-native 4x4 matrix in the instance CSV. Mirrored rows are not failures; they are a warning that the exporter must apply the full matrix or preserve handedness/sign.

| Proof Item | Rows |
|---|---:|
{chr(10).join(proof_lines)}

Transform anomaly rows: {totals['transform_anomaly_rows']}

| Flag | Rows |
|---|---:|
{chr(10).join(anomaly_lines)}

## BSP / Model Coverage

- BSP Model rows: {totals['bsp_model_rows']}
- BSP decoded triangle total: {totals['bsp_triangles_decoded']}
- BSP nondecoded/problem rows: {totals['bsp_nondecoded_or_problem_rows']}

Status counts:

```json
{json.dumps(totals['bsp_status_counts'], indent=2, ensure_ascii=True)}
```

## Top Repeated StaticMeshes

| StaticMesh | Instances | Collection Rows | Actor Rows | Mirrored Matrix Rows |
|---|---:|---:|---:|---:|
{chr(10).join(top_lines)}

## BSP Owner Types

| Owner Type | Model Rows |
|---|---:|
{chr(10).join(owner_lines)}

## Export Implications

- Use `matrix_json` directly for `StaticMeshCollectionActor` rows.
- Use tagged actor transform plus component signed scale for `StaticMeshActor` rows.
- Do not discard mirrored matrix rows; they are source-native transforms.
- Resolve all rows from `{prefix}_staticmesh_instance_rows.csv`; the unresolved reference table should remain empty before a final export.
- BSP rows from `{prefix}_bsp_model_instance_rows.csv` are the source-native shell/model proof layer.

"""
    (out_dir / f"{prefix}_geometry_instance_atlas_manifest.json").write_text(json.dumps(totals, indent=2, ensure_ascii=True), encoding="utf-8")
    (out_dir / f"{prefix}_geometry_instance_atlas_report.md").write_text(report, encoding="utf-8")
    return totals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-csv", required=True)
    parser.add_argument("--placement-csv", required=True)
    parser.add_argument("--bsp-csv", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    args = parser.parse_args()
    totals = build_atlas(args)
    print(json.dumps(totals, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
