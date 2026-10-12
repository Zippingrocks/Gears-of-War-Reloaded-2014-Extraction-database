#!/usr/bin/env python3
"""Compatibility wrapper for the Model_2 BSP texel-UV fix.

The base tool was written against an older helper name. This wrapper keeps the
base implementation intact and patches the decode call to the current
gowreloaded_factory_interior_bsp_confidence.decode_landmarks API.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


BASE = Path(__file__).with_name("gowreloaded_gridlock_model2_bsp_texel_uv_fix.py")


def load_base():
    spec = importlib.util.spec_from_file_location("gowr_gridlock_model2_bsp_texel_uv_fix_base", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {BASE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_gridlock_model2_bsp_texel_uv_fix_base"] = module
    spec.loader.exec_module(module)
    return module


base = load_base()
_last_tables: tuple[Any, ...] | None = None


def load_package_tables_fixed(path: Path):
    global _last_tables
    result = base._original_load_package_tables(path)
    _last_tables = result
    return result


def decode_model2_fixed(virt: bytes, exports: list[dict[str, Any]]):
    if _last_tables is None:
        raise RuntimeError("package tables were not loaded before decode_model2")
    _virt, names, imports, _exports, _ref_short_name, ref_path = _last_tables
    row = base.model_row(exports, base.MODEL2_EXPORT_INDEX)
    lm = base.bsp.decode_landmarks(virt, names, imports, exports, ref_path, row)
    if lm is None:
        raise RuntimeError("Model_2 landmark decode failed")
    decoded = base.bsp.decode_model_faces(virt, row, lm)
    if not decoded.get("triangles"):
        raise RuntimeError(f"Model_2 did not decode visible BSP triangles: {decoded.get('status')}")
    return row, lm, decoded


base._original_load_package_tables = base.load_package_tables
base.load_package_tables = load_package_tables_fixed
base.decode_model2 = decode_model2_fixed


if __name__ == "__main__":
    raise SystemExit(base.main())
