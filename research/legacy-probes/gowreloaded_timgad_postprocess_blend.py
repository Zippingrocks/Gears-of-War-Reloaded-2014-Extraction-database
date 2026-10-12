from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--root-name", default="SP_Timgad_A_Chapter_01_IMPASSE_Reloaded_Native_Textured")
    parser.add_argument("--source-scope", default="SP_Timgad A package family")
    parser.add_argument("--chapter-provider", default="Timgad-Chap1 UIDataProvider_WarfareMaps")
    parser.add_argument("--chapter-display-name", default="IMPASSE")
    parser.add_argument("--chapter-enum-start", default="eCHAPTER_Timgad_Impasse")
    parser.add_argument("--export-note", default="Pilot native textured export; SP_Timgad_B/Jurassic and SP_Station intentionally excluded.")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    old_root = bpy.data.collections.get("SP_FactoryBasement_Reloaded_Native_Textured")
    if old_root is not None:
        old_root.name = args.root_name

    bpy.context.scene["game"] = "Gears of War Reloaded"
    bpy.context.scene["source_scope"] = args.source_scope
    bpy.context.scene["chapter_provider"] = args.chapter_provider
    bpy.context.scene["chapter_display_name"] = args.chapter_display_name
    bpy.context.scene["chapter_enum_start"] = args.chapter_enum_start
    bpy.context.scene["export_note"] = args.export_note

    root_objects = list(bpy.context.scene.collection.objects)
    proof = {
        "blend_path": bpy.data.filepath,
        "root_collection_renamed": old_root is not None,
        "scene_root_direct_objects": len(root_objects),
        "objects": len(bpy.data.objects),
        "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
        "mesh_datablocks": len(bpy.data.meshes),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "collections": len(bpy.data.collections),
        "has_target_root_collection": bpy.data.collections.get(args.root_name) is not None,
        "top_collections": sorted(collection.name for collection in bpy.context.scene.collection.children),
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
