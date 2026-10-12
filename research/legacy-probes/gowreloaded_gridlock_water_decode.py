#!/usr/bin/env python3
"""Decode MP_Gridlock Reloaded skeletal water mesh geometry to proof OBJs."""

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
WATER_ACTOR_LOCATIONS = {
    "gridlockWater_skMesh_sc_ma_00_gridlock_water_00_MESH": (3200.0, -4300.0, 112.0),
    "gridlockWater_skMesh_sc_ma_01_gridlock_water_01_MESH": (3200.0, 700.0, 112.0),
    "gridlockWater_skMesh_sc_ma_02_gridlock_water_02_MESH": (3200.0, 5700.0, 112.0),
}


def load_heavy():
    spec = importlib.util.spec_from_file_location("gowr_heavy", HEAVY_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser: {HEAVY_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def compact(value: Any, limit: int = 2400) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def finite(value: float, limit: float = 500_000.0) -> bool:
    return math.isfinite(value) and abs(value) <= limit


def safe_name(text: str) -> str:
    out = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text]
    while "__" in "".join(out):
        out = list("".join(out).replace("__", "_"))
    return "".join(out).strip("_")


def bounds(points: list[tuple[float, float, float]]) -> dict[str, Any]:
    mins = [min(p[i] for p in points) for i in range(3)]
    maxs = [max(p[i] for p in points) for i in range(3)]
    center = [(mins[i] + maxs[i]) / 2.0 for i in range(3)]
    extent = [(maxs[i] - mins[i]) / 2.0 for i in range(3)]
    return {"min": mins, "max": maxs, "center": center, "extent": extent}


def read_indices(data: bytes, header_rel: int, count: int) -> list[int]:
    start = header_rel + 8
    return [u16(data, start + idx * 2) for idx in range(count)]


def find_index_header(data: bytes, start_rel: int) -> dict[str, Any] | None:
    for rel in range(max(0, start_rel), max(0, len(data) - 8)):
        element_size = i32(data, rel)
        count = i32(data, rel + 4)
        if element_size != 2 or count != 18816:
            continue
        end_rel = rel + 8 + element_size * count
        if end_rel > len(data):
            continue
        indices = read_indices(data, rel, count)
        if min(indices) == 0 and max(indices) == 3248 and len(set(indices)) == 3249:
            return {
                "start_rel": rel,
                "data_rel": rel + 8,
                "count": count,
                "triangle_count": count // 3,
                "end_rel": end_rel,
                "min_index": min(indices),
                "max_index": max(indices),
                "unique_indices": len(set(indices)),
                "first_indices": indices[:24],
                "last_indices": indices[-24:],
            }
    return None


def read_vertices(
    data: bytes,
    vertex_rel: int,
    count: int,
    stride: int,
    pos_offset: int,
    uv_offset: int,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float]]]:
    verts: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    for idx in range(count):
        base = vertex_rel + idx * stride
        pos = (f32(data, base + pos_offset), f32(data, base + pos_offset + 4), f32(data, base + pos_offset + 8))
        uv = (f32(data, base + uv_offset), f32(data, base + uv_offset + 4))
        if not all(finite(v) for v in pos):
            raise ValueError(f"non-finite position at vertex {idx}: {pos}")
        if not all(finite(v, 1000.0) for v in uv):
            uv = (0.0, 0.0)
        verts.append(pos)
        uvs.append(uv)
    return verts, uvs


def score_vertex_stream(points: list[tuple[float, float, float]]) -> dict[str, Any] | None:
    b = bounds(points)
    extent = b["extent"]
    xy = max(extent[0], extent[1])
    z = extent[2]
    if xy < 1000.0 or xy > 100_000.0:
        return None
    if z > 500.0:
        return None
    unique_sample = len(set(points[:: max(1, len(points) // 96)]))
    if unique_sample < 16:
        return None
    return {"bounds": b, "xy_extent_max": xy, "z_extent": z, "unique_sample": unique_sample}


def try_vertex_stream(
    data: bytes,
    rel: int,
    vertex_count: int,
    stride: int,
    pos_offset: int,
    uv_offset: int,
) -> dict[str, Any] | None:
    if rel < 0 or rel + (vertex_count - 1) * stride + max(pos_offset + 12, uv_offset + 8) > len(data):
        return None
    try:
        points, uvs = read_vertices(data, rel, vertex_count, stride, pos_offset, uv_offset)
        score = score_vertex_stream(points)
        if not score:
            return None
        return {
            "vertex_rel": rel,
            "vertex_count": vertex_count,
            "stride": stride,
            "pos_offset": pos_offset,
            "uv_offset": uv_offset,
            "score": score,
            "points": points,
            "uvs": uvs,
        }
    except Exception:  # noqa: BLE001
        return None


def find_vertex_stream(data: bytes, index_end_rel: int, vertex_count: int = 3249) -> dict[str, Any] | None:
    # Reloaded Gridlock strips 00 and 02 place 3249 skinned water vertices 508 bytes after
    # the unaligned u16 index payload. XYZ begins at the candidate base; UV0 follows at +20.
    for rel, stride, pos_offset, uv_offset in (
        (index_end_rel + 508, 64, 0, 20),
        (index_end_rel + 538, 64, 0, 20),
        (index_end_rel + 504, 64, 4, 24),
    ):
        candidate = try_vertex_stream(data, rel, vertex_count, stride, pos_offset, uv_offset)
        if candidate:
            return candidate

    candidates: list[dict[str, Any]] = []
    search_start = max(0, index_end_rel)
    search_end = min(len(data), index_end_rel + 32_000)
    layouts = [(64, 4, 24), (68, 4, 24), (64, 0, 20), (68, 0, 20), (60, 4, 24), (72, 4, 24)]
    for rel in range(search_start, search_end):
        for stride, pos_offset, uv_offset in layouts:
            if rel + (vertex_count - 1) * stride + max(pos_offset + 12, uv_offset + 8) > len(data):
                continue
            try:
                # Cheap sample before the full read.
                sample = []
                for idx in (0, 1, 2, vertex_count // 2, vertex_count - 3, vertex_count - 2, vertex_count - 1):
                    base = rel + idx * stride + pos_offset
                    pos = (f32(data, base), f32(data, base + 4), f32(data, base + 8))
                    if not all(finite(v) for v in pos):
                        raise ValueError
                    sample.append(pos)
                sample_score = score_vertex_stream(sample)
                if not sample_score:
                    continue
                candidate = try_vertex_stream(data, rel, vertex_count, stride, pos_offset, uv_offset)
                if not candidate:
                    continue
                candidates.append(candidate)
            except Exception:  # noqa: BLE001
                continue
    candidates.sort(key=lambda c: (c["score"]["z_extent"], -c["score"]["xy_extent_max"], c["vertex_rel"], c["stride"]))
    return candidates[0] if candidates else None


def write_obj(
    path: Path,
    name: str,
    points: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    indices: list[int],
    translate: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tx, ty, tz = translate
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"# Reloaded MP_Gridlock decoded skeletal water proof\n")
        handle.write(f"o {safe_name(name)}\n")
        for x, y, z in points:
            handle.write(f"v {x + tx:.6f} {y + ty:.6f} {z + tz:.6f}\n")
        for u, v in uvs:
            handle.write(f"vt {u:.6f} {1.0 - v:.6f}\n")
        for idx in range(0, len(indices), 3):
            a, b, c = indices[idx] + 1, indices[idx + 1] + 1, indices[idx + 2] + 1
            handle.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")


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
    obj_dir = out_dir / "objs"
    out_dir.mkdir(parents=True, exist_ok=True)
    obj_dir.mkdir(parents=True, exist_ok=True)

    virt, groups, compression_mode = heavy.rebuild_virtual_package(package.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for row in exports:
        row["class_name"] = ref_short_name(row["class_ref"])
        row["full_path"] = ref_path(row["index"])

    rows: list[dict[str, Any]] = []
    topology_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in exports:
        if row["class_name"] != "SkeletalMesh" or not row["full_path"].startswith(WATER_MESH_PREFIX):
            continue
        blob = virt[row["serial_offset"] : row["serial_offset"] + row["serial_size"]]
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4, 8, 16, 32, 64, 68])
        property_end_rel = int(scan["result"].get("end_rel") or 0) if scan["result"].get("ok") else 0
        index = find_index_header(blob, property_end_rel)
        if not index:
            failures.append({"export_index": row["index"], "object_name": row["object_short_name"], "reason": "index_header_not_found"})
            continue
        topology_rows.append(
            {
                "package": package.name,
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "serial_offset": row["serial_offset"],
                "serial_size": row["serial_size"],
                "property_end_rel": property_end_rel,
                "index_start_rel": index["start_rel"],
                "index_data_rel": index["data_rel"],
                "index_end_rel": index["end_rel"],
                "index_count": index["count"],
                "triangle_count": index["triangle_count"],
                "index_min": index["min_index"],
                "index_max": index["max_index"],
                "unique_indices": index["unique_indices"],
                "first_indices_json": compact(index["first_indices"], 1000),
                "last_indices_json": compact(index["last_indices"], 1000),
                "topology_status": "decoded_57x57_u16_index_grid",
            }
        )
        vertex = find_vertex_stream(blob, index["end_rel"])
        if not vertex:
            failures.append(
                {
                    "export_index": row["index"],
                    "object_name": row["object_short_name"],
                    "reason": "vertex_stream_not_found",
                    "index_header_json": compact(index),
                }
            )
            continue
        indices = read_indices(blob, index["start_rel"], index["count"])
        points = vertex["points"]
        uvs = vertex["uvs"]
        local_obj = obj_dir / f"{safe_name(row['object_short_name'])}__local.obj"
        world_obj = obj_dir / f"{safe_name(row['object_short_name'])}__world.obj"
        actor_location = WATER_ACTOR_LOCATIONS.get(row["object_short_name"], (0.0, 0.0, 0.0))
        write_obj(local_obj, row["object_short_name"] + "_local", points, uvs, indices)
        write_obj(world_obj, row["object_short_name"] + "_world", points, uvs, indices, actor_location)
        row_out = {
            "package": package.name,
            "export_index": row["index"],
            "object_name": row["object_short_name"],
            "full_path": row["full_path"],
            "serial_offset": row["serial_offset"],
            "serial_size": row["serial_size"],
            "property_end_rel": property_end_rel,
            "index_start_rel": index["start_rel"],
            "index_count": index["count"],
            "triangle_count": index["triangle_count"],
            "index_min": index["min_index"],
            "index_max": index["max_index"],
            "unique_indices": index["unique_indices"],
            "vertex_rel": vertex["vertex_rel"],
            "vertex_count": vertex["vertex_count"],
            "vertex_stride": vertex["stride"],
            "position_offset": vertex["pos_offset"],
            "uv_offset": vertex["uv_offset"],
            "local_bounds_json": compact(vertex["score"]["bounds"], 2400),
            "actor_location_json": compact(actor_location),
            "local_obj": str(local_obj),
            "world_obj": str(world_obj),
            "decode_status": "decoded_index_and_vertex_stream",
        }
        rows.append(row_out)

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "package": str(package),
        "compression_mode": compression_mode,
        "compressed_groups": len(groups),
        "water_meshes_topology_decoded": len(topology_rows),
        "water_meshes_decoded": len(rows),
        "water_mesh_failures": len(failures),
        "total_vertices": sum(int(r["vertex_count"]) for r in rows),
        "total_triangles": sum(int(r["triangle_count"]) for r in rows),
        "source_tool": str(HEAVY_TOOL),
        "rule": "Decode MP_Gridlock skeletal water by unaligned 18816-u16 index topology and 3249 64-byte skinned-vertex records with XYZ at +0 and UV0 at +20. Strips 00/02 use index_end+508; strip 01 uses index_end+538.",
    }
    (out_dir / f"{args.prefix}_water_skeletal_decode_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    write_csv(
        out_dir / f"{args.prefix}_water_skeletal_topology_rows.csv",
        topology_rows,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_end_rel",
            "index_start_rel",
            "index_data_rel",
            "index_end_rel",
            "index_count",
            "triangle_count",
            "index_min",
            "index_max",
            "unique_indices",
            "first_indices_json",
            "last_indices_json",
            "topology_status",
        ],
    )
    write_csv(
        out_dir / f"{args.prefix}_water_skeletal_decode_rows.csv",
        rows,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_end_rel",
            "index_start_rel",
            "index_count",
            "triangle_count",
            "index_min",
            "index_max",
            "unique_indices",
            "vertex_rel",
            "vertex_count",
            "vertex_stride",
            "position_offset",
            "uv_offset",
            "local_bounds_json",
            "actor_location_json",
            "local_obj",
            "world_obj",
            "decode_status",
        ],
    )
    write_csv(out_dir / f"{args.prefix}_water_skeletal_decode_failures.csv", failures, ["export_index", "object_name", "reason", "index_header_json"])
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
