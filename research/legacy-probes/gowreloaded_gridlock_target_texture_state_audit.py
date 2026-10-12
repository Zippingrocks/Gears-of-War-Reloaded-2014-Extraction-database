#!/usr/bin/env python3
"""Audit selected Gridlock blend objects for UV layers and material node routing."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore


TARGETS = [
    "Model_6__MP_Gridlock.war__11546",
    "Model_5__MP_Gridlock.war__11545",
    "Model_313__MP_Gridlock.war__11531",
    "Model_27__MP_Gridlock.war__11527",
    "Model_195__MP_Gridlock.war__11514",
    "Model_26__MP_Gridlock.war__11526",
    "Model_14__MP_Gridlock.war__11506",
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2550_StaticMesh__27112",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--targets", nargs="*", default=[])
    return parser.parse_args(passthrough)


def vector_tuple(values: Any) -> list[float]:
    return [float(value) for value in values]


def uv_stats(layer: bpy.types.MeshUVLoopLayer) -> dict[str, Any]:
    values: list[tuple[float, float]] = []
    invalid = 0
    for item in layer.data:
        u = float(item.uv[0])
        v = float(item.uv[1])
        if not math.isfinite(u) or not math.isfinite(v):
            invalid += 1
            continue
        values.append((u, v))
    if not values:
        return {"loops": len(layer.data), "invalid": invalid}
    us = [uv[0] for uv in values]
    vs = [uv[1] for uv in values]
    return {
        "loops": len(layer.data),
        "valid": len(values),
        "invalid": invalid,
        "min": [min(us), min(vs)],
        "max": [max(us), max(vs)],
        "span": [max(us) - min(us), max(vs) - min(vs)],
        "sample": [[round(u, 6), round(v, 6)] for u, v in values[:8]],
    }


def material_images(material: bpy.types.Material | None) -> list[dict[str, str]]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    out: list[dict[str, str]] = []
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        out.append(
            {
                "node": node.name,
                "label": getattr(node, "label", ""),
                "image": image.name if image else "",
                "filepath": str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False)) if image and image.filepath else "",
                "extension": str(getattr(node, "extension", "")),
            }
        )
    return out


def material_uv_nodes(material: bpy.types.Material | None) -> list[dict[str, str]]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    rows: list[dict[str, str]] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeUVMap":
            rows.append({"node": node.name, "label": getattr(node, "label", ""), "uv_map": str(getattr(node, "uv_map", ""))})
    return rows


def image_node_inputs(material: bpy.types.Material | None) -> list[dict[str, str]]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    rows: list[dict[str, str]] = []
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        vector_input = node.inputs.get("Vector")
        linked_from = ""
        if vector_input is not None and vector_input.links:
            link = vector_input.links[0]
            linked_from = f"{link.from_node.name}:{link.from_socket.name}"
        rows.append({"image_node": node.name, "vector_link": linked_from})
    return rows


def material_entry(material: bpy.types.Material | None) -> dict[str, Any]:
    if material is None:
        return {"name": "", "exists": False}
    props = {key: material[key] for key in material.keys()}
    return {
        "name": material.name,
        "exists": True,
        "use_nodes": bool(material.use_nodes),
        "diffuse_color": vector_tuple(material.diffuse_color),
        "images": material_images(material),
        "uv_nodes": material_uv_nodes(material),
        "image_vector_links": image_node_inputs(material),
        "custom_props": props,
    }


def object_entry(name: str) -> dict[str, Any]:
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"object": name, "exists": False}
    entry: dict[str, Any] = {
        "object": obj.name,
        "exists": True,
        "type": obj.type,
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "location": vector_tuple(obj.location),
        "rotation_euler": vector_tuple(obj.rotation_euler),
        "scale": vector_tuple(obj.scale),
        "dimensions": vector_tuple(obj.dimensions),
        "collections": sorted(collection.name for collection in obj.users_collection),
        "custom_props": {key: obj[key] for key in obj.keys()},
    }
    if obj.type != "MESH":
        return entry
    mesh = obj.data
    entry.update(
        {
            "mesh": mesh.name,
            "mesh_custom_props": {key: mesh[key] for key in mesh.keys()},
            "vertices": len(mesh.vertices),
            "loops": len(mesh.loops),
            "polygons": len(mesh.polygons),
            "uv_layers": [layer.name for layer in mesh.uv_layers],
            "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
            "active_render_uv": next((layer.name for layer in mesh.uv_layers if getattr(layer, "active_render", False)), ""),
            "uv_stats": {layer.name: uv_stats(layer) for layer in mesh.uv_layers},
            "polygon_material_indices": dict(Counter(str(poly.material_index) for poly in mesh.polygons)),
            "materials": [material_entry(slot.material) for slot in obj.material_slots],
        }
    )
    return entry


def scene_gap_summary() -> dict[str, Any]:
    visible = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render]
    model_objects = [obj for obj in visible if obj.name.startswith("Model_") and "__MP_Gridlock.war__" in obj.name]
    static_objects = [obj for obj in visible if obj.get("ue_static_mesh_path")]
    no_uv_models = [obj.name for obj in model_objects if not obj.data.uv_layers]
    no_render_uv_static = [obj.name for obj in static_objects if obj.data.uv_layers.get("UV_Source_Render") is None]
    return {
        "visible_mesh_objects": len(visible),
        "visible_direct_bsp_model_objects": len(model_objects),
        "visible_direct_bsp_models_without_uv": len(no_uv_models),
        "visible_direct_bsp_models_without_uv_samples": no_uv_models[:80],
        "visible_staticmesh_objects": len(static_objects),
        "visible_staticmesh_objects_without_uv_source_render": len(no_render_uv_static),
        "visible_staticmesh_objects_without_uv_source_render_samples": no_render_uv_static[:80],
    }


def main() -> int:
    args = parse_args()
    target_names = args.targets or TARGETS
    proof = {
        "blend_path": bpy.data.filepath,
        "targets": {name: object_entry(name) for name in target_names},
        "gap_summary": scene_gap_summary(),
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "mesh_datablocks": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "gap_summary": proof["gap_summary"]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
