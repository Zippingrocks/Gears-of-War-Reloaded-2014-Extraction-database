#!/usr/bin/env python3
"""Audit exported Gridlock normal-map PNG channel ranges."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--limit", type=int, default=40)
    return parser.parse_args()


def audit_image(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGBA")
    stat = ImageStat.Stat(image)
    extrema = image.getextrema()
    means = [round(float(value), 3) for value in stat.mean]
    mins = [int(pair[0]) for pair in extrema]
    maxs = [int(pair[1]) for pair in extrema]
    blue_flat = maxs[2] - mins[2] <= 2
    alpha_flat = maxs[3] - mins[3] <= 2
    return {
        "path": str(path),
        "name": path.name,
        "mode": image.mode,
        "size": list(image.size),
        "mean_rgba": means,
        "min_rgba": mins,
        "max_rgba": maxs,
        "blue_flat": blue_flat,
        "alpha_flat": alpha_flat,
        "looks_like_bc5_or_dxn_export": blue_flat or "PF_DXN" in path.name,
    }


def main() -> int:
    args = parse_args()
    texture_dir = Path(args.texture_dir)
    normal_paths = sorted(
        path
        for path in texture_dir.glob("*.png")
        if "normal" in path.name.lower() or "PF_DXN" in path.name
    )
    rows = [audit_image(path) for path in normal_paths[: args.limit]]
    proof = {
        "texture_dir": str(texture_dir),
        "normal_png_count": len(normal_paths),
        "sample_count": len(rows),
        "bc5_or_dxn_like_count": sum(1 for row in rows if row["looks_like_bc5_or_dxn_export"]),
        "rows": rows,
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in proof.items() if k != "rows"}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
