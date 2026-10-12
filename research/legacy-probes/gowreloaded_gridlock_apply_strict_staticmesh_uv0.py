#!/usr/bin/env python3
"""OBSOLETE: old strict UE3 StaticMesh UV0 layout pass for MP_Gridlock.

Earlier Gridlock passes scored raw half/float pairs and sometimes chose byte
offset 4 in 20-byte StaticMesh vertex records. This pass later proved unsafe:
Gridlock's clean `static_vertex_buffer.data_rel` can point at UE3 UV stream
metadata/header, not the vertex payload.

Do not use this for current Reloaded exports. Use
`gowreloaded_gridlock_apply_repo_uvstream_payload.py` or the patched shared
Reloaded exporter instead.
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
STRICT_UV = "UV0_Source_UE3StaticVertex"

TARGET_OBJECT_NAMES = [
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "SDStitchingProxy_2409_StaticMesh__27021",
    "SDStitchingProxy_2755_StaticMesh__27221",
    "SDStitchingProxy_2661_StaticMesh__27170",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--decompressed-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--allow-obsolete-uv-heuristic", action="store_true")
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


def finish_v(v: float, flip_v: bool = True) -> float:
    return float(1.0 - v if flip_v and math.isfinite(v) else v)


def package_bytes(package_dir: Path, package_name: str, cache: dict[str, bytes]) -> bytes:
    key = package_name.lower()
    if key in cache:
        return cache[key]
    stem = Path(package_name).stem
    suffix = Path(package_name).suffix or ".war"
    candidates = [
        package_dir / package_name,
        package_dir / f"{stem}.decompressed{suffix}",
        package_dir / f"{stem}.decompressed.war",
    ]
    for candidate in candidates:
        if candidate.exists():
            cache[key] = candidate.read_bytes()
            return cache[key]
    raise FileNotFoundError(f"no decompressed package for {package_name} under {package_dir}")


def strict_uv_spec(element_size: int) -> dict[str, Any] | None:
    if element_size in {16, 20, 24}:
        return {
            "encoding": "half",
            "offset": 8,
            "rule": "UE3 packed static vertex: tangentX@0 tangentZ@4 UV0@8",
        }
    if element_size == 28:
        return {
            "encoding": "float",
            "offset": 4,
            "rule": "Reloaded high-precision static vertex candidate retained from source probe: float UV0@4",
        }
    return None


def read_uv(data: bytes, base: int, element_size: int, offset: int, vertex_index: int, encoding: str) -> tuple[float, float] | None:
    off = base + vertex_index * element_size + offset
    try:
        if encoding == "half":
            if off + 4 > len(data):
                return None
            u = f16(data, off)
            v = finish_v(f16(data, off + 2))
        elif encoding == "float":
            if off + 8 > len(data):
                return None
            u = f32(data, off)
            v = finish_v(f32(data, off + 4))
        else:
            return None
    except Exception:
        return None
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (u, v)


def object_asset_key(obj: bpy.types.Object) -> str:
    path = str(obj.get("ue_static_mesh_path", "")).strip()
    if path:
        return path.lower()
    if obj.type == "MESH":
        return str(obj.data.get("ue_full_path", "")).strip().lower()
    return ""


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> None:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == layer_name:
            mesh.uv_layers.active_index = index
            break
    try:
        layer.active_render = True
    except Exception:
        pass


def uv_stats(values: list[tuple[float, float]]) -> dict[str, Any]:
    if not values:
        return {"valid": 0}
    us = [value[0] for value in values]
    vs = [value[1] for value in values]
    unique = len({(round(u, 4), round(v, 4)) for u, v in values})
    return {
        "valid": len(values),
        "unique_rounded": unique,
        "u_min": round(min(us), 8),
        "u_max": round(max(us), 8),
        "v_min": round(min(vs), 8),
        "v_max": round(max(vs), 8),
        "span_u": round(max(us) - min(us), 8),
        "span_v": round(max(vs) - min(vs), 8),
        "unitish_ratio": round(sum(1 for u, v in values if -0.25 <= u <= 1.25 and -0.25 <= v <= 1.25) / max(1, len(values)), 6),
        "sample": [[round(u, 8), round(v, 8)] for u, v in values[:8]],
    }


def apply_row_uv_to_object(
    obj: bpy.types.Object,
    row: dict[str, str],
    package_dir: Path,
    package_cache: dict[str, bytes],
) -> dict[str, Any]:
    mesh = obj.data
    geom = parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    static_count = int(static_vertex.get("count") or 0)
    data_rel = int(static_vertex.get("data_rel") or 0)
    serial_offset = int(row.get("serial_offset") or 0)
    spec = strict_uv_spec(element_size)
    if spec is None:
        return {"object": obj.name, "status": "unsupported_static_vertex_stride", "element_size": element_size}
    offset = int(spec["offset"])
    encoding = str(spec["encoding"])
    if encoding == "half" and offset + 4 > element_size:
        return {"object": obj.name, "status": "strict_half_offset_out_of_range", "element_size": element_size, "offset": offset}
    if encoding == "float" and offset + 8 > element_size:
        return {"object": obj.name, "status": "strict_float_offset_out_of_range", "element_size": element_size, "offset": offset}

    data = package_bytes(package_dir, row["package"], package_cache)
    static_base = serial_offset + data_rel
    strict_layer = mesh.uv_layers.get(STRICT_UV)
    if strict_layer is None:
        strict_layer = mesh.uv_layers.new(name=STRICT_UV)
    render_layer = mesh.uv_layers.get(RENDER_UV)
    if render_layer is None:
        render_layer = mesh.uv_layers.new(name=RENDER_UV)

    values: list[tuple[float, float]] = []
    loops_written = 0
    skipped_loops = 0
    fallback_loops = 0
    for loop in mesh.loops:
        vertex_index = int(loop.vertex_index)
        static_index = vertex_index
        if static_index >= static_count:
            skipped_loops += 1
            continue
        uv = read_uv(data, static_base, element_size, offset, static_index, encoding)
        if uv is None:
            skipped_loops += 1
            continue
        strict_layer.data[loop.index].uv = uv
        render_layer.data[loop.index].uv = uv
        values.append(uv)
        loops_written += 1

    previous = {
        "source_name": mesh.get("gridlock_render_uv_source_name", ""),
        "source_encoding": mesh.get("gridlock_render_uv_source_encoding", ""),
        "source_offset": mesh.get("gridlock_render_uv_source_offset", ""),
        "indexed_domain_v2": mesh.get("gridlock_indexed_uv_domain_v2", ""),
        "normalization_source": mesh.get("gridlock_render_uv_source_layer", ""),
    }
    set_active_uv(mesh, RENDER_UV)
    mesh["gridlock_render_uv_layer"] = RENDER_UV
    mesh["gridlock_render_uv_source_name"] = STRICT_UV
    mesh["gridlock_render_uv_source_encoding"] = encoding
    mesh["gridlock_render_uv_source_offset"] = offset
    mesh["gridlock_strict_staticmesh_uv0"] = json.dumps(
        {
            "encoding": encoding,
            "offset": offset,
            "rule": spec["rule"],
            "previous": previous,
        },
        ensure_ascii=True,
    )
    obj["gridlock_render_uv_layer"] = RENDER_UV
    obj["gridlock_render_uv_source_name"] = STRICT_UV
    obj["gridlock_render_uv_source_offset"] = offset
    mesh.update(calc_edges=False)
    return {
        "object": obj.name,
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
        "mesh": mesh.name,
        "status": "updated",
        "element_size": element_size,
        "encoding": encoding,
        "offset": offset,
        "rule": spec["rule"],
        "loops_written": loops_written,
        "fallback_loops": fallback_loops,
        "skipped_loops": skipped_loops,
        "previous": previous,
        "uv_stats": uv_stats(values),
    }


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]


def relink_material(material: bpy.types.Material | None) -> int:
    if material is None or not material.use_nodes or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    imgs = image_nodes(material)
    if not imgs:
        return 0
    uv = nodes.get("Gridlock_Strict_StaticMesh_UV0")
    if uv is None:
        uv = nodes.new("ShaderNodeUVMap")
        uv.name = "Gridlock_Strict_StaticMesh_UV0"
        uv.label = RENDER_UV
        uv.location = (-940, 140)
    uv.uv_map = RENDER_UV
    output = uv.outputs.get("UV")
    if output is None:
        return 0
    linked = 0
    for image in imgs:
        vector = image.inputs.get("Vector")
        if vector is None:
            continue
        for existing in list(vector.links):
            links.remove(existing)
        links.new(output, vector)
        linked += 1
    material["texture_coordinate_uv_map"] = RENDER_UV
    material["gridlock_strict_staticmesh_uv0_material_relink"] = "image nodes linked to UV_Source_Render rebuilt from UE3 StaticMesh UV0 layout"
    return linked


def object_audit(name: str) -> dict[str, Any]:
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"object": name, "exists": False}
    entry: dict[str, Any] = {
        "object": obj.name,
        "exists": True,
        "type": obj.type,
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
    }
    if obj.type == "MESH":
        mesh = obj.data
        entry.update(
            {
                "mesh": mesh.name,
                "uv_layers": [layer.name for layer in mesh.uv_layers],
                "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
                "source_name": mesh.get("gridlock_render_uv_source_name", ""),
                "source_offset": mesh.get("gridlock_render_uv_source_offset", ""),
                "strict_staticmesh_uv0": mesh.get("gridlock_strict_staticmesh_uv0", ""),
                "materials": [slot.material.name for slot in obj.material_slots if slot.material],
            }
        )
    return entry


def main() -> int:
    args = parse_args()
    if not args.allow_obsolete_uv_heuristic:
        raise SystemExit(
            "Refusing to run obsolete strict UV heuristic. Use "
            "gowreloaded_gridlock_apply_repo_uvstream_payload.py or pass "
            "--allow-obsolete-uv-heuristic only for historical comparison."
        )
    rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path", "")).lower(): row for row in rows}
    package_cache: dict[str, bytes] = {}
    package_dir = Path(args.decompressed_dir)

    results: list[dict[str, Any]] = []
    skipped = Counter()
    updated_mesh_names: set[str] = set()
    touched_materials: set[bpy.types.Material] = set()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        key = object_asset_key(obj)
        if not key:
            skipped["missing_staticmesh_key"] += 1
            continue
        row = clean_by_path.get(key)
        if row is None:
            skipped["missing_clean_row"] += 1
            continue
        if row.get("extract_status") != "bulk_position_index":
            skipped[f"extract_status:{row.get('extract_status') or 'unknown'}"] += 1
            continue
        result = apply_row_uv_to_object(obj, row, package_dir, package_cache)
        if result["status"] != "updated":
            skipped[result["status"]] += 1
            if len(results) < 150:
                results.append(result)
            continue
        results.append(result)
        updated_mesh_names.add(obj.data.name)
        for slot in obj.material_slots:
            if slot.material is not None:
                touched_materials.add(slot.material)

    relinked_nodes = 0
    relinked_materials = 0
    for material in touched_materials:
        count = relink_material(material)
        if count:
            relinked_materials += 1
            relinked_nodes += count

    offsets = Counter(f"{row.get('encoding')}@{row.get('offset')}" for row in results if row.get("status") == "updated")
    element_sizes = Counter(str(row.get("element_size")) for row in results if row.get("status") == "updated")
    proof = {
        "blend_path": bpy.data.filepath,
        "clean_csv": str(Path(args.clean_csv)),
        "decompressed_dir": str(package_dir),
        "policy": "Strict source-native UE3 StaticMesh UV0: packed tangent bytes are not UVs; 16/20/24-byte packed records use half UV0 at byte 8.",
        "summary": {
            "updated_objects": sum(1 for row in results if row.get("status") == "updated"),
            "updated_mesh_datablocks": len(updated_mesh_names),
            "updated_offsets": dict(sorted(offsets.items())),
            "updated_element_sizes": dict(sorted(element_sizes.items())),
            "relinked_materials": relinked_materials,
            "relinked_image_nodes": relinked_nodes,
            "skipped": dict(sorted(skipped.items())),
            "packages_read": sorted(package_cache),
        },
        "target_audit": {name: object_audit(name) for name in TARGET_OBJECT_NAMES},
        "updated_samples": results[:180],
        "status": "gridlock_strict_staticmesh_uv0_applied",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_strict_staticmesh_uv0"] = proof["status"]
    bpy.context.scene["gridlock_strict_staticmesh_uv0_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
