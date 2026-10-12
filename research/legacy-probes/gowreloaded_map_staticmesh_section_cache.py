#!/usr/bin/env python3
"""Generic StaticMesh section/material cache wrapper for Reloaded cooked maps."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_staticmesh_section_cache.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_section_cache", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load source tool: {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_section_cache"] = module
    spec.loader.exec_module(module)
    return module


def sanitize_prefix(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "_")
    value = "".join(out).strip("_")
    while "__" in value:
        value = value.replace("__", "_")
    return value or "gowreloaded_map"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--asset-csv", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    args = parser.parse_args()

    src = load_source()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = sanitize_prefix(args.prefix)

    asset_rows = src.read_csv(Path(args.asset_csv))
    package_cache: dict[str, dict[str, Any]] = {}
    cache: dict[str, Any] = {}
    summary_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for index, asset in enumerate(asset_rows, 1):
        if asset.get("extract_status") != "bulk_position_index":
            result = {"status": "not_bulk_position_index", "sections": []}
        else:
            ctx = src.package_context(Path(args.map_dir), asset["package"], package_cache)
            result = src.decode_sections_fast(ctx["virt"], asset, ctx["ref_path"], ctx["imports"], ctx["exports"])
        status_counts[result.get("status", "")] += 1
        cache[asset["full_path"].lower()] = {
            "asset": asset["full_path"],
            "status": result.get("status", ""),
            "layout_name": result.get("layout_name", ""),
            "record_size": result.get("record_size", ""),
            "array_rel": result.get("array_rel", ""),
            "section_count": result.get("section_count", 0),
            "sections": result.get("sections", []),
        }
        summary_rows.append(
            {
                "package": asset.get("package", ""),
                "export_index": asset.get("export_index", ""),
                "object_name": asset.get("object_name", ""),
                "full_path": asset.get("full_path", ""),
                "extract_status": asset.get("extract_status", ""),
                "section_status": result.get("status", ""),
                "layout_name": result.get("layout_name", ""),
                "record_size": result.get("record_size", ""),
                "array_rel": result.get("array_rel", ""),
                "section_count": result.get("section_count", 0),
                "material_like_count": result.get("material_like_count", 0),
                "material_paths": "; ".join(section.get("material_path", "") for section in result.get("sections", [])[:12]),
            }
        )
        if index % 250 == 0:
            print(f"cached sections for {index} / {len(asset_rows)} StaticMesh rows")

    cache_path = out_dir / f"{prefix}_staticmesh_section_cache.json"
    csv_path = out_dir / f"{prefix}_staticmesh_section_cache_summary.csv"
    manifest_path = out_dir / f"{prefix}_staticmesh_section_cache_manifest.json"
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=True), encoding="utf-8")
    src.write_csv(
        csv_path,
        summary_rows,
        ["package", "export_index", "object_name", "full_path", "extract_status", "section_status", "layout_name", "record_size", "array_rel", "section_count", "material_like_count", "material_paths"],
    )
    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "asset_rows": len(asset_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "cache_path": str(cache_path),
        "summary_csv": str(csv_path),
        "source_tool": str(SOURCE_TOOL),
        "rule": "Decode TArray-prefixed FStaticMeshElement records before the position buffer; material_ref at i32[0], first_index at i32[4], num_triangles at i32[5] for 32/36/40-byte layouts, plus rare 24-byte shifted layout fallback.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
