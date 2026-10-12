# StaticMesh UV Layout

## Proven rule

Do not use a fixed UV offset for Reloaded StaticMesh exports.

Gridlock proved that a decoded cache's `static_vertex_buffer.data_rel` can identify UE3 UV stream metadata rather than the first vertex payload. The old fixed-offset path misread every ordinary bulk StaticMesh row and produced smeared or triangular textures.

The maintained regression guard recognizes two metadata-relative layouts and validates:

- texture-coordinate count from `1` to `8`;
- item size and vertex count agreement;
- full- versus half-precision UVs;
- repeated bulk item size/count;
- payload delta from the decoded `data_rel`;
- UV channel offset derived from `item_size - num_texcoords * pair_size`.

Run:

```powershell
python src\gowreloaded_static_uvstream_regression_guard.py `
  --clean-csv "<decoded clean extract csv>" `
  --decompressed-dir "<decompressed package directory>" `
  --proof-out "<external proof directory>\static-uv-proof.json"
```

The gate must report `status: pass`, `failure_count: 0`, and `repo_verified` for ordinary bulk position/index rows. Inline streams are a separate visual class and may be reported as skipped when explicitly identified.
