#!/usr/bin/env python3
"""Hash-lock the surviving Reloaded research and compact evidence corpus."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    (ROOT / "research" / "legacy-probes", "legacy-probe", "canonical-workspace/tools"),
    (ROOT / "evidence" / "legacy-snapshots", "legacy-evidence", "canonical-workspace/evidence-and-reports"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    items: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    for directory, kind, source_prefix in SOURCES:
        for path in sorted(candidate for candidate in directory.rglob("*") if candidate.is_file()):
            relative = path.relative_to(ROOT).as_posix()
            items.append(
                {
                    "kind": kind,
                    "source": f"{source_prefix}/{path.relative_to(directory).as_posix()}",
                    "destination": relative,
                    "destinationBytes": path.stat().st_size,
                    "destinationSha256": sha256_file(path),
                }
            )
            counts[kind] += 1

    output = ROOT / "inventory" / "legacy-migration.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema": "gowr_legacy_migration_v1",
                "itemCount": len(items),
                "countsByKind": dict(sorted(counts.items())),
                "items": items,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output}: {len(items)} hash-locked items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
