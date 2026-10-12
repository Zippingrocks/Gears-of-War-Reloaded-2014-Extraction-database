#!/usr/bin/env python3
"""OBSOLETE/opt-in MP_Gridlock uniform UV payload pass.

This script correctly found that `static_vertex_buffer.data_rel` can sit near
UE3 StaticMesh UV stream metadata/header, but applying one uniform payload
layout to every Gridlock mesh later proved unsafe. Some Reloaded Gridlock
assets require the source-scored mixed indexed UV-domain policy, including
`half@4`, `half@8`, and rare `index_plus_half` domains.

For the current production Gridlock blend use
`gowreloaded_gridlock_apply_indexed_uv_domain_v2.py` with
`gridlock_uv_domain_repo_variant_2026_08_14.json`.

This script now requires `--allow-uniform-payload-uv` so it cannot accidentally
clobber the mixed render UV layer again.
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
LIGHTMAP_UV_LAYER = "UV_Source_Lightmap"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--decompressed-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--allow-uniform-payload-uv", action="store_true")
    return parser.parse_args(passthrough)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_json_field(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


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


def read_index(data: bytes, off: int, element_size: int) -> int:
    return int(u16(data, off)) if element_size == 2 else int(u32(data, off))


def read_indices(data: bytes, base: int, count: int, element_size: int) -> list[int]:
    values: list[int] = []
    for index in range(count):
        off = base + index * element_size
        if off + element_size > len(data):
            break
        values.append(read_index(data, off, element_size))
    return values


def valid_ordered_triangles(indices: list[int], vertex_count: int) -> list[tuple[int, int, int]]:
    triangles: list[tuple[int, int, int]] = []
    for index in range(0, len(indices) - 2, 3):
        tri = (indices[index], indices[index + 1], indices[index + 2])
        if any(value < 0 or value >= vertex_count for value in tri):
            continue
        # Matches the existing OBJ export winding.
        triangles.append((tri[0], tri[2], tri[1]))
    return triangles


def detect_uv_stream(data: bytes, raw_base: int, item_size: int, item_count: int) -> dict[str, Any] | None:
    if item_size <= 0 or item_count <= 0:
        return None

    candidates: list[dict[str, Any]] = []

    # Current clean extract shape: data_rel points at bUseFullPrecisionUVs.
    if raw_base >= 12 and raw_base + 12 <= len(data):
        num_texcoords = i32(data, raw_base - 12)
        meta_item_size = i32(data, raw_base - 8)
        meta_count = i32(data, raw_base - 4)
        full_precision = i32(data, raw_base)
        bulk_item_size = i32(data, raw_base + 4)
        bulk_count = i32(data, raw_base + 8)
        score = 0
        if 1 <= num_texcoords <= 8:
            score += 2
        if meta_item_size == item_size and bulk_item_size == item_size:
            score += 3
        if meta_count == item_count and bulk_count == item_count:
            score += 3
        if full_precision in {0, 1}:
            score += 2
        if score >= 10:
            candidates.append(
                {
                    "layout": "ue3_uvstream_data_rel_at_full_precision_flag",
                    "metadata_abs": raw_base - 12,
                    "payload_abs": raw_base + 12,
                    "num_texcoords": num_texcoords,
                    "item_size": item_size,
                    "item_count": item_count,
                    "use_full_precision_uvs": bool(full_precision),
                    "bulk_item_size": bulk_item_size,
                    "bulk_count": bulk_count,
                    "score": score,
                }
            )

    # Safer fallback: data_rel points at BulkSerialize item size/count.
    if raw_base >= 16 and raw_base + 8 <= len(data):
        bulk_item_size = i32(data, raw_base)
        bulk_count = i32(data, raw_base + 4)
        num_texcoords = i32(data, raw_base - 16)
        meta_item_size = i32(data, raw_base - 12)
        meta_count = i32(data, raw_base - 8)
        full_precision = i32(data, raw_base - 4)
        score = 0
        if 1 <= num_texcoords <= 8:
            score += 2
        if meta_item_size == item_size and bulk_item_size == item_size:
            score += 3
        if meta_count == item_count and bulk_count == item_count:
            score += 3
        if full_precision in {0, 1}:
            score += 2
        if score >= 10:
            candidates.append(
                {
                    "layout": "ue3_uvstream_data_rel_at_bulk_header",
                    "metadata_abs": raw_base - 16,
                    "payload_abs": raw_base + 8,
                    "num_texcoords": num_texcoords,
                    "item_size": item_size,
                    "item_count": item_count,
                    "use_full_precision_uvs": bool(full_precision),
                    "bulk_item_size": bulk_item_size,
                    "bulk_count": bulk_count,
                    "score": score,
                }
            )

    if candidates:
        return max(candidates, key=lambda row: row["score"])

    return {
        "layout": "legacy_data_rel_at_payload_unverified",
        "metadata_abs": "",
        "payload_abs": raw_base,
        "num_texcoords": 1,
        "item_size": item_size,
        "item_count": item_count,
        "use_full_precision_uvs": False,
        "bulk_item_size": "",
        "bulk_count": "",
        "score": 0,
    }


def uv_pair_size(stream: dict[str, Any]) -> int:
    return 8 if stream.get("use_full_precision_uvs") else 4


def uv_offset_for_channel(stream: dict[str, Any], channel: int) -> int | None:
    pair_size = uv_pair_size(stream)
    num_texcoords = int(stream.get("num_texcoords") or 0)
    item_size = int(stream.get("item_size") or 0)
    prefix = item_size - num_texcoords * pair_size
    offset = prefix + channel * pair_size
    if prefix < 0 or channel >= num_texcoords or offset + pair_size > item_size:
        return None
    return offset


def read_uv(data: bytes, stream: dict[str, Any], vertex_index: int, channel: int, flip_v: bool) -> tuple[float, float] | None:
    item_size = int(stream["item_size"])
    if vertex_index < 0 or vertex_index >= int(stream["item_count"]):
        return None
    offset = uv_offset_for_channel(stream, channel)
    if offset is None:
        return None
    off = int(stream["payload_abs"]) + vertex_index * item_size + offset
    if stream.get("use_full_precision_uvs"):
        if off + 8 > len(data):
            return None
        u = float(f32(data, off))
        v = float(f32(data, off + 4))
    else:
        if off + 4 > len(data):
            return None
        u = float(f16(data, off))
        v = float(f16(data, off + 2))
    if not math.isfinite(u) or not math.isfinite(v):
        return None
    return (u, float(1.0 - v if flip_v else v))


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


def ensure_uv_layer(mesh: bpy.types.Mesh, name: str) -> bpy.types.MeshUVLoopLayer:
    layer = mesh.uv_layers.get(name)
    if layer is None:
        layer = mesh.uv_layers.new(name=name)
    mesh.uv_layers.active = layer
    if name == RENDER_UV_LAYER:
        try:
            layer.active_render = True
        except Exception:
            pass
    return layer


def apply_mesh(
    mesh: bpy.types.Mesh,
    row: dict[str, str],
    data: bytes,
    flip_v: bool,
) -> dict[str, Any]:
    geom = parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    index_buffer = geom.get("index_buffer") or {}
    item_size = int(static_vertex.get("element_size") or 0)
    item_count = int(static_vertex.get("count") or 0)
    vertex_count = int(row.get("vertex_count") or 0)
    serial_offset = int(row.get("serial_offset") or 0)
    raw_base = serial_offset + int(static_vertex.get("data_rel") or 0)
    stream = detect_uv_stream(data, raw_base, item_size, item_count)
    if stream is None:
        return {"status": "missing_uv_stream"}

    index_base = serial_offset + int(index_buffer.get("data_rel") or row.get("index_rel") or 0)
    index_count = int(index_buffer.get("count") or row.get("index_count") or 0)
    index_element_size = int(index_buffer.get("element_size") or geom.get("index_element_size") or 2)
    indices = read_indices(data, index_base, index_count, index_element_size)
    native_tris = valid_ordered_triangles(indices, vertex_count)
    render_layer = ensure_uv_layer(mesh, RENDER_UV_LAYER)
    light_layer = ensure_uv_layer(mesh, LIGHTMAP_UV_LAYER) if int(stream.get("num_texcoords") or 0) > 1 else None

    loops_written = 0
    skipped_loops = 0
    render_changed = 0
    sample: list[dict[str, Any]] = []
    for poly_index, poly in enumerate(mesh.polygons):
        native_tri = native_tris[poly_index] if poly_index < len(native_tris) else None
        for corner, loop_index in enumerate(poly.loop_indices):
            source_index = native_tri[corner] if native_tri and corner < len(native_tri) else int(mesh.loops[loop_index].vertex_index)
            uv0 = read_uv(data, stream, source_index, 0, flip_v)
            if uv0 is None:
                skipped_loops += 1
                continue
            before = (float(render_layer.data[loop_index].uv.x), float(render_layer.data[loop_index].uv.y))
            if max(abs(before[0] - uv0[0]), abs(before[1] - uv0[1])) > 1.0e-5:
                render_changed += 1
                if len(sample) < 8:
                    sample.append(
                        {
                            "poly": poly_index,
                            "corner": corner,
                            "source_index": source_index,
                            "before": [round(before[0], 8), round(before[1], 8)],
                            "after": [round(uv0[0], 8), round(uv0[1], 8)],
                        }
                    )
            render_layer.data[loop_index].uv = uv0
            if light_layer is not None:
                uv1 = read_uv(data, stream, source_index, 1, flip_v)
                if uv1 is not None:
                    light_layer.data[loop_index].uv = uv1
            loops_written += 1

    mesh.uv_layers.active = render_layer
    mesh["gridlock_repo_uvstream_payload"] = json.dumps(
        {
            "source": "UE3 StaticMesh UV stream bulk payload",
            "layout": stream.get("layout"),
            "num_texcoords": stream.get("num_texcoords"),
            "item_size": stream.get("item_size"),
            "payload_abs": stream.get("payload_abs"),
            "uv0_offset": uv_offset_for_channel(stream, 0),
            "uv1_offset": uv_offset_for_channel(stream, 1),
        },
        ensure_ascii=True,
    )
    return {
        "status": "applied",
        "layout": stream.get("layout"),
        "num_texcoords": stream.get("num_texcoords"),
        "use_full_precision_uvs": stream.get("use_full_precision_uvs"),
        "item_size": stream.get("item_size"),
        "item_count": stream.get("item_count"),
        "payload_abs": stream.get("payload_abs"),
        "uv0_offset": uv_offset_for_channel(stream, 0),
        "uv1_offset": uv_offset_for_channel(stream, 1),
        "loops_written": loops_written,
        "skipped_loops": skipped_loops,
        "render_changed_loops": render_changed,
        "polygon_count": len(mesh.polygons),
        "native_triangle_count": len(native_tris),
        "sample_changes": sample,
    }


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def relink_material(material: bpy.types.Material | None) -> int:
    if material is None or str(material.name).startswith("INLINE_PROXY__"):
        return 0
    if material.node_tree is None or not material.use_nodes:
        return 0
    nodes = material.node_tree.nodes
    imgs = image_nodes(material)
    if not imgs:
        return 0
    uv_node = nodes.get("Source_StaticMesh_RepoUVStreamPayload")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_RepoUVStreamPayload"
        uv_node.label = "Source StaticMesh Repo UV Stream Payload"
        uv_node.location = (-1040, -360)
    uv_node.uv_map = RENDER_UV_LAYER
    changed = 0
    for node in imgs:
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for link in list(vector.links):
            material.node_tree.links.remove(link)
        material.node_tree.links.new(uv_node.outputs["UV"], vector)
        changed += 1
    material["texture_coordinate_uv_map"] = RENDER_UV_LAYER
    material["gridlock_repo_uvstream_payload_material_relink"] = "image nodes use UV_Source_Render rebuilt from UE3 StaticMesh UV stream payload"
    return changed


def collect_materials(meshes: set[bpy.types.Mesh]) -> set[bpy.types.Material]:
    materials: set[bpy.types.Material] = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data not in meshes:
            continue
        for slot in obj.material_slots:
            if slot.material:
                materials.add(slot.material)
    return materials


def main() -> int:
    args = parse_args()
    if not args.allow_uniform_payload_uv:
        raise SystemExit(
            "Refusing to run obsolete uniform Gridlock UV payload pass. Use "
            "gowreloaded_gridlock_apply_indexed_uv_domain_v2.py with "
            "gridlock_uv_domain_repo_variant_2026_08_14.json, or pass "
            "--allow-uniform-payload-uv only for historical comparison."
        )
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path") or "").lower(): row for row in clean_rows}
    package_dir = Path(args.decompressed_dir)
    package_cache: dict[str, bytes] = {}

    updated_meshes: set[bpy.types.Mesh] = set()
    skipped: Counter[str] = Counter()
    layouts: Counter[str] = Counter()
    changed_meshes = 0
    changed_loops = 0
    samples: dict[str, Any] = {}

    for mesh in bpy.data.meshes:
        key = mesh_key(mesh)
        if not key:
            skipped["missing_mesh_source_key"] += 1
            continue
        row = clean_by_path.get(key)
        if row is None:
            skipped["missing_clean_row"] += 1
            continue
        if row.get("extract_status") != "bulk_position_index":
            skipped[f"status:{row.get('extract_status')}"] += 1
            continue
        try:
            data = package_bytes(package_dir, row["package"], package_cache)
            result = apply_mesh(mesh, row, data, True)
        except Exception as exc:
            skipped[f"apply_error:{type(exc).__name__}"] += 1
            if len(samples) < 80:
                samples[mesh.name] = {"full_path": key, "status": "error", "error": repr(exc)}
            continue
        if result.get("status") != "applied":
            skipped[str(result.get("status"))] += 1
            continue
        updated_meshes.add(mesh)
        layouts[str(result.get("layout"))] += 1
        changed_loops += int(result.get("render_changed_loops") or 0)
        if int(result.get("render_changed_loops") or 0) > 0:
            changed_meshes += 1
        if len(samples) < 120 and (result.get("sample_changes") or key in {
            "neutral_vehicles.ms_neutral_sedan_smesh",
            "delta_gridlock_01.bsp.bsp_gridlock_road_b_smesh",
            "delta_gridlock_01.bsp_gridlock_bld_01_smesh_delta",
            "cog_city_architecture.cog_undentedcar1_frame_smesh_dr",
            "cog_city_architecture_03.cog_city_brokencarchasey1_smesh_dr",
        }):
            samples[mesh.name] = {"full_path": key, **result}

    relinked_materials = 0
    relinked_image_nodes = 0
    for material in collect_materials(updated_meshes):
        changed = relink_material(material)
        if changed:
            relinked_materials += 1
            relinked_image_nodes += changed

    proof = {
        "blend_path": bpy.data.filepath,
        "policy": "Repo-confirmed UE3 StaticMesh UV stream payload decode; clean data_rel is treated as metadata/header when detected, not vertex payload.",
        "repo_evidence": [
            "UEViewer UnMesh3.cpp FStaticMeshUVStream3 reads NumTexCoords, ItemSize, NumVerts, bUseFullPrecisionUVs, then BulkSerialize payload.",
            "CUE4Parse FStaticMeshVertexBuffer/FStaticMeshUVItem serializes tangent/color prefix before texcoords.",
        ],
        "summary": {
            "updated_mesh_datablocks": len(updated_meshes),
            "updated_mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH" and obj.data in updated_meshes),
            "changed_mesh_datablocks": changed_meshes,
            "changed_render_loops": changed_loops,
            "layouts": dict(sorted(layouts.items())),
            "relinked_materials": relinked_materials,
            "relinked_image_nodes": relinked_image_nodes,
            "skipped": dict(sorted(skipped.items())),
            "packages_read": sorted(package_cache.keys()),
        },
        "samples": samples,
    }

    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_repo_uvstream_payload_repair"] = "applied"
    bpy.context.scene["gridlock_repo_uvstream_payload_repair_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
