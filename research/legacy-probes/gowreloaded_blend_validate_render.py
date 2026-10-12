from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-out", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--resolution-x", type=int, default=1280)
    parser.add_argument("--resolution-y", type=int, default=720)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    render_out = Path(args.render_out)
    proof_out = Path(args.proof_out)
    render_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.parent.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = args.resolution_x
    scene.render.resolution_y = args.resolution_y
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(render_out)
    if scene.camera is None and "Overview_Camera" in bpy.data.objects:
        scene.camera = bpy.data.objects["Overview_Camera"]
    bpy.ops.render.render(write_still=True)

    proof = {
        "blend_path": bpy.data.filepath,
        "render_path": str(render_out),
        "render_exists": render_out.exists(),
        "render_size": render_out.stat().st_size if render_out.exists() else 0,
        "objects": len(bpy.data.objects),
        "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
        "mesh_datablocks": len(bpy.data.meshes),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        "top_collections": sorted(collection.name for collection in bpy.context.scene.collection.children),
        "camera": scene.camera.name if scene.camera else "",
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0 if proof["render_exists"] and proof["render_size"] > 0 and proof["mesh_objects"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
