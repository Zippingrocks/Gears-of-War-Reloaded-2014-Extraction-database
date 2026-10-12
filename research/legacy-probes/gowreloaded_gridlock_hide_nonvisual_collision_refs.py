#!/usr/bin/env python3
"""Disable visible draw for Gridlock nonvisual hitmesh/collision reference meshes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def get_collection(name: str) -> bpy.types.Collection:
    root = bpy.data.collections.get("MP_Gridlock_Reloaded_Native_Scene") or bpy.context.scene.collection
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in root.children:
        try:
            root.children.link(coll)
        except RuntimeError:
            pass
    return coll


def link_only(obj: bpy.types.Object, target: bpy.types.Collection) -> None:
    if obj.name not in target.objects:
        target.objects.link(obj)
    for coll in list(obj.users_collection):
        if coll != target:
            coll.objects.unlink(obj)


def material_names(obj: bpy.types.Object) -> list[str]:
    return [slot.material.name for slot in obj.material_slots if slot.material]


def is_nonvisual_collision_ref(obj: bpy.types.Object) -> tuple[bool, str]:
    static_path = str(obj.get("ue_static_mesh_path") or "").lower()
    mats = " ".join(name.lower() for name in material_names(obj))
    if "delta_window_hitmeshes01." in static_path or "hitmesh" in static_path:
        return True, "window_hitmesh_collision_reference"
    if "delta_puddlecollisions.materials.puddle_physmat" in mats:
        return True, "puddle_physical_material_collision_reference"
    return False, ""


def main() -> int:
    args = parse_args()
    if args.backup_out:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(bpy.data.filepath, backup)
    coll = get_collection("StaticMesh_Nonvisual_Collision_Reference_Disabled")
    coll.hide_viewport = True
    coll.hide_render = True
    rows: list[dict[str, Any]] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        match, reason = is_nonvisual_collision_ref(obj)
        if not match:
            continue
        obj.hide_viewport = True
        obj.hide_render = True
        obj["nonvisual_collision_reference_disabled"] = reason
        link_only(obj, coll)
        rows.append(
            {
                "object": obj.name,
                "reason": reason,
                "ue_static_mesh_path": obj.get("ue_static_mesh_path", ""),
                "materials": material_names(obj),
            }
        )
    proof = {
        "blend_path": bpy.data.filepath,
        "objects_disabled_preserved": len(rows),
        "rows": rows,
        "status": "nonvisual_hitmesh_and_puddle_collision_references_disabled_preserved",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_nonvisual_collision_reference_repair"] = proof["status"]
    bpy.context.scene["gridlock_nonvisual_collision_reference_repair_proof"] = str(args.proof_out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({key: proof[key] for key in ("objects_disabled_preserved", "status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
