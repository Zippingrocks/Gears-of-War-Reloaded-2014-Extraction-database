# Architecture

The repository separates four confidence layers.

1. **Native inventory** records build identity, package paths, sizes, tags, and version fields without extracting assets.
2. **Decode evidence** records package tables, object properties, Kismet boundaries, StaticMesh/BSP payloads, and material references.
3. **Reconstruction** converts decoded caches into portable mesh/material structures and Blender scenes outside Git.
4. **Validation** compares counts, unresolved references, transforms, UV routing, renders, and exclusions against source evidence.

`src/reloaded_package.py` and `tools/inventory_native.py` form the current maintained native layer. `src/gowreloaded_static_uvstream_regression_guard.py` is the maintained UV gate. `src/gowreloaded_map_textured_staticmesh_asset_pack.py` packages already-decoded caches; it is not a native package parser.

The historical heavy parser is not currently available. Scripts under `research/legacy-probes/` may describe or wrap that parser, but they are not part of the maintained execution path.
