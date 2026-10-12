# Repository Instructions

This repository is the canonical extraction and reconstruction knowledge base for Gears of War: Reloaded.

## Source of truth

- Prefer native `.war`, `.upk`, `.tfc`, package object, property, Kismet, and localization evidence.
- Treat Blender output and renders as validation, not proof of native placement or completeness.
- Preserve package names, export indices, object paths, class names, component names, and source transforms.
- Label observations, decoded facts, validated results, hypotheses, rejected approaches, and unknowns distinctly.

## Repository boundaries

- Maintained reusable code belongs in `src/`.
- Focused experiments belong in `research/` until they have deterministic fixtures and documented failure behavior.
- Curated conclusions belong in `knowledge/` and must cite compact evidence.
- Native metadata belongs in `inventory/` or `evidence/native-inventory/`.
- Never commit game packages, extracted assets, textures, audio, video, generated scenes, or Blender files.

## Promotion rules

- Do not promote a script that depends on an absent absolute-path helper.
- Do not silently guess transforms, UV offsets, material slots, streaming roots, or missing assets.
- Unsupported records must remain visible in reports and exit status.
- Every claimed fix needs a reproducible test or source-specific evidence record.
- Obsolete fixed-offset Gridlock UV scripts remain historical only.

## Validation

Run before committing:

```powershell
python tools\validate_repository.py
python -m unittest discover -s tests -v
python -m compileall -q src tools
```
