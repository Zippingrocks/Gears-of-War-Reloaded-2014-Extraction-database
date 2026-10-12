#!/usr/bin/env python3
"""Generic BSP face extraction wrapper for Reloaded cooked maps."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_bsp_confidence", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load source tool: {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_bsp_confidence"] = module
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
    parser.add_argument("--sample-count", type=int, default=8)
    args = parser.parse_args()

    src = load_source()
    packages = [Path(p) for p in args.map_file]
    missing = [str(p) for p in packages if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing map package(s): {missing}")

    out_dir = Path(args.out)
    samples_dir = out_dir / "sample_bsp_model_objs"
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(parents=True, exist_ok=True)
    prefix = sanitize_prefix(args.prefix)

    sample_budget = {"bsp_model_faces_decoded": int(args.sample_count)}
    package_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for package in packages:
        try:
            summary, models, samples = src.process_package(package, samples_dir, sample_budget)
            summary["target"] = args.target
            package_rows.append(summary)
            model_rows.extend(models)
            sample_rows.extend(samples)
            print(
                f"bsp {package.name}: models={summary['model_exports']} "
                f"faces={summary['models_faces_decoded']} empty={summary['empty_models']} "
                f"not_decoded={summary['models_not_decoded']}"
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"package": package.name, "error": str(exc)})
            print(f"FAILED {package.name}: {exc}")

    totals = {
        "packages": len(package_rows),
        "packages_failed": len(errors),
        "model_exports": len(model_rows),
        "models_faces_decoded": sum(row["status"] in {"bsp_model_faces_decoded", "bsp_model_faces_decoded_zero_bounds"} for row in model_rows),
        "empty_models": sum(row["status"] == "empty_model" for row in model_rows),
        "point_cloud_no_bsp_nodes": sum(row["status"] == "point_cloud_no_bsp_nodes" for row in model_rows),
        "models_with_bounds_mismatch": sum(row["status"] == "faces_decoded_bounds_mismatch" for row in model_rows),
        "zero_sized_model_arrays": sum(row["status"] == "zero_sized_model_arrays" for row in model_rows),
        "models_not_decoded": sum(
            row["status"]
            not in {
                "bsp_model_faces_decoded",
                "bsp_model_faces_decoded_zero_bounds",
                "empty_model",
                "point_cloud_no_bsp_nodes",
                "zero_sized_model_arrays",
            }
            for row in model_rows
        ),
        "triangles_decoded": sum(int(row["triangle_count"] or 0) for row in model_rows),
        "status_counts": dict(Counter(row["status"] for row in model_rows)),
        "sample_objs": len(sample_rows),
    }

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "scope": "BSP Model face reconstruction confidence for a specific Reloaded cooked map; no Blender scene emitted.",
        "packages": [str(p) for p in packages],
        "out_dir": str(out_dir),
        "layout_constants": {
            "surf_record_size": src.SURF_RECORD_SIZE,
            "vert_record_size": src.VERT_RECORD_SIZE,
            "node_record_size": src.NODE_RECORD_SIZE,
            "node_i_vert_pool_rel": src.NODE_I_VERT_POOL_REL,
            "node_i_surf_rel": src.NODE_I_SURF_REL,
            "node_num_vertices_rel": src.NODE_NUM_VERTICES_REL,
        },
        "totals": totals,
        "source_tool": str(SOURCE_TOOL),
    }
    (out_dir / f"{prefix}_bsp_confidence_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    src.write_csv(
        out_dir / f"{prefix}_bsp_confidence_packages.csv",
        package_rows,
        ["package", "target", "virtual_size", "names", "imports", "exports", "model_exports", "models_faces_decoded", "empty_models", "models_with_bounds_mismatch", "models_not_decoded"],
    )
    src.write_csv(
        out_dir / f"{prefix}_bsp_model_faces_manifest.csv",
        model_rows,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_end_rel",
            "bounds_json",
            "vectors_json",
            "points_json",
            "nodes_json",
            "surf_count",
            "vert_count",
            "status",
            "point_count",
            "node_count",
            "polygon_count",
            "triangle_count",
            "used_point_count",
            "chosen_point_field_rel",
            "bounds_error",
            "face_bounds_json",
            "notes",
        ],
    )
    src.write_csv(out_dir / f"{prefix}_bsp_sample_objs.csv", sample_rows, ["package", "export_index", "object_name", "status", "obj_path", "detail_json"])
    src.write_csv(out_dir / f"{prefix}_bsp_confidence_errors.csv", errors, ["package", "error"])
    print(json.dumps(totals, indent=2, ensure_ascii=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
