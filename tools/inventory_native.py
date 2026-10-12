#!/usr/bin/env python3
"""Create a metadata-only inventory of an owned Reloaded CookedPC tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reloaded_package import PackageFormatError, read_package_summary  # noqa: E402


INVENTORY_SUFFIXES = {".war", ".upk", ".tfc", ".bik"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Owned WarGame directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--anchor", action="append", default=[], help="Relative file to hash; may be repeated")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in INVENTORY_SUFFIXES),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    by_extension: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "bytes": 0})
    files: list[dict[str, Any]] = []
    package_errors = 0

    for path in paths:
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        size = path.stat().st_size
        by_extension[suffix]["count"] += 1
        by_extension[suffix]["bytes"] += size
        row: dict[str, Any] = {"relativePath": relative, "bytes": size, "kind": suffix[1:]}
        if suffix in {".war", ".upk"}:
            try:
                row["packageSummary"] = asdict(read_package_summary(path))
            except (OSError, PackageFormatError) as exc:
                package_errors += 1
                row["packageError"] = str(exc)
        files.append(row)

    anchors: list[dict[str, Any]] = []
    for value in args.anchor:
        normalized = Path(*PurePosixPath(value.replace("\\", "/")).parts)
        path = root / normalized
        if not path.is_file():
            raise FileNotFoundError(f"anchor does not exist under root: {value}")
        anchors.append(
            {
                "relativePath": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    result = {
        "schema": "gowr_native_inventory_v1",
        "sourceLabel": args.source_label,
        "fileCount": len(files),
        "totalBytes": sum(row["bytes"] for row in files),
        "packageSummaryErrors": package_errors,
        "byExtension": dict(sorted(by_extension.items())),
        "anchors": anchors,
        "files": files,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(files)} files, {result['totalBytes']} bytes, {package_errors} package errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
