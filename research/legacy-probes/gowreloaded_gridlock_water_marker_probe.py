#!/usr/bin/env python3
"""Probe raw marker offsets in the three Gridlock skeletal water meshes."""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path


HEAVY_TOOL = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py")
MAP_FILE = Path(r"D:\SteamLibrary\steamapps\common\Gears of War Reloaded\WarGame\CookedPC\Maps\MP_Maps\MP_Gridlock.war")
WATER_PREFIX = "FX_MP_GridlockWater_Delta.gridlockWater_skMesh"


def load_heavy():
    spec = importlib.util.spec_from_file_location("gowr_heavy", HEAVY_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(HEAVY_TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def find_all(data: bytes, needle: bytes) -> list[int]:
    out = []
    pos = data.find(needle)
    while pos >= 0:
        out.append(pos)
        pos = data.find(needle, pos + 1)
    return out


def table(data: bytes, rel: int, words: int = 24):
    out = []
    for n in range(words):
        off = rel + n * 4
        if off + 4 > len(data):
            break
        out.append({"rel": off, "hex": data[off:off+4].hex(), "i32": i32(data, off), "f32": f32(data, off)})
    return out


def main() -> int:
    heavy = load_heavy()
    virt, _, _ = heavy.rebuild_virtual_package(MAP_FILE.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    rows = []
    for row in exports:
        if ref_short_name(row["class_ref"]) != "SkeletalMesh":
            continue
        full_path = ref_path(row["index"])
        if not full_path.startswith(WATER_PREFIX):
            continue
        data = virt[row["serial_offset"] : row["serial_offset"] + row["serial_size"]]
        markers = {
            "i32_3249": find_all(data, struct.pack("<i", 3249))[:40],
            "i32_18816": find_all(data, struct.pack("<i", 18816))[:40],
            "i32_68": find_all(data, struct.pack("<i", 68))[:40],
            "float_neg286ish": [],
        }
        # Cheap scan for negative water-corner-ish floats.
        for rel in range(0, len(data) - 12, 4):
            x, y, z = f32(data, rel), f32(data, rel + 4), f32(data, rel + 8)
            if -500.0 <= x <= -200.0 and -2600.0 <= y <= -1800.0 and -200.0 <= z <= 200.0:
                markers["float_neg286ish"].append(rel)
                if len(markers["float_neg286ish"]) >= 40:
                    break
        context = {}
        for label, offsets in markers.items():
            context[label] = {str(off): table(data, max(0, off - 16), 12) for off in offsets[:4]}
        rows.append({"name": row["object_short_name"], "serial_size": row["serial_size"], "markers": markers, "context": context})
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
