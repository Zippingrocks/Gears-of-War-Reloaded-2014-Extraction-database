#!/usr/bin/env python3
"""Export layout-aware render UVs for the Reloaded MP_Gridlock blend.

The first Gridlock UV repair forced every textured material to
UV0_Source_Offset4. That is only valid for one StaticMesh vertex-buffer
layout. This pass decodes the plausible UV streams by static-vertex stride and
emits one canonical render layer per mesh: UV_Source_Render.
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

RENDER_UV_LAYER = "UV_Source_Render"

TARGET_NAMES = [
    "Delta_Gridlock_01.BSP.bsp_gridlock_road_b_SMesh",
    "COG_City_Ephyra2.COG_City_Ephyra2_1post_Smesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2377_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2378_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2381_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2409_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2661_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2755_StaticMesh",
    "Neutral_Vehicles.MS_Neutral_Sedan_SMesh",
    "COG_City_Architecture.COG_UndentedCar1_Frame_SMesh_DR",
    "COG_City_Architecture.COG_UndentedCar1_FrontDoor_SMesh_DR",
    "COG_City_Architecture_03.COG_City_BrokenCarChasey1_Smesh_DR",
    "COG_City_Ephyra.COG_City_Ephyra_Facade03_SideTile_MS_SMesh",
    "COG_City_EBA.COG_City_EBA_Statue_whole",
    "COG_City_Ephyra7.COG_Ephyra_LargePillar3_Arch6_SMesh_DR",
    "DCR_Bridge.Traffic_Curved_Wall_B",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target-names", nargs="*", default=TARGET_NAMES)
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


def safe_half(src: Any, data: bytes, off: int) -> float:
    if off < 0 or off + 2 > len(data):
        return float("nan")
    return float(src.f16(data, off))


def safe_float(src: Any, data: bytes, off: int) -> float:
    if off < 0 or off + 4 > len(data):
        return float("nan")
    return float(src.f32(data, off))


def finish_v(v: float, flip_v: bool) -> float:
    if not math.isfinite(v):
        return v
    return float(1.0 - v if flip_v else v)


def decode_half_layer(
    src: Any,
    data: bytes,
    base: int,
    element_size: int,
    offset: int,
    vertex_count: int,
    flip_v: bool,
) -> list[list[float]]:
    out: list[list[float]] = []
    for vertex_index in range(vertex_count):
        off = base + vertex_index * element_size + offset
        u = safe_half(src, data, off)
        v = finish_v(safe_half(src, data, off + 2), flip_v)
        if not math.isfinite(u) or not math.isfinite(v):
            out.append([0.0, 0.0])
        else:
            out.append([round(u, 8), round(v, 8)])
    return out


def decode_float_layer(
    src: Any,
    data: bytes,
    base: int,
    element_size: int,
    offset: int,
    vertex_count: int,
    flip_v: bool,
) -> list[list[float]]:
    out: list[list[float]] = []
    for vertex_index in range(vertex_count):
        off = base + vertex_index * element_size + offset
        u = safe_float(src, data, off)
        v = finish_v(safe_float(src, data, off + 4), flip_v)
        if not math.isfinite(u) or not math.isfinite(v):
            out.append([0.0, 0.0])
        else:
            out.append([round(u, 8), round(v, 8)])
    return out


def uv_stats(uvs: list[list[float]], vertex_count: int) -> dict[str, Any]:
    finite = [(u, v) for u, v in uvs if math.isfinite(u) and math.isfinite(v)]
    if not finite:
        return {
            "finite": 0,
            "unique_rounded": 0,
            "score": -9999.0,
        }
    us = [u for u, _ in finite]
    vs = [v for _, v in finite]
    unique = len({(round(u, 4), round(v, 4)) for u, v in finite})
    span_u = max(us) - min(us)
    span_v = max(vs) - min(vs)
    reasonable = sum(1 for u, v in finite if abs(u) <= 64.0 and abs(v) <= 64.0) / max(1, len(finite))
    unitish = sum(1 for u, v in finite if -0.25 <= u <= 1.25 and -0.25 <= v <= 1.25) / max(1, len(finite))
    zeroish = sum(1 for u, v in finite if abs(u) < 0.00001 and abs(v) < 0.00001) / max(1, len(finite))
    finite_ratio = len(finite) / max(1, vertex_count)
    unique_ratio = unique / max(1, vertex_count)
    span_score = min(2.0, max(0.0, span_u)) + min(2.0, max(0.0, span_v))
    score = (
        finite_ratio * 30.0
        + unique_ratio * 55.0
        + span_score * 10.0
        + reasonable * 15.0
        + unitish * 4.0
        - zeroish * 18.0
    )
    if unique < 4 or span_u < 0.0001 or span_v < 0.0001:
        score -= 50.0
    if reasonable < 0.98:
        score -= 35.0
    return {
        "finite": len(finite),
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
        "score": round(score, 6),
        "sample": [[round(u, 8), round(v, 8)] for u, v in finite[:8]],
    }


def candidate_specs(element_size: int) -> list[dict[str, Any]]:
    if element_size == 16:
        return [{"name": "UV_Half_Offset8", "encoding": "half", "offset": 8, "policy": "compact_static_vertex_render_uv"}]
    if element_size == 20:
        return [
            {"name": "UV_Half_Offset4", "encoding": "half", "offset": 4, "policy": "material_diffuse_tiled_render_uv"},
            {"name": "UV_Half_Offset8", "encoding": "half", "offset": 8, "policy": "secondary_lightmap_style_uv"},
        ]
    if element_size == 24:
        return [
            {"name": "UV_Half_Offset0", "encoding": "half", "offset": 0, "policy": "alternate_packed_candidate"},
            {"name": "UV_Half_Offset4", "encoding": "half", "offset": 4, "policy": "alternate_packed_candidate"},
            {"name": "UV_Half_Offset8", "encoding": "half", "offset": 8, "policy": "alternate_packed_candidate"},
        ]
    if element_size == 28:
        return [
            {"name": "UV_Float_Offset0", "encoding": "float", "offset": 0, "policy": "full_precision_render_uv"},
            {"name": "UV_Float_Offset4_Diagnostic", "encoding": "float", "offset": 4, "policy": "diagnostic_overlap_candidate"},
            {"name": "UV_Half_Offset4_Diagnostic", "encoding": "half", "offset": 4, "policy": "diagnostic_half_candidate"},
        ]
    specs: list[dict[str, Any]] = []
    for offset in range(0, max(0, element_size - 3), 4):
        specs.append({"name": f"UV_Half_Offset{offset}", "encoding": "half", "offset": offset, "policy": "fallback_scan"})
    for offset in range(0, max(0, element_size - 7), 4):
        specs.append({"name": f"UV_Float_Offset{offset}", "encoding": "float", "offset": offset, "policy": "fallback_scan"})
    return specs


def select_render_candidate(element_size: int, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_name = {candidate["name"]: candidate for candidate in candidates}
    if element_size == 16:
        return by_name.get("UV_Half_Offset8")
    if element_size == 20:
        return by_name.get("UV_Half_Offset4")
    if element_size == 28:
        return by_name.get("UV_Float_Offset0")
    plausible = [
        candidate
        for candidate in candidates
        if candidate["stats"].get("finite_ratio", 0.0) >= 0.95
        and candidate["stats"].get("unique_rounded", 0) >= 4
        and candidate["stats"].get("reasonable_abs64_ratio", 0.0) >= 0.98
    ]
    if not plausible:
        plausible = candidates
    if not plausible:
        return None
    return max(
        plausible,
        key=lambda candidate: (
            float(candidate["stats"].get("score", -9999.0)),
            int(candidate["stats"].get("unique_rounded", 0)),
            -int(candidate["offset"]),
        ),
    )


def decode_candidate(
    src: Any,
    data: bytes,
    base: int,
    element_size: int,
    spec: dict[str, Any],
    vertex_count: int,
    flip_v: bool,
) -> dict[str, Any] | None:
    offset = int(spec["offset"])
    encoding = str(spec["encoding"])
    if encoding == "half":
        if offset + 4 > element_size:
            return None
        uvs = decode_half_layer(src, data, base, element_size, offset, vertex_count, flip_v)
    elif encoding == "float":
        if offset + 8 > element_size:
            return None
        uvs = decode_float_layer(src, data, base, element_size, offset, vertex_count, flip_v)
    else:
        return None
    stats = uv_stats(uvs, vertex_count)
    return {
        "name": spec["name"],
        "encoding": encoding,
        "offset": offset,
        "policy": spec.get("policy", ""),
        "stats": stats,
        "uvs": uvs,
    }


def decode_asset(
    src: Any,
    map_dir: Path,
    row: dict[str, str],
    package_cache: dict[str, bytes],
    flip_v: bool,
) -> dict[str, Any] | None:
    if row.get("extract_status") != "bulk_position_index":
        return None
    vertex_count = int(row.get("vertex_count") or 0)
    if vertex_count <= 0:
        return None
    geom = src.parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    static_count = int(static_vertex.get("count") or 0)
    data_rel = int(static_vertex.get("data_rel") or 0)
    if element_size <= 0 or static_count < vertex_count:
        return None
    serial_offset = int(row["serial_offset"])
    static_base = serial_offset + data_rel
    data = src.package_virtual_bytes(map_dir, row["package"], package_cache)

    candidates: list[dict[str, Any]] = []
    for spec in candidate_specs(element_size):
        decoded = decode_candidate(src, data, static_base, element_size, spec, vertex_count, flip_v)
        if decoded is not None:
            candidates.append(decoded)
    render_candidate = select_render_candidate(element_size, candidates)
    if render_candidate is None:
        return None
    candidate_stats = {
        candidate["name"]: {
            "encoding": candidate["encoding"],
            "offset": candidate["offset"],
            "policy": candidate["policy"],
            "stats": candidate["stats"],
        }
        for candidate in candidates
    }
    return {
        "full_path": row["full_path"],
        "object_name": row.get("object_name", ""),
        "package": row["package"],
        "export_index": int(row.get("export_index") or 0),
        "vertex_count": vertex_count,
        "index_count": int(row.get("index_count") or 0),
        "static_vertex_element_size": element_size,
        "static_vertex_count": static_count,
        "static_vertex_data_rel": data_rel,
        "render_uv_layer": RENDER_UV_LAYER,
        "render_source_name": render_candidate["name"],
        "render_source_encoding": render_candidate["encoding"],
        "render_source_offset": render_candidate["offset"],
        "render_source_policy": render_candidate["policy"],
        "render_uv_stats": render_candidate["stats"],
        "candidate_stats": candidate_stats,
        "render_uvs": render_candidate["uvs"],
    }


def main() -> int:
    args = parse_args()
    src = load_source()
    scene_manifest = read_json(Path(args.scene_manifest))
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path", "")).lower(): row for row in clean_rows}
    wanted_paths = [
        str(asset.get("full_path", ""))
        for asset in scene_manifest.get("assets", [])
        if asset.get("full_path")
    ]
    package_cache: dict[str, bytes] = {}
    assets: dict[str, Any] = {}
    skipped: Counter[str] = Counter()
    stride_counts: Counter[int] = Counter()
    render_policy_counts: Counter[str] = Counter()
    missing_clean_rows: list[str] = []

    for full_path in wanted_paths:
        row = clean_by_path.get(full_path.lower())
        if not row:
            missing_clean_rows.append(full_path)
            continue
        decoded = decode_asset(src, Path(args.map_dir), row, package_cache, bool(scene_manifest.get("flip_v", True)))
        if decoded is None:
            skipped[str(row.get("extract_status") or "unsupported")] += 1
            continue
        assets[full_path.lower()] = decoded
        stride_counts[int(decoded["static_vertex_element_size"])] += 1
        render_policy_counts[
            f"{decoded['static_vertex_element_size']}:{decoded['render_source_name']}"
        ] += 1

    target_audit: dict[str, Any] = {}
    for name in args.target_names:
        decoded = assets.get(name.lower())
        if not decoded:
            target_audit[name] = {"found": False}
            continue
        target_audit[name] = {
            "found": True,
            "vertex_count": decoded["vertex_count"],
            "static_vertex_element_size": decoded["static_vertex_element_size"],
            "render_source_name": decoded["render_source_name"],
            "render_source_encoding": decoded["render_source_encoding"],
            "render_source_offset": decoded["render_source_offset"],
            "render_uv_stats": decoded["render_uv_stats"],
            "candidate_stats": decoded["candidate_stats"],
        }

    proof = {
        "target": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "source_scope": scene_manifest.get("source_scope", ""),
        "map_dir": str(Path(args.map_dir)),
        "clean_csv": str(Path(args.clean_csv)),
        "scene_manifest": str(Path(args.scene_manifest)),
        "blend_path": scene_manifest.get("blend_path", ""),
        "render_uv_layer": RENDER_UV_LAYER,
        "policy": {
            "stride_16": "half-float UV at offset 8; old offset 0 was compact-buffer noise",
            "stride_20": "half-float UV at offset 4 for material/tiled render UV; offset 8 retained as secondary evidence",
            "stride_24": "score half-float offsets 0/4/8 and choose the strongest render stream per asset",
            "stride_28": "float32 UV at offset 0; half-float interpretation is diagnostic only",
            "material_side": "Blender pass copies chosen stream into UV_Source_Render so shared materials have one stable input name",
        },
        "summary": {
            "scene_assets": len(wanted_paths),
            "decoded_assets": len(assets),
            "missing_clean_rows": len(missing_clean_rows),
            "skipped_by_status": dict(skipped),
            "decoded_stride_counts": dict(sorted(stride_counts.items())),
            "render_policy_counts": dict(sorted(render_policy_counts.items())),
            "packages_read": sorted(package_cache),
        },
        "target_audit": target_audit,
        "assets": assets,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    printable = {key: value for key, value in proof.items() if key != "assets"}
    print(json.dumps(printable, indent=2, ensure_ascii=True))
    return 0 if assets else 1


if __name__ == "__main__":
    raise SystemExit(main())
