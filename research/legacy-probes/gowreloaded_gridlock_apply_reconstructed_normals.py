#!/usr/bin/env python3
"""Relink Gridlock Blender normal nodes to reconstructed BC5/DXN normal maps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore


def parse_args() -> argparse.Namespace:
    passthrough = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal-map-json", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--strength", type=float, default=0.55)
    parser.add_argument("--no-save", action="store_true")
    return parser.parse_args(passthrough)


def load_mapping(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(key).lower(): str(value) for key, value in raw.items()}


def node_is_normal_image(node: bpy.types.Node) -> bool:
    if node.bl_idname != "ShaderNodeTexImage":
        return False
    image = getattr(node, "image", None)
    text = " ".join(
        [
            str(node.name),
            str(getattr(node, "label", "")),
            image.name if image else "",
            bpy.path.abspath(image.filepath) if image and image.filepath else "",
        ]
    ).lower()
    return "normal" in text or "pf_dxn" in text or "dxn" in text


def mapping_key_for_image(image: bpy.types.Image | None, mapping: dict[str, str]) -> str | None:
    if image is None:
        return None
    candidates = [
        image.name.lower(),
        Path(image.name).name.lower(),
    ]
    if image.filepath:
        abs_path = str(Path(bpy.path.abspath(image.filepath)).resolve(strict=False)).lower()
        candidates.append(abs_path)
        candidates.append(Path(abs_path).name.lower())
    for candidate in candidates:
        if candidate in mapping:
            return candidate
    return None


def load_image(path: str) -> bpy.types.Image | None:
    target = Path(path)
    if not target.exists():
        return None
    image = bpy.data.images.get(target.name)
    if image is None:
        image = bpy.data.images.load(str(target), check_existing=True)
    try:
        image.colorspace_settings.name = "Non-Color"
    except Exception:
        pass
    return image


def set_normal_strength(material: bpy.types.Material, strength: float) -> int:
    if material.node_tree is None:
        return 0
    touched = 0
    for node in material.node_tree.nodes:
        if node.bl_idname != "ShaderNodeNormalMap":
            continue
        if "Strength" in node.inputs:
            node.inputs["Strength"].default_value = strength
            touched += 1
        try:
            node.space = "TANGENT"
        except Exception:
            pass
    return touched


def main() -> int:
    args = parse_args()
    mapping = load_mapping(Path(args.normal_map_json))
    relinked_nodes = 0
    relinked_materials = 0
    normal_nodes_tuned = 0
    samples: list[dict[str, Any]] = []
    missing_outputs: list[dict[str, Any]] = []

    for material in bpy.data.materials:
        if not material.use_nodes or material.node_tree is None:
            continue
        material_relinked = False
        for node in material.node_tree.nodes:
            if not node_is_normal_image(node):
                continue
            image = getattr(node, "image", None)
            key = mapping_key_for_image(image, mapping)
            if key is None:
                continue
            rebuilt_path = mapping[key]
            rebuilt = load_image(rebuilt_path)
            if rebuilt is None:
                if len(missing_outputs) < 40:
                    missing_outputs.append({"material": material.name, "node": node.name, "path": rebuilt_path})
                continue
            old_name = image.name if image else ""
            node.image = rebuilt
            try:
                node.extension = "REPEAT"
            except Exception:
                pass
            relinked_nodes += 1
            material_relinked = True
            if len(samples) < 80:
                samples.append(
                    {
                        "material": material.name,
                        "node": node.name,
                        "old_image": old_name,
                        "new_image": rebuilt.name,
                        "new_path": rebuilt_path,
                    }
                )
        if material_relinked:
            relinked_materials += 1
            normal_nodes_tuned += set_normal_strength(material, float(args.strength))
            material["gridlock_reconstructed_dxn_normals"] = "PF_DXN/BC5 normal maps rebuilt with blue channel and DirectX green inverted for Blender"
            material["gridlock_reconstructed_dxn_normal_strength"] = float(args.strength)

    proof = {
        "blend_path": bpy.data.filepath,
        "normal_map_json": str(Path(args.normal_map_json)),
        "summary": {
            "mapping_entries": len(mapping),
            "materials_relinked": relinked_materials,
            "normal_image_nodes_relinked": relinked_nodes,
            "normal_map_nodes_strength_tuned": normal_nodes_tuned,
            "missing_outputs": len(missing_outputs),
        },
        "samples": samples,
        "missing_output_samples": missing_outputs,
        "scene_counts": {
            "objects": len(bpy.data.objects),
            "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
        },
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_reconstructed_dxn_normals"] = "source PF_DXN normals reconstructed and relinked for Blender viewport/rendering"
    bpy.context.scene["gridlock_reconstructed_dxn_normals_proof"] = str(out)
    print(json.dumps({"proof_out": str(out), "summary": proof["summary"]}, indent=2, ensure_ascii=True))
    if not args.no_save:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
