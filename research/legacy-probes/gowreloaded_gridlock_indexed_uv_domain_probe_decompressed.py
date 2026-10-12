#!/usr/bin/env python3
"""Run the indexed UV probe against a decompressed Reloaded package copy."""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SCRIPT = Path(__file__).with_name("gowreloaded_gridlock_indexed_uv_domain_probe.py")


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def f16(data: bytes, off: int) -> float:
    return struct.unpack_from("<e", data, off)[0]


def parse_json_field(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def package_virtual_bytes(map_dir: Path, package_name: str, cache: dict[str, bytes]) -> bytes:
    key = package_name.lower()
    if key in cache:
        return cache[key]

    package_path = map_dir / package_name
    stem = Path(package_name).stem
    suffix = Path(package_name).suffix or ".war"
    candidates = [
        package_path,
        map_dir / f"{stem}.decompressed{suffix}",
        map_dir / f"{stem}.decompressed.war",
    ]
    for candidate in candidates:
        if candidate.exists():
            cache[key] = candidate.read_bytes()
            return cache[key]
    raise FileNotFoundError(f"no decompressed package for {package_name} under {map_dir}")


def main() -> int:
    spec = importlib.util.spec_from_file_location("gridlock_indexed_uv_domain_probe", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.load_source = lambda: SimpleNamespace(
        u16=u16,
        u32=u32,
        f16=f16,
        f32=f32,
        parse_json_field=parse_json_field,
        package_virtual_bytes=package_virtual_bytes,
    )
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
