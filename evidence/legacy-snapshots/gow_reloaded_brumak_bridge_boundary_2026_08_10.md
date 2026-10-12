# Gears of War Reloaded - Brumak / Bridge Chapter Boundary Decode

Decode date: 2026-08-10

Scope: decode-only. No map or Blender export was produced for this pass.

## Source-Native Result

The bridge/Brumak-adjacent run is not one monolithic source chapter. The decoded package/Kismet markers split it into:

1. `SP_OldEphyra_S06GasStation*` / `eCHAPTER_Kryll_Powderkeg`
   - Brumak and gas-station fight/finale.
   - Starts from `SP_OldEphyra_S06GasStation_S.war`.
   - Completes in `SP_OldEphyra_S06GasStation_Cin.war`.

2. `SP_Viaducts*` / `eCHAPTER_Viaducts_BurntRubber`
   - Following bridge/viaduct driving chapter.
   - Starts from `SP_Viaducts_P.war` plus `SP_Viaducts_Scripting_01.war`.
   - Completes in `SP_Viaducts_P.war`, then prepares `sp_alamo_p`.
Follow-up correction: the player-facing final Brumak kill chapter is not the OldEphyra gas-station segment. The localized in-game chapter is `Timgad-Chap5`, `FriendlyName=JURASSIC PROPORTIONS`, and the decoded source-native marker for that chapter is `eCHAPTER_Timgad_Jurassic`.

## Player-Facing Name Bridge

The database should preserve three identities for each story section:

1. Source package family, for example `SP_Timgad_b_P.war` / `SP_Timgad_Cine7.war`.
2. Runtime/Kismet enum, for example `eCHAPTER_Timgad_Jurassic`.
3. Localized UI provider and display text from `WarGame\Localization\INT\warfaregame.int`.

Confirmed mappings:

- `SP_OldEphyra_S06GasStation*` / `eCHAPTER_Kryll_Powderkeg` -> `[OldEphyra-Chap4 UIDataProvider_WarfareMaps]` -> `POWDER KEG`
  - Description key: `OldEphyra4_Desc=Shootout at Chaps Gas Station.`
- `SP_Viaducts*` / `eCHAPTER_Viaducts_BurntRubber` -> `[Viaducts-Chap1 UIDataProvider_WarfareMaps]` -> `BURNT RUBBER`
  - Description key: `Viaducts1_Desc=Burn Kryll... while burning rubber.`
- `SP_Timgad_B*` / `eCHAPTER_Timgad_Jurassic` -> `[Timgad-Chap5 UIDataProvider_WarfareMaps]` -> `JURASSIC PROPORTIONS`
  - Description key: `Timgad5_Desc=It's time to play fetch.`
  - Brumak objective text: `TIMGAD_OBJ_10_5=Destroy the Brumak's arm guns.`, `TIMGAD_OBJ_10_6=Kill the Brumak's driver.`, `TIMGAD_OBJ_11=Lure the Brumak into the transformers.`

Timgad decode evidence:

- `SP_Timgad_b_P.war`, exports `10915` and `10916`, `SeqAct_DisplayChapterTitle`: `DisplayChapter = eCHAPTER_Timgad_Jurassic`.
- `SP_Timgad_Cine7.war`, export `1535`, `SeqAct_ChapterComplete`: `ChapterCompleted = eCHAPTER_Timgad_Jurassic`, with Brumak death effect references.
- `SP_Timgad_Scripting_13.war` streams `SP_Timgad_Cine7`, `SP_Timgad_S16Lighting`, and `SP_Timgad_S16` during the Brumak finale setup.
- `SP_Timgad_b_P.war`, export `10923`, prepares the following main map `sp_station_p`.

## OldEphyra Brumak / Gas Station

Start marker:

- Package: `SP_OldEphyra_S06GasStation_S.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.GasStation.LIGHTS_UP!__Stranded_intro.SeqAct_DisplayChapterTitle_0`
- Decoded property: `DisplayChapter = eCHAPTER_Kryll_Powderkeg`

Start checkpoint:

- Package: `SP_OldEphyra_S06GasStation_S.war`
- Actor: `TheWorld.PersistentLevel.WarCheckpoint_1`
- Location: `[34238.0, 46559.0, -902.5]`
- Rotation yaw: `10084`
- Activated by: `TheWorld.PersistentLevel.Main_Sequence.GasStation.LIGHTS_UP!__Stranded_intro.SeqEvt_CheckpointActivated_0`

Named mid/fight checkpoint:

- Package: `SP_OldEphyra_S06GasStation_S.war`
- Actor: `TheWorld.PersistentLevel.WarCheckpoint_2`
- CheckpointName: `S06 Gas Station`
- Location: `[35840.0, 49872.0, -877.82421875]`
- Rotation yaw: `-14731`
- Activated by: `TheWorld.PersistentLevel.Main_Sequence.GasStation.Return_to_station.SeqEvt_CheckpointActivated_0`

Brumak/finale evidence in the same source family:

- `Geist_Brumak`
- `Brumak_Camera_Anims`
- `COG_GasTanker`, `COG_GasTanker_CineDry`, `COG_GasTanker_Physics`
- `GasStation_Explo`, `GasStation_Powerup`
- `Music_GasStationBattleCue`
- `Junker_Boom`
- `scripted_gas_tank_hit_explosion_01` through `_04`
- `SP_Gastation_Krill_End_Seq`

Completion marker:

- Package: `SP_OldEphyra_S06GasStation_Cin.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.SeqAct_ChapterComplete_3`
- Decoded property: `ChapterCompleted = eCHAPTER_Kryll_Powderkeg`
- Comment: `Powderkeg`

Immediate post-fight/coda:

- Package: `SP_OldEphyra_S06GasStation_S2.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.SeqAct_ChapterComplete_2`
- Decoded property: `ChapterCompleted = eCHAPTER_Kryll_EndOfTheTunnel`
- Evidence: car push / car roll / propane tank / Kryll volume events.

Handoff out of OldEphyra:

- Package: `SP_OldEphyra_S06GasStation_S.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.GasStation.SeqAct_PrepareMapChange_0`
- Decoded property: `MainLevelName = sp_viaducts_p`

## Viaducts / Bridge Chapter

Start checkpoint:

- Package: `SP_Viaducts_P.war`
- Actor: `TheWorld.PersistentLevel.WarCheckpoint_1`
- Decoded property: `bIsLevelBeginning = true`
- Location: `[-28412.0, 11903.0, 1234.6339111328125]`

Chapter title marker:

- Package: `SP_Viaducts_Scripting_01.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.SeqAct_DisplayChapterTitle_0`
- Decoded property: `DisplayChapter = eCHAPTER_Viaducts_BurntRubber`

Initial loaded chunks:

- Package: `SP_Viaducts_P.war`
- Kismet comment: `SP_Viaducts_World,SP_Viaducts_S01, SP_Viaducts_S03, SP_Viaducts_Scripting_01`

Completion marker:

- Package: `SP_Viaducts_P.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.SeqAct_ChapterComplete_0`
- Decoded property: `ChapterCompleted = eCHAPTER_Viaducts_BurntRubber`

Handoff after bridge chapter:

- Package: `SP_Viaducts_P.war`
- Path: `TheWorld.PersistentLevel.Main_Sequence.SeqAct_PrepareMapChange_0`
- Decoded property: `MainLevelName = sp_alamo_p`
- Comment: `Load SP_Alamo_P`

## Conclusion

For the database, classify the OldEphyra gas-station/Kryll section as `SP_OldEphyra_S06GasStation*`, source chapter `eCHAPTER_Kryll_Powderkeg`, player-facing chapter `POWDER KEG`.

Classify the following bridge/viaduct driving stretch as `SP_Viaducts*`, source chapter `eCHAPTER_Viaducts_BurntRubber`, player-facing chapter `BURNT RUBBER`.

Classify the final Brumak kill chapter as `SP_Timgad_B*` plus finale/cinematic chunks such as `SP_Timgad_Cine7`, source chapter `eCHAPTER_Timgad_Jurassic`, player-facing chapter `JURASSIC PROPORTIONS`.

Do not merge these as one chapter unless building a player-facing "contiguous encounter arc" view. Source-native Kismet treats them as separate chapter sections with explicit map-change handoffs.
