#!/usr/bin/env python3
"""Generic heavy parse wrapper for Gears of War Reloaded cooked .war maps.

This reuses the proven Reloaded parser functions from the FactoryInterior
research tool, but writes target-specific output names so MP maps are not
mislabeled as campaign packages.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_heavy", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load source tool: {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_heavy"] = module
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


def write_outputs(src: Any, args: argparse.Namespace, packages: list[Path]) -> dict[str, Any]:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = sanitize_prefix(args.prefix or f"gowreloaded_{Path(packages[0]).stem}")

    inventory_rows = [
        {
            "package": p.name,
            "path": str(p),
            "size": p.stat().st_size,
            "last_write_time": p.stat().st_mtime,
            "role": src.package_role(p),
            "parse_scope": "full_parse",
        }
        for p in packages
    ]

    summaries: list[dict[str, Any]] = []
    class_counts: list[dict[str, Any]] = []
    geometry_candidates: list[dict[str, Any]] = []
    static_mesh_payloads: list[dict[str, Any]] = []
    static_mesh_geometry_probes: list[dict[str, Any]] = []
    bsp_model_payloads: list[dict[str, Any]] = []
    actor_transform_refs: list[dict[str, Any]] = []
    visual_refs: list[dict[str, Any]] = []
    theme_hits: list[dict[str, Any]] = []
    property_samples: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for package_path in packages:
        try:
            package_out = src.process_package(
                package_path,
                int(args.max_staticmesh_scan_bytes),
                int(args.max_property_samples_per_package),
            )
            summaries.append(package_out.summary)
            class_counts.extend(package_out.class_counts)
            geometry_candidates.extend(package_out.geometry_candidates)
            static_mesh_payloads.extend(package_out.static_mesh_payloads)
            static_mesh_geometry_probes.extend(package_out.static_mesh_geometry_probes)
            bsp_model_payloads.extend(package_out.bsp_model_payloads)
            actor_transform_refs.extend(package_out.actor_transform_refs)
            visual_refs.extend(package_out.visual_refs)
            theme_hits.extend(package_out.theme_hits)
            property_samples.extend(package_out.property_samples)
            issues.extend(package_out.issues)
            print(
                f"parsed {package_path.name}: exports={package_out.summary['exports']} "
                f"staticmesh={package_out.summary['static_mesh_count']} model={package_out.summary['model_count']}"
            )
        except Exception as exc:  # noqa: BLE001
            issue = {"package": package_path.name, "error": str(exc)}
            issues.append(issue)
            print(f"FAILED {package_path.name}: {exc}")

    totals = {
        "packages_inventory_total": len(inventory_rows),
        "packages_full_parse_attempted": len(packages),
        "packages_full_parse_resolved": len(summaries),
        "packages_failed": len([row for row in issues if "error" in row]),
        "names": sum(row["names"] for row in summaries),
        "imports": sum(row["imports"] for row in summaries),
        "exports": sum(row["exports"] for row in summaries),
        "compressed_groups": sum(row["compressed_group_count"] for row in summaries),
        "compressed_chunks": sum(row["compressed_chunk_count"] for row in summaries),
        "geometry_candidates": len(geometry_candidates),
        "visual_references": len(visual_refs),
        "static_mesh_exports": len(static_mesh_payloads),
        "static_mesh_geometry_probes": len(static_mesh_geometry_probes),
        "static_mesh_position_and_index_found": len(
            [row for row in static_mesh_geometry_probes if row["status"] == "position_and_index_found"]
        ),
        "static_mesh_position_only": len([row for row in static_mesh_geometry_probes if row["status"] == "position_only"]),
        "bsp_model_exports": len(bsp_model_payloads),
        "bsp_model_landmarks_decoded": len([row for row in bsp_model_payloads if row["decode_status"] == "bsp_landmarks_decoded"]),
        "actor_transform_reference_rows": len(actor_transform_refs),
        "theme_hits": len(theme_hits),
    }

    report_files = {
        "package_inventory": f"{prefix}_package_inventory.csv",
        "export_resolution_packages": f"{prefix}_export_resolution_packages.csv",
        "export_classes": f"{prefix}_export_classes.csv",
        "geometry_candidates": f"{prefix}_geometry_candidates.csv",
        "static_mesh_payloads": f"{prefix}_static_mesh_payloads.csv",
        "static_mesh_geometry_probe": f"{prefix}_static_mesh_geometry_probe.csv",
        "bsp_model_payloads": f"{prefix}_bsp_model_payloads.csv",
        "actor_transform_property_refs": f"{prefix}_actor_transform_property_refs.csv",
        "visual_reference_exports": f"{prefix}_visual_reference_exports.csv",
        "theme_reference_hits": f"{prefix}_theme_reference_hits.csv",
        "property_samples": f"{prefix}_property_samples.json",
        "decode_issues": f"{prefix}_decode_issues.csv",
        "manifest": f"{prefix}_heavy_parse_manifest.json",
    }

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "scope": args.scope,
        "packages": [str(p) for p in packages],
        "out_dir": str(out_dir),
        "totals": totals,
        "package_summaries": summaries,
        "issues": issues,
        "report_files": report_files,
        "source_parser": str(SOURCE_TOOL),
    }

    (out_dir / report_files["manifest"]).write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    src.write_csv(out_dir / report_files["package_inventory"], inventory_rows, ["package", "path", "size", "last_write_time", "role", "parse_scope"])
    src.write_csv(
        out_dir / report_files["export_resolution_packages"],
        summaries,
        [
            "package",
            "path",
            "size",
            "sha1",
            "compression_mode",
            "virtual_size",
            "compressed_group_count",
            "compressed_chunk_count",
            "names",
            "imports",
            "exports",
            "geometry_candidate_count",
            "visual_reference_count",
            "static_mesh_count",
            "static_mesh_actor_count",
            "static_mesh_component_count",
            "model_count",
            "polys_count",
        ],
    )
    src.write_csv(out_dir / report_files["export_classes"], class_counts, ["package", "class_name", "count"])
    src.write_csv(out_dir / report_files["geometry_candidates"], geometry_candidates, ["package", "export_index", "class_name", "object_name", "full_path", "serial_offset", "serial_size", "table_offset"])
    src.write_csv(
        out_dir / report_files["static_mesh_payloads"],
        static_mesh_payloads,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_start_rel",
            "property_end_rel",
            "property_ok",
            "property_error",
            "property_count",
            "source_file_path",
            "lightmap_coordinate_index",
            "lightmap_resolution",
            "native_payload_bytes",
            "bounds_plausible",
            "bounds_json",
            "object_refs_json",
        ],
    )
    src.write_csv(
        out_dir / report_files["static_mesh_geometry_probe"],
        static_mesh_geometry_probes,
        ["package", "export_index", "object_name", "full_path", "serial_size", "status", "vertex_count", "triangle_count", "position_buffer_json", "static_vertex_buffer_json", "index_buffer_json", "notes"],
    )
    src.write_csv(
        out_dir / report_files["bsp_model_payloads"],
        bsp_model_payloads,
        [
            "package",
            "export_index",
            "object_name",
            "full_path",
            "serial_offset",
            "serial_size",
            "property_start_rel",
            "property_end_rel",
            "property_ok",
            "property_error",
            "net_index",
            "bounds_json",
            "vectors_json",
            "points_json",
            "nodes_json",
            "surfs_owner_ref",
            "surfs_owner_path",
            "surfs_count",
            "decode_status",
        ],
    )
    src.write_csv(
        out_dir / report_files["actor_transform_property_refs"],
        actor_transform_refs,
        ["package", "export_index", "class_name", "object_name", "full_path", "property_start_rel", "property_end_rel", "property_ok", "key_properties_json", "object_refs_json"],
    )
    src.write_csv(out_dir / report_files["visual_reference_exports"], visual_refs, ["package", "export_index", "class_name", "object_name", "full_path", "serial_size"])
    src.write_csv(out_dir / report_files["theme_reference_hits"], theme_hits, ["package", "source", "index", "class_name", "path", "matched_text"])
    (out_dir / report_files["property_samples"]).write_text(json.dumps(property_samples, indent=2, ensure_ascii=True), encoding="utf-8")
    src.write_csv(out_dir / report_files["decode_issues"], issues, ["package", "error"])
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-file", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    parser.add_argument("--scope", default="Heavy package/native payload parse for a specific Reloaded cooked map. No .blend is emitted.")
    parser.add_argument("--max-staticmesh-scan-bytes", type=int, default=12_000_000)
    parser.add_argument("--max-property-samples-per-package", type=int, default=220)
    args = parser.parse_args()

    src = load_source()
    packages = [Path(p) for p in args.map_file]
    missing = [str(p) for p in packages if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing map package(s): {missing}")
    manifest = write_outputs(src, args, packages)
    print(json.dumps(manifest["totals"], indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
