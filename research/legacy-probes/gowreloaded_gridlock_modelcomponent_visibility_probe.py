#!/usr/bin/env python3
"""Decode tagged visibility-ish properties for Gridlock ModelComponents."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any


BSP_CONFIDENCE = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_bsp_confidence.py"
)
DEFAULT_DECOMPRESSED = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\Texture_Section_UV_Validation_2026_08_13\MP_Gridlock.decompressed.war"
)
DEFAULT_OUT = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\BSP_Confidence\gridlock_modelcomponent_visibility_probe_2026_08_15.json"
)
MODEL2_EXPORT = 11515
VISIBILITY_TERMS = (
    "hidden",
    "visible",
    "render",
    "draw",
    "shadow",
    "collide",
    "collision",
    "block",
    "owner",
    "light",
)


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
    spec = importlib.util.spec_from_file_location("gowr_gridlock_bsp_confidence_for_modelcomponent_visibility", BSP_CONFIDENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {BSP_CONFIDENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_gridlock_bsp_confidence_for_modelcomponent_visibility"] = module
    spec.loader.exec_module(module)
    return module


bsp = load_bsp()
heavy = bsp.heavy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompressed", default=str(DEFAULT_DECOMPRESSED))
    parser.add_argument("--proof-out", default=str(DEFAULT_OUT))
    return parser.parse_args()


def load_package(path: Path):
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


def interesting_tag(tag: dict[str, Any]) -> bool:
    text = " ".join(
        [
            str(tag.get("name", "")),
            str(tag.get("base_name", "")),
            str(tag.get("type", "")),
            json.dumps(tag.get("decoded", ""), ensure_ascii=True),
        ]
    ).lower()
    return any(term in text for term in VISIBILITY_TERMS)


def ref_scan_has_model2(virt: bytes, row: dict[str, Any], ref_path) -> bool:
    import struct

    start = int(row["serial_offset"])
    for rel in range(0, int(row["serial_size"]) - 3, 4):
        value = struct.unpack_from("<i", virt, start + rel)[0]
        if value == MODEL2_EXPORT:
            return True
        try:
            path = ref_path(value)
        except Exception:
            continue
        if path.endswith(".Model_2"):
            return True
    return False


def main() -> int:
    args = parse_args()
    virt, names, imports, exports, ref_path = load_package(Path(args.decompressed))
    rows: list[dict[str, Any]] = []
    for row in exports:
        if str(row.get("class_name")) != "ModelComponent":
            continue
        has_model2 = ref_scan_has_model2(virt, row, ref_path)
        scan = heavy.best_property_scan(virt, names, exports, imports, ref_path, row, [4, 0])
        tags = scan.get("result", {}).get("tags", []) if scan else []
        named_tags = [tag for tag in tags if tag.get("name") != "None"]
        visibility_tags = [tag for tag in named_tags if interesting_tag(tag)]
        rows.append(
            {
                "export_index": row["index"],
                "object_name": row["object_short_name"],
                "full_path": row["full_path"],
                "has_model2_ref": has_model2,
                "property_scan_ok": bool(scan.get("result", {}).get("ok")) if scan else False,
                "property_scan_start_rel": scan.get("start_rel") if scan else None,
                "property_scan_end_rel": scan.get("result", {}).get("end_rel") if scan else None,
                "property_count": len(named_tags),
                "visibility_tags": visibility_tags,
                "all_tags": named_tags[:80],
            }
        )
    model2_rows = [row for row in rows if row["has_model2_ref"]]
    hidden_tag_hits = [
        {
            "component": row["full_path"],
            "tag": tag,
        }
        for row in model2_rows
        for tag in row["visibility_tags"]
        if "hidden" in str(tag.get("name", "")).lower() or "hidden" in str(tag.get("base_name", "")).lower()
    ]
    proof = {
        "package": str(Path(args.decompressed)),
        "modelcomponent_count": len(rows),
        "model2_component_count": len(model2_rows),
        "model2_hidden_tag_hits": hidden_tag_hits,
        "model2_rows": model2_rows,
        "interpretation": (
            "An empty model2_hidden_tag_hits list means the source package does not expose an explicit tagged bHidden/bHiddenGame override "
            "on these ModelComponents; it does not prove the BSP is visually important, only that it is source-renderable/default-visible."
        ),
    }
    out = Path(args.proof_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"proof_out": str(out), "model2_components": len(model2_rows), "hidden_tag_hits": len(hidden_tag_hits)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
