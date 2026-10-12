#!/usr/bin/env python3
"""Replace Gridlock floor puddle unbound material with a named shader approximation."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import bpy  # type: ignore


TARGET_PATH = "Delta_Gridlock_01.MP_Gridlock_floor_puddle_SMesh_VertexColorMesh"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def clear_nodes(nodes: bpy.types.Nodes) -> None:
    for node in list(nodes):
        nodes.remove(node)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def make_puddle_material() -> bpy.types.Material:
    material = bpy.data.materials.get("MAT_MP_Gridlock_Floor_Puddle_VertexColor_Approx")
    if material is None:
        material = bpy.data.materials.new("MAT_MP_Gridlock_Floor_Puddle_VertexColor_Approx")
    material.use_nodes = True
    material.diffuse_color = (0.06, 0.075, 0.07, 0.38)
    material.blend_method = "BLEND"
    material.show_transparent_back = True
    material["ue_static_mesh_path"] = TARGET_PATH
    material["source_material_status"] = "native StaticMesh section material_ref=0 material_path=None; shader is Blender puddle approximation"
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    clear_nodes(nodes)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (330, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (80, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base_input = principled_input(bsdf, ("Base Color",))
    alpha_input = principled_input(bsdf, ("Alpha",))
    rough_input = principled_input(bsdf, ("Roughness",))
    metallic_input = principled_input(bsdf, ("Metallic",))
    if base_input is not None:
        base_input.default_value = (0.035, 0.045, 0.042, 1.0)
    if alpha_input is not None:
        alpha_input.default_value = 0.38
    if rough_input is not None:
        rough_input.default_value = 0.12
    if metallic_input is not None:
        metallic_input.default_value = 0.0
    return material


def main() -> int:
    args = parse_args()
    if args.backup_out:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(bpy.data.filepath, backup)
    material = make_puddle_material()
    rows = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or str(obj.get("ue_static_mesh_path") or "") != TARGET_PATH:
            continue
        before = [slot.material.name for slot in obj.material_slots if slot.material]
        if not obj.material_slots:
            obj.data.materials.append(material)
        for slot in obj.material_slots:
            if slot.material is None or slot.material.name == "MAT__UNBOUND_SOURCE_MATERIAL":
                slot.link = "OBJECT"
                slot.material = material
        obj["puddle_material_repair"] = material["source_material_status"]
        rows.append({"object": obj.name, "before": before, "after": [slot.material.name for slot in obj.material_slots if slot.material]})
    proof = {
        "blend_path": bpy.data.filepath,
        "target_static_mesh_path": TARGET_PATH,
        "objects_repaired": len(rows),
        "rows": rows,
        "status": "floor_puddle_unbound_slot_replaced_with_named_shader_approximation",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_floor_puddle_shader_repair"] = proof["status"]
    bpy.context.scene["gridlock_floor_puddle_shader_repair_proof"] = str(args.proof_out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
