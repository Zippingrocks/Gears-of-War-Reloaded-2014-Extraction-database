#!/usr/bin/env python3
"""Probe indexed StaticMesh UV domains for Reloaded MP_Gridlock.

The original bulk OBJ exporter wrote UVs from the same raw vertex index as the
position index. Several Gridlock meshes have index buffers that address only
the first half of a doubled static-vertex stream, so this probe scores the UVs
actually reached by triangle indices for both index and index+half domains.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_prepare_textured_blend_export.py"
)

DEFAULT_TARGETS = [
    "Delta_Gridlock_01.BSP.bsp_gridlock_road_b_SMesh",
    "COG_City_Ephyra2.COG_City_Ephyra2_1post_Smesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2377_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2378_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2381_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2409_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2755_StaticMesh",
    "Neutral_Vehicles.MS_Neutral_Sedan_SMesh",
    "COG_City_Architecture.COG_UndentedCar1_Frame_SMesh_DR",
    "COG_City_Architecture_03.COG_City_BrokenCarChasey1_Smesh_DR",
    "COG_City_Ephyra.COG_City_Ephyra_Facade03_SideTile_MS_SMesh",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target-names", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--all-scene-assets", action="store_true")
    return parser.parse_args()


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location("gowr_prepare", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def finish_v(v: float, flip_v: bool) -> float:
    return float(1.0 - v if flip_v and math.isfinite(v) else v)


def read_index(src: Any, virt: bytes, off: int, element_size: int) -> int:
    if element_size == 2:
        return int(src.u16(virt, off))
    return int(src.u32(virt, off))


def read_indices(src: Any, virt: bytes, base: int, count: int, element_size: int) -> list[int]:
    indices: list[int] = []
    for index in range(count):
        off = base + index * element_size
        if off + element_size > len(virt):
            break
        indices.append(read_index(src, virt, off, element_size))
    return indices


def read_uv(
    src: Any,
    virt: bytes,
    base: int,
    element_size: int,
    offset: int,
    static_index: int,
    encoding: str,
    flip_v: bool,
) -> tuple[float, float] | None:
    off = base + static_index * element_size + offset
    if encoding == "half":
        if off + 4 > len(virt):
            return None
        u = float(src.f16(virt, off))
        v = finish_v(float(src.f16(virt, off + 2)), flip_v)
    elif encoding == "float":
        if off + 8 > len(virt):
            return None
        u = float(src.f32(virt, off))
        v = finish_v(float(src.f32(virt, off + 4)), flip_v)
    else:
        return None
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (u, v)


def candidate_specs(element_size: int) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for offset in range(0, max(0, element_size - 3), 4):
        specs.append({"encoding": "half", "offset": offset, "name": f"half@{offset}"})
    for offset in range(0, max(0, element_size - 7), 4):
        specs.append({"encoding": "float", "offset": offset, "name": f"float@{offset}"})
    return specs


def triangle_area(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) * 0.5


def score_uvs(uv_by_vertex: dict[int, tuple[float, float]], indices: list[int], used: set[int]) -> dict[str, Any]:
    pairs = [uv_by_vertex[index] for index in sorted(used) if index in uv_by_vertex]
    finite_ratio = len(pairs) / max(1, len(used))
    if not pairs:
        return {"score": -9999.0, "finite_ratio": 0.0, "unique_rounded": 0}

    us = [pair[0] for pair in pairs]
    vs = [pair[1] for pair in pairs]
    unique = len({(round(u, 4), round(v, 4)) for u, v in pairs})
    unique_ratio = unique / max(1, len(pairs))
    span_u = max(us) - min(us)
    span_v = max(vs) - min(vs)
    reasonable = sum(1 for u, v in pairs if abs(u) <= 64.0 and abs(v) <= 64.0) / max(1, len(pairs))
    unitish = sum(1 for u, v in pairs if -0.25 <= u <= 1.25 and -0.25 <= v <= 1.25) / max(1, len(pairs))
    zeroish = sum(1 for u, v in pairs if abs(u) < 0.00001 and abs(v) < 0.00001) / max(1, len(pairs))

    tri_total = 0
    tri_valid = 0
    tri_degenerate = 0
    tri_area_sum = 0.0
    tri_area_max = 0.0
    for tri_index in range(0, len(indices) - 2, 3):
        tri = indices[tri_index : tri_index + 3]
        tri_total += 1
        if any(vertex not in uv_by_vertex for vertex in tri):
            continue
        tri_valid += 1
        area = triangle_area(uv_by_vertex[tri[0]], uv_by_vertex[tri[1]], uv_by_vertex[tri[2]])
        tri_area_sum += area
        tri_area_max = max(tri_area_max, area)
        if area < 1.0e-8:
            tri_degenerate += 1

    degenerate_ratio = tri_degenerate / max(1, tri_valid)
    avg_area = tri_area_sum / max(1, tri_valid)
    score = (
        finite_ratio * 40.0
        + unique_ratio * 35.0
        + min(span_u, 16.0) * 1.5
        + min(span_v, 16.0) * 1.5
        + reasonable * 25.0
        + unitish * 4.0
        - zeroish * 30.0
        - degenerate_ratio * 35.0
    )
    if unique < 4 or span_u < 0.0001 or span_v < 0.0001:
        score -= 60.0
    if reasonable < 0.98:
        score -= 60.0

    return {
        "score": round(score, 6),
        "finite": len(pairs),
        "finite_ratio": round(finite_ratio, 6),
        "unique_rounded": unique,
        "unique_ratio": round(unique_ratio, 6),
        "u_min": round(min(us), 8),
        "u_max": round(max(us), 8),
        "v_min": round(min(vs), 8),
        "v_max": round(max(vs), 8),
        "span_u": round(span_u, 8),
        "span_v": round(span_v, 8),
        "reasonable_abs64_ratio": round(reasonable, 6),
        "unitish_ratio": round(unitish, 6),
        "zeroish_ratio": round(zeroish, 6),
        "triangle_count": tri_total,
        "triangle_valid_ratio": round(tri_valid / max(1, tri_total), 6),
        "triangle_degenerate_ratio": round(degenerate_ratio, 6),
        "triangle_uv_area_avg": round(avg_area, 10),
        "triangle_uv_area_max": round(tri_area_max, 10),
        "sample": [[round(u, 8), round(v, 8)] for u, v in pairs[:8]],
    }


def domain_starts(static_count: int, max_index: int) -> list[dict[str, Any]]:
    domains = [{"name": "index", "start": 0, "policy": "face_index_to_same_static_vertex"}]
    half = static_count // 2
    if half > 0 and max_index + half < static_count:
        domains.append({"name": "index_plus_half", "start": half, "policy": "face_index_to_second_half_static_vertex"})
    return domains


def decode_candidate(
    src: Any,
    virt: bytes,
    static_base: int,
    element_size: int,
    spec: dict[str, Any],
    domain: dict[str, Any],
    indices: list[int],
    used: set[int],
    static_count: int,
    flip_v: bool,
) -> dict[str, Any] | None:
    start = int(domain["start"])
    offset = int(spec["offset"])
    encoding = str(spec["encoding"])
    if encoding == "half" and offset + 4 > element_size:
        return None
    if encoding == "float" and offset + 8 > element_size:
        return None
    if used and max(used) + start >= static_count:
        return None

    uv_by_vertex: dict[int, tuple[float, float]] = {}
    for vertex_index in used:
        uv = read_uv(src, virt, static_base, element_size, offset, vertex_index + start, encoding, flip_v)
        if uv is not None:
            uv_by_vertex[vertex_index] = uv

    return {
        "name": f"{domain['name']}__{spec['name']}",
        "domain": domain["name"],
        "domain_start": start,
        "encoding": encoding,
        "offset": offset,
        "policy": domain["policy"],
        "stats": score_uvs(uv_by_vertex, indices, used),
    }


def choose_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    plausible = [
        candidate
        for candidate in candidates
        if candidate["stats"].get("finite_ratio", 0.0) >= 0.99
        and candidate["stats"].get("unique_rounded", 0) >= 4
        and candidate["stats"].get("reasonable_abs64_ratio", 0.0) >= 0.98
        and candidate["stats"].get("triangle_valid_ratio", 0.0) >= 0.99
    ]
    if not plausible:
        plausible = candidates
    if not plausible:
        return None
    return max(
        plausible,
        key=lambda candidate: (
            float(candidate["stats"].get("score", -9999.0)),
            1 if candidate["domain"] == "index_plus_half" else 0,
            int(candidate["stats"].get("unique_rounded", 0)),
            -int(candidate["offset"]),
        ),
    )


def audit_row(
    src: Any,
    map_dir: Path,
    row: dict[str, str],
    package_cache: dict[str, bytes],
    flip_v: bool,
) -> dict[str, Any] | None:
    if row.get("extract_status") != "bulk_position_index":
        return None
    geom = src.parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    index_buffer = geom.get("index_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    static_count = int(static_vertex.get("count") or 0)
    if element_size <= 0 or static_count <= 0:
        return None

    serial_offset = int(row["serial_offset"])
    static_base = serial_offset + int(static_vertex.get("data_rel") or 0)
    index_base = serial_offset + int(index_buffer.get("data_rel") or row.get("index_rel") or 0)
    index_count = int(index_buffer.get("count") or row.get("index_count") or 0)
    index_element_size = int(index_buffer.get("element_size") or geom.get("index_element_size") or 2)
    virt = src.package_virtual_bytes(map_dir, row["package"], package_cache)
    indices = read_indices(src, virt, index_base, index_count, index_element_size)
    used = {index for index in indices if 0 <= index < static_count}
    if not used:
        return None

    candidates: list[dict[str, Any]] = []
    for domain in domain_starts(static_count, max(used)):
        for spec in candidate_specs(element_size):
            candidate = decode_candidate(
                src, virt, static_base, element_size, spec, domain, indices, used, static_count, flip_v
            )
            if candidate is not None:
                candidates.append(candidate)

    chosen = choose_candidate(candidates)
    if chosen is None:
        return None

    return {
        "full_path": row["full_path"],
        "object_name": row.get("object_name", ""),
        "package": row["package"],
        "export_index": int(row.get("export_index") or 0),
        "vertex_count": int(row.get("vertex_count") or 0),
        "index_count": index_count,
        "index_min": min(indices) if indices else "",
        "index_max": max(indices) if indices else "",
        "used_vertex_count": len(used),
        "static_vertex_element_size": element_size,
        "static_vertex_count": static_count,
        "static_vertex_data_rel": int(static_vertex.get("data_rel") or 0),
        "doubled_static_stream": static_count >= (max(used) + 1) * 2 if used else False,
        "chosen": {
            key: chosen[key]
            for key in ("name", "domain", "domain_start", "encoding", "offset", "policy")
        },
        "chosen_stats": chosen["stats"],
        "top_candidates": sorted(
            [
                {
                    "name": candidate["name"],
                    "domain": candidate["domain"],
                    "domain_start": candidate["domain_start"],
                    "encoding": candidate["encoding"],
                    "offset": candidate["offset"],
                    "score": candidate["stats"].get("score"),
                    "unique_rounded": candidate["stats"].get("unique_rounded"),
                    "span_u": candidate["stats"].get("span_u"),
                    "span_v": candidate["stats"].get("span_v"),
                    "degenerate": candidate["stats"].get("triangle_degenerate_ratio"),
                    "sample": candidate["stats"].get("sample"),
                }
                for candidate in candidates
            ],
            key=lambda item: float(item.get("score") or -9999.0),
            reverse=True,
        )[:12],
    }


def main() -> int:
    args = parse_args()
    src = load_source()
    scene_manifest = read_json(Path(args.scene_manifest))
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path", "")).lower(): row for row in clean_rows}

    if args.all_scene_assets:
        wanted = [
            str(asset.get("full_path", ""))
            for asset in scene_manifest.get("assets", [])
            if asset.get("full_path")
        ]
    else:
        wanted = list(args.target_names)

    package_cache: dict[str, bytes] = {}
    assets: dict[str, Any] = {}
    missing: list[str] = []
    skipped: Counter[str] = Counter()
    chosen_domains: Counter[str] = Counter()
    chosen_offsets: Counter[str] = Counter()
    doubled_chosen_half = 0

    for full_path in wanted:
        row = clean_by_path.get(full_path.lower())
        if not row:
            missing.append(full_path)
            continue
        decoded = audit_row(src, Path(args.map_dir), row, package_cache, bool(scene_manifest.get("flip_v", True)))
        if decoded is None:
            skipped[str(row.get("extract_status") or "unsupported")] += 1
            continue
        assets[full_path.lower()] = decoded
        chosen = decoded["chosen"]
        chosen_domains[chosen["domain"]] += 1
        chosen_offsets[f"{chosen['encoding']}@{chosen['offset']}"] += 1
        if decoded["doubled_static_stream"] and chosen["domain"] == "index_plus_half":
            doubled_chosen_half += 1

    target_audit = {name: assets.get(name.lower(), {"found": False}) for name in args.target_names}
    for value in target_audit.values():
        if isinstance(value, dict) and value.get("full_path"):
            value["found"] = True

    proof = {
        "target": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "source_scope": scene_manifest.get("source_scope", ""),
        "blend_path": scene_manifest.get("blend_path", ""),
        "map_dir": str(Path(args.map_dir)),
        "clean_csv": str(Path(args.clean_csv)),
        "scene_manifest": str(Path(args.scene_manifest)),
        "policy": "Score UV candidates through the triangle index buffer; test index and index+half domains for doubled static streams.",
        "summary": {
            "wanted_assets": len(wanted),
            "decoded_assets": len(assets),
            "missing_clean_rows": len(missing),
            "skipped_by_status": dict(skipped),
            "chosen_domains": dict(chosen_domains),
            "chosen_offsets": dict(chosen_offsets),
            "doubled_stream_assets_chosen_index_plus_half": doubled_chosen_half,
            "packages_read": sorted(package_cache),
        },
        "missing_clean_rows": missing[:80],
        "target_audit": target_audit,
        "assets": assets,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
