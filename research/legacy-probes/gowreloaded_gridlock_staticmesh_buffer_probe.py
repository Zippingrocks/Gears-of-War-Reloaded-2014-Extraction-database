#!/usr/bin/env python3
"""Probe Gridlock StaticMesh position/static-vertex halves and UV offsets."""

from __future__ import annotations

import argparse
import csv
import json
import math
import struct
from pathlib import Path
from typing import Any


TARGET_TERMS = [
    "cog_undentedcar1_frame",
    "ms_neutral_sedan_smesh",
    "bsp_gridlock_bld_01",
    "sdstitchingproxy_2550",
    "bsp_gridlock_road_b",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--terms", nargs="*", default=TARGET_TERMS)
    return parser.parse_args()


def f16(data: bytes, off: int) -> float:
    return struct.unpack_from("<e", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_json_field(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def read_indices(data: bytes, base: int, count: int, size: int) -> list[int]:
    out: list[int] = []
    for index in range(count):
        off = base + index * size
        if off + size > len(data):
            break
        out.append(u16(data, off) if size == 2 else struct.unpack_from("<I", data, off)[0])
    return out


def read_pos(data: bytes, base: int, index: int) -> tuple[float, float, float]:
    off = base + index * 12
    return (f32(data, off), f32(data, off + 4), f32(data, off + 8))


def read_uv(data: bytes, base: int, stride: int, index: int, offset: int) -> tuple[float, float] | None:
    off = base + index * stride + offset
    if off + 4 > len(data):
        return None
    u = f16(data, off)
    v = f16(data, off + 2)
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (float(u), float(v))


def vec_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def uv_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
    }


def uv_stats(uvs: list[tuple[float, float]]) -> dict[str, Any]:
    if not uvs:
        return {}
    us = [uv[0] for uv in uvs]
    vs = [uv[1] for uv in uvs]
    return {
        "count": len(uvs),
        "unique4": len({(round(u, 4), round(v, 4)) for u, v in uvs}),
        "u_min": min(us),
        "u_max": max(us),
        "v_min": min(vs),
        "v_max": max(vs),
        "span_u": max(us) - min(us),
        "span_v": max(vs) - min(vs),
        "unitish_ratio": sum(1 for u, v in uvs if -0.25 <= u <= 1.25 and -0.25 <= v <= 1.25) / len(uvs),
        "sample": [[round(u, 6), round(v, 6)] for u, v in uvs[:8]],
    }


def probe_row(row: dict[str, str], data: bytes) -> dict[str, Any]:
    geom = parse_json_field(row.get("geometry_json", ""))
    static = geom.get("static_vertex_buffer") or {}
    ib = geom.get("index_buffer") or {}
    serial = int(row["serial_offset"])
    vertex_base = serial + int(row["vertex_rel"])
    static_base = serial + int(static.get("data_rel") or 0)
    stride = int(static.get("element_size") or 0)
    static_count = int(static.get("count") or 0)
    index_base = serial + int(ib.get("data_rel") or row.get("index_rel") or 0)
    index_count = int(ib.get("count") or row.get("index_count") or 0)
    index_size = int(ib.get("element_size") or 2)
    indices = read_indices(data, index_base, index_count, index_size)
    used = sorted({idx for idx in indices if 0 <= idx < static_count})
    half = static_count // 2
    comparable = [idx for idx in used if idx + half < static_count]

    pos_deltas = [vec_dist(read_pos(data, vertex_base, idx), read_pos(data, vertex_base, idx + half)) for idx in comparable[:2000]]
    uv_delta_by_offset: dict[str, Any] = {}
    uv_stats_by_domain_offset: dict[str, Any] = {}
    for offset in range(0, max(0, stride - 3), 4):
        pairs: list[float] = []
        first_uvs: list[tuple[float, float]] = []
        second_uvs: list[tuple[float, float]] = []
        for idx in comparable[:5000]:
            a = read_uv(data, static_base, stride, idx, offset)
            b = read_uv(data, static_base, stride, idx + half, offset)
            if a is None or b is None:
                continue
            pairs.append(uv_dist(a, b))
            first_uvs.append(a)
            second_uvs.append(b)
        uv_delta_by_offset[f"half@{offset}"] = stats(pairs)
        uv_stats_by_domain_offset[f"index_half@{offset}"] = uv_stats(first_uvs)
        uv_stats_by_domain_offset[f"index_plus_half_half@{offset}"] = uv_stats(second_uvs)

    return {
        "full_path": row.get("full_path"),
        "export_index": int(row.get("export_index") or 0),
        "vertex_count": int(row.get("vertex_count") or 0),
        "index_count": index_count,
        "index_min": min(indices) if indices else None,
        "index_max": max(indices) if indices else None,
        "static_vertex_count": static_count,
        "static_vertex_stride": stride,
        "half": half,
        "used_vertex_count": len(used),
        "used_plus_half_available": len(comparable),
        "position_first_second_delta": stats(pos_deltas),
        "uv_first_second_delta_by_offset": uv_delta_by_offset,
        "uv_stats_by_domain_offset": uv_stats_by_domain_offset,
    }


def main() -> int:
    args = parse_args()
    data = Path(args.package).read_bytes()
    rows = read_rows(Path(args.csv))
    wanted = [
        row for row in rows
        if row.get("extract_status") == "bulk_position_index"
        and any(term.lower() in row.get("full_path", "").lower() for term in args.terms)
    ]
    proof = {
        "csv": str(Path(args.csv)),
        "package": str(Path(args.package)),
        "terms": args.terms,
        "rows": [probe_row(row, data) for row in wanted],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
