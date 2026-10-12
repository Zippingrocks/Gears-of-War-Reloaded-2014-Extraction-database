# Chapter Boundary Evidence

Preserve three identities for every story section:

1. Native package family.
2. Runtime/Kismet chapter enum.
3. Localized player-facing title.

Confirmed examples:

| Package family | Runtime enum | Player title |
| --- | --- | --- |
| `SP_Timgad` A | `eCHAPTER_Timgad_Impasse` | `IMPASSE` |
| `SP_Timgad` A | `eCHAPTER_Timgad_Comedy` | `COMEDY OF ERRORS` |
| `SP_Timgad_B` | later Timgad enums | `WINDOW SHOPPING`, `POWERS THAT BE`, `JURASSIC PROPORTIONS` |
| `SP_OldEphyra_S06GasStation*` | `eCHAPTER_Kryll_Powderkeg` | `POWDER KEG` |
| `SP_Viaducts*` | `eCHAPTER_Viaducts_BurntRubber` | `BURNT RUBBER` |

Decoded handoffs include Old Ephyra to `sp_viaducts_p`, Viaducts to `sp_alamo_p`, and Timgad A to `sp_timgad_b_p`. The final Timgad Brumak encounter belongs to `eCHAPTER_Timgad_Jurassic`, not the Old Ephyra gas-station Brumak sequence.

Chapter-focused Blender exports remain approximations until every streaming transition is reconstructed in runtime order.
