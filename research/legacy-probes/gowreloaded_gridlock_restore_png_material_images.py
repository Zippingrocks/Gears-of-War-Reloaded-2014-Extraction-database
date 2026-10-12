#!/usr/bin/env python3
"""Restore MP_Gridlock Blender materials to native PNG texture payloads.

Later repair passes can rebuild materials from DDS aliases. The earlier visual
breakthrough used PNG conversions from the native TFC/DDS cache, which Blender
handles more predictably. This pass does not rewrite mesh UVs or transforms; it
only swaps image nodes to matching PNGs and routes texture nodes to the existing
per-object render UV layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import bpy  # type: ignore


STATIC_RENDER_UV = "UV_Source_Render"
BSP_RENDER_UV = "UV_Source_BSP_RenderTexCoord"
INLINE_RENDER_UV = "UV0_Source_InlineCard"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--png-rows", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def image_abs(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    except Exception:
        return str(image.filepath or "")


def load_png(path_text: str, role: str) -> bpy.types.Image | None:
    clean = str(path_text or "").strip()
    if not clean or not Path(clean).exists():
        return None
    wanted = str(Path(clean)).lower()
    for image in bpy.data.images:
        if image_abs(image).lower() == wanted:
            return image
    try:
        image = bpy.data.images.load(clean, check_existing=True)
    except Exception:
        return None
    try:
        image.colorspace_settings.name = "sRGB" if role in {"diffuse", "emissive"} else "Non-Color"
    except Exception:
        pass
    return image


def role_from_node(node: bpy.types.Node) -> str:
    text = " ".join(
        [
            str(getattr(node, "name", "")),
            str(getattr(node, "label", "")),
            str(getattr(getattr(node, "image", None), "name", "")),
            str(getattr(getattr(node, "image", None), "filepath", "")),
        ]
    ).lower()
    if "normal" in text or "_n." in text or "_normal" in text:
        return "normal"
    if "specular" in text or "spec" in text or "_s." in text:
        return "specular"
    if "emissive" in text or "emiss" in text:
        return "emissive"
    if "opacity" in text or "alpha" in text or "mask" in text:
        return "mask"
    if "diffuse" in text or "base" in text or "albedo" in text or "_tex" in text or "_d." in text:
        return "diffuse"
    return ""


def material_path(material: bpy.types.Material | None) -> str:
    if material is None:
        return ""
    for key in ("ue_material_path", "native_material_path", "source_material_path"):
        value = str(material.get(key, "") or "").strip()
        if value:
            return value
    name = material.name
    if name.startswith("MAT_UE__"):
        return name[len("MAT_UE__") :].replace("__", ".")
    return ""


def material_token(path_text: str) -> str:
    token = str(path_text or "").strip().lower().rsplit(".", 1)[-1]
    for suffix in (
        "_delta_mat_notranslucency",
        "_mat_notranslucency",
        "_delta_mat_mic",
        "_mat_mic",
        "_delta_mat",
        "_mat",
        "_delta",
    ):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    return token


def image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return [row for row in payload.values() if isinstance(row, dict) and "png" in row]
    return []


def build_maps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, dict[str, Any]] = {}
    by_alias_name: dict[str, dict[str, Any]] = {}
    by_material_role: dict[tuple[str, str], dict[str, Any]] = {}
    by_token_role: dict[tuple[str, str], dict[str, Any]] = {}
    roles_by_material: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = str(row.get("source") or "").strip()
        material = str(row.get("material") or "").strip().lower()
        role = str(row.get("role") or "").strip().lower()
        png = str(row.get("png") or "").strip()
        if not png or str(row.get("status") or "").lower() != "converted":
            continue
        if source:
            by_source[str(Path(source)).lower()] = row
            source_key = os.path.normcase(os.path.abspath(source))
            digest = hashlib.sha1(source_key.encode("utf-8", errors="ignore")).hexdigest()[:20]
            by_alias_name[f"dds_{digest}.dds"] = row
        if material and role:
            by_material_role[(material, role)] = row
            token = material_token(material)
            if token:
                by_token_role[(token, role)] = row
            roles_by_material[material].append(row)
    return {
        "by_source": by_source,
        "by_alias_name": by_alias_name,
        "by_material_role": by_material_role,
        "by_token_role": by_token_role,
        "roles_by_material": roles_by_material,
    }


def source_row_for_node(
    material: bpy.types.Material,
    node: bpy.types.Node,
    maps: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    role = role_from_node(node)
    image = getattr(node, "image", None)
    current = image_abs(image)
    if role == "normal" and (
        "gridlock_reconstructed_dxn_normals" in material
        or "bc5_reconstructed" in current.lower()
        or Path(current).name.lower().startswith("rn_")
    ):
        return None, "preserve_reconstructed_bc5_normal"


    if current:
        current_path = Path(current)
        row = maps["by_source"].get(str(current_path).lower())
        if row:
            return row, "exact_source_path"
        row = maps["by_alias_name"].get(current_path.name.lower())
        if row:
            return row, "texture_alias_digest"

    mat_path = material_path(material).lower()
    if mat_path and role:
        row = maps["by_material_role"].get((mat_path, role))
        if row:
            return row, f"material_role:{role}"
        token = material_token(mat_path)
        row = maps["by_token_role"].get((token, role))
        if row:
            return row, f"material_token_role:{role}"

    if mat_path:
        rows = maps["roles_by_material"].get(mat_path, [])
        if len(rows) == 1 and not role:
            return rows[0], "single_material_texture"
        diffuse = maps["by_material_role"].get((mat_path, "diffuse"))
        if diffuse and not role:
            return diffuse, "material_default_diffuse"

    return None, "no_png_match"


def object_uv_name(obj: bpy.types.Object) -> str:
    mesh = obj.data
    if obj.name.startswith("Model_") and mesh.uv_layers.get(BSP_RENDER_UV):
        return BSP_RENDER_UV
    if mesh.uv_layers.get(STATIC_RENDER_UV):
        return STATIC_RENDER_UV
    if mesh.uv_layers.get(INLINE_RENDER_UV):
        return INLINE_RENDER_UV
    return mesh.uv_layers.active.name if mesh.uv_layers.active else ""


def relink_to_uv(material: bpy.types.Material, uv_name: str) -> int:
    if not uv_name or not material.use_nodes or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    uv_node = nodes.get(f"Gridlock_SourceUV_{uv_name}") or nodes.new("ShaderNodeUVMap")
    uv_node.name = f"Gridlock_SourceUV_{uv_name}"
    uv_node.label = uv_name
    uv_node.uv_map = uv_name
    linked = 0
    for node in image_nodes(material):
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for existing in list(vector.links):
            links.remove(existing)
        links.new(uv_node.outputs["UV"], vector)
        linked += 1
    if linked:
        material["texture_coordinate_uv_map"] = uv_name
        material["gridlock_png_restore_uv_routing"] = uv_name
    return linked


def material_used_by_scene_mesh(material: bpy.types.Material) -> bool:
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if not (obj.get("ue_static_mesh_path") or (obj.name.startswith("Model_") and "__MP_Gridlock.war__" in obj.name)):
            continue
        if any(slot.material == material for slot in obj.material_slots):
            return True
    return False


def restore_material_images(material: bpy.types.Material, maps: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    changed = 0
    for node in image_nodes(material):
        before = image_abs(getattr(node, "image", None))
        row, reason = source_row_for_node(material, node, maps)
        if row is None:
            rows.append({"node": node.name, "before": before, "status": "unchanged", "reason": reason})
            continue
        role = str(row.get("role") or role_from_node(node) or "diffuse").lower()
        image = load_png(str(row.get("png") or ""), role)
        if image is None:
            rows.append({"node": node.name, "before": before, "status": "png_load_failed", "reason": reason, "png": row.get("png", "")})
            continue
        node.image = image
        after = image_abs(image)
        try:
            image.colorspace_settings.name = "sRGB" if role in {"diffuse", "emissive"} else "Non-Color"
        except Exception:
            pass
        if after != before:
            changed += 1
        material[f"gridlock_png_{role}"] = after
        rows.append({"node": node.name, "before": before, "after": after, "role": role, "status": "png_assigned", "reason": reason})
    material["gridlock_png_material_restore"] = "native PNG texture payloads restored from converted cache"
    return {"material": material.name, "ue_material_path": material_path(material), "changed_image_nodes": changed, "nodes": rows}


def main() -> int:
    args = parse_args()
    if args.backup_out and not args.no_save:
        shutil.copyfile(bpy.data.filepath, args.backup_out)

    rows = rows_from_payload(read_json(Path(args.png_rows)))
    maps = build_maps(rows)
    material_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    touched_materials: set[str] = set()

    for material in bpy.data.materials:
        if not image_nodes(material):
            continue
        if not material_used_by_scene_mesh(material):
            continue
        result = restore_material_images(material, maps)
        if result["changed_image_nodes"] or any(node["status"] == "png_assigned" for node in result["nodes"]):
            material_rows.append(result)
            touched_materials.add(material.name)

    relinked_slots = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if not (obj.get("ue_static_mesh_path") or (obj.name.startswith("Model_") and "__MP_Gridlock.war__" in obj.name)):
            continue
        uv_name = object_uv_name(obj)
        if not uv_name:
            continue
        linked = 0
        mats: list[str] = []
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.name not in touched_materials:
                continue
            linked += relink_to_uv(material, uv_name)
            mats.append(material.name)
        if linked:
            relinked_slots += len(mats)
            if len(object_rows) < 120:
                object_rows.append({"object": obj.name, "uv_map": uv_name, "materials": mats, "linked_image_nodes": linked})

    target_names = [
        "SDStitchingProxy_2661_StaticMesh__27170",
        "bsp_gridlock_bld_01_SMesh_Delta__28042",
        "MS_Neutral_Sedan_SMesh__27672",
        "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP",
    ]
    target_summary = {}
    for name in target_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            target_summary[name] = {"exists": bool(obj), "type": obj.type if obj else ""}
            continue
        target_summary[name] = {
            "uv_layers": [layer.name for layer in obj.data.uv_layers],
            "active_uv": obj.data.uv_layers.active.name if obj.data.uv_layers.active else "",
            "materials": [
                {
                    "slot": index,
                    "material": slot.material.name if slot.material else "",
                    "ue_material_path": material_path(slot.material),
                    "images": [image_abs(getattr(node, "image", None)) for node in image_nodes(slot.material)],
                }
                for index, slot in enumerate(obj.material_slots)
            ],
        }

    proof = {
        "blend_path": bpy.data.filepath,
        "png_rows": str(Path(args.png_rows)),
        "policy": "No mesh UVs/transforms rewritten; material image nodes restored to native PNG conversions and routed to existing render UV layers.",
        "png_rows_loaded": len(rows),
        "materials_touched": len(material_rows),
        "relinked_object_samples": object_rows,
        "relinked_slots_estimate": relinked_slots,
        "target_summary": target_summary,
        "material_rows": material_rows[:300],
        "status": "gridlock_png_material_images_restored",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({key: proof[key] for key in ("png_rows_loaded", "materials_touched", "relinked_slots_estimate", "status")}, indent=2))
    if not args.no_save:
        bpy.context.scene["gridlock_png_material_restore"] = proof["status"]
        bpy.context.scene["gridlock_png_material_restore_proof"] = str(out)
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
