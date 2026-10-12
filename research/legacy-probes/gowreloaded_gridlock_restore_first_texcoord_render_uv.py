#!/usr/bin/env python3
"""Restore Gridlock static meshes to first texture-coordinate render UVs.

The visible material repair proved texture files and material identities are
now sane. This pass fixes the other failure mode: some static meshes had
`UV_Source_Render` overwritten with the second 0-1 texcoord channel, which is
appropriate for lightmap/secondary data but wrong for diffuse atlas/material
textures. It copies the original imported first texture UV layer back into the
stable render layer and relinks non-inline texture nodes to that render layer.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


RENDER_UV = "UV_Source_Render"
SOURCE_CANDIDATES = ("UV0_Source_Offset4", "UV0", "UV_Half_Offset4")
INLINE_UV = "UV0_Source_InlineCard"
DEFAULT_TARGETS = [
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2550_StaticMesh__27112",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_smesh_DR__27323",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--render-out", default="")
    parser.add_argument("--preview-copy", default="")
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def visible_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render


def is_staticmesh_object(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and bool(obj.get("ue_static_mesh_path"))


def is_inline_asset(obj: bpy.types.Object) -> bool:
    mesh = obj.data
    if mesh.uv_layers.get(INLINE_UV) is not None:
        return True
    status = str(mesh.get("extract_status", "") or obj.get("extract_status", "")).lower()
    return "inline" in status


def choose_source_layer(mesh: bpy.types.Mesh) -> str:
    for name in SOURCE_CANDIDATES:
        if mesh.uv_layers.get(name) is not None:
            return name
    return ""


def uv_stats(layer: bpy.types.MeshUVLoopLayer | None) -> dict[str, Any]:
    if layer is None:
        return {}
    values: list[tuple[float, float]] = []
    invalid = 0
    for item in layer.data:
        u = float(item.uv.x)
        v = float(item.uv.y)
        if not math.isfinite(u) or not math.isfinite(v):
            invalid += 1
            continue
        values.append((u, v))
    if not values:
        return {"loops": len(layer.data), "invalid": invalid}
    us = [uv[0] for uv in values]
    vs = [uv[1] for uv in values]
    return {
        "loops": len(layer.data),
        "valid": len(values),
        "invalid": invalid,
        "min": [round(min(us), 6), round(min(vs), 6)],
        "max": [round(max(us), 6), round(max(vs), 6)],
        "span": [round(max(us) - min(us), 6), round(max(vs) - min(vs), 6)],
        "sample": [[round(u, 6), round(v, 6)] for u, v in values[:6]],
    }


def max_delta(a: bpy.types.MeshUVLoopLayer, b: bpy.types.MeshUVLoopLayer) -> float:
    count = min(len(a.data), len(b.data))
    delta = 0.0
    for index in range(count):
        av = a.data[index].uv
        bv = b.data[index].uv
        delta = max(delta, abs(float(av.x) - float(bv.x)), abs(float(av.y) - float(bv.y)))
    return delta


def copy_layer(mesh: bpy.types.Mesh, source_name: str) -> dict[str, Any]:
    source = mesh.uv_layers.get(source_name)
    if source is None:
        return {"status": "missing_source", "source": source_name}
    dest = mesh.uv_layers.get(RENDER_UV)
    created = False
    if dest is None:
        dest = mesh.uv_layers.new(name=RENDER_UV)
        created = True
    before_stats = uv_stats(dest)
    before_delta = max_delta(source, dest)
    loops_changed = 0
    for index in range(min(len(source.data), len(dest.data))):
        old = dest.data[index].uv.copy()
        new = source.data[index].uv
        if max(abs(float(old.x) - float(new.x)), abs(float(old.y) - float(new.y))) > 1.0e-6:
            loops_changed += 1
        dest.data[index].uv = new
    mesh.uv_layers.active = dest
    try:
        dest.active_render = True
    except Exception:
        pass
    mesh["gridlock_render_uv_policy"] = "first imported texture coordinate restored"
    mesh["gridlock_render_uv_source_layer"] = source_name
    return {
        "status": "created" if created else "updated",
        "source": source_name,
        "loops": len(dest.data),
        "loops_changed": loops_changed,
        "max_delta_before": round(before_delta, 8),
        "before": before_stats,
        "after": uv_stats(dest),
    }


def material_image_nodes(material: bpy.types.Material | None) -> list[bpy.types.Node]:
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    return [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]


def is_inline_material(material: bpy.types.Material | None) -> bool:
    if material is None:
        return False
    name = material.name.lower()
    return name.startswith("inline_proxy__") or name.startswith("inline_asset_native__") or "inline" in str(material.get("gridlock_inline_masked_proxy_repair", "")).lower()


def relink_material(material: bpy.types.Material | None) -> int:
    if material is None or is_inline_material(material) or material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    imgs = material_image_nodes(material)
    if not imgs:
        return 0
    uv_node = nodes.get("Gridlock_FirstTexCoord_RenderUV")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Gridlock_FirstTexCoord_RenderUV"
        uv_node.label = RENDER_UV
        uv_node.location = (-1040, -320)
    uv_node.uv_map = RENDER_UV
    linked = 0
    for node in imgs:
        vector = node.inputs.get("Vector")
        if vector is None:
            continue
        for link in list(vector.links):
            links.remove(link)
        links.new(uv_node.outputs["UV"], vector)
        linked += 1
    if linked:
        material["texture_coordinate_uv_map"] = RENDER_UV
        material["gridlock_first_texcoord_uv_routing"] = "image nodes routed to UV_Source_Render restored from UV0/UV0_Source_Offset4"
    return linked


def apply_scene() -> dict[str, Any]:
    mesh_results: dict[str, dict[str, Any]] = {}
    object_results: list[dict[str, Any]] = []
    relinked_materials: set[str] = set()
    skipped: list[dict[str, Any]] = []
    for obj in bpy.context.scene.objects:
        if not is_staticmesh_object(obj):
            continue
        if obj.name.startswith("Model_"):
            continue
        if is_inline_asset(obj):
            skipped.append({"object": obj.name, "reason": "inline_asset_uses_card_uv"})
            continue
        mesh = obj.data
        key = mesh.name
        source = choose_source_layer(mesh)
        if not source:
            skipped.append({"object": obj.name, "mesh": mesh.name, "reason": "no_first_uv_source_layer"})
            continue
        if key not in mesh_results:
            mesh_results[key] = copy_layer(mesh, source)
            mesh_results[key]["mesh"] = mesh.name
            mesh_results[key]["ue_full_path"] = mesh.get("ue_full_path", "")
        linked = 0
        mats: list[str] = []
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None:
                continue
            linked += relink_material(mat)
            mats.append(mat.name)
            relinked_materials.add(mat.name)
        if len(object_results) < 200:
            object_results.append(
                {
                    "object": obj.name,
                    "static_mesh_path": obj.get("ue_static_mesh_path", ""),
                    "mesh": mesh.name,
                    "source": source,
                    "linked_image_nodes": linked,
                    "materials": mats[:8],
                }
            )
    changed_meshes = sum(1 for row in mesh_results.values() if int(row.get("loops_changed") or 0) > 0)
    changed_loops = sum(int(row.get("loops_changed") or 0) for row in mesh_results.values())
    return {
        "mesh_datablocks_checked": len(mesh_results),
        "mesh_datablocks_changed": changed_meshes,
        "loops_changed": changed_loops,
        "relinked_materials": len(relinked_materials),
        "mesh_results": list(mesh_results.values()),
        "object_samples": object_results,
        "skipped_samples": skipped[:120],
    }


def bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x)
            mins.y = min(mins.y, world.y)
            mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x)
            maxs.y = max(maxs.y, world.y)
            maxs.z = max(maxs.z, world.z)
    if not math.isfinite(mins.x):
        mins = Vector((-50.0, -50.0, 0.0))
        maxs = Vector((50.0, 50.0, 60.0))
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    radius = max(float(extent.x), float(extent.y), float(extent.z), 25.0) * 0.5
    return {
        "center": [float(center.x), float(center.y), float(center.z)],
        "extent": [float(extent.x), float(extent.y), float(extent.z)],
        "radius": radius,
    }


def select_targets(names: list[str]) -> tuple[list[bpy.types.Object], list[str]]:
    objects: list[bpy.types.Object] = []
    missing: list[str] = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            missing.append(f"{name} (missing)")
        elif not visible_mesh(obj):
            missing.append(f"{name} (hidden)")
        else:
            objects.append(obj)
    return objects, missing


def render_preview(render_out: str, preview_copy: str, targets: list[str]) -> dict[str, Any]:
    objects, missing = select_targets(targets)
    keep = set(objects)
    changed_hide = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        hide = obj not in keep
        if obj.hide_render != hide:
            obj.hide_render = hide
            changed_hide += 1

    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    b = bounds(objects)
    center = Vector(b["center"])
    radius = float(b["radius"])
    cam_data = bpy.data.cameras.get("CAM_MP_Gridlock_FirstTexcoordPreview") or bpy.data.cameras.new("CAM_MP_Gridlock_FirstTexcoordPreview")
    cam = bpy.data.objects.get(cam_data.name) or bpy.data.objects.new(cam_data.name, cam_data)
    if not cam.users_collection:
        scene.collection.objects.link(cam)
    cam.location = center + Vector((-radius * 0.72, -radius * 0.92, radius * 0.52))
    direction = center - Vector(cam.location)
    if direction.length > 0:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data.lens = 28.0
    cam_data.clip_start = 0.05
    cam_data.clip_end = max(120000.0, radius * 30.0)
    scene.camera = cam
    scene.render.filepath = render_out
    Path(render_out).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    if preview_copy:
        Path(preview_copy).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(render_out, preview_copy)
    return {
        "render_out": render_out,
        "preview_copy": preview_copy,
        "visible_targets": len(objects),
        "missing_or_hidden_targets": missing,
        "hide_render_changes": changed_hide,
    }


def target_summary(names: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            out[name] = {"exists": bool(obj)}
            continue
        mesh = obj.data
        out[name] = {
            "mesh": mesh.name,
            "static_mesh_path": obj.get("ue_static_mesh_path", ""),
            "uv_layers": [layer.name for layer in mesh.uv_layers],
            "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
            "uv_stats": {
                key: uv_stats(mesh.uv_layers.get(key))
                for key in ("UV0", "UV0_Source_Offset4", "UV1_Source_Offset8", RENDER_UV, INLINE_UV)
                if mesh.uv_layers.get(key) is not None
            },
        }
    return out


def main() -> int:
    args = parse_args()
    if args.backup_out and not args.no_save:
        shutil.copyfile(bpy.data.filepath, args.backup_out)
    result = apply_scene()
    preview = {}
    if args.render_out:
        preview = render_preview(args.render_out, args.preview_copy, args.targets)
    proof = {
        "blend_path": bpy.data.filepath,
        "policy": "StaticMesh render UV restored from first imported texture-coordinate layer; inline cards and BSP models skipped.",
        "result": result,
        "preview": preview,
        "target_summary": target_summary(args.targets),
        "status": "first_texcoord_render_uv_restored",
        "saved": not args.no_save,
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"status": proof["status"], **{k: result[k] for k in ("mesh_datablocks_checked", "mesh_datablocks_changed", "loops_changed", "relinked_materials")}, "saved": proof["saved"]}, indent=2))
    if not args.no_save:
        bpy.context.scene["gridlock_first_texcoord_render_uv_restore"] = proof["status"]
        bpy.context.scene["gridlock_first_texcoord_render_uv_restore_proof"] = str(out)
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
