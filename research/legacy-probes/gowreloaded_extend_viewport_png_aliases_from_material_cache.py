#!/usr/bin/env python3
"""Extend a viewport PNG alias map with every DDS referenced by material cache roles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image


def norm_path(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(str(Path(path).resolve(strict=False)))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def png_name_for(path: Path) -> str:
    digest = hashlib.sha1(norm_path(str(path)).encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"vp_{digest}.png"


def convert_dds(src: Path, dst: Path, max_size: int) -> dict[str, Any]:
    with Image.open(src) as image:
        original_size = list(image.size)
        converted = image.convert("RGBA")
        resized = False
        if max(converted.size) > max_size:
            converted.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            resized = True
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            converted.save(dst, "PNG", optimize=True)
        return {
            "source": str(src),
            "png": str(dst),
            "original_size": original_size,
            "png_size": list(converted.size),
            "resized": resized,
            "status": "converted",
            "source_bytes": src.stat().st_size,
            "png_bytes": dst.stat().st_size if dst.exists() else 0,
        }


def material_dds_sources(material_cache: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    for binding in material_cache.values():
        if not isinstance(binding, dict):
            continue
        roles = binding.get("roles")
        if not isinstance(roles, dict):
            continue
        for role_data in roles.values():
            if isinstance(role_data, dict):
                dds_path = str(role_data.get("dds_path") or "").strip()
                if dds_path:
                    sources.add(dds_path)
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--png-map", required=True)
    parser.add_argument("--material-cache", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--out-map", required=True)
    parser.add_argument("--max-size", type=int, default=1024)
    args = parser.parse_args()

    png_map = json.loads(Path(args.png_map).read_text(encoding="utf-8"))
    material_cache = json.loads(Path(args.material_cache).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    rows = list(png_map.get("rows") or [])
    by_source = {norm_path(str(row.get("source") or "")): row for row in rows if row.get("source")}

    added = 0
    refreshed = 0
    failed = 0
    for source in sorted(material_dds_sources(material_cache), key=str.lower):
        src = Path(source)
        key = norm_path(source)
        dst = out_dir / png_name_for(src)
        if key in by_source and Path(str(by_source[key].get("png") or "")).exists():
            refreshed += 1
            continue
        if not src.exists():
            row = {"source": str(src), "png": str(dst), "status": "source_missing"}
            failed += 1
        else:
            try:
                row = convert_dds(src, dst, int(args.max_size))
                added += 1
            except Exception as exc:  # noqa: BLE001
                row = {"source": str(src), "png": str(dst), "status": "failed", "error": repr(exc)}
                failed += 1
        by_source[key] = row

    merged_rows = [by_source[key] for key in sorted(by_source)]
    summary = {
        "base_png_map": str(args.png_map),
        "material_cache": str(args.material_cache),
        "out_dir": str(out_dir),
        "max_size": int(args.max_size),
        "unique_sources": len(merged_rows),
        "already_present": refreshed,
        "added": added,
        "failed_or_missing": failed,
        "converted_or_existing": sum(1 for row in merged_rows if row.get("status") == "converted"),
        "rows": merged_rows,
    }
    Path(args.out_map).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
