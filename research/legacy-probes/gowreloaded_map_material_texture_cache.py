#!/usr/bin/env python3
"""Generic MaterialInstanceConstant texture binding wrapper for Reloaded maps."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_material_texture_cache.py"
)


def load_source():
    spec = importlib.util.spec_from_file_location("gowr_material_cache", SOURCE_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load source tool: {SOURCE_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_material_cache"] = module
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


def install_inline_dds_export(src: Any, map_dir: Path) -> None:
    """Patch the shared exporter so package-inline Texture2D mip payloads export."""

    original_export = src.prep.export_texture_dds
    package_cache: dict[str, bytes] = {}

    def export_texture_dds(texture: dict[str, Any], mip: dict[str, Any], out_dir: Path) -> dict[str, Any]:
        if mip.get("external"):
            return original_export(texture, mip, out_dir)

        fmt = str(texture.get("format") or "")
        if fmt not in src.prep.SUPPORTED_FOURCC:
            return {"status": "unsupported_format", "reason": fmt}
        inline_offset = mip.get("inline_offset")
        if inline_offset is None:
            return {"status": "missing_inline_offset"}

        width = int(mip["width"])
        height = int(mip["height"])
        stored_size = int(mip["stored_size"])
        uncompressed_size = int(mip["uncompressed_size"])
        virt = src.prep.package_virtual_bytes(map_dir, texture["package"], package_cache)
        blob = virt[int(inline_offset) : int(inline_offset) + stored_size]
        if len(blob) != stored_size:
            return {"status": "short_inline_bulk_read", "read": len(blob), "expected": stored_size}

        if mip.get("compressed"):
            group = src.heavy.decode_group_at(blob, 0)
            if not group:
                return {"status": "compressed_inline_bulk_decode_failed", "stored_size": stored_size}
            payload = group["data"]
        else:
            payload = blob

        expected_size = src.prep.expected_dxt_size(width, height, fmt)
        if len(payload) != expected_size and len(payload) != uncompressed_size:
            return {
                "status": "payload_size_mismatch",
                "payload_size": len(payload),
                "expected_dxt_size": expected_size,
                "uncompressed_size": uncompressed_size,
            }

        out_dir.mkdir(parents=True, exist_ok=True)
        dds_path = out_dir / src.prep.texture_filename(texture["full_path"], width, height, fmt)
        if not dds_path.exists():
            dds_path.write_bytes(
                src.prep.dds_header_fourcc(width, height, src.prep.SUPPORTED_FOURCC[fmt], len(payload), 1)
                + payload
            )
        return {
            "status": "dds_exported",
            "dds_path": str(dds_path),
            "width": width,
            "height": height,
            "format": fmt,
            "mip_index": mip["mip_index"],
            "payload_size": len(payload),
            "source_cache": str(map_dir / texture["package"]),
            "file_offset": inline_offset,
            "inline_payload": True,
        }

    src.prep.export_texture_dds = export_texture_dds
def role_for_reference(src: Any, tex_path: str, texture: dict[str, Any]) -> str:
    role = src.role_for_texture_path(tex_path)
    if role != "unknown":
        return role
    fmt = str(texture.get("format") or "")
    if fmt == "PF_DXN":
        return "normal"
    combined = " ".join(
        src.prep.normalize_key(str(value or ""))
        for value in (tex_path, texture.get("object_name"), texture.get("source_file_path"))
    )
    blocked = (
        "normal",
        "nrm",
        "spec",
        "specular",
        "mask",
        "ramp",
        "noise",
        "cube",
        "cloud",
        "foam",
        "opacity",
        "alpha",
        "height",
    )
    if fmt in {"PF_DXT1", "PF_DXT3", "PF_DXT5"} and not any(token in combined for token in blocked):
        return "diffuse"
    return "unknown"
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-dir", required=True)
    parser.add_argument("--cooked-root", required=True)
    parser.add_argument("--visual-csv", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--texture-out", required=True)
    parser.add_argument("--target", default="MP_Gridlock")
    parser.add_argument("--prefix", default="gowreloaded_mp_gridlock")
    parser.add_argument("--max-texture-size", type=int, default=2048)
    args = parser.parse_args()

    src = load_source()
    map_dir = Path(args.map_dir)
    install_inline_dds_export(src, map_dir)
    out_dir = Path(args.out)
    texture_out = Path(args.texture_out)
    out_dir.mkdir(parents=True, exist_ok=True)
    texture_out.mkdir(parents=True, exist_ok=True)
    prefix = sanitize_prefix(args.prefix)

    visual_rows = src.read_csv(Path(args.visual_csv))
    material_rows = [row for row in visual_rows if row.get("class_name") in {"MaterialInstanceConstant", "Material"}]
    print(f"building texture inventory from {args.visual_csv}")
    textures = src.prep.build_texture_inventory(map_dir, Path(args.cooked_root), Path(args.visual_csv))
    texture_by_path = {str(texture.get("full_path", "")).lower(): texture for texture in textures}
    texture_exports_by_key: dict[str, dict[str, Any]] = {}
    package_cache: dict[str, dict[str, Any]] = {}
    bindings: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for index, row in enumerate(material_rows, 1):
        class_name = row.get("class_name", "")
        binding_prefix = "mic_referenced_textures" if class_name == "MaterialInstanceConstant" else "material_referenced_textures"
        ctx = src.package_context(map_dir, row["package"], package_cache)
        export_index = int(row["export_index"])
        export = ctx["exports"][export_index - 1]
        scan = src.heavy.best_property_scan(ctx["virt"], ctx["names"], ctx["exports"], ctx["imports"], ctx["ref_path"], export, [4, 0])
        result = scan["result"]
        tags = result.get("tags", []) if result.get("ok") else []
        referenced = src.referenced_texture_paths(tags)
        roles: dict[str, dict[str, Any]] = {}
        missing_refs: list[str] = []
        unknown_refs: list[str] = []
        for tex_path in referenced:
            texture = texture_by_path.get(tex_path.lower())
            if not texture:
                missing_refs.append(tex_path)
                continue
            role = role_for_reference(src, tex_path, texture)
            if role == "unknown":
                unknown_refs.append(tex_path)
                continue
            mip = src.prep.choose_mip(texture, int(args.max_texture_size))
            if not mip:
                missing_refs.append(tex_path)
                continue
            tex_key = texture["full_path"].lower() + f"#{mip['mip_index']}"
            if tex_key not in texture_exports_by_key:
                texture_exports_by_key[tex_key] = src.prep.export_texture_dds(texture, mip, texture_out)
            exported = texture_exports_by_key[tex_key]
            if exported.get("status") == "dds_exported":
                roles[role] = src.make_role_entry(texture, exported)
            else:
                missing_refs.append(tex_path)
        status = f"{binding_prefix}_bound" if roles.get("diffuse") else (f"{binding_prefix}_no_diffuse" if roles else f"{binding_prefix}_unbound")
        status_counts[status] += 1
        binding = {
            "material_path": row["full_path"],
            "material_object_name": row["object_name"],
            "material_package": row["package"],
            "export_index": export_index,
            "binding_status": status,
            "binding_evidence": f"{class_name}.ReferencedTextures property decoded to Texture2D exports",
            "material_class": class_name,
            "parent_material_path": src.parent_path(tags),
            "referenced_textures": referenced,
            "missing_referenced_textures": missing_refs,
            "unknown_role_textures": unknown_refs,
            "roles": roles,
        }
        old = bindings.get(row["full_path"].lower())
        if old is None or (not old.get("roles", {}).get("diffuse") and roles.get("diffuse")):
            bindings[row["full_path"].lower()] = binding
        rows.append(
            {
                "package": row["package"],
                "export_index": export_index,
                "class_name": class_name,
                "material_path": row["full_path"],
                "binding_status": status,
                "parent_material_path": binding["parent_material_path"],
                "referenced_textures": "; ".join(referenced),
                "diffuse_texture": roles.get("diffuse", {}).get("texture_full_path", ""),
                "diffuse_dds": roles.get("diffuse", {}).get("dds_path", ""),
                "normal_texture": roles.get("normal", {}).get("texture_full_path", ""),
                "normal_dds": roles.get("normal", {}).get("dds_path", ""),
                "specular_texture": roles.get("specular", {}).get("texture_full_path", ""),
                "specular_dds": roles.get("specular", {}).get("dds_path", ""),
                "emissive_texture": roles.get("emissive", {}).get("texture_full_path", ""),
                "emissive_dds": roles.get("emissive", {}).get("dds_path", ""),
                "missing_referenced_textures": "; ".join(missing_refs),
                "unknown_role_textures": "; ".join(unknown_refs),
            }
        )
        if index % 200 == 0:
            print(f"decoded material texture bindings {index} / {len(material_rows)}")

    texture_export_rows = [{"texture_key": key, **value} for key, value in sorted(texture_exports_by_key.items())]
    cache_path = out_dir / f"{prefix}_material_texture_bindings.json"
    csv_path = out_dir / f"{prefix}_material_texture_bindings.csv"
    export_csv = out_dir / f"{prefix}_material_texture_export_manifest.csv"
    manifest_path = out_dir / f"{prefix}_material_texture_bindings_manifest.json"
    cache_path.write_text(json.dumps(bindings, indent=2, ensure_ascii=True), encoding="utf-8")
    src.write_csv(
        csv_path,
        rows,
        ["package", "export_index", "class_name", "material_path", "binding_status", "parent_material_path", "referenced_textures", "diffuse_texture", "diffuse_dds", "normal_texture", "normal_dds", "specular_texture", "specular_dds", "emissive_texture", "emissive_dds", "missing_referenced_textures", "unknown_role_textures"],
    )
    src.write_csv(
        export_csv,
        texture_export_rows,
        ["texture_key", "status", "dds_path", "width", "height", "format", "mip_index", "payload_size", "source_cache", "file_offset", "reason", "cache_path"],
    )
    manifest = {
        "target": args.target,
        "game": "Gears of War Reloaded",
        "mic_exports_scanned": sum(1 for row in material_rows if row.get("class_name") == "MaterialInstanceConstant"),
        "material_exports_scanned": len(material_rows),
        "material_classes_scanned": sorted({row.get("class_name", "") for row in material_rows}),
        "unique_material_bindings": len(bindings),
        "status_counts": dict(sorted(status_counts.items())),
        "texture_exports": len(texture_export_rows),
        "dds_textures_exported": sum(1 for row in texture_export_rows if row.get("status") == "dds_exported"),
        "cache_json": str(cache_path),
        "summary_csv": str(csv_path),
        "texture_export_csv": str(export_csv),
        "texture_out_dir": str(texture_out),
        "source_tool": str(SOURCE_TOOL),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
