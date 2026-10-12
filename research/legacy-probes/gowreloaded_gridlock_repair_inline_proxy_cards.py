#!/usr/bin/env python3
"""Repair Gridlock inline StaticMesh proxy cards in the existing Blender scene.

This targets Reloaded MP_Gridlock inline `StaticMesh` exports such as
`SDStitchingProxy_2661_StaticMesh`. Those assets were originally emitted as
diagnostic triangles with no UVs because they do not use the normal UE3
bulk-position/index path. In Blender that produced twisted quads and fallback
pink/green card materials.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


INLINE_UV_NAME = "UV0_Source_InlineCard"
ACTIVE_UV_NAME = "UV0_Source_Offset4"


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--material-cache", required=True)
    parser.add_argument("--png-map", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--backup-out", default="")
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def safe_name(text: str, limit: int = 120) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(text))
    return (clean.strip("._") or "unnamed")[:limit]


def norm_path(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(str(Path(path).resolve(strict=False)))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def read_obj_vertices(path: Path) -> list[tuple[float, float, float]]:
    verts: list[tuple[float, float, float]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            parts = line.split()
            if len(parts) >= 4:
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return verts


def fixed_inline_faces(vertex_count: int, object_name: str) -> list[tuple[int, int, int]]:
    lower = object_name.lower()
    if "rain_cube" in lower and vertex_count >= 8:
        return [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    if vertex_count == 4:
        return [(0, 1, 2), (0, 2, 3)]
    if vertex_count % 4 == 0:
        faces: list[tuple[int, int, int]] = []
        for start in range(0, vertex_count, 4):
            faces.append((start, start + 1, start + 2))
            faces.append((start, start + 2, start + 3))
        return faces
    if vertex_count >= 3:
        return [(0, index, index + 1) for index in range(1, vertex_count - 1)]
    return []


def uv_for_vertex(vertex_index: int) -> tuple[float, float]:
    local = vertex_index % 4
    if local == 0:
        return (0.0, 1.0)
    if local == 1:
        return (1.0, 1.0)
    if local == 2:
        return (1.0, 0.0)
    return (0.0, 0.0)


def write_fixed_inline_obj(asset: dict[str, Any], verts: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> None:
    out_path = Path(str(asset.get("obj_path") or ""))
    if not out_path:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Gears Reloaded MP_Gridlock inline StaticMesh OBJ\n")
        handle.write(f"# source={asset.get('full_path', '')}\n")
        handle.write("# status=inline_staticmesh_stream\n")
        handle.write("# vertex_positions=source_native\n")
        handle.write("# face_order=quad_card_reconstruction_fixed_2026_08_12\n")
        handle.write("# uv_status=inline_card_uv0_inferred_from_quad_order\n")
        handle.write(f"o {safe_name(asset.get('object_name') or asset.get('full_path'))}\n")
        for x, y, z in verts:
            handle.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for index in range(len(verts)):
            u, v = uv_for_vertex(index)
            handle.write(f"vt {u:.6f} {v:.6f}\n")
        for a, b, c in faces:
            handle.write(f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}\n")


def rebuild_mesh(mesh: bpy.types.Mesh, verts: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> dict[str, Any]:
    materials = [material for material in mesh.materials]
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update(calc_edges=False)
    mesh.materials.clear()
    for material in materials:
        mesh.materials.append(material)

    for layer_name in (INLINE_UV_NAME, ACTIVE_UV_NAME):
        layer = mesh.uv_layers.get(layer_name)
        if layer is None:
            layer = mesh.uv_layers.new(name=layer_name)
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                layer.data[loop_index].uv = uv_for_vertex(vertex_index)

    active = mesh.uv_layers.get(ACTIVE_UV_NAME) or mesh.uv_layers.get(INLINE_UV_NAME)
    if active is not None:
        for index, layer in enumerate(mesh.uv_layers):
            if layer.name == active.name:
                mesh.uv_layers.active_index = index
                break
        try:
            active.active_render = True
        except Exception:
            pass
    mesh["uv_status"] = "inline_card_uv0_inferred_from_quad_order"
    mesh["native_face_source"] = "quad_card_reconstruction_fixed_2026_08_12"
    return {"vertices": len(mesh.vertices), "polygons": len(mesh.polygons), "uv_layers": [layer.name for layer in mesh.uv_layers]}


def load_png_map(path: Path) -> dict[str, str]:
    payload = read_json(path)
    by_source: dict[str, str] = {}
    for row in payload.get("rows") or []:
        if row.get("status") != "converted":
            continue
        source = norm_path(str(row.get("source") or ""))
        png = str(row.get("png") or "")
        if source and png and Path(png).exists():
            by_source[source] = png
    return by_source


def image_for_role(role_data: dict[str, Any], png_by_source: dict[str, str]) -> str:
    dds_path = str(role_data.get("dds_path") or "").strip()
    if not dds_path:
        return ""
    return png_by_source.get(norm_path(dds_path), "")


def first_visual_role(binding: dict[str, Any], material_path: str) -> tuple[str, dict[str, Any], str]:
    roles = binding.get("roles") if isinstance(binding, dict) else {}
    if not isinstance(roles, dict):
        return "", {}, ""
    if isinstance(roles.get("diffuse"), dict) and roles["diffuse"].get("dds_path"):
        return "diffuse", roles["diffuse"], "native_diffuse"

    lowered = " ".join(
        [
            str(material_path).lower(),
            " ".join(str(item).lower() for item in binding.get("referenced_textures", []) if item),
        ]
    )
    if any(token in lowered for token in ("traffic", "streetcross", "crossing", "poster", "decal", "paint", "signage")):
        for role in ("specular", "alpha", "mask", "emissive", "normal"):
            value = roles.get(role)
            if isinstance(value, dict) and value.get("dds_path"):
                return role, value, f"{role}_as_visual_base_for_inline_proxy"

    if len(roles) == 1:
        role, value = next(iter(roles.items()))
        if isinstance(value, dict) and value.get("dds_path"):
            return str(role), value, f"{role}_as_only_texture_visual_base"
    return "", {}, ""


def clear_nodes(nodes: bpy.types.Nodes) -> None:
    for node in list(nodes):
        nodes.remove(node)


def principled_input(bsdf: bpy.types.Node, names: tuple[str, ...]):
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def make_inline_material(material_path: str, binding: dict[str, Any], png_by_source: dict[str, str]) -> bpy.types.Material:
    role, role_data, reason = first_visual_role(binding, material_path)
    mat_name = f"INLINE_PROXY__{safe_name(material_path, 90)}"
    if reason and role:
        mat_name += f"__{role}_base"
    material = bpy.data.materials.get(mat_name)
    if material is None:
        material = bpy.data.materials.new(mat_name)
    material.use_nodes = True
    material.diffuse_color = (0.24, 0.24, 0.22, 1.0)
    material["ue_material_path"] = material_path
    material["inline_proxy_material_repair"] = reason or "plain_neutral_no_texture_binding"
    material["texture_binding_status"] = binding.get("binding_status", "") if isinstance(binding, dict) else ""

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    clear_nodes(nodes)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (340, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (120, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base_input = principled_input(bsdf, ("Base Color",))
    alpha_input = principled_input(bsdf, ("Alpha",))
    rough_input = principled_input(bsdf, ("Roughness",))
    if rough_input is not None:
        rough_input.default_value = 0.82

    png_path = image_for_role(role_data, png_by_source) if role_data else ""
    if png_path and base_input is not None:
        image = bpy.data.images.load(png_path, check_existing=True)
        try:
            image.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        image["source_dds_path"] = str(role_data.get("dds_path") or "")
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = "InlineProxy_VisualBase_PNG"
        tex.label = f"{role} visual base"
        tex.location = (-420, 100)
        tex.image = image
        tex.extension = "REPEAT"
        uv = nodes.new("ShaderNodeUVMap")
        uv.name = "InlineProxy_SourceUV0"
        uv.label = ACTIVE_UV_NAME
        uv.location = (-650, 90)
        uv.uv_map = ACTIVE_UV_NAME
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], base_input)
        if alpha_input is not None and "Alpha" in tex.outputs:
            links.new(tex.outputs["Alpha"], alpha_input)
            material.blend_method = "HASHED"
            material.show_transparent_back = True
        material["viewport_png_alias"] = png_path
        material["visual_base_role"] = role
        material["visual_base_source_dds"] = str(role_data.get("dds_path") or "")
    else:
        if base_input is not None:
            base_input.default_value = (0.18, 0.18, 0.17, 1.0)
    return material


def apply_inline_materials(
    obj: bpy.types.Object,
    material_cache: dict[str, Any],
    png_by_source: dict[str, str],
) -> dict[str, Any]:
    info = parse_json_field(obj.get("ue_materials_json"))
    paths = info.get("object_ref_paths_sample") if isinstance(info, dict) else None
    applied: list[dict[str, Any]] = []
    if not isinstance(paths, list) or not paths:
        return {"applied": applied, "reason": "no_object_override_paths"}

    while len(obj.material_slots) < len(paths):
        obj.data.materials.append(None)
    for index, material_path in enumerate(paths):
        clean = str(material_path or "").strip()
        if not clean or clean.lower() in {"none", "null"}:
            continue
        binding = material_cache.get(clean.lower()) or {}
        material = make_inline_material(clean, binding, png_by_source)
        obj.material_slots[index].link = "OBJECT"
        obj.material_slots[index].material = material
        applied.append(
            {
                "slot": index,
                "material_path": clean,
                "binding_status": binding.get("binding_status", "") if isinstance(binding, dict) else "",
                "material": material.name,
                "repair": material.get("inline_proxy_material_repair", ""),
                "visual_base_role": material.get("visual_base_role", ""),
                "viewport_png_alias": material.get("viewport_png_alias", ""),
            }
        )
    obj["inline_proxy_material_repair"] = json.dumps(applied, ensure_ascii=True, separators=(",", ":"))
    return {"applied": applied}


def main() -> None:
    args = parse_args()
    manifest = read_json(Path(args.scene_manifest))
    material_cache = read_json(Path(args.material_cache))
    png_by_source = load_png_map(Path(args.png_map))

    if args.backup_out:
        backup = Path(args.backup_out)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copyfile(bpy.data.filepath, backup)

    assets = [
        asset
        for asset in manifest.get("assets") or []
        if asset.get("extract_status") == "inline_staticmesh_stream"
    ]
    assets_by_path = {str(asset.get("full_path", "")).lower(): asset for asset in assets}
    mesh_rows: list[dict[str, Any]] = []
    material_rows: list[dict[str, Any]] = []
    missing_meshes: list[str] = []

    for asset in assets:
        full_path = str(asset.get("full_path") or "")
        mesh = next((candidate for candidate in bpy.data.meshes if str(candidate.get("ue_full_path", "")).lower() == full_path.lower()), None)
        if mesh is None:
            missing_meshes.append(full_path)
            continue
        obj_path = Path(str(asset.get("obj_path") or ""))
        verts = read_obj_vertices(obj_path) if obj_path.exists() else [(float(v.co.x), float(v.co.y), float(v.co.z)) for v in mesh.vertices]
        faces = fixed_inline_faces(len(verts), str(asset.get("object_name") or full_path))
        before_polys = [list(poly.vertices) for poly in mesh.polygons]
        write_fixed_inline_obj(asset, verts, faces)
        result = rebuild_mesh(mesh, verts, faces)
        mesh_rows.append(
            {
                "asset": full_path,
                "object_name": asset.get("object_name", ""),
                "obj_path": str(obj_path),
                "before_polygons": before_polys,
                "after_polygons": [list(face) for face in faces],
                **result,
            }
        )

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        asset_path = str(obj.get("ue_static_mesh_path") or "").lower()
        if asset_path not in assets_by_path:
            continue
        mat_result = apply_inline_materials(obj, material_cache, png_by_source)
        material_rows.append(
            {
                "object": obj.name,
                "static_mesh_path": obj.get("ue_static_mesh_path", ""),
                **mat_result,
            }
        )

    proof = {
        "blend_path": bpy.data.filepath,
        "scene_manifest": str(args.scene_manifest),
        "inline_asset_count": len(assets),
        "inline_meshes_rebuilt": len(mesh_rows),
        "inline_meshes_missing": missing_meshes,
        "inline_objects_material_repaired": sum(1 for row in material_rows if row.get("applied")),
        "material_rows": material_rows,
        "mesh_rows": mesh_rows,
        "named_target": next((row for row in material_rows if row.get("object") == "SDStitchingProxy_2661_StaticMesh__27170"), {}),
        "status": "inline_proxy_quad_faces_uvs_and_visual_materials_repaired",
    }
    Path(args.proof_out).write_text(json.dumps(proof, indent=2), encoding="utf-8")
    bpy.context.scene["gridlock_inline_proxy_repair"] = "quad faces fixed, inferred card UV0 added, proxy override materials repaired"
    bpy.context.scene["gridlock_inline_proxy_repair_proof"] = str(args.proof_out)
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps({k: v for k, v in proof.items() if k not in {"material_rows", "mesh_rows"}}, indent=2))


if __name__ == "__main__":
    main()
