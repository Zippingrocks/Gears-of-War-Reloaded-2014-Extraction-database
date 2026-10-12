#!/usr/bin/env python3
"""Convert referenced DDS images to bounded PNG viewport aliases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image


def safe_name(text: str, limit: int = 80) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in text)
    clean = clean.strip("._")
    return (clean or "image")[:limit]


def png_name_for(path: Path) -> str:
    digest = hashlib.sha1(os.path.normcase(str(path)).encode("utf-8", errors="ignore")).hexdigest()[:16]
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
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-json", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--map-out", required=True)
    parser.add_argument("--max-size", type=int, default=1024)
    args = parser.parse_args()

    payload = json.loads(Path(args.image_json).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for image in payload.get("images") or []:
        abs_path = str(image.get("abs_path") or "")
        if not abs_path.lower().endswith(".dds"):
            continue
        src = Path(abs_path)
        key = os.path.normcase(str(src))
        if key in seen:
            continue
        seen.add(key)
        dst = out_dir / png_name_for(src)
        if not src.exists():
            rows.append({"source": str(src), "png": str(dst), "status": "source_missing"})
            continue
        try:
            row = convert_dds(src, dst, int(args.max_size))
            row["source_bytes"] = src.stat().st_size
            row["png_bytes"] = dst.stat().st_size if dst.exists() else 0
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            rows.append({"source": str(src), "png": str(dst), "status": "failed", "error": repr(exc)})

    summary = {
        "image_json": str(args.image_json),
        "out_dir": str(out_dir),
        "max_size": int(args.max_size),
        "unique_dds_sources": len(rows),
        "converted_or_existing": sum(1 for row in rows if row.get("status") == "converted"),
        "failed": sum(1 for row in rows if row.get("status") == "failed"),
        "source_missing": sum(1 for row in rows if row.get("status") == "source_missing"),
        "source_bytes_total": sum(int(row.get("source_bytes") or 0) for row in rows),
        "png_bytes_total": sum(int(row.get("png_bytes") or 0) for row in rows),
        "rows": rows,
    }
    Path(args.map_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
