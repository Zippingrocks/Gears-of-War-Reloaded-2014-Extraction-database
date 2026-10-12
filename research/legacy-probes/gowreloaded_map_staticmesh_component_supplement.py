#!/usr/bin/env python3
"""Append map-owned StaticMeshComponent placements outside StaticMeshActor collections."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def parse_json(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def compact(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def owner_actor_path(component_path: str) -> str:
    parts = component_path.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


def mesh_path_from_component(row: dict[str, str]) -> str:
    key = parse_json(row.get("key_properties_json", ""), {})
    static_mesh = key.get("StaticMesh")
    if isinstance(static_mesh, dict):
        return str(static_mesh.get("path") or "")
    refs = parse_json(row.get("object_refs_json", ""), [])
    if isinstance(refs, list):
        for ref in refs:
            ref = str(ref)
            if not ref.startswith("TheWorld.") and "." in ref:
                return ref
    return ""


def materials_json_from_component(row: dict[str, str]) -> str:
    key = parse_json(row.get("key_properties_json", ""), {})
    materials = key.get("Materials")
    return compact(materials if materials else {})


def transform_from_actor(actor_row: dict[str, str]) -> dict[str, Any]:
    key = parse_json(actor_row.get("key_properties_json", ""), {})
    return {
        "location": key.get("Location") or [0.0, 0.0, 0.0],
        "rotation": key.get("Rotation") or {"pitch": 0, "yaw": 0, "roll": 0},
        "draw_scale": key.get("DrawScale", 1.0),
        "draw_scale3d": key.get("DrawScale3D") or [1.0, 1.0, 1.0],
        "pre_pivot": key.get("PrePivot") or [0.0, 0.0, 0.0],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-placement-csv", required=True)
    parser.add_argument("--actor-transform-csv", required=True)
    parser.add_argument("--owner-actor-probe-csv", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    args = parser.parse_args()

    base_rows = read_csv(Path(args.base_placement_csv))
    component_rows = [row for row in read_csv(Path(args.actor_transform_csv)) if row.get("class_name") == "StaticMeshComponent"]
    actor_probe_rows = read_csv(Path(args.owner_actor_probe_csv))
    placed_components = {row.get("component_path", "") for row in base_rows if row.get("component_path")}
    actors_by_path = {row.get("full_path", ""): row for row in actor_probe_rows}

    supplement_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    for comp in component_rows:
        component_path = comp.get("full_path", "")
        if component_path in placed_components:
            continue
        mesh_path = mesh_path_from_component(comp)
        owner_path = owner_actor_path(component_path)
        if not component_path.startswith("TheWorld.PersistentLevel."):
            excluded_rows.append(
                {
                    "component_path": component_path,
                    "static_mesh_path": mesh_path,
                    "exclude_reason": "class_default_or_nonlevel_component",
                }
            )
            continue
        actor = actors_by_path.get(owner_path)
        if actor is None:
            excluded_rows.append(
                {
                    "component_path": component_path,
                    "static_mesh_path": mesh_path,
                    "exclude_reason": "missing_owner_actor_transform_probe",
                }
            )
            continue
        supplement_rows.append(
            {
                "package": comp.get("package", ""),
                "placement_kind": "MapOwnedStaticMeshComponent",
                "actor_export_index": actor.get("export_index", ""),
                "actor_name": actor.get("object_name", ""),
                "actor_path": owner_path,
                "component_ref": comp.get("export_index", ""),
                "component_path": component_path,
                "static_mesh_path": mesh_path,
                "materials_json": materials_json_from_component(comp),
                "component_scale3d_json": compact([1.0, 1.0, 1.0]),
                "component_scale_source": "default",
                "transform_json": compact(transform_from_actor(actor)),
                "matrix_json": "",
                "supplement_evidence": "StaticMeshComponent not referenced by StaticMeshActor/StaticMeshCollectionActor, owner actor transform decoded by targeted actor probe",
            }
        )

    placement_fields = [
        "package",
        "placement_kind",
        "actor_export_index",
        "actor_name",
        "actor_path",
        "component_ref",
        "component_path",
        "static_mesh_path",
        "materials_json",
        "component_scale3d_json",
        "component_scale_source",
        "transform_json",
        "matrix_json",
        "supplement_evidence",
    ]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    augmented_rows = [{**row, "supplement_evidence": ""} for row in base_rows] + supplement_rows
    write_csv(out_dir / f"{args.prefix}_staticmesh_placement_augmented_manifest.csv", augmented_rows, placement_fields)
    write_csv(out_dir / f"{args.prefix}_staticmesh_component_supplement_rows.csv", supplement_rows, placement_fields)
    write_csv(out_dir / f"{args.prefix}_staticmesh_component_supplement_excluded.csv", excluded_rows, ["component_path", "static_mesh_path", "exclude_reason"])
    manifest = {
        "target": args.target,
        "base_placement_rows": len(base_rows),
        "supplement_rows": len(supplement_rows),
        "augmented_placement_rows": len(augmented_rows),
        "excluded_unplaced_components": len(excluded_rows),
        "excluded_reason_counts": {reason: sum(1 for row in excluded_rows if row["exclude_reason"] == reason) for reason in sorted({row["exclude_reason"] for row in excluded_rows})},
        "rule": "Only TheWorld.PersistentLevel StaticMeshComponents missing from StaticMeshActor/StaticMeshCollectionActor placement manifests are promoted. Class default components remain excluded.",
    }
    (out_dir / f"{args.prefix}_staticmesh_component_supplement_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
