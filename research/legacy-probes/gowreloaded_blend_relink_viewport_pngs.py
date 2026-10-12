#!/usr/bin/env python3
"""Relink Blender DDS images to generated PNG viewport aliases."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--png-map", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--save-as", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def abs_image_path(image: bpy.types.Image) -> str:
    try:
        return bpy.path.abspath(image.filepath)
    except Exception:
        return str(image.filepath or "")


def main() -> None:
    args = parse_args()
    mapping = json.loads(Path(args.png_map).read_text(encoding="utf-8"))
    by_source = {
        os.path.normcase(str(row.get("source") or "")): row
        for row in (mapping.get("rows") or [])
        if row.get("status") == "converted" and row.get("png")
    }

    if args.backup_out:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copyfile(bpy.data.filepath, backup)

    relinked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for image in bpy.data.images:
        current = abs_image_path(image)
        if not current.lower().endswith(".dds"):
            continue
        row = by_source.get(os.path.normcase(current))
        if not row:
            skipped.append({"image": image.name, "source": current, "reason": "no_png_alias"})
            continue
        png_path = str(row.get("png") or "")
        if not Path(png_path).exists():
            skipped.append({"image": image.name, "source": current, "png": png_path, "reason": "png_missing"})
            continue
        colorspace = ""
        try:
            colorspace = image.colorspace_settings.name
        except Exception:
            pass
        image["source_dds_path"] = current
        image.filepath = png_path
        image.source = "FILE"
        try:
            image.reload()
        except Exception as exc:  # noqa: BLE001
            skipped.append({"image": image.name, "source": current, "png": png_path, "reason": "reload_failed", "error": repr(exc)})
            continue
        try:
            if colorspace:
                image.colorspace_settings.name = colorspace
        except Exception:
            pass
        image["viewport_png_alias"] = png_path
        relinked.append({"image": image.name, "source": current, "png": png_path, "colorspace": colorspace})

    proof = {
        "blend_path": bpy.data.filepath,
        "png_map": str(args.png_map),
        "relinked_images": len(relinked),
        "skipped_images": len(skipped),
        "relinked": relinked,
        "skipped": skipped[:100],
        "objects": len(bpy.data.objects),
        "meshes": len(bpy.data.meshes),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "note": "DDS source paths are preserved on each relinked Image as custom property source_dds_path.",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2), encoding="utf-8")

    if not args.no_save:
        save_path = args.save_as or bpy.data.filepath
        bpy.ops.wm.save_as_mainfile(filepath=save_path)
    print(json.dumps({k: v for k, v in proof.items() if k not in {"relinked", "skipped"}}, indent=2))


if __name__ == "__main__":
    main()
