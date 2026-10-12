#!/usr/bin/env python3
"""Targeted actor/property probe for Reloaded cooked maps."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


HEAVY_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)


def load_heavy():
    spec = importlib.util.spec_from_file_location("gowr_heavy", HEAVY_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser: {HEAVY_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compact(value: Any, limit: int = 12000) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    parser.add_argument("--class-regex", default=r"WarWeaponPickupFactory|WarTeamPlayerStart|PlayerStart|WarWeapon")
    parser.add_argument("--max-tags", type=int, default=120)
    args = parser.parse_args()

    heavy = load_heavy()
    package = Path(args.map_file)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rx = re.compile(args.class_regex, re.IGNORECASE)

    virt, groups, compression_mode = heavy.rebuild_virtual_package(package.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for row in exports:
        row["class_name"] = ref_short_name(row["class_ref"])
        row["outer_path"] = ref_path(row["outer_ref"])
        row["full_path"] = ref_path(row["index"])

    rows: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for row in exports:
        if row["serial_size"] <= 0 or not rx.search(row["class_name"]):
            continue
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4])
        result = scan["result"]
        tags = result.get("tags", []) if result.get("ok") else []
        key_tags = heavy.collect_key_tags(tags)
        object_refs = heavy.property_object_refs(tags)
        rows.append(
            {
                "package": package.name,
                "export_index": row["index"],
                "class_name": row["class_name"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "property_start_rel": scan.get("start_rel", ""),
                "property_end_rel": result.get("end_rel", ""),
                "property_ok": result.get("ok", False),
                "property_error": result.get("error", ""),
                "property_count": len([tag for tag in tags if tag.get("name") != "None"]),
                "key_properties_json": compact(key_tags, 4000),
                "object_refs_json": compact(object_refs[:96], 4000),
            }
        )
        samples.append(
            {
                "package": package.name,
                "export_index": row["index"],
                "class_name": row["class_name"],
                "full_path": row["full_path"],
                "tags": tags[: int(args.max_tags)],
            }
        )

    class_counts: dict[str, int] = {}
    for row in rows:
        class_counts[row["class_name"]] = class_counts.get(row["class_name"], 0) + 1

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "package": str(package),
        "compression_mode": compression_mode,
        "compressed_groups": len(groups),
        "class_regex": args.class_regex,
        "rows": len(rows),
        "class_counts": dict(sorted(class_counts.items())),
        "source_tool": str(HEAVY_TOOL),
    }
    manifest_path = out_dir / f"{args.prefix}_actor_property_probe_manifest.json"
    csv_path = out_dir / f"{args.prefix}_actor_property_probe.csv"
    sample_path = out_dir / f"{args.prefix}_actor_property_probe_samples.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    sample_path.write_text(json.dumps(samples, indent=2, ensure_ascii=True), encoding="utf-8")
    write_csv(
        csv_path,
        rows,
        [
            "package",
            "export_index",
            "class_name",
            "object_name",
            "full_path",
            "property_start_rel",
            "property_end_rel",
            "property_ok",
            "property_error",
            "property_count",
            "key_properties_json",
            "object_refs_json",
        ],
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
