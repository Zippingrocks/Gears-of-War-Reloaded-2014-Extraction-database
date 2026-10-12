#!/usr/bin/env python3
"""Summarize Gridlock indexed UV proof for selected StaticMesh assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_TARGETS = [
    "Delta_Gridlock_01.BSP.bsp_gridlock_road_b_SMesh",
    "COG_City_Ephyra2.COG_City_Ephyra2_1post_Smesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2661_StaticMesh",
    "MP_Gridlock_STITCHINGDATA.SDStitchingProxy_2550_StaticMesh",
    "Neutral_Vehicles.MS_Neutral_Sedan_SMesh",
    "COG_City_Architecture.COG_UndentedCar1_Frame_SMesh_DR",
    "COG_City_Architecture_03.COG_City_BrokenCarChasey1_Smesh_DR",
    "COG_City_Ephyra.COG_City_Ephyra_Facade03_SideTile_MS_SMesh",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", required=True)
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    return parser.parse_args()


def slim_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    stats = candidate.get("stats") or {}
    return {
        "name": candidate.get("name", ""),
        "domain": candidate.get("domain", ""),
        "domain_start": candidate.get("domain_start", 0),
        "encoding": candidate.get("encoding", ""),
        "offset": candidate.get("offset", ""),
        "score": stats.get("score", ""),
        "unique_rounded": stats.get("unique_rounded", ""),
        "span_u": stats.get("span_u", ""),
        "span_v": stats.get("span_v", ""),
        "unitish_ratio": stats.get("unitish_ratio", ""),
        "triangle_degenerate_ratio": stats.get("triangle_degenerate_ratio", ""),
        "triangle_uv_area_avg": stats.get("triangle_uv_area_avg", ""),
        "sample": stats.get("sample", [])[:4],
    }


def summarize_asset(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_path": asset.get("full_path", ""),
        "vertex_count": asset.get("vertex_count", ""),
        "static_vertex_count": asset.get("static_vertex_count", ""),
        "index_min": asset.get("index_min", ""),
        "index_max": asset.get("index_max", ""),
        "doubled_static_stream": asset.get("doubled_static_stream", ""),
        "chosen": asset.get("chosen", {}),
        "chosen_stats": asset.get("chosen_stats", {}),
        "top_candidates": [slim_candidate(candidate) for candidate in (asset.get("top_candidates") or [])[:8]],
    }


def main() -> int:
    args = parse_args()
    proof = json.loads(Path(args.proof).read_text(encoding="utf-8"))
    assets = proof.get("assets") or {}
    out: dict[str, Any] = {"summary": proof.get("summary", {}), "targets": {}}
    for target in args.targets:
        asset = assets.get(target.lower())
        out["targets"][target] = summarize_asset(asset) if isinstance(asset, dict) else {"found": False}
    print(json.dumps(out, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
