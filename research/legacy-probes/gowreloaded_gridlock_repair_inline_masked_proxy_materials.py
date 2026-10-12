#!/usr/bin/env python3
"""Turn Gridlock inline proxy specular/mask fallbacks into transparent overlays.

Some Reloaded MP_Gridlock inline StaticMesh streams have no decoded StaticMesh
sections and no native diffuse binding. Earlier passes bound their only
available texture as an opaque base color so the scene was textured, but those
materials are really decal/shadow-style mask overlays. This pass keeps the
source texture and geometry, then rebuilds the material as a transparent
overlay using grayscale texture luminance for alpha.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


INLINE_CARD_UV = "UV0_Source_InlineCard"
OFFSET_UV = "UV0_Source_Offset4"
TARGET_TOKENS = (
    "traffic_tattered_crossing",
    "cloudshadow_delta_mat_mic",
)


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def material_images(material: bpy.types.Material) -> list[bpy.types.Image]:
    if not material.use_nodes or material.node_tree is None:
        return []
    images: list[bpy.types.Image] = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            images.append(node.image)
    return images


def is_inline_mask_candidate(material: bpy.types.Material) -> bool:
    name = material.name.lower()
    if not (name.startswith("inline_proxy__") or name.startswith("inline_asset_native__")):
        return False
    if "__specular_base" not in name and str(material.get("visual_base_role", "")).lower() != "specular":
        return False
    return any(token in name for token in TARGET_TOKENS)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def clear_nodes(material: bpy.types.Material) -> None:
    assert material.node_tree is not None
    for node in list(material.node_tree.nodes):
        material.node_tree.nodes.remove(node)


def ensure_inline_uv(obj: bpy.types.Object) -> str:
    mesh = obj.data
    source = mesh.uv_layers.get(INLINE_CARD_UV) or mesh.uv_layers.get(OFFSET_UV) or mesh.uv_layers.active
    target = mesh.uv_layers.get(INLINE_CARD_UV)
    if target is None:
        target = mesh.uv_layers.new(name=INLINE_CARD_UV)
        if source is not None:
            for index in range(min(len(target.data), len(source.data))):
                target.data[index].uv = source.data[index].uv
    for index, layer in enumerate(mesh.uv_layers):
        if layer.name == INLINE_CARD_UV:
            mesh.uv_layers.active_index = index
            break
    try:
        target.active_render = True
    except Exception:
        pass
    obj["gridlock_inline_masked_proxy_uv"] = INLINE_CARD_UV
    return INLINE_CARD_UV


def overlay_settings(material: bpy.types.Material) -> dict[str, Any]:
    name = material.name.lower()
    if "cloudshadow" in name:
        return {
            "base_color": (0.015, 0.014, 0.013, 1.0),
            "diffuse_color": (0.015, 0.014, 0.013, 0.18),
            "alpha_low": 0.0,
            "alpha_high": 0.24,
            "ramp_low": 0.12,
            "ramp_high": 0.92,
            "roughness": 1.0,
            "overlay_class": "soft_cloud_shadow_mask",
        }
    return {
        "base_color": (0.58, 0.54, 0.46, 1.0),
        "diffuse_color": (0.58, 0.54, 0.46, 0.42),
        "alpha_low": 0.0,
        "alpha_high": 0.62,
        "ramp_low": 0.08,
        "ramp_high": 0.88,
        "roughness": 0.94,
        "overlay_class": "traffic_crossing_specular_mask_decal",
    }


def rebuild_material_as_overlay(material: bpy.types.Material, image: bpy.types.Image) -> dict[str, Any]:
    settings = overlay_settings(material)
    material.use_nodes = True
    material.diffuse_color = settings["diffuse_color"]
    material.blend_method = "BLEND"
    material.use_nodes = True
    try:
        material.surface_render_method = "BLENDED"
    except Exception:
        pass
    try:
        material.show_transparent_back = True
    except Exception:
        pass

    clear_nodes(material)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (560, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    base_input = principled_input(bsdf, ("Base Color",))
    alpha_input = principled_input(bsdf, ("Alpha",))
    rough_input = principled_input(bsdf, ("Roughness",))
    if base_input is not None:
        base_input.default_value = settings["base_color"]
    if alpha_input is not None:
        alpha_input.default_value = settings["alpha_high"]
    if rough_input is not None:
        rough_input.default_value = settings["roughness"]

    uv = nodes.new("ShaderNodeUVMap")
    uv.name = "InlineProxy_DecalCardUV"
    uv.label = INLINE_CARD_UV
    uv.location = (-740, 120)
    uv.uv_map = INLINE_CARD_UV

    tex = nodes.new("ShaderNodeTexImage")
    tex.name = "InlineProxy_MaskTexture"
    tex.label = "Source mask/specular texture"
    tex.location = (-500, 120)
    tex.image = image
    tex.extension = "CLIP"
    links.new(uv.outputs["UV"], tex.inputs["Vector"])

    bw = nodes.new("ShaderNodeRGBToBW")
    bw.name = "InlineProxy_TextureLuminance"
    bw.location = (-250, -80)
    links.new(tex.outputs["Color"], bw.inputs["Color"])

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "InlineProxy_OverlayAlphaRamp"
    ramp.location = (-40, -90)
    ramp.color_ramp.elements[0].position = settings["ramp_low"]
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, settings["alpha_low"])
    ramp.color_ramp.elements[1].position = settings["ramp_high"]
    ramp.color_ramp.elements[1].color = (
        settings["alpha_high"],
        settings["alpha_high"],
        settings["alpha_high"],
        settings["alpha_high"],
    )
    links.new(bw.outputs["Val"], ramp.inputs["Fac"])
    if alpha_input is not None:
        links.new(ramp.outputs["Color"], alpha_input)

    material["gridlock_inline_masked_proxy_repair"] = "specular/mask-only inline proxy converted from opaque base to transparent overlay"
    material["gridlock_inline_masked_proxy_uv_map"] = INLINE_CARD_UV
    material["gridlock_inline_masked_proxy_overlay_class"] = settings["overlay_class"]
    material["gridlock_inline_masked_proxy_source_image"] = str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    return {
        "material": material.name,
        "overlay_class": settings["overlay_class"],
        "source_image": material["gridlock_inline_masked_proxy_source_image"],
        "alpha_high": settings["alpha_high"],
        "uv_map": INLINE_CARD_UV,
    }


def main() -> int:
    args = parse_args()
    candidates = [material for material in bpy.data.materials if is_inline_mask_candidate(material)]
    material_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for material in candidates:
        images = material_images(material)
        if not images:
            skipped.append({"material": material.name, "reason": "no_image_nodes"})
            continue
        material_rows.append(rebuild_material_as_overlay(material, images[0]))

    repaired_names = {row["material"] for row in material_rows}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        mats = [slot.material for slot in obj.material_slots if slot.material]
        if not any(mat.name in repaired_names for mat in mats):
            continue
        uv_name = ensure_inline_uv(obj)
        object_rows.append(
            {
                "object": obj.name,
                "static_mesh_path": obj.get("ue_static_mesh_path", ""),
                "materials": [mat.name for mat in mats if mat.name in repaired_names],
                "uv_layers": [layer.name for layer in obj.data.uv_layers],
                "active_uv": obj.data.uv_layers.active.name if obj.data.uv_layers.active else "",
                "overlay_uv": uv_name,
            }
        )

    proof = {
        "blend_path": bpy.data.filepath,
        "policy": "Inline proxy/asset native materials that only had specular mask textures are transparent overlays, not opaque diffuse surfaces.",
        "candidate_materials": len(candidates),
        "repaired_materials": len(material_rows),
        "repaired_objects": len(object_rows),
        "material_rows": material_rows,
        "object_rows": object_rows,
        "skipped": skipped,
        "target_sd_stitching_proxy_2661": next(
            (row for row in object_rows if row["object"] == "SDStitchingProxy_2661_StaticMesh__27170"),
            {},
        ),
        "status": "inline_masked_proxy_materials_repaired",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_inline_masked_proxy_repair"] = proof["status"]
    bpy.context.scene["gridlock_inline_masked_proxy_repair_proof"] = str(out)
    print(json.dumps({key: proof[key] for key in ("candidate_materials", "repaired_materials", "repaired_objects", "target_sd_stitching_proxy_2661", "status")}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if material_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
