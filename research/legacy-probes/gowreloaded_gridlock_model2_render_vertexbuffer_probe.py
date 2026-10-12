#!/usr/bin/env python3
"""Probe MP_Gridlock Model_2 cooked BSP render vertex buffer.

CUE4Parse's UModel layout shows that cooked BSP has a render vertex buffer with
per-vertex TexCoord/ShadowTexCoord after the editor FVerts pool. This probe
finds that buffer in the decompressed Reloaded package and compares it against
the node iVertexIndex ranges.
"""

from __future__ import annotations

import importlib.util
import json
import math
import struct
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
DEFAULT_PROOF = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Multiplayer\MP_Gridlock_Parse_2026_08_12\BSP_Confidence\gridlock_model2_render_vertexbuffer_probe_2026_08_15.json"
)

MODEL2_EXPORT_INDEX = 11515
NODE_RECORD_SIZE = 64
NODE_IVERT_POOL_REL = 16
NODE_ISURF_REL = 20
NODE_IVERTEX_INDEX_REL = 24
NODE_NUM_VERTICES_REL = 54
SURF_RECORD_SIZE = 68
FVERT_RECORD_SIZE = 24


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


def load_bsp_module():
    install_fake_lz4()
    return load_module(BSP_CONFIDENCE, "gowr_gridlock_bsp_confidence_render_vb_probe")


bsp = load_bsp_module()
heavy = bsp.heavy


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def finite_vec(values: list[float], limit: float = 1_000_000.0) -> bool:
    return all(math.isfinite(value) and abs(value) <= limit for value in values)


def bounds(values: list[list[float]]) -> dict[str, Any]:
    if not values:
        return {}
    mins = [min(value[axis] for value in values) for axis in range(3)]
    maxs = [max(value[axis] for value in values) for axis in range(3)]
    return {"min": mins, "max": maxs, "extent": [maxs[i] - mins[i] for i in range(3)]}


def uv_stats(values: list[list[float]]) -> dict[str, Any]:
    if not values:
        return {}
    us = [value[0] for value in values]
    vs = [value[1] for value in values]
    return {
        "min": [min(us), min(vs)],
        "max": [max(us), max(vs)],
        "span": [max(us) - min(us), max(vs) - min(vs)],
        "sample": [[round(value[0], 6), round(value[1], 6)] for value in values[:12]],
    }


def load_package_tables(path: Path) -> tuple[bytes, list[str], list[dict[str, Any]], list[dict[str, Any]], Any, Any]:
    data = path.read_bytes()
    virt, _groups, _mode = heavy.rebuild_virtual_package(data)
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)
    for export in exports:
        export["class_name"] = ref_short_name(export["class_ref"])
        export["full_path"] = ref_path(export["index"])
    return virt, names, imports, exports, ref_short_name, ref_path


def model_row(exports: list[dict[str, Any]], export_index: int) -> dict[str, Any]:
    row = exports[export_index - 1]
    if row.get("class_name") != "Model":
        raise RuntimeError(f"export {export_index} is not Model: {row.get('class_name')}")
    return row


def decode_model2(virt: bytes, names: list[str], imports: list[dict[str, Any]], exports: list[dict[str, Any]], ref_path):
    row = model_row(exports, MODEL2_EXPORT_INDEX)
    lm = bsp.decode_landmarks(virt, names, imports, exports, ref_path, row)
    if lm is None:
        raise RuntimeError("Model_2 landmarks failed")
    decoded = bsp.decode_model_faces(virt, row, lm)
    return row, lm, decoded


def read_nodes_raw(virt: bytes, row: dict[str, Any], lm: dict[str, Any]) -> list[dict[str, Any]]:
    serial = int(row["serial_offset"])
    data_rel = int(lm["nodes"]["data_rel"])
    count = int(lm["nodes"]["count"])
    out: list[dict[str, Any]] = []
    for idx in range(count):
        base = serial + data_rel + idx * NODE_RECORD_SIZE
        out.append(
            {
                "node_index": idx,
                "i_vert_pool": i32(virt, base + NODE_IVERT_POOL_REL),
                "i_surf": i32(virt, base + NODE_ISURF_REL),
                "i_vertex_index": i32(virt, base + NODE_IVERTEX_INDEX_REL),
                "component_index": u16(virt, base + 28),
                "component_node_index": u16(virt, base + 30),
                "component_element_index": i32(virt, base + 32),
                "num_vertices": virt[base + NODE_NUM_VERTICES_REL],
                "node_flags": virt[base + 55],
            }
        )
    return out


def fvert_tail(virt: bytes, row: dict[str, Any], lm: dict[str, Any]) -> dict[str, Any]:
    serial = int(row["serial_offset"])
    surf_rel = int(lm["nodes"]["end_rel"])
    surf_count = i32(virt, serial + surf_rel + 4)
    vert_header_rel = surf_rel + 8 + surf_count * SURF_RECORD_SIZE
    vert_element_size = i32(virt, serial + vert_header_rel)
    vert_count = i32(virt, serial + vert_header_rel + 4)
    vert_data_rel = vert_header_rel + 8
    vert_end_rel = vert_data_rel + vert_count * FVERT_RECORD_SIZE
    return {
        "surf_rel": surf_rel,
        "surf_count": surf_count,
        "vert_header_rel": vert_header_rel,
        "vert_element_size": vert_element_size,
        "vert_count": vert_count,
        "vert_data_rel": vert_data_rel,
        "vert_end_rel": vert_end_rel,
        "tail_abs": serial + vert_end_rel,
    }


def parse_bool_i32(data: bytes, off: int) -> int | None:
    if off + 4 > len(data):
        return None
    value = i32(data, off)
    return value if value in (0, 1) else None


def read_vertex_deprecated(virt: bytes, off: int) -> dict[str, Any]:
    position = [f32(virt, off), f32(virt, off + 4), f32(virt, off + 8)]
    tangent_x_packed = u32(virt, off + 12)
    tangent_z_packed = u32(virt, off + 16)
    texcoord = [f32(virt, off + 20), f32(virt, off + 24)]
    shadow = [f32(virt, off + 28), f32(virt, off + 32)]
    return {
        "position": position,
        "tangent_x_packed": tangent_x_packed,
        "tangent_z_packed": tangent_z_packed,
        "texcoord": texcoord,
        "shadow_texcoord": shadow,
    }


def read_vertex_new(virt: bytes, off: int) -> dict[str, Any]:
    position = [f32(virt, off), f32(virt, off + 4), f32(virt, off + 8)]
    tangent_x = [f32(virt, off + 12), f32(virt, off + 16), f32(virt, off + 20)]
    tangent_z = [f32(virt, off + 24), f32(virt, off + 28), f32(virt, off + 32), f32(virt, off + 36)]
    texcoord = [f32(virt, off + 40), f32(virt, off + 44)]
    shadow = [f32(virt, off + 48), f32(virt, off + 52)]
    return {
        "position": position,
        "tangent_x": tangent_x,
        "tangent_z": tangent_z,
        "texcoord": texcoord,
        "shadow_texcoord": shadow,
    }


def score_vertex_buffer(
    virt: bytes,
    row: dict[str, Any],
    start_rel: int,
    header_kind: str,
    stride: int,
    required_vertices: int,
) -> dict[str, Any]:
    serial = int(row["serial_offset"])
    start_abs = serial + start_rel
    if header_kind == "bulk":
        if start_abs + 8 > serial + int(row["serial_size"]):
            return {"ok": False, "reason": "header_oob"}
        element_size = i32(virt, start_abs)
        count = i32(virt, start_abs + 4)
        data_abs = start_abs + 8
    elif header_kind == "array":
        if start_abs + 4 > serial + int(row["serial_size"]):
            return {"ok": False, "reason": "header_oob"}
        element_size = stride
        count = i32(virt, start_abs)
        data_abs = start_abs + 4
    else:
        raise ValueError(header_kind)
    if count < required_vertices or count > 500_000 or element_size != stride:
        return {"ok": False, "start_rel": start_rel, "header_kind": header_kind, "stride": stride, "element_size": element_size, "count": count}
    data_end = data_abs + count * stride
    if data_end > serial + int(row["serial_size"]):
        return {"ok": False, "start_rel": start_rel, "header_kind": header_kind, "stride": stride, "element_size": element_size, "count": count, "reason": "data_oob"}
    reader = read_vertex_deprecated if stride == 36 else read_vertex_new
    sample_indices = sorted({0, 1, min(count - 1, required_vertices - 1), count - 1})
    samples = [reader(virt, data_abs + idx * stride) | {"index": idx} for idx in sample_indices]
    sample_ok = all(finite_vec(sample["position"]) and finite_vec(sample["texcoord"], 10000) for sample in samples)
    positions = []
    texcoords = []
    shadows = []
    scan_count = min(count, 20000)
    for idx in range(scan_count):
        vertex = reader(virt, data_abs + idx * stride)
        if not finite_vec(vertex["position"]):
            return {"ok": False, "start_rel": start_rel, "header_kind": header_kind, "stride": stride, "element_size": element_size, "count": count, "reason": "bad_position", "bad_index": idx}
        positions.append(vertex["position"])
        texcoords.append(vertex["texcoord"])
        shadows.append(vertex["shadow_texcoord"])
    return {
        "ok": sample_ok,
        "start_rel": start_rel,
        "data_rel": data_abs - serial,
        "header_kind": header_kind,
        "stride": stride,
        "element_size": element_size,
        "count": count,
        "required_vertices": required_vertices,
        "remaining_bytes_after_data": serial + int(row["serial_size"]) - data_end,
        "position_bounds_first_scan": bounds(positions),
        "texcoord_stats_first_scan": uv_stats(texcoords),
        "shadow_texcoord_stats_first_scan": uv_stats(shadows),
        "samples": samples,
    }


def main() -> int:
    package = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DECOMPRESSED
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PROOF
    virt, names, imports, exports, _ref_short_name, ref_path = load_package_tables(package)
    row, lm, decoded = decode_model2(virt, names, imports, exports, ref_path)
    nodes = read_nodes_raw(virt, row, lm)
    visible_nodes = [node for node in nodes if int(node["num_vertices"]) >= 3 and int(node["i_vertex_index"]) >= 0]
    required_vertices = max((int(node["i_vertex_index"]) + int(node["num_vertices"]) for node in visible_nodes), default=0)
    tail = fvert_tail(virt, row, lm)
    serial = int(row["serial_offset"])
    tail_abs = int(tail["tail_abs"])
    tail_words = []
    for rel in range(0, 96, 4):
        off = tail_abs + rel
        if off + 4 <= serial + int(row["serial_size"]):
            tail_words.append({"rel_from_fvert_end": rel, "i32": i32(virt, off), "u32": u32(virt, off), "f32": f32(virt, off)})
    base = int(tail["vert_end_rel"])
    candidates = []
    for skip in range(0, 96, 4):
        start_rel = base + skip
        for header_kind, stride in (("bulk", 36), ("array", 56), ("bulk", 56), ("array", 36)):
            candidate = score_vertex_buffer(virt, row, start_rel, header_kind, stride, required_vertices)
            if candidate.get("ok") or (
                candidate.get("count", 0) >= required_vertices and candidate.get("count", 0) < 500_000
            ):
                candidates.append(candidate)
    candidates.sort(key=lambda c: (not c.get("ok", False), abs(int(c.get("remaining_bytes_after_data", 999999999))), int(c.get("start_rel", 0))))
    proof = {
        "package": str(package),
        "source": {
            "export_index": MODEL2_EXPORT_INDEX,
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
        "tail_words": tail_words,
        "vertex_buffer_candidates": candidates[:24],
        "repo_basis": {
            "CUE4Parse": "UModel.FBspNode.iVertexIndex and UModel.FModelVertexBuffer Vertices contain Position, TexCoord, ShadowTexCoord after Verts/NumUniqueVertices.",
            "reason": "BSP render vertices are per-corner render data; editor point-table reconstruction shares vertices and cannot carry correct per-surface UVs.",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "required_vertices": required_vertices, "best_candidates": candidates[:4]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
