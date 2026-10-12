# Gears of War Reloaded - Timgad COMEDY OF ERRORS Export

Export date: 2026-08-11

Scope: source-native Blender export for Reloaded chapter 2 of the Timgad insert, player-facing `COMEDY OF ERRORS`.

## Output

- Blend: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_02_COMEDY_OF_ERRORS\SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_native_textured.blend`
- Proof render: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_02_COMEDY_OF_ERRORS\SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_native_textured_proof.png`
- Build proof: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_02_COMEDY_OF_ERRORS\SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_build_proof.json`
- Postprocess proof: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_02_COMEDY_OF_ERRORS\SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_postprocess_proof.json`
- Render validation proof: `D:\Game Extraction Database\Gears of War Franchise 2027\01_SOURCE_EXPORTS\GOW_Reloaded_PC\Campaign\Act_5_Timgad_New_Content\Chapter_02_COMEDY_OF_ERRORS\SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_validate_render_proof.json`
- Scene manifest: `D:\Game Extraction Database\Gears of War Franchise 2027\03_REPORTS_AND_PROOFS\GOW_Reloaded_PC\SP_Timgad_A_Chapter_02_COMEDY_Export_2026_08_11\Prepared_Textured\gowreloaded_sp_timgad_a_chapter_02_comedy_native_textured_scene_manifest.json`

## Source-Native Chapter Identity

- Localized provider: `[Timgad-Chap2 UIDataProvider_WarfareMaps]`
- FriendlyName: `COMEDY OF ERRORS`
- Kismet chapter enum: `eCHAPTER_Timgad_Comedy`
- Boundary evidence: `SP_Timgad_P.war` export `10725` completes `eCHAPTER_Timgad_Impasse`; exports `10754` and `10755` display `eCHAPTER_Timgad_Comedy`; export `10769` prepares map change to `sp_timgad_b_p`.
- Package scope: staged `SP_Timgad` A-side chapter-2 subset only. `SP_Timgad_B`, `SP_Station`, Tyro/train maps, and non-Timgad maps are excluded.

## Staged Packages

The staged map directory is `D:\Game Extraction Database\Gears of War Franchise 2027\04_TEMP_WORKING\GOW_Reloaded_PC\SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_MapDir_2026_08_11`.

It contains 29 hardlinked source packages:

`SP_Timgad_P`, `SP_Timgad_World`, `SP_Timgad_Lighting`, `SP_Timgad_Audio`, `SP_Timgad_BD1`, `SP_Timgad_BD1Lighting`, `SP_Timgad_Cine3`, `SP_Timgad_Cine4`, `SP_Timgad_Cine5`, `SP_Timgad_S04`, `SP_Timgad_S04Lighting`, `SP_Timgad_S05`, `SP_Timgad_S05Lighting`, `SP_Timgad_S05b`, `SP_Timgad_S05bLighting`, `SP_Timgad_S06`, `SP_Timgad_S06Lighting`, `SP_Timgad_S06b`, `SP_Timgad_S06bLighting`, `SP_Timgad_S07`, `SP_Timgad_S07Lighting`, `SP_Timgad_S07b`, `SP_Timgad_Scripting_2`, `SP_Timgad_Scripting_3`, `SP_Timgad_Scripting_4`, `SP_Timgad_Scripting_5`, `SP_Timgad_Zone2_VFX`, `SP_Timgad_Zone3_VFX`, `SP_Timgad_Zone4_VFX`.

`SP_Timgad_S04` is included as the handoff seam because decoded Kismet events explicitly disable `S04` while entering the later A-side flow, and the first checkpoint pair points at `SP_Timgad_S04`.

## Decode / Export Counts

- Full package parses resolved: `29 / 29`
- StaticMesh assets decoded: `2395 / 2395`
- StaticMesh unique placed paths prepared: `1458 / 1464`
- StaticMesh placements written to manifest: `17637`
- StaticMesh placements created in Blender: `17580`
- Missing placement refs: `57`
- BSP Model exports decoded with faces: `837`
- Visible BSP shell models imported: `5`
- Mesh objects in final blend: `17585`
- Mesh datablocks: `1463`
- Vertices in mesh objects: `6065905`
- Polygons in mesh objects: `2666740`
- Materials: `674`
- Images loaded: `667`
- DDS textures exported: `2086`
- Material texture bindings: `875`
- Textured material count: `275`
- UV decoded mesh datablocks: `1430`
- Sectioned StaticMesh datablocks: `1430`
- Scene root direct objects: `0`
- Top-level scene collection: `SP_Timgad_A_Chapter_02_COMEDY_OF_ERRORS_Reloaded_Native_Textured`

## Known Gaps

Six unique StaticMesh refs remain unresolved:

- `EditorMeshes.TexPropPlane`
- `Geist_Grunt.locust_grunt_helmet_soc_all`
- `Geist_Grunt.locust_grunt_helmet_soc_mask`
- `Geist_Grunt.locust_grunt_helmet_soc_mouth`
- `Geist_Grunt.locust_grunt_helmet_soc_none`
- `Geist_Grunt.Mesh.Locust_Grunt_Goggles_Down_Mesh`

These account for `57` skipped placement refs. The Blender builder returned nonzero because it treats missing refs as an error, but it saved the file and render validation passed.

BSP material binding is still pending. Imported BSP geometry uses decoded native Model faces, but not final source material slots.

Runtime streaming order is approximated from decoded Kismet markers. This is a chapter-2-focused staged export, not a live engine streaming simulation.

## Validation

Render proof passed:

- Image size: `1280 x 720`
- Render file size: `649606`
- Pixel mean RGB: `[16.322, 16.323, 16.31]`
- Pixel extrema RGB: `[(1, 64), (1, 64), (1, 64)]`

The render is dark because the scene still uses the decode/work-light grade, but it is nonblank and opens as a real Blender scene.
