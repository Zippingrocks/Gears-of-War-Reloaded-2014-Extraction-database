#!/usr/bin/env python3
"""Probe bytes around MP_Gridlock StaticMesh UV stream bulk arrays.

This is a small repo-guided diagnostic: UEViewer's UE3 `FStaticMeshUVStream3`
reader expects metadata immediately before the UV item bulk payload:

    NumTexCoords, ItemSize, NumVerts, bUseFullPrecisionUVs

Our clean extractor already records the payload `data_rel`. This probe reads
near that offset for representative meshes so we can tell whether a bad visual
result is coming from stream layout metadata or from later Blender binding.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path
from typing import Any


DEFAULT_TARGETS = {
    "neutral_vehicles.ms_neutral_sedan_smesh",
    "cog_city_architecture.cog_undentedcar1_frame_smesh_dr",
    "cog_city_architecture_03.cog_city_brokencarchasey1_smesh_dr",
    "cog_city_ephyra2.cog_city_ephyra_facade03_sidetile_ms_smesh",
    "delta_gridlock_01.bsp.bsp_gridlock_road_b_smesh",
    "delta_gridlock_01.bsp_gridlock_bld_01_smesh_delta",
    "mp_gridlock_stitchingdata.sdstitchingproxy_2661_staticmesh",
    "mp_gridlock_stitchingdata.sdstitchingproxy_2409_staticmesh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--targets", nargs="*", default=sorted(DEFAULT_TARGETS))
    return parser.parse_args()


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_json_field(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def metadata_candidates(data: bytes, payload_abs: int, static_count: int, element_size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for back in range(8, 65, 4):
        off = payload_abs - back
        if off < 0 or off + 16 > len(data):
            continue
        values = [i32(data, off + index * 4) for index in range(4)]
        score = 0
        reasons: list[str] = []
        if 1 <= values[0] <= 8:
            score += 3
            reasons.append("num_texcoords_plausible")
        if values[1] == element_size:
            score += 4
            reasons.append("item_size_matches_clean")
        if values[2] == static_count:
            score += 4
            reasons.append("num_verts_matches_clean")
        if values[3] in {0, 1}:
            score += 2
            reasons.append("full_precision_flag_plausible")
        rows.append(
            {
                "metadata_abs": off,
                "bytes_before_payload": back,
                "i32": values,
                "u32_hex": [f"0x{u32(data, off + index * 4):08x}" for index in range(4)],
                "score": score,
                "reasons": reasons,
            }
        )
    return sorted(rows, key=lambda row: (row["score"], -row["bytes_before_payload"]), reverse=True)[:8]


def main() -> int:
    args = parse_args()
    targets = {target.lower() for target in args.targets}
    data = Path(args.package).read_bytes()
    rows = read_csv_rows(Path(args.clean_csv))
    out_rows: list[dict[str, Any]] = []

    for row in rows:
        full_path = str(row.get("full_path") or "")
        if full_path.lower() not in targets:
            continue
        geom = parse_json_field(row.get("geometry_json", ""), {})
        static_vertex = geom.get("static_vertex_buffer") or {}
        static_count = int(static_vertex.get("count") or 0)
        element_size = int(static_vertex.get("element_size") or 0)
        serial_offset = int(row.get("serial_offset") or 0)
        data_rel = int(static_vertex.get("data_rel") or 0)
        payload_abs = serial_offset + data_rel
        out_rows.append(
            {
                "full_path": full_path,
                "object_name": row.get("object_name", ""),
                "extract_status": row.get("extract_status", ""),
                "vertex_count": int(row.get("vertex_count") or 0),
                "index_count": int(row.get("index_count") or 0),
                "static_count": static_count,
                "static_element_size": element_size,
                "static_data_rel": data_rel,
                "payload_abs": payload_abs,
                "payload_first_u32": [f"0x{u32(data, payload_abs + index * 4):08x}" for index in range(4) if payload_abs + index * 4 + 4 <= len(data)],
                "metadata_candidates": metadata_candidates(data, payload_abs, static_count, element_size),
            }
        )

    proof = {
        "package": str(Path(args.package)),
        "clean_csv": str(Path(args.clean_csv)),
        "repo_basis": "UEViewer UE3 FStaticMeshUVStream3 metadata probe: NumTexCoords, ItemSize, NumVerts, bUseFullPrecisionUVs before UV bulk payload.",
        "rows": out_rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
