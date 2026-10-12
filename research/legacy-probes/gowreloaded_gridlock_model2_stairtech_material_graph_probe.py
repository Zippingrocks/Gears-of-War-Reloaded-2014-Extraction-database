#!/usr/bin/env python3
"""Probe the native UE3 material graph used by Gridlock Model_2 BSP.

The Blender scene currently simplifies the source material
COG_City_Ephyra3.EphyraCity_Stairtech01_PE_MAT into a direct diffuse/normal
shader. This probe dumps the cooked material and expression properties from the
Reloaded package so fixes can be based on native material graph evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import struct
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_DECOMPRESSED = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\MP_Gridlock.decompressed.war"
)
DEFAULT_OUT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Material_Graph_Probe_2026_08_15\gridlock_model2_stairtech_material_graph_probe_2026_08_15.json"
)
PROBE_MODULE = Path(__file__).with_name("gowreloaded_gridlock_model2_render_vertexbuffer_probe.py")

MATERIAL_EXPORT_INDEX = 7349
INTERESTING_EXPORTS = {
    7349,
    7463,
    7995,
    7996,
    7997,
    8407,
    8889,
    8890,
    8891,
    10346,
    10539,
    10655,
    10656,
    10657,
    28254,
    28255,
}
INTERESTING_TAGS = {
    "Expressions",
    "DiffuseColor",
    "BaseColor",
    "SpecularColor",
    "SpecularPower",
    "Normal",
    "Texture",
    "Coordinates",
    "CoordinateIndex",
    "UTiling",
    "VTiling",
    "ConstA",
    "ConstB",
    "A",
    "B",
    "R",
    "G",
    "EditorX",
    "EditorY",
    "SamplerType",
    "TextureObject",
}


def install_fake_lz4() -> None:
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")

    def _unused_decompress(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("this probe uses the already decompressed .war package")

    block_module.decompress = _unused_decompress  # type: ignore[attr-defined]
    lz4_module.block = block_module  # type: ignore[attr-defined]
    sys.modules.setdefault("lz4", lz4_module)
    sys.modules.setdefault("lz4.block", block_module)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def ref_valid(ref: int, exports: list[dict[str, Any]], imports: list[dict[str, Any]]) -> bool:
    return ref == 0 or (ref > 0 and ref <= len(exports)) or (ref < 0 and -ref - 1 < len(imports))


def tag_digest(tag: dict[str, Any]) -> dict[str, Any]:
    return {
        key: tag.get(key)
        for key in ("name", "base_name", "type", "item_name", "size", "array_index", "rel", "value_rel", "decoded")
        if key in tag
    }


def scan_object_refs(
    virt: bytes,
    row: dict[str, Any],
    exports: list[dict[str, Any]],
    imports: list[dict[str, Any]],
    ref_path,
    tags_end_rel: int | None,
) -> list[dict[str, Any]]:
    """Find valid package refs in the native payload for graph breadcrumbs."""
    start_abs = int(row["serial_offset"])
    end_abs = start_abs + int(row["serial_size"])
    out: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for abs_pos in range(start_abs, end_abs - 3, 4):
        ref = i32(virt, abs_pos)
        if not ref_valid(ref, exports, imports):
            continue
        path = ref_path(ref)
        if not path or path == "None":
            continue
        lower = path.lower()
        if not any(
            token in lower
            for token in (
                "ephyracity_stairtech01",
                "crackle3",
                "materialexpression",
                "texture2d",
                "cog_city_ephyra3",
                "cog_city_basematerials",
            )
        ):
            continue
        rel = abs_pos - start_abs
        key = (rel, ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "rel": rel,
                "after_properties": tags_end_rel is not None and rel >= tags_end_rel,
                "ref": ref,
                "path": path,
            }
        )
    return out[:256]


def scan_float_hints(virt: bytes, row: dict[str, Any]) -> list[dict[str, Any]]:
    start = int(row["serial_offset"])
    end = start + int(row["serial_size"])
    hints: list[dict[str, Any]] = []
    for abs_pos in range(start, end - 3, 4):
        value = f32(virt, abs_pos)
        if value in {0.0, 1.0, 2.0, 4.0, 8.0, 15.0, 16.0, 32.0, 64.0}:
            hints.append({"rel": abs_pos - start, "value": value})
    return hints[:128]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", default=str(DEFAULT_DECOMPRESSED))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    install_fake_lz4()
    probe = load_module(PROBE_MODULE, "gowr_gridlock_model2_render_probe_for_material_graph")
    heavy = probe.heavy
    virt, names, imports, exports, _ref_short_name, ref_path = probe.load_package_tables(Path(args.decompressed))

    rows: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    for export_index in sorted(INTERESTING_EXPORTS):
        row = exports[export_index - 1]
        class_counts[row.get("class_name", "")] += 1
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [0, 4])
        result = scan.get("result", {})
        tags = result.get("tags", [])
        tags_end_rel = result.get("end_rel") if result.get("ok") else None
        digest_tags = [
            tag_digest(tag)
            for tag in tags
            if tag.get("base_name") in INTERESTING_TAGS
            or tag.get("name") in INTERESTING_TAGS
            or tag.get("decoded") not in (None, "")
        ]
        rows.append(
            {
                "export_index": export_index,
                "class_name": row.get("class_name", ""),
                "object_name": row.get("object_short_name", ""),
                "full_path": row.get("full_path", ref_path(export_index)),
                "serial_offset": row.get("serial_offset"),
                "serial_size": row.get("serial_size"),
                "property_scan_ok": bool(result.get("ok")),
                "property_scan_end_rel": result.get("end_rel"),
                "property_scan_error": result.get("error", ""),
                "tag_count": len(tags),
                "interesting_tags": digest_tags,
                "object_refs": scan_object_refs(virt, row, exports, imports, ref_path, tags_end_rel),
                "float_hints": scan_float_hints(virt, row),
            }
        )

    material_row = exports[MATERIAL_EXPORT_INDEX - 1]
    material_refs = rows[0]["object_refs"] if rows else []
    proof = {
        "package": str(Path(args.decompressed)),
        "source": "native cooked Reloaded package; no Blender data used",
        "target_material_export": MATERIAL_EXPORT_INDEX,
        "target_material_path": material_row.get("full_path", ref_path(MATERIAL_EXPORT_INDEX)),
        "class_counts": dict(class_counts),
        "rows": rows,
        "material_refs_summary": material_refs[:64],
        "interpretation": {
            "model2_bsp_source_material": "FBspSurf.Material and UModelComponent.Elements.Material both resolve to this material in prior audits.",
            "purpose": "Identify whether Blender must apply UE3 TextureCoordinate tiling or restore missing detail-normal graph pieces.",
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"status": "ok", "out": str(out), "rows": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
