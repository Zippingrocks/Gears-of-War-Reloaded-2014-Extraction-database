#!/usr/bin/env python3
"""Summarize Gridlock UV proof choices against repo-derived layout expectations."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SUSPECT_TARGETS = {
    "SDStitchingProxy_2661_StaticMesh__27170",
    "SDStitchingProxy_2377_StaticMesh__26992",
    "SDStitchingProxy_2378_StaticMesh__27002",
    "SDStitchingProxy_2381_StaticMesh__27004",
    "SDStitchingProxy_2409_StaticMesh__27021",
    "SDStitchingProxy_2755_StaticMesh__27221",
    "bsp_gridlock_road_b_SMesh__26847",
    "bsp_gridlock_bld_01_SMesh_Delta__28042",
    "MS_Neutral_Sedan_SMesh__27672",
    "COG_UndentedCar1_Frame_SMesh_DR__27322",
    "COG_City_BrokenCarChasey1_Smesh_DR__27323",
    "COG_City_Ephyra_Facade03_SideTile_MS_SMesh__27333",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", required=True)
    parser.add_argument("--audit")
    parser.add_argument("--out")
    return parser.parse_args()


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def short_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": candidate.get("name"),
        "domain": candidate.get("domain"),
        "domain_start": candidate.get("domain_start"),
        "encoding": candidate.get("encoding"),
        "offset": candidate.get("offset"),
        "score": candidate.get("score"),
        "finite_ratio": candidate.get("finite_ratio"),
        "unique_ratio": candidate.get("unique_ratio"),
        "span_u": candidate.get("span_u"),
        "span_v": candidate.get("span_v"),
        "outside_0_1_ratio": candidate.get("outside_0_1_ratio"),
    }


def is_repo_suspicious(asset: dict[str, Any]) -> bool:
    chosen = asset.get("chosen") or {}
    elem = int(asset.get("static_vertex_element_size") or 0)
    encoding = str(chosen.get("encoding") or "")
    offset = int(chosen.get("offset") or -1)
    if elem == 20 and encoding == "half" and offset < 8:
        return True
    if elem == 24 and encoding == "half" and offset < 8:
        return True
    if elem == 28 and encoding == "float" and offset < 8:
        return True
    return False


def main() -> int:
    args = parse_args()
    proof = load_json(args.proof)
    assets: dict[str, dict[str, Any]] = proof.get("assets") or {}
    by_choice: Counter[str] = Counter()
    by_elem_choice: Counter[str] = Counter()
    suspicious: list[dict[str, Any]] = []
    target_assets: dict[str, dict[str, Any]] = {}

    audit_name_to_path: dict[str, str] = {}
    if args.audit:
        audit = load_json(args.audit)
        for target in audit.get("targets") or []:
            for match in target.get("matches") or []:
                path = str(match.get("static_mesh_path") or match.get("ue_full_path") or "").lower()
                if path:
                    audit_name_to_path[str(match.get("object") or target.get("target"))] = path

    reverse_object_lookup: defaultdict[str, list[str]] = defaultdict(list)
    for object_name, path in audit_name_to_path.items():
        reverse_object_lookup[path].append(object_name)

    for key, asset in assets.items():
        chosen = asset.get("chosen") or {}
        elem = int(asset.get("static_vertex_element_size") or 0)
        choice_key = f"{chosen.get('encoding')}@{chosen.get('offset')}"
        by_choice[choice_key] += 1
        by_elem_choice[f"elem{elem}:{choice_key}"] += 1
        row = {
            "asset_key": key,
            "object_name": asset.get("object_name", ""),
            "known_objects": reverse_object_lookup.get(key, []),
            "static_vertex_element_size": elem,
            "vertex_count": asset.get("vertex_count"),
            "index_count": asset.get("index_count"),
            "doubled_static_stream": asset.get("doubled_static_stream"),
            "chosen": short_candidate(chosen),
            "top_candidates": [short_candidate(c) for c in (asset.get("top_candidates") or [])[:12]],
        }
        if is_repo_suspicious(asset):
            suspicious.append(row)
        names = {str(asset.get("object_name") or ""), *reverse_object_lookup.get(key, [])}
        if names & SUSPECT_TARGETS:
            target_assets[key] = row

    summary = {
        "proof": str(Path(args.proof)),
        "asset_count": len(assets),
        "chosen_offsets": dict(by_choice),
        "element_choice_counts": dict(by_elem_choice),
        "repo_suspicious_count": len(suspicious),
        "repo_suspicious": suspicious,
        "target_assets": target_assets,
    }
    text = json.dumps(summary, indent=2, ensure_ascii=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
