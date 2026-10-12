#!/usr/bin/env python3
"""Export Blender image filepath metadata to JSON.

Run inside Blender:
    blender -b scene.blend --python gowreloaded_blend_export_image_paths.py -- --out images.json
"""

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
    parser.add_argument("--out", required=True)
    return parser.parse_args(passthrough)


def image_row(image: bpy.types.Image) -> dict[str, Any]:
    try:
        abs_path = bpy.path.abspath(image.filepath)
    except Exception:
        abs_path = str(image.filepath or "")
    colorspace = ""
    try:
        colorspace = image.colorspace_settings.name
    except Exception:
        pass
    return {
        "name": image.name,
        "filepath": str(image.filepath or ""),
        "abs_path": abs_path,
        "source": str(image.source),
        "type": str(image.type),
        "colorspace": colorspace,
        "size": [0, 0],
        "size_note": "not queried; querying image.size can force DDS decode and crash Blender on this scene",
        "packed": image.packed_file is not None,
    }


def main() -> None:
    args = parse_args()
    rows = [image_row(image) for image in bpy.data.images]
    dds_rows = [row for row in rows if row["abs_path"].lower().endswith(".dds")]
    payload = {
        "blend_path": bpy.data.filepath,
        "image_count": len(rows),
        "dds_image_count": len(dds_rows),
        "images": rows,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"out": args.out, "image_count": len(rows), "dds_image_count": len(dds_rows)}, indent=2))


if __name__ == "__main__":
    main()
