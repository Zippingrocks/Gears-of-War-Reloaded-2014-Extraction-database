#!/usr/bin/env python3
"""Populate named UE3 StaticMesh UV channels for Gridlock bulk assets.

The strict UV0 pass fixes tangent bytes being used as UVs, but Unreal materials
can address UV1/UV2. This pass exposes the source channels explicitly as
UV0_Source_UE3, UV1_Source_UE3, etc. It keeps UV_Source_Render pointed at UV0
for now, while making channel switching/auditing concrete instead of hidden.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore


RENDER_UV = "UV_Source_Render"
CHANNEL_PREFIX = "UV"
CHANNEL_SUFFIX = "_Source_UE3"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--decompressed-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_json_field(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def f16(data: bytes, off: int) -> float:
    return float(struct.unpack_from("<e", data, off)[0])


def f32(data: bytes, off: int) -> float:
    return float(struct.unpack_from("<f", data, off)[0])


def finish_v(v: float) -> float:
    return float(1.0 - v if math.isfinite(v) else v)


def package_bytes(package_dir: Path, package_name: str, cache: dict[str, bytes]) -> bytes:
    key = package_name.lower()
    if key in cache:
        return cache[key]
    stem = Path(package_name).stem
    candidates = [
        package_dir / package_name,
        package_dir / f"{stem}.decompressed.war",
    ]
    for candidate in candidates:
        if candidate.exists():
            cache[key] = candidate.read_bytes()
            return cache[key]
    raise FileNotFoundError(f"missing package {package_name}")


def channel_specs(element_size: int) -> list[dict[str, Any]]:
    if element_size in {16, 20, 24}:
        count = max(1, (element_size - 8) // 4)
        return [
            {"channel": channel, "encoding": "half", "offset": 8 + channel * 4}
            for channel in range(count)
        ]
    if element_size == 28:
        # Source probe shows high-precision UVs for this layout at float offsets
        # 4 and 0. Expose both, with the strongest/current UV0 first.
        return [
            {"channel": 0, "encoding": "float", "offset": 4},
            {"channel": 1, "encoding": "float", "offset": 0},
        ]
    return []


def read_uv(data: bytes, base: int, element_size: int, spec: dict[str, Any], vertex_index: int) -> tuple[float, float] | None:
    off = base + vertex_index * element_size + int(spec["offset"])
    try:
        if spec["encoding"] == "half":
            if off + 4 > len(data):
                return None
            u = f16(data, off)
            v = finish_v(f16(data, off + 2))
        else:
            if off + 8 > len(data):
                return None
            u = f32(data, off)
            v = finish_v(f32(data, off + 4))
    except Exception:
        return None
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (u, v)


def uv_stats(values: list[tuple[float, float]]) -> dict[str, Any]:
    if not values:
        return {"valid": 0}
    us = [u for u, _v in values]
    vs = [v for _u, v in values]
    return {
        "valid": len(values),
        "unique_rounded": len({(round(u, 4), round(v, 4)) for u, v in values}),
        "u_min": round(min(us), 8),
        "u_max": round(max(us), 8),
        "v_min": round(min(vs), 8),
        "v_max": round(max(vs), 8),
        "span_u": round(max(us) - min(us), 8),
        "span_v": round(max(vs) - min(vs), 8),
        "unitish_ratio": round(sum(1 for u, v in values if -0.25 <= u <= 1.25 and -0.25 <= v <= 1.25) / len(values), 6),
    }


def object_asset_key(obj: bpy.types.Object) -> str:
    return str(obj.get("ue_static_mesh_path", "") or obj.data.get("ue_full_path", "")).strip().lower()


def apply_channels(obj: bpy.types.Object, row: dict[str, str], package_dir: Path, cache: dict[str, bytes]) -> dict[str, Any]:
    geom = parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    static_count = int(static_vertex.get("count") or 0)
    data_rel = int(static_vertex.get("data_rel") or 0)
    serial_offset = int(row.get("serial_offset") or 0)
    specs = channel_specs(element_size)
    if not specs:
        return {"object": obj.name, "status": "unsupported_stride", "element_size": element_size}
    data = package_bytes(package_dir, row["package"], cache)
    base = serial_offset + data_rel
    mesh = obj.data
    channel_rows: list[dict[str, Any]] = []
    for spec in specs:
        name = f"{CHANNEL_PREFIX}{spec['channel']}{CHANNEL_SUFFIX}"
        layer = mesh.uv_layers.get(name)
        if layer is None:
            mesh.uv_layers.new(name=name)
            layer = mesh.uv_layers.get(name)
        if layer is None:
            channel_rows.append(
                {
                    "name": name,
                    "channel": int(spec["channel"]),
                    "encoding": spec["encoding"],
                    "offset": int(spec["offset"]),
                    "loops_written": 0,
                    "skipped": len(mesh.loops),
                    "stats": {"valid": 0},
                    "status": "uv_layer_create_failed",
                }
            )
            continue
        values: list[tuple[float, float]] = []
        written = 0
        skipped = 0
        for loop in mesh.loops:
            vertex_index = int(loop.vertex_index)
            if vertex_index >= static_count:
                skipped += 1
                continue
            uv = read_uv(data, base, element_size, spec, vertex_index)
            if uv is None:
                skipped += 1
                continue
            layer.data[loop.index].uv = uv
            values.append(uv)
            written += 1
        channel_rows.append(
            {
                "name": name,
                "channel": int(spec["channel"]),
                "encoding": spec["encoding"],
                "offset": int(spec["offset"]),
                "loops_written": written,
                "skipped": skipped,
                "stats": uv_stats(values),
            }
        )
    mesh["gridlock_staticmesh_ue3_uv_channels"] = json.dumps(channel_rows, ensure_ascii=True)
    return {
        "object": obj.name,
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
        "mesh": mesh.name,
        "status": "updated",
        "element_size": element_size,
        "channels": channel_rows,
    }


def main() -> int:
    args = parse_args()
    clean_by_path = {row["full_path"].lower(): row for row in read_csv_rows(Path(args.clean_csv))}
    package_dir = Path(args.decompressed_dir)
    cache: dict[str, bytes] = {}
    rows: list[dict[str, Any]] = []
    skipped = Counter()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        key = object_asset_key(obj)
        row = clean_by_path.get(key)
        if row is None:
            skipped["missing_clean_row"] += 1
            continue
        if row.get("extract_status") != "bulk_position_index":
            skipped[f"extract_status:{row.get('extract_status') or 'unknown'}"] += 1
            continue
        result = apply_channels(obj, row, package_dir, cache)
        if result["status"] != "updated":
            skipped[result["status"]] += 1
        if len(rows) < 220:
            rows.append(result)

    proof = {
        "blend_path": bpy.data.filepath,
        "policy": "Expose UE3 static vertex UV channels from packed record layout for material-coordinate verification.",
        "summary": {
            "updated_objects": sum(1 for row in rows if row.get("status") == "updated"),
            "sampled_rows": len(rows),
            "skipped": dict(sorted(skipped.items())),
            "packages_read": sorted(cache),
        },
        "samples": rows,
        "status": "gridlock_staticmesh_ue3_uv_channels_populated",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_staticmesh_ue3_uv_channels"] = proof["status"]
    bpy.context.scene["gridlock_staticmesh_ue3_uv_channels_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
