#!/usr/bin/env python3
"""Focused layout probe for Reloaded MP_Gridlock skeletal water meshes."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any


HEAVY_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)

WATER_MESH_PREFIX = "FX_MP_GridlockWater_Delta.gridlockWater_skMesh"


def load_heavy():
    spec = importlib.util.spec_from_file_location("gowr_heavy", HEAVY_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser: {HEAVY_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compact(value: Any, limit: int = 2400) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def finite(value: float, limit: float = 1_000_000.0) -> bool:
    return math.isfinite(value) and abs(value) <= limit


def vec_bounds(points: list[tuple[float, float, float]]) -> dict[str, Any]:
    mins = [min(p[i] for p in points) for i in range(3)]
    maxs = [max(p[i] for p in points) for i in range(3)]
    center = [(mins[i] + maxs[i]) / 2.0 for i in range(3)]
    extent = [(maxs[i] - mins[i]) / 2.0 for i in range(3)]
    return {"min": mins, "max": maxs, "center": center, "extent": extent}


def read_indices(data: bytes, rel: int, count: int) -> list[int]:
    start = rel + 8
    return [u16(data, start + i * 2) for i in range(count)]


def expected_grid_indices(width: int = 57, height: int = 57) -> list[int]:
    out: list[int] = []
    for y in range(height - 1):
        for x in range(width - 1):
            a = y * width + x
            b = a + 1
            c = a + width
            d = c + 1
            out.extend([a, c, b, b, c, d])
    return out


def index_stats(indices: list[int]) -> dict[str, Any]:
    expected = expected_grid_indices()
    matches_forward = indices == expected
    matches_reversed_winding = all(a == b for a, b in zip(indices, [expected[i ^ 1] if i % 3 != 2 else expected[i] for i in range(len(expected))]))
    return {
        "count": len(indices),
        "triangles": len(indices) // 3,
        "min": min(indices) if indices else None,
        "max": max(indices) if indices else None,
        "unique": len(set(indices)),
        "expected_grid_57x57_index_count": len(expected),
        "matches_grid_forward": matches_forward,
        "matches_grid_reversed_test": matches_reversed_winding,
        "first_24": indices[:24],
        "last_24": indices[-24:],
    }


def sample_table(data: bytes, rel: int, rows: int = 32) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in range(rows):
        off = rel + n * 4
        if off + 4 > len(data):
            break
        raw = data[off : off + 4]
        out.append(
            {
                "rel": off,
                "hex": raw.hex(),
                "u32": u32(data, off),
                "i32": i32(data, off),
                "f32": f32(data, off),
            }
        )
    return out


def score_position_stream(
    data: bytes,
    data_rel: int,
    count: int,
    stride: int,
    xyz_offset: int,
) -> dict[str, Any] | None:
    if data_rel + (count - 1) * stride + xyz_offset + 12 > len(data):
        return None
    for idx in sorted(set([0, 1, 2, count // 2, count - 3, count - 2, count - 1])):
        off = data_rel + idx * stride + xyz_offset
        vals = (f32(data, off), f32(data, off + 4), f32(data, off + 8))
        if not all(finite(v, 500_000.0) for v in vals):
            return None
    points: list[tuple[float, float, float]] = []
    for idx in range(count):
        off = data_rel + idx * stride + xyz_offset
        vals = (f32(data, off), f32(data, off + 4), f32(data, off + 8))
        if not all(finite(v, 500_000.0) for v in vals):
            return None
        points.append(vals)
    bounds = vec_bounds(points)
    extent = bounds["extent"]
    z_extent = extent[2]
    xy_extent = max(extent[0], extent[1])
    if xy_extent < 100.0:
        return None
    if z_extent > max(1000.0, xy_extent * 0.5):
        return None
    unique_sample = len(set(points[:: max(1, count // 64)]))
    return {
        "data_rel": data_rel,
        "count": count,
        "stride": stride,
        "xyz_offset": xyz_offset,
        "bounds": bounds,
        "xy_extent_max": xy_extent,
        "z_extent": z_extent,
        "unique_sample": unique_sample,
        "first_points": points[:5],
        "last_points": points[-5:],
    }


def scan_position_streams(data: bytes, data_rels: list[int], count: int = 3249) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for stride in (12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64):
        for xyz_offset in range(0, min(stride - 8, 32), 4):
            for data_rel in data_rels:
                row = score_position_stream(data, data_rel, count, stride, xyz_offset)
                if row:
                    hits.append(row)
    hits.sort(key=lambda r: (r["z_extent"], -r["xy_extent_max"], r["data_rel"], r["stride"], r["xyz_offset"]))
    return hits[:80]

def scan_bulk_headers(data: bytes, start_rel: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in range(start_rel, max(0, len(data) - 8), 4):
        element_size = i32(data, rel)
        count = i32(data, rel + 4)
        if element_size not in {1, 2, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 68, 72, 80, 88, 96, 112, 128}:
            continue
        if count <= 0 or count > 2_000_000:
            continue
        end = rel + 8 + element_size * count
        if end > len(data):
            continue
        if count in {224, 3249, 18816, 32640, 528} or element_size in {12, 16, 20, 24, 28, 32, 36, 40, 44, 48} and count > 1000:
            rows.append(
                {
                    "start_rel": rel,
                    "data_rel": rel + 8,
                    "element_size": element_size,
                    "count": count,
                    "payload_size": element_size * count,
                    "end_rel": end,
                    "first_u32": [u32(data, rel + 8 + i * 4) for i in range(min(8, max(0, (element_size * count) // 4)))],
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    args = parser.parse_args()

    heavy = load_heavy()
    package = Path(args.map_file)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    virt, groups, compression_mode = heavy.rebuild_virtual_package(package.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for row in exports:
        row["class_name"] = ref_short_name(row["class_ref"])
        row["full_path"] = ref_path(row["index"])

    mesh_reports: list[dict[str, Any]] = []
    bulk_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []

    for row in exports:
        if row["class_name"] != "SkeletalMesh" or not row["full_path"].startswith(WATER_MESH_PREFIX):
            continue
        data = virt[row["serial_offset"] : row["serial_offset"] + row["serial_size"]]
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4, 8, 16, 32, 64, 68])
        native_start = int(scan["result"].get("end_rel") or 0) if scan["result"].get("ok") else 0

        headers = scan_bulk_headers(data, native_start)
        for header in headers:
            out = {"export_index": row["index"], "object_name": row["object_short_name"], "full_path": row["full_path"]}
            out.update(header)
            out["first_u32_json"] = compact(header.pop("first_u32"), 1000)
            bulk_rows.append(out)

        index_header = next((h for h in headers if h["element_size"] == 2 and h["count"] == 18816), None)
        idx_stats: dict[str, Any] = {}
        if index_header:
            idx = read_indices(data, index_header["start_rel"], index_header["count"])
            idx_stats = index_stats(idx)

        # The strongest topology clue is the 3249-count array after the index buffer.
        u32_header = next((h for h in headers if h["element_size"] == 4 and h["count"] == 3249), None)
        if u32_header:
            for sample in sample_table(data, u32_header["data_rel"], 40):
                sample["export_index"] = row["index"]
                sample["object_name"] = row["object_short_name"]
                sample["table"] = "u32_3249_payload"
                table_rows.append(sample)

        # Search actual bulk payload starts and small windows around the strongest anchors.
        candidate_data_rels: set[int] = set()
        for header in headers:
            if header["count"] == 3249:
                candidate_data_rels.add(header["data_rel"])
        for anchor in [index_header, u32_header]:
            if not anchor:
                continue
            for base in (anchor["start_rel"], anchor["data_rel"], anchor["end_rel"]):
                for delta in (-64, -32, -16, -8, 0, 8, 16, 32, 64, 128):
                    rel = base + delta
                    if 0 <= rel < len(data):
                        candidate_data_rels.add(rel)
        hits = scan_position_streams(data, sorted(candidate_data_rels), 3249)
        seen: set[tuple[int, int, int]] = set()
        unique_hits: list[dict[str, Any]] = []
        for hit in hits:
            key = (hit["data_rel"], hit["stride"], hit["xyz_offset"])
            if key in seen:
                continue
            seen.add(key)
            unique_hits.append(hit)
        unique_hits = unique_hits[:40]
        for hit in unique_hits:
            position_rows.append(
                {
                    "export_index": row["index"],
                    "object_name": row["object_short_name"],
                    "full_path": row["full_path"],
                    "data_rel": hit["data_rel"],
                    "stride": hit["stride"],
                    "xyz_offset": hit["xyz_offset"],
                    "xy_extent_max": hit["xy_extent_max"],
                    "z_extent": hit["z_extent"],
                    "unique_sample": hit["unique_sample"],
                    "bounds_json": compact(hit["bounds"], 1600),
                    "first_points_json": compact(hit["first_points"], 1200),
                    "last_points_json": compact(hit["last_points"], 1200),
                }
            )

        mesh_reports.append(
            {
                "package": package.name,
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "serial_offset": row["serial_offset"],
                "serial_size": row["serial_size"],
                "property_end_rel": native_start,
                "bulk_header_count": len(headers),
                "index_18816_header_json": compact(index_header or {}, 1600),
                "index_18816_stats_json": compact(idx_stats, 2400),
                "u32_3249_header_json": compact(u32_header or {}, 1600),
                "position_candidate_count": len(unique_hits),
                "best_position_candidate_json": compact(unique_hits[0] if unique_hits else {}, 2400),
            }
        )

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "package": str(package),
        "compression_mode": compression_mode,
        "compressed_groups": len(groups),
        "water_skeletal_meshes": len(mesh_reports),
        "bulk_rows": len(bulk_rows),
        "position_candidate_rows": len(position_rows),
        "source_tool": str(HEAVY_TOOL),
        "rule": "Focused water topology/layout probe. No Blender scene emitted.",
    }
    (out_dir / f"{args.prefix}_water_layout_probe_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    write_csv(
        out_dir / f"{args.prefix}_water_layout_mesh_summary.csv",
        mesh_reports,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_end_rel",
            "bulk_header_count",
            "index_18816_header_json",
            "index_18816_stats_json",
            "u32_3249_header_json",
            "position_candidate_count",
            "best_position_candidate_json",
        ],
    )
    write_csv(
        out_dir / f"{args.prefix}_water_layout_bulk_headers.csv",
        bulk_rows,
        ["export_index", "object_name", "full_path", "start_rel", "data_rel", "element_size", "count", "payload_size", "end_rel", "first_u32_json"],
    )
    write_csv(
        out_dir / f"{args.prefix}_water_layout_position_candidates.csv",
        position_rows,
        [
            "export_index",
            "object_name",
            "full_path",
            "data_rel",
            "stride",
            "xyz_offset",
            "xy_extent_max",
            "z_extent",
            "unique_sample",
            "bounds_json",
            "first_points_json",
            "last_points_json",
        ],
    )
    write_csv(
        out_dir / f"{args.prefix}_water_layout_u32_3249_samples.csv",
        table_rows,
        ["export_index", "object_name", "table", "rel", "hex", "u32", "i32", "f32"],
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
