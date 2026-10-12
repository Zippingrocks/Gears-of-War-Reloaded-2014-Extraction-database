#!/usr/bin/env python3
"""Bind native materials to Gridlock inline StaticMesh assets with no overrides."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


ACTIVE_UV_NAME = "UV0_Source_Offset4"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--material-cache", required=True)
    parser.add_argument("--png-map", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def norm_path(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(str(Path(path).resolve(strict=False)))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def safe_name(text: str, limit: int = 110) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(text))
    return (clean.strip("._") or "unnamed")[:limit]


def load_png_map(path: Path) -> dict[str, str]:
    rows = read_json(path)
    by_source: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else rows.get("rows", []):
        if row.get("status") != "converted":
            continue
        source = norm_path(str(row.get("source") or ""))
        png = str(row.get("png") or "")
        if source and png and Path(png).exists():
            by_source[source] = png
    return by_source


def material_images(material: bpy.types.Material | None) -> list[str]:
    if material is None or not material.use_nodes:
        return []
    out: list[str] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            out.append(str(Path(node.image.filepath).resolve(strict=False)))
    return out


def visual_role(binding: dict[str, Any], material_path: str) -> tuple[str, dict[str, Any], str]:
    roles = binding.get("roles") if isinstance(binding, dict) else {}
    if not isinstance(roles, dict):
        return "", {}, ""
    diffuse = roles.get("diffuse")
    if isinstance(diffuse, dict) and diffuse.get("dds_path"):
        return "diffuse", diffuse, "native_diffuse"
    lowered = " ".join(
        [
            str(material_path).lower(),
            str(binding.get("parent_material_path", "")).lower(),
            " ".join(str(item).lower() for item in binding.get("referenced_textures", []) if item),
        ]
    )
    if any(token in lowered for token in ("traffic", "streetcross", "crossing", "poster", "decal", "paint", "sign", "asphalt", "damage", "ashes", "vent")):
        for role in ("alpha", "mask", "emissive", "specular", "normal"):
            value = roles.get(role)
            if isinstance(value, dict) and value.get("dds_path"):
                return role, value, f"{role}_as_visual_base"
    if len(roles) == 1:
        role, value = next(iter(roles.items()))
        if isinstance(value, dict) and value.get("dds_path"):
            return str(role), value, f"{role}_as_only_texture_visual_base"
    return "", {}, ""


def image_for_role(role_data: dict[str, Any], png_by_source: dict[str, str]) -> str:
    dds_path = str(role_data.get("dds_path") or "").strip()
    return png_by_source.get(norm_path(dds_path), "") if dds_path else ""


def clear_nodes(nodes: bpy.types.Nodes) -> None:
    for node in list(nodes):
        nodes.remove(node)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def material_needs_alpha(material_path: str, binding: dict[str, Any]) -> bool:
    text = " ".join(
        [
            material_path.lower(),
            str(binding.get("parent_material_path", "")).lower(),
            " ".join(str(item).lower() for item in binding.get("referenced_textures", []) if item),
        ]
    )
    return any(token in text for token in ("transparent", "translucent", "masked", "decal", "poster", "asphalt_decal", "damage", "ashes", "godray"))


def make_material(material_path: str, binding: dict[str, Any], png_by_source: dict[str, str]) -> bpy.types.Material:
    role, role_data, reason = visual_role(binding, material_path)
    mat_name = f"INLINE_ASSET_NATIVE__{safe_name(material_path, 86)}"
    if role:
        mat_name += f"__{role}_base"
    material = bpy.data.materials.get(mat_name)
    if material is None:
        material = bpy.data.materials.new(mat_name)
    material.use_nodes = True
    material.diffuse_color = (0.25, 0.25, 0.23, 1.0)
    material["ue_material_path"] = material_path
    material["inline_asset_material_repair"] = reason or "no_texture_binding"
    material["texture_binding_status"] = binding.get("binding_status", "") if isinstance(binding, dict) else ""

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    clear_nodes(nodes)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (420, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (160, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base_input = principled_input(bsdf, ("Base Color",))
    alpha_input = principled_input(bsdf, ("Alpha",))
    rough_input = principled_input(bsdf, ("Roughness",))
    if rough_input is not None:
        rough_input.default_value = 0.8

    png_path = image_for_role(role_data, png_by_source) if role_data else ""
    if png_path and base_input is not None:
        image = bpy.data.images.load(png_path, check_existing=True)
        try:
            image.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        image["source_dds_path"] = str(role_data.get("dds_path") or "")
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "InlineAsset_VisualBase_PNG"
        tex.label = f"{role} visual base"
        tex.location = (-440, 100)
        tex.image = image
        tex.extension = "REPEAT"
        uv = nodes.new("ShaderNodeUVMap")
        uv.name = "InlineAsset_SourceUV0"
        uv.label = ACTIVE_UV_NAME
        uv.location = (-690, 90)
        uv.uv_map = ACTIVE_UV_NAME
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], base_input)
        if alpha_input is not None and "Alpha" in tex.outputs and material_needs_alpha(material_path, binding):
            links.new(tex.outputs["Alpha"], alpha_input)
            material.blend_method = "HASHED"
            material.show_transparent_back = True
        material["viewport_png_alias"] = png_path
        material["visual_base_role"] = role
        material["visual_base_source_dds"] = str(role_data.get("dds_path") or "")
    elif base_input is not None:
        base_input.default_value = (0.18, 0.18, 0.17, 1.0)
    return material


def candidate_material_keys(static_mesh_path: str, slot_material_name: str, material_cache: dict[str, Any]) -> list[str]:
    lower_path = static_mesh_path.lower()
    candidates: list[str] = []
    slot_lower = slot_material_name.lower()
    if slot_lower in material_cache:
        candidates.append(slot_lower)

    if "." in lower_path:
        package, object_name = lower_path.rsplit(".", 1)
    else:
        package, object_name = "", lower_path
    stems = [object_name]
    for suffix in ("_smesh_mesh_lod0", "_smesh", "_staticmesh", "_mesh_lod0"):
        if object_name.endswith(suffix):
            stems.append(object_name[: -len(suffix)])
    stems = list(dict.fromkeys(stems))
    for stem in stems:
        if package:
            candidates.append(f"{package}.{stem}_mat_mic")
            if not stem.endswith("_delta"):
                candidates.append(f"{package}.{stem}_delta_mat_mic")
            if stem.endswith("_delta"):
                candidates.append(f"{package}.{stem[:-6]}_delta_mat_mic")
    if "cog_city_architecture.vent_02" in lower_path:
        candidates.append("cog_city_architecture.vent_01_delta_mat_mic")
    if lower_path.startswith("signage_paint.signage_paint_"):
        candidates.extend(["signage_paint.paintwall_mat", "signage_paint.paintwall_mat_lighter"])
    if "delta_gridlock_01.decals." in lower_path and ("poster" in lower_path or "bulletin_board" in lower_path):
        candidates.extend(
            [
                "delta_gridlock_01.decals.posters_01a_masked_delta_mat_mic",
                "delta_gridlock_01.decals.posters_01a_delta_mat_mic",
                "delta_gridlock_01.decals.bulletin_board_01a_delta_mat_mic",
            ]
        )
    if "debris_ashes_02a_delta_smesh" in lower_path:
        candidates.append("delta_gridlock_01.debris_ashes_02a_delta_mat_mic")
    if "debris_ashes_01a_delta_smesh" in lower_path:
        candidates.append("delta_gridlock_01.debris_ashes_01a_delta_mat_mic")
    return list(dict.fromkeys(candidates))


def choose_binding(static_mesh_path: str, slot_material_name: str, material_cache: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    candidates = candidate_material_keys(static_mesh_path, slot_material_name, material_cache)
    for key in candidates:
        binding = material_cache.get(key)
        if not isinstance(binding, dict):
            continue
        role, role_data, _reason = visual_role(binding, binding.get("material_path", key))
        if role and role_data:
            return str(binding.get("material_path") or key), binding, candidates
    return "", {}, candidates


def is_target_slot(slot: bpy.types.MaterialSlot) -> bool:
    mat = slot.material
    if mat is None:
        return True
    if mat.name == "MAT__UNBOUND_SOURCE_MATERIAL":
        return True
    return not material_images(mat)


def main() -> int:
    args = parse_args()
    material_cache = read_json(Path(args.material_cache))
    png_by_source = load_png_map(Path(args.png_map))
    if args.backup_out:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(bpy.data.filepath, backup)

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        static_mesh_path = str(obj.get("ue_static_mesh_path") or "")
        if not static_mesh_path:
            continue
        if not obj.material_slots:
            obj.data.materials.append(None)
        for index, slot in enumerate(obj.material_slots):
            if not is_target_slot(slot):
                continue
            before = slot.material.name if slot.material else ""
            material_path, binding, candidates = choose_binding(static_mesh_path, before, material_cache)
            if not material_path:
                skipped.append({"object": obj.name, "slot": index, "static_mesh_path": static_mesh_path, "before": before, "candidates": candidates[:12]})
                continue
            material = make_material(material_path, binding, png_by_source)
            if not material.get("viewport_png_alias"):
                skipped.append({"object": obj.name, "slot": index, "static_mesh_path": static_mesh_path, "before": before, "material_path": material_path, "reason": "no_png_alias"})
                continue
            slot.link = "OBJECT"
            slot.material = material
            if obj.data.uv_layers.get(ACTIVE_UV_NAME):
                for uv_index, layer in enumerate(obj.data.uv_layers):
                    if layer.name == ACTIVE_UV_NAME:
                        obj.data.uv_layers.active_index = uv_index
                        break
            obj["inline_asset_fallback_material_repair"] = "native material inferred from static mesh asset path"
            rows.append(
                {
                    "object": obj.name,
                    "slot": index,
                    "static_mesh_path": static_mesh_path,
                    "before": before,
                    "material_path": material_path,
                    "material": material.name,
                    "visual_base_role": material.get("visual_base_role", ""),
                    "viewport_png_alias": material.get("viewport_png_alias", ""),
                    "candidates": candidates[:12],
                }
            )

    proof = {
        "blend_path": bpy.data.filepath,
        "repaired_slots": len(rows),
        "repaired_objects": len({row["object"] for row in rows}),
        "skipped_slots": len(skipped),
        "rows": rows,
        "skipped_samples": skipped[:160],
        "status": "inline_staticmesh_asset_name_material_fallbacks_applied",
    }
    proof_path = Path(args.proof_out)
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_inline_asset_material_fallback_repair"] = proof["status"]
    bpy.context.scene["gridlock_inline_asset_material_fallback_repair_proof"] = str(proof_path)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({key: proof[key] for key in ("repaired_slots", "repaired_objects", "skipped_slots", "status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
