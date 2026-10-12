#!/usr/bin/env python3
"""Repair MP_Gridlock static-mesh material slots in an existing Blender scene.

Runs inside Blender. It rebuilds mesh section material slots from the native
manifest, then reapplies only valid nonblank instance overrides so partial
override arrays cannot hide the real section textures.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy


BUILDER_PATH = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factorybasement_build_textured_blend_scene.py"
)

TARGET_NAMES = [
    "bsp_gridlock_road_b_SMesh__26847",
    "COG_City_Ephyra2_1post_Smesh__26695",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "MS_Neutral_Sedan_SMesh__27672",
    "SDStitchingProxy_2755_StaticMesh__27221",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
]

RENDER_UV_LAYER = 'UV_Source_Render'
TEXTURE_ALIAS_DIR: Path | None = None
TEXTURE_ALIASES: dict[str, dict[str, str]] = {}


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--targets", nargs="*", default=TARGET_NAMES)
    parser.add_argument("--all-staticmeshes", action="store_true", default=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("gow_reloaded_blend_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import builder from {BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_json_field(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    text = str(value).strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def placement_object_name(row: dict[str, Any]) -> str:
    mesh_path = str(row.get("static_mesh_path") or "").strip()
    base = mesh_path.rsplit(".", 1)[-1] if mesh_path else ""
    if not base:
        base = str(row.get("object_name") or row.get("actor_name") or row.get("static_mesh_object_name") or "StaticMesh")
    comp = row.get("component_ref") or row.get("component_export_index") or row.get("export_index") or ""
    comp_text = str(comp).strip()
    return f"{base}__{comp_text}" if comp_text else base


def texture_roles(binding: dict[str, Any]) -> dict[str, str]:
    roles = binding.get("roles") if isinstance(binding, dict) else None
    role_map: dict[str, str] = {}
    if isinstance(roles, dict):
        for key, value in roles.items():
            role = str(key).strip().lower()
            if not role:
                continue
            if isinstance(value, dict):
                path = str(value.get("dds_path") or value.get("texture_full_path") or "").strip()
            else:
                path = str(value or "").strip()
            if path:
                role_map[role] = path
        return role_map
    for texture in binding.get("textures", []) if isinstance(binding, dict) else []:
        if not isinstance(texture, dict):
            continue
        role = str(texture.get("role") or "").strip().lower()
        dds_path = str(texture.get("dds_path") or "").strip()
        if role and dds_path:
            role_map[role] = dds_path
    return role_map


def has_bound_diffuse(binding: dict[str, Any]) -> bool:
    roles = texture_roles(binding)
    if roles.get("diffuse"):
        return True
    return any("diffuse" in key.lower() or "base" in key.lower() for key in roles)


def binding_role(binding: dict[str, Any], role: str) -> dict[str, Any]:
    roles = binding.get("roles") if isinstance(binding, dict) else None
    wanted = str(role).strip().lower()
    if isinstance(roles, dict):
        for key, value in roles.items():
            if str(key).strip().lower() == wanted and isinstance(value, dict):
                return value
    return {}


def windows_long_path(path: str) -> str:
    if os.name != "nt":
        return path
    text = str(Path(path))
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text.lstrip("\\")
    return "\\\\?\\" + text


def copy_to_texture_alias(dds_path: str) -> str:
    global TEXTURE_ALIASES
    clean_path = str(dds_path or "").strip()
    if not clean_path:
        return ""
    source_abs = os.path.abspath(clean_path)
    source_key = os.path.normcase(source_abs)
    source_path = Path(source_abs)
    try:
        if source_path.exists() and len(source_abs) < 248:
            return source_abs
    except OSError:
        pass

    if TEXTURE_ALIAS_DIR is None:
        return clean_path
    TEXTURE_ALIAS_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(source_key.encode("utf-8", errors="ignore")).hexdigest()[:20]
    alias_path = TEXTURE_ALIAS_DIR / f"dds_{digest}.dds"
    alias_abs = str(alias_path)
    try:
        if not alias_path.exists():
            shutil.copyfile(windows_long_path(source_abs), alias_abs)
        TEXTURE_ALIASES[source_key] = {"source": source_abs, "alias": alias_abs}
        return alias_abs
    except Exception as exc:
        TEXTURE_ALIASES[source_key] = {"source": source_abs, "alias": "", "error": repr(exc)}
        return clean_path


def materialize_binding_dds_paths(binding: dict[str, Any]) -> dict[str, Any]:
    fixed = copy.deepcopy(binding or {})
    roles = fixed.get("roles")
    if not isinstance(roles, dict):
        return fixed
    for role_data in roles.values():
        if not isinstance(role_data, dict):
            continue
        original = str(role_data.get("dds_path") or "").strip()
        if not original:
            continue
        loadable = copy_to_texture_alias(original)
        if loadable and loadable != original:
            role_data["source_dds_path"] = original
            role_data["dds_path"] = loadable
    return fixed

def binding_for_material_path(
    material_path: str,
    seed_binding: dict[str, Any],
    asset: dict[str, Any],
    material_texture_bindings: dict[str, Any],
) -> dict[str, Any]:
    binding = dict(seed_binding or {})
    if not binding and isinstance(asset.get("texture_binding"), dict):
        binding = dict(asset["texture_binding"])
    clean_path = str(material_path or "").strip()
    manifest_binding = material_texture_bindings.get(clean_path.lower()) if clean_path else None
    if isinstance(manifest_binding, dict) and manifest_binding:
        binding = dict(manifest_binding)
    if clean_path and binding:
        binding["static_mesh_path"] = clean_path
    return materialize_binding_dds_paths(binding)


def clear_nodes(nodes: bpy.types.Nodes) -> None:
    for node in list(nodes):
        nodes.remove(node)


def upgrade_material_from_binding(material: bpy.types.Material, binding: dict[str, Any], builder: Any) -> bool:
    diffuse = binding_role(binding, "diffuse")
    diffuse_path = str(diffuse.get("dds_path") or "").strip()
    if not diffuse_path:
        return False
    if str(material.get("decoded_diffuse_dds", "")) == diffuse_path:
        return False

    material.use_nodes = True
    material.diffuse_color = builder.hashed_color(material.name)
    material["texture_binding_status"] = binding.get("binding_status", "")
    material["texture_binding_evidence"] = binding.get("binding_evidence", "")
    material["source_file_path"] = binding.get("source_file_path", "")
    material["source_basename"] = binding.get("source_basename", "")

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    clear_nodes(nodes)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (360, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (120, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    base_input = builder.principled_input(bsdf, ("Base Color",))
    rough_input = builder.principled_input(bsdf, ("Roughness",))
    metallic_input = builder.principled_input(bsdf, ("Metallic",))
    spec_input = builder.principled_input(bsdf, ("Specular IOR Level", "Specular"))
    normal_input = builder.principled_input(bsdf, ("Normal",))
    if rough_input is not None:
        rough_input.default_value = 0.78
    if metallic_input is not None:
        metallic_input.default_value = 0.0
    if spec_input is not None:
        spec_input.default_value = 0.35

    diffuse_image = builder.load_image(diffuse_path, non_color=False)
    if diffuse_image is not None and base_input is not None:
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "Decoded_Diffuse_DDS"
        tex.label = "Decoded Diffuse DDS"
        tex.location = (-520, 120)
        tex.image = diffuse_image
        tex.extension = "REPEAT"
        links.new(tex.outputs["Color"], base_input)
        material["decoded_diffuse_dds"] = diffuse_path
        material["source_diffuse_dds"] = diffuse.get("source_dds_path", diffuse_path)

    normal = binding_role(binding, "normal")
    normal_path = str(normal.get("dds_path") or "").strip()
    normal_image = builder.load_image(normal_path, non_color=True)
    if normal_image is not None and normal_input is not None:
        tex_n = nodes.new("ShaderNodeTexImage")
        tex_n.name = "Decoded_Normal_DDS"
        tex_n.label = "Decoded Normal DDS"
        tex_n.location = (-520, -120)
        tex_n.image = normal_image
        tex_n.extension = "REPEAT"
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-160, -120)
        normal_map.inputs["Strength"].default_value = 0.55
        links.new(tex_n.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], normal_input)
        material["decoded_normal_dds"] = normal_path

    specular = binding_role(binding, "specular")
    specular_path = str(specular.get("dds_path") or "").strip()
    specular_image = builder.load_image(specular_path, non_color=True)
    if specular_image:
        tex_s = nodes.new("ShaderNodeTexImage")
        tex_s.name = "Decoded_Specular_DDS"
        tex_s.label = "Decoded Specular DDS"
        tex_s.location = (-520, -360)
        tex_s.image = specular_image
        tex_s.extension = "REPEAT"
        if spec_input is not None and "Alpha" in tex_s.outputs:
            links.new(tex_s.outputs["Alpha"], spec_input)
        material["decoded_specular_dds"] = specular_path

    emissive = binding_role(binding, "emissive")
    emissive_path = str(emissive.get("dds_path") or "").strip()
    emissive_image = builder.load_image(emissive_path, non_color=False)
    emission_input = builder.principled_input(bsdf, ("Emission Color", "Emission"))
    emission_strength = builder.principled_input(bsdf, ("Emission Strength",))
    if emissive_image is not None and emission_input is not None:
        tex_e = nodes.new("ShaderNodeTexImage")
        tex_e.name = "Decoded_Emissive_DDS"
        tex_e.label = "Decoded Emissive DDS"
        tex_e.location = (-520, -600)
        tex_e.image = emissive_image
        tex_e.extension = "REPEAT"
        links.new(tex_e.outputs["Color"], emission_input)
        if emission_strength is not None:
            emission_strength.default_value = 0.75
        material["decoded_emissive_dds"] = emissive_path
    return bool(material.get("decoded_diffuse_dds", ""))


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def relink_material_to_render_uv(material: bpy.types.Material | None) -> int:
    images = image_nodes(material)
    if material is None or material.node_tree is None or not images:
        return 0
    nodes = material.node_tree.nodes
    uv_node = nodes.get("Gridlock_StaticMesh_SourceRenderUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Gridlock_StaticMesh_SourceRenderUV"
        uv_node.label = RENDER_UV_LAYER
        uv_node.location = (-900, 240)
    uv_node.uv_map = RENDER_UV_LAYER
    linked = 0
    for node in images:
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for link in list(vector.links):
            material.node_tree.links.remove(link)
        material.node_tree.links.new(uv_node.outputs["UV"], vector)
        linked += 1
    material["texture_coordinate_uv_map"] = RENDER_UV_LAYER
    material["gridlock_section_material_repair_uv_routing"] = "image nodes linked to repo-confirmed UV_Source_Render"
    return linked


def unique_material_name_for_path(builder: Any, material_path: str, fallback_name: str) -> str:
    token = str(material_path or fallback_name or "UNBOUND_SOURCE_MATERIAL").strip()
    token = token.replace(".", "__")
    return builder.safe_name(f"MAT_UE__{token}", 120)


def material_for_unique_ue_path(
    material: bpy.types.Material,
    material_path: str,
    binding: dict[str, Any],
    builder: Any,
) -> bpy.types.Material:
    clean_path = str(material_path or "").strip()
    if material is None or not clean_path or clean_path.lower() == "none":
        return material
    unique_name = unique_material_name_for_path(builder, clean_path, material.name)
    existing = bpy.data.materials.get(unique_name)
    if existing is not None:
        unique = existing
    elif material.name == unique_name:
        unique = material
    else:
        unique = material.copy()
        unique.name = unique_name
    unique["ue_material_path"] = clean_path
    unique["gridlock_unique_ue_material_variant"] = "true"
    unique["gridlock_variant_source_material_name"] = material.name
    if binding:
        upgrade_material_from_binding(unique, binding, builder)
    return unique


def make_repaired_section_material(
    builder: Any,
    asset: dict[str, Any],
    section: dict[str, Any],
    fallback: bpy.types.Material,
    material_texture_bindings: dict[str, Any],
) -> bpy.types.Material:
    fixed_section = dict(section)
    material_path = str(fixed_section.get("material_path") or "").strip()
    binding = binding_for_material_path(
        material_path,
        fixed_section.get("material_texture_binding") or {},
        asset,
        material_texture_bindings,
    )
    if binding:
        fixed_section["material_texture_binding"] = binding
    material = builder.make_section_material(asset, fixed_section, fallback)
    return material_for_unique_ue_path(material, material_path, binding, builder)


def apply_staticmesh_sections_repaired(
    mesh: bpy.types.Mesh,
    asset: dict[str, Any],
    fallback: bpy.types.Material,
    builder: Any,
    material_texture_bindings: dict[str, Any],
) -> int:
    sections = asset.get("sections") or []
    if not sections:
        mesh.materials.append(fallback)
        return 0
    ordered = sorted(sections, key=lambda row: builder.as_int(row.get("section_index")))
    for section in ordered:
        mesh.materials.append(make_repaired_section_material(builder, asset, section, fallback, material_texture_bindings))
    max_index = max(len(mesh.materials) - 1, 0)
    for triangle_index, polygon in enumerate(mesh.polygons):
        polygon.material_index = min(builder.section_index_for_polygon(ordered, triangle_index), max_index)
    mesh["section_status"] = asset.get("section_status", "")
    mesh["section_count"] = len(ordered)
    return len(ordered)


def material_audit(obj: bpy.types.Object) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, slot in enumerate(obj.material_slots):
        material = slot.material
        material_name = material.name if material else ""
        ue_path = material.get("ue_material_path", "") if material else ""
        diffuse = (material.get("decoded_diffuse_dds", "") or material.get("ue_diffuse_dds", "")) if material else ""
        rows.append(
            {
                "slot": index,
                "link": slot.link,
                "material": material_name,
                "ue_material_path": ue_path,
                "diffuse_dds": diffuse,
                "source_diffuse_dds": material.get("source_diffuse_dds", "") if material else "",
            }
        )
    return rows


def repair_object(
    obj: bpy.types.Object,
    row: dict[str, Any],
    asset: dict[str, Any],
    builder: Any,
    fallback: bpy.types.Material,
    material_texture_bindings: dict[str, Any],
) -> dict[str, Any]:
    before = material_audit(obj)

    obj.data.materials.clear()
    section_count = apply_staticmesh_sections_repaired(obj.data, asset, fallback, builder, material_texture_bindings)
    for slot in obj.material_slots:
        slot.link = "DATA"

    materials_info = parse_json_field(row.get("materials_json"))
    paths = materials_info.get("object_ref_paths_sample") if isinstance(materials_info, dict) else None
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    if isinstance(paths, list):
        for index, material_path in enumerate(paths):
            if index >= len(obj.material_slots):
                skipped.append({"slot": index, "reason": "slot_out_of_range", "material_path": str(material_path)})
                continue
            clean_path = str(material_path or "").strip()
            if not clean_path or clean_path.lower() in {"none", "null"}:
                skipped.append({"slot": index, "reason": "blank_override_kept_section_material", "material_path": clean_path})
                continue
            binding = material_texture_bindings.get(clean_path.lower()) or {}
            if binding:
                binding = materialize_binding_dds_paths(binding)
            if not binding and index < len(obj.data.materials) and obj.data.materials[index]:
                skipped.append({"slot": index, "reason": "unbound_override_kept_section_material", "material_path": clean_path})
                continue
            material = builder.material_from_override_path(clean_path, asset, fallback, material_texture_bindings)
            material = material_for_unique_ue_path(material, clean_path, binding, builder)
            upgraded = bool(binding and material.get("decoded_diffuse_dds", ""))
            obj.material_slots[index].link = "OBJECT"
            obj.material_slots[index].material = material
            applied.append(
                {
                    "slot": index,
                    "material_path": clean_path,
                    "binding_found": bool(binding),
                    "has_bound_diffuse": has_bound_diffuse(binding),
                    "binding_diffuse_dds": binding_role(binding, "diffuse").get("dds_path", "") if binding else "",
                    "upgraded_to_dds": bool(upgraded),
                }
            )

    obj["material_override_count"] = len(applied)
    obj["material_repair_status"] = "sections_rebuilt_valid_overrides_reapplied"

    uv_relinked = 0
    if obj.data.uv_layers.get(RENDER_UV_LAYER) is not None:
        for slot in obj.material_slots:
            uv_relinked += relink_material_to_render_uv(slot.material)

    return {
        "object": obj.name,
        "static_mesh_path": row.get("static_mesh_path", obj.get("ue_static_mesh_path", "")),
        "section_count": section_count,
        "before": before,
        "after": material_audit(obj),
        "applied_overrides": applied,
        "skipped_overrides": skipped,
        "uv_relinked_image_nodes": uv_relinked,
    }


def main() -> None:
    global TEXTURE_ALIAS_DIR
    args = parse_args()
    builder = load_builder()
    manifest_path = Path(args.scene_manifest)
    manifest = load_json(manifest_path)
    TEXTURE_ALIAS_DIR = Path(bpy.data.filepath).resolve().parent / "texture_aliases_dds"

    material_texture_bindings = {
        str(key).lower(): value for key, value in (manifest.get("material_texture_bindings") or {}).items()
    }
    assets_by_path = {
        str(asset.get("full_path", "")).lower(): asset for asset in (manifest.get("assets") or manifest.get("staticmesh_assets") or [])
    }
    placements_by_name = {
        placement_object_name(row): row for row in (manifest.get("placements") or manifest.get("staticmesh_placements") or [])
    }

    fallback = bpy.data.materials.get("MAT__UNBOUND_SOURCE_MATERIAL")
    if fallback is None:
        fallback = builder.make_plain_material("MAT__UNBOUND_SOURCE_MATERIAL", (0.65, 0.25, 0.70, 1.0))

    targets = set(args.targets or [])
    repaired: list[dict[str, Any]] = []
    missing_targets: list[str] = []
    skipped_objects = 0

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if not obj.get("ue_static_mesh_path"):
            continue
        if not args.all_staticmeshes and obj.name not in targets:
            continue
        row = placements_by_name.get(obj.name)
        if row is None:
            skipped_objects += 1
            continue
        asset_path = str(row.get("static_mesh_path") or obj.get("ue_static_mesh_path") or "")
        asset = assets_by_path.get(asset_path.lower())
        if asset is None:
            skipped_objects += 1
            continue
        if str(asset.get("extract_status") or "").lower() == "inline_staticmesh_stream":
            skipped_objects += 1
            continue
        repaired.append(repair_object(obj, row, asset, builder, fallback, material_texture_bindings))

    repaired_by_name = {row["object"]: row for row in repaired}
    for target in targets:
        if target not in repaired_by_name:
            missing_targets.append(target)

    proof = {
        "scene": bpy.data.filepath,
        "manifest": str(manifest_path),
        "mode": "all_staticmeshes",
        "repaired_object_count": len(repaired),
        "skipped_object_count": skipped_objects,
        "target_count": len(targets),
        "texture_alias_dir": str(TEXTURE_ALIAS_DIR),
        "texture_alias_count": len(TEXTURE_ALIASES),
        "texture_aliases": list(TEXTURE_ALIASES.values()),
        "missing_targets": sorted(missing_targets),
        "target_audit": [repaired_by_name[name] for name in args.targets if name in repaired_by_name],
    }

    with Path(args.proof_out).open("w", encoding="utf-8") as handle:
        json.dump(proof, handle, indent=2)

    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)


if __name__ == "__main__":
    main()
