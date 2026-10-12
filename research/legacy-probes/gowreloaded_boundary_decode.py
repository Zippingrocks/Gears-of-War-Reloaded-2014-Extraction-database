from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


def load_heavy(path: Path):
    spec = importlib.util.spec_from_file_location("gowr_heavy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_heavy"] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decode-only Gears Reloaded chapter/map boundary report.")
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--heavy-parser", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="gowreloaded_boundary")
    parser.add_argument("--package-regex", default=r".*\.war$")
    return parser.parse_args()


INTERESTING_CLASS_RE = re.compile(
    r"^(Seq|Sequence|Trigger|WarCheckpoint|LevelStreaming|Interp|Pawn|WarAI|WarPointOfInterest|WarWeapon|WarAmmo|"
    r"ActorFactory|SkeletalMesh|SkeletalMeshActor|SkeletalMeshComponent|WarVehicle|WarVWeap|DynamicBlockingVolume|"
    r"BlockingVolume|KryllVolume|CoverLink)",
    re.IGNORECASE,
)

INTERESTING_TEXT_RE = re.compile(
    r"brumak|viaduct|bridge|gas|station|jurassic|chapter|complete|checkpoint|start|end|stream|level|load|unload|"
    r"cin|cine|matinee|truck|tanker|tank|boom|destroy|kill|hammer|breaker|remote|objective|troika|train|powderkeg|"
    r"tomb|queen|raven|corpser|kryll",
    re.IGNORECASE,
)


def compact(value: Any, limit: int = 6000) -> str:
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
    args = parse_args()
    heavy = load_heavy(Path(args.heavy_parser))
    map_dir = Path(args.map_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    package_re = re.compile(args.package_regex, re.IGNORECASE)

    packages = sorted(p for p in map_dir.glob("*.war") if package_re.search(p.name))
    export_rows: list[dict[str, Any]] = []
    property_rows: list[dict[str, Any]] = []
    name_hits: list[dict[str, Any]] = []
    import_hits: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []

    for package in packages:
        data = package.read_bytes()
        virt, groups, compression_mode = heavy.rebuild_virtual_package(data)
        names = heavy.read_names(virt)
        imports = heavy.read_imports(virt, names)
        exports = heavy.read_exports(virt, names, imports)
        ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
        for row in exports:
            row["class_name"] = ref_short_name(row["class_ref"])
            row["outer_path"] = ref_path(row["outer_ref"])
            row["full_path"] = ref_path(row["index"])

        for idx, name in enumerate(names):
            if INTERESTING_TEXT_RE.search(name):
                name_hits.append({"package": package.name, "name_index": idx, "name": name})

        for imp in imports:
            text = f"{imp.get('class_name','')} {imp.get('object_short_name','')} {ref_path(imp['index'])}"
            if INTERESTING_TEXT_RE.search(text):
                import_hits.append(
                    {
                        "package": package.name,
                        "import_index": imp["index"],
                        "class_name": imp.get("class_name", ""),
                        "object_name": imp.get("object_short_name", ""),
                        "path": ref_path(imp["index"]),
                    }
                )

        package_export_start = len(export_rows)
        package_property_start = len(property_rows)
        for row in exports:
            text = f"{row['class_name']} {row['object_short_name']} {row['full_path']}"
            class_interesting = bool(INTERESTING_CLASS_RE.search(row["class_name"]))
            text_interesting = bool(INTERESTING_TEXT_RE.search(text))
            if not (class_interesting or text_interesting):
                continue
            export_rows.append(
                {
                    "package": package.name,
                    "export_index": row["index"],
                    "class_name": row["class_name"],
                    "object_name": row["object_short_name"],
                    "outer_path": row.get("outer_path", ""),
                    "full_path": row["full_path"],
                    "serial_offset": row["serial_offset"],
                    "serial_size": row["serial_size"],
                    "reason": ("class" if class_interesting else "") + (";text" if text_interesting else ""),
                }
            )
            if row["serial_size"] <= 0:
                continue
            try:
                scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4])
            except Exception as exc:  # noqa: BLE001
                property_rows.append(
                    {
                        "package": package.name,
                        "export_index": row["index"],
                        "class_name": row["class_name"],
                        "object_name": row["object_short_name"],
                        "full_path": row["full_path"],
                        "property_ok": False,
                        "property_error": str(exc),
                        "tag_count": 0,
                        "key_tags_json": "{}",
                        "object_refs_json": "[]",
                        "all_tags_json": "[]",
                        "search_text": "",
                    }
                )
                continue
            tags = scan["result"].get("tags", [])
            key_tags = heavy.collect_key_tags(tags)
            object_refs = heavy.property_object_refs(tags)
            search_text = heavy.property_search_text(tags)
            property_rows.append(
                {
                    "package": package.name,
                    "export_index": row["index"],
                    "class_name": row["class_name"],
                    "object_name": row["object_short_name"],
                    "full_path": row["full_path"],
                    "property_start_rel": scan.get("start_rel", ""),
                    "property_end_rel": scan["result"].get("end_rel", ""),
                    "property_ok": bool(scan["result"].get("ok")),
                    "property_error": scan["result"].get("error", ""),
                    "tag_count": len([tag for tag in tags if tag.get("name") != "None"]),
                    "key_tags_json": compact(key_tags, 4000),
                    "object_refs_json": compact(object_refs[:128], 5000),
                    "all_tags_json": compact(tags[:160], 16000),
                    "search_text": search_text[:2400],
                }
            )

        summary.append(
            {
                "package": package.name,
                "compression_mode": compression_mode,
                "compressed_groups": len(groups),
                "compressed_chunks": sum(group["chunk_count"] for group in groups),
                "names": len(names),
                "imports": len(imports),
                "exports": len(exports),
                "interesting_exports": len(export_rows) - package_export_start,
                "interesting_properties": len(property_rows) - package_property_start,
            }
        )
        print(f"decoded {package.name}: exports={len(exports)} interesting={summary[-1]['interesting_exports']}")

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.label).strip("_") or "gowreloaded_boundary"
    write_csv(
        out_dir / f"{stem}_interesting_exports.csv",
        export_rows,
        [
            "package",
            "export_index",
            "class_name",
            "object_name",
            "outer_path",
            "full_path",
            "serial_offset",
            "serial_size",
            "reason",
        ],
    )
    write_csv(
        out_dir / f"{stem}_interesting_properties.csv",
        property_rows,
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
            "tag_count",
            "key_tags_json",
            "object_refs_json",
            "all_tags_json",
            "search_text",
        ],
    )
    write_csv(out_dir / f"{stem}_name_hits.csv", name_hits, ["package", "name_index", "name"])
    write_csv(
        out_dir / f"{stem}_import_hits.csv",
        import_hits,
        ["package", "import_index", "class_name", "object_name", "path"],
    )
    (out_dir / f"{stem}_summary.json").write_text(
        json.dumps({"packages": summary, "name_hits": len(name_hits), "import_hits": len(import_hits)}, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "packages": len(packages),
                "interesting_exports": len(export_rows),
                "interesting_properties": len(property_rows),
                "out_dir": str(out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
