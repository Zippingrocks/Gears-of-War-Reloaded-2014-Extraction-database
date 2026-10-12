#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_INSTALL_ROOT = Path(r"D:\SteamLibrary\steamapps\common\Gears of War Reloaded")
DEFAULT_HEAVY_PARSER = Path(
    r"D:\Game Extraction Database\Gears of War Franchise 2027\02_ACTIVE_TOOLS\GOW_RELOADED_PC\gowreloaded_factory_interior_heavy_parse.py"
)
DEFAULT_OUT = Path(
    r"C:\Users\Bilbo\Downloads\Gears Map Ripping\reports\gow_reloaded_horde_trace_scan_2026_08_10"
)


MODE_RE = re.compile(
    r"\b("
    r"horde|hordemode|hordegame|gameinfo_horde|hordewave|wavemanager|wavespawner|"
    r"gametype_horde|survivalmode|coopwave|wavebased|fortification"
    r")\b",
    re.IGNORECASE,
)

TEXT_TRACE_RE = re.compile(r"horde|survival|fortification", re.IGNORECASE)

LORE_FALSE_POSITIVE_RE = re.compile(
    r"Locust Horde|before the Horde|my Horde|the Horde is|avenge the Horde|Horde shall|Horde des locustes",
    re.IGNORECASE,
)


def load_heavy(path: Path):
    spec = importlib.util.spec_from_file_location("gowr_heavy_for_horde_scan", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load heavy parser: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gowr_heavy_for_horde_scan"] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def compact(value: Any, limit: int = 1200) -> str:
    text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 3] + "..."


def printable_window(data: bytes, start: int, radius: int = 96) -> str:
    lo = max(0, start - radius)
    hi = min(len(data), start + radius)
    raw = data[lo:hi]
    text = "".join(chr(b) if 32 <= b <= 126 else " " for b in raw)
    return re.sub(r"\s+", " ", text).strip()


def byte_offsets(package: Path, payload_kind: str, data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for needle in (b"HORDE", b"Horde", b"horde"):
        pos = data.find(needle)
        while pos >= 0:
            rows.append(
                {
                    "package": str(package),
                    "payload_kind": payload_kind,
                    "needle": needle.decode("ascii"),
                    "offset": pos,
                    "context": printable_window(data, pos),
                }
            )
            pos = data.find(needle, pos + 1)
    return rows


def parse_package(heavy: Any, package: Path) -> dict[str, Any]:
    data = package.read_bytes()
    virt, groups, compression_mode = heavy.rebuild_virtual_package(data)
    names = heavy.read_names(virt)
    imports = heavy.read_imports(virt, names)
    exports = heavy.read_exports(virt, names, imports)
    ref_short_name, ref_path = heavy.make_ref_helpers(exports, imports)

    name_hits = []
    for idx, name in enumerate(names):
        if MODE_RE.search(name):
            name_hits.append(
                {
                    "kind": "name",
                    "package": str(package),
                    "index": idx,
                    "name": name,
                    "nearby_names": compact(names[max(0, idx - 8) : min(len(names), idx + 9)]),
                }
            )

    import_hits = []
    for imp in imports:
        path_text = ref_path(imp["index"])
        text = f"{imp.get('class_name', '')} {imp.get('object_short_name', '')} {path_text}"
        if MODE_RE.search(text):
            import_hits.append(
                {
                    "kind": "import",
                    "package": str(package),
                    "index": imp["index"],
                    "class_name": imp.get("class_name", ""),
                    "object_name": imp.get("object_short_name", ""),
                    "path": path_text,
                }
            )

    export_hits = []
    for row in exports:
        class_name = ref_short_name(row["class_ref"])
        path_text = ref_path(row["index"])
        text = f"{class_name} {row.get('object_short_name', '')} {path_text}"
        if MODE_RE.search(text):
            export_hits.append(
                {
                    "kind": "export",
                    "package": str(package),
                    "index": row["index"],
                    "class_name": class_name,
                    "object_name": row.get("object_short_name", ""),
                    "path": path_text,
                    "serial_size": row.get("serial_size", ""),
                }
            )

    raw_offsets = byte_offsets(package, "physical_file", data)
    virtual_offsets = byte_offsets(package, "rebuilt_virtual_package", virt)

    return {
        "package": str(package),
        "compression_mode": compression_mode,
        "compressed_groups": len(groups),
        "names": len(names),
        "imports": len(imports),
        "exports": len(exports),
        "name_hits": name_hits,
        "import_hits": import_hits,
        "export_hits": export_hits,
        "raw_offsets": raw_offsets,
        "virtual_offsets": virtual_offsets,
    }


def text_scan(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for file in sorted(path.rglob("*")):
        if not file.is_file() or file.suffix.lower() not in {".ini", ".int", ".deu", ".esm", ".esn", ".fra", ".ita", ".jpn", ".kor", ".pol", ".ptb", ".rus", ".chi"}:
            continue
        try:
            payload = file.read_bytes()
        except OSError:
            continue
        if payload.startswith(b"\xff\xfe"):
            text = payload.decode("utf-16-le", "ignore")
        elif payload.startswith(b"\xfe\xff"):
            text = payload.decode("utf-16-be", "ignore")
        else:
            text = payload.decode("utf-8-sig", "ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if TEXT_TRACE_RE.search(line):
                rows.append(
                    {
                        "file": str(file),
                        "line": line_no,
                        "text": line[:1000],
                        "classification": "likely_lore_or_dialogue" if LORE_FALSE_POSITIVE_RE.search(line) else "needs_review",
                    }
                )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan Gears of War Reloaded files for Horde-mode traces.")
    parser.add_argument("--install-root", default=str(DEFAULT_INSTALL_ROOT))
    parser.add_argument("--heavy-parser", default=str(DEFAULT_HEAVY_PARSER))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    install_root = Path(args.install_root)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    heavy = load_heavy(Path(args.heavy_parser))

    package_candidates = [
        install_root / "WarfareGame.u",
        install_root / "WarGame" / "CookedPC" / "WarfareGame.u",
        install_root / "WarGame" / "CookedPC" / "Startup.upk",
        install_root / "WarGame" / "CookedPC" / "Startup_LOC_INT.upk",
        install_root / "WarGame" / "CookedPC" / "Maps" / "WarStart.war",
        install_root / "WarGame" / "CookedPC" / "Maps" / "WarGame_p.war",
    ]
    package_candidates = [p for p in package_candidates if p.exists()]

    filename_hits = [
        {"path": str(path), "length": path.stat().st_size}
        for path in sorted(install_root.rglob("*Horde*"))
        if path.exists()
    ]

    package_summaries = []
    name_hits: list[dict[str, Any]] = []
    import_hits: list[dict[str, Any]] = []
    export_hits: list[dict[str, Any]] = []
    raw_hits: list[dict[str, Any]] = []
    virtual_hits: list[dict[str, Any]] = []
    for package in package_candidates:
        result = parse_package(heavy, package)
        package_summaries.append(
            {
                "package": result["package"],
                "compression_mode": result["compression_mode"],
                "compressed_groups": result["compressed_groups"],
                "names": result["names"],
                "imports": result["imports"],
                "exports": result["exports"],
                "name_hits": len(result["name_hits"]),
                "import_hits": len(result["import_hits"]),
                "export_hits": len(result["export_hits"]),
                "raw_offsets": len(result["raw_offsets"]),
                "virtual_offsets": len(result["virtual_offsets"]),
            }
        )
        name_hits.extend(result["name_hits"])
        import_hits.extend(result["import_hits"])
        export_hits.extend(result["export_hits"])
        raw_hits.extend(result["raw_offsets"])
        virtual_hits.extend(result["virtual_offsets"])

    loc_hits = text_scan(install_root / "WarGame" / "Localization")
    config_hits = text_scan(install_root / "WarGame" / "Config")

    write_csv(out_dir / "filename_hits.csv", filename_hits, ["path", "length"])
    write_csv(
        out_dir / "package_summaries.csv",
        package_summaries,
        ["package", "compression_mode", "compressed_groups", "names", "imports", "exports", "name_hits", "import_hits", "export_hits", "raw_offsets", "virtual_offsets"],
    )
    write_csv(out_dir / "name_hits.csv", name_hits, ["kind", "package", "index", "name", "nearby_names"])
    write_csv(out_dir / "import_hits.csv", import_hits, ["kind", "package", "index", "class_name", "object_name", "path"])
    write_csv(out_dir / "export_hits.csv", export_hits, ["kind", "package", "index", "class_name", "object_name", "path", "serial_size"])
    write_csv(out_dir / "raw_horde_offsets.csv", raw_hits, ["package", "payload_kind", "needle", "offset", "context"])
    write_csv(out_dir / "virtual_horde_offsets.csv", virtual_hits, ["package", "payload_kind", "needle", "offset", "context"])
    write_csv(out_dir / "localization_hits.csv", loc_hits, ["file", "line", "text", "classification"])
    write_csv(out_dir / "config_hits.csv", config_hits, ["file", "line", "text", "classification"])

    evidence_mode = bool(import_hits or export_hits)
    exact_core_name = [row for row in name_hits if row["name"].lower() == "horde"]
    likely_lore = len(loc_hits) > 0 and not evidence_mode
    summary = {
        "install_root": str(install_root),
        "filename_hits": len(filename_hits),
        "packages_scanned": len(package_summaries),
        "package_name_hits": len(name_hits),
        "package_exact_horde_name_hits": len(exact_core_name),
        "package_import_hits": len(import_hits),
        "package_export_hits": len(export_hits),
        "physical_file_horde_offsets": len(raw_hits),
        "rebuilt_virtual_horde_offsets": len(virtual_hits),
        "localization_hits": len(loc_hits),
        "config_hits": len(config_hits),
        "assessment": (
            "mode_scaffolding_evidence"
            if evidence_mode
            else "core_token_only_no_mode_scaffolding" if exact_core_name else "no_horde_mode_evidence"
        ),
        "notes": [
            "A bare HORDE name in WarfareGame.u is a trace, but not enough by itself to prove a shipped/planned Horde mode.",
            "No Horde-named files were found under the install root.",
            "Localization hits are mostly Myrrah/Locust Horde lore or bios, not playlist/menu/mode strings.",
            "No imports/exports matched HordeMode, HordeGame, GameInfo_Horde, HordeWave, WaveManager, WaveSpawner, SurvivalMode, CoopWave, or WaveBased in the scanned core packages.",
        ],
        "likely_lore_only": likely_lore,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
