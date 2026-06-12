# CiliaBuilder2

CiliaBuilder2 is a UCSF ChimeraX bundle for building and placing cilia-related models.

It focuses on a STAR-driven workflow for:

- microtubule layouts
- central pair layouts
- membrane generation
- IFT placement
- attaching maps and models onto STAR points
- geometric drawing helpers
- session save/load
- STAR import/export

## Current Scope

The main working UI is organized into three sidebar sections:

- `Build`
- `Attach`
- `Save/Load`

Build tools currently cover:

- `Microtubules`
- `Central Pair`
- `Membrane`
- `IFT`

Attachment supports common ChimeraX model types including:

- `mrc`
- `stl`
- `glb` / `gltf`
- `pdb`
- `cif` / `mmcif`

## Install In ChimeraX

From the project root, install the bundle into ChimeraX with:

```bash
/Applications/ChimeraX-1.11.app/Contents/bin/ChimeraX --nogui --exit --cmd "devel install /Users/qs/PycharmProjects/CiliaBuilder2"
```

If you are using a different ChimeraX app bundle, replace the executable path accordingly.

## Build A Wheel

To build a distributable wheel:

```bash
/Applications/ChimeraX-1.11.app/Contents/bin/ChimeraX --nogui --exit --cmd "devel build /Users/qs/PycharmProjects/CiliaBuilder2"
```

The wheel is written into:

- `dist/`

## Open The Tool

After install, open the tool with the ChimeraX command:

```chimerax
cbui
```

The bundle also exposes these command entry points:

- `cbstraight`
- `buildcentriole`
- `cbui`
- `cbopenapr`

## Quick Start

1. Find the CiliaBuilder2 in High-Order Structures
2. In `Build > Microtubules`, create a STAR model.
3. Open or load a source map/model in ChimeraX.
4. In `Attach`, choose a `STAR model` and `Map model`.
5. Click `Attach selected STAR + map`.
6. Save your scene later with `Save session JSON`.

## Example Files

Example inputs in this repo include:

- [example/random_load_test.star](https://github.com/builab/CiliaBuilder2/blob/main/example/CH_14.00Apx_complete.mrc)
- [example/doublet.star](/Users/qs/PycharmProjects/CiliaBuilder2/example/doublet.star)
- [example/cp.star](/Users/qs/PycharmProjects/CiliaBuilder2/example/cp.star)
- [example/triplet.mrc](/Users/qs/PycharmProjects/CiliaBuilder2/example/triplet.mrc)
- [example/CH_14.00Apx_complete.mrc](/Users/qs/PycharmProjects/CiliaBuilder2/example/CH_14.00Apx_complete.mrc)

You can also import external STAR files from `Save/Load > Load STAR file`.

## Session Save/Load

The session JSON workflow preserves:

- generated STAR models
- generated membranes
- attach sources
- attachments
- selected UI state

For portable sessions, copied `glb`, `gltf`, and `stl` assets are stored next to the JSON package instead of overwriting the original source files.

## STAR Workflows

Current STAR-related features include:

- building new microtubule STAR models
- continuing a microtubule build from an existing STAR model
- importing external `.star` files
- exporting the current STAR model back to `.star`
- substituting a selected filament through the temporary substitution window

## Geometric Drawing

The `Attach > Geometric drawing` section provides drawing helpers that can be used for guide geometry and later export as GLB for attachment workflows.

## CellPACK Status

CellPACK-related code paths still exist in the source tree, including local APR helpers and membrane export support, but the visible cellPACK UI is currently hidden.

## Repository Layout

Important files:

- [bundle_info.xml](/Users/qs/PycharmProjects/CiliaBuilder2/bundle_info.xml)
- [src/__init__.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/__init__.py)
- [src/tool.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/tool.py)
- [src/history_mixin.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/history_mixin.py)
- [src/map.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/map.py)
- [src/cmd.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/cmd.py)
- [src/draw.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/draw.py)
- [src/star.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/star.py)
- [src/cellpack_export.py](/Users/qs/PycharmProjects/CiliaBuilder2/src/cellpack_export.py)
- [AGENTS.md](/Users/qs/PycharmProjects/CiliaBuilder2/AGENTS.md)

## Development Notes

- This project is packaged as a ChimeraX bundle, not a generic `pyproject.toml` Python package.
- Use ChimeraX `devel install` / `devel build` instead of `python -m build`.
- The current bundle metadata lives in [bundle_info.xml](/Users/qs/PycharmProjects/CiliaBuilder2/bundle_info.xml).
- The current wheel output goes to [dist](/Users/qs/PycharmProjects/CiliaBuilder2/dist).

## Notes For Future Editing

This repo keeps a detailed working contract in [AGENTS.md](/Users/qs/PycharmProjects/CiliaBuilder2/AGENTS.md). If behavior changes, update that file too.
