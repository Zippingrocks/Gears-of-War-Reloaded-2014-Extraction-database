#!/usr/bin/env python3
"""Generic StaticMesh clean-extract wrapper for Reloaded cooked maps."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_clean_extract_confidence.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_clean_extract", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load source tool: {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_clean_extract"] = module
    spec.loader.exec_module(module)
    return module


def sanitize_prefix(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "_")
    value = "".join(out).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "gowreloaded_map"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-file", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    parser.add_argument("--sample-per-status", type=int, default=3)
    args = parser.parse_args()

    src = load_source()
    packages = [Path(p) for p in args.map_file]
    missing = [str(p) for p in packages if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing map package(s): {missing}")

    out_dir = Path(args.out)
    samples_dir = out_dir / "sample_objs"
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(parents=True, exist_ok=True)
    prefix = sanitize_prefix(args.prefix)

    package_rows: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    placement_rows: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    sample_budget = Counter()
    for package in packages:
        try:
            summary, assets, placements, samples = src.process_package(package, samples_dir, sample_budget)
            summary["target"] = args.target
            package_rows.append(summary)
            asset_rows.extend(assets)
            placement_rows.extend(placements)
            sample_rows.extend(samples)
            print(
                f"confidence {package.name}: assets={summary['static_mesh_assets']} "
                f"bulk={summary['bulk_position_index']} inline={summary['inline_staticmesh_stream']} "
                f"placements={summary['placement_rows']}"
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"package": package.name, "error": str(exc)})
            print(f"FAILED {package.name}: {exc}")

    totals = {
        "packages": len(package_rows),
        "errors": len(errors),
        "static_mesh_assets": len(asset_rows),
        "bulk_position_index": sum(row["extract_status"] == "bulk_position_index" for row in asset_rows),
        "inline_staticmesh_stream": sum(row["extract_status"] == "inline_staticmesh_stream" for row in asset_rows),
        "static_mesh_not_decoded": sum(row["extract_status"] == "not_decoded" for row in asset_rows),
        "placement_rows": len(placement_rows),
        "placement_staticmesh_paths": sum(bool(row["static_mesh_path"]) for row in placement_rows),
        "placement_by_kind": dict(Counter(row["placement_kind"] for row in placement_rows)),
        "sample_objs": len([row for row in sample_rows if row.get("obj_path")]),
    }

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "scope": "StaticMesh asset geometry and placement confidence for a specific Reloaded cooked map; no Blender scene emitted.",
        "packages": [str(p) for p in packages],
        "out_dir": str(out_dir),
        "totals": totals,
        "source_tool": str(SOURCE_TOOL),
    }
    (out_dir / f"{prefix}_clean_extract_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    src.write_csv(
        out_dir / f"{prefix}_clean_extract_packages.csv",
        package_rows,
        [
            "package",
            "target",
            "virtual_size",
            "names",
            "imports",
            "exports",
            "static_mesh_assets",
            "bulk_position_index",
            "inline_staticmesh_stream",
            "not_decoded",
            "staticmesh_components",
            "placement_rows",
            "unplaced_staticmesh_components",
        ],
    )
    src.write_csv(
        out_dir / f"{prefix}_staticmesh_clean_extract_manifest.csv",
        asset_rows,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_end_rel",
            "source_file_path",
            "lightmap_coordinate_index",
            "lightmap_resolution",
            "bounds_json",
            "extract_status",
            "vertex_rel",
            "vertex_count",
            "index_rel",
            "index_count",
            "index_element_size",
            "triangle_count",
            "bounds_error",
            "geometry_json",
        ],
    )
    src.write_csv(
        out_dir / f"{prefix}_staticmesh_placement_manifest.csv",
        placement_rows,
        [
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
        ],
    )
    src.write_csv(out_dir / f"{prefix}_staticmesh_sample_objs.csv", sample_rows, ["package", "export_index", "object_name", "status", "obj_path", "detail_json"])
    src.write_csv(out_dir / f"{prefix}_clean_extract_errors.csv", errors, ["package", "error"])
    print(json.dumps(totals, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
