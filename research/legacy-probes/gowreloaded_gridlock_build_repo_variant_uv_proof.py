#!/usr/bin/env python3
"""Build a repo-variant-aware Gridlock render UV proof.

UEViewer's UE3 StaticMesh reader has two relevant shapes:

* normal-bearing records read packed normals before UVs;
* stripped-normal records jump directly to UV payloads, which can leave a
  leading color/unknown dword before the first half-precision UV pair.

The previous repo-layout correction treated every 20-byte `half@4` choice as
tangent data and forced `half@8`. MP_Gridlock road/building assets disprove
that as a global rule: their `half@4` candidate is a sane tiled diffuse UV
stream, while `half@8` is a 0-1 atlas-like channel. This proof preserves the
source-scored render UV choice and annotates the stream variant.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-proof", required=True)
    parser.add_argument("--out-proof", required=True)
    return parser.parse_args()


def candidate_span(candidate: dict[str, Any] | None) -> tuple[float, float]:
    if not candidate:
        return (0.0, 0.0)
    try:
        return (float(candidate.get("span_u") or 0.0), float(candidate.get("span_v") or 0.0))
    except Exception:
        return (0.0, 0.0)


def find_candidate(asset: dict[str, Any], chosen: dict[str, Any], offset: int) -> dict[str, Any] | None:
    domain = str(chosen.get("domain") or "index")
    domain_start = int(chosen.get("domain_start") or 0)
    encoding = str(chosen.get("encoding") or "")
    for candidate in asset.get("top_candidates") or []:
        if (
            str(candidate.get("domain") or "") == domain
            and int(candidate.get("domain_start") or 0) == domain_start
            and str(candidate.get("encoding") or "") == encoding
            and int(candidate.get("offset") or -1) == offset
        ):
            return candidate
    return None


def annotate_choice(asset: dict[str, Any]) -> str:
    chosen = asset.get("chosen") or {}
    elem = int(asset.get("static_vertex_element_size") or 0)
    encoding = str(chosen.get("encoding") or "")
    offset = int(chosen.get("offset") or -1)

    if elem in {20, 24} and encoding == "half" and offset == 4:
        half4 = find_candidate(asset, chosen, 4)
        half8 = find_candidate(asset, chosen, 8)
        span4 = candidate_span(half4)
        span8 = candidate_span(half8)
        tiled4 = max(span4) > 1.25 and max(span4) < 256.0
        atlas8 = max(span8) <= 1.25 if half8 else False
        if tiled4 and atlas8:
            policy = "repo_variant_stripped_normal_tiled_diffuse_uv0_half_at_4"
        else:
            policy = "source_scored_half_at_4_retained_repo_stripped_normal_variant_possible"
        chosen["policy"] = policy
        asset["chosen"] = chosen
        asset["repo_variant_annotation"] = {
            "policy": policy,
            "evidence": [
                "UEViewer UnMesh3.cpp FStaticMeshUVItem3 has a GStripStaticNormals path that jumps to UV serialization.",
                "UEViewer UnMesh3.cpp serializes UVs after optional normals/color; stripped-normal variants can make low offsets legal UV data.",
                "Candidate comparison: half@4 behaves as the tiled render stream for several Gridlock road/building meshes; half@8 behaves like a 0-1 atlas channel.",
            ],
            "candidate_half4": half4,
            "candidate_half8": half8,
        }
        return policy

    if elem in {16, 20, 24} and encoding == "half" and offset == 8:
        policy = "repo_normal_or_atlas_half_uv_stream_at_8"
        chosen["policy"] = policy
        asset["chosen"] = chosen
        asset["repo_variant_annotation"] = {
            "policy": policy,
            "evidence": [
                "CUE4Parse FStaticMeshUVItem.cs serializes tangents before texcoords for normal-bearing records.",
                "UEViewer UnMesh3.cpp reads packed static normals before UVs when normals are present.",
            ],
        }
        return policy

    if elem == 28 and encoding == "float":
        policy = "source_scored_full_precision_uv_stream_retained"
        chosen["policy"] = policy
        asset["chosen"] = chosen
        asset["repo_variant_annotation"] = {
            "policy": policy,
            "evidence": [
                "UEViewer UnMesh3.cpp supports full-precision StaticMesh UV serialization.",
                "Gridlock candidate scores select finite full-float streams for 28-byte records.",
            ],
        }
        return policy

    return str(chosen.get("policy") or "source_scored_choice_retained")


def main() -> int:
    args = parse_args()
    source = Path(args.in_proof)
    data = json.loads(source.read_text(encoding="utf-8"))
    policy_counts: Counter[str] = Counter()
    offset_counts: Counter[str] = Counter()

    for asset in (data.get("assets") or {}).values():
        policy_counts[annotate_choice(asset)] += 1
        chosen = asset.get("chosen") or {}
        offset_counts[f"{chosen.get('encoding')}@{chosen.get('offset')}"] += 1

    data["repo_variant_staticmesh_uv_policy"] = {
        "source_proof": str(source),
        "policy": "Preserve source-scored Gridlock render UV choices, with repo-backed variants for normal-bearing and stripped-normal UE3 StaticMesh streams.",
        "why_previous_global_override_was_wrong": "Forcing all 20-byte half@4 streams to half@8 maps tiled environment diffuse textures onto atlas/lightmap-like UVs.",
        "repo_evidence": [
            "UEViewer UnrealMesh/UnMesh3.cpp FStaticMeshUVItem3: optional GStripStaticNormals path jumps to UV serialization.",
            "UEViewer UnrealMesh/UnMesh3.cpp FStaticMeshUVItem3: normal-bearing records serialize packed normals before UVs.",
            "CUE4Parse FStaticMeshUVItem.cs: normal-bearing StaticMesh UV items serialize tangents before texcoords.",
        ],
        "policy_counts": dict(sorted(policy_counts.items())),
        "chosen_offsets": dict(sorted(offset_counts.items())),
    }
    out = Path(args.out_proof)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(data["repo_variant_staticmesh_uv_policy"], indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
