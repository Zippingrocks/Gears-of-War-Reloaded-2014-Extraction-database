#!/usr/bin/env python3
"""Repair MP_Gridlock's main rendered BSP material UV routing.

This is intentionally scoped to one object:
Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP

The cooked UE3 FModelVertexBuffer already contains the texture coordinates used
for this rendered BSP. A later experimental FBspSurf texel projection created
UV_Source_BSP_MaterialTexel and wired the material to it, which made the main
BSP smear in Blender. This pass keeps that diagnostic layer but restores the
active/render UV and all image-node vector links to UV_Source_BSP_RenderTexCoord.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import bpy  # type: ignore


MODEL2_OBJECT = "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP"
NATIVE_RENDER_UV = "UV_Source_BSP_RenderTexCoord"
SHADOW_UV = "UV_Source_BSP_ShadowTexCoord"
MODEL2_POLICY_PATH = Path(__file__).with_name("gowreloaded_gridlock_model2_visual_policy.py")
def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


model2_policy = load_module(MODEL2_POLICY_PATH, "gowr_gridlock_model2_visual_policy")


RETIRED_TEXEL_UVS = {
    "UV_Source_BSP_MaterialTexel",
    "UV_Source_BSP_MaterialTexel_NoVFlip",
    "UV_Source_BSP_Surface",
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(argv)


def image_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    except Exception:
        return str(getattr(image, "filepath", "") or "")


def uv_stats(layer: bpy.types.MeshUVLoopLayer | None) -> dict[str, Any]:
    if layer is None:
        return {"exists": False}
    values: list[tuple[float, float]] = []
    invalid = 0
    for loop_uv in layer.data:
        u = float(loop_uv.uv[0])
        v = float(loop_uv.uv[1])
        if not math.isfinite(u) or not math.isfinite(v):
            invalid += 1
            continue
        values.append((u, v))
    if not values:
        return {"exists": True, "loops": len(layer.data), "valid": 0, "invalid": invalid}
    us = [u for u, _v in values]
    vs = [v for _u, v in values]
    return {
        "exists": True,
        "loops": len(layer.data),
        "valid": len(values),
        "invalid": invalid,
        "min": [min(us), min(vs)],
        "max": [max(us), max(vs)],
        "span": [max(us) - min(us), max(vs) - min(vs)],
        "sample": [[round(u, 6), round(v, 6)] for u, v in values[:8]],
    }


def active_uv_name(mesh: bpy.types.Mesh) -> str:
    return mesh.uv_layers.active.name if mesh.uv_layers.active else ""


def active_render_uv_name(mesh: bpy.types.Mesh) -> str:
    for layer in mesh.uv_layers:
        if getattr(layer, "active_render", False):
            return layer.name
    return ""


def set_active_render_uv(mesh: bpy.types.Mesh, uv_name: str) -> None:
    layer = mesh.uv_layers.get(uv_name)
    if layer is None:
        raise RuntimeError(f"{mesh.name} is missing required UV layer {uv_name}")
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == uv_name:
            mesh.uv_layers.active_index = index
        try:
            candidate.active_render = candidate.name == uv_name
        except Exception:
            pass


def node_role(node: bpy.types.Node) -> str:
    text = " ".join(
        [
            str(getattr(node, "name", "")),
            str(getattr(node, "label", "")),
            str(getattr(getattr(node, "image", None), "name", "")),
            image_path(getattr(node, "image", None)),
        ]
    ).lower()
    if "normal" in text or "_nrm" in text or "_normal" in text:
        return "normal"
    if "spec" in text or "rough" in text or "mask" in text or "alpha" in text:
        return "non_color"
    return "diffuse"


def texture_node_links(material: bpy.types.Material) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not material.use_nodes or material.node_tree is None:
        return rows
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        vector = node.inputs.get("Vector")
        linked = ""
        uv_map = ""
        if vector is not None and vector.links:
            link = vector.links[0]
            linked = f"{link.from_node.name}:{link.from_socket.name}"
            if link.from_node.bl_idname == "ShaderNodeUVMap":
                uv_map = str(getattr(link.from_node, "uv_map", ""))
        image = getattr(node, "image", None)
        rows.append(
            {
                "node": node.name,
                "label": str(getattr(node, "label", "")),
                "image": image.name if image else "",
                "image_path": image_path(image),
                "role": node_role(node),
                "vector_link": linked,
                "uv_map": uv_map,
                "extension": str(getattr(node, "extension", "")),
            }
        )
    return rows


def ensure_native_uv_node(material: bpy.types.Material) -> bpy.types.Node:
    if not material.use_nodes:
        material.use_nodes = True
    if material.node_tree is None:
        raise RuntimeError(f"{material.name} has no node tree")
    nodes = material.node_tree.nodes
    uv_node = nodes.get("Model2_BSP_NativeRenderUV")
    if uv_node is None:
        uv_node = nodes.get(f"Gridlock_SourceUV_{NATIVE_RENDER_UV}")
    if uv_node is None or uv_node.bl_idname != "ShaderNodeUVMap":
        uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "Model2_BSP_NativeRenderUV"
    uv_node.label = NATIVE_RENDER_UV
    uv_node.uv_map = NATIVE_RENDER_UV
    uv_node.location = (-780, 120)
    return uv_node


def repair_material(material: bpy.types.Material) -> dict[str, Any]:
    if not material.use_nodes or material.node_tree is None:
        return {"material": material.name, "status": "no_nodes"}
    before = texture_node_links(material)
    uv_node = ensure_native_uv_node(material)
    links = material.node_tree.links
    changed_links = 0
    texture_nodes = [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]
    role_counts: dict[str, int] = {}
    for node in texture_nodes:
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for existing in list(vector.links):
            links.remove(existing)
        links.new(uv_node.outputs["UV"], vector)
        changed_links += 1
        node.extension = "REPEAT"
        role = node_role(node)
        role_counts[role] = role_counts.get(role, 0) + 1
        if role == "normal":
            node.name = "Model2_BSP_Normal_NativeRenderUV"
        elif role == "diffuse" and role_counts[role] == 1:
            node.name = "Model2_BSP_Diffuse_NativeRenderUV"
        elif role == "diffuse":
            node.name = f"Model2_BSP_Diffuse_NativeRenderUV_{role_counts[role]}"
        else:
            node.name = f"Model2_BSP_Texture_NativeRenderUV_{role_counts[role]}"
        image = getattr(node, "image", None)
        if image is not None:
            try:
                image.colorspace_settings.name = "Non-Color" if role in {"normal", "non_color"} else "sRGB"
            except Exception:
                pass
    material["texture_coordinate_uv_map"] = NATIVE_RENDER_UV
    material["gridlock_model2_bsp_fix"] = "main BSP material image nodes routed to native FModelVertexBuffer TexCoord UVs"
    material["gridlock_model2_bsp_uv_policy"] = (
        "Use UV_Source_BSP_RenderTexCoord from cooked UE3 FModelVertexBuffer; "
        "UV_Source_BSP_MaterialTexel is retained only as a retired diagnostic layer."
    )
    material["gridlock_model2_retired_uv_layers"] = ",".join(sorted(RETIRED_TEXEL_UVS))
    return {
        "material": material.name,
        "status": "repaired",
        "image_nodes_relinked": changed_links,
        "before": before,
        "after": texture_node_links(material),
    }


def object_state(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    return {
        "object": obj.name,
        "mesh": mesh.name,
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "active_uv": active_uv_name(mesh),
        "active_render_uv": active_render_uv_name(mesh),
        "uv_layers": [layer.name for layer in mesh.uv_layers],
        "uv_stats": {layer.name: uv_stats(layer) for layer in mesh.uv_layers},
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_select": bool(obj.hide_select),
        "materials": [slot.material.name if slot.material else "" for slot in obj.material_slots],
        "custom_props": {key: obj[key] for key in obj.keys()},
        "mesh_custom_props": {key: mesh[key] for key in mesh.keys()},
    }


def main() -> int:
    args = parse_args()
    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"missing mesh object: {MODEL2_OBJECT}")

    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    if not args.no_save and bpy.data.filepath:
        if args.backup_out:
            backup_path = Path(args.backup_out)
        else:
            source = Path(bpy.data.filepath)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = source.with_name(f"{source.stem}.before_model2_main_bsp_native_uv_repair_{stamp}{source.suffix}")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bpy.data.filepath, backup_path)
        backup = str(backup_path)

    before = object_state(obj)
    mesh = obj.data
    set_active_render_uv(mesh, NATIVE_RENDER_UV)
    native_policy = (
        "Use UV_Source_BSP_RenderTexCoord from the cooked UE3 FModelVertexBuffer. "
        "UV_Source_BSP_MaterialTexel/NoVFlip are retained only as retired diagnostic projections "
        "and must not drive the main BSP material."
    )
    obj["gridlock_bsp_surface_uv_layer"] = NATIVE_RENDER_UV
    obj["gridlock_bsp_lightmap_uv_layer"] = SHADOW_UV
    obj["gridlock_model2_bsp_fix"] = "native render-buffer geometry with material routed to FModelVertexBuffer TexCoord"
    obj["gridlock_model2_bsp_uv_policy"] = native_policy
    obj["gridlock_model2_retired_uv_layers"] = ",".join(sorted(RETIRED_TEXEL_UVS))
    mesh["gridlock_bsp_surface_uv_layer"] = NATIVE_RENDER_UV
    mesh["gridlock_bsp_lightmap_uv_layer"] = SHADOW_UV
    mesh["gridlock_bsp_surface_uv_source"] = native_policy
    mesh["gridlock_model2_bsp_fix"] = obj["gridlock_model2_bsp_fix"]
    mesh["gridlock_model2_bsp_uv_policy"] = native_policy
    mesh["gridlock_model2_renderbuffer_texel_uv_fix"] = (
        "retired diagnostic layer provenance only; main BSP render path uses UV_Source_BSP_RenderTexCoord"
    )

    material_results = []
    for slot in obj.material_slots:
        if slot.material is not None:
            material_results.append(repair_material(slot.material))

    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        obj,
        reason="model2_main_bsp_native_uv_repair",
    )
    after = object_state(obj)
    proof = {
        "blend_path": bpy.data.filepath,
        "backup": backup,
        "status": "model2_main_bsp_native_render_uv_repaired",
        "scope": MODEL2_OBJECT,
        "policy": (
            "Only the main rendered BSP object was edited. Geometry, transforms, static meshes, "
            "Delta SMeshes, decals, water, skybox, and lighting were left untouched."
        ),
        "source_native_basis": {
            "render_uv": NATIVE_RENDER_UV,
            "shadow_uv": SHADOW_UV,
            "retired_diagnostic_uvs": sorted(RETIRED_TEXEL_UVS),
        },
        "before": before,
        "after": after,
        "material_results": material_results,
        "model2_visual_policy": model2_policy_result,
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    if not args.no_save:
        bpy.context.scene["gridlock_model2_main_bsp_native_uv_repair"] = str(proof_out)
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"status": proof["status"], "proof_out": str(proof_out), "backup": backup}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
