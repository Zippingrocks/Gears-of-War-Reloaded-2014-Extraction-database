#!/usr/bin/env python3
"""Harden MP_Gridlock materials for Blender viewport fidelity.

This pass fixes two persistent visual failure modes:

* UE mask/spec-only inline proxy cards showing as opaque colored sheets.
* Opaque StaticMesh/BSP materials inheriting UE packed-channel alpha/overstrong
  normal behavior that Blender displays very differently without UE's shader
  graph and tangent basis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


RENDER_UV_LAYER = "UV_Source_Render"
INLINE_CARD_UV = "UV0_Source_InlineCard"
TRANSPARENT_TOKENS = (
    "inline_proxy__",
    "godray",
    "cloudshadow",
    "decal",
    "blood",
    "water",
    "glass",
    "windowpane",
    "puddle",
    "steam",
    "smoke",
)
INLINE_OVERLAY_TOKENS = (
    "traffic_tattered_crossing",
    "cloudshadow_delta_mat_mic",
)


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--opaque-normal-strength", type=float, default=0.22)
    parser.add_argument("--vehicle-normal-strength", type=float, default=0.16)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def is_transparent_material(material: bpy.types.Material) -> bool:
    text = " ".join(
        [
            material.name,
            str(material.get("ue_material_path", "")),
            str(material.get("source_material_path", "")),
            str(material.get("gridlock_inline_masked_proxy_overlay_class", "")),
        ]
    ).lower()
    return any(token in text for token in TRANSPARENT_TOKENS)


def is_inline_overlay_material(material: bpy.types.Material) -> bool:
    name = material.name.lower()
    if not (name.startswith("inline_proxy__") or material.get("gridlock_inline_masked_proxy_overlay_class")):
        return False
    return any(token in name for token in INLINE_OVERLAY_TOKENS)


def material_text(material: bpy.types.Material) -> str:
    return " ".join(
        [
            material.name,
            str(material.get("ue_material_path", "")),
            str(material.get("source_material_path", "")),
            str(material.get("decoded_diffuse_dds", "")),
        ]
    ).lower()


def image_nodes(material: bpy.types.Material) -> list[bpy.types.Node]:
    if not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]


def first_image(material: bpy.types.Material) -> bpy.types.Image | None:
    for node in image_nodes(material):
        image = getattr(node, "image", None)
        if image is not None:
            return image
    return None


def clear_nodes(material: bpy.types.Material) -> None:
    assert material.node_tree is not None
    for node in list(material.node_tree.nodes):
        material.node_tree.nodes.remove(node)


def set_material_transparency_mode(material: bpy.types.Material, transparent: bool) -> None:
    if transparent:
        material.blend_method = "HASHED"
        try:
            material.surface_render_method = "BLENDED"
        except Exception:
            pass
        try:
            material.show_transparent_back = True
        except Exception:
            pass
        return
    material.blend_method = "OPAQUE"
    try:
        material.surface_render_method = "DITHERED"
    except Exception:
        pass
    try:
        material.show_transparent_back = False
    except Exception:
        pass


def rebuild_inline_overlay(material: bpy.types.Material, image: bpy.types.Image) -> dict[str, Any]:
    name = material.name.lower()
    cloudshadow = "cloudshadow" in name
    traffic = "traffic_tattered_crossing" in name
    color = (0.015, 0.014, 0.012, 1.0) if cloudshadow else (0.58, 0.54, 0.46, 1.0)
    alpha = 0.18 if cloudshadow else 0.46
    ramp_low = 0.18 if cloudshadow else 0.08
    ramp_high = 0.92 if cloudshadow else 0.88

    material.use_nodes = True
    material.diffuse_color = (color[0], color[1], color[2], alpha)
    set_material_transparency_mode(material, True)
    clear_nodes(material)
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (620, 0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (330, -110)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (330, 110)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (520, 0)
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(bsdf.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    base_input = principled_input(bsdf, ("Base Color",))
    alpha_input = principled_input(bsdf, ("Alpha",))
    rough_input = principled_input(bsdf, ("Roughness",))
    if base_input is not None:
        base_input.default_value = color
    if alpha_input is not None:
        alpha_input.default_value = alpha
    if rough_input is not None:
        rough_input.default_value = 1.0

    uv = nodes.new("ShaderNodeUVMap")
    uv.name = "InlineProxy_OverlayUV"
    uv.label = INLINE_CARD_UV
    uv.uv_map = INLINE_CARD_UV
    uv.location = (-780, 120)
    tex = nodes.new("ShaderNodeTexImage")
    tex.name = "InlineProxy_MaskTexture"
    tex.label = "Source mask/specular texture"
    tex.image = image
    tex.extension = "CLIP"
    tex.location = (-540, 120)
    links.new(uv.outputs["UV"], tex.inputs["Vector"])

    bw = nodes.new("ShaderNodeRGBToBW")
    bw.name = "InlineProxy_Luminance"
    bw.location = (-300, -70)
    links.new(tex.outputs["Color"], bw.inputs["Color"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "InlineProxy_OverlayAlpha"
    ramp.location = (-90, -70)
    ramp.color_ramp.elements[0].position = ramp_low
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 0.0)
    ramp.color_ramp.elements[1].position = ramp_high
    ramp.color_ramp.elements[1].color = (alpha, alpha, alpha, alpha)
    links.new(bw.outputs["Val"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], mix.inputs["Fac"])

    material["gridlock_material_viewport_hardening"] = "inline mask/spec proxy rebuilt as transparent shader mix"
    material["gridlock_inline_masked_proxy_overlay_class"] = "soft_cloud_shadow_mask" if cloudshadow else "traffic_crossing_mask_overlay"
    material["texture_coordinate_uv_map"] = INLINE_CARD_UV
    return {
        "material": material.name,
        "image": image.name,
        "overlay": material["gridlock_inline_masked_proxy_overlay_class"],
        "alpha": alpha,
        "traffic": traffic,
        "cloudshadow": cloudshadow,
    }


def ensure_opaque_static_material(material: bpy.types.Material, normal_strength: float) -> dict[str, Any]:
    row: dict[str, Any] = {"material": material.name, "normal_nodes_tuned": 0, "alpha_links_removed": 0}
    material.use_nodes = True
    if material.node_tree is None:
        return row
    set_material_transparency_mode(material, False)
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeBsdfPrincipled":
            continue
        alpha_input = principled_input(node, ("Alpha",))
        if alpha_input is not None:
            for link in list(alpha_input.links):
                material.node_tree.links.remove(link)
                row["alpha_links_removed"] += 1
            alpha_input.default_value = 1.0
        spec_input = principled_input(node, ("Specular IOR Level", "Specular"))
        if spec_input is not None and not spec_input.links:
            spec_input.default_value = 0.28
        rough_input = principled_input(node, ("Roughness",))
        if rough_input is not None and not rough_input.links:
            rough_input.default_value = 0.82
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeNormalMap":
            continue
        if "Strength" in node.inputs:
            before = float(node.inputs["Strength"].default_value)
            node.inputs["Strength"].default_value = normal_strength
            if abs(before - normal_strength) > 1.0e-6:
                row["normal_nodes_tuned"] += 1
        try:
            node.space = "TANGENT"
        except Exception:
            pass
    material["gridlock_material_viewport_hardening"] = "opaque static/BSP material alpha clamped; normal strength restrained for Blender tangent basis"
    material["gridlock_opaque_normal_strength"] = float(normal_strength)
    return row


def ensure_inline_uv_on_users(material: bpy.types.Material) -> int:
    touched = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if not any(slot.material == material for slot in obj.material_slots):
            continue
        mesh = obj.data
        source = mesh.uv_layers.get(INLINE_CARD_UV) or mesh.uv_layers.get(RENDER_UV_LAYER) or mesh.uv_layers.active
        target = mesh.uv_layers.get(INLINE_CARD_UV)
        if target is None:
            target = mesh.uv_layers.new(name=INLINE_CARD_UV)
            if source is not None:
                for index in range(min(len(source.data), len(target.data))):
                    target.data[index].uv = source.data[index].uv
        mesh.uv_layers.active = target
        try:
            target.active_render = True
        except Exception:
            pass
        obj["gridlock_inline_overlay_uv_hardened"] = INLINE_CARD_UV
        touched += 1
    return touched


def main() -> int:
    args = parse_args()
    overlay_rows: list[dict[str, Any]] = []
    opaque_rows: list[dict[str, Any]] = []
    skipped_overlay: list[dict[str, Any]] = []
    for material in bpy.data.materials:
        if not material.use_nodes or material.node_tree is None:
            continue
        if is_inline_overlay_material(material):
            image = first_image(material)
            if image is None:
                skipped_overlay.append({"material": material.name, "reason": "no_image"})
                continue
            row = rebuild_inline_overlay(material, image)
            row["objects_touched"] = ensure_inline_uv_on_users(material)
            overlay_rows.append(row)
            continue
        if is_transparent_material(material):
            set_material_transparency_mode(material, True)
            continue
        strength = float(args.vehicle_normal_strength) if any(token in material_text(material) for token in ("vehicle", "car", "sedan")) else float(args.opaque_normal_strength)
        row = ensure_opaque_static_material(material, strength)
        if row["normal_nodes_tuned"] or row["alpha_links_removed"]:
            opaque_rows.append(row)

    proof = {
        "blend_path": bpy.data.filepath,
        "policy": {
            "inline_cards": "mask/spec-only proxy materials are transparent shader overlays, not opaque diffuse sheets",
            "opaque_surfaces": "non-transparent static/BSP materials force opaque alpha and restrained normal strength",
        },
        "summary": {
            "inline_overlay_materials_rebuilt": len(overlay_rows),
            "inline_overlay_objects_touched": sum(int(row.get("objects_touched", 0)) for row in overlay_rows),
            "opaque_materials_tuned": len(opaque_rows),
            "opaque_normal_nodes_tuned": sum(int(row.get("normal_nodes_tuned", 0)) for row in opaque_rows),
            "opaque_alpha_links_removed": sum(int(row.get("alpha_links_removed", 0)) for row in opaque_rows),
            "skipped_overlay": len(skipped_overlay),
        },
        "overlay_rows": overlay_rows,
        "opaque_rows_sample": opaque_rows[:120],
        "skipped_overlay": skipped_overlay,
        "status": "gridlock_material_viewport_hardening_applied",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_material_viewport_hardening"] = proof["status"]
    bpy.context.scene["gridlock_material_viewport_hardening_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
