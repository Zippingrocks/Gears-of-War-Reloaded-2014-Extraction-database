#!/usr/bin/env python3
"""Decode MP_Gridlock Model_2 UModel tail through the cooked render vertex buffer."""

from __future__ import annotations

import importlib.util
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any


BASE = Path(__file__).with_name("gowreloaded_gridlock_model2_render_vertexbuffer_probe.py")
DEFAULT_PROOF = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\BSP_Confidence\gridlock_model2_render_vertexbuffer_probe_v2_2026_08_15.json"
)


def load_base():
    spec = importlib.util.spec_from_file_location("gowr_gridlock_model2_render_vb_probe_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {BASE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_gridlock_model2_render_vb_probe_base"] = module
    spec.loader.exec_module(module)
    return module


base = load_base()


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def parse_bulk_header(virt: bytes, serial: int, serial_size: int, rel: int, label: str) -> dict[str, Any]:
    if rel + 8 > serial_size:
        return {"label": label, "rel": rel, "ok": False, "reason": "header_oob"}
    elem = i32(virt, serial + rel)
    count = i32(virt, serial + rel + 4)
    end_rel = rel + 8 + elem * count
    ok = elem >= 0 and count >= 0 and end_rel <= serial_size
    return {"label": label, "rel": rel, "element_size": elem, "count": count, "end_rel": end_rel, "ok": ok}


def read_deprecated_vertex(virt: bytes, off: int) -> dict[str, Any]:
    return {
        "position": [f32(virt, off), f32(virt, off + 4), f32(virt, off + 8)],
        "tangent_x_packed": u32(virt, off + 12),
        "tangent_z_packed": u32(virt, off + 16),
        "texcoord": [f32(virt, off + 20), f32(virt, off + 24)],
        "shadow_texcoord": [f32(virt, off + 28), f32(virt, off + 32)],
    }


def read_new_vertex(virt: bytes, off: int) -> dict[str, Any]:
    return {
        "position": [f32(virt, off), f32(virt, off + 4), f32(virt, off + 8)],
        "tangent_x": [f32(virt, off + 12), f32(virt, off + 16), f32(virt, off + 20)],
        "tangent_z": [f32(virt, off + 24), f32(virt, off + 28), f32(virt, off + 32), f32(virt, off + 36)],
        "texcoord": [f32(virt, off + 40), f32(virt, off + 44)],
        "shadow_texcoord": [f32(virt, off + 48), f32(virt, off + 52)],
    }


def finite(values: list[float], limit: float = 1_000_000.0) -> bool:
    return all(math.isfinite(v) and abs(v) <= limit for v in values)


def stats2(values: list[list[float]]) -> dict[str, Any]:
    if not values:
        return {}
    xs = [v[0] for v in values]
    ys = [v[1] for v in values]
    return {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)], "span": [max(xs) - min(xs), max(ys) - min(ys)], "sample": [[round(v[0], 6), round(v[1], 6)] for v in values[:12]]}


def stats3(values: list[list[float]]) -> dict[str, Any]:
    if not values:
        return {}
    return {
        "min": [min(v[a] for v in values) for a in range(3)],
        "max": [max(v[a] for v in values) for a in range(3)],
        "span": [max(v[a] for v in values) - min(v[a] for v in values) for a in range(3)],
    }


def score_vb(virt: bytes, serial: int, serial_size: int, rel: int, mode: str, stride: int, required_vertices: int) -> dict[str, Any]:
    if mode == "bulk":
        header = parse_bulk_header(virt, serial, serial_size, rel, f"vertex_buffer_{mode}_{stride}")
        if not header.get("ok"):
            return header | {"mode": mode, "stride": stride}
        count = int(header["count"])
        element_size = int(header["element_size"])
        data_rel = rel + 8
        if element_size != stride:
            return header | {"mode": mode, "stride": stride, "ok": False, "reason": "stride_mismatch"}
    else:
        if rel + 4 > serial_size:
            return {"mode": mode, "stride": stride, "rel": rel, "ok": False, "reason": "header_oob"}
        count = i32(virt, serial + rel)
        element_size = stride
        data_rel = rel + 4
    if count < required_vertices or count > 100000:
        return {"mode": mode, "stride": stride, "rel": rel, "element_size": element_size, "count": count, "ok": False, "reason": "bad_count"}
    end_rel = data_rel + count * stride
    if end_rel > serial_size:
        return {"mode": mode, "stride": stride, "rel": rel, "element_size": element_size, "count": count, "ok": False, "reason": "data_oob", "end_rel": end_rel}
    reader = read_deprecated_vertex if stride == 36 else read_new_vertex
    positions: list[list[float]] = []
    texcoords: list[list[float]] = []
    shadows: list[list[float]] = []
    for idx in range(min(count, 20000)):
        vertex = reader(virt, serial + data_rel + idx * stride)
        if not finite(vertex["position"]):
            return {"mode": mode, "stride": stride, "rel": rel, "element_size": element_size, "count": count, "ok": False, "reason": "bad_position", "bad_index": idx}
        if not finite(vertex["texcoord"], 100000):
            return {"mode": mode, "stride": stride, "rel": rel, "element_size": element_size, "count": count, "ok": False, "reason": "bad_texcoord", "bad_index": idx, "sample": vertex}
        positions.append(vertex["position"])
        texcoords.append(vertex["texcoord"])
        shadows.append(vertex["shadow_texcoord"])
    sample_indices = sorted({0, 1, min(count - 1, required_vertices - 1), count - 1})
    samples = [reader(virt, serial + data_rel + idx * stride) | {"index": idx} for idx in sample_indices]
    return {
        "ok": True,
        "mode": mode,
        "stride": stride,
        "rel": rel,
        "data_rel": data_rel,
        "element_size": element_size,
        "count": count,
        "end_rel": end_rel,
        "required_vertices": required_vertices,
        "remaining_bytes_after_data": serial_size - end_rel,
        "position_stats": stats3(positions),
        "texcoord_stats": stats2(texcoords),
        "shadow_texcoord_stats": stats2(shadows),
        "samples": samples,
    }


def parse_known_ue3_tail(virt: bytes, row: dict[str, Any], tail: dict[str, Any], required_vertices: int) -> dict[str, Any]:
    serial = int(row["serial_offset"])
    serial_size = int(row["serial_size"])
    rel = int(tail["vert_end_rel"])
    steps: list[dict[str, Any]] = []

    num_shared_sides = i32(virt, serial + rel)
    steps.append({"label": "NumSharedSides", "rel": rel, "value": num_shared_sides})
    rel += 4

    zone_count = i32(virt, serial + rel)
    zones_rel = rel
    zones_end = rel + 4 + zone_count * 24 if 0 <= zone_count < 512 else rel
    steps.append({"label": "Zones", "rel": zones_rel, "count": zone_count, "element_size_assumed": 24, "end_rel": zones_end})
    rel = zones_end

    dummy_polys = i32(virt, serial + rel)
    steps.append({"label": "DummyPolys", "rel": rel, "value": dummy_polys})
    rel += 4

    dummy_leaf_hulls = parse_bulk_header(virt, serial, serial_size, rel, "DummyLeafHulls")
    steps.append(dummy_leaf_hulls)
    rel = int(dummy_leaf_hulls.get("end_rel", rel))

    dummy_leaves = parse_bulk_header(virt, serial, serial_size, rel, "DummyLeaves")
    steps.append(dummy_leaves)
    rel = int(dummy_leaves.get("end_rel", rel))

    root_outside = i32(virt, serial + rel)
    linked = i32(virt, serial + rel + 4)
    steps.append({"label": "RootOutside_Linked", "rel": rel, "root_outside": root_outside, "linked": linked})
    rel += 8

    portal_nodes = parse_bulk_header(virt, serial, serial_size, rel, "PortalNodes")
    if portal_nodes.get("ok") and portal_nodes.get("element_size") == 4:
        steps.append(portal_nodes)
        rel = int(portal_nodes["end_rel"])
    else:
        steps.append(portal_nodes | {"note": "not consumed"})

    num_unique_vertices = u32(virt, serial + rel)
    steps.append({"label": "NumUniqueVertices", "rel": rel, "value": num_unique_vertices})
    rel += 4

    candidates = []
    for offset in range(0, 64, 4):
        for mode, stride in (("bulk", 36), ("array", 56), ("bulk", 56), ("array", 36)):
            candidates.append(score_vb(virt, serial, serial_size, rel + offset, mode, stride, required_vertices))
    candidates.sort(key=lambda c: (not c.get("ok", False), abs(int(c.get("remaining_bytes_after_data", 999999999))), int(c.get("rel", 0))))
    return {"steps": steps, "vertex_buffer_search_base_rel": rel, "vertex_buffer_candidates": candidates[:24]}


def main() -> int:
    package = Path(sys.argv[1]) if len(sys.argv) > 1 else base.DEFAULT_DECOMPRESSED
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PROOF
    virt, names, imports, exports, _ref_short_name, ref_path = base.load_package_tables(package)
    row, lm, decoded = base.decode_model2(virt, names, imports, exports, ref_path)
    nodes = base.read_nodes_raw(virt, row, lm)
    visible_nodes = [node for node in nodes if int(node["num_vertices"]) >= 3 and int(node["i_vertex_index"]) >= 0]
    required_vertices = max((int(node["i_vertex_index"]) + int(node["num_vertices"]) for node in visible_nodes), default=0)
    tail = base.fvert_tail(virt, row, lm)
    parsed_tail = parse_known_ue3_tail(virt, row, tail, required_vertices)
    proof = {
        "package": str(package),
        "source": {
            "export_index": base.MODEL2_EXPORT_INDEX,
            "full_path": row.get("full_path", ""),
            "serial_offset": row.get("serial_offset"),
            "serial_size": row.get("serial_size"),
            "decode_status": decoded.get("status"),
            "node_count": len(nodes),
            "visible_node_count": len(visible_nodes),
            "triangle_count_from_nodes": len(decoded.get("triangles") or []),
        },
        "node_i_vertex_index": {
            "required_vertices": required_vertices,
            "min": min((int(node["i_vertex_index"]) for node in visible_nodes), default=0),
            "max": max((int(node["i_vertex_index"]) for node in visible_nodes), default=0),
            "samples": visible_nodes[:16],
        },
        "after_fverts": tail,
        "parsed_tail": parsed_tail,
        "repo_basis": {
            "CUE4Parse": "UModel serializes Verts, NumSharedSides, zones/dummy editor arrays for this old UE version, RootOutside/Linked, PortalNodes, NumUniqueVertices, then FModelVertexBuffer.",
            "fix_target": "Build Model_2 from FBspNode.iVertexIndex + FModelVertexBuffer.Position/TexCoord instead of shared FPoints + projected FBspSurf UVs.",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "required_vertices": required_vertices, "steps": parsed_tail["steps"], "best_candidates": parsed_tail["vertex_buffer_candidates"][:4]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
