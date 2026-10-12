#!/usr/bin/env python3
"""Reconstruct Blender-usable normal maps from exported PF_DXN/BC5 Gridlock PNGs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--map-out", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-invert-green", dest="invert_green", action="store_false")
    parser.set_defaults(invert_green=True)
    return parser.parse_args()


def is_dxn_normal(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() == ".png" and "normal" in name and ("pf_dxn" in name or "dxn" in name)


def needs_reconstruction(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    extrema = rgba.getextrema()
    blue_min, blue_max = extrema[2]
    return int(blue_max) - int(blue_min) <= 2


def reconstruct(path: Path, out_path: Path, invert_green: bool) -> dict[str, Any]:
    image = Image.open(path).convert("RGBA")
    source = np.asarray(image, dtype=np.uint8)
    rg = source[:, :, :2].astype(np.float32) / 255.0
    xy = rg * 2.0 - 1.0
    z = np.sqrt(np.maximum(0.0, 1.0 - (xy[:, :, 0] * xy[:, :, 0] + xy[:, :, 1] * xy[:, :, 1])))
    out = np.empty_like(source)
    out[:, :, 0] = source[:, :, 0]
    out[:, :, 1] = 255 - source[:, :, 1] if invert_green else source[:, :, 1]
    out[:, :, 2] = np.clip(np.rint(z * 255.0), 0, 255).astype(np.uint8)
    out[:, :, 3] = source[:, :, 3]
    Image.fromarray(out, mode="RGBA").save(out_path)
    return {
        "source": str(path),
        "out": str(out_path),
        "size": list(image.size),
        "invert_green": invert_green,
        "source_blue_extrema": list(image.convert("RGBA").getextrema()[2]),
        "out_blue_extrema": list(Image.open(out_path).convert("RGBA").getextrema()[2]),
    }


def main() -> int:
    args = parse_args()
    texture_dir = Path(args.texture_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    normal_paths = [path for path in sorted(texture_dir.glob("*.png")) if is_dxn_normal(path)]
    rows: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    skipped: list[dict[str, Any]] = []
    for path in normal_paths:
        image = Image.open(path)
        if not needs_reconstruction(image):
            skipped.append({"source": str(path), "reason": "blue_channel_not_flat"})
            continue
        out_path = out_dir / path.name.replace(".png", "__BC5_reconstructed_OpenGL.png")
        detail = reconstruct(path, out_path, bool(args.invert_green))
        rows.append(detail)
        mapping[str(path).lower()] = str(out_path)
        mapping[path.name.lower()] = str(out_path)
    proof = {
        "texture_dir": str(texture_dir),
        "out_dir": str(out_dir),
        "normal_candidates": len(normal_paths),
        "reconstructed": len(rows),
        "skipped": len(skipped),
        "invert_green": bool(args.invert_green),
        "rows": rows,
        "skipped_samples": skipped[:40],
    }
    Path(args.map_out).write_text(json.dumps(mapping, indent=2, ensure_ascii=True), encoding="utf-8")
    Path(args.proof_out).write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"rows", "skipped_samples"}}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
