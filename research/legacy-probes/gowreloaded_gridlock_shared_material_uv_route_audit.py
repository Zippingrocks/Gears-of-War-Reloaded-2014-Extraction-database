#!/usr/bin/env python3
"""Audit MP_Gridlock material sharing vs. UV-map routing inside Blender.

The persistent Gridlock texture failure can happen when a shared material has a
single UVMap node but is used by objects that need different decoded UV layers.
This script is read-only: it reports material users, texture vector routing,
and mismatches between linked UV names and object mesh UV layers.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import bpy  # type: ignore


STATIC_RENDER_UV = "UV_Source_Render"
BSP_RENDER_UV = "UV_Source_BSP_RenderTexCoord"
BSP_RENDER_UV_ALT = "UV_Source_BSP_MaterialTexel"
INLINE_RENDER_UV = "UV0_Source_InlineCard"

TARGETS = {
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2550_StaticMesh__27112",
    "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP",
    "Model_5__MP_Gridlock.war__11545",
    "Model_6__MP_Gridlock.war__11546",
    "Model_27__MP_Gridlock.war__11527",
    "Model_313__MP_Gridlock.war__11531",
    "Model_195__MP_Gridlock.war__11514",
    "Model_26__MP_Gridlock.war__11526",
    "Model_14__MP_Gridlock.war__11506",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
}


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", required=True)
    return parser.parse_args(passthrough)


def is_gridlock_mesh(obj: bpy.types.Object) -> bool:
    if obj.type != "MESH":
        return False
    if obj.get("ue_static_mesh_path"):
        return True
    return obj.name.startswith("Model_") and "__MP_Gridlock.war__" in obj.name


def is_visible(obj: bpy.types.Object) -> bool:
    return not obj.hide_get() and not obj.hide_viewport and not obj.hide_render


def expected_uv(obj: bpy.types.Object) -> str:
    mesh = obj.data
    if obj.name.startswith("Model_") and mesh.uv_layers.get(BSP_RENDER_UV):
        return BSP_RENDER_UV
    if obj.name.startswith("Model_") and mesh.uv_layers.get(BSP_RENDER_UV_ALT):
        return BSP_RENDER_UV_ALT
    if mesh.uv_layers.get(STATIC_RENDER_UV):
        return STATIC_RENDER_UV
    if mesh.uv_layers.get(INLINE_RENDER_UV):
        return INLINE_RENDER_UV
    return mesh.uv_layers.active.name if mesh.uv_layers.active else ""


def uv_stats(mesh: bpy.types.Mesh, layer_name: str) -> dict[str, Any]:
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        return {"exists": False}
    values: list[tuple[float, float]] = []
    for item in layer.data:
        u = float(item.uv.x)
        v = float(item.uv.y)
        if math.isfinite(u) and math.isfinite(v):
            values.append((u, v))
    if not values:
        return {"exists": True, "valid": 0}
    us = [u for u, _v in values]
    vs = [v for _u, v in values]
    return {
        "exists": True,
        "valid": len(values),
        "unique_rounded": len({(round(u, 4), round(v, 4)) for u, v in values}),
        "min": [round(min(us), 6), round(min(vs), 6)],
        "max": [round(max(us), 6), round(max(vs), 6)],
        "span": [round(max(us) - min(us), 6), round(max(vs) - min(vs), 6)],
    }


def image_node_vector_source(material: bpy.types.Material) -> list[dict[str, Any]]:
    if not material.use_nodes or material.node_tree is None:
        return []
    rows: list[dict[str, Any]] = []
    links = material.node_tree.links
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeTexImage":
            continue
        image = getattr(node, "image", None)
        vector = node.inputs.get("Vector")
        source = ""
        uv_map = ""
        chain: list[str] = []
        if vector is not None and vector.links:
            link = vector.links[0]
            source = link.from_node.bl_idname
            chain.append(f"{link.from_node.name}:{link.from_socket.name}")
            if link.from_node.bl_idname == "ShaderNodeUVMap":
                uv_map = str(getattr(link.from_node, "uv_map", ""))
            elif link.from_node.bl_idname == "ShaderNodeMapping":
                for inner in links:
                    if inner.to_node == link.from_node and inner.to_socket == link.from_node.inputs.get("Vector"):
                        chain.append(f"{inner.from_node.name}:{inner.from_socket.name}")
                        if inner.from_node.bl_idname == "ShaderNodeUVMap":
                            uv_map = str(getattr(inner.from_node, "uv_map", ""))
        rows.append(
            {
                "node": node.name,
                "label": node.label,
                "image": image.name if image else "",
                "image_path": bpy.path.abspath(image.filepath) if image and image.filepath else "",
                "colorspace": image.colorspace_settings.name if image else "",
                "vector_source": source,
                "uv_map": uv_map,
                "chain": chain,
            }
        )
    return rows


def material_path(material: bpy.types.Material) -> str:
    for key in ("ue_material_path", "native_material_path", "source_material_path"):
        value = str(material.get(key, "") or "").strip()
        if value:
            return value
    return ""


def main() -> int:
    args = parse_args()
    material_users: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in bpy.context.scene.objects:
        if not is_gridlock_mesh(obj):
            continue
        exp_uv = expected_uv(obj)
        for slot_index, slot in enumerate(obj.material_slots):
            mat = slot.material
            if mat is None:
                continue
            material_users[mat.name].append(
                {
                    "object": obj.name,
                    "slot": slot_index,
                    "visible": is_visible(obj),
                    "expected_uv": exp_uv,
                    "uv_layers": [layer.name for layer in obj.data.uv_layers],
                    "static_mesh_path": str(obj.get("ue_static_mesh_path", "")),
                }
            )

    material_rows: list[dict[str, Any]] = []
    mismatch_rows: list[dict[str, Any]] = []
    target_rows: dict[str, Any] = {}
    for mat_name, users in sorted(material_users.items(), key=lambda item: (-len(item[1]), item[0].lower())):
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            continue
        node_rows = image_node_vector_source(mat)
        linked_uvs = sorted({row.get("uv_map", "") for row in node_rows if row.get("uv_map")})
        expected_uvs = sorted({row.get("expected_uv", "") for row in users if row.get("expected_uv")})
        visible_users = [row for row in users if row.get("visible")]
        missing_on_users = []
        for row in visible_users:
            for linked_uv in linked_uvs:
                if linked_uv and linked_uv not in row["uv_layers"]:
                    missing_on_users.append({"object": row["object"], "slot": row["slot"], "linked_uv": linked_uv, "expected_uv": row["expected_uv"]})
        route_mismatch = bool(linked_uvs and expected_uvs and set(linked_uvs) != set(expected_uvs))
        if route_mismatch or missing_on_users or len(visible_users) > 1:
            material_rows.append(
                {
                    "material": mat_name,
                    "ue_material_path": material_path(mat),
                    "user_count": len(users),
                    "visible_user_count": len(visible_users),
                    "linked_uvs": linked_uvs,
                    "expected_uvs": expected_uvs,
                    "route_mismatch": route_mismatch,
                    "missing_linked_uv_on_visible_users": missing_on_users[:20],
                    "image_nodes": node_rows,
                    "visible_user_samples": visible_users[:20],
                }
            )
        if route_mismatch or missing_on_users:
            mismatch_rows.append(material_rows[-1])

    for target in sorted(TARGETS):
        obj = bpy.data.objects.get(target)
        if obj is None:
            target_rows[target] = {"exists": False}
            continue
        mats = []
        for index, slot in enumerate(obj.material_slots):
            mat = slot.material
            mats.append(
                {
                    "slot": index,
                    "material": mat.name if mat else "",
                    "ue_material_path": material_path(mat) if mat else "",
                    "image_nodes": image_node_vector_source(mat) if mat else [],
                }
            )
        target_rows[target] = {
            "exists": True,
            "visible": is_visible(obj),
            "expected_uv": expected_uv(obj),
            "uv_layers": [layer.name for layer in obj.data.uv_layers],
            "active_uv": obj.data.uv_layers.active.name if obj.data.uv_layers.active else "",
            "uv_stats": {layer.name: uv_stats(obj.data, layer.name) for layer in obj.data.uv_layers},
            "materials": mats,
        }

    linked_uv_counter = Counter()
    expected_uv_counter = Counter()
    for row in material_rows:
        for value in row["linked_uvs"]:
            linked_uv_counter[value] += row["visible_user_count"]
        for value in row["expected_uvs"]:
            expected_uv_counter[value] += row["visible_user_count"]

    proof = {
        "blend_path": bpy.data.filepath,
        "summary": {
            "gridlock_materials_used": len(material_users),
            "shared_or_suspicious_material_rows": len(material_rows),
            "uv_route_mismatch_rows": len(mismatch_rows),
            "linked_uv_counter_weighted": dict(linked_uv_counter),
            "expected_uv_counter_weighted": dict(expected_uv_counter),
        },
        "target_rows": target_rows,
        "mismatch_rows": mismatch_rows[:200],
        "material_rows": material_rows[:300],
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(proof["summary"], indent=2, ensure_ascii=True))
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
