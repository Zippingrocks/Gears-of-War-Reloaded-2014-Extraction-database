# Reloaded Cooked Packages

Reloaded stores maps and many assets in Unreal-style cooked packages with `.war` and `.upk` suffixes. Texture bulk data also appears in `.tfc` caches; pre-rendered video uses `.bik`.

Sampled map headers begin with:

| Field | Value |
| --- | --- |
| Package tag | `0x9E2A83C1` |
| File version | `835` |
| Licensee version | `76` |
| Folder name | `None` |

After the tag, version pair, header size, and folder string, the maintained parser reads package flags and the name/export/import table counts and offsets. Counts and offsets are structural metadata; they do not by themselves prove payload decoding.

Many map packages are compressed. A full exporter must reconstruct the virtual package before resolving names, imports, exports, serialized properties, StaticMesh buffers, and BSP Model arrays.

Never identify a package by extension alone. Validate the tag, versions, table bounds, and source build.
