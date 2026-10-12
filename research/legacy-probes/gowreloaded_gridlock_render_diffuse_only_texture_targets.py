#!/usr/bin/env python3
"""Render Gridlock problem targets with in-memory diffuse-only materials.

This is a no-save diagnostic. It intentionally removes normal/spec/emissive
graphs from copied materials so we can tell whether the remaining visual break
is UV/section placement or shader reconstruction.
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


DEFAULT_TARGETS = [
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2550_StaticMesh__27112",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "Model_2__MP_Gridlock.war__11515__REAL_RENDERED_BSP",
    "Model_5__MP_Gridlock.war__11545",
    "Model_27__MP_Gridlock.war__11527",
    "Model_313__MP_Gridlock.war__11531",
    "Model_195__MP_Gridlock.war__11514",
    "Model_26__MP_Gridlock.war__11526",
    "Model_14__MP_Gridlock.war__11506",
]


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-out", required=True)
    parser.add_argument("--proof-out", required=True)
    parser.add_argument("--preview-copy", default="")
    parser.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    return parser.parse_args(argv)


def visible_mesh(obj: bpy.types.Object) -> bool:
    return obj.type == "MESH" and not obj.hide_viewport and not obj.hide_render




def vec3(value: Vector) -> list[float]:
    return [round(float(value.x), 6), round(float(value.y), 6), round(float(value.z), 6)]


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
        "min": vec3(mins),
        "max": vec3(maxs),
        "center": vec3(center),
        "extent": vec3(extent),
        "radius": round(radius, 6),
    }


def select_targets(names: list[str]) -> tuple[list[bpy.types.Object], list[str]]:
    objects: list[bpy.types.Object] = []
    unavailable: list[str] = []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            unavailable.append(f"{name} (missing)")
        elif not visible_mesh(obj):
            unavailable.append(f"{name} (hidden)")
        else:
            objects.append(obj)
    return objects, unavailable


def isolate(objects: list[bpy.types.Object]) -> dict[str, Any]:
    keep = set(objects)
    changed = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        desired_hide = obj not in keep
        if obj.hide_render != desired_hide:
            obj.hide_render = desired_hide
            changed += 1
    return {"render_visible_mesh_objects": len(keep), "hide_render_changes": changed}


def configure_camera(objects: list[bpy.types.Object]) -> dict[str, Any]:
    b = bounds(objects)
    center = Vector(b["center"])
    radius = float(b["radius"])
    data = bpy.data.cameras.get("CAM_MP_Gridlock_DiffuseOnlyDiagnostic") or bpy.data.cameras.new(
        "CAM_MP_Gridlock_DiffuseOnlyDiagnostic"
    )
    cam = bpy.data.objects.get(data.name) or bpy.data.objects.new(data.name, data)
    if not cam.users_collection:
        bpy.context.scene.collection.objects.link(cam)
    cam.location = center + Vector((-radius * 0.68, -radius * 0.94, radius * 0.58))
    direction = center - Vector(cam.location)
    if direction.length > 0:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    data.lens = 28.0
    data.clip_start = 0.05
    data.clip_end = max(120000.0, radius * 30.0)
    bpy.context.scene.camera = cam
    return {"camera": cam.name, "location": vec3(cam.location), "target": b["center"], "lens": data.lens, "bounds": b}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.035, 0.038, 0.04)
    return {"engine": str(scene.render.engine), "resolution": [scene.render.resolution_x, scene.render.resolution_y]}


def principled_input(node: bpy.types.Node, names: tuple[str, ...]) -> bpy.types.NodeSocket | None:
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def image_path(image: bpy.types.Image | None) -> str:
    if image is None:
        return ""
    try:
        return bpy.path.abspath(image.filepath)
    except Exception:
        return str(image.filepath or "")


def load_image_from_path(path_text: str, non_color: bool = False) -> bpy.types.Image | None:
    clean = str(path_text or "").strip()
    if not clean:
        return None
    wanted = str(Path(clean)).lower()
    for image in bpy.data.images:
        if image_path(image).lower() == wanted:
            return image
    try:
        image = bpy.data.images.load(clean, check_existing=True)
        if non_color:
            image.colorspace_settings.name = "Non-Color"
        else:
            image.colorspace_settings.name = "sRGB"
        return image
    except Exception:
        return None


def image_score(node: bpy.types.Node) -> int:
    text = " ".join(
        [
            str(getattr(node, "name", "")),
            str(getattr(node, "label", "")),
            str(getattr(getattr(node, "image", None), "name", "")),
            str(getattr(getattr(node, "image", None), "filepath", "")),
        ]
    ).lower()
    score = 0
    if "diffuse" in text or "_d." in text or "_d_" in text or "albedo" in text or "base" in text:
        score += 20
    if "decoded_diffuse" in text:
        score += 40
    if "normal" in text or "_n." in text or "_n_" in text or "spec" in text or "mask" in text or "emiss" in text:
        score -= 50
    return score


def choose_diffuse_image(material: bpy.types.Material | None) -> tuple[bpy.types.Image | None, str]:
    if material is None:
        return None, ""
    for prop in ("decoded_diffuse_dds", "source_diffuse_dds", "ue_diffuse_dds"):
        path_text = str(material.get(prop, "") or "").strip()
        image = load_image_from_path(path_text, non_color=False)
        if image is not None:
            return image, f"material property {prop}"
    if not material.use_nodes or material.node_tree is None:
        return None, ""
    image_nodes = [node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage" and node.image]
    if not image_nodes:
        return None, ""
    image_nodes.sort(key=image_score, reverse=True)
    return image_nodes[0].image, f"image node score {image_score(image_nodes[0])}"


def render_uv_name(obj: bpy.types.Object) -> str:
    mesh = obj.data
    if mesh.uv_layers.get("UV_Source_Render") is not None:
        return "UV_Source_Render"
    if mesh.uv_layers.get("UV_Source_BSP_RenderTexCoord") is not None:
        return "UV_Source_BSP_RenderTexCoord"
    if mesh.uv_layers.get("UV0_Source_InlineCard") is not None:
        return "UV0_Source_InlineCard"
    return mesh.uv_layers.active.name if mesh.uv_layers.active else ""


def make_diffuse_only_material(
    source: bpy.types.Material | None,
    image: bpy.types.Image | None,
    uv_name: str,
) -> bpy.types.Material:
    source_name = source.name if source else "NO_SOURCE_MATERIAL"
    name = f"DIAG_DIFFUSE_ONLY__{source_name}"[:120]
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (0.8, 0.8, 0.8, 1.0)
    material["gridlock_diffuse_only_diagnostic"] = "true"
    material["source_material"] = source_name
    if source:
        material["ue_material_path"] = str(source.get("ue_material_path", ""))
    material["uv_map"] = uv_name

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (360, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base = principled_input(bsdf, ("Base Color",))
    rough = principled_input(bsdf, ("Roughness",))
    metallic = principled_input(bsdf, ("Metallic",))
    spec = principled_input(bsdf, ("Specular IOR Level", "Specular"))
    alpha = principled_input(bsdf, ("Alpha",))
    if rough:
        rough.default_value = 0.86
    if metallic:
        metallic.default_value = 0.0
    if spec:
        spec.default_value = 0.05
    if image is None:
        if base:
            base.default_value = (0.65, 0.2, 0.75, 1.0)
        return material

    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    tex = nodes.new("ShaderNodeTexImage")
    tex.name = "Diagnostic_Diffuse_Only"
    tex.label = "Diagnostic Diffuse Only"
    tex.location = (-360, 100)
    tex.image = image
    tex.extension = "REPEAT"
    if uv_name:
        uv = nodes.new("ShaderNodeUVMap")
        uv.name = "Diagnostic_Source_UV"
        uv.label = uv_name
        uv.location = (-620, 100)
        uv.uv_map = uv_name
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
    if base:
        links.new(tex.outputs["Color"], base)
    if alpha and "Alpha" in tex.outputs:
        links.new(tex.outputs["Alpha"], alpha)
    material["diffuse_image"] = image_path(image)
    material["shader_note"] = "Normal/spec/emissive layers intentionally removed for diagnosis."
    return material


def apply_diffuse_only(objects: list[bpy.types.Object]) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    cache: dict[tuple[str, str, str], bpy.types.Material] = {}
    for obj in objects:
        uv_name = render_uv_name(obj)
        object_rows: list[dict[str, Any]] = []
        for index, slot in enumerate(obj.material_slots):
            source = slot.material
            image, reason = choose_diffuse_image(source)
            key = (source.name if source else "", image_path(image), uv_name)
            if key not in cache:
                cache[key] = make_diffuse_only_material(source, image, uv_name)
            slot.material = cache[key]
            slot.link = "OBJECT"
            object_rows.append(
                {
                    "slot": index,
                    "source_material": source.name if source else "",
                    "ue_material_path": str(source.get("ue_material_path", "")) if source else "",
                    "chosen_image": image_path(image),
                    "chosen_reason": reason,
                    "uv_map": uv_name,
                }
            )
        audit.append(
            {
                "object": obj.name,
                "mesh": obj.data.name,
                "uv_layers": [layer.name for layer in obj.data.uv_layers],
                "slots": object_rows,
            }
        )
    return audit


def main() -> int:
    args = parse_args()
    render_out = Path(args.render_out)
    proof_out = Path(args.proof_out)
    render_out.parent.mkdir(parents=True, exist_ok=True)
    proof_out.parent.mkdir(parents=True, exist_ok=True)

    objects, unavailable = select_targets(args.targets)
    if not objects:
        raise RuntimeError("No requested visible target objects were found.")
    diagnostic_materials = apply_diffuse_only(objects)
    isolation = isolate(objects)
    render = configure_render()
    camera = configure_camera(objects)
    bpy.context.scene.render.filepath = str(render_out)
    bpy.ops.render.render(write_still=True)

    if args.preview_copy:
        preview = Path(args.preview_copy)
        preview.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(render_out, preview)

    proof = {
        "blend_path": bpy.data.filepath,
        "render_out": str(render_out),
        "preview_copy": args.preview_copy,
        "targets": args.targets,
        "unavailable_targets": unavailable,
        "isolation": isolation,
        "render": render,
        "camera": camera,
        "diagnostic_materials": diagnostic_materials,
        "note": "In-memory diffuse-only render; normal/spec/emissive graphs removed; blend was not saved.",
    }
    proof_out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"render_out": str(render_out), "proof_out": str(proof_out), "targets": len(objects)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
