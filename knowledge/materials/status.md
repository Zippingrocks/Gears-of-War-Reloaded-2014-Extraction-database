# Materials and Textures

## Demonstrated

- Texture2D payload extraction to external DDS caches.
- StaticMesh section records and material references.
- Material-to-texture role caching for diffuse, normal, specular, emissive, and alpha lanes.
- UV0 routing from verified StaticMesh stream metadata.
- Blender material/image population sufficient for nonblank Timgad validation renders.

## Incomplete

- Full material-instance inheritance and scalar/vector parameter evaluation.
- Native special-shader parity for water, sky, decals, puddles, masked cards, and vegetation.
- BSP surface/material binding.
- Authored lightmaps and final lighting/post-process parity.
- Guaranteed texture-cache coverage for every map and build.

The OBJ/MTL packager in `src/` consumes decoded caches. It does not prove that those caches are complete or source-correct.
