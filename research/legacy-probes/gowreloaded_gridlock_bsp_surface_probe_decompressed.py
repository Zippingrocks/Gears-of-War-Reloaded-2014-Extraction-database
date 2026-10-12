#!/usr/bin/env python3
"""Probe MP_Gridlock BSP FBspSurf records from a decompressed Reloaded package."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import struct
import sys
import types
from pathlib import Path
from typing import Any


BSP_CONFIDENCE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)


def install_fake_lz4() -> None:
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")

    def _unused_decompress(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("compressed package decode is not used by this decompressed-package probe")

    block_module.decompress = _unused_decompress  # type: ignore[attr-defined]
    lz4_module.block = block_module  # type: ignore[attr-defined]
    sys.modules.setdefault("lz4", lz4_module)
    sys.modules.setdefault("lz4.block", block_module)


def load_bsp_module():
    install_fake_lz4()
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
    parser.add_argument("--decompressed", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--targets", nargs="*", type=int, default=[11544, 11545, 11546, 11548, 11549, 11550])
    return parser.parse_args()


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def vec3(data: bytes, off: int) -> list[float]:
    return [f32(data, off), f32(data, off + 4), f32(data, off + 8)]


def dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def finite(values: list[float]) -> bool:
    return all(math.isfinite(value) and abs(value) < 1_000_000 for value in values)


def read_vecs(virt: bytes, serial_offset: int, rel: int, count: int) -> list[list[float]]:
    return [vec3(virt, serial_offset + rel + idx * 12) for idx in range(count)]


def ref_kind(path: str) -> str:
    lower = path.lower()
    if not path:
        return ""
    if "material" in lower or lower.endswith("_mat") or "_mat." in lower or ".mat_" in lower or "mat__" in lower:
        return "material_like"
    if "actor" in lower or "level" in lower:
        return "actor_or_level_like"
    return "object_ref"


def surf_words(virt: bytes, row: dict[str, Any], lm: dict[str, Any], ref_path, surf_index: int) -> dict[str, Any]:
    serial_offset = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    surf_abs = serial_offset + surf_rel + 8 + surf_index * bsp.SURF_RECORD_SIZE
    points = read_vecs(virt, serial_offset, int(lm["points"]["data_rel"]), int(lm["points"]["count"]))
    vectors = read_vecs(virt, serial_offset, int(lm["vectors"]["data_rel"]), int(lm["vectors"]["count"]))
    words: list[dict[str, Any]] = []
    for rel in range(0, bsp.SURF_RECORD_SIZE, 4):
        value = i32(virt, surf_abs + rel)
        entry: dict[str, Any] = {
            "rel": rel,
            "i32": value,
            "f32": f32(virt, surf_abs + rel),
        }
        path = ""
        if value:
            try:
                path = ref_path(value)
            except Exception:
                path = ""
        if path:
            entry["ref_path"] = path
            entry["ref_kind"] = ref_kind(path)
        if 0 <= value < len(points):
            entry["point"] = points[value]
        if 0 <= value < len(vectors):
            entry["vector"] = vectors[value]
        words.append(entry)
    return {"surf_index": surf_index, "surf_abs": surf_abs, "words": words}


def score_layout(
    virt: bytes,
    row: dict[str, Any],
    lm: dict[str, Any],
    decoded: dict[str, Any],
    material_rel: int,
    pbase_rel: int,
    u_rel: int,
    v_rel: int,
    ref_path,
) -> dict[str, Any]:
    serial_offset = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    points = read_vecs(virt, serial_offset, int(lm["points"]["data_rel"]), int(lm["points"]["count"]))
    vectors = read_vecs(virt, serial_offset, int(lm["vectors"]["data_rel"]), int(lm["vectors"]["count"]))
    valid_faces = 0
    invalid = 0
    material_paths: set[str] = set()
    spans: list[float] = []
    for node, polygon in zip(decoded.get("nodes", []), decoded.get("polygons", []), strict=False):
        surf_index = int(node.get("i_surf", -1))
        if surf_index < 0 or surf_index >= int(decoded.get("surf_count") or 0):
            invalid += 1
            continue
        surf_abs = serial_offset + surf_rel + 8 + surf_index * bsp.SURF_RECORD_SIZE
        mat_ref = i32(virt, surf_abs + material_rel)
        pbase = i32(virt, surf_abs + pbase_rel)
        u_index = i32(virt, surf_abs + u_rel)
        v_index = i32(virt, surf_abs + v_rel)
        if mat_ref:
            try:
                material_paths.add(ref_path(mat_ref))
            except Exception:
                pass
        if not (0 <= pbase < len(points) and 0 <= u_index < len(vectors) and 0 <= v_index < len(vectors)):
            invalid += 1
            continue
        base = points[pbase]
        u_vec = vectors[u_index]
        v_vec = vectors[v_index]
        if not (finite(base) and finite(u_vec) and finite(v_vec)):
            invalid += 1
            continue
        uvs = [(dot(sub(points[point_idx], base), u_vec), dot(sub(points[point_idx], base), v_vec)) for point_idx in polygon]
        if not uvs or not all(math.isfinite(u) and math.isfinite(v) for u, v in uvs):
            invalid += 1
            continue
        span_u = max(u for u, _ in uvs) - min(u for u, _ in uvs)
        span_v = max(v for _, v in uvs) - min(v for _, v in uvs)
        spans.append(abs(span_u) + abs(span_v))
        valid_faces += 1
    mat_like_count = sum(1 for path in material_paths if ref_kind(path) == "material_like")
    return {
        "material_rel": material_rel,
        "pbase_rel": pbase_rel,
        "u_rel": u_rel,
        "v_rel": v_rel,
        "valid_faces": valid_faces,
        "invalid_faces": invalid,
        "unique_material_refs": len(material_paths),
        "material_like_refs": mat_like_count,
        "material_ref_samples": sorted(path for path in material_paths if path)[:12],
        "span_min": min(spans) if spans else 0,
        "span_max": max(spans) if spans else 0,
        "span_avg": sum(spans) / len(spans) if spans else 0,
    }


def main() -> int:
    args = parse_args()
    package = Path(args.decompressed)
    virt = package.read_bytes()
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])

    rows: list[dict[str, Any]] = []
    for export_index in args.targets:
        row = exports[export_index - 1]
        lm = bsp.decode_landmarks(virt, names, imports, exports, ref_path, row)
        if not lm:
            rows.append({"export_index": export_index, "status": "missing_landmarks"})
            continue
        decoded = bsp.decode_model_faces(virt, row, lm)
        used_surfs = sorted(
            {
                int(node.get("i_surf", -1))
                for node in decoded.get("nodes", [])
                if int(node.get("i_surf", -1)) >= 0
            }
        )
        candidates: list[dict[str, Any]] = []
        for material_rel in range(0, bsp.SURF_RECORD_SIZE, 4):
            for pbase_rel, u_rel, v_rel in ((8, 16, 20), (12, 16, 20), (8, 12, 16), (12, 20, 24)):
                candidates.append(score_layout(virt, row, lm, decoded, material_rel, pbase_rel, u_rel, v_rel, ref_path))
        candidates.sort(
            key=lambda item: (
                -int(item["material_like_refs"]),
                int(item["invalid_faces"]),
                -int(item["valid_faces"]),
                abs(float(item["span_avg"]) - 1.0),
                int(item["material_rel"]),
            )
        )
        rows.append(
            {
                "export_index": export_index,
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "class_name": row.get("class_name", ""),
                "serial_offset": row["serial_offset"],
                "serial_size": row["serial_size"],
                "decode_status": decoded.get("status"),
                "surf_count": decoded.get("surf_count"),
                "used_surfs": used_surfs,
                "points_count": int(lm["points"]["count"]),
                "vectors_count": int(lm["vectors"]["count"]),
                "nodes_count": int(lm["nodes"]["count"]),
                "chosen_point_field_rel": decoded.get("chosen_point_field_rel"),
                "layout_candidates": candidates[:12],
                "surf_samples": [surf_words(virt, row, lm, ref_path, surf_index) for surf_index in used_surfs[:8]],
            }
        )
    proof = {
        "package": str(package),
        "targets": args.targets,
        "bsp_surface_record_size": bsp.SURF_RECORD_SIZE,
        "bsp_vertex_record_size": bsp.VERT_RECORD_SIZE,
        "rows": rows,
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "targets": len(rows)}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
