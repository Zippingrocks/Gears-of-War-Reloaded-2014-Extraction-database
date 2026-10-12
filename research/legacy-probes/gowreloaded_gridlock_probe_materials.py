#!/usr/bin/env python3
"""Probe selected Gridlock Blender materials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


MATERIALS = [
    "Delta_Gridlock_01.tilefloor_concrete_dirty_01_Delta_Tex",
    "COG_City_Architecture.COG_UndentedCar1_Frame_Delta_Delta_Tex",
    "COG_City_Architecture_03.COG_City_BrokenCarChasey1_Delta_Tex",
    "Neutral_Vehicles.vehicle_neutral_sedan_01a_Delta_Tex",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--materials", nargs="*", default=MATERIALS)
    return parser.parse_args(passthrough)


def main() -> None:
    args = parse_args()
    rows = []
    for name in args.materials:
        material = bpy.data.materials.get(name)
        if material is None:
            rows.append({"material": name, "found": False})
            continue
        nodes = []
        if material.use_nodes and material.node_tree:
            for node in material.node_tree.nodes:
                image = getattr(node, "image", None)
                nodes.append(
                    {
                        "name": node.name,
                        "type": node.bl_idname,
                        "image": image.name if image else "",
                        "image_filepath": image.filepath if image else "",
                    }
                )
        rows.append(
            {
                "material": name,
                "found": True,
                "custom_properties": {str(key): material.get(key) for key in material.keys()},
                "node_count": len(nodes),
                "nodes": nodes,
            }
        )
    with Path(args.proof_out).open("w", encoding="utf-8") as handle:
        json.dump({"scene": bpy.data.filepath, "materials": rows}, handle, indent=2)


if __name__ == "__main__":
    main()
