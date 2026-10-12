#!/usr/bin/env python3
"""Search the middle Gridlock skeletal water mesh for its vertex stream."""

from __future__ import annotations

import importlib.util
import json
import math
import struct
import sys
from pathlib import Path


HEAVY_TOOL = Path(r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py")
MAP_FILE = Path(r"D:\SteamLibrary\steamapps\common\Gears of War Reloaded\WarGame\CookedPC\Maps\MP_Maps\MP_Gridlock.war")
TARGET = "gridlockWater_skMesh_sc_ma_01_gridlock_water_01_MESH"


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


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def finite(v: float) -> bool:
    return math.isfinite(v) and abs(v) < 500000.0


def find_index(data: bytes) -> tuple[int, int]:
    for rel in range(0, len(data) - 8):
        if i32(data, rel) == 2 and i32(data, rel + 4) == 18816:
            vals = [u16(data, rel + 8 + n * 2) for n in range(18816)]
            if min(vals) == 0 and max(vals) == 3248 and len(set(vals)) == 3249:
                return rel, rel + 8 + 18816 * 2
    raise RuntimeError("index not found")


def bounds(points):
    mins = [min(p[i] for p in points) for i in range(3)]
    maxs = [max(p[i] for p in points) for i in range(3)]
    return {"min": mins, "max": maxs, "extent": [(maxs[i] - mins[i]) / 2 for i in range(3)], "center": [(mins[i] + maxs[i]) / 2 for i in range(3)]}


def try_stream(data: bytes, rel: int, stride: int):
    if rel + 3248 * stride + 12 > len(data):
        return None
    sample_indices = [0, 1, 2, 3, 4, 57, 58, 1624, 3244, 3245, 3246, 3247, 3248]
    sample = []
    for idx in sample_indices:
        off = rel + idx * stride
        p = (f32(data, off), f32(data, off + 4), f32(data, off + 8))
        if not all(finite(v) for v in p):
            return None
        sample.append(p)
    sb = bounds(sample)
    if max(sb["extent"][0], sb["extent"][1]) < 1000 or sb["extent"][2] > 500:
        return None
    points = []
    for idx in range(3249):
        off = rel + idx * stride
        p = (f32(data, off), f32(data, off + 4), f32(data, off + 8))
        if not all(finite(v) for v in p):
            return None
        points.append(p)
    b = bounds(points)
    if max(b["extent"][0], b["extent"][1]) < 1000 or b["extent"][2] > 500:
        return None
    return {"rel": rel, "stride": stride, "bounds": b, "first": points[:5], "mid": points[1624:1629], "last": points[-5:]}


def main() -> int:
    heavy = load_heavy()
    virt, _, _ = heavy.rebuild_virtual_package(MAP_FILE.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for row in exports:
        if ref_short_name(row["class_ref"]) != "SkeletalMesh" or row["object_short_name"] != TARGET:
            continue
        data = virt[row["serial_offset"] : row["serial_offset"] + row["serial_size"]]
        idx_rel, idx_end = find_index(data)
        hits = []
        for rel in range(0, len(data) - 12, 4):
            x, y, z = f32(data, rel), f32(data, rel + 4), f32(data, rel + 8)
            if not all(finite(v) for v in (x, y, z)):
                continue
            for stride in (32, 36, 40, 44, 48, 52, 56, 60, 64, 68, 72, 80, 88, 96):
                hit = try_stream(data, rel, stride)
                if hit:
                    hits.append(hit)
        hits.sort(key=lambda h: (h["bounds"]["extent"][2], h["rel"]))
        print(json.dumps({"index_rel": idx_rel, "index_end": idx_end, "hits": hits[:20]}, indent=2))
        return 0
    raise RuntimeError("target not found")


if __name__ == "__main__":
    raise SystemExit(main())
