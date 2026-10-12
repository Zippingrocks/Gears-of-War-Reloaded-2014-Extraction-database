# Research Model

`research/legacy-probes/` preserves the latest surviving Reloaded-specific scripts from the canonical workspace. Many are map-specific, contain historical external paths, or import a heavy parser that is no longer present.

Promotion into `src/` requires portable inputs, no hidden dependencies, deterministic fixtures, explicit unsupported-data reporting, and documentation of the source-native contract. A script is not promoted merely because it produced a visually useful result once.
