# Asset Policy

Commit only source code, schemas, compact metadata, hashes, evidence summaries, and documentation.

Do not commit `.war`, `.upk`, `.tfc`, `.bik`, extracted meshes, textures, materials, audio, video, `.blend`, FBX, OBJ, or generated scene data. Keep those files in an external user-owned workspace.

An evidence record may include a native relative path, object identifier, count, byte size, or hash. It must not embed proprietary payload bytes.
