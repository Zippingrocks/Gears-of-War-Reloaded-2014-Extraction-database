#!/usr/bin/env python3
"""Extract MP_Gridlock Reloaded native light/fog values into a clean manifest."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any


HEAVY_TOOL = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)
DEFAULT_MAP = Path(r"D:\SteamLibrary\steamapps\common\Gears of War Reloaded\WarGame\CookedPC\Maps\MP_Maps\MP_Gridlock.war")
DEFAULT_OUT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Native_Lighting_Probe_2026_08_15\gowreloaded_mp_gridlock_native_lighting_done_manifest.json"
)
DEFAULT_CSV = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Native_Lighting_Probe_2026_08_15\gowreloaded_mp_gridlock_native_lighting_done_rows.csv"
)

SLC_TOKEN = "TheWorld.PersistentLevel.MP_Gridlock_SLC_0."
UNIT_SCALE = 0.01


def load_heavy():
    spec = importlib.util.spec_from_file_location("gowr_heavy", HEAVY_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser: {HEAVY_TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-file", default=str(DEFAULT_MAP))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV))
    parser.add_argument("--unit-scale", type=float, default=UNIT_SCALE)
    return parser.parse_args()


def tag_by_base(tags: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tag in tags:
        base = str(tag.get("base_name") or tag.get("name") or "")
        if base and base != "None":
            out[base] = tag
    return out


def tag_value(tags: dict[str, dict[str, Any]], key: str, default: Any = None) -> Any:
    tag = tags.get(key)
    if not tag:
        return default
    return tag.get("decoded", default)


def read_struct_bytes(virt: bytes, row: dict[str, Any], tag: dict[str, Any]) -> bytes:
    value_rel = int(tag.get("value_rel") or 0)
    size = int(tag.get("size") or 0)
    start = int(row["serial_offset"]) + value_rel
    return virt[start : start + size]


def decode_matrix(virt: bytes, row: dict[str, Any], tag: dict[str, Any] | None) -> dict[str, Any]:
    if not tag:
        return {}
    raw = read_struct_bytes(virt, row, tag)
    if len(raw) < 64:
        return {"status": "missing_or_short_matrix", "raw_size": len(raw)}
    values = list(struct.unpack("<16f", raw[:64]))
    translation = values[12:15]
    basis_rows = [values[0:3], values[4:7], values[8:11]]
    basis_cols = [
        [values[0], values[4], values[8]],
        [values[1], values[5], values[9]],
        [values[2], values[6], values[10]],
    ]
    return {
        "status": "decoded_matrix64",
        "row_major": values,
        "basis_rows": basis_rows,
        "basis_cols": basis_cols,
        "ue_translation": translation,
        "blender_location": ue_to_blender_point(translation),
    }


def decode_color(virt: bytes, row: dict[str, Any], tag: dict[str, Any] | None) -> dict[str, Any]:
    if not tag:
        return {}
    raw = read_struct_bytes(virt, row, tag)
    if len(raw) == 4:
        # UE3 FColor serializes as BGRA on little-endian platforms.
        b, g, r, a = raw
        return {
            "status": "decoded_fcolor_bgra",
            "hex": raw.hex(),
            "rgba8": [r, g, b, a],
            "rgb_srgb": [r / 255.0, g / 255.0, b / 255.0],
            "alpha": a / 255.0,
        }
    if len(raw) >= 16:
        vals = list(struct.unpack("<4f", raw[:16]))
        return {"status": "decoded_linear_color", "rgba_linear": vals, "rgb_srgb": vals[:3], "alpha": vals[3]}
    return {"status": "missing_or_short_color", "raw_size": len(raw), "hex": raw.hex()}


def ue_to_blender_point(values: list[float] | tuple[float, float, float], unit_scale: float = UNIT_SCALE) -> list[float]:
    x, y, z = values
    return [float(y) * unit_scale, -float(x) * unit_scale, float(z) * unit_scale]


def ue_to_blender_vector(values: list[float] | tuple[float, float, float]) -> list[float]:
    x, y, z = values
    return [float(y), -float(x), float(z)]


def normalized(values: list[float]) -> list[float]:
    length = math.sqrt(sum(float(v) * float(v) for v in values))
    if length <= 1e-8:
        return [0.0, 0.0, -1.0]
    return [float(v) / length for v in values]


def clean_tags(tags: list[dict[str, Any]]) -> dict[str, Any]:
    keep: dict[str, Any] = {}
    for tag in tags:
        base = str(tag.get("base_name") or tag.get("name") or "")
        if not base or base == "None":
            continue
        decoded = tag.get("decoded")
        if isinstance(decoded, (int, float, str, bool, list)):
            keep[base] = decoded
        elif isinstance(decoded, dict) and decoded.get("path"):
            keep[base] = decoded
        elif base in {
            "CachedParentToWorld",
            "LightColor",
            "LightEnv_BouncedModulationColor",
            "OppositeLightColor",
            "LightInscatteringColor",
            "LightingChannels",
            "LightmassSettings",
        }:
            keep[base] = decoded
    return keep


def extract_light(virt: bytes, row: dict[str, Any], tags: list[dict[str, Any]], unit_scale: float) -> dict[str, Any]:
    by_base = tag_by_base(tags)
    matrix = decode_matrix(virt, row, by_base.get("CachedParentToWorld"))
    light_color = decode_color(virt, row, by_base.get("LightColor"))
    bounce_color = decode_color(virt, row, by_base.get("LightEnv_BouncedModulationColor"))
    cls = str(row["class_name"])
    basis_rows = matrix.get("basis_rows") or []
    basis_cols = matrix.get("basis_cols") or []
    forward_candidates: dict[str, list[float]] = {}
    for idx, vec in enumerate(basis_rows):
        forward_candidates[f"row{idx}"] = normalized(ue_to_blender_vector(vec))
        forward_candidates[f"neg_row{idx}"] = normalized([-v for v in ue_to_blender_vector(vec)])
    for idx, vec in enumerate(basis_cols):
        forward_candidates[f"col{idx}"] = normalized(ue_to_blender_vector(vec))
        forward_candidates[f"neg_col{idx}"] = normalized([-v for v in ue_to_blender_vector(vec)])

    brightness = tag_value(by_base, "Brightness", 1.0)
    radius = tag_value(by_base, "Radius", None)
    outer = tag_value(by_base, "OuterConeAngle", None)
    inner = tag_value(by_base, "InnerConeAngle", None)
    return {
        "package": "MP_Gridlock.war",
        "export_index": int(row["index"]),
        "class_name": cls,
        "object_name": row["object_short_name"],
        "full_path": row["full_path"],
        "property_start_rel": row.get("_scan_start_rel", ""),
        "property_end_rel": row.get("_scan_end_rel", ""),
        "matrix": matrix,
        "brightness": float(brightness) if isinstance(brightness, (int, float)) else 1.0,
        "radius": float(radius) if isinstance(radius, (int, float)) else None,
        "outer_cone_angle": float(outer) if isinstance(outer, (int, float)) else None,
        "inner_cone_angle": float(inner) if isinstance(inner, (int, float)) else None,
        "light_color": light_color,
        "bounced_brightness": tag_value(by_base, "LightEnv_BouncedLightBrightness", None),
        "bounced_color": bounce_color,
        "shadow_filter_quality": tag_value(by_base, "ShadowFilterQuality", ""),
        "shadow_depth_bias": tag_value(by_base, "ShadowDepthBias", None),
        "built_into_lightmap": bool((tag_value(by_base, "bHasLightEverBeenBuiltIntoLightMap", {}) or {}).get("value", False)),
        "forward_candidates_blender": forward_candidates,
        "properties": clean_tags(tags),
    }


def extract_fog(virt: bytes, row: dict[str, Any], tags: list[dict[str, Any]]) -> dict[str, Any]:
    by_base = tag_by_base(tags)
    out = {
        "package": "MP_Gridlock.war",
        "export_index": int(row["index"]),
        "class_name": row["class_name"],
        "object_name": row["object_short_name"],
        "full_path": row["full_path"],
        "properties": clean_tags(tags),
    }
    for color_key in ("LightColor", "OppositeLightColor", "LightInscatteringColor"):
        if color_key in by_base:
            out[f"{color_key}_decoded"] = decode_color(virt, row, by_base[color_key])
    return out


def write_csv(path: Path, lights: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "class_name",
        "object_name",
        "full_path",
        "brightness",
        "radius",
        "outer_cone_angle",
        "inner_cone_angle",
        "ue_x",
        "ue_y",
        "ue_z",
        "blender_x",
        "blender_y",
        "blender_z",
        "rgb",
        "built_into_lightmap",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for light in lights:
            matrix = light.get("matrix") or {}
            ue = matrix.get("ue_translation") or ["", "", ""]
            bl = matrix.get("blender_location") or ["", "", ""]
            rgb = (light.get("light_color") or {}).get("rgb_srgb") or []
            writer.writerow(
                {
                    "class_name": light.get("class_name", ""),
                    "object_name": light.get("object_name", ""),
                    "full_path": light.get("full_path", ""),
                    "brightness": light.get("brightness", ""),
                    "radius": light.get("radius", ""),
                    "outer_cone_angle": light.get("outer_cone_angle", ""),
                    "inner_cone_angle": light.get("inner_cone_angle", ""),
                    "ue_x": ue[0] if len(ue) > 0 else "",
                    "ue_y": ue[1] if len(ue) > 1 else "",
                    "ue_z": ue[2] if len(ue) > 2 else "",
                    "blender_x": bl[0] if len(bl) > 0 else "",
                    "blender_y": bl[1] if len(bl) > 1 else "",
                    "blender_z": bl[2] if len(bl) > 2 else "",
                    "rgb": json.dumps(rgb, ensure_ascii=True),
                    "built_into_lightmap": light.get("built_into_lightmap", ""),
                }
            )


def main() -> int:
    args = parse_args()
    heavy = load_heavy()
    map_file = Path(args.map_file)
    virt, groups, compression_mode = heavy.rebuild_virtual_package(map_file.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for row in exports:
        row["class_name"] = ref_short_name(row["class_ref"])
        row["outer_path"] = ref_path(row["outer_ref"])
        row["full_path"] = ref_path(row["index"])

    lights: list[dict[str, Any]] = []
    fog: list[dict[str, Any]] = []
    all_light_classes: Counter[str] = Counter()
    slc_refs: list[str] = []
    lightmap_texture_count = 0

    for row in exports:
        cls = str(row["class_name"])
        full_path = str(row["full_path"])
        if cls == "LightMapTexture2D":
            lightmap_texture_count += 1
            continue
        wants_light = cls in {"PointLightComponent", "SpotLightComponent", "DirectionalLightComponent"} and full_path.startswith(SLC_TOKEN)
        wants_fog = cls in {"ExponentialHeightFog", "ExponentialHeightFogComponent", "HeightFog", "HeightFogComponent"}
        wants_slc = cls == "StaticLightCollectionActor" and full_path == "TheWorld.PersistentLevel.MP_Gridlock_SLC_0"
        if not (wants_light or wants_fog or wants_slc):
            continue
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4, 8])
        result = scan["result"]
        tags = result.get("tags", []) if result.get("ok") else []
        row["_scan_start_rel"] = scan.get("start_rel", "")
        row["_scan_end_rel"] = result.get("end_rel", "")
        if wants_slc:
            for path in heavy.property_object_refs(tags):
                if path.startswith(SLC_TOKEN):
                    slc_refs.append(path)
            continue
        if wants_light:
            all_light_classes[cls] += 1
            lights.append(extract_light(virt, row, tags, float(args.unit_scale)))
        elif wants_fog:
            fog.append(extract_fog(virt, row, tags))

    manifest = {
        "target": "MP_Gridlock native lighting done manifest",
        "game": "Gears of War Reloaded",
        "source_scope": "Reloaded PC MP_Gridlock.war only",
        "map_file": str(map_file),
        "compression_mode": compression_mode,
        "compressed_groups": len(groups),
        "unit_scale": float(args.unit_scale),
        "slc_path": "TheWorld.PersistentLevel.MP_Gridlock_SLC_0",
        "slc_component_refs": slc_refs,
        "counts": {
            "native_slc_refs": len(slc_refs),
            "native_lights_decoded": len(lights),
            "class_counts": dict(sorted(all_light_classes.items())),
            "fog_records_decoded": len(fog),
            "lightmap_texture2d_exports": lightmap_texture_count,
            "lights_with_matrix": sum(1 for light in lights if (light.get("matrix") or {}).get("status") == "decoded_matrix64"),
            "lights_with_color": sum(1 for light in lights if (light.get("light_color") or {}).get("status")),
        },
        "lights": lights,
        "fog": fog,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    write_csv(Path(args.csv_out), lights)
    print(json.dumps({k: manifest[k] for k in ("target", "game", "source_scope", "counts")}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
