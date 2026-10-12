#!/usr/bin/env python3
"""Apply indexed source UV domains to the Reloaded MP_Gridlock blend."""

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
TARGET_OBJECT_NAMES = [
    "SDStitchingProxy_2661_StaticMesh__27170",
    "bsp_gridlock_road_b_SMesh__26847",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "SDStitchingProxy_2409_StaticMesh__27021",
    "SDStitchingProxy_2755_StaticMesh__27221",
]


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
    return str(mesh.get("ue_full_path", "")).strip().lower()


def object_key_for_mesh(mesh: bpy.types.Mesh) -> str:
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data == mesh:
            key = str(obj.get("ue_static_mesh_path", "")).strip().lower()
            if key:
                return key
    return ""


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> None:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return
    mesh.uv_layers.active = layer
    try:
        layer.active_render = True
    except Exception:
        pass


def apply_asset_uv(
    mesh: bpy.types.Mesh,
    row: dict[str, str],
    asset_proof: dict[str, Any],
    package_dir: Path,
    package_cache: dict[str, bytes],
    flip_v: bool,
) -> dict[str, Any]:
    geom = parse_json_field(row.get("geometry_json", ""), {})
    static_vertex = geom.get("static_vertex_buffer") or {}
    element_size = int(static_vertex.get("element_size") or 0)
    static_count = int(static_vertex.get("count") or 0)
    static_data_rel = int(static_vertex.get("data_rel") or 0)
    serial_offset = int(row["serial_offset"])
    static_base = serial_offset + static_data_rel

    chosen = asset_proof.get("chosen") or {}
    domain_start = int(chosen.get("domain_start") or 0)
    encoding = str(chosen.get("encoding") or "")
    offset = int(chosen.get("offset") or 0)
    data = package_bytes(package_dir, row["package"], package_cache)

    layer = mesh.uv_layers.get(RENDER_UV_LAYER)
    created = False
    if layer is None:
        layer = mesh.uv_layers.new(name=RENDER_UV_LAYER)
        created = True

    loops_written = 0
    fallback_loops = 0
    skipped_loops = 0
    sample: list[list[float]] = []
    for loop in mesh.loops:
        vertex_index = int(loop.vertex_index)
        static_index = vertex_index + domain_start
        if static_index >= static_count and vertex_index < static_count:
            static_index = vertex_index
            fallback_loops += 1
        uv = read_uv(data, static_base, element_size, offset, static_index, encoding, flip_v)
        if uv is None:
            skipped_loops += 1
            continue
        layer.data[loop.index].uv = uv
        loops_written += 1
        if len(sample) < 6:
            sample.append([round(float(uv[0]), 8), round(float(uv[1]), 8)])

    set_active_uv(mesh, RENDER_UV_LAYER)
    mesh["gridlock_indexed_uv_domain_v2"] = json.dumps(
        {
            "domain": chosen.get("domain", ""),
            "domain_start": domain_start,
            "encoding": encoding,
            "offset": offset,
            "source_proof": "gridlock_indexed_uv_domain_probe_allscene_2026_08_14",
        },
        ensure_ascii=True,
    )
    mesh["gridlock_render_uv_layer"] = RENDER_UV_LAYER
    return {
        "status": "created" if created else "updated",
        "loops_written": loops_written,
        "fallback_loops": fallback_loops,
        "skipped_loops": skipped_loops,
        "sample": sample,
        "chosen": {
            "domain": chosen.get("domain", ""),
            "domain_start": domain_start,
            "encoding": encoding,
            "offset": offset,
        },
    }


def material_image_nodes(material: bpy.types.Material) -> list[bpy.types.Node]:
    if not material or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def relink_material_to_render_uv(material: bpy.types.Material) -> int:
    if not material or str(material.name).startswith("INLINE_PROXY__"):
        return 0
    image_nodes = material_image_nodes(material)
    if not image_nodes or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    uv_node = nodes.get("Source_StaticMesh_RenderUV_v2") or nodes.get("Source_StaticMesh_RenderUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_RenderUV_v2"
        uv_node.label = "Source StaticMesh Render UV v2"
        uv_node.location = (-920, -220)
    try:
        uv_node.uv_map = RENDER_UV_LAYER
    except Exception:
        pass
    uv_output = uv_node.outputs.get("UV")
    if uv_output is None:
        return 0
    relinked = 0
    for image_node in image_nodes:
        vector_input = image_node.inputs.get("Vector")
        if vector_input is None:
            continue
        for existing in list(vector_input.links):
            links.remove(existing)
        links.new(uv_output, vector_input)
        relinked += 1
    material["texture_coordinate_uv_map"] = RENDER_UV_LAYER
    material["gridlock_indexed_uv_domain_v2_material_relink"] = "image nodes use source-indexed UV_Source_Render"
    return relinked


def collect_materials_for_meshes(meshes: set[bpy.types.Mesh]) -> set[bpy.types.Material]:
    materials: set[bpy.types.Material] = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.data not in meshes:
            continue
        for slot in obj.material_slots:
            if slot.material is not None:
                materials.add(slot.material)
    return materials


def object_uv_audit(name: str) -> dict[str, Any]:
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"object": name, "found": False}
    audit: dict[str, Any] = {
        "object": name,
        "found": True,
        "type": obj.type,
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
    }
    if obj.type == "MESH":
        mesh = obj.data
        audit["mesh"] = mesh.name
        audit["mesh_full_path"] = mesh.get("ue_full_path", "")
        audit["uv_layers"] = [layer.name for layer in mesh.uv_layers]
        audit["active_uv"] = mesh.uv_layers.active.name if mesh.uv_layers.active else ""
        audit["active_render_uv"] = next((layer.name for layer in mesh.uv_layers if getattr(layer, "active_render", False)), "")
        audit["indexed_uv_domain_v2"] = mesh.get("gridlock_indexed_uv_domain_v2", "")
        audit["materials"] = [slot.material.name for slot in obj.material_slots if slot.material]
    return audit


def main() -> int:
    args = parse_args()
    uv_domain_proof = read_json(Path(args.uv_domain_proof))
    clean_rows = read_csv_rows(Path(args.clean_csv))
    clean_by_path = {str(row.get("full_path", "")).lower(): row for row in clean_rows}
    assets = uv_domain_proof.get("assets") or {}
    package_dir = Path(args.decompressed_dir)
    package_cache: dict[str, bytes] = {}
    flip_v = True

    updated_meshes: set[bpy.types.Mesh] = set()
    mesh_results: dict[str, Any] = {}
    skipped = Counter()
    chosen_offsets = Counter()
    chosen_domains = Counter()

    for mesh in bpy.data.meshes:
        key = mesh_key(mesh) or object_key_for_mesh(mesh)
        if not key:
            skipped["missing_mesh_source_key"] += 1
            continue
        asset_proof = assets.get(key)
        if not isinstance(asset_proof, dict):
            skipped["not_in_uv_domain_proof"] += 1
            continue
        row = clean_by_path.get(key)
        if row is None:
            skipped["missing_clean_row"] += 1
            continue
        try:
            result = apply_asset_uv(mesh, row, asset_proof, package_dir, package_cache, flip_v)
        except Exception as exc:
            skipped[f"apply_error:{type(exc).__name__}"] += 1
            if len(mesh_results) < 60:
                mesh_results[mesh.name] = {
                    "full_path": key,
                    "status": "error",
                    "error": str(exc),
                }
            continue
        updated_meshes.add(mesh)
        chosen = result.get("chosen", {})
        chosen_offsets[f"{chosen.get('encoding')}@{chosen.get('offset')}"] += 1
        chosen_domains[str(chosen.get("domain") or "")] += 1
        if len(mesh_results) < 120:
            mesh_results[mesh.name] = {"full_path": key, **result}

    materials = collect_materials_for_meshes(updated_meshes)
    relinked_nodes = 0
    relinked_materials = 0
    for material in materials:
        linked = relink_material_to_render_uv(material)
        if linked:
            relinked_materials += 1
            relinked_nodes += linked

    updated_object_count = sum(1 for obj in bpy.data.objects if obj.type == "MESH" and obj.data in updated_meshes)
    proof = {
        "blend_path": bpy.data.filepath,
        "uv_domain_proof": str(Path(args.uv_domain_proof)),
        "clean_csv": str(Path(args.clean_csv)),
        "decompressed_dir": str(package_dir),
        "render_uv_layer": RENDER_UV_LAYER,
        "summary": {
            "updated_mesh_datablocks": len(updated_meshes),
            "updated_mesh_objects": updated_object_count,
            "relinked_materials": relinked_materials,
            "relinked_image_nodes": relinked_nodes,
            "chosen_offsets_on_updated_meshes": dict(chosen_offsets),
            "chosen_domains_on_updated_meshes": dict(chosen_domains),
            "skipped": dict(skipped),
            "packages_read": sorted(package_cache),
        },
        "sample_mesh_results": mesh_results,
        "target_object_audit": {name: object_uv_audit(name) for name in TARGET_OBJECT_NAMES},
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "mesh_datablocks": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }

    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"proof_out": str(proof_out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
