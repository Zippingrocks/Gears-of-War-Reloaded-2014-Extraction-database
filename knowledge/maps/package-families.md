# Map Package Families

The native map root contains these top-level families:

`Comic`, `gyms`, `MP_Maps`, `SP_Adams`, `SP_Alamo`, `SP_Caves`, `SP_Eba`, `SP_EBA_Riverwalk`, `SP_Embry`, `SP_EphyraStreets`, `SP_Factory`, `SP_FactoryBasement`, `SP_FactoryInterior`, `SP_HOS`, `SP_OldEphyra`, `SP_Prison`, `SP_Station`, `SP_Timgad`, `SP_Timgad_B`, `SP_Tomb`, `SP_Tyro`, and `SP_Viaducts`.

A playable area is usually a package family, not one file. Roles can include persistent/root, world, numbered geometry chunks, scripting, cinematics, lighting, audio, VFX, and out-of-bounds helpers.

Grouping rules:

1. Start from the persistent package and decoded LevelStreaming references.
2. Add Kismet load/unload and map-change targets.
3. Preserve scripting, cinematic, lighting, audio, and VFX roles separately.
4. Keep package-family identity distinct from player-facing chapter identity.
5. Do not merge contiguous story sections merely because gameplay transitions between them.

`MP_Gridlock.war` is the primary multiplayer regression anchor. Timgad A and B are the strongest recorded campaign reconstruction families.
