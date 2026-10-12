#!/usr/bin/env python3
"""Probe Reloaded MP_Gridlock BSP surface records for material/UV fields."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any


BSP_CONFIDENCE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)


def load_bsp_module():
    spec = importlib.util.spec_from_file_location("gowr_bsp_confidence", BSP_CONFIDENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load BSP confidence module: {BSP_CONFIDENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_bsp_confidence"] = module
    spec.loader.exec_module(module)
    return module


bsp = load_bsp_module()
heavy = bsp.heavy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--package", default="MP_Gridlock.war")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-models", type=int, default=12)
    return parser.parse_args()


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def read_vec3(virt: bytes, serial_offset: int, rel: int, index: int) -> list[float]:
    off = serial_offset + rel + index * 12
    return [f32(virt, off), f32(virt, off + 4), f32(virt, off + 8)]


def finite_vec(values: list[float]) -> bool:
    return all(math.isfinite(value) and abs(value) < 1_000_000 for value in values)


def surf_record_probe(
    virt: bytes,
    row: dict[str, Any],
    lm: dict[str, Any],
    ref_path,
    surf_index: int,
) -> dict[str, Any]:
    surf_rel = int(lm["nodes"]["end_rel"])
    surf_abs = int(row["serial_offset"]) + surf_rel + 8 + surf_index * bsp.SURF_RECORD_SIZE
    words: list[dict[str, Any]] = []
    vectors_rel = int(lm["vectors"]["data_rel"])
    points_rel = int(lm["points"]["data_rel"])
    vector_count = int(lm["vectors"]["count"])
    point_count = int(lm["points"]["count"])
    for rel in range(0, bsp.SURF_RECORD_SIZE, 4):
        value = i32(virt, surf_abs + rel)
        entry: dict[str, Any] = {"rel": rel, "i32": value, "f32": f32(virt, surf_abs + rel)}
        if value != 0:
            try:
                path = ref_path(value)
            except Exception:
                path = ""
            if path:
                entry["ref_path"] = path
        if 0 <= value < point_count:
            point = read_vec3(virt, int(row["serial_offset"]), points_rel, value)
            if finite_vec(point):
                entry["as_point"] = point
        if 0 <= value < vector_count:
            vector = read_vec3(virt, int(row["serial_offset"]), vectors_rel, value)
            if finite_vec(vector):
                entry["as_vector"] = vector
        words.append(entry)
    return {"surf_index": surf_index, "words": words}


def main() -> int:
    args = parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    wanted = {
        int(row["export_index"]): row
        for row in manifest.get("bsp_models", [])
        if str(row.get("package", "")).lower() == args.package.lower()
    }
    package_path = Path(args.map_dir) / args.package
    data = package_path.read_bytes()
    virt, groups, mode = heavy.rebuild_virtual_package(data)
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])

    rows: list[dict[str, Any]] = []
    for row in exports:
        if int(row["index"]) not in wanted:
            continue
        lm = bsp.decode_landmarks(virt, names, imports, exports, ref_path, row)
        if not lm:
            continue
        decoded = bsp.decode_model_faces(virt, row, lm)
        used_surfs = sorted({int(node["i_surf"]) for node in decoded.get("nodes", []) if int(node.get("i_surf", -1)) >= 0})
        rows.append(
            {
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "surf_count": decoded.get("surf_count", ""),
                "used_surfs": used_surfs,
                "vectors_count": int(lm["vectors"]["count"]),
                "points_count": int(lm["points"]["count"]),
                "nodes_count": int(lm["nodes"]["count"]),
                "sample_surfs": [
                    surf_record_probe(virt, row, lm, ref_path, surf_index)
                    for surf_index in used_surfs[:8]
                    if surf_index < int(decoded.get("surf_count") or 0)
                ],
            }
        )
        if len(rows) >= args.max_models:
            break
    proof = {
        "package": str(package_path),
        "compression_mode": mode,
        "compressed_groups": len(groups),
        "models_sampled": len(rows),
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": args.out, "models_sampled": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
