#!/usr/bin/env python3
"""Probe MP_Gridlock UModelComponent refs around Model_2.

This is a lightweight source-native scan, not a full FModelElement lightmap
deserializer. It answers the important question for the BSP texture issue:
whether cooked ModelComponent exports that reference Model_2 expose render
material refs other than FBspSurf.Material.
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


BSP_CONFIDENCE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)
DEFAULT_DECOMPRESSED = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\MP_Gridlock.decompressed.war"
)
DEFAULT_OUT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\BSP_Confidence\gridlock_model2_modelcomponent_ref_probe_2026_08_15.json"
)
MODEL2_EXPORT = 11515


def install_fake_lz4() -> None:
    lz4_module = types.ModuleType("lz4")
    block_module = types.ModuleType("lz4.block")

    def _unused_decompress(*_args: Any, **_kwargs: Any) -> bytes:
        raise RuntimeError("this probe expects an already decompressed package")

    block_module.decompress = _unused_decompress  # type: ignore[attr-defined]
    lz4_module.block = block_module  # type: ignore[attr-defined]
    sys.modules.setdefault("lz4", lz4_module)
    sys.modules.setdefault("lz4.block", block_module)


def load_bsp():
    install_fake_lz4()
    spec = importlib.util.spec_from_file_location("gowr_gridlock_bsp_confidence_for_modelcomponents", BSP_CONFIDENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {BSP_CONFIDENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_gridlock_bsp_confidence_for_modelcomponents"] = module
    spec.loader.exec_module(module)
    return module


bsp = load_bsp()
heavy = bsp.heavy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", default=str(DEFAULT_DECOMPRESSED))
    parser.add_argument("--proof-out", default=str(DEFAULT_OUT))
    return parser.parse_args()


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def ref_kind(path: str) -> str:
    lower = path.lower()
    if not path:
        return ""
    if "material" in lower or lower.endswith("_mat") or "_mat" in lower or "mat_" in lower:
        return "material_like"
    if "model" in lower:
        return "model_like"
    if "lightmap" in lower or "shadowmap" in lower:
        return "light_shadow_like"
    return "other_ref"


def load_package_tables(path: Path) -> tuple[bytes, list[str], list[dict[str, Any]], list[dict[str, Any]], Any]:
    data = path.read_bytes()
    virt, _groups, _mode = heavy.rebuild_virtual_package(data)
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])
    return virt, names, imports, exports, ref_path


def scan_refs(virt: bytes, row: dict[str, Any], ref_path) -> list[dict[str, Any]]:
    start = int(row["serial_offset"])
    end = start + int(row["serial_size"])
    rows: list[dict[str, Any]] = []
    for rel in range(0, int(row["serial_size"]) - 3, 4):
        value = i32(virt, start + rel)
        if value == 0:
            continue
        try:
            path = ref_path(value)
        except Exception:
            continue
        if not path or path == "None" or path.startswith("<badref"):
            continue
        rows.append({"rel": rel, "ref": value, "path": path, "kind": ref_kind(path)})
    return rows


def main() -> int:
    args = parse_args()
    virt, names, imports, exports, ref_path = load_package_tables(Path(args.decompressed))
    component_rows: list[dict[str, Any]] = []
    material_counter: Counter[str] = Counter()
    model2_component_count = 0
    modelcomponent_count = 0
    for row in exports:
        if str(row.get("class_name")) != "ModelComponent":
            continue
        modelcomponent_count += 1
        refs = scan_refs(virt, row, ref_path)
        has_model2 = any(int(ref["ref"]) == MODEL2_EXPORT or ref["path"].endswith(".Model_2") for ref in refs)
        materials = [ref for ref in refs if ref["kind"] == "material_like"]
        if has_model2:
            model2_component_count += 1
            for ref in materials:
                material_counter[str(ref["path"])] += 1
        component_rows.append(
            {
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "serial_offset": row["serial_offset"],
                "serial_size": row["serial_size"],
                "has_model2_ref": has_model2,
                "model2_ref_hits": [ref for ref in refs if int(ref["ref"]) == MODEL2_EXPORT or ref["path"].endswith(".Model_2")][:12],
                "material_refs": materials[:40],
                "all_ref_kind_counts": dict(Counter(ref["kind"] for ref in refs)),
                "all_refs_sample": refs[:80],
            }
        )
    proof = {
        "package": str(Path(args.decompressed)),
        "modelcomponent_exports": modelcomponent_count,
        "model2_export": MODEL2_EXPORT,
        "model2_component_count": model2_component_count,
        "model2_component_material_ref_counts": dict(material_counter),
        "model2_component_material_paths": sorted(material_counter),
        "model2_component_rows": [row for row in component_rows if row["has_model2_ref"]],
        "all_modelcomponent_rows_sample": component_rows[:40],
        "interpretation": (
            "If model2_component_material_paths has only Stairtech, the cooked ModelComponent refs do not provide "
            "a missing multi-material override for Model_2. If it has other materials, Model_2 needs a section-material rebuild."
        ),
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "modelcomponents": modelcomponent_count, "model2_components": model2_component_count, "model2_materials": dict(material_counter)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
