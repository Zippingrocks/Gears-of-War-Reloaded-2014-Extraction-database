#!/usr/bin/env python3
"""Apply layout-aware Gridlock render UVs and static-mesh material clones."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


RENDER_UV_LAYER = "UV_Source_Render"
MATERIAL_SUFFIX = "__UV_Source_Render"

TARGET_OBJECT_NAMES = [
    "bsp_gridlock_road_b_SMesh__26847",
    "COG_City_Ephyra2_1post_Smesh__26695",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "MS_Neutral_Sedan_SMesh__27672",
    "SDStitchingProxy_2755_StaticMesh__27221",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
    "SDStitchingProxy_2409_StaticMesh__27021",
    "SDStitchingProxy_2661_StaticMesh__27170",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-uv-payload", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def set_active_render_uv(mesh: bpy.types.Mesh, layer_name: str) -> bool:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return False
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == layer_name:
            mesh.uv_layers.active_index = index
            break
    try:
        layer.active_render = True
    except Exception:
        pass
    return True


def apply_uv_layer(mesh: bpy.types.Mesh, layer_name: str, uvs: list[list[float]]) -> dict[str, Any]:
    if len(uvs) < len(mesh.vertices):
        return {
            "status": "skipped_vertex_count_mismatch",
            "mesh_vertices": len(mesh.vertices),
            "uv_vertices": len(uvs),
            "loops_written": 0,
        }
    layer = mesh.uv_layers.get(layer_name)
    created = False
    if layer is None:
        layer = mesh.uv_layers.new(name=layer_name)
        created = True
    loops_written = 0
    for loop in mesh.loops:
        vertex_index = loop.vertex_index
        if 0 <= vertex_index < len(uvs):
            layer.data[loop.index].uv = (float(uvs[vertex_index][0]), float(uvs[vertex_index][1]))
            loops_written += 1
    return {
        "status": "created" if created else "updated",
        "loops_written": loops_written,
    }


def mesh_asset_key(mesh: bpy.types.Mesh) -> str:
    return str(mesh.get("ue_full_path", "")).strip().lower()


def object_asset_key(obj: bpy.types.Object) -> str:
    path = str(obj.get("ue_static_mesh_path", "")).strip()
    if path:
        return path.lower()
    if obj.type == "MESH":
        return mesh_asset_key(obj.data)
    return ""


def apply_render_uv_payload(payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload.get("assets") or {}
    updated_meshes = 0
    skipped_meshes = 0
    mismatch_samples: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    stride_counts: dict[str, int] = {}

    for mesh in bpy.data.meshes:
        key = mesh_asset_key(mesh)
        if not key:
            continue
        asset = assets.get(key)
        if not isinstance(asset, dict):
            skipped_meshes += 1
            continue
        uvs = asset.get("render_uvs")
        if not isinstance(uvs, list):
            skipped_meshes += 1
            continue
        result = apply_uv_layer(mesh, RENDER_UV_LAYER, uvs)
        source_name = str(asset.get("render_source_name") or "")
        if source_name and source_name != RENDER_UV_LAYER:
            apply_uv_layer(mesh, source_name, uvs)
        if result["status"].startswith("skipped"):
            if len(mismatch_samples) < 20:
                mismatch_samples.append(
                    {
                        "mesh": mesh.name,
                        "full_path": mesh.get("ue_full_path", ""),
                        **result,
                    }
                )
            continue
        set_active_render_uv(mesh, RENDER_UV_LAYER)
        mesh["gridlock_render_uv_layer"] = RENDER_UV_LAYER
        mesh["gridlock_render_uv_source_name"] = source_name
        mesh["gridlock_render_uv_source_encoding"] = str(asset.get("render_source_encoding") or "")
        mesh["gridlock_render_uv_source_offset"] = int(asset.get("render_source_offset") or 0)
        mesh["gridlock_render_uv_source_policy"] = str(asset.get("render_source_policy") or "")
        mesh["gridlock_render_uv_breakthrough"] = "layout-aware native StaticMesh UVs copied into a stable render layer"
        mesh.update(calc_edges=False)
        updated_meshes += 1
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
        stride = str(asset.get("static_vertex_element_size") or "")
        stride_counts[stride] = stride_counts.get(stride, 0) + 1

    return {
        "updated_mesh_datablocks": updated_meshes,
        "skipped_mesh_datablocks_without_payload": skipped_meshes,
        "source_counts": dict(sorted(source_counts.items())),
        "stride_counts": dict(sorted(stride_counts.items())),
        "mismatch_samples": mismatch_samples,
    }


def material_has_images(material: bpy.types.Material | None) -> bool:
    if material is None or not material.use_nodes or material.node_tree is None:
        return False
    return any(
        node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)
        for node in material.node_tree.nodes
    )


def is_inline_material(material: bpy.types.Material | None) -> bool:
    if material is None:
        return False
    name = material.name
    return (
        name.startswith("INLINE_PROXY__")
        or name.startswith("INLINE_ASSET_NATIVE__")
        or "inline_proxy_material_repair" in material
        or "inline_asset_material_repair" in material
    )


def relink_material_to_render_uv(material: bpy.types.Material) -> int:
    if not material.use_nodes or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_nodes = [
        node
        for node in nodes
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)
    ]
    if not image_nodes:
        return 0
    uv_node = nodes.get("Source_StaticMesh_RenderUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_RenderUV"
        uv_node.label = "Source StaticMesh Render UV"
        uv_node.location = (-820, -160)
    try:
        uv_node.uv_map = RENDER_UV_LAYER
    except Exception:
        pass
    uv_output = uv_node.outputs.get("UV")
    if uv_output is None:
        return 0
    linked = 0
    for image_node in image_nodes:
        vector_input = image_node.inputs.get("Vector")
        if vector_input is None:
            continue
        for existing in list(vector_input.links):
            links.remove(existing)
        links.new(uv_output, vector_input)
        linked += 1
    material["texture_coordinate_uv_map"] = RENDER_UV_LAYER
    material["gridlock_render_uv_material_clone"] = "texture nodes linked to per-mesh UV_Source_Render"
    return linked


def render_uv_material(original: bpy.types.Material, cache: dict[str, bpy.types.Material]) -> bpy.types.Material:
    if original.name.endswith(MATERIAL_SUFFIX):
        relink_material_to_render_uv(original)
        return original
    cache_key = original.name
    if cache_key in cache:
        return cache[cache_key]
    clone_name = original.name + MATERIAL_SUFFIX
    material = bpy.data.materials.get(clone_name)
    if material is None:
        material = original.copy()
        material.name = clone_name
    material["gridlock_render_uv_clone_source_material"] = original.name
    relink_material_to_render_uv(material)
    cache[cache_key] = material
    return material


def assign_render_uv_materials(payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload.get("assets") or {}
    clone_cache: dict[str, bpy.types.Material] = {}
    assigned_slots = 0
    skipped_inline_slots = 0
    skipped_no_image_slots = 0
    touched_objects = 0
    material_link_count = 0
    object_samples: list[dict[str, Any]] = []

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        key = object_asset_key(obj)
        if key not in assets:
            continue
        if obj.data.uv_layers.get(RENDER_UV_LAYER) is None:
            continue
        object_touched = False
        assigned_names: list[str] = []
        for slot in obj.material_slots:
            original = slot.material
            if original is None:
                continue
            if is_inline_material(original):
                skipped_inline_slots += 1
                continue
            if not material_has_images(original):
                skipped_no_image_slots += 1
                continue
            material = render_uv_material(original, clone_cache)
            before_links = int(material.get("gridlock_render_uv_link_count") or 0)
            linked = relink_material_to_render_uv(material)
            material["gridlock_render_uv_link_count"] = max(before_links, linked)
            material_link_count += linked
            slot.link = "OBJECT"
            slot.material = material
            assigned_slots += 1
            object_touched = True
            assigned_names.append(material.name)
        if object_touched:
            obj["gridlock_render_uv_material_assignment"] = "object material slots assigned to render-UV clones"
            obj["gridlock_render_uv_layer"] = RENDER_UV_LAYER
            touched_objects += 1
            if len(object_samples) < 30:
                object_samples.append(
                    {
                        "object": obj.name,
                        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
                        "materials": assigned_names,
                    }
                )

    return {
        "objects_with_render_uv_materials": touched_objects,
        "assigned_material_slots": assigned_slots,
        "unique_material_clones": len(clone_cache),
        "texture_nodes_linked": material_link_count,
        "skipped_inline_material_slots": skipped_inline_slots,
        "skipped_no_image_slots": skipped_no_image_slots,
        "object_samples": object_samples,
    }


def material_uv_nodes(material: bpy.types.Material | None) -> list[dict[str, str]]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    rows: list[dict[str, str]] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeUVMap":
            rows.append({"name": node.name, "uv_map": str(getattr(node, "uv_map", ""))})
    return rows


def material_image_paths(material: bpy.types.Material | None) -> list[str]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    paths: list[str] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            paths.append(str(Path(bpy.path.abspath(node.image.filepath)).resolve(strict=False)))
    return paths


def target_object_audit() -> dict[str, Any]:
    audit: dict[str, Any] = {}
    for name in TARGET_OBJECT_NAMES:
        obj = bpy.data.objects.get(name)
        if obj is None:
            audit[name] = {"exists": False}
            continue
        mesh = obj.data if obj.type == "MESH" else None
        materials = [slot.material for slot in obj.material_slots if slot.material]
        audit[name] = {
            "exists": True,
            "type": obj.type,
            "static_mesh_path": obj.get("ue_static_mesh_path", ""),
            "mesh_name": mesh.name if mesh else "",
            "uv_layers": [layer.name for layer in mesh.uv_layers] if mesh else [],
            "active_uv": mesh.uv_layers.active.name if mesh and mesh.uv_layers.active else "",
            "gridlock_render_uv_source_name": mesh.get("gridlock_render_uv_source_name", "") if mesh else "",
            "gridlock_render_uv_source_encoding": mesh.get("gridlock_render_uv_source_encoding", "") if mesh else "",
            "gridlock_render_uv_source_offset": mesh.get("gridlock_render_uv_source_offset", "") if mesh else "",
            "materials": [material.name for material in materials],
            "material_uv_nodes": {
                material.name: material_uv_nodes(material)
                for material in materials
            },
            "image_path_count": sum(len(material_image_paths(material)) for material in materials),
        }
    return audit


def visible_render_uv_gap_audit(payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload.get("assets") or {}
    gaps: list[dict[str, Any]] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.hide_viewport or obj.hide_render:
            continue
        key = object_asset_key(obj)
        if key not in assets:
            continue
        if obj.data.uv_layers.get(RENDER_UV_LAYER) is None:
            gaps.append({"object": obj.name, "static_mesh_path": obj.get("ue_static_mesh_path", "")})
    return {
        "visible_payload_staticmesh_objects_missing_render_uv": len(gaps),
        "samples": gaps[:40],
    }


def main() -> int:
    args = parse_args()
    payload_path = Path(args.render_uv_payload)
    proof_out = Path(args.proof_out)
    payload = read_json(payload_path)

    uv_summary = apply_render_uv_payload(payload)
    material_summary = assign_render_uv_materials(payload)
    gap_summary = visible_render_uv_gap_audit(payload)
    proof = {
        "blend_path": bpy.data.filepath,
        "render_uv_payload": str(payload_path),
        "source_scope": payload.get("source_scope", ""),
        "render_uv_layer": RENDER_UV_LAYER,
        "uv_summary": uv_summary,
        "material_summary": material_summary,
        "gap_summary": gap_summary,
        "target_object_audit": target_object_audit(),
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "mesh_datablocks": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
        "status": "gridlock_layout_aware_render_uv_breakthrough_applied",
    }
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_render_uv_breakthrough"] = proof["status"]
    bpy.context.scene["gridlock_render_uv_breakthrough_proof"] = str(proof_out)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if uv_summary["updated_mesh_datablocks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
