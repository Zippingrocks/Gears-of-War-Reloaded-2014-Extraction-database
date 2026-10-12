# Gears of War Reloaded - Horde Trace Scan

Scan date: 2026-08-10

## Conclusion

I do not see evidence that Reloaded contains usable or planned Horde mode scaffolding in the shipped local files we scanned.

There are traces of the word `Horde`, but they classify as lore/dialogue or isolated raw bytes, not a decoded mode implementation.

## Evidence

- Install root scanned: `D:\SteamLibrary\steamapps\common\Gears of War Reloaded`
- Horde-named files/folders: `0`
- Core packages decoded for name/import/export checks: `6`
- Decoded package name-table hits for Horde-mode terms: `0`
- Decoded import hits for Horde-mode classes/systems: `0`
- Decoded export hits for Horde-mode classes/systems: `0`
- Config hits: `0`
- Localization text hits: `424`
- Raw/virtual package byte hits: `2`

The localization hits are Myrrah/Locust Horde lore, bios, or ordinary text such as `Survival` / `Fortification Act`, not menu, playlist, wave, survival, or Horde-mode UI strings.

The only non-localization clue is a raw uppercase `HORDE` token in both `WarfareGame.u` copies at offset `130657`, near other MP-ish words in raw bytes. It does not appear as a decoded package name, import, or export, so it is a weak trace only.

## Report Files

- Summary JSON: `C:\Users\Bilbo\Downloads\Gears Map Ripping\reports\gow_reloaded_horde_trace_scan_2026_08_10\summary.json`
- Raw byte hits: `C:\Users\Bilbo\Downloads\Gears Map Ripping\reports\gow_reloaded_horde_trace_scan_2026_08_10\raw_horde_offsets.csv`
- Localization hits: `C:\Users\Bilbo\Downloads\Gears Map Ripping\reports\gow_reloaded_horde_trace_scan_2026_08_10\localization_hits.csv`
- Scanner tool: `C:\Users\Bilbo\Downloads\Gears Map Ripping\tools\gowreloaded_horde_trace_scan.py`
