# Blender Reconstruction Contract

A Blender reconstruction is acceptable for validation only when it records:

- exact package scope and source build;
- decoded StaticMesh asset and placement totals;
- unresolved mesh paths and affected placement counts;
- BSP Model totals and visible-shell selection;
- transform source and attachment composition;
- UV verification status;
- material, image, and texture-binding counts;
- excluded collision, volume, helper, skeletal, dynamic, and runtime-selected layers;
- zero unexplained scene-root objects;
- a nonblank render or deterministic scene audit.

The scene must preserve native object names where available. Guessed labels, visual nudging, and silent fallback geometry are not source-native reconstruction.

Historical Timgad scenes met several of these gates, but current reproducibility remains blocked by the absent heavy parser source.
