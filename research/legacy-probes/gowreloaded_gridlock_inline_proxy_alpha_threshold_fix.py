#!/usr/bin/env python3
"""Tighten Gridlock inline proxy overlay alpha so cards stop rendering as sheets."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


INLINE_CARD_UV = "UV0_Source_InlineCard"
TRAFFIC_TOKEN = "traffic_tattered_crossing"
CLOUD_TOKEN = "cloudshadow"


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def principled_input(node: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in node.inputs:
            return node.inputs[name]
    return None


def texture_image(material: bpy.types.Material) -> bpy.types.Image | None:
    if material.node_tree is None:
        return None
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            return node.image
    path = str(material.get("gridlock_inline_masked_proxy_source_image", "") or material.get("viewport_png_alias", ""))
    if path and Path(path).exists():
        return bpy.data.images.load(path, check_existing=True)
    return None


def is_target_material(material: bpy.types.Material) -> bool:
    name = material.name.lower()
    overlay = str(material.get("gridlock_inline_masked_proxy_overlay_class", "")).lower()
    if not (name.startswith("inline_proxy__") or name.startswith("inline_asset_native__") or overlay):
        return False
    return TRAFFIC_TOKEN in name or "traffic_crossing" in overlay or CLOUD_TOKEN in name or CLOUD_TOKEN in overlay


def clear_nodes(material: bpy.types.Material) -> None:
    assert material.node_tree is not None
    for node in list(material.node_tree.nodes):
        material.node_tree.nodes.remove(node)


def set_transparency(material: bpy.types.Material) -> None:
    material.blend_method = "HASHED"
    try:
        material.surface_render_method = "BLENDED"
    except Exception:
        pass
    try:
        material.show_transparent_back = True
    except Exception:
        pass
    try:
        material.use_backface_culling = False
    except Exception:
        pass


def settings_for(material: bpy.types.Material) -> dict[str, Any]:
    name = material.name.lower()
    overlay = str(material.get("gridlock_inline_masked_proxy_overlay_class", "")).lower()
    if CLOUD_TOKEN in name or CLOUD_TOKEN in overlay:
        return {
            "kind": "cloudshadow",
            "base": (0.018, 0.017, 0.015, 1.0),
            "diffuse": (0.018, 0.017, 0.015, 0.16),
            "alpha_high": 0.18,
            "ramp_low": 0.30,
            "ramp_high": 0.92,
        }
    return {
        "kind": "traffic_crossing_hard_threshold",
        "base": (0.70, 0.68, 0.58, 1.0),
        "diffuse": (0.70, 0.68, 0.58, 0.42),
        "alpha_high": 0.58,
        "ramp_low": 0.48,
        "ramp_high": 0.82,
    }


def rebuild_overlay(material: bpy.types.Material, image: bpy.types.Image) -> dict[str, Any]:
    cfg = settings_for(material)
    material.use_nodes = True
    material.diffuse_color = cfg["diffuse"]
    set_transparency(material)
    clear_nodes(material)
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (680, 0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (360, -120)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (360, 120)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (560, 0)
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(bsdf.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])

    base = principled_input(bsdf, ("Base Color",))
    rough = principled_input(bsdf, ("Roughness",))
    alpha = principled_input(bsdf, ("Alpha",))
    if base is not None:
        base.default_value = cfg["base"]
    if rough is not None:
        rough.default_value = 0.96
    if alpha is not None:
        alpha.default_value = cfg["alpha_high"]

    uv = nodes.new("ShaderNodeUVMap")
    uv.name = "InlineProxy_SourceCardUV"
    uv.label = INLINE_CARD_UV
    uv.uv_map = INLINE_CARD_UV
    uv.location = (-820, 120)
    tex = nodes.new("ShaderNodeTexImage")
    tex.name = "InlineProxy_SourceMaskTexture"
    tex.label = "Source spec/mask texture"
    tex.image = image
    tex.extension = "CLIP"
    tex.location = (-560, 120)
    links.new(uv.outputs["UV"], tex.inputs["Vector"])

    bw = nodes.new("ShaderNodeRGBToBW")
    bw.name = "InlineProxy_SourceLuminance"
    bw.location = (-320, -80)
    links.new(tex.outputs["Color"], bw.inputs["Color"])

    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "InlineProxy_HardAlphaThreshold"
    ramp.location = (-80, -80)
    ramp.color_ramp.elements[0].position = cfg["ramp_low"]
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 0.0)
    ramp.color_ramp.elements[1].position = cfg["ramp_high"]
    ramp.color_ramp.elements[1].color = (
        cfg["alpha_high"],
        cfg["alpha_high"],
        cfg["alpha_high"],
        cfg["alpha_high"],
    )
    links.new(bw.outputs["Val"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], mix.inputs["Fac"])

    material["gridlock_inline_proxy_alpha_threshold_fix"] = "hard luminance threshold prevents opaque sheet rendering"
    material["gridlock_inline_proxy_alpha_threshold_kind"] = cfg["kind"]
    material["gridlock_inline_masked_proxy_uv_map"] = INLINE_CARD_UV
    material["texture_coordinate_uv_map"] = INLINE_CARD_UV
    material["gridlock_inline_proxy_alpha_threshold_values"] = json.dumps(
        {"ramp_low": cfg["ramp_low"], "ramp_high": cfg["ramp_high"], "alpha_high": cfg["alpha_high"]},
        ensure_ascii=True,
    )
    return {
        "material": material.name,
        "kind": cfg["kind"],
        "image": image.name,
        "image_path": str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False)) if image.filepath else "",
        "ramp_low": cfg["ramp_low"],
        "ramp_high": cfg["ramp_high"],
        "alpha_high": cfg["alpha_high"],
    }


def ensure_inline_uv(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    source = mesh.uv_layers.get(INLINE_CARD_UV) or mesh.uv_layers.active
    target = mesh.uv_layers.get(INLINE_CARD_UV)
    created = False
    if target is None:
        target = mesh.uv_layers.new(name=INLINE_CARD_UV)
        created = True
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
    obj["gridlock_inline_proxy_alpha_threshold_uv"] = INLINE_CARD_UV
    return {"object": obj.name, "uv_layers": [layer.name for layer in mesh.uv_layers], "active_uv": mesh.uv_layers.active.name, "created_uv": created}


def main() -> int:
    args = parse_args()
    if args.backup_out and not args.no_save:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copyfile(bpy.data.filepath, backup)

    material_rows = []
    target_materials = []
    skipped = []
    for material in bpy.data.materials:
        if not is_target_material(material):
            continue
        image = texture_image(material)
        if image is None:
            skipped.append({"material": material.name, "reason": "no_source_image"})
            continue
        material_rows.append(rebuild_overlay(material, image))
        target_materials.append(material)

    object_rows = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        if any(slot.material in target_materials for slot in obj.material_slots):
            object_rows.append(ensure_inline_uv(obj))

    proof = {
        "blend_path": bpy.data.filepath,
        "policy": "Only inline proxy overlay materials are changed; bulk StaticMesh UVs, BSP UVs, geometry, and transforms are preserved.",
        "material_count": len(material_rows),
        "object_count": len(object_rows),
        "material_rows": material_rows,
        "object_rows": object_rows,
        "skipped": skipped,
        "target_sd_stitching_proxy_2661": next((row for row in object_rows if row["object"] == "SDStitchingProxy_2661_StaticMesh__27170"), {}),
        "status": "inline_proxy_alpha_threshold_fixed",
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_inline_proxy_alpha_threshold_fix"] = proof["status"]
    bpy.context.scene["gridlock_inline_proxy_alpha_threshold_fix_proof"] = str(out)
    print(json.dumps({k: proof[k] for k in ("material_count", "object_count", "target_sd_stitching_proxy_2661", "status")}, indent=2))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if material_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
