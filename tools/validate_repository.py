#!/usr/bin/env python3
"""Dependency-free structural validation for the Reloaded repository."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "NOTICE.md",
    "LICENSE",
    "game.json",
    "docs/architecture.md",
    "docs/evidence-standard.md",
    "knowledge/project-status.md",
    "knowledge/failure-ledger.md",
    "knowledge/formats/ue3-packages.md",
    "knowledge/formats/staticmesh-uv.md",
    "knowledge/maps/package-families.md",
    "knowledge/maps/chapter-boundaries.md",
    "inventory/legacy-migration.json",
    "platforms/pc-steam-build-20087529/README.md",
    "schemas/evidence.schema.json",
    "schemas/game.schema.json",
    "src/reloaded_package.py",
    "src/gowreloaded_static_uvstream_regression_guard.py",
)
FORBIDDEN_SUFFIXES = {
    ".blend", ".blend1", ".fbx", ".glb", ".gltf", ".obj", ".mtl",
    ".psk", ".pskx", ".war", ".upk", ".tfc", ".bik", ".udk",
    ".u", ".dds", ".tga", ".hdr", ".png", ".jpg", ".jpeg",
    ".wav", ".mp4", ".wmv", ".dll", ".exe", ".pdb", ".pyc", ".zip",
}
CLAIM_STATES = {"hypothesis", "observed", "decoded", "validated", "rejected", "unknown"}
CONFIDENCE = {"low", "medium", "high"}
CLAIM_ID = re.compile(r"^[a-z0-9][a-z0-9-]+$")
WINDOWS_ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:\\")
SCOPE_KEYS = {"game", "platform", "build", "root", "maps", "packages", "objects"}


def load_json(path: Path, errors: list[str]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {exc}")
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_files(errors: list[str]) -> list[Path]:
    command = [
        "git",
        "-c",
        f"safe.directory={ROOT.as_posix()}",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"could not enumerate committable repository files: {exc}")
        return []
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def validate_claim(path: Path, errors: list[str]) -> None:
    value = load_json(path, errors)
    if not isinstance(value, dict):
        return
    required = {"id", "revision", "state", "confidence", "scope", "claim", "evidence", "limitations"}
    missing = required - value.keys()
    if missing:
        errors.append(f"{path.relative_to(ROOT)}: missing {sorted(missing)}")
        return
    if path.stem != value.get("id"):
        errors.append(f"{path.relative_to(ROOT)}: file name must match claim id")
    if not isinstance(value["id"], str) or not CLAIM_ID.fullmatch(value["id"]):
        errors.append(f"{path.relative_to(ROOT)}: invalid claim id")
    if value["state"] not in CLAIM_STATES:
        errors.append(f"{path.relative_to(ROOT)}: invalid state {value['state']!r}")
    if value["confidence"] not in CONFIDENCE:
        errors.append(f"{path.relative_to(ROOT)}: invalid confidence {value['confidence']!r}")
    scope = value.get("scope")
    if not isinstance(scope, dict):
        errors.append(f"{path.relative_to(ROOT)}: scope must be an object")
    else:
        if scope.get("game") != "gears-of-war-reloaded":
            errors.append(f"{path.relative_to(ROOT)}: invalid game scope")
        if scope.get("platform") != "pc-steam-build-20087529":
            errors.append(f"{path.relative_to(ROOT)}: invalid platform scope")
        extra = set(scope) - SCOPE_KEYS
        if extra:
            errors.append(f"{path.relative_to(ROOT)}: unknown scope keys {sorted(extra)}")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"{path.relative_to(ROOT)}: at least one evidence reference is required")
        return
    for entry in evidence:
        if not isinstance(entry, dict) or not isinstance(entry.get("ref"), str):
            errors.append(f"{path.relative_to(ROOT)}: invalid evidence reference")
            continue
        ref = entry["ref"]
        if "://" not in ref and not (ROOT / ref).is_file():
            errors.append(f"{path.relative_to(ROOT)}: missing evidence target {ref}")


def validate_migration_manifest(errors: list[str]) -> None:
    path = ROOT / "inventory" / "legacy-migration.json"
    value = load_json(path, errors)
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        errors.append("inventory/legacy-migration.json: missing items array")
        return
    destinations: set[str] = set()
    for index, item in enumerate(value["items"]):
        if not isinstance(item, dict):
            errors.append(f"inventory/legacy-migration.json: item {index} is not an object")
            continue
        destination = item.get("destination")
        if not isinstance(destination, str) or Path(destination).is_absolute() or ".." in Path(destination).parts:
            errors.append(f"inventory/legacy-migration.json: item {index} has invalid destination")
            continue
        if destination in destinations:
            errors.append(f"inventory/legacy-migration.json: duplicate destination {destination}")
        destinations.add(destination)
        target = ROOT / destination
        if not target.is_file():
            errors.append(f"inventory/legacy-migration.json: missing destination {destination}")
            continue
        if target.stat().st_size != item.get("destinationBytes"):
            errors.append(f"inventory/legacy-migration.json: byte mismatch for {destination}")
        if sha256_file(target) != item.get("destinationSha256"):
            errors.append(f"inventory/legacy-migration.json: hash mismatch for {destination}")


def validate_curated_paths(files: list[Path], errors: list[str]) -> None:
    curated_roots = {"docs", "knowledge", "platforms", "src", "tests", "tools"}
    curated_files = {"README.md", "AGENTS.md", "CONTRIBUTING.md", "NOTICE.md"}
    for path in files:
        relative = path.relative_to(ROOT)
        if relative.as_posix() not in curated_files and relative.parts[0] not in curated_roots:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError as exc:
            errors.append(f"{relative}: expected UTF-8 text: {exc}")
            continue
        if WINDOWS_ABSOLUTE_PATH.search(text):
            errors.append(f"{relative}: contains a machine-specific absolute path")


def validate_game_metadata(errors: list[str]) -> None:
    value = load_json(ROOT / "game.json", errors)
    if not isinstance(value, dict):
        return
    if value.get("id") != "gears-of-war-reloaded" or value.get("releaseYear") != 2025:
        errors.append("game.json: incorrect Reloaded identity")
    platforms = value.get("platforms")
    if not isinstance(platforms, list) or not platforms or platforms[0].get("steamAppId") != 2523720:
        errors.append("game.json: Steam app 2523720 is required")


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")

    files = repository_files(errors)
    for path in sorted(candidate for candidate in files if candidate.suffix.lower() == ".json"):
        if path.is_file():
            load_json(path, errors)
    for path in files:
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden asset payload: {path.relative_to(ROOT)}")

    for path in sorted((ROOT / "evidence" / "claims").glob("*.json")):
        validate_claim(path, errors)
    validate_migration_manifest(errors)
    validate_curated_paths(files, errors)
    validate_game_metadata(errors)

    if errors:
        print("Repository validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
