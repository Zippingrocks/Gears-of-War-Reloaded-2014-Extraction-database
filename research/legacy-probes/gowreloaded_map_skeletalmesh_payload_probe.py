#!/usr/bin/env python3
"""Probe Reloaded SkeletalMesh native payload landmarks for a cooked map."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


HEAVY_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)


def load_heavy():
    spec = importlib.util.spec_from_file_location("gowr_heavy", HEAVY_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser: {HEAVY_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compact(value: Any, limit: int = 2000) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def sample_indices(count: int) -> list[int]:
    if count <= 0:
        return []
    return sorted(set([0, 1, 2, max(0, count // 2), max(0, count - 3), max(0, count - 2), max(0, count - 1)]))


def vector_sample_ok(heavy: Any, data: bytes, abs_off: int, count: int, stride: int) -> bool:
    for idx in sample_indices(count):
        base = abs_off + idx * stride
        try:
            vals = [heavy.f32(data, base), heavy.f32(data, base + 4), heavy.f32(data, base + 8)]
        except Exception:  # noqa: BLE001
            return False
        if not all(math.isfinite(v) and abs(v) <= 1_000_000.0 for v in vals):
            return False
    return True


def index_sample_stats(heavy: Any, data: bytes, abs_off: int, count: int, element_size: int) -> dict[str, Any] | None:
    values: list[int] = []
    for idx in sample_indices(count):
        try:
            value = heavy.u16(data, abs_off + idx * 2) if element_size == 2 else heavy.u32(data, abs_off + idx * 4)
        except Exception:  # noqa: BLE001
            return None
        values.append(value)
    if not values:
        return None
    return {"sample_min": min(values), "sample_max": max(values), "sample_unique": len(set(values))}


def scan_bulk_candidates(
    heavy: Any,
    data: bytes,
    serial_offset: int,
    serial_size: int,
    start_rel: int,
) -> list[dict[str, Any]]:
    serial_end = serial_offset + serial_size
    candidates: list[dict[str, Any]] = []
    element_sizes = {2, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 68, 72, 80, 88, 96, 112, 128}
    for rel in range(max(0, start_rel), max(0, serial_size - 8), 4):
        abs_off = serial_offset + rel
        try:
            element_size = heavy.i32(data, abs_off)
            count = heavy.i32(data, abs_off + 4)
        except Exception:  # noqa: BLE001
            break
        if element_size not in element_sizes or count <= 0 or count > 2_000_000:
            continue
        payload_size = element_size * count
        data_abs = abs_off + 8
        if payload_size <= 0 or data_abs + payload_size > serial_end:
            continue
        kind: list[str] = []
        detail: dict[str, Any] = {}
        if element_size >= 12 and vector_sample_ok(heavy, data, data_abs, count, element_size):
            kind.append("vector_or_vertex_like")
            if count <= 200_000:
                bounds = heavy.vector_bounds(data, data_abs, count, element_size)
                if bounds:
                    detail["vector_bounds"] = bounds
        if element_size == 12 and count >= 3 and "vector_or_vertex_like" in kind:
            kind.append("position_vector12_candidate")
        if element_size in {2, 4} and count >= 3:
            stats = index_sample_stats(heavy, data, data_abs, count, element_size)
            if stats and stats["sample_unique"] > 1:
                kind.append(f"index{element_size * 8}_candidate")
                detail.update(stats)
        if not kind:
            if payload_size < 4096:
                kind.append("small_struct_or_ref_array")
            else:
                continue
        candidates.append(
            {
                "start_rel": rel,
                "data_rel": rel + 8,
                "element_size": element_size,
                "count": count,
                "payload_size": payload_size,
                "end_rel": rel + 8 + payload_size,
                "kind": ";".join(kind),
                "detail_json": compact(detail, 2400),
            }
        )
    return candidates


def find_plausible_bounds(heavy: Any, data: bytes, serial_offset: int, serial_size: int, start_rel: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel in range(max(0, start_rel), max(0, serial_size - 28), 4):
        try:
            bounds = heavy.read_bounds(data, serial_offset + rel)
        except Exception:  # noqa: BLE001
            continue
        if not bounds or not bounds.get("plausible"):
            continue
        extent = [float(value) for value in bounds.get("extent") or [0.0, 0.0, 0.0]]
        sphere = float(bounds.get("sphere_radius") or 0.0)
        max_extent = max(extent) if extent else 0.0
        diag = math.sqrt(sum(value * value for value in extent))
        if max_extent < 1.0 or sphere < 1.0:
            continue
        if sphere < max_extent * 0.5 or sphere > max(0.05, diag * 1.5):
            continue
        if any(abs(float(value)) > 2_000_000.0 for value in bounds.get("origin") or []):
            continue
        if any(value < 0.0 or value > 2_000_000.0 for value in extent):
            continue
        out.append({"rel": rel, "bounds": bounds})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    parser.add_argument("--path-regex", default="")
    args = parser.parse_args()

    heavy = load_heavy()
    package = Path(args.map_file)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = package.read_bytes()
    virt, groups, compression_mode = heavy.rebuild_virtual_package(data)
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for row in exports:
        row["class_name"] = ref_short_name(row["class_ref"])
        row["full_path"] = ref_path(row["index"])

    import re

    path_rx = re.compile(args.path_regex, re.IGNORECASE) if args.path_regex else None
    mesh_rows: list[dict[str, Any]] = []
    bulk_rows: list[dict[str, Any]] = []

    for row in exports:
        if row["class_name"] != "SkeletalMesh" or row["serial_size"] <= 0:
            continue
        if path_rx and not path_rx.search(row["full_path"]):
            continue
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4, 8, 16, 32, 64, 68])
        result = scan["result"]
        tags = result.get("tags", []) if result.get("ok") else []
        native_start = int(result.get("end_rel") or 0) if result.get("ok") else 0
        bounds_candidates = find_plausible_bounds(heavy, virt, row["serial_offset"], row["serial_size"], native_start)
        selected_bounds = bounds_candidates[0]["bounds"] if bounds_candidates else None
        position = None
        static_vertex = None
        index = None
        if selected_bounds:
            try:
                position = heavy.find_position_buffer(virt, row["serial_offset"], row["serial_size"], bounds_candidates[0]["rel"] + 28, selected_bounds)
                if position:
                    static_vertex = heavy.find_static_vertex_buffer(virt, row["serial_offset"], row["serial_size"], position)
                    index = heavy.find_index_buffer(virt, row["serial_offset"], row["serial_size"], position, static_vertex)
            except Exception as exc:  # noqa: BLE001
                position = {"error": str(exc)}
        candidates = scan_bulk_candidates(heavy, virt, row["serial_offset"], row["serial_size"], native_start)
        for candidate in candidates:
            bulk = {
                "package": package.name,
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
            }
            bulk.update(candidate)
            bulk_rows.append(bulk)
        status = "native_payload_probed"
        if position and index:
            status = "position_and_index_found"
        elif position:
            status = "position_only"
        elif bounds_candidates:
            status = "bounds_only"
        mesh_rows.append(
            {
                "package": package.name,
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "serial_offset": row["serial_offset"],
                "serial_size": row["serial_size"],
                "property_start_rel": scan.get("start_rel", ""),
                "property_end_rel": native_start,
                "property_ok": result.get("ok", False),
                "property_error": result.get("error", ""),
                "property_count": len([tag for tag in tags if tag.get("name") != "None"]),
                "status": status,
                "bounds_candidates": len(bounds_candidates),
                "bounds_rel": bounds_candidates[0]["rel"] if bounds_candidates else "",
                "bounds_json": compact(selected_bounds or {}, 2000),
                "position_buffer_json": compact(position or {}, 2400),
                "static_vertex_buffer_json": compact(static_vertex or {}, 1600),
                "index_buffer_json": compact(index or {}, 1600),
                "bulk_candidate_count": len(candidates),
                "object_refs_json": compact(heavy.property_object_refs(tags)[:48], 4000),
            }
        )

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "package": str(package),
        "compression_mode": compression_mode,
        "compressed_groups": len(groups),
        "skeletalmesh_rows": len(mesh_rows),
        "status_counts": {},
        "bulk_candidate_rows": len(bulk_rows),
        "source_tool": str(HEAVY_TOOL),
        "rule": "This is a source-native payload landmark probe only. It does not export SkeletalMesh geometry.",
    }
    for row in mesh_rows:
        manifest["status_counts"][row["status"]] = manifest["status_counts"].get(row["status"], 0) + 1

    (out_dir / f"{args.prefix}_skeletalmesh_payload_probe_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    write_csv(
        out_dir / f"{args.prefix}_skeletalmesh_payload_probe.csv",
        mesh_rows,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_start_rel",
            "property_end_rel",
            "property_ok",
            "property_error",
            "property_count",
            "status",
            "bounds_candidates",
            "bounds_rel",
            "bounds_json",
            "position_buffer_json",
            "static_vertex_buffer_json",
            "index_buffer_json",
            "bulk_candidate_count",
            "object_refs_json",
        ],
    )
    write_csv(
        out_dir / f"{args.prefix}_skeletalmesh_bulk_candidates.csv",
        bulk_rows,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "start_rel",
            "data_rel",
            "element_size",
            "count",
            "payload_size",
            "end_rel",
            "kind",
            "detail_json",
        ],
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
