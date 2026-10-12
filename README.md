# Gears of War: Reloaded (2025) Extraction Database

An evidence-driven extraction and Blender reconstruction foundation for Gears of War: Reloaded maps and assets from native PC data.

Native cooked packages, object metadata, actor/component properties, material references, and runtime map transitions are the source of truth. A convincing Blender scene is useful validation, but it does not prove package closure, correct streaming scope, complete placement, or material parity.

## Verified source scope

| Platform | Build evidence | Native content root | Working reconstruction path |
| --- | --- | --- | --- |
| Windows PC Steam | App `2523720`, build `20087529`, executable `1.0.381.6947` | `WarGame` (`CookedPC` packages) | `.war` / `.upk` decode -> audited caches -> Blender |

The [Steam product page](https://store.steampowered.com/app/2523720/Gears_of_War_Reloaded/) records an August 26, 2025 release date. This repository records evidence for the installed build above; other builds require separate source identity and regression evidence.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/` | Maintained package inspection, UV validation, and decoded-cache packaging tools |
| `knowledge/` | Curated format, map-family, transform, material, Blender, and failure state |
| `evidence/claims/` | Machine-readable durable conclusions |
| `evidence/legacy-snapshots/` | Compact historical reports retained for provenance |
| `research/legacy-probes/` | Historical map-specific experiments that have not met promotion criteria |
| `platforms/` | Build-specific source and serialization contract |
| `inventory/` | Native metadata and migration provenance |
| `schemas/` | Evidence and repository metadata contracts |
| `tests/` | Repository and format regression tests |

Game packages, decoded packages, extracted meshes, textures, `.blend`, FBX, OBJ, audio, video, and generated scenes remain external.

## Current state

- The recorded `WarGame` tree contains 1,859 `.war`, 566 `.upk`, 68 `.tfc`, and 113 `.bik` files totaling 74,256,775,264 bytes. Cooked packages and texture caches are under `WarGame/CookedPC`; movies are outside that package root.
- Reloaded package files use the Unreal package tag `0x9E2A83C1`; sampled map packages report file version `835` and licensee version `76`.
- Historical Timgad exports decoded thousands of StaticMesh assets, tens of thousands of placements, native BSP faces, UVs, material references, and texture payloads into real Blender scenes.
- The corrected StaticMesh UV path derives payload and channel offsets from UE3 stream metadata. Fixed offsets are rejected because they produced smeared and triangular textures on Gridlock.
- Timgad chapter boundaries are supported by Kismet chapter enums, streaming markers, package families, and localized player-facing names.
- BSP material binding, unresolved cross-package mesh references, skeletal/dynamic layers, exact runtime streaming, and authored lighting parity remain incomplete.
- The historical shared heavy parser referenced by many probes is not present in the surviving workspace. Until it is recovered or replaced, full map exports are evidence-backed historical results, not a clean reproducible command from this repository.

See [Project Status](knowledge/project-status.md), [Known Failures](knowledge/failure-ledger.md), [Architecture](docs/architecture.md), and [Evidence Standard](docs/evidence-standard.md).

## Quick start

Inspect one owned package:

```powershell
python src\reloaded_package.py "<owned install>\WarGame\CookedPC\Maps\MP_Maps\MP_Gridlock.war"
```

Rebuild the metadata-only native inventory:

```powershell
python tools\inventory_native.py "<owned install>\WarGame" `
  --output evidence\native-inventory\pc-steam-build-20087529\native-inventory.json `
  --source-label "Steam app 2523720 build 20087529" `
  --anchor "CookedPC/Maps/MP_Maps/MP_Gridlock.war" `
  --anchor "CookedPC/Maps/SP_Timgad/SP_Timgad_P.war"
```

The promoted UV regression guard operates on decoded external cache data; see [StaticMesh UV Layout](knowledge/formats/staticmesh-uv.md). Generated assets must stay outside this repository.

## Legal boundary

This repository does not distribute proprietary game data. Users must provide legally obtained files locally. See [Asset Policy](docs/asset-policy.md) and [Notice](NOTICE.md).
