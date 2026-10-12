#!/usr/bin/env python3
"""Audit effective exporter transforms for Reloaded StaticMesh placements."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PREP_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_prepare_textured_blend_export.py"
)


def load_prep():
    spec = importlib.util.spec_from_file_location("gowr_prep_transform", PREP_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load prepare tool: {PREP_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_json(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def det3(values: list[float]) -> float:
    return (
        values[0] * (values[5] * values[10] - values[6] * values[9])
        - values[1] * (values[4] * values[10] - values[6] * values[8])
        + values[2] * (values[4] * values[9] - values[5] * values[8])
    )


def handedness(det: float) -> str:
    if det < -1e-6:
        return "mirrored"
    if det > 1e-6:
        return "normal"
    return "degenerate"


def loc_from_matrix(values: list[float]) -> list[float]:
    return [float(values[12]), float(values[13]), float(values[14])]


def flags_for(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    loc = [row["location_x"], row["location_y"], row["location_z"]]
    if max(abs(float(v)) for v in loc) > 250000:
        flags.append("extreme_location")
    if row["effective_handedness"] == "mirrored":
        flags.append("effective_mirrored")
    if row["effective_handedness"] == "degenerate":
        flags.append("effective_degenerate")
    if row["base_matrix_tail_ok"] is False:
        flags.append("bad_matrix_tail")
    scale = [abs(float(row["component_scale_x"])), abs(float(row["component_scale_y"])), abs(float(row["component_scale_z"]))]
    if max(scale) > 100:
        flags.append("large_component_scale")
    if min(scale) < 1e-6:
        flags.append("zero_component_scale")
    return flags


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--placement-csv", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    args = parser.parse_args()

    prep = load_prep()
    placements = read_csv(Path(args.placement_csv))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    problem_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()

    for ordinal, row in enumerate(placements):
        component_scale = prep.effective_component_scale(row)
        component_scale_applied = prep.scale_is_nondefault(component_scale)
        has_collection_matrix = bool(row.get("matrix_json"))
        if has_collection_matrix:
            base_values = [float(v) for v in parse_json(row["matrix_json"], [])]
            transform_source = "decoded_collection_actor_matrix64_component_scale" if component_scale_applied else "decoded_collection_actor_matrix64"
        else:
            transform = parse_json(row.get("transform_json", ""), {})
            base_values = prep.unreal_rotator_row_major_matrix(transform)
            transform_source = "decoded_static_mesh_actor_rotator_component_scale" if component_scale_applied else "decoded_static_mesh_actor_rotator"
        effective_values = prep.apply_component_scale_to_unreal_row_major(base_values, component_scale)
        base_det = det3(base_values)
        effective_det = det3(effective_values)
        loc = loc_from_matrix(base_values)
        out_row: dict[str, Any] = {
            "ordinal": ordinal,
            "placement_kind": row.get("placement_kind", ""),
            "actor_name": row.get("actor_name", ""),
            "actor_path": row.get("actor_path", ""),
            "component_path": row.get("component_path", ""),
            "static_mesh_path": row.get("static_mesh_path", ""),
            "transform_source": transform_source,
            "has_collection_matrix": has_collection_matrix,
            "base_matrix_tail_ok": abs(float(base_values[15]) - 1.0) <= 1e-4,
            "base_det3": round(base_det, 8),
            "base_handedness": handedness(base_det),
            "component_scale_x": component_scale[0],
            "component_scale_y": component_scale[1],
            "component_scale_z": component_scale[2],
            "component_scale_applied": component_scale_applied,
            "effective_det3": round(effective_det, 8),
            "effective_handedness": handedness(effective_det),
            "location_x": loc[0],
            "location_y": loc[1],
            "location_z": loc[2],
        }
        flags = flags_for(out_row)
        out_row["audit_flags"] = ";".join(flags)
        rows.append(out_row)
        counts[f"source:{transform_source}"] += 1
        counts[f"effective_handedness:{out_row['effective_handedness']}"] += 1
        if component_scale_applied:
            counts["component_scale_applied"] += 1
        for flag in flags:
            flag_counts[flag] += 1
        if flags:
            problem_rows.append(out_row)

    manifest = {
        "target": args.target,
        "placement_rows": len(placements),
        "counts": dict(sorted(counts.items())),
        "audit_flag_counts": dict(sorted(flag_counts.items())),
        "flagged_rows": len(problem_rows),
        "source_tool": str(PREP_TOOL),
        "rule": "Effective transform uses the same path as the Reloaded Blender exporter: row matrix or actor rotator, then component_scale3d applied to the first three Unreal row-major basis rows.",
    }
    fields = [
        "ordinal",
        "placement_kind",
        "actor_name",
        "actor_path",
        "component_path",
        "static_mesh_path",
        "transform_source",
        "has_collection_matrix",
        "base_matrix_tail_ok",
        "base_det3",
        "base_handedness",
        "component_scale_x",
        "component_scale_y",
        "component_scale_z",
        "component_scale_applied",
        "effective_det3",
        "effective_handedness",
        "location_x",
        "location_y",
        "location_z",
        "audit_flags",
    ]
    (out_dir / f"{args.prefix}_effective_transform_audit_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    write_csv(out_dir / f"{args.prefix}_effective_transform_rows.csv", rows, fields)
    write_csv(out_dir / f"{args.prefix}_effective_transform_flagged_rows.csv", problem_rows, fields)
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
