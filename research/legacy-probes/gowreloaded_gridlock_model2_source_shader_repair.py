#!/usr/bin/env python3
"""Rebuild Gridlock Model_2 BSP material from the decoded source graph.

Scope is deliberately narrow: this edits only
Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP.
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
SCENE_DIR = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12"
)
TEXTURE_DIR = SCENE_DIR / "model2_source_shader_textures"
DIFFUSE_PNG = TEXTURE_DIR / "EphyraCity_Stairtech01_PE_Tex__source_diffuse.png"
MAIN_NORMAL_PNG = TEXTURE_DIR / "EphyraCity_Stairtech01_PE_Normal__OpenGL_Gflip.png"
DETAIL_NORMAL_PNG = TEXTURE_DIR / "crackle3_detail_ogl.png"
SOURCE_GRAPH_PROOF = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Graph_Probe_2026_08_15\gridlock_model2_stairtech_material_graph_probe_2026_08_15.json"
)
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


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", default=str(SCENE_DIR / "gridlock_model2_source_shader_repair_2026_08_15.json"))
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--main-normal-strength", type=float, default=0.135)
    parser.add_argument("--detail-normal-strength", type=float, default=0.055)
    parser.add_argument("--detail-tiling", type=float, default=15.0)
    return parser.parse_args(argv)


def ensure_paths() -> None:
    missing = [str(path) for path in (DIFFUSE_PNG, MAIN_NORMAL_PNG, DETAIL_NORMAL_PNG, SOURCE_GRAPH_PROOF) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing required shader repair input(s): {missing}")


def image_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False))
    except Exception:
        return str(getattr(image, "filepath", "") or "")


def load_image(path: Path, colorspace: str) -> bpy.types.Image:
    image = bpy.data.images.load(str(path), check_existing=True)
    try:
        image.colorspace_settings.name = colorspace
    except Exception:
        pass
    return image


def principled_input(node: bpy.types.Node, names: tuple[str, ...]) -> bpy.types.NodeSocket | None:
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def set_input(node: bpy.types.Node, names: tuple[str, ...], value: float | tuple[float, ...]) -> None:
    socket = principled_input(node, names)
    if socket is not None:
        socket.default_value = value


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


def material_image_nodes(material: bpy.types.Material) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not material.use_nodes or material.node_tree is None:
        return rows
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        vector_link = ""
        uv_map = ""
        vector = node.inputs.get("Vector")
        if vector is not None and vector.links:
            link = vector.links[0]
            vector_link = f"{link.from_node.name}:{link.from_socket.name}"
            if link.from_node.bl_idname == "ShaderNodeUVMap":
                uv_map = str(getattr(link.from_node, "uv_map", ""))
        image = getattr(node, "image", None)
        rows.append(
            {
                "node": node.name,
                "label": str(getattr(node, "label", "")),
                "image": image.name if image else "",
                "image_path": image_path(image),
                "colorspace": image.colorspace_settings.name if image else "",
                "extension": str(getattr(node, "extension", "")),
                "vector_link": vector_link,
                "uv_map": uv_map,
            }
        )
    return rows


def add_image_texture(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    name: str,
    label: str,
    image: bpy.types.Image,
    vector_socket: bpy.types.NodeSocket,
    location: tuple[float, float],
) -> bpy.types.Node:
    tex = nodes.new("ShaderNodeTexImage")
    tex.name = name
    tex.label = label
    tex.location = location
    tex.image = image
    tex.extension = "REPEAT"
    links.new(vector_socket, tex.inputs["Vector"])
    return tex


def rebuild_material(args: argparse.Namespace, old_materials: list[str]) -> bpy.types.Material:
    diffuse = load_image(DIFFUSE_PNG, "sRGB")
    main_normal = load_image(MAIN_NORMAL_PNG, "Non-Color")
    detail_normal = load_image(DETAIL_NORMAL_PNG, "Non-Color")

    mat_name = "BSP_NATIVE_GRAPH__COG_City_Ephyra3__EphyraCity_Stairtech01_PE_MAT"
    old = bpy.data.materials.get(mat_name)
    if old is not None and old.users == 0:
        bpy.data.materials.remove(old)
    material = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
    material.use_nodes = True
    material.diffuse_color = (0.42, 0.42, 0.40, 1.0)
    material.blend_method = "OPAQUE"
    if hasattr(material, 'use_screen_refraction'):
        material.use_screen_refraction = False

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)

    output = nodes.new("ShaderNodeOutputMaterial")
    output.name = "SourceGraph_Output"
    output.location = (520, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "SourceGraph_Principled_GearsUE3"
    bsdf.location = (250, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    set_input(bsdf, ("Roughness",), 0.72)
    set_input(bsdf, ("Metallic",), 0.0)
    set_input(bsdf, ("Specular IOR Level", "Specular"), 0.18)
    set_input(bsdf, ("Alpha",), 1.0)

    uv = nodes.new("ShaderNodeUVMap")
    uv.name = "SourceGraph_UV_RenderTexCoord"
    uv.label = NATIVE_RENDER_UV
    uv.location = (-900, 160)
    uv.uv_map = NATIVE_RENDER_UV

    detail_mapping = nodes.new("ShaderNodeMapping")
    detail_mapping.name = "SourceGraph_TextureCoordinate6_Tiling15"
    detail_mapping.label = "MaterialExpressionTextureCoordinate_6 Tiling=15"
    detail_mapping.location = (-640, -300)
    if "Scale" in detail_mapping.inputs:
        detail_mapping.inputs["Scale"].default_value[0] = float(args.detail_tiling)
        detail_mapping.inputs["Scale"].default_value[1] = float(args.detail_tiling)
        detail_mapping.inputs["Scale"].default_value[2] = 1.0
    links.new(uv.outputs["UV"], detail_mapping.inputs["Vector"])

    diffuse_tex = add_image_texture(
        nodes,
        links,
        "SourceGraph_TextureSample_1_Diffuse",
        "TextureSample_1: EphyraCity_Stairtech01_PE_Tex",
        diffuse,
        uv.outputs["UV"],
        (-600, 220),
    )
    base_color = principled_input(bsdf, ("Base Color",))
    if base_color is not None:
        links.new(diffuse_tex.outputs["Color"], base_color)

    main_tex = add_image_texture(
        nodes,
        links,
        "SourceGraph_TextureSample_0_MainNormal_OpenGL",
        "TextureSample_0: EphyraCity_Stairtech01_PE_Normal (G flipped)",
        main_normal,
        uv.outputs["UV"],
        (-600, -70),
    )
    detail_tex = add_image_texture(
        nodes,
        links,
        "SourceGraph_TextureSample_6_DetailNormal_Tiling15_OpenGL",
        "TextureSample_6: Crackle3 detail normal fallback (G flipped)",
        detail_normal,
        detail_mapping.outputs["Vector"],
        (-360, -315),
    )

    main_n = nodes.new("ShaderNodeNormalMap")
    main_n.name = "SourceGraph_MainNormal_Strength"
    main_n.location = (-130, -90)
    main_n.inputs["Strength"].default_value = float(args.main_normal_strength)
    links.new(main_tex.outputs["Color"], main_n.inputs["Color"])

    detail_n = nodes.new("ShaderNodeNormalMap")
    detail_n.name = "SourceGraph_DetailNormal_Tiling15_Strength"
    detail_n.location = (-130, -315)
    detail_n.inputs["Strength"].default_value = float(args.detail_normal_strength)
    links.new(detail_tex.outputs["Color"], detail_n.inputs["Color"])

    add = nodes.new("ShaderNodeVectorMath")
    add.name = "SourceGraph_Normal_Add_Approx"
    add.operation = "ADD"
    add.location = (70, -190)
    links.new(main_n.outputs["Normal"], add.inputs[0])
    links.new(detail_n.outputs["Normal"], add.inputs[1])

    normalize = nodes.new("ShaderNodeVectorMath")
    normalize.name = "SourceGraph_Normal_Normalize_Approx"
    normalize.operation = "NORMALIZE"
    normalize.location = (260, -190)
    links.new(add.outputs["Vector"], normalize.inputs[0])
    normal_socket = principled_input(bsdf, ("Normal",))
    if normal_socket is not None:
        links.new(normalize.outputs["Vector"], normal_socket)

    material["ue_material_path"] = "COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT"
    material["source_graph_proof_json"] = str(SOURCE_GRAPH_PROOF)
    material["texture_coordinate_uv_map"] = NATIVE_RENDER_UV
    material["source_texture_diffuse"] = str(DIFFUSE_PNG)
    material["source_texture_main_normal_opengl"] = str(MAIN_NORMAL_PNG)
    material["source_texture_detail_normal_fallback_opengl"] = str(DETAIL_NORMAL_PNG)
    material["source_detail_normal_reloaded_ref"] = "COG_City_BaseMaterials.COG_City_BaseMat_Crackle3_CP_DetailNormal"
    material["source_detail_normal_reloaded_cache_status"] = "referenced by MP_Gridlock material graph, missing local texture payload; same-named GOW4 Legacy Delta PNG used as labeled fallback"
    material["source_detail_normal_tiling"] = float(args.detail_tiling)
    material["source_normal_green_channel_policy"] = "Reloaded TC_Normalmap/legacy fallback normals converted from DirectX to Blender/OpenGL by green-channel inversion"
    material["gridlock_model2_bsp_fix"] = "rebuilt from decoded UE3 source material graph with native render UV, OpenGL normals, and tiling-15 detail-normal branch"
    material["previous_model2_materials"] = ",".join(old_materials)
    return material


def object_state(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    return {
        "object": obj.name,
        "mesh": mesh.name,
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
        "active_render_uv": next((layer.name for layer in mesh.uv_layers if getattr(layer, "active_render", False)), ""),
        "uv_stats": uv_stats(mesh.uv_layers.get(NATIVE_RENDER_UV)),
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "hide_select": bool(obj.hide_select),
        "materials": [slot.material.name if slot.material else "" for slot in obj.material_slots],
    }


def main() -> int:
    args = parse_args()
    ensure_paths()
    obj = bpy.data.objects.get(MODEL2_OBJECT)
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"missing target mesh object: {MODEL2_OBJECT}")

    proof_out = Path(args.proof_out)
    proof_out.parent.mkdir(parents=True, exist_ok=True)

    backup = ""
    if not args.no_save and bpy.data.filepath:
        if args.backup_out:
            backup_path = Path(args.backup_out)
        else:
            source = Path(bpy.data.filepath)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = source.with_name(f"{source.stem}.before_model2_source_shader_repair_{stamp}{source.suffix}")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bpy.data.filepath, backup_path)
        backup = str(backup_path)

    before = object_state(obj)
    set_active_render_uv(obj.data, NATIVE_RENDER_UV)
    old_materials = [slot.material.name if slot.material else "" for slot in obj.material_slots]
    material = rebuild_material(args, old_materials)
    if not obj.material_slots:
        obj.data.materials.append(material)
    for slot in obj.material_slots:
        slot.material = material
        if hasattr(slot, "link"):
            slot.link = "DATA"

    obj["gridlock_model2_bsp_fix"] = material["gridlock_model2_bsp_fix"]
    obj["gridlock_model2_source_material_graph"] = str(SOURCE_GRAPH_PROOF)
    obj["gridlock_model2_detail_normal_fallback"] = str(DETAIL_NORMAL_PNG)
    obj.data["gridlock_bsp_surface_uv_layer"] = NATIVE_RENDER_UV
    obj.data["gridlock_model2_bsp_fix"] = obj["gridlock_model2_bsp_fix"]

    model2_policy_result = model2_policy.apply_model2_visual_policy(
        bpy,
        obj,
        reason="model2_source_shader_repair",
    )
    after = object_state(obj)
    proof = {
        "status": "model2_source_shader_rebuilt",
        "blend_path": bpy.data.filepath,
        "backup": backup,
        "scope": MODEL2_OBJECT,
        "policy": "Only this BSP object's material slots were replaced, then Model_2 was returned to hidden diagnostic visual-layer policy.",
        "source_graph_proof": str(SOURCE_GRAPH_PROOF),
        "source_graph_findings": {
            "diffuse": "TextureSample_1 -> EphyraCity_Stairtech01_PE_Tex using default/native UV",
            "main_normal": "TextureSample_0 -> EphyraCity_Stairtech01_PE_Normal using default/native UV",
            "detail_normal": "TextureSample_6 -> COG_City_BaseMat_Crackle3_CP_DetailNormal using TextureCoordinate_6 Tiling=15",
            "normal_policy": "DirectX normals green-inverted for Blender/OpenGL tangent convention",
        },
        "before": before,
        "after": after,
        "model2_visual_policy": model2_policy_result,
        "material": {
            "name": material.name,
            "image_nodes": material_image_nodes(material),
            "main_normal_strength": float(args.main_normal_strength),
            "detail_normal_strength": float(args.detail_normal_strength),
            "detail_tiling": float(args.detail_tiling),
            "custom_props": {key: material[key] for key in material.keys()},
        },
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    if not args.no_save:
        bpy.context.scene["gridlock_model2_source_shader_repair"] = str(proof_out)
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({"status": proof["status"], "proof_out": str(proof_out), "backup": backup}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
