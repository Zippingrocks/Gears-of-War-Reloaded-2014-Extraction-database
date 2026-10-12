#!/usr/bin/env python3
"""Read the stable front matter of Reloaded cooked Unreal packages."""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path


PACKAGE_TAG = 0x9E2A83C1
MAX_FSTRING_UNITS = 1_048_576


class PackageFormatError(ValueError):
    """Raised when a file cannot satisfy the maintained package contract."""


@dataclass(frozen=True)
class PackageSummary:
    tag: str
    file_version: int
    licensee_version: int
    header_size: int
    folder_name: str
    package_flags: str
    name_count: int
    name_offset: int
    export_count: int
    export_offset: int
    import_count: int
    import_offset: int
    depends_offset: int


def _require(data: bytes, offset: int, size: int) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise PackageFormatError(f"truncated package header at offset {offset} for {size} bytes")


def _i16(data: bytes, offset: int) -> int:
    _require(data, offset, 2)
    return struct.unpack_from("<h", data, offset)[0]


def _i32(data: bytes, offset: int) -> int:
    _require(data, offset, 4)
    return struct.unpack_from("<i", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    _require(data, offset, 4)
    return struct.unpack_from("<I", data, offset)[0]


def read_fstring(data: bytes, offset: int) -> tuple[str, int]:
    """Read an ANSI or UTF-16 Unreal FString and return value plus new offset."""
    units = _i32(data, offset)
    offset += 4
    if units == 0:
        return "", offset
    if abs(units) > MAX_FSTRING_UNITS:
        raise PackageFormatError(f"implausible FString length {units}")

    if units > 0:
        _require(data, offset, units)
        raw = data[offset : offset + units]
        value = raw[:-1] if raw.endswith(b"\0") else raw
        return value.decode("latin-1"), offset + units

    byte_count = -units * 2
    _require(data, offset, byte_count)
    raw = data[offset : offset + byte_count]
    value = raw[:-2] if raw.endswith(b"\0\0") else raw
    return value.decode("utf-16-le"), offset + byte_count


def parse_package_summary(data: bytes) -> PackageSummary:
    _require(data, 0, 16)
    tag = _u32(data, 0)
    if tag != PACKAGE_TAG:
        raise PackageFormatError(f"unexpected package tag 0x{tag:08X}")

    folder_name, offset = read_fstring(data, 12)
    _require(data, offset, 32)
    package_flags = _u32(data, offset)
    values = struct.unpack_from("<7i", data, offset + 4)
    fields = ("name_count", "name_offset", "export_count", "export_offset", "import_count", "import_offset", "depends_offset")
    decoded = dict(zip(fields, values, strict=True))

    header_size = _i32(data, 8)
    if header_size <= 0:
        raise PackageFormatError(f"invalid header size {header_size}")
    for count_key in ("name_count", "export_count", "import_count"):
        if decoded[count_key] < 0:
            raise PackageFormatError(f"negative {count_key}: {decoded[count_key]}")
    for offset_key in ("name_offset", "export_offset", "import_offset", "depends_offset"):
        if decoded[offset_key] < 0:
            raise PackageFormatError(f"negative {offset_key}: {decoded[offset_key]}")

    return PackageSummary(
        tag=f"0x{tag:08X}",
        file_version=_i16(data, 4),
        licensee_version=_i16(data, 6),
        header_size=header_size,
        folder_name=folder_name,
        package_flags=f"0x{package_flags:08X}",
        **decoded,
    )


def read_package_summary(path: Path, read_size: int = 4096) -> PackageSummary:
    with path.open("rb") as stream:
        return parse_package_summary(stream.read(read_size))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    summary = asdict(read_package_summary(args.package))
    summary["package"] = args.package.name
    print(json.dumps(summary, indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
