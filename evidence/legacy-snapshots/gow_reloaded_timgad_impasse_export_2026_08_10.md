# Gears of War Reloaded - Timgad IMPASSE Pilot Export

Export date: 2026-08-10

Scope: source-native Blender export pilot for the PC/Reloaded-only Timgad insert, starting with player-facing chapter `IMPASSE`.

## Output

- Blend: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_01_IMPASSE\SP_Timgad_A_Chapter_01_IMPASSE_native_textured.blend`
- Proof render: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_01_IMPASSE\SP_Timgad_A_Chapter_01_IMPASSE_native_textured_proof.png`
- Scene manifest: `D:\Game Extraction Database\Gears of War Franchise 2027\03_REPORTS_AND_PROOFS\GOW_Reloaded_PC\SP_Timgad_A_Impasse_Pilot_Export_2026_08_10\Prepared_Textured\gowreloaded_sp_timgad_a_impasse_native_textured_scene_manifest.json`

## Source-Native Chapter Identity

- Localized provider: `[Timgad-Chap1 UIDataProvider_WarfareMaps]`
- FriendlyName: `IMPASSE`
- Kismet start enum: `eCHAPTER_Timgad_Impasse`
- Package scope: `SP_Timgad` A-side package family only.
- Excluded intentionally: `SP_Timgad_B`, `SP_Station`, Tyro/train packages.

## Decode / Export Counts

- StaticMesh assets decoded: `3873 / 3873`
- StaticMesh unique placed paths prepared: `2014 / 2021`
- StaticMesh placements created in Blender: `26754`
- BSP persistent shell models imported: `9`
- Mesh objects in final blend: `26763`
- Mesh datablocks: `2023`
- Materials: `811`
- Images loaded: `1199`
- DDS textures exported: `2409`
- Root direct scene objects: `0`
- Top-level scene collection: `SP_Timgad_A_Chapter_01_IMPASSE_Reloaded_Native_Textured`

## Known Gaps

Seven unique StaticMesh refs remain unresolved in this first pilot pass:

- `EditorMeshes.TexPropPlane`
- `Ephyra_02.EmbrySquare_Gearsofwarprop_SMesh`
- `Geist_Grunt.locust_grunt_helmet_soc_all`
- `Geist_Grunt.locust_grunt_helmet_soc_mask`
- `Geist_Grunt.locust_grunt_helmet_soc_mouth`
- `Geist_Grunt.locust_grunt_helmet_soc_none`
- `Geist_Grunt.Mesh.Locust_Grunt_Goggles_Down_Mesh`

These account for `68` skipped placement refs in the blend build. A quick cooked-root package-name search did not find obvious `Ephyra_02`, `EditorMeshes`, or `Geist_Grunt` package files, so they need a deeper cross-package dependency search later.

BSP material binding is still pending. The imported BSP shell uses decoded native Model faces, but not source material assignments yet.

Chapter splitting inside `SP_Timgad` A still needs tighter Kismet streaming analysis before the export can be called a pure one-chapter-only cut. This pilot intentionally captures the A-side Timgad family anchored to IMPASSE without crossing into `SP_Timgad_B` / `JURASSIC PROPORTIONS`.
