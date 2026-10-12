#!/usr/bin/env python3
"""Build a repo-layout-corrected Gridlock UV proof.

Local UEViewer/CUE4Parse references serialize StaticMesh tangents before
texcoords. For 20-byte half-precision StaticMesh UV records, `half@4` is packed
tangent/normal data, not UV0. This rewrites only those choices to `half@8` and
keeps the previous index/index_plus_half domain selection intact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-proof", required=True)
    parser.add_argument("--out-proof", required=True)
    parser.add_argument("--allow-obsolete-uv-heuristic", action="store_true")
    return parser.parse_args()


def find_candidate(asset: dict[str, Any], domain: str, domain_start: int, offset: int) -> dict[str, Any] | None:
    for candidate in asset.get("top_candidates") or []:
        if (
            candidate.get("domain") == domain
            and int(candidate.get("domain_start") or 0) == domain_start
            and str(candidate.get("encoding") or "half") == "half"
            and int(candidate.get("offset") or -1) == offset
        ):
            return candidate
    return None


def main() -> int:
    args = parse_args()
    if not args.allow_obsolete_uv_heuristic:
        raise SystemExit(
            "Refusing to build obsolete half@4->half@8 UV proof. Use "
            "gowreloaded_static_uvstream_regression_guard.py and the "
            "repo-confirmed payload exporter instead."
        )
    source = Path(args.in_proof)
    out = Path(args.out_proof)
    data = json.loads(source.read_text(encoding="utf-8"))
    overrides: list[dict[str, Any]] = []

    for key, asset in (data.get("assets") or {}).items():
        chosen = asset.get("chosen") or {}
        if not (
            int(asset.get("static_vertex_element_size") or 0) == 20
            and str(chosen.get("encoding") or "") == "half"
            and int(chosen.get("offset") or -1) == 4
        ):
            continue

        domain = str(chosen.get("domain") or "index")
        domain_start = int(chosen.get("domain_start") or 0)
        candidate = find_candidate(asset, domain, domain_start, 8)
        before = dict(chosen)
        after = dict(chosen)
        after.update(
            {
                "name": f"{domain}__half@8",
                "encoding": "half",
                "offset": 8,
                "policy": "repo_layout_tangentx_tangentz_before_uv0__CUE4Parse_FStaticMeshUVItem",
            }
        )
        asset["chosen"] = after
        asset["repo_layout_override"] = {
            "before": before,
            "after": after,
            "evidence": [
                "CUE4Parse StaticMesh/FStaticMeshUVItem.cs: SerializeTangents before SerializeTexcoords",
                "CUE4Parse StaticMesh/FStaticMeshVertexBuffer.cs: FStaticMeshUVItem array stores tangents then UV",
                "UEViewer UnrealMesh/UnMesh3.cpp: FStaticMeshUVItem3 reads packed normals before UVs",
            ],
            "candidate_stats": candidate,
        }
        overrides.append(
            {
                "key": key,
                "object_name": asset.get("object_name", ""),
                "static_vertex_element_size": asset.get("static_vertex_element_size"),
                "before": before,
                "after": after,
                "candidate_stats": candidate,
            }
        )

    data["repo_layout_staticmesh_uv_override"] = {
        "policy": "20-byte half StaticMesh UV streams cannot use offset4 because offset4 is packed TangentZ/normal data; use offset8 for UV0 per local CUE4Parse/UEViewer layout references.",
        "source_proof": str(source),
        "override_count": len(overrides),
        "overrides": overrides,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps({"out": str(out), "override_count": len(overrides), "sample": overrides[:8]}, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
