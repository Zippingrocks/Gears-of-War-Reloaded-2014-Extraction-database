#!/usr/bin/env python3
"""Blender argv wrapper for gowreloaded_gridlock_indexed_uv_domain_probe.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).with_name("gowreloaded_gridlock_indexed_uv_domain_probe.py")


def main() -> int:
    if "--" in sys.argv:
        sys.argv = [sys.argv[0], *sys.argv[sys.argv.index("--") + 1 :]]
    spec = importlib.util.spec_from_file_location("gridlock_indexed_uv_domain_probe", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
