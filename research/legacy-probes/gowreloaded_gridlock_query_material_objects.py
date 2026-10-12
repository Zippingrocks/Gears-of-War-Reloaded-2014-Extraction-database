#!/usr/bin/env python3
"""List visible Gridlock objects using a named material."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--material", action="append", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(passthrough)


def visible(obj: bpy.types.Object) -> bool:
    if obj.hide_viewport or obj.hide_render:
        return False
    return all(not coll.hide_viewport and not coll.hide_render for coll in obj.users_collection)


def main() -> int:
    args = parse_args()
    wanted = set(args.material)
    rows: list[dict[str, Any]] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not visible(obj):
            continue
        mats = [slot.material.name for slot in obj.material_slots if slot.material]
        if wanted.intersection(mats):
            rows.append(
                {
                    "object": obj.name,
                    "materials": mats,
                    "ue_static_mesh_path": obj.get("ue_static_mesh_path", ""),
                    "ue_materials_json": obj.get("ue_materials_json", ""),
                    "bsp_model_full_path": obj.get("bsp_model_full_path", ""),
                }
            )
    proof = {"materials": sorted(wanted), "count": len(rows), "rows": rows}
    Path(args.out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True)[:8000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
