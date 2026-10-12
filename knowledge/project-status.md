# Project Status

## Proven

- Steam app/build identity and executable version.
- Native content families: `.war`, `.upk`, `.tfc`, and `.bik`.
- Unreal package tag `0x9E2A83C1`, file version `835`, and licensee version `76` on sampled map packages.
- Package-family and Kismet boundary evidence for Timgad, Old Ephyra, Viaducts, and following-map handoffs.
- Historical decode of large StaticMesh placement sets and selected visible BSP shells into Blender.
- StaticMesh position/index payload extraction, section records, UV metadata, material references, Texture2D payload caching, and render validation on prior Timgad passes.
- Gridlock disproved the old fixed StaticMesh UV-offset assumption. The promoted guard derives UV offsets from stream metadata.

## Partially proven

- StaticMesh actor/component transforms were sufficient for dense prior scenes, but the current repository lacks a clean end-to-end parser fixture proving every attachment and coordinate-conversion case.
- Texture roles and material bindings worked for many static meshes, but material-instance inheritance and special shaders remain incomplete.
- Native BSP faces were decoded and filtered into visible shells, but BSP surface/material binding is still pending.
- Timgad package-family grouping is proven; exact live streaming order and pure per-chapter cuts remain approximate.
- Sky, water, decals, cards, lighting, and post-process passes have substantial Gridlock research but have not been promoted into a deterministic pipeline.

## Hard blockers

1. Recover or replace the missing shared heavy package parser.
2. Add package decompression and table/property decoding fixtures.
3. Re-prove world-transform composition from a clean checkout.
4. Close unresolved cross-package StaticMesh references.
5. Bind native BSP surfaces to materials and UVs.
6. Promote material-instance and texture-cache decoding.
7. Add skeletal, animated, dynamic, destructible, and runtime-selected actors.
8. Reconstruct authored lighting and exact streaming state.

## Honesty rule

Historical scenes demonstrate capability and preserve valuable counts. They are not considered currently reproducible until the native heavy parser exists in maintained source and the same results can be regenerated from an owned clean install.
