
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

SCENE_DIR = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Blender_Scene_2026_08_12")
ALIAS = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\_gridlock_water_native_alias_20260815")
VIS = Path(r"C:\Users\Bilbo\.codex\visualizations\2026\06\28\019f0bba-7647-7e82-9b57-7c1574085478")
ROOT_COLLECTION = "MP_Gridlock_Reloaded_Native_Scene"
CLOSE_MAT = "MAT__FX_MP_GridlockWater__CloseWater_GameView_v3_Calm"
VISTA_MAT = "MAT__FX_Ocean_Delta__FactoryOcean_Vista_GameView_v3_Calm"
DEFAULT_PROOF = SCENE_DIR / "gridlock_water_v3_calm_pass_2026_08_15.json"
DEFAULT_CLOSE = SCENE_DIR / "gridlock_close_water_v3_calm_2026_08_15.png"
DEFAULT_VISTA = SCENE_DIR / "gridlock_vista_water_v3_calm_2026_08_15.png"
DEFAULT_CLOSE_PREVIEW = VIS / "gridlock_close_water_v3_calm_latest.png"
DEFAULT_VISTA_PREVIEW = VIS / "gridlock_vista_water_v3_calm_latest.png"

CLOSE_IMAGES = {
    "occ": ALIAS / "mp_gridlock_occlusion__native.png",
    "normal_hi": ALIAS / "gridlock_normals_hi_freq__native.png",
    "normal_lo": ALIAS / "gridlock_normals_lo_freq__native.png",
    "foam": ALIAS / "mp_gridlock_foam__native.png",
    "foam_prox": ALIAS / "mp_gridlock_foam_proximity__native.png",
    "cube": ALIAS / "close_gridlock_skydome_cube_equirect__native.png",
}
VISTA_IMAGES = {
    "normal": ALIAS / "T_OceanFoam_Delta_Normal__BC5_reconstructed_native.png",
    "foam": ALIAS / "T_OceanFoam__native.png",
    "cloud": ALIAS / "T_CloudTile_Delta__native.png",
    "cube": ALIAS / "vista_factory_ocean_cube_equirect__native.png",
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-out", default=str(DEFAULT_PROOF))
    parser.add_argument("--close-render-out", default=str(DEFAULT_CLOSE))
    parser.add_argument("--vista-render-out", default=str(DEFAULT_VISTA))
    parser.add_argument("--close-preview-copy", default=str(DEFAULT_CLOSE_PREVIEW))
    parser.add_argument("--vista-preview-copy", default=str(DEFAULT_VISTA_PREVIEW))
    parser.add_argument("--render-proof", action="store_true")
    return parser.parse_args(argv)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def vec3(value: Any) -> list[float]:
    return [round(float(value[0]), 6), round(float(value[1]), 6), round(float(value[2]), 6)]


def safe_setattr(owner: Any, prop: str, value: Any) -> None:
    if hasattr(owner, prop):
        try:
            setattr(owner, prop, value)
        except Exception:
            pass


def set_enum(owner: Any, prop: str, preferred: list[str]) -> str:
    if not hasattr(owner, prop):
        return ""
    try:
        available = {item.identifier for item in owner.bl_rna.properties[prop].enum_items}
    except Exception:
        available = set()
    for value in preferred:
        if not available or value in available:
            try:
                setattr(owner, prop, value)
                return str(getattr(owner, prop))
            except Exception:
                pass
    return str(getattr(owner, prop, ""))


def image(path: Path | None, colorspace: str) -> bpy.types.Image | None:
    if path is None or not path.is_file():
        return None
    resolved = str(path.resolve(strict=False))
    for existing in bpy.data.images:
        if bpy.path.abspath(existing.filepath) == resolved:
            try:
                existing.colorspace_settings.name = colorspace
            except Exception:
                pass
            return existing
    try:
        img = bpy.data.images.load(resolved, check_existing=True)
        img.filepath = resolved
        img.colorspace_settings.name = colorspace
        img.alpha_mode = "STRAIGHT"
        return img
    except Exception:
        return None


def principled_socket(bsdf: bpy.types.Node, names: tuple[str, ...]) -> bpy.types.NodeSocket | None:
    for name in names:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_principled(bsdf: bpy.types.Node, names: tuple[str, ...], value: Any) -> None:
    sock = principled_socket(bsdf, names)
    if sock is not None:
        try:
            sock.default_value = value
        except Exception:
            pass


def clear_nodes(mat: bpy.types.Material) -> tuple[bpy.types.Nodes, bpy.types.NodeLinks]:
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for node in list(nodes):
        nodes.remove(node)
    return nodes, mat.node_tree.links


def material_base(name: str, alpha: float, base_color: tuple[float, float, float, float]) -> tuple[bpy.types.Material, bpy.types.Nodes, bpy.types.NodeLinks, bpy.types.Node, bpy.types.Node, bpy.types.Node]:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (base_color[0], base_color[1], base_color[2], alpha)
    safe_setattr(mat, "use_backface_culling", False)
    safe_setattr(mat, "show_transparent_back", True)
    safe_setattr(mat, "use_screen_refraction", True)
    set_enum(mat, "blend_method", ["BLEND", "HASHED", "DITHERED"])
    set_enum(mat, "surface_render_method", ["BLENDED", "DITHERED"])
    nodes, links = clear_nodes(mat)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (900, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (620, 0)
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-900, 80)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_principled(bsdf, ("Base Color",), base_color)
    set_principled(bsdf, ("Alpha",), alpha)
    set_principled(bsdf, ("Roughness",), 0.050)
    set_principled(bsdf, ("Metallic",), 0.0)
    set_principled(bsdf, ("Specular IOR Level", "Specular"), 0.94)
    set_principled(bsdf, ("Transmission Weight", "Transmission"), 0.045)
    set_principled(bsdf, ("Coat Weight", "Clearcoat"), 0.38)
    set_principled(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.040)
    set_principled(bsdf, ("IOR",), 1.333)
    return mat, nodes, links, out, bsdf, coord


def rgb_node(nodes: bpy.types.Nodes, color: tuple[float, float, float, float], loc: tuple[float, float]) -> bpy.types.NodeSocket:
    node = nodes.new("ShaderNodeRGB")
    node.location = loc
    node.outputs["Color"].default_value = color
    return node.outputs["Color"]


def add_env_reflection(nodes: bpy.types.Nodes, links: bpy.types.NodeLinks, coord: bpy.types.Node, color_in: bpy.types.NodeSocket, path: Path, fac: float, value: float, saturation: float) -> bpy.types.NodeSocket:
    img = image(path, "sRGB")
    if img is None:
        return color_in
    env = nodes.new("ShaderNodeTexEnvironment")
    env.location = (-520, 360)
    env.image = img
    hue = nodes.new("ShaderNodeHueSaturation")
    hue.location = (-285, 360)
    hue.inputs["Saturation"].default_value = saturation
    hue.inputs["Value"].default_value = value
    mix = nodes.new("ShaderNodeMixRGB")
    mix.location = (145, 210)
    mix.blend_type = "SCREEN"
    mix.inputs["Fac"].default_value = fac
    links.new(coord.outputs["Reflection"], env.inputs["Vector"])
    links.new(env.outputs["Color"], hue.inputs["Color"])
    links.new(color_in, mix.inputs["Color1"])
    links.new(hue.outputs["Color"], mix.inputs["Color2"])
    return mix.outputs["Color"]


def add_mask_layer(nodes: bpy.types.Nodes, links: bpy.types.NodeLinks, coord: bpy.types.Node, color_in: bpy.types.NodeSocket, path: Path, mode: str, fac: float, scale: float, threshold: float, tint: tuple[float, float, float, float], y: float, animate: tuple[float, float] | None = None) -> bpy.types.NodeSocket:
    img = image(path, "Non-Color")
    if img is None:
        return color_in
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-710, y)
    mapping.inputs["Scale"].default_value[0] = scale
    mapping.inputs["Scale"].default_value[1] = scale
    if animate is not None:
        mapping.inputs["Location"].default_value[0] = 0.0
        mapping.inputs["Location"].default_value[1] = 0.0
        mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
        mapping.inputs["Location"].default_value[0] = animate[0]
        mapping.inputs["Location"].default_value[1] = animate[1]
        mapping.inputs["Location"].keyframe_insert("default_value", frame=180)
    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (-490, y)
    tex.image = img
    tex.extension = "REPEAT"
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-255, y)
    ramp.color_ramp.elements[0].position = threshold
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1.0) if mode == "SCREEN" else tint
    ramp.color_ramp.elements[1].position = min(1.0, threshold + 0.22)
    ramp.color_ramp.elements[1].color = tint if mode == "SCREEN" else (0.86, 0.90, 0.87, 1.0)
    mix = nodes.new("ShaderNodeMixRGB")
    mix.location = (145, y)
    mix.blend_type = mode
    mix.inputs["Fac"].default_value = fac
    links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], ramp.inputs["Fac"])
    links.new(color_in, mix.inputs["Color1"])
    links.new(ramp.outputs["Color"], mix.inputs["Color2"])
    return mix.outputs["Color"]


def add_normal(nodes: bpy.types.Nodes, links: bpy.types.NodeLinks, coord: bpy.types.Node, bsdf: bpy.types.Node, paths: list[tuple[Path, float, tuple[float, float]]], strength: float) -> None:
    normal_out = None
    y = -520.0
    for path, scale, anim in paths:
        img = image(path, "Non-Color")
        if img is None:
            continue
        mapping = nodes.new("ShaderNodeMapping")
        mapping.location = (-710, y)
        mapping.inputs["Scale"].default_value[0] = scale
        mapping.inputs["Scale"].default_value[1] = scale
        mapping.inputs["Location"].default_value[0] = 0.0
        mapping.inputs["Location"].default_value[1] = 0.0
        mapping.inputs["Location"].keyframe_insert("default_value", frame=1)
        mapping.inputs["Location"].default_value[0] = anim[0]
        mapping.inputs["Location"].default_value[1] = anim[1]
        mapping.inputs["Location"].keyframe_insert("default_value", frame=180)
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-490, y)
        tex.image = img
        tex.extension = "REPEAT"
        links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        if normal_out is None:
            normal_out = tex.outputs["Color"]
        else:
            mix = nodes.new("ShaderNodeMixRGB")
            mix.location = (-255, y + 80)
            mix.blend_type = "OVERLAY"
            mix.inputs["Fac"].default_value = 0.15
            links.new(normal_out, mix.inputs["Color1"])
            links.new(tex.outputs["Color"], mix.inputs["Color2"])
            normal_out = mix.outputs["Color"]
        y -= 210.0
    if normal_out is not None and principled_socket(bsdf, ("Normal",)):
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.location = (180, -500)
        nmap.inputs["Strength"].default_value = strength
        links.new(normal_out, nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])


def make_close_material() -> dict[str, Any]:
    mat, nodes, links, _out, bsdf, coord = material_base(CLOSE_MAT, 0.57, (0.014, 0.032, 0.030, 1.0))
    color = rgb_node(nodes, (0.012, 0.030, 0.029, 1.0), (-520, 110))
    color = add_env_reflection(nodes, links, coord, color, CLOSE_IMAGES["cube"], 0.13, 0.10, 0.26)
    color = add_mask_layer(nodes, links, coord, color, CLOSE_IMAGES["occ"], "MULTIPLY", 0.20, 1.0, 0.12, (0.40, 0.48, 0.45, 1.0), 35)
    color = add_mask_layer(nodes, links, coord, color, CLOSE_IMAGES["foam_prox"], "SCREEN", 0.12, 1.0, 0.74, (0.22, 0.27, 0.22, 1.0), -175)
    color = add_mask_layer(nodes, links, coord, color, CLOSE_IMAGES["foam"], "SCREEN", 0.055, 2.25, 0.82, (0.16, 0.20, 0.17, 1.0), -385, (0.04, -0.03))
    links.new(color, bsdf.inputs["Base Color"])
    add_normal(nodes, links, coord, bsdf, [(CLOSE_IMAGES["normal_lo"], 1.35, (-0.05, 0.075)), (CLOSE_IMAGES["normal_hi"], 3.85, (0.10, -0.06))], 0.055)
    images = {key: str(value) for key, value in CLOSE_IMAGES.items()}
    mat["gridlock_water_status"] = "v3_calm_native_masks_reflection_subtle_normals"
    mat["source_images"] = json.dumps(images, ensure_ascii=True)
    return {"material": mat.name, "node_count": len(nodes), "images": images}


def make_vista_material() -> dict[str, Any]:
    mat, nodes, links, _out, bsdf, coord = material_base(VISTA_MAT, 0.62, (0.018, 0.040, 0.050, 1.0))
    color = rgb_node(nodes, (0.017, 0.038, 0.049, 1.0), (-520, 110))
    color = add_env_reflection(nodes, links, coord, color, VISTA_IMAGES["cube"], 0.22, 0.15, 0.34)
    color = add_mask_layer(nodes, links, coord, color, VISTA_IMAGES["foam"], "SCREEN", 0.060, 1.65, 0.80, (0.18, 0.24, 0.22, 1.0), -120, (0.035, -0.025))
    color = add_mask_layer(nodes, links, coord, color, VISTA_IMAGES["cloud"], "MULTIPLY", 0.055, 0.68, 0.18, (0.86, 0.90, 0.88, 1.0), -330)
    links.new(color, bsdf.inputs["Base Color"])
    add_normal(nodes, links, coord, bsdf, [(VISTA_IMAGES["normal"], 2.05, (0.060, -0.035))], 0.050)
    images = {key: str(value) for key, value in VISTA_IMAGES.items()}
    mat["gridlock_water_status"] = "v3_calm_factory_ocean_native_reflection_subtle_foam"
    mat["source_images"] = json.dumps(images, ensure_ascii=True)
    return {"material": mat.name, "node_count": len(nodes), "images": images}


def set_wave(obj: bpy.types.Object, height: float, width: float, speed: float) -> None:
    for mod in list(obj.modifiers):
        if "Water" in mod.name or "GRIDLOCK_Water" in mod.name:
            obj.modifiers.remove(mod)
    wave = obj.modifiers.new("GRIDLOCK_Water_Subtle_SurfaceMotion_v3", "WAVE")
    safe_setattr(wave, "height", height)
    safe_setattr(wave, "width", width)
    safe_setattr(wave, "speed", speed)
    safe_setattr(wave, "narrowness", 1.7)
    safe_setattr(wave, "use_x", True)
    safe_setattr(wave, "use_y", True)


def apply_materials(close_mat: bpy.types.Material, vista_mat: bpy.types.Material) -> dict[str, Any]:
    applied = {"close_water": [], "vista_ocean": []}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        text = " ".join([obj.name, getattr(obj.data, "name", ""), str(obj.get("ue_static_mesh_path") or ""), " ".join(c.name for c in obj.users_collection)]).lower()
        if "factoryocean1" in text or "fx_ocean_delta.meshes.factoryocean" in text:
            if obj.data.materials:
                for index in range(len(obj.data.materials)):
                    obj.data.materials[index] = vista_mat
            else:
                obj.data.materials.append(vista_mat)
            set_wave(obj, 0.018, 150.0, 0.018)
            obj.hide_viewport = False
            obj.hide_render = False
            obj["gridlock_water_status"] = "v3_calm_vista_ocean"
            applied["vista_ocean"].append({"object": obj.name, "dimensions": vec3(obj.dimensions), "material": vista_mat.name})
        elif "gridlockwater" in text or "gridlock_water_" in text:
            if "spray" in text or "marker" in text or "p_wall_spray" in text:
                continue
            if obj.data.materials:
                for index in range(len(obj.data.materials)):
                    obj.data.materials[index] = close_mat
            else:
                obj.data.materials.append(close_mat)
            set_wave(obj, 0.018 if max(obj.dimensions.x, obj.dimensions.y) < 80 else 0.026, 28.0, 0.045)
            obj.hide_viewport = False
            obj.hide_render = False
            obj["gridlock_water_status"] = "v3_calm_close_water"
            applied["close_water"].append({"object": obj.name, "dimensions": vec3(obj.dimensions), "material": close_mat.name})
    return applied


def bounds(objects: list[bpy.types.Object]) -> dict[str, Any]:
    if not objects:
        return {"min": [0, 0, 0], "max": [0, 0, 0], "center": [0, 0, 0], "radius": 64.0}
    mins = Vector((float("inf"), float("inf"), float("inf")))
    maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
    for obj in objects:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, world.x); mins.y = min(mins.y, world.y); mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x); maxs.y = max(maxs.y, world.y); maxs.z = max(maxs.z, world.z)
    center = (mins + maxs) * 0.5
    extent = maxs - mins
    return {"min": vec3(mins), "max": vec3(maxs), "center": vec3(center), "radius": max(extent.x, extent.y, extent.z) * 0.5}


def camera(name: str, objects: list[bpy.types.Object], offset: Vector, lens: float) -> dict[str, Any]:
    b = bounds(objects)
    target = Vector(b["center"])
    cam = bpy.data.objects.get(name)
    if cam is None:
        data = bpy.data.cameras.new(name)
        cam = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(cam)
    cam.location = target + offset
    direction = target - Vector(cam.location)
    if direction.length > 0:
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    cam.data.clip_start = 0.05
    cam.data.clip_end = 220000.0
    return {"camera": cam.name, "location": vec3(cam.location), "target": vec3(target), "lens": cam.data.lens, "bounds": b}


def configure_render() -> dict[str, Any]:
    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.frame_start = min(int(scene.frame_start or 1), 1)
    scene.frame_end = max(int(scene.frame_end or 1), 180)
    scene.frame_set(72)
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
        scene.view_settings.exposure = -0.18
        scene.view_settings.gamma = 1.0
    except Exception:
        pass
    return {"engine": scene.render.engine, "frame": scene.frame_current, "resolution": [scene.render.resolution_x, scene.render.resolution_y]}


def render(path: Path, cam_name: str) -> dict[str, Any]:
    ensure_parent(path)
    bpy.context.scene.camera = bpy.data.objects[cam_name]
    bpy.context.scene.render.filepath = str(path)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        return {"path": str(path), "ok": False, "error": str(exc)}
    return {"path": str(path), "ok": path.is_file() and path.stat().st_size > 0, "size": path.stat().st_size if path.is_file() else 0}


def copy_preview(src: Path, dst: Path) -> dict[str, Any]:
    if not src.is_file():
        return {"preview": str(dst), "copied": False}
    ensure_parent(dst)
    shutil.copyfile(src, dst)
    return {"preview": str(dst), "copied": True, "size": dst.stat().st_size}


def main() -> int:
    args = parse_args()
    close_summary = make_close_material()
    vista_summary = make_vista_material()
    applied = apply_materials(bpy.data.materials[CLOSE_MAT], bpy.data.materials[VISTA_MAT])
    render_cfg = configure_render()
    close_objs = [bpy.data.objects[row["object"]] for row in applied["close_water"] if row["object"] in bpy.data.objects]
    vista_objs = [bpy.data.objects[row["object"]] for row in applied["vista_ocean"] if row["object"] in bpy.data.objects]
    close_cam = camera("CAM_MP_Gridlock_CloseWater_v3_Calm_Preview", close_objs, Vector((-145.0, -210.0, 74.0)), 30.0)
    vista_cam = camera("CAM_MP_Gridlock_VistaWater_v3_Calm_Preview", vista_objs, Vector((-520.0, -720.0, 210.0)), 30.0)
    render_summary: dict[str, Any] = {"render_requested": bool(args.render_proof)}
    if args.render_proof:
        close_render = render(Path(args.close_render_out), close_cam["camera"])
        close_render.update(copy_preview(Path(args.close_render_out), Path(args.close_preview_copy)))
        vista_render = render(Path(args.vista_render_out), vista_cam["camera"])
        vista_render.update(copy_preview(Path(args.vista_render_out), Path(args.vista_preview_copy)))
        render_summary.update({"close": close_render, "vista": vista_render})
    proof = {
        "blend_path": bpy.data.filepath,
        "status": "gridlock_water_v3_calm_native_shader_applied",
        "map": "MP_Gridlock",
        "game": "Gears of War Reloaded",
        "materials": {"close_water": close_summary, "vista_ocean": vista_summary},
        "applied": applied,
        "cameras": {"close": close_cam, "vista": vista_cam},
        "render_config": render_cfg,
        "render": render_summary,
        "notes": [
            "Uses the 28/28 native water decode, but renders only the masks that should visibly matter.",
            "Close water is dark, reflective, low-saturation, with high-threshold foam and subtle animated normals.",
            "Vista FactoryOcean is mostly cubemap reflection with faint foam/cloud modulation.",
        ],
        "scene_counts": {"objects": len(bpy.data.objects), "mesh_objects": sum(1 for obj in bpy.data.objects if obj.type == "MESH"), "materials": len(bpy.data.materials), "images": len(bpy.data.images)},
    }
    proof_path = Path(args.proof_out)
    ensure_parent(proof_path)
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    bpy.context.scene["gridlock_water_v3_calm_proof"] = str(proof_path)
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print(json.dumps(proof, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
