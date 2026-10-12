#!/usr/bin/env python3
"""Apply MP_Gridlock render UVs per Blender loop from native index buffers.

Earlier UV passes selected the right StaticMesh UV stream per asset, but wrote
the value by ``loop.vertex_index``. This pass is stricter: for polygon N/corner
M it reads the native triangle index buffer entry that produced that corner in
the exported OBJ and writes the UV for that exact source index. This protects
against Blender-side vertex/index divergence and makes the proof measurable.
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


RENDER_UV_LAYER = "UV_Source_Render"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv-domain-proof", required=True)
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--decompressed-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def f16(data: bytes, off: int) -> float:
    return struct.unpack_from("<e", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


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


def finish_v(v: float, flip_v: bool) -> float:
    return float(1.0 - v if flip_v and math.isfinite(v) else v)


def read_index(data: bytes, off: int, element_size: int) -> int:
    if element_size == 2:
        return int(u16(data, off))
    return int(u32(data, off))


def read_indices(data: bytes, base: int, count: int, element_size: int) -> list[int]:
    values: list[int] = []
    for index in range(count):
        off = base + index * element_size
        if off + element_size > len(data):
            break
        values.append(read_index(data, off, element_size))
    return values


def read_uv(
    data: bytes,
    static_base: int,
    element_size: int,
    offset: int,
    static_index: int,
    encoding: str,
    flip_v: bool,
) -> tuple[float, float] | None:
    off = static_base + static_index * element_size + offset
    if encoding == "half":
        if off + 4 > len(data):
            return None
        u = float(f16(data, off))
        v = finish_v(float(f16(data, off + 2)), flip_v)
    elif encoding == "float":
        if off + 8 > len(data):
            return None
        u = float(f32(data, off))
        v = finish_v(float(f32(data, off + 4)), flip_v)
    else:
        return None
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (u, v)


def mesh_key(mesh: bpy.types.Mesh) -> str:
    key = str(mesh.get("ue_full_path", "")).strip().lower()
    if key:
        return key
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data == mesh:
            key = str(obj.get("ue_static_mesh_path", "")).strip().lower()
            if key:
                return key
    return ""


def valid_ordered_triangles(indices: list[int], vertex_count: int) -> list[tuple[int, int, int]]:
    triangles: list[tuple[int, int, int]] = []
    for tri_index in range(0, len(indices) - 2, 3):
        tri = (indices[tri_index], indices[tri_index + 1], indices[tri_index + 2])
        if any(index < 0 or index >= vertex_count for index in tri):
            continue
        # Matches write_bulk_staticmesh_obj(): ordered = (tri[0], tri[2], tri[1]).
        triangles.append((tri[0], tri[2], tri[1]))
    return triangles


def ensure_render_layer(mesh: bpy.types.Mesh) -> bpy.types.MeshUVLoopLayer:
    layer = mesh.uv_layers.get(RENDER_UV_LAYER)
    if layer is None:
        layer = mesh.uv_layers.new(name=RENDER_UV_LAYER)
    mesh.uv_layers.active = layer
    try:
        layer.active_render = True
    except Exception:
        pass
    return layer


def uv_delta(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(abs(float(a[0]) - float(b[0])), abs(float(a[1]) - float(b[1])))


def apply_mesh(
    mesh: bpy.types.Mesh,
    row: dict[str, str],
    asset_proof: dict[str, Any],
    package_dir: Path,
    package_cache: dict[str, bytes],
    flip_v: bool,
) -> dict[str, Any]:
    geom = parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    index_buffer = geom.get("index_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    static_count = int(static_vertex.get("count") or 0)
    vertex_count = int(row.get("vertex_count") or 0)
    serial_offset = int(row["serial_offset"])
    static_base = serial_offset + int(static_vertex.get("data_rel") or 0)
    index_base = serial_offset + int(index_buffer.get("data_rel") or row.get("index_rel") or 0)
    index_count = int(index_buffer.get("count") or row.get("index_count") or 0)
    index_element_size = int(index_buffer.get("element_size") or geom.get("index_element_size") or 2)
    chosen = asset_proof.get("chosen") or {}
    domain_start = int(chosen.get("domain_start") or 0)
    encoding = str(chosen.get("encoding") or "")
    offset = int(chosen.get("offset") or 0)
    data = package_bytes(package_dir, row["package"], package_cache)
    indices = read_indices(data, index_base, index_count, index_element_size)
    native_tris = valid_ordered_triangles(indices, vertex_count)
    layer = ensure_render_layer(mesh)

    loops_written = 0
    loops_changed = 0
    source_index_mismatches = 0
    skipped_loops = 0
    sample_changes: list[dict[str, Any]] = []
    for poly_index, poly in enumerate(mesh.polygons):
        if poly_index >= len(native_tris):
            skipped_loops += len(poly.loop_indices)
            continue
        native_tri = native_tris[poly_index]
        for corner, loop_index in enumerate(poly.loop_indices):
            if corner >= len(native_tri):
                skipped_loops += 1
                continue
            source_index = native_tri[corner]
            if int(mesh.loops[loop_index].vertex_index) != source_index:
                source_index_mismatches += 1
            static_index = source_index + domain_start
            if static_index >= static_count:
                static_index = source_index
            uv = read_uv(data, static_base, element_size, offset, static_index, encoding, flip_v)
            if uv is None:
                skipped_loops += 1
                continue
            before = (float(layer.data[loop_index].uv.x), float(layer.data[loop_index].uv.y))
            if uv_delta(before, uv) > 1.0e-5:
                loops_changed += 1
                if len(sample_changes) < 8:
                    sample_changes.append(
                        {
                            "poly": poly_index,
                            "corner": corner,
                            "loop": loop_index,
                            "blender_vertex_index": int(mesh.loops[loop_index].vertex_index),
                            "native_source_index": source_index,
                            "before": [round(before[0], 8), round(before[1], 8)],
                            "after": [round(uv[0], 8), round(uv[1], 8)],
                        }
                    )
            layer.data[loop_index].uv = uv
            loops_written += 1

    mesh["gridlock_native_index_loop_uvs"] = json.dumps(
        {
            "source": "native index buffer per polygon corner",
            "domain": chosen.get("domain", ""),
            "domain_start": domain_start,
            "encoding": encoding,
            "offset": offset,
        },
        ensure_ascii=True,
    )
    return {
        "status": "applied",
        "loops_written": loops_written,
        "loops_changed": loops_changed,
        "source_index_mismatches": source_index_mismatches,
        "skipped_loops": skipped_loops,
        "polygon_count": len(mesh.polygons),
        "native_triangle_count": len(native_tris),
        "vertex_count": vertex_count,
        "static_count": static_count,
        "chosen": {
            "domain": chosen.get("domain", ""),
            "domain_start": domain_start,
            "encoding": encoding,
            "offset": offset,
        },
        "sample_changes": sample_changes,
    }


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def relink_material(material: bpy.types.Material | None) -> int:
    if material is None or str(material.name).startswith("INLINE_PROXY__"):
        return 0
    nodes = material.node_tree.nodes if material.use_nodes and material.node_tree else None
    if nodes is None:
        return 0
    imgs = image_nodes(material)
    if not imgs:
        return 0
    links = material.node_tree.links
    uv_node = nodes.get("Source_StaticMesh_NativeIndexLoopUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_NativeIndexLoopUV"
        uv_node.label = "Source StaticMesh Native Index Loop UV"
        uv_node.location = (-980, -280)
    uv_node.uv_map = RENDER_UV_LAYER
    uv_output = uv_node.outputs.get("UV")
    if uv_output is None:
        return 0
    changed = 0
    for node in imgs:
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for link in list(vector.links):
            links.remove(link)
        links.new(uv_output, vector)
        changed += 1
    material["texture_coordinate_uv_map"] = RENDER_UV_LAYER
    material["gridlock_native_index_loop_uv_material_relink"] = "image nodes use UV_Source_Render written per native index-buffer corner"
    return changed


def collect_materials(meshes: set[bpy.types.Mesh]) -> set[bpy.types.Material]:
    mats: set[bpy.types.Material] = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data not in meshes:
            continue
        for slot in obj.material_slots:
            if slot.material is not None:
                mats.add(slot.material)
    return mats


def main() -> int:
    args = parse_args()
    proof = read_json(Path(args.uv_domain_proof))
    assets = proof.get("assets") or {}
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path", "")).lower(): row for row in clean_rows}
    package_dir = Path(args.decompressed_dir)
    package_cache: dict[str, bytes] = {}
    updated: set[bpy.types.Mesh] = set()
    skipped: Counter[str] = Counter()
    offset_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    changed_meshes = 0
    mismatch_meshes = 0
    sample_results: dict[str, Any] = {}

    for mesh in bpy.data.meshes:
        key = mesh_key(mesh)
        if not key:
            skipped["missing_mesh_source_key"] += 1
            continue
        asset = assets.get(key)
        if not isinstance(asset, dict):
            skipped["not_in_uv_domain_proof"] += 1
            continue
        row = clean_by_path.get(key)
        if row is None:
            skipped["missing_clean_row"] += 1
            continue
        if row.get("extract_status") != "bulk_position_index":
            skipped[f"status:{row.get('extract_status')}"] += 1
            continue
        try:
            result = apply_mesh(mesh, row, asset, package_dir, package_cache, True)
        except Exception as exc:
            skipped[f"apply_error:{type(exc).__name__}"] += 1
            if len(sample_results) < 80:
                sample_results[mesh.name] = {"full_path": key, "status": "error", "error": repr(exc)}
            continue
        updated.add(mesh)
        if result["loops_changed"]:
            changed_meshes += 1
        if result["source_index_mismatches"]:
            mismatch_meshes += 1
        chosen = result["chosen"]
        offset_counts[f"{chosen.get('encoding')}@{chosen.get('offset')}"] += 1
        domain_counts[str(chosen.get("domain", ""))] += 1
        if result["loops_changed"] or result["source_index_mismatches"] or len(sample_results) < 80:
            sample_results[mesh.name] = {"full_path": key, **result}

    relinked_materials = 0
    relinked_nodes = 0
    for material in collect_materials(updated):
        count = relink_material(material)
        if count:
            relinked_materials += 1
            relinked_nodes += count

    out_data = {
        "blend_path": bpy.data.filepath,
        "uv_domain_proof": str(Path(args.uv_domain_proof)),
        "clean_csv": str(Path(args.clean_csv)),
        "decompressed_dir": str(package_dir),
        "summary": {
            "updated_mesh_datablocks": len(updated),
            "updated_mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH" and obj.data in updated),
            "changed_mesh_datablocks": changed_meshes,
            "source_index_mismatch_mesh_datablocks": mismatch_meshes,
            "relinked_materials": relinked_materials,
            "relinked_image_nodes": relinked_nodes,
            "chosen_offsets": dict(offset_counts),
            "chosen_domains": dict(domain_counts),
            "skipped": dict(skipped),
            "packages_read": sorted(package_cache),
        },
        "sample_results": sample_results,
        "status": "native_index_loop_uvs_applied",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_data, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_native_index_loop_uvs"] = out_data["status"]
    bpy.context.scene["gridlock_native_index_loop_uvs_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": out_data["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
