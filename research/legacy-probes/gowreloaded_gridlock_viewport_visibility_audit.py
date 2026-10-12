#!/usr/bin/env python3
"""Audit Blender viewport-visible objects independently from render visibility."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy  # type: ignore


MODEL_RE = re.compile(r"^Model_\d+__MP_Gridlock\.war__\d+", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    return parser.parse_args(passthrough)


def obj_row(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data if obj.type == "MESH" else None
    return {
        "object": obj.name,
        "type": obj.type,
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "viewport_visible_object_flag": not bool(obj.hide_viewport),
        "render_visible_object_flag": not bool(obj.hide_render),
        "collections": [
            {
                "name": collection.name,
                "hide_viewport": bool(collection.hide_viewport),
                "hide_render": bool(collection.hide_render),
            }
            for collection in obj.users_collection
        ],
        "mesh": mesh.name if mesh else "",
        "mesh_ue_full_path": mesh.get("ue_full_path", "") if mesh else "",
        "static_mesh_path": obj.get("ue_static_mesh_path", ""),
        "game_render_visibility": obj.get("game_render_visibility", ""),
        "materials": [slot.material.name for slot in obj.material_slots if slot.material] if obj.type == "MESH" else [],
        "uv_layers": [layer.name for layer in mesh.uv_layers] if mesh else [],
    }


def main() -> int:
    args = parse_args()
    rows = [obj_row(obj) for obj in bpy.data.objects if obj.type == "MESH" and MODEL_RE.match(obj.name)]
    viewport_visible = [row for row in rows if row["viewport_visible_object_flag"] and not any(col["hide_viewport"] for col in row["collections"])]
    render_visible = [row for row in rows if row["render_visible_object_flag"] and not any(col["hide_render"] for col in row["collections"])]
    counter = Counter()
    for row in rows:
        counter[f"hide_viewport={row['hide_viewport']} hide_render={row['hide_render']}"] += 1
    proof = {
        "blend_path": bpy.data.filepath,
        "summary": {
            "model_star_total": len(rows),
            "model_star_viewport_visible": len(viewport_visible),
            "model_star_render_visible": len(render_visible),
            "visibility_flag_counts": dict(counter),
        },
        "model_star_viewport_visible": viewport_visible,
        "model_star_render_visible": render_visible,
        "all_model_star": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
