#!/usr/bin/env python3
"""Audit candidate UV half-float offsets for Reloaded MP_Gridlock StaticMeshes."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_prepare_textured_blend_export.py"
)

DEFAULT_NAMES = [
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2409_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2377_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2378_StaticMesh",
    "Delta_Gridlock_01.BSP.bsp_gridlock_road_b_SMesh",
    "COG_City_Architecture.COG_UndentedCar1_Frame_SMesh_DR",
    "Neutral_Vehicles.MS_Neutral_Sedan_SMesh",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--names", nargs="*", default=DEFAULT_NAMES)
    parser.add_argument("--sample-count", type=int, default=128)
    return parser.parse_args(passthrough)


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location("gowr_prepare", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def stat_pairs(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    finite = [(u, v) for u, v in pairs if math.isfinite(u) and math.isfinite(v)]
    if not finite:
        return {"finite": 0}
    us = [u for u, _ in finite]
    vs = [v for _, v in finite]
    rounded = {(round(u, 4), round(v, 4)) for u, v in finite}
    plausible = [(u, v) for u, v in finite if -64.0 <= u <= 64.0 and -64.0 <= v <= 64.0]
    unitish = [(u, v) for u, v in finite if -4.0 <= u <= 4.0 and -4.0 <= v <= 4.0]
    return {
        "finite": len(finite),
        "unique_rounded": len(rounded),
        "u_min": min(us),
        "u_max": max(us),
        "v_min": min(vs),
        "v_max": max(vs),
        "u_span": max(us) - min(us),
        "v_span": max(vs) - min(vs),
        "plausible_frac_abs64": len(plausible) / len(finite),
        "unitish_frac_abs4": len(unitish) / len(finite),
        "sample": [[round(u, 8), round(v, 8)] for u, v in finite[:16]],
    }


def read_pairs(src: Any, virt: bytes, static_base: int, element_size: int, offset: int, count: int, flip_v: bool) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for index in range(count):
        off = static_base + index * element_size + offset
        if off + 4 > len(virt):
            break
        u = src.f16(virt, off)
        v_raw = src.f16(virt, off + 2)
        v = 1.0 - v_raw if flip_v else v_raw
        pairs.append((float(u), float(v)))
    return pairs


def read_positions(src: Any, virt: bytes, pos_base: int, count: int) -> list[list[float]]:
    rows: list[list[float]] = []
    for index in range(count):
        off = pos_base + index * 12
        if off + 12 > len(virt):
            break
        rows.append([round(src.f32(virt, off), 6), round(src.f32(virt, off + 4), 6), round(src.f32(virt, off + 8), 6)])
    return rows


def audit_row(src: Any, map_dir: Path, row: dict[str, str], package_cache: dict[str, bytes], sample_count: int) -> dict[str, Any]:
    virt = src.package_virtual_bytes(map_dir, row["package"], package_cache)
    geom = src.parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    position_buffer = geom.get("position_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    data_rel = int(static_vertex.get("data_rel") or 0)
    static_count = int(static_vertex.get("count") or 0)
    serial_offset = int(row["serial_offset"])
    vertex_count = int(row["vertex_count"])
    static_base = serial_offset + data_rel
    pos_base = serial_offset + int(position_buffer.get("data_rel") or row["vertex_rel"])
    count = min(static_count or vertex_count, vertex_count, sample_count)
    candidates: dict[str, Any] = {}
    for offset in range(0, max(element_size - 3, 0), 4):
        candidates[str(offset)] = stat_pairs(read_pairs(src, virt, static_base, element_size, offset, count, True))
    return {
        "full_path": row["full_path"],
        "package": row["package"],
        "object_name": row["object_name"],
        "extract_status": row["extract_status"],
        "vertex_count": vertex_count,
        "index_count": int(row["index_count"]),
        "position_sample": read_positions(src, virt, pos_base, min(6, count)),
        "static_vertex_element_size": element_size,
        "static_vertex_count": static_count,
        "static_vertex_data_rel": data_rel,
        "candidate_offsets": candidates,
    }


def main() -> int:
    args = parse_args()
    src = load_source()
    rows = read_csv(Path(args.clean_csv))
    by_path = {row.get("full_path", "").lower(): row for row in rows}
    package_cache: dict[str, bytes] = {}
    audits = []
    missing = []
    for name in args.names:
        row = by_path.get(name.lower())
        if not row:
            missing.append(name)
            continue
        audits.append(audit_row(src, Path(args.map_dir), row, package_cache, args.sample_count))
    proof = {"audits": audits, "missing": missing}
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
