#!/usr/bin/env python3
"""Normalize visible Gridlock staticmesh UV routing to UV_Source_Render.

Most decoded StaticMesh instances already have UV_Source_Render. Inline card /
decal style staticmesh exports kept their source card UV names, which is valid
but makes scene-wide material validation ambiguous. This pass copies the active
source UV into UV_Source_Render for every visible staticmesh and routes image
nodes through that layer while preserving material blend/alpha settings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


RENDER_UV = "UV_Source_Render"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def object_is_visible(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    return all(not collection.hide_viewport and not collection.hide_render for collection in obj.users_collection)


def is_visible_staticmesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and object_is_visible(obj) and bool(obj.get("ue_static_mesh_path"))


def choose_source_uv(mesh: bpy.types.Mesh) -> bpy.types.MeshUVLoopLayer | None:
    for name in ("UV_Source_Render", "UV0_Source_InlineCard", "UV0_Source_Offset4", "UV0", "UV1_Source_Offset8"):
        layer = mesh.uv_layers.get(name)
        if layer is not None:
            return layer
    return mesh.uv_layers.active if mesh.uv_layers else None


def set_active_render_uv(mesh: bpy.types.Mesh, layer: bpy.types.MeshUVLoopLayer) -> None:
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == layer.name:
            mesh.uv_layers.active_index = index
            break
    try:
        layer.active_render = True
    except Exception:
        pass


def ensure_render_uv(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    target = mesh.uv_layers.get(RENDER_UV)
    source = choose_source_uv(mesh)
    if source is None:
        return {"object": obj.name, "status": "no_source_uv", "uv_layers": []}
    created = False
    if target is None:
        target = mesh.uv_layers.new(name=RENDER_UV)
        created = True
    count = min(len(target.data), len(source.data))
    for index in range(count):
        target.data[index].uv = source.data[index].uv
    set_active_render_uv(mesh, target)
    mesh["gridlock_render_uv_layer"] = RENDER_UV
    mesh["gridlock_render_uv_source_layer"] = source.name
    obj["gridlock_render_uv_layer"] = RENDER_UV
    obj["gridlock_render_uv_source_layer"] = source.name
    return {
        "object": obj.name,
        "status": "created" if created else "updated",
        "source_uv": source.name,
        "loops_copied": count,
        "uv_layers": [layer.name for layer in mesh.uv_layers],
    }


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]


def ensure_material_uses_render_uv(material: bpy.types.Material | None) -> dict[str, Any]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return {"material": material.name if material else "", "status": "no_node_material", "linked": 0}
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    imgs = image_nodes(material)
    if not imgs:
        return {"material": material.name, "status": "no_image_nodes", "linked": 0}
    uv = nodes.get("Gridlock_Normalized_RenderUV")
    if uv is None:
        uv = nodes.new("ShaderNodeUVMap")
        uv.name = "Gridlock_Normalized_RenderUV"
        uv.label = RENDER_UV
        uv.location = (-900, 80)
    uv.uv_map = RENDER_UV
    output = uv.outputs.get("UV")
    linked = 0
    if output is None:
        return {"material": material.name, "status": "uv_node_no_output", "linked": 0}
    for node in imgs:
        vector_input = node.inputs.get("Vector")
        if vector_input is None:
            continue
        for existing in list(vector_input.links):
            links.remove(existing)
        links.new(output, vector_input)
        linked += 1
    material["texture_coordinate_uv_map"] = RENDER_UV
    material["gridlock_visible_staticmesh_uv_normalization"] = "image nodes linked to UV_Source_Render"
    return {"material": material.name, "status": "linked", "linked": linked}


def main() -> int:
    args = parse_args()
    objects = [obj for obj in bpy.context.scene.objects if is_visible_staticmesh(obj)]
    object_rows: list[dict[str, Any]] = []
    material_rows_by_name: dict[str, dict[str, Any]] = {}
    no_source_uv: list[str] = []
    for obj in objects:
        row = ensure_render_uv(obj)
        object_rows.append(row)
        if row["status"] == "no_source_uv":
            no_source_uv.append(obj.name)
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            if material.name not in material_rows_by_name:
                material_rows_by_name[material.name] = ensure_material_uses_render_uv(material)

    visible_missing_after = [
        obj.name
        for obj in bpy.context.scene.objects
        if is_visible_staticmesh(obj) and obj.data.uv_layers.get(RENDER_UV) is None
    ]
    proof = {
        "blend_path": bpy.data.filepath,
        "policy": "Every visible staticmesh gets UV_Source_Render; existing active/card UVs are copied, not discarded.",
        "visible_staticmesh_objects": len(objects),
        "objects_created_or_updated": sum(1 for row in object_rows if row["status"] in {"created", "updated"}),
        "objects_without_source_uv": len(no_source_uv),
        "objects_without_source_uv_samples": no_source_uv[:80],
        "materials_rerouted": sum(1 for row in material_rows_by_name.values() if row["status"] == "linked"),
        "image_nodes_rerouted": sum(int(row.get("linked") or 0) for row in material_rows_by_name.values()),
        "visible_staticmesh_without_uv_source_render_after": len(visible_missing_after),
        "visible_staticmesh_without_uv_source_render_after_samples": visible_missing_after[:80],
        "object_samples": object_rows[:120],
        "material_samples": list(material_rows_by_name.values())[:120],
        "status": "visible_staticmesh_uv_source_render_normalized",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_visible_staticmesh_uv_normalization"] = proof["status"]
    bpy.context.scene["gridlock_visible_staticmesh_uv_normalization_proof"] = str(out)
    print(json.dumps({key: proof[key] for key in ("visible_staticmesh_objects", "objects_created_or_updated", "objects_without_source_uv", "materials_rerouted", "image_nodes_rerouted", "visible_staticmesh_without_uv_source_render_after", "status")}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if not visible_missing_after else 1


if __name__ == "__main__":
    raise SystemExit(main())
