#!/usr/bin/env python3
"""Apply Gridlock source UV channels and material-coordinate repairs in Blender."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


WINDOWPANE_MATERIAL_PATH = "Delta_Window_Hitmeshes01.windowpane_hitmesh_Delta_MAT"

TARGET_OBJECT_NAMES = [
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
    "SDStitchingProxy_2409_StaticMesh__27021",
]


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv-payload", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def set_active_uv(mesh: bpy.types.Mesh, layer_name: str) -> bool:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return False
    for index, candidate in enumerate(mesh.uv_layers):
        if candidate.name == layer_name:
            mesh.uv_layers.active_index = index
            break
    try:
        layer.active_render = True
    except Exception:
        pass
    return True


def apply_layer_to_mesh(mesh: bpy.types.Mesh, layer_name: str, uvs: list[list[float]]) -> dict[str, Any]:
    if len(uvs) < len(mesh.vertices):
        return {
            "status": "skipped_vertex_count_mismatch",
            "layer": layer_name,
            "mesh_vertices": len(mesh.vertices),
            "uv_vertices": len(uvs),
            "loops_written": 0,
        }
    layer = mesh.uv_layers.get(layer_name)
    created = False
    if layer is None:
        layer = mesh.uv_layers.new(name=layer_name)
        created = True
    loops_written = 0
    for loop in mesh.loops:
        vertex_index = loop.vertex_index
        if 0 <= vertex_index < len(uvs):
            layer.data[loop.index].uv = (float(uvs[vertex_index][0]), float(uvs[vertex_index][1]))
            loops_written += 1
    return {
        "status": "created" if created else "updated",
        "layer": layer_name,
        "loops_written": loops_written,
    }


def copy_uv_layer(mesh: bpy.types.Mesh, source_name: str, dest_name: str) -> bool:
    source = mesh.uv_layers.get(source_name)
    if source is None:
        return False
    dest = mesh.uv_layers.get(dest_name)
    if dest is None:
        dest = mesh.uv_layers.new(name=dest_name)
    for index, source_data in enumerate(source.data):
        if index < len(dest.data):
            dest.data[index].uv = source_data.uv
    return True


def apply_uv_payload(payload: dict[str, Any]) -> dict[str, Any]:
    assets = payload.get("assets") or {}
    updated_meshes = 0
    skipped_meshes = 0
    layer_counts: dict[str, int] = {}
    mismatch_samples: list[dict[str, Any]] = []
    target_mesh_paths = set()

    for mesh in bpy.data.meshes:
        full_path = str(mesh.get("ue_full_path", "")).strip()
        if not full_path:
            continue
        asset = assets.get(full_path.lower())
        if not isinstance(asset, dict):
            skipped_meshes += 1
            continue
        layers = asset.get("layers") or {}
        if not isinstance(layers, dict) or not layers:
            skipped_meshes += 1
            continue
        mesh_updated = False
        for layer_name, layer_data in layers.items():
            uvs = layer_data.get("uvs") if isinstance(layer_data, dict) else None
            if not isinstance(uvs, list):
                continue
            result = apply_layer_to_mesh(mesh, str(layer_name), uvs)
            if result["status"].startswith("skipped"):
                if len(mismatch_samples) < 12:
                    mismatch_samples.append({"mesh": mesh.name, "full_path": full_path, **result})
                continue
            layer_counts[str(layer_name)] = layer_counts.get(str(layer_name), 0) + 1
            mesh_updated = True
        recommended = str(asset.get("recommended_diffuse_uv") or "UV0_Source_Offset4")
        if recommended != "UV0_Source_Offset4" and mesh.uv_layers.get("UV0_Source_Offset4") is None:
            if copy_uv_layer(mesh, recommended, "UV0_Source_Offset4"):
                layer_counts["UV0_Source_Offset4_alias"] = layer_counts.get("UV0_Source_Offset4_alias", 0) + 1
        active_name = "UV0_Source_Offset4" if mesh.uv_layers.get("UV0_Source_Offset4") else recommended
        if set_active_uv(mesh, active_name):
            mesh["active_render_uv"] = active_name
        mesh["source_uv_payload"] = "gowreloaded_gridlock_export_uv_channels"
        mesh["source_uv_layers"] = ",".join(layer.name for layer in mesh.uv_layers)
        mesh["uv_material_coordinate_repair"] = "source static vertex UV streams decoded from Reloaded MP_Gridlock.war"
        mesh.update(calc_edges=False)
        if mesh_updated:
            updated_meshes += 1
            if str(full_path).lower().startswith("mp_gridlock_stitchingdata."):
                target_mesh_paths.add(full_path)

    return {
        "updated_mesh_datablocks": updated_meshes,
        "skipped_mesh_datablocks_without_payload": skipped_meshes,
        "layer_mesh_counts": layer_counts,
        "mismatch_samples": mismatch_samples,
        "stitching_mesh_paths_updated": sorted(target_mesh_paths),
    }


def link_material_to_uv0(material: bpy.types.Material) -> dict[str, Any]:
    if not material or not material.use_nodes or not material.node_tree:
        return {"linked": 0, "has_images": False}
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    image_nodes = [node for node in nodes if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None)]
    if not image_nodes:
        return {"linked": 0, "has_images": False}
    uv_node = nodes.get("Source_StaticMesh_UV0")
    if uv_node is None:
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = "Source_StaticMesh_UV0"
        uv_node.label = "Source StaticMesh UV0"
        uv_node.location = (-760, -180)
    try:
        uv_node.uv_map = "UV0_Source_Offset4"
    except Exception:
        pass

    linked = 0
    uv_output = uv_node.outputs.get("UV")
    if uv_output is None:
        return {"linked": 0, "has_images": True}
    for image_node in image_nodes:
        vector_input = image_node.inputs.get("Vector")
        if vector_input is None:
            continue
        for existing in list(vector_input.links):
            links.remove(existing)
        links.new(uv_output, vector_input)
        linked += 1
    material["texture_coordinate_uv_map"] = "UV0_Source_Offset4"
    material["material_placement_repair"] = "explicit source StaticMesh UV0 node linked to DDS texture nodes"
    return {"linked": linked, "has_images": True}


def repair_textured_material_coordinates() -> dict[str, Any]:
    materials_with_images = 0
    texture_nodes_linked = 0
    for material in bpy.data.materials:
        result = link_material_to_uv0(material)
        if result.get("has_images"):
            materials_with_images += 1
            texture_nodes_linked += int(result.get("linked") or 0)
    return {
        "materials_with_dds_image_nodes": materials_with_images,
        "texture_nodes_linked_to_source_uv0": texture_nodes_linked,
    }


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def make_windowpane_material() -> bpy.types.Material:
    material = bpy.data.materials.get(WINDOWPANE_MATERIAL_PATH)
    if material is None:
        material = bpy.data.materials.new(WINDOWPANE_MATERIAL_PATH)
    material.diffuse_color = (0.26, 0.38, 0.44, 0.34)
    material.use_nodes = True
    material["ue_material_path"] = WINDOWPANE_MATERIAL_PATH
    material["source_binding_status"] = "unbound_source_material_path_no_decoded_dds_binding"
    material["visual_repair"] = "transparent smoky glass material for window hitmesh/stitching proxy overrides"
    try:
        material.blend_method = "BLEND"
    except Exception:
        pass
    try:
        material.use_screen_refraction = True
    except Exception:
        pass
    try:
        material.show_transparent_back = True
    except Exception:
        pass
    try:
        material.surface_render_method = "BLENDED"
    except Exception:
        pass

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (360, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (80, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base = principled_input(bsdf, ("Base Color",))
    alpha = principled_input(bsdf, ("Alpha",))
    rough = principled_input(bsdf, ("Roughness",))
    metallic = principled_input(bsdf, ("Metallic",))
    specular = principled_input(bsdf, ("Specular IOR Level", "Specular"))
    transmission = principled_input(bsdf, ("Transmission Weight", "Transmission"))
    if base:
        base.default_value = (0.26, 0.38, 0.44, 0.34)
    if alpha:
        alpha.default_value = 0.34
    if rough:
        rough.default_value = 0.16
    if metallic:
        metallic.default_value = 0.0
    if specular:
        specular.default_value = 0.82
    if transmission:
        transmission.default_value = 0.18
    return material


def repair_windowpane_family() -> dict[str, Any]:
    material = make_windowpane_material()
    objects_repaired = 0
    target_names_repaired: list[str] = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        materials_json = str(obj.get("ue_materials_json", ""))
        static_mesh_path = str(obj.get("ue_static_mesh_path", ""))
        should_repair = WINDOWPANE_MATERIAL_PATH in materials_json
        if not should_repair:
            continue
        if not obj.material_slots:
            obj.data.materials.append(material)
        else:
            obj.material_slots[0].link = "OBJECT"
            obj.material_slots[0].material = material
        obj["windowpane_material_repair"] = "object override source material converted to translucent glass"
        obj["material_texture_placement_fix"] = "source windowpane override had no decoded DDS binding; repaired as transparent Gears-style glass"
        obj["source_windowpane_material_path"] = WINDOWPANE_MATERIAL_PATH
        objects_repaired += 1
        if obj.name in TARGET_OBJECT_NAMES:
            target_names_repaired.append(obj.name)
        if static_mesh_path.lower().startswith("mp_gridlock_stitchingdata."):
            obj["stitching_proxy_material_family"] = "windowpane_hitmesh"
    return {
        "windowpane_material": material.name,
        "windowpane_objects_repaired": objects_repaired,
        "target_windowpane_objects_repaired": sorted(target_names_repaired),
    }


def target_object_audit() -> dict[str, Any]:
    audit: dict[str, Any] = {}
    for name in TARGET_OBJECT_NAMES:
        obj = bpy.data.objects.get(name)
        if obj is None:
            audit[name] = {"exists": False}
            continue
        mesh = obj.data if obj.type == "MESH" else None
        audit[name] = {
            "exists": True,
            "type": obj.type,
            "static_mesh_path": obj.get("ue_static_mesh_path", ""),
            "mesh_name": mesh.name if mesh else "",
            "uv_layers": [layer.name for layer in mesh.uv_layers] if mesh else [],
            "active_render_uv": mesh.get("active_render_uv", "") if mesh else "",
            "materials": [slot.material.name if slot.material else "" for slot in obj.material_slots],
            "windowpane_material_repair": obj.get("windowpane_material_repair", ""),
            "material_texture_placement_fix": obj.get("material_texture_placement_fix", ""),
        }
    return audit


def main() -> int:
    args = parse_args()
    payload_path = Path(args.uv_payload)
    proof_out = Path(args.proof_out)
    payload = read_json(payload_path)
    uv_summary = apply_uv_payload(payload)
    material_summary = repair_textured_material_coordinates()
    window_summary = repair_windowpane_family()
    proof = {
        "blend_path": bpy.data.filepath,
        "uv_payload": str(payload_path),
        "source_scope": payload.get("source_scope", ""),
        "uv_summary": uv_summary,
        "material_coordinate_summary": material_summary,
        "windowpane_summary": window_summary,
        "target_object_audit": target_object_audit(),
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "mesh_datablocks": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "scene_root_direct_objects": len(bpy.context.scene.collection.objects),
        },
    }
    proof_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0 if uv_summary["updated_mesh_datablocks"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
