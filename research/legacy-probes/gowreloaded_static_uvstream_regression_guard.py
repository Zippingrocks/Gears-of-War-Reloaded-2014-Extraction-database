#!/usr/bin/env python3
"""Fail-fast guard for Gears Reloaded StaticMesh UV stream decoding.

Run this after a map clean extract and before building a `.blend`.

Why it exists:
MP_Gridlock exposed a bad assumption where `static_vertex_buffer.data_rel`
was treated as the first UV item. In UE3 StaticMesh UV streams, the clean
offset can point at stream metadata/header instead:

    NumTexCoords, ItemSize, NumVerts, bUseFullPrecisionUVs,
    BulkItemSize, BulkItemCount, Payload...

If an exporter reads the metadata/header as UV payload, materials look wildly
smeared even though the correct textures are bound. This guard verifies the
repo-confirmed payload start for every bulk StaticMesh row.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean-csv", required=True)
    parser.add_argument("--decompressed-dir", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument(
        "--allow-legacy-unverified",
        action="store_true",
        help="Allow rows whose data_rel does not match UE3 UV stream metadata. Use only for older/nonstandard extracts.",
    )
    return parser.parse_args()


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_json_field(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def package_bytes(package_dir: Path, package_name: str, cache: dict[str, bytes]) -> bytes:
    key = package_name.lower()
    if key in cache:
        return cache[key]
    stem = Path(package_name).stem
    suffix = Path(package_name).suffix or ".war"
    candidates = [
        package_dir / package_name,
        package_dir / f"{stem}.decompressed{suffix}",
        package_dir / f"{stem}.decompressed.war",
    ]
    for candidate in candidates:
        if candidate.exists():
            cache[key] = candidate.read_bytes()
            return cache[key]
    raise FileNotFoundError(f"no decompressed package for {package_name} under {package_dir}")


def detect_uv_stream(data: bytes, raw_base: int, item_size: int, item_count: int) -> dict[str, Any]:
    if item_size <= 0 or item_count <= 0:
        return {"status": "missing_static_vertex_buffer"}

    if raw_base >= 12 and raw_base + 12 <= len(data):
        num_texcoords = i32(data, raw_base - 12)
        meta_item_size = i32(data, raw_base - 8)
        meta_count = i32(data, raw_base - 4)
        full_precision = i32(data, raw_base)
        bulk_item_size = i32(data, raw_base + 4)
        bulk_count = i32(data, raw_base + 8)
        if (
            1 <= num_texcoords <= 8
            and meta_item_size == item_size
            and meta_count == item_count
            and full_precision in {0, 1}
            and bulk_item_size == item_size
            and bulk_count == item_count
        ):
            return {
                "status": "repo_verified",
                "layout": "ue3_uvstream_data_rel_at_full_precision_flag",
                "payload_delta_from_data_rel": 12,
                "payload_abs": raw_base + 12,
                "num_texcoords": num_texcoords,
                "use_full_precision_uvs": bool(full_precision),
                "uv0_offset": uv_offset(item_size, num_texcoords, bool(full_precision), 0),
                "uv1_offset": uv_offset(item_size, num_texcoords, bool(full_precision), 1),
            }

    if raw_base >= 16 and raw_base + 8 <= len(data):
        num_texcoords = i32(data, raw_base - 16)
        meta_item_size = i32(data, raw_base - 12)
        meta_count = i32(data, raw_base - 8)
        full_precision = i32(data, raw_base - 4)
        bulk_item_size = i32(data, raw_base)
        bulk_count = i32(data, raw_base + 4)
        if (
            1 <= num_texcoords <= 8
            and meta_item_size == item_size
            and meta_count == item_count
            and full_precision in {0, 1}
            and bulk_item_size == item_size
            and bulk_count == item_count
        ):
            return {
                "status": "repo_verified",
                "layout": "ue3_uvstream_data_rel_at_bulk_header",
                "payload_delta_from_data_rel": 8,
                "payload_abs": raw_base + 8,
                "num_texcoords": num_texcoords,
                "use_full_precision_uvs": bool(full_precision),
                "uv0_offset": uv_offset(item_size, num_texcoords, bool(full_precision), 0),
                "uv1_offset": uv_offset(item_size, num_texcoords, bool(full_precision), 1),
            }

    return {
        "status": "legacy_unverified",
        "layout": "data_rel_not_matched_to_repo_uvstream_header",
        "payload_delta_from_data_rel": 0,
        "payload_abs": raw_base,
        "num_texcoords": "",
        "use_full_precision_uvs": "",
        "uv0_offset": "",
        "uv1_offset": "",
    }


def uv_offset(item_size: int, num_texcoords: int, full_precision: bool, channel: int) -> int | str:
    pair_size = 8 if full_precision else 4
    prefix = item_size - num_texcoords * pair_size
    offset = prefix + channel * pair_size
    if prefix < 0 or channel >= num_texcoords or offset + pair_size > item_size:
        return ""
    return offset


def old_heuristic_offset(item_size: int) -> int | str:
    if item_size >= 20:
        return 4
    if item_size >= 16:
        return 0
    return ""


def main() -> int:
    args = parse_args()
    package_dir = Path(args.decompressed_dir)
    package_cache: dict[str, bytes] = {}
    rows = read_csv_rows(Path(args.clean_csv))
    checked: list[dict[str, Any]] = []
    skipped = Counter()
    status_counts = Counter()
    layout_counts = Counter()
    old_mismatch_count = 0

    for row in rows:
        if row.get("extract_status") != "bulk_position_index":
            skipped[f"status:{row.get('extract_status')}"] += 1
            continue
        geom = parse_json_field(row.get("geometry_json", ""), {})
        static_vertex = geom.get("static_vertex_buffer") or {}
        item_size = int(static_vertex.get("element_size") or 0)
        item_count = int(static_vertex.get("count") or 0)
        serial_offset = int(row.get("serial_offset") or 0)
        raw_base = serial_offset + int(static_vertex.get("data_rel") or 0)
        try:
            data = package_bytes(package_dir, row["package"], package_cache)
            detected = detect_uv_stream(data, raw_base, item_size, item_count)
        except Exception as exc:
            detected = {"status": "probe_error", "layout": type(exc).__name__, "error": repr(exc)}

        old_offset = old_heuristic_offset(item_size)
        old_mismatch = detected.get("status") == "repo_verified" and old_offset != detected.get("uv0_offset")
        if old_mismatch:
            old_mismatch_count += 1

        status_counts[str(detected.get("status"))] += 1
        layout_counts[str(detected.get("layout"))] += 1
        checked.append(
            {
                "full_path": row.get("full_path", ""),
                "object_name": row.get("object_name", ""),
                "package": row.get("package", ""),
                "vertex_count": int(row.get("vertex_count") or 0),
                "index_count": int(row.get("index_count") or 0),
                "static_item_size": item_size,
                "static_item_count": item_count,
                "data_rel": int(static_vertex.get("data_rel") or 0),
                "old_heuristic_uv0_offset": old_offset,
                "old_heuristic_would_misread": old_mismatch,
                **detected,
            }
        )

    failures = [
        row
        for row in checked
        if row["status"] not in {"repo_verified"} and not args.allow_legacy_unverified
    ]
    proof = {
        "clean_csv": str(Path(args.clean_csv)),
        "decompressed_dir": str(package_dir),
        "policy": "Every bulk StaticMesh export must pass UE3 StaticMesh UV stream metadata detection before blend creation.",
        "repo_evidence": [
            "UEViewer UnMesh3.cpp FStaticMeshUVStream3 reads stream metadata before BulkSerialize UV item payload.",
            "CUE4Parse FStaticMeshVertexBuffer/FStaticMeshUVItem uses metadata-driven texcoord serialization; fixed offsets are unsafe.",
        ],
        "summary": {
            "checked_bulk_staticmesh_rows": len(checked),
            "status_counts": dict(sorted(status_counts.items())),
            "layout_counts": dict(sorted(layout_counts.items())),
            "old_heuristic_would_misread_rows": old_mismatch_count,
            "skipped": dict(sorted(skipped.items())),
            "packages_read": sorted(package_cache.keys()),
            "failure_count": len(failures),
            "status": "pass" if not failures else "fail",
        },
        "failure_samples": failures[:50],
        "old_heuristic_misread_samples": [row for row in checked if row.get("old_heuristic_would_misread")][:50],
        "rows": checked,
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
