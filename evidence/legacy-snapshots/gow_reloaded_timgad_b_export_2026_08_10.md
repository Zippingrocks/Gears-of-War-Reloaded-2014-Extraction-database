# Gears of War Reloaded - Timgad B Native Textured Export

Export date: 2026-08-10

Scope: source-native Blender export for the Reloaded-only `SP_Timgad_B` package family, covering the later Timgad chapter block: `WINDOW SHOPPING`, `POWERS THAT BE`, and `JURASSIC PROPORTIONS`.

## Output

- Blend: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapters_03_to_05_Timgad_B\SP_Timgad_B_Chapters_03_to_05_native_textured.blend`
- Proof render: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapters_03_to_05_Timgad_B\SP_Timgad_B_Chapters_03_to_05_native_textured_proof.png`
- Build proof: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapters_03_to_05_Timgad_B\SP_Timgad_B_Chapters_03_to_05_build_proof.json`
- Postprocess proof: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapters_03_to_05_Timgad_B\SP_Timgad_B_Chapters_03_to_05_postprocess_proof.json`
- Render validation proof: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapters_03_to_05_Timgad_B\SP_Timgad_B_Chapters_03_to_05_validate_render_proof.json`
- Scene manifest: `D:\Game Extraction Database\Gears of War Franchise 2027\03_REPORTS_AND_PROOFS\GOW_Reloaded_PC\SP_Timgad_B_New_Content_Export_2026_08_10\Prepared_Textured\gowreloaded_sp_timgad_b_chapters_03_to_05_native_textured_scene_manifest.json`

## Decode / Export Counts

- Full package parses resolved: `43 / 43`
- StaticMesh assets decoded: `2905 / 2905`
- StaticMesh unique placed paths prepared: `1299 / 1303`
- StaticMesh placements written to manifest: `19351`
- StaticMesh placements created in Blender: `19322`
- Missing placement refs: `29`
- BSP Model exports decoded with faces: `785`
- Visible BSP shell models imported: `13`
- Mesh objects in final blend: `19335`
- Mesh datablocks: `1312`
- Vertices in mesh objects: `8784650`
- Polygons in mesh objects: `3691606`
- Materials: `598`
- Images loaded: `980`
- DDS textures exported: `1772`
- Material texture bindings: `785`
- Textured material count: `383`
- Scene root direct objects: `0`
- Top-level scene collection: `SP_Timgad_B_Chapters_03_to_05_Reloaded_Native_Textured`

## Known Gaps

Four unique StaticMesh refs remain unresolved in this pass:

- `EditorMeshes.TexPropPlane`
- `Ephyra_02.EmbrySquare_Gearsofwarprop_SMesh`
- `Geist_Grunt.locust_grunt_helmet_soc_all`
- `Geist_Grunt.locust_grunt_helmet_soc_mask`

These account for `29` skipped placement refs in the blend build. The blend still saved and render-validated.

BSP material binding is still pending. BSP geometry is decoded from native Model faces, but not yet assigned source material textures.

This is a package-family export, not a final pure per-chapter split.

## Validation

Render proof passed:

- Image size: `1280 x 720`
- Render file size: `802573`
- Pixel mean RGB: `[37.118, 41.996, 33.875]`
- Pixel extrema RGB: `[(7, 64), (7, 64), (6, 64)]`

The render is dark because the scene is still using decode/work-light grade lighting, but it is nonblank and opens as a real Blender scene.
