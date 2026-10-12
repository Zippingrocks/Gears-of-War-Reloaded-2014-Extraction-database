#!/usr/bin/env python3
"""Image-level sanity checks for decoded Gridlock texture roles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


TARGET_TOKENS = (
    "vehicle_neutral_sedan_01a",
    "cog_undentedcar1_frame",
    "cog_city_brokencarchasey1",
    "frontstaircase2_clean",
    "whitebrick_01a",
    "asphalt_dirty_01a",
    "ephyracity_stairtech01_pe",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture-dir", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=240)
    return parser.parse_args()


def entropy_u8(channel: np.ndarray) -> float:
    hist = np.bincount(channel.reshape(-1), minlength=256).astype(np.float64)
    probs = hist / max(1.0, hist.sum())
    probs = probs[probs > 0.0]
    return float(-(probs * np.log2(probs)).sum())


def image_stats(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGBA")
    arr = np.asarray(image, dtype=np.uint8)
    rgb = arr[:, :, :3].astype(np.float32)
    alpha = arr[:, :, 3]
    means = rgb.mean(axis=(0, 1))
    stds = rgb.std(axis=(0, 1))
    mins = rgb.min(axis=(0, 1))
    maxs = rgb.max(axis=(0, 1))
    gray = np.rint(rgb.mean(axis=2)).astype(np.uint8)

    # Interpret as tangent-space normal map for diagnostics only.
    n = (rgb / 255.0) * 2.0 - 1.0
    lengths = np.sqrt(np.sum(n * n, axis=2))
    blue = rgb[:, :, 2]
    red_green = rgb[:, :, :2] / 255.0
    xy = red_green * 2.0 - 1.0
    xy_len_sq = np.sum(xy * xy, axis=2)

    return {
        "path": str(path),
        "name": path.name,
        "size": list(image.size),
        "bytes": path.stat().st_size,
        "role_guess": role_guess(path.name),
        "channel_mean_rgb": [round(float(v), 3) for v in means],
        "channel_std_rgb": [round(float(v), 3) for v in stds],
        "channel_min_rgb": [int(v) for v in mins],
        "channel_max_rgb": [int(v) for v in maxs],
        "alpha_min_max": [int(alpha.min()), int(alpha.max())],
        "alpha_nonopaque_ratio": round(float(np.mean(alpha < 250)), 6),
        "gray_entropy": round(entropy_u8(gray), 4),
        "blue_span": int(blue.max() - blue.min()),
        "normal_vector_length_mean_if_rgb_normal": round(float(lengths.mean()), 4),
        "normal_vector_length_std_if_rgb_normal": round(float(lengths.std()), 4),
        "bc5_xy_outside_unit_ratio": round(float(np.mean(xy_len_sq > 1.0001)), 6),
    }


def role_guess(name: str) -> str:
    lower = name.lower()
    if "normal" in lower or "pf_dxn" in lower or "dxn" in lower:
        return "normal"
    if "specular" in lower:
        return "specular"
    if "emissive" in lower:
        return "emissive"
    if "mask" in lower or "alpha" in lower:
        return "mask"
    if "_tex" in lower or "delta_tex" in lower:
        return "diffuse"
    return "unknown"


def wanted(path: Path) -> bool:
    lower = path.name.lower()
    if any(token in lower for token in TARGET_TOKENS):
        return True
    if "__bc5_reconstructed" in lower and any(token in lower for token in TARGET_TOKENS):
        return True
    return False


def main() -> int:
    args = parse_args()
    paths: list[Path] = []
    for directory in args.texture_dir:
        root = Path(directory)
        if not root.exists():
            continue
        for path in sorted(root.glob("*.png")):
            if wanted(path):
                paths.append(path)
    paths = paths[: args.limit]
    rows = [image_stats(path) for path in paths]
    by_role: dict[str, Any] = {}
    for role in sorted({row["role_guess"] for row in rows}):
        role_rows = [row for row in rows if row["role_guess"] == role]
        by_role[role] = {
            "count": len(role_rows),
            "mean_gray_entropy": round(float(np.mean([row["gray_entropy"] for row in role_rows])), 4) if role_rows else 0,
            "mean_alpha_nonopaque_ratio": round(float(np.mean([row["alpha_nonopaque_ratio"] for row in role_rows])), 6) if role_rows else 0,
            "mean_blue_span": round(float(np.mean([row["blue_span"] for row in role_rows])), 3) if role_rows else 0,
            "mean_bc5_xy_outside_unit_ratio": round(float(np.mean([row["bc5_xy_outside_unit_ratio"] for row in role_rows])), 6) if role_rows else 0,
        }
    proof = {
        "texture_dirs": args.texture_dir,
        "target_tokens": TARGET_TOKENS,
        "rows": rows,
        "summary": {
            "images_checked": len(rows),
            "by_role": by_role,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof["summary"], indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
