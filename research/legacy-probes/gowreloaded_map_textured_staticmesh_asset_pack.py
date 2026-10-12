#!/usr/bin/env python3
"""Build standalone textured StaticMesh OBJ/MTL packs from Reloaded map caches.

This is a packaging and audit layer. It expects native geometry, UV0, StaticMesh
section records, actor/component material overrides, and Texture2D DDS payloads
to already be decoded by the map-specific Reloaded extraction passes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def norm_key(value: str | None) -> str:
    return (value or "").strip().lower()


def hash_text(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def safe_name(value: str, fallback: str = "unnamed") -> str:
    stem = value.rsplit(".", 1)[-1] if value else fallback
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return stem or fallback


def relpath_for_mtl(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(path, start).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def parse_materials_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    paths = data.get("object_ref_paths_sample") or data.get("object_ref_paths") or []
    return [str(path) for path in paths if path]


def texture_role(binding: dict[str, Any], role: str) -> dict[str, Any]:
    roles = binding.get("roles") or {}
    value = roles.get(role) or {}
    return value if isinstance(value, dict) else {}


def binding_has_role(binding: dict[str, Any], role: str) -> bool:
    return bool(texture_role(binding, role).get("dds_path"))


def resolve_binding(material_path: str, material_cache: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    cache_binding = material_cache.get(norm_key(material_path), {})
    if cache_binding:
        return cache_binding
    embedded = section.get("material_texture_binding")
    if isinstance(embedded, dict) and embedded:
        return embedded
    return {}


def build_section_ranges(asset: dict[str, Any]) -> list[dict[str, Any]]:
    sections = asset.get("sections") or []
    ranges: list[dict[str, Any]] = []
    for section in sections:
        try:
            start = int(section.get("triangle_start") or (int(section.get("first_index") or 0) // 3))
            count = int(section.get("num_triangles") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        ranges.append(
            {
                "start": start,
                "end": start + count,
                "section": section,
                "section_index": int(section.get("section_index") or len(ranges)),
            }
        )
    ranges.sort(key=lambda item: (item["start"], item["section_index"]))
    return ranges


def material_name_for(asset: dict[str, Any], section: dict[str, Any]) -> str:
    material_path = str(section.get("material_path") or "unbound_material")
    section_index = section.get("section_index", "x")
    return f"{safe_name(asset.get('object_name') or asset.get('full_path'), 'StaticMesh')}_s{section_index}_{safe_name(material_path, 'mat')}_{hash_text(material_path, 8)}"


def link_texture(
    source_path: str,
    role: str,
    texture_dir: Path,
    link_rows: list[dict[str, Any]],
) -> tuple[str, str]:
    if not source_path:
        return "", "missing"

    src = Path(source_path)
    if not src.exists():
        link_rows.append(
            {
                "source_path": source_path,
                "linked_path": "",
                "role": role,
                "status": "source_missing",
            }
        )
        return source_path.replace("\\", "/"), "source_missing"

    texture_dir.mkdir(parents=True, exist_ok=True)
    dest = texture_dir / src.name
    status = "existing"
    if not dest.exists():
        try:
            os.link(src, dest)
            status = "hardlinked"
        except OSError as exc:
            link_rows.append(
                {
                    "source_path": str(src),
                    "linked_path": "",
                    "role": role,
                    "status": f"hardlink_failed:{type(exc).__name__}",
                }
            )
            return str(src).replace("\\", "/"), f"hardlink_failed:{type(exc).__name__}"

    link_rows.append(
        {
            "source_path": str(src),
            "linked_path": str(dest),
            "role": role,
            "status": status,
        }
    )
    return str(dest), status


def write_mtl(
    asset: dict[str, Any],
    asset_materials: list[dict[str, Any]],
    mtl_path: Path,
    texture_dir: Path,
    link_rows: list[dict[str, Any]],
) -> None:
    lines: list[str] = [
        f"# Reloaded textured StaticMesh material pack",
        f"# source_asset={asset.get('full_path', '')}",
        f"# object_name={asset.get('object_name', '')}",
        "",
    ]

    seen_links: set[tuple[str, str]] = set()
    for material in asset_materials:
        binding = material["binding"]
        roles = binding.get("roles") or {}
        diffuse = texture_role(binding, "diffuse")
        normal = texture_role(binding, "normal")
        specular = texture_role(binding, "specular")
        emissive = texture_role(binding, "emissive")
        alpha = texture_role(binding, "alpha")

        lines.extend(
            [
                f"newmtl {material['mtl_name']}",
                f"# material_path={material['material_path']}",
                f"# binding_status={binding.get('binding_status', 'unbound') if binding else 'unbound'}",
                "Ka 0.000000 0.000000 0.000000",
                "Kd 1.000000 1.000000 1.000000",
                "Ks 0.250000 0.250000 0.250000",
                "Ns 32.000000",
                "illum 2",
            ]
        )

        role_values = [
            ("diffuse", diffuse, "map_Kd"),
            ("specular", specular, "map_Ks"),
            ("normal", normal, "map_Bump"),
            ("emissive", emissive, "map_Ke"),
            ("alpha", alpha, "map_d"),
        ]
        for role, tex, mtl_token in role_values:
            dds_path = str(tex.get("dds_path") or "")
            if not dds_path:
                continue
            key = (role, dds_path.lower())
            linked_path, _status = link_texture(dds_path, role, texture_dir, link_rows)
            if key in seen_links and Path(linked_path).is_absolute():
                pass
            seen_links.add(key)
            map_path = relpath_for_mtl(Path(linked_path), mtl_path.parent) if linked_path else ""
            if map_path:
                lines.append(f"{mtl_token} {map_path}")

        if roles:
            lines.append(f"# decoded_roles={','.join(sorted(roles.keys()))}")
        lines.append("")

    mtl_path.write_text("\n".join(lines), encoding="utf-8")


def count_obj_features(obj_path: Path) -> dict[str, int]:
    counts = {"v": 0, "vt": 0, "vn": 0, "f": 0, "usemtl": 0, "mtllib": 0}
    if not obj_path.exists():
        return counts
    with obj_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                counts["v"] += 1
            elif line.startswith("vt "):
                counts["vt"] += 1
            elif line.startswith("vn "):
                counts["vn"] += 1
            elif line.startswith("f "):
                counts["f"] += 1
            elif line.startswith("usemtl "):
                counts["usemtl"] += 1
            elif line.startswith("mtllib "):
                counts["mtllib"] += 1
    return counts


def write_textured_obj(
    asset: dict[str, Any],
    source_obj: Path,
    out_obj: Path,
    mtl_name: str,
    section_ranges: list[dict[str, Any]],
    section_to_mtl: dict[int, str],
) -> dict[str, Any]:
    out_obj.parent.mkdir(parents=True, exist_ok=True)
    if not source_obj.exists():
        return {
            "obj_status": "source_obj_missing",
            "source_obj": str(source_obj),
            "out_obj": str(out_obj),
            "v": 0,
            "vt": 0,
            "vn": 0,
            "f": 0,
            "usemtl": 0,
        }

    active_range_index = -1
    face_index = 0
    usemtl_count = 0
    counts = {"v": 0, "vt": 0, "vn": 0, "f": 0}
    range_cursor = 0
    sorted_ranges = list(section_ranges)

    with source_obj.open("r", encoding="utf-8", errors="replace") as src, out_obj.open("w", encoding="utf-8", newline="\n") as dst:
        dst.write(f"# Reloaded textured StaticMesh OBJ pack\n")
        dst.write(f"# source_asset={asset.get('full_path', '')}\n")
        dst.write(f"# source_obj={source_obj}\n")
        dst.write(f"mtllib {mtl_name}\n")

        for line in src:
            if line.startswith("mtllib "):
                continue
            if line.startswith("usemtl "):
                continue
            if line.startswith("v "):
                counts["v"] += 1
            elif line.startswith("vt "):
                counts["vt"] += 1
            elif line.startswith("vn "):
                counts["vn"] += 1
            elif line.startswith("f "):
                while range_cursor + 1 < len(sorted_ranges) and face_index >= sorted_ranges[range_cursor]["end"]:
                    range_cursor += 1
                if sorted_ranges:
                    section_range = sorted_ranges[range_cursor]
                    if section_range["start"] <= face_index < section_range["end"]:
                        section_index = int(section_range["section_index"])
                    else:
                        section_index = int(sorted_ranges[0]["section_index"])
                else:
                    section_index = -1
                if section_index != active_range_index:
                    active_range_index = section_index
                    dst.write(f"usemtl {section_to_mtl.get(section_index, section_to_mtl.get(-1, 'unbound_material'))}\n")
                    usemtl_count += 1
                face_index += 1
                counts["f"] += 1
            dst.write(line)

    return {
        "obj_status": "textured_obj_written",
        "source_obj": str(source_obj),
        "out_obj": str(out_obj),
        "v": counts["v"],
        "vt": counts["vt"],
        "vn": counts["vn"],
        "f": counts["f"],
        "usemtl": usemtl_count,
    }


def build_asset_pack(
    scene_manifest: dict[str, Any],
    material_cache: dict[str, Any],
    out_dir: Path,
    prefix: str,
    target: str,
    write_obj: bool = True,
) -> dict[str, Any]:
    asset_out_dir = out_dir / "assets_obj_mtl"
    texture_dir = out_dir / "textures"
    proof_dir = out_dir / "proof"
    asset_out_dir.mkdir(parents=True, exist_ok=True)
    texture_dir.mkdir(parents=True, exist_ok=True)
    proof_dir.mkdir(parents=True, exist_ok=True)

    assets = scene_manifest.get("assets") or []
    placements = scene_manifest.get("placements") or []
    asset_by_path = {norm_key(asset.get("full_path")): asset for asset in assets}

    asset_rows: list[dict[str, Any]] = []
    asset_manifest: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    material_rows: list[dict[str, Any]] = []
    missing_material_paths: Counter[str] = Counter()
    stats = Counter()
    by_status: dict[str, Counter[str]] = defaultdict(Counter)

    for asset_index, asset in enumerate(assets):
        full_path = str(asset.get("full_path") or "")
        object_name = str(asset.get("object_name") or safe_name(full_path, "StaticMesh"))
        source_obj = Path(str(asset.get("obj_path") or ""))
        asset_hash = hash_text(full_path, 16)
        out_obj = asset_out_dir / f"{safe_name(object_name, 'StaticMesh')}__{asset_hash}.obj"
        out_mtl = asset_out_dir / f"{safe_name(object_name, 'StaticMesh')}__{asset_hash}.mtl"

        section_ranges = build_section_ranges(asset)
        asset_materials: list[dict[str, Any]] = []
        section_to_mtl: dict[int, str] = {}
        section_stats = Counter()

        for section_range in section_ranges:
            section = section_range["section"]
            section_index = int(section_range["section_index"])
            material_path = str(section.get("material_path") or "")
            binding = resolve_binding(material_path, material_cache, section)
            mtl_name = material_name_for(asset, section)
            section_to_mtl[section_index] = mtl_name

            if not binding:
                missing_material_paths[material_path or "(empty_material_path)"] += 1
                section_stats["unbound"] += 1
            if binding_has_role(binding, "diffuse"):
                section_stats["diffuse"] += 1
            if binding_has_role(binding, "normal"):
                section_stats["normal"] += 1
            if binding_has_role(binding, "specular"):
                section_stats["specular"] += 1
            if binding_has_role(binding, "emissive"):
                section_stats["emissive"] += 1

            material_rows.append(
                {
                    "asset_full_path": full_path,
                    "asset_object_name": object_name,
                    "section_index": section_index,
                    "triangle_start": section_range["start"],
                    "num_triangles": section_range["end"] - section_range["start"],
                    "material_path": material_path,
                    "binding_status": binding.get("binding_status", "unbound") if binding else "unbound",
                    "diffuse_dds": texture_role(binding, "diffuse").get("dds_path", "") if binding else "",
                    "normal_dds": texture_role(binding, "normal").get("dds_path", "") if binding else "",
                    "specular_dds": texture_role(binding, "specular").get("dds_path", "") if binding else "",
                    "emissive_dds": texture_role(binding, "emissive").get("dds_path", "") if binding else "",
                }
            )
            asset_materials.append(
                {
                    "section_index": section_index,
                    "material_path": material_path,
                    "mtl_name": mtl_name,
                    "binding": binding,
                }
            )

        if not section_to_mtl:
            section_to_mtl[-1] = f"{safe_name(object_name, 'StaticMesh')}_unbound"
            asset_materials.append(
                {
                    "section_index": -1,
                    "material_path": "",
                    "mtl_name": section_to_mtl[-1],
                    "binding": {},
                }
            )

        write_mtl(asset, asset_materials, out_mtl, texture_dir, link_rows)
        obj_counts = count_obj_features(source_obj)
        textured_counts = {}
        if write_obj:
            textured_counts = write_textured_obj(
                asset=asset,
                source_obj=source_obj,
                out_obj=out_obj,
                mtl_name=out_mtl.name,
                section_ranges=section_ranges,
                section_to_mtl=section_to_mtl,
            )

        face_count = int(asset.get("face_count") or obj_counts["f"] or textured_counts.get("f", 0) or 0)
        section_count = len(section_ranges)
        diffuse_sections = int(section_stats["diffuse"])
        all_sections_have_diffuse = bool(section_count and diffuse_sections == section_count)
        has_uv0 = "uv0" in str(asset.get("uv_status", "")).lower() or obj_counts["vt"] > 0
        has_source_obj = source_obj.exists()
        obj_status = textured_counts.get("obj_status", "obj_skipped")

        stats["assets_total"] += 1
        stats["sections_total"] += section_count
        stats["sections_with_diffuse"] += diffuse_sections
        stats["sections_with_normal"] += int(section_stats["normal"])
        stats["sections_with_specular"] += int(section_stats["specular"])
        stats["sections_with_emissive"] += int(section_stats["emissive"])
        stats["sections_unbound"] += int(section_stats["unbound"])
        stats["assets_with_source_obj"] += int(has_source_obj)
        stats["assets_with_uv0"] += int(has_uv0)
        stats["assets_with_sections"] += int(section_count > 0)
        stats["assets_all_sections_have_diffuse"] += int(all_sections_have_diffuse)
        stats["assets_textured_obj_written"] += int(obj_status == "textured_obj_written")
        by_status["extract_status"][str(asset.get("extract_status", ""))] += 1
        by_status["section_status"][str(asset.get("section_status", ""))] += 1
        by_status["uv_status"][str(asset.get("uv_status", ""))] += 1
        by_status["obj_status"][str(obj_status)] += 1

        asset_row = {
            "target": target,
            "asset_index": asset_index,
            "asset_full_path": full_path,
            "asset_object_name": object_name,
            "source_obj": str(source_obj),
            "out_obj": str(out_obj) if write_obj else "",
            "out_mtl": str(out_mtl),
            "extract_status": asset.get("extract_status", ""),
            "uv_status": asset.get("uv_status", ""),
            "section_status": asset.get("section_status", ""),
            "source_vertices": obj_counts["v"],
            "source_uvs": obj_counts["vt"],
            "source_normals": obj_counts["vn"],
            "source_faces": obj_counts["f"],
            "face_count_manifest": face_count,
            "section_count": section_count,
            "sections_with_diffuse": diffuse_sections,
            "sections_with_normal": int(section_stats["normal"]),
            "sections_with_specular": int(section_stats["specular"]),
            "sections_with_emissive": int(section_stats["emissive"]),
            "sections_unbound": int(section_stats["unbound"]),
            "all_sections_have_diffuse": all_sections_have_diffuse,
            "obj_status": obj_status,
            "written_usemtl_count": textured_counts.get("usemtl", 0),
        }
        asset_rows.append(asset_row)
        asset_manifest.append(
            {
                **asset_row,
                "sections": [
                    {
                        "section_index": item["section_index"],
                        "material_path": item["material_path"],
                        "mtl_name": item["mtl_name"],
                        "binding_status": item["binding"].get("binding_status", "unbound") if item["binding"] else "unbound",
                        "roles": sorted((item["binding"].get("roles") or {}).keys()) if item["binding"] else [],
                    }
                    for item in asset_materials
                ],
            }
        )

    placement_rows: list[dict[str, Any]] = []
    for placement_index, placement in enumerate(placements):
        mesh_path = str(placement.get("static_mesh_path") or "")
        asset = asset_by_path.get(norm_key(mesh_path))
        overrides = parse_materials_json(placement.get("materials_json"))
        sections = build_section_ranges(asset) if asset else []
        material_slots: list[tuple[int, str, str]] = []
        for section_range in sections:
            section = section_range["section"]
            section_index = int(section_range["section_index"])
            native_path = str(section.get("material_path") or "")
            override_path = overrides[section_index] if section_index < len(overrides) else ""
            effective_path = override_path or native_path
            material_slots.append((section_index, effective_path, "component_override" if override_path else "asset_section"))
        if not material_slots and overrides:
            material_slots = [(i, path, "component_override_no_section_cache") for i, path in enumerate(overrides)]

        diffuse_ok = 0
        slot_count = len(material_slots)
        unresolved_slots = 0
        slot_statuses: list[str] = []
        for _section_index, material_path, source in material_slots:
            binding = material_cache.get(norm_key(material_path), {})
            if not binding and asset:
                for section_range in sections:
                    section = section_range["section"]
                    if norm_key(section.get("material_path")) == norm_key(material_path):
                        binding = resolve_binding(material_path, material_cache, section)
                        break
            if binding_has_role(binding, "diffuse"):
                diffuse_ok += 1
            else:
                unresolved_slots += 1
            slot_statuses.append(f"{source}:{safe_name(material_path, 'mat')}:{binding.get('binding_status', 'unbound') if binding else 'unbound'}")

        all_effective_slots_have_diffuse = bool(slot_count and diffuse_ok == slot_count)
        stats["placements_total"] += 1
        stats["placements_with_mesh_asset"] += int(asset is not None)
        stats["placements_with_component_material_overrides"] += int(bool(overrides))
        stats["placements_with_effective_slots"] += int(slot_count > 0)
        stats["placements_all_effective_slots_have_diffuse"] += int(all_effective_slots_have_diffuse)
        stats["placement_effective_material_slots"] += slot_count
        stats["placement_effective_material_slots_with_diffuse"] += diffuse_ok
        stats["placement_effective_material_slots_without_diffuse"] += unresolved_slots

        placement_rows.append(
            {
                "target": target,
                "placement_index": placement_index,
                "actor_name": placement.get("actor_name", ""),
                "actor_path": placement.get("actor_path", ""),
                "static_mesh_path": mesh_path,
                "asset_found": asset is not None,
                "component_override_count": len(overrides),
                "effective_material_slot_count": slot_count,
                "effective_slots_with_diffuse": diffuse_ok,
                "effective_slots_without_diffuse": unresolved_slots,
                "all_effective_slots_have_diffuse": all_effective_slots_have_diffuse,
                "slot_statuses": " | ".join(slot_statuses[:16]),
            }
        )

    link_status_counts = Counter(row["status"] for row in link_rows)
    unique_linked_sources = len({norm_key(row.get("source_path")) for row in link_rows if row.get("source_path")})
    summary = {
        "target": target,
        "source_scene_manifest": scene_manifest.get("blend_path", ""),
        "output_dir": str(out_dir),
        "asset_manifest_csv": str(proof_dir / f"{prefix}_textured_staticmesh_asset_pack_manifest.csv"),
        "asset_manifest_json": str(proof_dir / f"{prefix}_textured_staticmesh_asset_pack_manifest.json"),
        "placement_materials_csv": str(proof_dir / f"{prefix}_textured_staticmesh_effective_placement_materials.csv"),
        "section_materials_csv": str(proof_dir / f"{prefix}_textured_staticmesh_section_materials.csv"),
        "texture_links_csv": str(proof_dir / f"{prefix}_textured_staticmesh_texture_links.csv"),
        "counts": dict(stats),
        "status_counts": {name: dict(counter) for name, counter in by_status.items()},
        "texture_link_status_counts": dict(link_status_counts),
        "unique_texture_sources_linked_or_referenced": unique_linked_sources,
        "top_missing_material_paths": [
            {"material_path": path, "section_count": count}
            for path, count in missing_material_paths.most_common(40)
        ],
        "notes": [
            "OBJ/MTL files are grouped by native StaticMesh asset, not by actor instance.",
            "MTL assignment follows decoded StaticMesh section triangle ranges.",
            "Component material override audit is emitted separately; Blender scene builders should use it per placement.",
            "DDS files are hardlinked when possible to avoid duplicating decoded texture payloads.",
        ],
    }

    write_csv(
        proof_dir / f"{prefix}_textured_staticmesh_asset_pack_manifest.csv",
        asset_rows,
        [
            "target",
            "asset_index",
            "asset_full_path",
            "asset_object_name",
            "source_obj",
            "out_obj",
            "out_mtl",
            "extract_status",
            "uv_status",
            "section_status",
            "source_vertices",
            "source_uvs",
            "source_normals",
            "source_faces",
            "face_count_manifest",
            "section_count",
            "sections_with_diffuse",
            "sections_with_normal",
            "sections_with_specular",
            "sections_with_emissive",
            "sections_unbound",
            "all_sections_have_diffuse",
            "obj_status",
            "written_usemtl_count",
        ],
    )
    write_csv(
        proof_dir / f"{prefix}_textured_staticmesh_effective_placement_materials.csv",
        placement_rows,
        [
            "target",
            "placement_index",
            "actor_name",
            "actor_path",
            "static_mesh_path",
            "asset_found",
            "component_override_count",
            "effective_material_slot_count",
            "effective_slots_with_diffuse",
            "effective_slots_without_diffuse",
            "all_effective_slots_have_diffuse",
            "slot_statuses",
        ],
    )
    write_csv(
        proof_dir / f"{prefix}_textured_staticmesh_section_materials.csv",
        material_rows,
        [
            "asset_full_path",
            "asset_object_name",
            "section_index",
            "triangle_start",
            "num_triangles",
            "material_path",
            "binding_status",
            "diffuse_dds",
            "normal_dds",
            "specular_dds",
            "emissive_dds",
        ],
    )
    write_csv(
        proof_dir / f"{prefix}_textured_staticmesh_texture_links.csv",
        link_rows,
        ["source_path", "linked_path", "role", "status"],
    )
    write_json(proof_dir / f"{prefix}_textured_staticmesh_asset_pack_manifest.json", asset_manifest)
    write_json(proof_dir / f"{prefix}_textured_staticmesh_asset_pack_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a textured Reloaded StaticMesh OBJ/MTL asset pack from decoded map caches.")
    parser.add_argument("--scene-manifest", required=True, help="Native scene manifest emitted by the Reloaded map Blender prep pass.")
    parser.add_argument("--material-texture-cache", required=True, help="Material texture binding JSON from the map Material_Texture_Cache pass.")
    parser.add_argument("--out-dir", required=True, help="Output directory for OBJ/MTL/textures/proof files.")
    parser.add_argument("--prefix", default="gowreloaded_map", help="Filename prefix for proof artifacts.")
    parser.add_argument("--target", default="UnknownMap", help="Human/readable map target name for proof rows.")
    parser.add_argument("--no-obj", action="store_true", help="Only write MTL/proof files; do not emit rewritten OBJ files.")
    args = parser.parse_args()

    scene_manifest_path = Path(args.scene_manifest)
    material_cache_path = Path(args.material_texture_cache)
    scene_manifest = read_json(scene_manifest_path)
    material_cache = read_json(material_cache_path)
    if not isinstance(material_cache, dict):
        raise TypeError(f"material texture cache must be a JSON object: {material_cache_path}")

    summary = build_asset_pack(
        scene_manifest=scene_manifest,
        material_cache=material_cache,
        out_dir=Path(args.out_dir),
        prefix=args.prefix,
        target=args.target,
        write_obj=not bool(args.no_obj),
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
