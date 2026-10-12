#!/usr/bin/env python3
"""Sanity-probe forced Gridlock skeletal water vertex layouts."""

from __future__ import annotations

import importlib.util
import json
import math
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


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def find_index(data: bytes) -> tuple[int, int]:
    for rel in range(0, len(data) - 8):
        if i32(data, rel) == 2 and i32(data, rel + 4) == 18816:
            vals = [u16(data, rel + 8 + n * 2) for n in range(18816)]
            if min(vals) == 0 and max(vals) == 3248 and len(set(vals)) == 3249:
                return rel, rel + 8 + 18816 * 2
    raise RuntimeError("index not found")


def finite(v: float) -> bool:
    return math.isfinite(v) and abs(v) < 500000.0


def score(points):
    mins = [min(p[i] for p in points) for i in range(3)]
    maxs = [max(p[i] for p in points) for i in range(3)]
    extent = [(maxs[i] - mins[i]) / 2 for i in range(3)]
    return {"min": mins, "max": maxs, "extent": extent, "center": [(mins[i] + maxs[i]) / 2 for i in range(3)]}


def main() -> int:
    heavy = load_heavy()
    virt, _, _ = heavy.rebuild_virtual_package(MAP_FILE.read_bytes())
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    rows = []
    for row in exports:
        class_name = ref_short_name(row["class_ref"])
        full_path = ref_path(row["index"])
        if class_name != "SkeletalMesh" or not full_path.startswith(WATER_PREFIX):
            continue
        data = virt[row["serial_offset"] : row["serial_offset"] + row["serial_size"]]
        idx_rel, idx_end = find_index(data)
        candidates = []
        for rel in range(idx_end, idx_end + 4000, 4):
            for stride in (64, 68, 60, 72):
                for pos_off in (0, 4, 8, 12, 16):
                    if rel + (3248 * stride) + pos_off + 12 > len(data):
                        continue
                    points = []
                    bad = 0
                    for n in range(3249):
                        off = rel + n * stride + pos_off
                        p = (f32(data, off), f32(data, off + 4), f32(data, off + 8))
                        if not all(finite(v) for v in p):
                            bad += 1
                            if bad > 0:
                                break
                        points.append(p)
                    if bad:
                        continue
                    b = score(points)
                    xy = max(b["extent"][0], b["extent"][1])
                    z = b["extent"][2]
                    if xy > 1000 and z < 500:
                        candidates.append({
                            "rel": rel,
                            "stride": stride,
                            "pos_off": pos_off,
                            "bounds": b,
                            "first": points[:3],
                            "mid": points[1624:1627],
                            "last": points[-3:],
                        })
        candidates.sort(key=lambda c: (c["bounds"]["extent"][2], -max(c["bounds"]["extent"][0], c["bounds"]["extent"][1]), c["rel"]))
        rows.append({"name": row["object_short_name"], "index_rel": idx_rel, "index_end": idx_end, "candidates": candidates[:10]})
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
