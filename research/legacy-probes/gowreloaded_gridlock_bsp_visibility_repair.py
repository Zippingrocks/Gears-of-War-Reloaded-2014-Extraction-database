#!/usr/bin/env python3
"""Move nonvisual Gridlock BSP Model proofs out of the visible map layer.

The Gridlock manifest filters BSP Model exports into visual candidates vs.
volume/collision proof rows. Older scene builds imported all Model proofs with a
neutral BSP material, which leaves large untextured hulls visible in Blender.
This pass preserves every decoded object but disables render/viewport display
for manifest-excluded BSP models and records the reason on each object.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
MODEL2_POLICY_PATH = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


model2_policy = load_module(MODEL2_POLICY_PATH, "gowr_gridlock_model2_visual_policy")


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def get_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    root = parent or bpy.context.scene.collection
    existing = bpy.data.collections.get(name)
    if existing:
        if existing.name not in root.children:
            try:
                root.children.link(existing)
            except RuntimeError:
                pass
        return existing
    coll = bpy.data.collections.new(name)
    root.children.link(coll)
    return coll


def link_only(obj: bpy.types.Object, target: bpy.types.Collection) -> None:
    if obj.name not in target.objects:
        target.objects.link(obj)
    for coll in list(obj.users_collection):
        if coll != target:
            coll.objects.unlink(obj)


def parse_export_index(obj: bpy.types.Object) -> int | None:
    value = obj.get("bsp_model_export_index")
    if value is not None:
        try:
            return int(value)
        except Exception:
            pass
    marker = "__MP_Gridlock.war__"
    if marker in obj.name:
        try:
            return int(obj.name.rsplit(marker, 1)[1])
        except Exception:
            return None
    return None


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.scene_manifest)
    manifest = read_json(manifest_path)
    included = {
        int(row["export_index"]): row
        for row in manifest.get("bsp_models", [])
        if str(row.get("package", "")).lower() == "mp_gridlock.war"
    }
    excluded = {
        int(row["export_index"]): row
        for row in manifest.get("excluded_bsp_models", [])
        if str(row.get("package", "")).lower() == "mp_gridlock.war"
    }
    root = bpy.data.collections.get("MP_Gridlock_Reloaded_Native_Scene") or bpy.context.scene.collection
    visual_coll = get_collection("BSP_Model_Visual_Candidates", root)
    collision_coll = get_collection("BSP_Model_Collision_Reference_Disabled", root)
    unknown_coll = get_collection("BSP_Model_Unclassified_Review", root)
    collision_coll.hide_viewport = True
    collision_coll.hide_render = True

    rows: list[dict[str, Any]] = []
    for obj in bpy.data.objects:
        export_index = parse_export_index(obj)
        if export_index is None or obj.type != "MESH":
            continue
        if obj.name.startswith("Model_") or obj.name.startswith("BSP__"):
            if export_index in included:
                row = included[export_index]
                obj.hide_viewport = False
                obj.hide_render = False
                obj["bsp_visibility_layer"] = "visual_candidate"
                obj["bsp_visibility_reason"] = row.get("bsp_filter_reason", "")
                obj["bsp_model_export_index"] = int(export_index)
                obj["bsp_model_full_path"] = row.get("full_path", "")
                link_only(obj, visual_coll)
                action = "kept_visible"
            elif export_index in excluded:
                row = excluded[export_index]
                obj.hide_viewport = True
                obj.hide_render = True
                obj["bsp_visibility_layer"] = "collision_reference_disabled"
                obj["bsp_visibility_reason"] = row.get("filter_reason", "")
                obj["bsp_model_export_index"] = int(export_index)
                obj["bsp_model_full_path"] = row.get("full_path", "")
                link_only(obj, collision_coll)
                action = "disabled_preserved"
            else:
                row = {}
                obj.hide_viewport = True
                obj.hide_render = True
                obj["bsp_visibility_layer"] = "unclassified_review_disabled"
                obj["bsp_visibility_reason"] = "not present in current scene manifest included/excluded BSP tables"
                link_only(obj, unknown_coll)
                action = "disabled_unclassified"
            rows.append(
                {
                    "object": obj.name,
                    "export_index": export_index,
                    "action": action,
                    "full_path": row.get("full_path", ""),
                    "reason": obj.get("bsp_visibility_reason", ""),
                }
            )

    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        bpy.data.objects.get(MODEL2_OBJECT),
        reason="bsp_visibility_repair",
    )

    proof = {
        "blend_path": bpy.data.filepath,
        "scene_manifest": str(manifest_path),
        "included_manifest_bsp_models": len(included),
        "excluded_manifest_bsp_models": len(excluded),
        "scene_bsp_objects_seen": len(rows),
        "kept_visible": sum(1 for row in rows if row["action"] == "kept_visible"),
        "disabled_preserved": sum(1 for row in rows if row["action"] == "disabled_preserved"),
        "disabled_unclassified": sum(1 for row in rows if row["action"] == "disabled_unclassified"),
        "rows": rows,
        "model2_visual_policy": model2_policy_result,
        "status": "bsp_collision_reference_models_preserved_but_removed_from_visible_layer",
    }
    proof_path = Path(args.proof_out)
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_bsp_visibility_repair"] = proof["status"]
    bpy.context.scene["gridlock_bsp_visibility_repair_proof"] = str(proof_path)
    if args.backup_out:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(bpy.data.filepath, backup)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({key: proof[key] for key in ("scene_bsp_objects_seen", "kept_visible", "disabled_preserved", "disabled_unclassified", "status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
