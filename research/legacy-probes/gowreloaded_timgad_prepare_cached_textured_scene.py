from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_prepare_textured_blend_export.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_textured_prepare", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load source tool: {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_textured_prepare"] = module
    spec.loader.exec_module(module)
    return module


src = load_source()


def classify_timgad_bsp_model(row: dict[str, str], include_volumes: bool) -> tuple[str, str]:
    classification, reason = src.classify_bsp_model(row, include_volumes)
    if classification == "excluded" and reason == "status=bsp_model_faces_decoded_zero_bounds":
        full_path = row.get("full_path", "")
        try:
            triangles = int(row.get("triangle_count") or 0)
        except ValueError:
            triangles = 0
        if ".PersistentLevel.Model_" in full_path and triangles > 0:
            return "visible_candidate", "timgad_persistent_model_zero_bounds"
    return classification, reason

def read_existing_texture_exports(material_cache_dir: Path) -> list[dict[str, str]]:
    path = material_cache_dir / "gowreloaded_sp_factorybasement_material_texture_export_manifest.csv"
    return src.read_csv(path) if path.exists() else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare cached textured Timgad scene manifest without recomputing DDS bindings.")
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--clean-dir", required=True)
    parser.add_argument("--bsp-dir", required=True)
    parser.add_argument("--section-cache", required=True)
    parser.add_argument("--material-texture-cache", required=True)
    parser.add_argument("--material-cache-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--blend-out", required=True)
    parser.add_argument("--target", default="SP_Timgad_A_Chapter_01_IMPASSE")
    parser.add_argument("--chapter-display-name", default="IMPASSE")
    parser.add_argument("--chapter-provider", default="Timgad-Chap1 UIDataProvider_WarfareMaps")
    parser.add_argument("--chapter-enum-start", default="eCHAPTER_Timgad_Impasse")
    parser.add_argument(
        "--source-scope",
        default="SP_Timgad A package family only; SP_Timgad_B/Jurassic and SP_Station are excluded from this pilot.",
    )
    parser.add_argument("--limitation", action="append", default=[])
    parser.add_argument("--manifest-name", default="gowreloaded_sp_timgad_a_impasse_native_textured_scene_manifest.json")
    parser.add_argument("--unit-scale", type=float, default=src.DEFAULT_UNIT_SCALE)
    parser.add_argument("--include-bsp-volumes", action="store_true")
    parser.add_argument("--no-flip-v", dest="flip_v", action="store_false")
    parser.set_defaults(flip_v=True)
    args = parser.parse_args()

    out_dir = Path(args.out)
    static_obj_dir = out_dir / "staticmesh_asset_objs_uv"
    out_dir.mkdir(parents=True, exist_ok=True)
    static_obj_dir.mkdir(parents=True, exist_ok=True)

    asset_csv = Path(args.clean_dir) / "gowreloaded_sp_factoryinterior_staticmesh_clean_extract_manifest.csv"
    placement_csv = Path(args.clean_dir) / "gowreloaded_sp_factoryinterior_staticmesh_placement_manifest.csv"
    bsp_csv = Path(args.bsp_dir) / "gowreloaded_sp_factoryinterior_bsp_model_faces_manifest.csv"
    bsp_obj_csv = Path(args.bsp_dir) / "gowreloaded_sp_factoryinterior_bsp_sample_objs.csv"

    section_cache = src.read_json_file(Path(args.section_cache), {})
    material_texture_cache = src.read_json_file(Path(args.material_texture_cache), {})
    texture_export_rows = read_existing_texture_exports(Path(args.material_cache_dir))

    asset_rows = src.read_csv(asset_csv)
    placement_rows = src.read_csv(placement_csv)
    bsp_rows = src.read_csv(bsp_csv)
    bsp_obj_rows = src.read_csv(bsp_obj_csv)

    assets_by_path = {row["full_path"].lower(): row for row in asset_rows}
    assets_by_object_name: dict[str, list[dict[str, str]]] = {}
    for asset_row in asset_rows:
        assets_by_object_name.setdefault(asset_row.get("object_name", "").lower(), []).append(asset_row)

    used_paths = {row["static_mesh_path"] for row in placement_rows if row.get("static_mesh_path")}
    package_cache: dict[str, bytes] = {}
    assets: list[dict[str, Any]] = []
    missing_assets: list[str] = []
    asset_alias_rows: list[dict[str, str]] = []

    for mesh_path in sorted(used_paths, key=str.lower):
        asset = assets_by_path.get(mesh_path.lower())
        asset_alias_source = ""
        if not asset:
            object_name = mesh_path.rsplit(".", 1)[-1].lower()
            candidates = assets_by_object_name.get(object_name, [])
            if len(candidates) == 1:
                asset = candidates[0]
                asset_alias_source = asset["full_path"]
                asset_alias_rows.append(
                    {
                        "requested_path": mesh_path,
                        "resolved_native_path": asset_alias_source,
                        "reason": "unique_object_name_match",
                    }
                )
        if not asset:
            missing_assets.append(mesh_path)
            continue

        out_path = static_obj_dir / src.asset_filename(mesh_path)
        virt = src.package_virtual_bytes(Path(args.map_dir), asset["package"], package_cache)
        if asset["extract_status"] == "bulk_position_index":
            detail = src.write_bulk_staticmesh_obj(virt, asset, out_path, bool(args.flip_v))
        elif asset["extract_status"] == "inline_staticmesh_stream":
            detail = src.write_inline_staticmesh_obj(virt, asset, out_path)
        else:
            raise RuntimeError(f"unsupported StaticMesh status {asset['extract_status']} for {mesh_path}")

        section_entry = section_cache.get(mesh_path.lower()) or section_cache.get(asset["full_path"].lower()) or {}
        sections: list[dict[str, Any]] = []
        for raw_section in section_entry.get("sections") or []:
            section = dict(raw_section)
            material_path = str(section.get("material_path") or "")
            material_binding = material_texture_cache.get(material_path.lower())
            if material_binding:
                section["material_texture_binding"] = material_binding
            sections.append(section)

        assets.append(
            {
                "full_path": mesh_path,
                "package": asset["package"],
                "export_index": int(asset["export_index"]),
                "object_name": asset["object_name"],
                "extract_status": asset["extract_status"],
                "obj_path": str(out_path),
                "source_file_path": asset.get("source_file_path", ""),
                "bounds_json": asset.get("bounds_json", ""),
                "asset_alias_source": asset_alias_source,
                "section_status": section_entry.get("status", "section_cache_missing"),
                "section_layout": section_entry.get("layout_name", ""),
                "sections": sections,
                "texture_binding": {},
                **detail,
            }
        )
        if len(assets) % 100 == 0:
            print(f"prepared Timgad static mesh assets: {len(assets)} / {len(used_paths)}")

    placements: list[dict[str, Any]] = []
    skipped_null_placements: list[dict[str, Any]] = []
    for ordinal, row in enumerate(placement_rows):
        mesh_path = row.get("static_mesh_path", "")
        if not mesh_path:
            skipped_null_placements.append({"ordinal": ordinal, "package": row["package"], "actor_path": row["actor_path"]})
            continue
        component_scale = src.effective_component_scale(row)
        component_scale_applied = src.scale_is_nondefault(component_scale)
        if row.get("matrix_json"):
            matrix_values = [float(v) for v in src.parse_json_field(row["matrix_json"], [])]
            matrix_values = src.apply_component_scale_to_unreal_row_major(matrix_values, component_scale)
            matrix_blender = src.blender_matrix_from_unreal_row_major(matrix_values, float(args.unit_scale))
            transform_source = "decoded_collection_actor_matrix64_component_scale" if component_scale_applied else "decoded_collection_actor_matrix64"
        else:
            transform = src.parse_json_field(row.get("transform_json", ""), {})
            matrix_values = src.unreal_rotator_row_major_matrix(transform)
            matrix_values = src.apply_component_scale_to_unreal_row_major(matrix_values, component_scale)
            matrix_blender = src.blender_matrix_from_unreal_row_major(matrix_values, float(args.unit_scale))
            transform_source = "decoded_static_mesh_actor_rotator_component_scale" if component_scale_applied else "decoded_static_mesh_actor_rotator"
        placements.append(
            {
                "ordinal": ordinal,
                "package": row["package"],
                "placement_kind": row["placement_kind"],
                "actor_export_index": row["actor_export_index"],
                "actor_name": row["actor_name"],
                "actor_path": row["actor_path"],
                "component_ref": row["component_ref"],
                "component_path": row["component_path"],
                "static_mesh_path": mesh_path,
                "materials_json": row.get("materials_json", ""),
                "component_scale3d": component_scale,
                "component_scale_source": row.get("component_scale_source", "default"),
                "component_scale_applied": component_scale_applied,
                "matrix_blender": matrix_blender,
                "transform_source": transform_source,
            }
        )

    bsp_obj_by_key = {
        (row["package"], row["export_index"], row["object_name"]): row["obj_path"]
        for row in bsp_obj_rows
        if row.get("obj_path")
    }
    bsp_models: list[dict[str, Any]] = []
    excluded_bsp_models: list[dict[str, Any]] = []
    bsp_filter_counts: Counter[str] = Counter()
    for row in bsp_rows:
        classification, filter_reason = classify_timgad_bsp_model(row, bool(args.include_bsp_volumes))
        bsp_filter_counts[f"{classification}:{filter_reason}"] += 1
        if classification not in {"visible_candidate", "included_volume"}:
            excluded_bsp_models.append(
                {
                    "package": row["package"],
                    "export_index": int(row["export_index"]),
                    "object_name": row["object_name"],
                    "full_path": row["full_path"],
                    "status": row["status"],
                    "filter_reason": filter_reason,
                }
            )
            continue
        key = (row["package"], row["export_index"], row["object_name"])
        obj_path = bsp_obj_by_key.get(key)
        if not obj_path:
            raise RuntimeError(f"missing BSP OBJ proof for {key}")
        bsp_models.append(
            {
                "package": row["package"],
                "export_index": int(row["export_index"]),
                "object_name": row["object_name"],
                "full_path": row["full_path"],
                "status": row["status"],
                "point_count": int(row["point_count"] or 0),
                "used_point_count": int(row.get("used_point_count") or 0),
                "triangle_count": int(row["triangle_count"] or 0),
                "obj_path": obj_path,
                "bounds_json": row.get("bounds_json", ""),
                "bsp_filter_classification": classification,
                "bsp_filter_reason": filter_reason,
                "coordinate_space": "ue_world_raw_obj_vertices",
            }
        )

    summary = {
        "staticmesh_assets_prepared": len(assets),
        "staticmesh_unique_used_paths": len(used_paths),
        "staticmesh_missing_assets": len(missing_assets),
        "staticmesh_alias_resolutions": len(asset_alias_rows),
        "staticmesh_placements": len(placements),
        "skipped_null_staticmesh_slots": len(skipped_null_placements),
        "bsp_input_models": len(bsp_rows),
        "bsp_models": len(bsp_models),
        "bsp_excluded_models": len(excluded_bsp_models),
        "bsp_filter_counts": dict(sorted(bsp_filter_counts.items())),
        "texture_exports": len(texture_export_rows),
        "dds_textures_exported": sum(1 for row in texture_export_rows if row.get("status") == "dds_exported"),
        "material_texture_bindings": len(material_texture_cache),
        "uv_decoded_assets": sum(1 for asset in assets if asset.get("uv_status") == "uv0_decoded_from_static_vertex_buffer"),
        "staticmesh_section_decoded_assets": sum(1 for asset in assets if asset.get("section_status") == "sections_decoded"),
        "staticmesh_section_rows": sum(len(asset.get("sections") or []) for asset in assets),
        "section_material_texture_bound_rows": sum(
            1
            for asset in assets
            for section in (asset.get("sections") or [])
            if section.get("material_texture_binding", {}).get("roles", {}).get("diffuse")
        ),
    }

    limitations = args.limitation or [
        "This is the first source-native Timgad A pilot export for IMPASSE; SP_Timgad_B/Jurassic is intentionally excluded.",
        "StaticMesh geometry, UV0, material sections, object overrides, DDS material references, and placement matrices are decoded from source package data.",
        "BSP geometry imports decoded native Model faces; BSP material texture binding remains pending.",
        "Chapter splitting inside SP_Timgad A still needs tighter Kismet-streaming cuts before this can be called a pure one-chapter-only export.",
    ]

    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "chapter_display_name": args.chapter_display_name,
        "chapter_provider": args.chapter_provider,
        "chapter_enum_start": args.chapter_enum_start,
        "source_scope": args.source_scope,
        "map_dir": str(args.map_dir),
        "out_dir": str(out_dir),
        "blend_path": str(Path(args.blend_out)),
        "unit_scale": float(args.unit_scale),
        "flip_v": bool(args.flip_v),
        "section_cache": str(Path(args.section_cache)),
        "material_texture_cache": str(Path(args.material_texture_cache)),
        "material_texture_bindings": material_texture_cache,
        "coordinate_system": {
            "staticmesh_obj_vertices": "raw_ue_local_coordinates",
            "staticmesh_object_matrix": "ue_local_to_blender_world_swizzled_scaled",
            "bsp_obj_vertices": "raw_ue_world_coordinates_imported_with_swizzle_scale",
            "ue_to_blender_point": "(x,y,z)_UE_cm -> (y*unit_scale, -x*unit_scale, z*unit_scale)_Blender",
        },
        "assets": assets,
        "placements": placements,
        "skipped_null_placements": skipped_null_placements,
        "bsp_models": bsp_models,
        "excluded_bsp_models": excluded_bsp_models,
        "missing_assets": missing_assets,
        "asset_alias_resolutions": asset_alias_rows,
        "summary": summary,
        "limitations": limitations,
    }
    manifest_path = out_dir / args.manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"scene_manifest": str(manifest_path), **summary}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
