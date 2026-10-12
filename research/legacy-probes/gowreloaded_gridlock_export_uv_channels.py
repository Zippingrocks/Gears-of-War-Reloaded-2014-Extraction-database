#!/usr/bin/env python3
"""Export source-native Gridlock StaticMesh UV channels for Blender repair.

Runs outside Blender with the bundled Codex Python. It reuses the Reloaded
native package virtual-byte path, then emits the UV channels that the current
Gridlock blend needs for material-coordinate repair.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_prepare_textured_blend_export.py"
)

TARGET_NAMES = [
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2409_StaticMesh",
    "Delta_Gridlock_01.BSP.bsp_gridlock_road_b_SMesh",
    "COG_City_Ephyra2.COG_City_Ephyra2_1post_Smesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2377_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2378_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2381_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2755_StaticMesh",
    "COG_City_Architecture.COG_UndentedCar1_Frame_SMesh_DR",
    "Neutral_Vehicles.MS_Neutral_Sedan_SMesh",
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


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def uv_stats(uvs: list[list[float]]) -> dict[str, Any]:
    finite = [(u, v) for u, v in uvs if math.isfinite(u) and math.isfinite(v)]
    if not finite:
        return {"finite": 0}
    us = [u for u, _ in finite]
    vs = [v for _, v in finite]
    return {
        "finite": len(finite),
        "unique_rounded": len({(round(u, 4), round(v, 4)) for u, v in finite}),
        "u_min": round(min(us), 8),
        "u_max": round(max(us), 8),
        "v_min": round(min(vs), 8),
        "v_max": round(max(vs), 8),
        "sample": [[round(u, 8), round(v, 8)] for u, v in finite[:8]],
    }


def decode_uv_layer(
    src: Any,
    virt: bytes,
    static_base: int,
    element_size: int,
    offset: int,
    vertex_count: int,
    flip_v: bool,
) -> list[list[float]]:
    out: list[list[float]] = []
    for vertex_index in range(vertex_count):
        u, v = src.read_uv(virt, static_base, element_size, offset, vertex_index, flip_v)
        out.append([round(float(u), 8), round(float(v), 8)])
    return out


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
    virt = src.package_virtual_bytes(map_dir, row["package"], package_cache)

    layer_specs: list[tuple[str, int, str]] = []
    if element_size >= 20:
        layer_specs.append(("UV0_Source_Offset4", 4, "decoded diffuse/world/static vertex UV stream"))
        layer_specs.append(("UV1_Source_Offset8", 8, "decoded secondary packed/lightmap-style UV stream"))
    elif element_size >= 16:
        layer_specs.append(("UV0_Source_Offset0", 0, "decoded compact static vertex UV stream"))

    layers: dict[str, Any] = {}
    for name, offset, meaning in layer_specs:
        if offset + 4 > element_size:
            continue
        uvs = decode_uv_layer(src, virt, static_base, element_size, offset, vertex_count, flip_v)
        layers[name] = {
            "offset": offset,
            "meaning": meaning,
            "uvs": uvs,
            "stats": uv_stats(uvs),
        }

    if not layers:
        return None
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
        "recommended_diffuse_uv": "UV0_Source_Offset4" if "UV0_Source_Offset4" in layers else next(iter(layers)),
        "recommended_secondary_uv": "UV1_Source_Offset8" if "UV1_Source_Offset8" in layers else "",
        "layers": layers,
    }


def main() -> int:
    args = parse_args()
    src = load_source()
    scene_manifest = read_json(Path(args.scene_manifest))
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path", "")).lower(): row for row in clean_rows}
    wanted_paths = [str(asset.get("full_path", "")) for asset in scene_manifest.get("assets", []) if asset.get("full_path")]
    package_cache: dict[str, bytes] = {}
    assets: dict[str, Any] = {}
    missing_clean_rows: list[str] = []
    skipped: Counter[str] = Counter()

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

    target_audit = {}
    for name in args.target_names:
        decoded = assets.get(name.lower())
        if decoded:
            target_audit[name] = {
                "found": True,
                "vertex_count": decoded["vertex_count"],
                "static_vertex_element_size": decoded["static_vertex_element_size"],
                "layers": {
                    layer_name: {
                        "offset": layer["offset"],
                        "stats": layer["stats"],
                    }
                    for layer_name, layer in decoded["layers"].items()
                },
            }
        else:
            target_audit[name] = {"found": False}

    proof = {
        "target": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "source_scope": scene_manifest.get("source_scope", ""),
        "map_dir": str(Path(args.map_dir)),
        "clean_csv": str(Path(args.clean_csv)),
        "scene_manifest": str(Path(args.scene_manifest)),
        "blend_path": scene_manifest.get("blend_path", ""),
        "layer_policy": {
            "element_size_20": {
                "UV0_Source_Offset4": "source-native diffuse/world static UV stream retained as active render UV",
                "UV1_Source_Offset8": "source-native secondary packed/lightmap-style stream added for materials that need it",
            },
            "element_size_16": {
                "UV0_Source_Offset0": "source-native compact static UV stream",
            },
        },
        "summary": {
            "scene_assets": len(wanted_paths),
            "decoded_assets": len(assets),
            "missing_clean_rows": len(missing_clean_rows),
            "skipped_by_status": dict(skipped),
            "packages_read": sorted(package_cache),
        },
        "target_audit": target_audit,
        "assets": assets,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in proof.items() if k != "assets"}, indent=2, ensure_ascii=True))
    return 0 if assets else 1


if __name__ == "__main__":
    raise SystemExit(main())
