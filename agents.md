# CiliaBuilder2 Agent Notes

This file is the handoff and working contract for future edits to this project.

The main rule for this repo is:

- preserve working behavior first
- prefer narrow patches over broad refactors
- do not rewrite working attachment, JSON, or GLB logic unless the user explicitly asks for it
- after any correct behavior-changing code fix, update this `agents.md` so the new stable rule is recorded


## Project Overview

CiliaBuilder2 is a ChimeraX bundle for building and placing cilia-related geometry:

- outer filament STAR models
- central pair STAR models
- membrane surfaces
- IFT STAR models
- attachments of maps/models onto STAR placements
- session JSON save/load
- cellPACK/APR/CPR export and load helpers

This working directory now tracks `https://github.com/builab/CiliaBuilder2.git` through Git. It contains local changes and files not present upstream; preserve them when pulling future updates.

### Upstream Integration (2026-10-12)

- Fast-forwarded `main` from `d7cea80` to `a3f8dfc` (52 upstream commits), then merged the local clipping and GLB-anchor fixes on top.
- Keep upstream's 0.2.1 package metadata, renamed `buildcentralpair` command, new example folders, 3000-Angstrom default build lengths, fixed-center controls, and multi-layer GLB source handling. Do not replace them with the older local UI/metadata.
- Session JSON now saves only managed content under CiliaBuilder2, not unrelated top-level scene models. Tests that export sources directly must archive those sources under Maps/Models first.
- An explicit fixed center takes precedence over the automatic volume-derived GLB anchor. Clipping and JSON replay must preserve both the fixed anchor and resulting attachment transforms.
- Previous local sources, documentation, tests and wheels are preserved in `/Users/qs/PycharmProjects/CiliaBuilder2-backup-20261012-202144/local-work.tgz` and pre-pull Git stashes. The nested checkout and external cellPACK directory were not modified. Older wheels removed from tracking upstream remain local ignored artifacts, not updated releases.

There is now also a root-level `README.md` intended for users and bundle distribution. When visible workflows, install steps, or packaging behavior change, update the README along with this file.

There is also now a root-level `paper.txt` manuscript scaffold. It is a plain-text draft template for the project paper and should be updated when the paper outline or manuscript framing changes.


## Main Files

- `/Users/qs/PycharmProjects/CiliaBuilder2/src/tool.py`
  - main UI
  - session save/load
  - selector logic
  - build actions
  - attachment replay
  - manual tweak workflow
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/map.py`
  - actual attachment backend
  - transform logic
  - instancing
  - source copying
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/history_mixin.py`
  - global undo/redo logic
  - per-step history delta recording
  - attachment-aware undo removal / redo restore helpers
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/cmd.py`
  - STAR rendering
  - membrane geometry creation
  - bundle commands and grouping helpers
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/draw.py`
  - STAR row generation
  - filament / central-pair coordinate generation
  - microtubule and central-pair builders share the axial position loop; IFT modes share row construction
  - keep STAR row output unchanged when cleaning these builders; run `python3 -B -m unittest discover -s tests -p test_draw_outputs.py`
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/orientation.py`
  - shared RELION Euler conversion, explicit STAR axes, and rigid vector alignment
  - used by STAR rendering, attachment, generation, and export; keep these conventions identical
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/source_paths.py`
  - records original GLB/GLTF inputs, including gzip inputs whose paths ChimeraX does not retain
  - normalizes compressed GLB display names without changing file paths or flattening their model trees
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/glb_anchor.py`
  - preserves volume-derived GLB attachment centers as optional glTF metadata
  - recovers old volume exports only through verified mesh matching, never filenames
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/clipping.py`
  - persists scene clipping planes and per-drawing clipping permissions in JSON
  - includes non-Model GLB drawings but excludes derived clip-cap geometry from saved paths
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/cellpack_export.py`
  - cellPACK-style export package
  - APR/CPR-related export pieces
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/membrane_recipe.py`
  - active independent stochastic membrane packer and selectable ingredient recipes
  - uses membrane_cellpack.py for legacy-compatible preview, history and export
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/membrane_collision.py`
  - cached triangle-distance and closed-mesh ray-parity checks for bead/protein contact
  - boxes are broad-phase filters only, not the excluded protein volume
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/membrane_cellpack.py`
  - built-in, incremental surface particle packing, preview, state and membrane-only export
- `/Users/qs/PycharmProjects/CiliaBuilder2/src/membrane_cellpack_ui.py`
  - optional membrane packing dialog with cancellable timer-driven preview and export
- `/Users/qs/PycharmProjects/CiliaBuilder2/bundle_info.xml`
  - bundle metadata


## Example Assets

- `/Users/qs/PycharmProjects/CiliaBuilder2/example/random_load_test.star`
  - deterministic external STAR loader test file
  - includes an optics loop before the particle loop on purpose
  - useful for testing `Save/Load > Load STAR file`


## Current UI Structure

The floating tool window uses three west-side sidebar tabs:

- `Build`
- `Attach`
- `Save/Load`

Inside the `Build` page there is another tab widget with:

- `Microtubules`
- `Central Pair`
- `Membrane`
- `IFT`

Important:

- there is now one always-visible global `Undo` / `Redo` button row at the upper right of the tool window
  - it is intended to cover scene-changing CiliaBuilder actions broadly, not only attachment
- the old pixel-size widget still exists internally, but it is hidden
- the older internal microtubule `angle_set` control still exists for compatibility, but it is hidden again
- manual tweak UI is hidden, but the code is still present and should not be removed casually
- `Load cellPACK` and `Export cellPACK package` code paths still exist, but their buttons are intentionally hidden in the `Save/Load` page for now
- there is now a visible `Load STAR file` button in the `Save/Load` page
- there is now a visible `Export STAR file` workflow in the `Save/Load` page
  - it uses its own STAR-model selector
  - it should write the current STAR rows from the selected model, not stale imported source text
- the `Auto Z-align map/model` interface is currently removed from the visible `Save/Load` page
- the build-page inner tab order is currently:
  - `Microtubules`
  - `Central Pair`
  - `Membrane`
  - `IFT`
- inside the `Attach` page there is now a top tab bar that switches between:
  - `Attachment`
  - `Geometric drawing`
- the floating window default startup size is currently a little wider than before at about `540 x 450`
- the main CiliaBuilder window should not force itself to stay above every other window
  - temporary dialogs such as filament substitution can sit above it normally
- the temporary filament substitution window should stay on top of the main CiliaBuilder window while it is open


## Hidden Pixel Size Behavior

The visible pixel size interface was removed from the UI, but the internal widget still exists:

- `self.pixel_size` in `tool.py`
- default internal value is `1.0`
- it is hidden with `self.pixel_size.hide()`

Do not remove the internal widget unless the user explicitly asks for a full pixel-size redesign.

Current implication:

- new builds use the hidden internal value unless the data already carries `rlnImagePixelSize`
- many newer workflows effectively behave like pixel size `1.0`
- JSON UI state still persists this hidden pixel-size value
- command-layer builders in `cmd.py` still expose `pixel_size` arguments and default them to `1.0`


## Build Behavior

### Microtubules

- Build button: `Build microtubules`
- Continue button: `Continue microtubules`
- there is now a `Substitute filament` button in the microtubule tab
  - it opens a temporary substitution window
  - the user picks one displayed STAR point to identify the filament / tube id to replace
  - when `Apply substitution` is pressed, the current picked filament target should be consumed immediately
  - while a substitution value field is being edited, `Apply substitution` must stay disabled until that edit is explicitly confirmed with Enter or focus loss
  - after a substitution attempt finishes, the picked filament target should be cleared from the temporary window so the same stale target cannot be applied again accidentally
  - substitution should first rebuild the chosen filament in the existing STAR model, and that visible change should succeed before any separation logic is attempted
  - after that working replacement is made, the changed filament should be read back from the updated STAR rows
  - the original STAR model should then be refreshed with that filament removed
  - the changed filament should be separated into its own new STAR model for independent attachment
  - if the later separation step fails, the already-applied changed STAR model should be kept as-is rather than rolled back or broken
  - the replacement filament should stay on the same filament line, using temporary-window values for:
    - `Length`
    - `Periodicity (spacing)`
    - `Z offset`
    - `Twist per layer (deg)`
  - because both resulting outputs are normal CiliaBuilder STAR models, the change should carry through to:
    - displayed STAR rendering
    - session JSON save/load
    - STAR export
    - undo / redo history
- external `.star` files can now be loaded from `Save/Load > Load STAR file`
- STAR models can now be exported from `Save/Load > Export STAR file`
  - export should serialize the current in-memory STAR rows
  - if a STAR was continued/edited after import, the exported file should reflect the current state
  - loaded STARs are converted into normal CiliaBuilder STAR models under `CiliaBuilder2 > STAR Models`
  - they should participate in the ordinary STAR selector / attach workflow like built STARs
  - importer should tolerate missing optional columns by defaulting:
    - angles to `0`
    - pixel size to `1`
    - helical tube id to `1`
    - class number to `1`
  - importer should normalize loaded external STAR rows to internal `rlnImagePixelSize = 1`
  - importer should still preserve the original world placement by scaling the stored coordinates and `_cbWorldCoordinate*` values appropriately during import
- there is now a visible `Continue from STAR` selector in the microtubule panel
- `Continue microtubules` should operate on the STAR selected in that selector
- it should create a new continued STAR model rather than mutating the selected source STAR in place
- the original source STAR should remain available so different versions can be attached to different maps/models
- continuation should create a new offset-generated segment model, not append the old rows into the continued output
- the continued model's start `Z offset` should equal:
  - base model `Z offset`
  - plus base model `Length`
  - plus one base `Periodicity (spacing)`
- the continued model should carry that computed start `Z offset` as its own stored continuation base for later continues and session restore
- continuation direction should follow the selected STAR line geometry instead of rebuilding a new ring from scratch
- for CiliaBuilder-built microtubule STARs, continuation should use a remembered next-start offset
  - next segment start = previous requested length + one repeating unit
  - after each continuation, the remembered next-start offset should advance by `continued length + repeating unit`
  - continuation should not depend only on the last actual bead coordinate
- older/imported STARs may still fall back to a geometry-derived continuation offset when no remembered offset exists
- `Angle of set (deg)` is no longer shown in the microtubule build UI
- the underlying internal value remains present for compatibility and currently defaults to `0`
- current startup defaults for the microtubule tab are:
  - length `3000`
  - no. of doublet `9`
  - radius `960`
  - periodicity `1000`
  - twist per layer `0`
  - Z offset `0`
  - random disabled
- in the microtubule tab:
  - `Twist per layer (deg)` adds a gradual extra local Z-axis rotation for each successive axial layer of points
    - layer `0` uses the base ring placement
    - each next layer rotates by the given additional amount in place
    - it should not move the filament's `x/y` ring position around the bundle
  - `Z offset` is the actual axial line movement along Z for the built STAR rows
- the older visible `Z axis rotation` control is intentionally hidden again
- randomization is per filament, not per point
- filament randomization is intended to preserve equal filament lengths while shifting whole filaments in Z
- random-enabled filament builds also support cut/clip logic that later attachments may inherit
- STAR display arrows are now rendered as simple surface arrows:
  - cylinder shaft plus cone head
  - particle centers still use the marker-set display

### Central Pair

Current modes:

- `Singlet line`
- `C1 + C2 lines`

Internal naming cleanup:

- active central-pair code paths now use `central_pair_*` names instead of older `centriole_*` names
- legacy compatibility fallbacks may still exist for:
  - old session JSON keys like `centriole_length`
  - the legacy Python callable alias `cmd.buildcentriole` (the advertised command is now `buildcentralpair`)
- preserve those fallbacks unless the user explicitly asks to drop backward compatibility

Current central-pair rules:

- `Singlet line` builds one central pair STAR model
- `C1 + C2 lines` builds two separate STAR models so different models can be attached to C1 and C2
- there is a user-visible `C1/C2 distance` field
- the current implementation places:
  - C1 at `-distance / 2`
  - C2 at `+distance / 2`
- current startup defaults for the central-pair tab are:
  - length `3000`
  - periodicity `333`
  - Z offset `0`
  - mode `Singlet line`
  - C1/C2 distance `100`
- the older `Tube id` UI was intentionally removed and should stay removed unless the user asks for it back
- STAR naming matters:
  - central pair single-line builds use normal central pair STAR names
  - dual-line builds should clearly distinguish C1 and C2

### Membrane

Membrane has its own build tab and its own ChimeraX model group.

Current visible parameters:

- `Length`
- `Radius`
- `Thickness`
- `Offset`
- `Distortion level`
- `Tip dome cap`

Current hidden internal membrane controls:

- `Receptors (%)`
- `Channels (%)`
- `Signaling (%)`
- `Scaffold (%)`
- `Lipids (%)`

Important:

- these membrane composition controls are intentionally hidden in the UI for now
- they are still persisted in session JSON
- future edits should keep them hidden unless the user explicitly asks to expose them
- current startup defaults for the membrane tab are:
  - length `3000`
  - radius `1350`
  - thickness `40`
  - offset `0`
  - distortion level `0.60`

Parameter meaning:

- `Radius` is the cylinder radius, not diameter
- `Radius` here means the membrane cylinder radius, not the cellPACK membrane particle radius
- `Offset` is axial offset along the main filament axis, not radial displacement
- membrane placement should start exactly from the chosen STAR-end plane
  - with randomized cut STARs, that means the cut-side start plane
  - otherwise it means the ordinary filament start side
  - `Offset` then moves that start plane along the membrane axis before the membrane length is applied
- membrane axis placement should use the bundle centerline inferred from equal tube weighting, not a raw all-points mean that can drift sideways when tube lengths differ
- `Tip dome cap` is an optional visible toggle for the generated display membrane
  - when enabled, it replaces the flat distal end with a dome on the tip side only
  - the dome uses the current membrane radius as its minimum cover size
  - if attached outputs already exist on the same outer STAR model, the dome may auto-extend farther along the tip axis so it fully covers the distal attached geometry

Membranes are grouped under:

- `CiliaBuilder2 > Membrane`

not under `Maps/Models`.

### Marker Path

There is now one shared `Geometric drawing` group inside the `Attach` page under the `Geometric drawing` top-tab.

Current visible parameters:

- `Draw type` bar with:
  - `Point`
  - `Sphere`
  - `Cylinder`
  - `Curve`
  - `Line`
- `Draw on model`
- `No. of markers`
- `Primitive radius`
- `Tube radius`
- one shared draw button whose text changes with the selected draw type
- `Drawing model`
- `Save drawing as GLB`

Current marker-path rules:

- the `Draw on model` selector is shared across the whole geometric-drawing workflow and is intentionally not scoped only to paths
- `Point` creates a one-point guide model under `Maps/Models`
- `Sphere` creates a one-point sphere-style guide model under `Maps/Models`
- `Cylinder` uses two picked points and creates a straight cylinder/tube guide model under `Maps/Models`
- `Curve` and `Line` reuse the same marker-pick machinery as primitive drawing, but produce tube/path outputs instead of one-off primitives
- the button switches left mouse into ChimeraX marker placement mode
- current preferred placement mode is `mark surface`, with `mark point` fallback if needed
- geometric drawing uses an explicit `Draw on model` selector populated from the current `Maps/Models` section rather than guessing the target model from the whole scene
- the selector should auto-select the first available model in `Maps/Models` when possible
- placed markers go into a temporary internal marker set first
- when placement starts, the chosen target model should be explicitly ChimeraX-selected with `select #...` after the button press and before marker clicking begins
- non-target visible scene models should be temporarily hidden so `mark surface` lands on the intended model
- once the requested marker count is reached, those points are turned into a final path model automatically
- completion should be monitored from the temporary marker set itself, using atomic marker-change events and timer fallback rather than relying only on ChimeraX selection-change timing
- the final marker-path result is a tube surface, not marker-link geometry
- `Line` mode makes a tube that follows the placed control points directly
- `Curve` mode makes a smooth tube through the placed control points
- tube thickness is controlled by the visible `Tube radius` field
- `No. of markers` only applies to `Curve` and `Line`; point/sphere/cylinder use fixed pick counts
- `Primitive radius` only applies to point/sphere/cylinder
- the visible replicate-to-STAR workflow has been replaced in the UI by GLB export for generated geometric drawings
- the `Drawing model` selector lists generated geometric drawing outputs, not the scene target model being clicked on
- the drawing export controls are intentionally stacked vertically to keep the floating tool narrower
- `Save drawing as GLB` should export the live drawing model to a `.glb`, then reopen that `.glb` as a normal attachable model and switch the `Map model` selector to it
- generated marker-path models remain guide/path outputs and are still filtered out of the attach-source selector directly
- the reopened saved `.glb` is the intended attachable replacement for that drawing
- marker-path session restore now rebuilds tube geometry from saved control points, mode, and tube radius
- generated marker-path models are guide/path outputs, not attach sources
- generated marker-path models should stay out of the map/model selector
- only `Place markers for path` enters cancellable marker-placement mode
- when the last marker is placed, temporary marker cleanup is deferred until after the ChimeraX mouse event finishes, to avoid the old `NoneType ... selection` exception during selection clear


## Membrane Distortion

The current membrane distortion should be treated as the accepted version unless the user explicitly wants a new shape model.

Important current behavior:

- distortion is based on the earlier low-frequency smooth sine/cosine style
- there are now **9 separate same-style curve terms**
- do not reintroduce the later experimental grouped/phase-alignment distortion version
- `Distortion level (0-10)` now edits an existing membrane on committed `valueChanged`, with keyboard tracking disabled so typing waits for Enter or focus loss. The range was already 0-10; only the former 0-1 label was wrong.
- Target a selected generated membrane first. If several are selected, prefer the latest built/restored one among them, otherwise the last selected membrane in model order. With none selected use the latest built/restored live membrane, falling back to the last remaining membrane if that target was deleted.
- If no membrane exists, the field only sets the value for the next build; it must not create geometry by itself. Committing an unchanged value must not create an undo entry.
- Live distortion edits use the model's stored dimensions, axis, center, dome heights and random seed, not unrelated uncommitted Build field values. Keep all nine wave terms, amplitude formulas and dome taper unchanged.
- `cmd.buildmembrane_surface(..., existing_surface=model)` rebuilds the existing surface in place without creating a temporary model or changing model ID, grouping, placement, color, display, selection or clipping permissions. Preserve vertex colors and triangle/edge masks when topology is unchanged, plus extra membrane metadata such as source STAR and offset.
- The accepted edit is one global undo action. Restoring an existing membrane must rebuild its geometry from saved state, not merely restore colors/display and skip the changed distortion. Undo/Redo also restores the field value for the active target without triggering another edit.
- Programmatic UI loading blocks the distortion widget's signals around `setValue`, restoring the prior blocking state afterward; it must not change existing geometry or add undo history, even when the field later loses focus. Do not use unconditional `editingFinished` for rebuilding, since it also fires for unchanged/programmatically loaded values. JSON rebuilds each membrane from its own saved level and seed, and restored membranes remain live-editable.
- Regression script: `runscript tests/verify_membrane_distortion.py`. Seven geometry/history/JSON tests run headlessly; an additional real-widget test runs in GUI ChimeraX and checks Enter, focus-loss and programmatic load behavior.
- All eight tests pass in GUI ChimeraX 1.7.1 and 1.11. The full headless 1.11 clipping, GLB-path/anchor (including EMDB 2132), attachment-center/Z-offset, STAR-orientation and command checks also pass after this change; straight-builder output hashes are unchanged. Do not use Qt's offscreen platform plugin for the GUI check on this Mac: it cannot create ChimeraX's OpenGL context; use a separate normal GUI process instead.

The current goal is:

- still organic / smooth
- but influenced by 9 components to echo the 9 outer filaments
- if the visible membrane uses the optional tip dome cap, distortion should taper smoothly to zero toward the dome pole so high distortion values do not create a pinched or star-like tip center

State saved with membranes includes:

- center
- axis
- length
- diameter/radius-derived geometry
- thickness
- distortion level
- distortion seed
- tip-dome enabled flag
- resolved tip-dome outer/inner heights

Additional membrane expectations:

- the membrane should start from the cut side when a randomized outer filament STAR provides clip anchor information
- otherwise it starts from the ordinary filament start side
- membrane display state is restored from session JSON
- the visible ChimeraX membrane can optionally use a dome only on the distal tip end; the proximal/base end stays in the existing flat-ended style
- the detailed cellPACK membrane bundle is currently an open cylinder wall only
  - no top cap
  - no bottom cap
- the detailed cellPACK membrane export is now lipid-rich by default so the membrane is visually filled rather than sparse
- the detailed membrane export also writes a membrane mmCIF with one explicit pseudo-site per packed membrane particle


## Model Grouping in ChimeraX

Current intended top-level grouping under the CiliaBuilder root:

- `STAR Models`
- `Maps/Models`
- `Membrane`

Future edits should preserve this grouping scheme unless the user requests a different one.

Grouping expectations:

- generated STAR models should live under `STAR Models`
- archived and reusable attach sources should live under `Maps/Models`
- generated attached outputs also end up under the maps/models side of the tree
- generated marker-path guide tube models also live under `Maps/Models`, but as non-source container models
- generated membrane models should live under `Membrane`


## Supported Attachment Source Types

Current supported source types include:

- volume maps such as `mrc`
- `stl`
- `glb` / `gltf`
- atomic models like `pdb`, `cif`, `mmcif`

Important:

- GLB is composite and special
- do not simplify GLB handling to “first leaf only”
- the working GLB attach path is the one the user restored manually and wants preserved
- GLB color is important and must be preserved during attachment, including nested child nodes inside composite GLB trees
- STL should be treated as top-level direct geometry
- for GLB:
  - selector shows the GLB itself
  - backend may need to traverse the GLB tree
  - selector should not expose GLB child nodes as independent user choices
  - for real ChimeraX `gltfModel` sources, attachment copy should prefer a real glTF asset reopen path over a plain Python `Model` clone so file-native glTF materials/colors survive
  - if ChimeraX does not expose a usable source path on the live `gltfModel`, the current fallback is to export the live model to a temporary `.glb` and reopen that for attachment
  - after attachment, the source model's captured color tree should be reapplied onto each attached GLB copy so recolored children such as nested marker/atom branches keep their colors
  - if the reopened temporary GLB inserts an extra nested root node, color replay should also target that nested root so direct recolors still land on the intended GLB children
- fetched models may also be used as attach sources when they can be identified by fetch id


## Attachment UI Controls

Current visible attachment controls:

- `Attachment Z rotation (deg)`
- `Attachment Y rotation (deg)`
- `Use fixed center for GLB & PDB`, with X/Y/Z fields
- `Read center coordinate from map`, with a source-map selector

Current semantics:

- Z offset is the line-wise / macro rotation path
- Y rotation is model-local orientation adjustment
- the relic Advanced options section was removed upstream; do not restore it while merging older local changes
- legacy pre-attach rotation flags still load from older JSON and apply before ordinary Y rotation
- a checked fixed center replaces the computed source anchor for non-volume models; maps always retain their grid center
- JSON persists both the fixed-center UI controls and each attachment's `fixed_anchor`

Current attach UX expectations:

- selectors now auto-pick the first real STAR/model option when available
- a `None` placeholder still exists internally in the combo boxes
- after a successful attach, selectors and visible attach parameter controls stay as-is
- after a successful attach, the source is archived/hidden under `Maps/Models`
- after a successful attach, the used STAR model is typically hidden


## Undo / Redo

Current intended behavior:

- the old attachment-only undo button/method is removed
- undo/redo is now global UI at the top right of the tool window
- undo/redo should cover CiliaBuilder STAR/model-producing and attachment actions broadly, including in-place product edits that change those managed results
- undo should revert the most recent CiliaBuilder-managed action, and redo should reapply that most recently reverted action
- the undo history limit is `30`
- undo/redo should currently cover actions such as:
  - microtubule, central-pair, membrane, and IFT STAR generation
  - microtubule continuation on an existing STAR
  - attachment creation
  - attachment rebuilds caused by changing attachment rotation controls
  - geometric drawing finalization
  - picked IFT placement generation
  - auto Z-align model creation
- save/load actions are intentionally excluded from undo/redo history
- load-style actions such as `Load session JSON`, `Load STAR file`, and local cellPACK load should reset the undo/redo stacks instead of becoming undoable entries
- the current implementation now records per-step managed scene deltas instead of replaying whole-scene recursive session snapshots
- attachment undo should remove the attached result created by that step, not recursively rebuild the whole scene
- redo should restore only the recorded touched items for that step
- generated STAR products for save/load/history must be collected by scanning the full recursive session model tree, not only top-level ChimeraX models, because STAR products live under `CiliaBuilder2 > STAR Models`
- when undo/redo removes a managed model tree, the current accepted delete path is:
  - hide every descendant model first
  - close the tree child-first
  - then force a redraw
  this avoids ghost displayed STAR particle children that can linger after the parent disappears from the model panel
- for nested CiliaBuilder content, undo/redo must target the specific managed model subtree itself, not walk up to the top-level `CiliaBuilder2` root model


## Attachment Transform Rules

### STAR Orientation

- RELION/ArtiaX particle placement uses `Rz(-psi) @ Ry(-tilt) @ Rz(-rot)`, acting on column vectors; its columns are local X/Y/Z in the scene.
- Do not transpose `Rz(psi) @ Ry(tilt) @ Rz(rot)` to obtain this matrix. That reverses Rot/Psi order and only appears correct at zero tilt.
- Matrix-to-Euler conversion must invert the same convention, including tilt 0 and 180 degrees. Near-pole tilts use `atan2` for precision.
- Cached `_cbAxisX/Y/Z` remain authoritative when present. IFT, substitution, continuation, and marker-pattern rows must also store matching Euler angles.
- STAR export recalculates Euler angles from cached axes without mutating the live rows, so older JSON rows with stale/zero angles still export their visible orientation correctly.
- The zero-tilt parametric builder output and its established clockwise/anticlockwise behavior remain unchanged.
- Vector alignment must be a proper rigid rotation (orthogonal matrix, determinant +1). With a normalized cross-product axis, Rodrigues' skew term needs its sine factor; otherwise tilted arrows distort.
- For antiparallel vectors, choose a perpendicular half-turn axis rather than assuming world X is perpendicular.
- Verify with ChimeraX `runscript tests/verify_star_rotations.py`: external STAR angles, 0/180-degree poles, tilted substitution/continuation, export/reload, rigid arrows, actual attachment transforms, and curved local Z offsets.
- The nine orientation regression tests passed headlessly in ChimeraX 1.7.1 and 1.11, including actual rendered arrow meshes and cached-axis continuation. Existing source-center, Z-offset, command-registration checks passed in 1.11; the straight builder output hashes are unchanged. These are synthetic regression cases, not a visual check of every user STAR file.
- Existing STAR glyphs and attachments are not automatically rebuilt when Python files change. Reopen/reload or rebuild them after updating the bundle to see corrected geometry.

### Z Offset

Current intended behavior:

- Z offset rotates attached copies about each filament's own longitudinal line, not around the cilium bundle centerline
- the user-facing per-line offset remains an incremental angle by filament index; the all-lines offset applies equally to every filament
- derive each point's local filament tangent from neighboring STAR points in the same tomogram/tube (keeping their file order), falling back to its STAR orientation for a single point or coincident neighbors
- on a curved filament, do not reuse one end-to-end chord for every point; straight filaments retain their original line-wise rotation
- never rotate or translate STAR placement centers when changing attachment Z offset; the cilium's center-to-center diameter and global angle must stay fixed, including during JSON attachment replay
- an asymmetric attached model may change the visible outer silhouette as it spins in place; this does not mean the STAR filament positions moved
- rotate around the attached source's own geometric center, including when that center is not its local origin; it must stay on the STAR point at every Z offset
- verify filament centers, source size, and actual in-place rotation in ChimeraX with `runscript tests/verify_attach_z_offset.py` after attachment-transform changes

### Y Rotation

- Y rotation is a separate local orientation adjustment
- it should not collapse into the Z logic

Additional transform notes:

- Y rotation is implemented separately from the macro Z logic
- macro Z logic is intended to stay stable even when local model orientation changes
- when an older JSON enables pre-attach Y rotation, that fixed rotation should happen before the user-facing Attachment Y rotation; the old UI control is no longer visible
- changes in this area should be verified against user expectations for “line-wise” versus “model-local” behavior


## Selector Rules

This is critical. Do not relax these without a user request.

### STAR model selector

- should show STAR models
- should allow manual user selection
- should auto-select the first real STAR model when available
- still keeps a `None` placeholder entry internally at index `0`
- after refresh, if the previous selection no longer exists, it falls back to the first real STAR model when available

### Map/model selector

The map/model selector must **never** read STAR-rendered child content.

It should:

- read top-level imported source models
- read direct archived source models under `CiliaBuilder2 > Maps/Models`
- auto-select the first real source model when available

It should **not**:

- read anything under `CiliaBuilder2 > STAR Models`
- read particle child models such as `Particles (#2.1.1.1)`
- read rendered STAR submodels
- read generated attached output children
- read generated membrane content

Current filter expectations:

- `_is_selector_attach_source()` hard-blocks STAR-group descendants
- `_selector_attach_models()` only lists top-level imported models plus direct archived children under the maps group
- top-level imported models are preferred over deeply nested children
- rendered particle trees are always noise for this selector and must stay filtered out

Selector-change behavior:

- changing either selector clears the live attachment runtime state
- this means clearing:
  - current remembered reattach target ids
  - last attached result pointer
  - ChimeraX selection
- changing a selector does **not** clear the visible selector values or the attachment parameter widgets


## Archiving Behavior

After successful attach, the original source is meant to be archived under:

- `CiliaBuilder2 > Maps/Models`

Archived source models should still be eligible for later reuse.

Important distinction:

- selector should show archived sources as sources
- selector should not show random submodels inside composite trees unless they are the intended direct archived source object

Current user-facing expectation:

- the original imported source should disappear from ordinary use after attach
- the archived version under `Maps/Models` is what remains available for reuse
- once a source is archived under `Maps/Models`, its live ChimeraX id may change, and attachment runtime state must refresh to that archived live id before later reuse


## Origin Reset Rules

There is explicit source-reset logic before attachment and in some restore/tweak flows.

Current intended behavior:

- for volumes:
  - use `volume #x origin 0,0,0`
- for STL-like surface models:
  - reset transform to identity before reuse
- for GLB:
  - do not casually generalize STL reset logic onto GLB without verifying composite-tree behavior

The attach button path should reset the selected source before actual attachment.

Timing expectation:

- source reset should happen after the user presses attach, but before the actual attach operation


## Front / Back Clipping

- Normal attachments must allow ChimeraX `clip front` and `clip back`; the old no-random-cut branch incorrectly set every attached model's `allow_clipping` to false.
- `_apply_attachment_clip_if_needed` enables clipping on the complete drawing tree for new attachments, including GLB children that are Drawings rather than Models. Random-start plane creation remains separate and keeps its existing behavior.
- These are ChimeraX scene-wide planes, not independent per-attachment cut planes. Random-start and manual front/back planes can coexist; `clip model #... false` explicitly exempts a model from scene clipping.
- JSON version 5 has an additive optional `scene_clipping` field containing `planes`, with each scene plane's `name`, world-space `normal`, and world-space `plane_point`.
- Save actual plane geometry, not just the numeric argument from `clip front`/`clip back`: those command offsets depend on the current view, bounds, and existing plane positions.
- Camera-relative near/far planes and the camera pose are not saved by this scene-cut feature; keep the existing `view orient` load behavior.
- Source, STAR, membrane, guide, and attachment records have optional `clipping_state` entries with relative drawing paths, `allow_clipping`, and `clip_cap` when available. Honor explicit `clip model ... false` on restore.
- Refresh volume drawings before reading/restoring drawing permissions so lazy-created volume surfaces are included.
- Clip caps are derived drawings. Exclude `clip_cap_owner` descendants from clipping-state paths and regenerate caps from the restored planes instead of persisting cap meshes.
- Restore per-model flags after recreating each model; attachment flags must be restored after the default attachment/random-cut setup, not before it overwrites them.
- Restore the saved scene planes after sources, STARs, attachments, model grouping, and the final `view orient`. Refresh clip caps and redraw afterward.
- An explicit empty saved plane list means clipping was off. It must remove scene cuts recreated by random-start attachment replay as well as stale front/back planes.
- A missing `scene_clipping` field means legacy JSON: do not clear existing scene cuts or suppress the prior random-start replay behavior.
- Existing JSON files cannot recover manual planes that were never recorded. Reapply the desired cuts and save again with the updated code. Existing live results may need reattachment/reload to remove old disabled-clipping flags.
- Do not modify attachment orientation, GLB anchors, source file paths, volume size, or voxel metadata to implement clipping.
- `_saved_attachment_item_model` must verify a saved ID still identifies a generated attachment with the saved name. A reopened/reparented source may reuse the old attachment ID; treating that source as the result skips actual attachment replay.
- Run `runscript tests/verify_session_clipping.py` in ChimeraX. Eight tests cover ordinary MRC/STL/GLB clipping, real JSON attachment reconstruction/caps, mixed attachments and model exemptions, clip-off versus random cuts, legacy JSON random cuts, tilted scene planes/front-off state, non-Model GLB drawing flags, and upstream's explicit GLB fixed center together with clipping across reload.
- The clipping tests and existing GLB-path, EMDB 2132 center, own-model center, Z-offset, STAR-orientation, and command-registration checks pass together in a fresh headless ChimeraX 1.11. Straight builder output hashes remain unchanged.
- Post-pull verification: all eight clipping tests and the current advertised commands pass in both ChimeraX 1.7.1 and 1.11. The full 1.11 regression run also passes six GLB-path, five GLB-anchor, nine orientation tests, and the center/Z-offset assertion scripts without logged errors. This tests source code, not a rebuilt or installed 0.2.1 wheel.
- In the headless clipping harness, flush a frame before and after closing created model roots. Immediate repeated volume create/delete cycles otherwise can expose ChimeraX's pending VolumeUpdateManager cleanup warning; do not patch the application's global update manager to hide it.


## Volume / Voxel Size Handling

Important current behavior:

- voxel size may be scalar or triple `(x, y, z)`
- isotropic triples like `1.33,1.33,1.33` should be treated as one effective value
- anisotropic triples are normalized sensibly rather than assuming only X matters

The user explicitly asked for code to handle 3-value voxel-size situations.

Current user preference:

- they do **not** want varying source map voxel size to create surprising attachment-size changes
- recent working state should be preserved

Do not reintroduce a hidden forced “set attached voxel size to 1” display hack unless explicitly requested again.

Latest stabilized voxel-size rule:

- attachment path currently keeps volume attachments at the same displayed size as the original source map by using `base_scale = 1.0` for volume sources
- this affects attachment-time scaling behavior only; it is not a mandate to rewrite every map's stored voxel metadata
- hidden manual-tweak voxel-size forcing is still off unless the user explicitly asks for it again
- volume attachments should use ChimeraX's volume grid center as the local anchor, not density center-of-mass or rendered surface bounds
- ordinary surface/GLB attachments use their own geometry center, never a similarly named volume's center
- exception: a GLB exported from a volume must retain that volume's grid-center anchor so both attachments overlap; see the GLB anchor rules below
- this especially applies to `.mrc` file-backed maps and off-center model geometry; verify with `runscript tests/verify_attach_model_center.py`

Important distinction:

- ChimeraX may print isotropic voxel size as `x,y,z`
- code should normalize this internally without assuming it is an error


## Manual Tweak

Manual tweak is hidden from the UI but kept in the code.

Important:

- do not delete manual tweak code
- manual tweak currently supports:
  - map
  - STL/GLB surface
  - PDB-like atomic models
- template path and save path logic remain in `tool.py`

Because it is hidden, changes here should be conservative and usually only done if the user explicitly asks.

Other manual tweak notes:

- manual tweak may open temporary maps such as `molmap` / `onesmask` / resampled outputs
- those temporary models should not leak into ordinary source selectors


## Auto Z-align

The `Auto Z-align map/model` UI is currently hidden/removed from the visible `Save/Load` page.

Current intended behavior:

- it operates on the currently selected source from the dedicated align selector, with fallback to the current map/model selector
- the aligned output path is chosen automatically from the source path/name; the user does not manually browse for a save destination in the normal UI
- automatic output naming should avoid clobbering an existing aligned file by adding a numeric suffix when needed
- for non-volume sources, it aligns the model's detected long axis onto world Z and saves a reopened aligned copy
- for volume sources, it estimates the long axis from density-weighted PCA when possible
- volume alignment should be baked by creating a temporary aligned reference grid, running `volume resample ... onGrid ...`, and then saving the resampled output
- if a temporary reference grid has to be reopened from disk, do not try to add it to the ChimeraX scene twice
- the reopened aligned output should be archived under `Maps/Models`, selected in the UI, and keep the source model's saved color state
- error handling should not try to pop a Qt dialog when running headless without a UI area


## Session JSON Save/Load

Current session JSON behavior is a core stabilized area. Do not widen it casually.

- Only CiliaBuilder2-managed models are serialized. Preserve upstream's outside-model filtering and its own-model (non-recursive) file/fetch identity lookup for composite GLB roots; children inside one file are not separate source records.

### Save

Current saved payload includes:

- `format: "ciliabuilder2_session"`
- `version: 5`
- `ui`
- `selected`
- `attach_sources`
- `generated_star_models`
- `generated_membranes`
- `generated_marker_paths`
- `attachments`
- `model_structure`
- `scene_clipping` (optional scene-plane state; absent in older version-5 files)

Current selected-state expectations:

- `selected` now also preserves the microtubule `Continue from STAR` selector state
- internal undo/redo snapshots may additionally carry transient selector state for geometric drawing and auto-Z controls, but that extra state is not a required public JSON contract

### Save rules by source type

#### Normal file-backed models

- save absolute path
- when possible, load by absolute path first before restoring dependent session state

#### Fetchable models

- save `fetch_type`
- save `fetch_id`
- load should prefer fetch id before fuzzy path/name fallback

#### `glb`, `gltf`, and compressed GLB/GLTF

Current intended save behavior:

- file-backed GLB/GLTF inputs now keep their original absolute file path in JSON; do not export another session-named copy when the path is known
- this rule supersedes the earlier always-copy GLB/GLTF behavior
- both `attach_sources[].path` and `attachments[].map_path` should reference that same original file
- loading `name.glb.gz` displays the root as `name.glb`; the actual recorded path retains `.glb.gz` and is opened directly on restore
- keep all GLB child nodes; changing the displayed root name must not flatten the composite or discard meshes/materials
- user-assigned custom model names should not be replaced when recording paths
- source tracking starts with the CiliaBuilder tool and uses ChimeraX command/model triggers, not a replaced file opener or generic JSON provider
- record exact input paths on successful opens, including paths with spaces and literal brackets; retain them through archive/reparent and manual rename
- models opened before tracking may recover a path from a unique file-history match; prefer the exact compressed filename and never guess between same-name files in different directories
- `_cb_original_source_path` takes priority over temporary exports and older session-copy aliases in both UI/session and attachment-backend source lookup
- in-memory GLB geometry without any recoverable source path retains automatic export as a fallback; that first saved file can then be referenced on later JSON saves
- source colors still persist separately in `color_state`; ordinary JSON save no longer bakes live GLB geometry edits into a new asset
- existing original files are never overwritten, renamed, or decompressed into replacement files by JSON save
- saved-session path aliases and tree-child paths remain supported for older JSON packages
- verify `runscript tests/verify_glb_source_paths.py` for compressed/plain names, actual JSON paths, no extra asset files, same-basename sources, history recovery, reopening, and reattachment of a composite GLB
- CiliaBuilder's own GLB writes must use `write_gltf(..., center=False)` (or `save ... center false`), including drawing export, live session fallback export, temporary attachment fallback export, and hidden auto-alignment export
- the six source-path regression tests include off-origin/rotated exports and temporary-copy geometry preservation; these pass headlessly in ChimeraX 1.7.1 and 1.11

#### Volume-derived GLB attachment centers

- `save test.glb center false` preserves geometry coordinates but native ChimeraX does not preserve the volume grid center in the file; neither the GLB bounding-box center nor a glTF node translation is necessarily the correct volume pivot
- preserve volume grid anchors and existing volume scale/voxel metadata; do not fix the mismatch by moving STAR points, changing Euler angles, or recentering every volume on its density
- `glb_anchor.py` stores an optional finite three-number anchor in GLB JSON `extras.ciliabuilder2.volume_grid_anchor`; mesh buffers, node transforms, materials, and composite children must remain unchanged
- successful GLB `save` commands while CiliaBuilder's source tracker is active record this metadata when the saved geometry matches an open source volume (or an already identified volume-derived GLB)
- this is a narrow successful-save hook, not a replacement ChimeraX saver/opener, restart/install patch, or a global JSON provider; file-dialog parsing must never be invoked by the hook
- programmatic CiliaBuilder exports preserve an already known anchor, transforming it into the exported scene coordinates
- without an explicit user fixed center, GLB/GLB.GZ attachment first uses retained/embedded anchor metadata
- an older export without metadata can recover the pivot from a matching live volume or identified GLB: verify all triangle indices and every transformed vertex within float32 tolerance, not just names, bounds, or a vertex sample
- match the full mesh collection, including nested-node transforms; do not pick one leaf of a composite, or match an instanced attachment output as if it were a source
- refresh source volume drawings before matching, because origin reset can leave hidden source surface coordinates stale
- exclude generated attached trees from reference candidates; if matching sources imply different grid centers, do not guess
- ordinary/unmatched GLBs and STL retain their prior own-geometry-center fallback; STL must never acquire this volume matching behavior
- old standalone GLBs with no metadata and no matching source cannot reveal a missing grid center; keep the matching original map open once or re-export with CiliaBuilder running
- JSON also stores an optional `attach_sources[].glb_volume_anchor` and restores it before attachment replay; old JSON without the field remains supported
- JSON save must not rewrite the original GLB to add metadata or make another asset copy; for old files the center belongs in JSON instead
- verified with `CB_TEST_EMDB_2132=1` and ChimeraX `runscript tests/verify_glb_volume_anchor.py`: actual EMDB 2132 export, two identical nine-filament/two-layer builds, all 18 placements compared vertex-by-vertex at Z offsets 0/43 and local Y rotation 21
- EMDB 2132 grid center is `(721.375,721.375,721.375)` whereas its level-1 surface bounds center is about `(870.121,629.941,721.375)`; that discrepancy caused the old mismatch
- the five center tests pass in ChimeraX 1.11: EMDB overlap (maximum coordinate difference about `0.00003` angstrom), anisotropic/nonzero-origin map export, compressed-file reopen without source volume, GLB re-export, legacy JSON restore without modifying original files, unrelated-mesh rejection, and conflicting-center rejection
- rerun existing `verify_attach_model_center.py`, `verify_attach_z_offset.py`, `verify_star_rotations.py`, `verify_glb_source_paths.py`, and `verify_bundle_commands.py` after this logic changes

#### `stl`

- STL retains automatic copying beside the JSON, using a different filename and storing the copy's absolute path
- preserve the original STL file

### Color persistence

Current intended save/load behavior:

- saved attach sources, generated STAR models, generated membranes, generated marker-path/primitive models, and generated attachments all persist `color_state`
- session restore reapplies that `color_state` after reopening the saved model tree
- this color-state replay is the main safeguard for GLB recolors, because a raw ChimeraX GLB reopen may still lose user recolors by itself

### Load

Current intended load order:

1. open/restore source maps/models first
2. restore generated STAR models
3. restore generated membranes
4. restore generated marker paths
5. replay attachments afterward
6. restore the saved CiliaBuilder model hierarchy/wrapper structure so `Maps`, `STAR Models`, `Membrane`, and any saved wrapper groups are reallocated like the pre-save tree
7. `view orient`
8. restore saved scene clipping planes and regenerate clip caps, when `scene_clipping` is present

If a saved path is missing:

- ask the user for a replacement file
- use that replacement to continue restore
- the replacement should then be treated as the effective source for the remainder of restore

Current important attachment replay rule:

- replay should prefer the exact restored source model objects opened during load
- not a later fuzzy scene search that can hit the wrong GLB child or wrapper
- saved JSON should preserve the CiliaBuilder-owned model tree shape, not just the individual models, so wrapper groups that existed before save do not get flattened into many separate direct children after load
- `view orient` is expected after load completes


## Attachment Replay on JSON Load

This is another stabilized area.

Current intended behavior:

- fetched-by-id sources can reopen and reattach
- file-backed `mrc`, `stl`, `glb` sources should also reopen and auto-attach after load
- replay stores and uses:
  - source ref / source session id
  - star ref / star session id
  - source path
  - fetch info when relevant

Do not change replay order or source matching broadly unless the user reports a specific restore failure.

Attachment replay details worth preserving:

- replay should zero/reset volume origin before reuse where appropriate
- replay should reapply stored line rotation and Y rotation
- older saved `x_movement` values should be ignored; attachment replay now always uses zero X movement
- replay should also preserve whether the advanced pre-attach 90-degree Y rotation was enabled for that attachment
- replay should restore display/hide state of source and STAR models as closely as practical
- for restored GLB sources, the attachment copy path must prefer reopening a real saved GLB path from the restored tree or `_cb_saved_session_paths` aliases before falling back to temporary live-model export; otherwise replay can produce an empty GLB copy


## CellPACK / APR / CPR Export

### Original Built-In Membrane Preview (2026-10-30, v1 Compatibility)

The v2 particle-only interface below supersedes the original UI/count/composition
and visible-guide rules in this historical subsection. Keep v1 JSON results and
the five-class `SurfacePacker` API compatible; do not silently convert old packs.

- User explicitly chose **built-in packing preview and export, no extra installation**. Do not add an external Python/engine dependency or automatic package installation. The separate upstream-engine experiment was removed before delivery.
- `Build > Membrane > cellPACK-style membrane...` is the new visible entry point. The existing whole-scene `Load cellPACK` and `Export cellPACK package` buttons remain hidden; their implementation is unchanged.
- Target selection reuses the membrane-distortion target rule (selected generated membrane first, otherwise latest). The dialog displays the target name/ID and keeps that specific target during the run. No membrane means log an instruction to build one; never create geometry implicitly.
- The dialog exposes requested count (default 5000, limit 10000), base ingredient radius (default min(12, 0.3 * thickness), clamped to at least 0.1 Angstrom), and seed (default 1). Composition widgets remain hidden. Reuse the existing five class definitions, colors, radius multipliers, and normalized hidden percentages from `_CellPackExporter`.
- Packing is an explicit **local cellPACK-style approximation**, not upstream cellPACK. Spheres are illustrative class proxies, not atomic proteins/lipids or a simulation-ready membrane. Preserve that distinction in UI, exports and documentation.
- Unlike the older ideal-cylinder exporter, this new preview samples the actual generated mesh by triangle area, with barycentric coordinates. Both wall surfaces, end rims, distortion and any dome are included; no membrane-generation formula is changed. No radius expansion, map fitting, STAR changes or attachment changes occur.
- Larger-radius classes are packed first, then smaller lipids. Count quotas use normalized weights and largest-remainder rounding. A 3D spatial hash checks true Euclidean sphere separation across all classes/surfaces, with a 1%-of-min-radius gap. Maximum 50 attempts per requested particle (minimum 200 per class) bounds dense/saturated runs; partial counts are reported honestly.
- NumPy's seeded generator consumes three random values per attempt; results must not depend on timer batch size. The same mesh/settings/seed reproduces a preview within the supported runtime. Completed positions/normals are stored, so JSON does not depend on regenerating randomness.
- Packing advances in 256-attempt Qt timer batches without blocking the full run or requiring threads/processes. Cancellation/closing the dialog leaves the old scene/history unchanged. Do not call QApplication.processEvents inside packing to create re-entrant scene changes.
- Completion validates the target is live and its mesh digest unchanged. Capture history at completion, not at start, because other actions may happen during a run. A changed/deleted target must not receive stale results.
- Preview is an ordinary model subtree named `cellPACK-style particles` under the generated membrane, with one instanced sphere Surface per non-empty ingredient class. Keep membrane mesh, ID, position, color, display and clipping unchanged; descendants remain excluded from attachment selectors through the existing membrane-ancestor filter.
- `state.cellpack_packing` embeds versioned, JSON-safe positions/normals/radii/colors/counts/seed/engine identity and mesh digest. Global Undo/Redo and existing membrane JSON restore reuse this state without running the packer. Restore particle geometry before applying saved color/clipping state.
- Rebuilding a membrane clears obsolete particle state and preview; Undo restores the previous mesh and packing together. Invalid saved packing must warn and leave the membrane restored without the bad preview rather than breaking the whole load.
- `Export package...` explicitly exports the existing preview, not a fresh random run. It creates a unique `membrane_cellpack_*` subfolder in the chosen directory. No source model save dialog or external engine is involved.
- Files: `membrane.cpr.json`, `membrane.apr.json`, `packing.json`, `membrane_particles.cif`, `README.txt`, `meshes/`, `ingredients/`. APR/CPR asset paths are relative; numeric filenames avoid interpreting JSON labels as filesystem paths. Never overwrite an existing populated package directory.
- Export only the selected membrane and its particles. APR/CIF use its current scene transform; stored preview coordinates are membrane-local so they move with the parent. APR carries actual sphere meshes/sizes/colors and surface-normal orientations. CIF is a pseudo-site representation (one site per sphere), not atomistic reconstruction; use the built-in UNK component to avoid network CCD lookups.
- Preserve the old `cellpack_export.py` implementation. The new path reuses only ingredient definitions, mesh/ingredient writing and CIF serialization helpers, not its whole-scene collection or cylinder packing routine.
- Regression: `runscript tests/verify_membrane_cellpack.py` checks seeded/batch-independent placement, class quotas, collision exclusion, actual distorted/domed surface sampling, saturation, validation, instancing/selector filtering, JSON and Undo/Redo, stale result rejection, portable APR/CIF reopen without network, default 5000-particle packing, and real Qt dialog preview/export/cancel.
- Validation: all 13 new tests pass in GUI ChimeraX 1.7.1 and 1.11 without any additional Python packages. All eight existing membrane distortion tests also pass in GUI. Existing headless 1.11 clipping, GLB source-path/anchor, attachment-center/Z-offset, STAR-orientation and command checks pass; the optional EMDB download case was not rerun for this change. Straight-builder output hashes remain unchanged.

### Particle-Only Membrane Packing (2026-10-30, v2)

The v3 dense-placement rules below supersede this subsection's random placement,
55% lipid target, all-sphere exclusion and version-2 output rules. All other
protein, UI, instancing, JSON, grouping, undo and export requirements still apply.

- User requested particles alone to form the visible membrane, a protein ratio, and a PDB-number input. Keep the no-extra-installation built-in workflow; do not label this as execution of the upstream cellPACK engine or an atomistic/biologically validated bilayer.
- Entry remains `Build > Membrane > cellPACK-style membrane...`. Dialog now offers `Protein surface coverage (%)`, `Protein PDB ID`, `PDB outward axis`, lipid bead radius, maximum particles and seed; action is `Pack membrane`. Existing hidden composition fields remain hidden and unchanged. Default protein percentage is 0 (lipid-only, no network), radius is half the stored wall thickness, maximum 50,000, seed 1. Reopening restores packed settings and cached protein mesh from that membrane.
- Percentage is nominal protein projected-bounding-disk area divided by the actual outer leaflet area, NOT a percentage of particle count. Report achieved nominal coverage, partial counts, particle-count limiting and protein-render limiting. Do not promise a requested percentage always fits.
- `MembraneFillPacker` uses actual distorted/domed mesh areas. `cmd.buildmembrane_surface` adds private outer/inner face masks without changing vertices, triangles, normals or any of the nine distortion terms. Flat end rims are not packing sites. Proteins sample outer faces only, shift inward by half stored thickness, and align their selected PDB axis with the outward normal. Lipid bead centers lie on both leaflet surfaces, so beads extend to either side of those surfaces; they are coarse proxies, not lipid atomic coordinates.
- Protein quotas are floor(outer area * fraction / projected bounding disk area). Lipid quotas estimate 0.55 * both-leaflet area * (1-fraction) / bead disk area. This is random sequential adsorption, not gap-free surface tiling. Protein-first packing uses conservative whole-protein bounding-sphere exclusion against all particles. A 1%-minimum-radius gap and original bounded attempt counts remain in force. The maximum count proportionally reduces quotas; protein geometry also has a ten-million-instanced-triangle safety budget. Never allocate a separate AtomicStructure per protein placement.
- `src/membrane_protein.py` validates four-character PDB IDs and fetches RCSB mmCIF via ChimeraX's standard cached fetch helper. Fetching and the initial mesh calculation are synchronous before the cancellable timer starts (Cancel is disabled during preparation). Fetch errors/invalid IDs leave existing scene/history unchanged. No arbitrary commands/URLs are constructed from user input.
- Use protein atoms only, first deposited model, no implicit biological-assembly expansion. Temporary structures are opened without session registration and always deleted, never archived as attach sources. Build one 6-Angstrom Gaussian surface (3-Angstrom grid), center its bounds, and rigidly align the user-selected +/-X/Y/Z axis to local Z. Never rescale the protein. PDB coordinates do not define transmembrane orientation; do not infer a biologically valid axis/embedding from the ID alone. Limits: 50,000 protein atoms, 600-Angstrom maximum coordinate extent, 50,000 mesh vertices / 100,000 triangles.
- New packing uses `algorithm_version=2`, `particle_only=true` inside the existing namespaced v1-schema envelope for backwards compatibility. Embed protein mesh/metadata ONCE alongside positions, normals, coverage settings and the guide's pre-packing triangle mask. Restoring JSON/Undo/Redo must not fetch the PDB or rerun packing. Validation covers geometry indices/bounds, counts, normals, coverage and rendering budget; invalid previews still warn without breaking membrane restore.
- Hide ONLY the membrane's own triangles with an all-false triangle mask; never set parent display false, which would hide the particles too. Preserve/restore the pre-packing mask on invalidation/clear. Repacking must retain that original mask, not save the already-hidden mask as the original. Keep membrane ID, transform, colors, clipping and group; particle descendants remain excluded from attach selectors. Undo restores guide visibility, Redo restores particles; distortion clears stale packing and reveals the guide until repacked.
- One instanced Surface per ingredient. Protein instance matrices use the shared proper vector-alignment rotation. Export must compose the FULL membrane scene rotation with each local protein rotation; deriving a new basis from world normals alone loses the protein's azimuth. APR gets actual protein meshes and lipid spheres, no visible `rep_file` shell; compartment `geom` remains available as hidden geometry. Existing v1 export keeps its prior visible-guide behavior.
- Export filenames/relative-path portability and unique package folders are unchanged. `membrane_particles.cif` intentionally remains explicit pseudo-sites, one center per particle, with UNK components; it is NOT an atomic-protein CIF. Package README and UI/help distinguish APR protein meshes from CIF centers. No changes to legacy whole-scene export, attachment, GLB, pixel sizes, STAR generation or session source-path logic.
- Regression script `tests/verify_membrane_cellpack.py` now also covers 0/100/intermediate ratios, collision exclusion, particle-only visibility, original mask preservation on repack/clear, protein instance rotations, full scene transforms in APR, offline JSON/Undo/Redo, distortion invalidation, invalid inputs, real RCSB 1AFO fetching, no temporary source leakage, and GUI input/cached-template behavior. Existing sphere-preview regression cases remain.
- Validation: all 21 packing tests and all 8 membrane-distortion tests pass in normal GUI ChimeraX 1.7.1 and 1.11. The 1.11 headless STAR-orientation, attachment-center/Z-offset, clipping, GLB path/anchor and command checks pass (optional EMDB download skipped); straight-builder output hash test is unchanged. A rendered PDB 1AFO test confirms particle-only appearance. Default-sized domed membrane (length 3000, diameter 2700, thickness 40), radius-20 lipid beads and 20% protein target packed 21,798 / 27,330 sites with 19.998% nominal protein coverage in approximately 20 seconds on this machine. That is a measured example, not a runtime/coverage guarantee. Initial PDB retrieval requires network/cache; restored JSON and relocated APR/CIF were tested with fetching forbidden.

### Dense Instanced Membrane Packing (2026-10-30, v3, Historical)

The v4 recipe workflow below supersedes these row-placement/UI rules. Keep the
v3 Python API for compatibility, but do not route the interactive dialog to it.

- User requested fewer gaps and much faster packing, reusing one element with built-in duplication. Continue using one shared Surface mesh per ingredient and ChimeraX `Places` instancing; do not copy atomic structures or merge repeated vertices into one enormous mesh. The performance problem was random rejection sampling, not mesh duplication.
- `MembraneFillPacker` now produces algorithm version 3. Keep the v1 schema envelope, accept algorithm versions 2 and 3 for particle-only JSON, and retain legacy five-class `SurfacePacker` behavior. Restore old positions exactly without rerunning packing; users must press `Pack membrane` again to opt into a denser layout. No source-path, attachment, STAR, pixel-size, membrane-distortion or legacy whole-scene exporter changes.
- `src/membrane_lattice.py` slices the actual mesh into closed cross-section polylines. It recovers the existing body's staggered rings, inner/outer dome rings and pole from saved dimensions and validates vertex count. Compare equal-angle points for meridional arc lengths, not staggered vertex indices. Intersect the actual triangles, split the angular seam, and sample by polyline arc length so sites and normals lie on real distorted faces. Do not substitute an ideal cylinder or bilinear patch that drifts off the mesh. Support tilted axes, domes and unequal inner/outer dome heights. End rims remain excluded.
- Lipid row pitch is 2.02 times bead radius, with approximately sqrt(3)/2 row-height spacing and half-cell staggering. Inner leaflet phase is shifted by half a cell. Generate one primary pass, then two fixed shifted gap-filling passes; process primary sites first. Keep row order during greedy collision rejection: randomizing this order creates extra holes. If an accepted set exceeds its quota, choose a seeded uniform subset afterward so the particle limit does not fill only one end of the membrane.
- Lipid quotas now estimate 90% of remaining leaflet area instead of 55%. This is a target, not an achieved-coverage guarantee. Protein ratio remains nominal projected bounding-disk coverage; protein candidates use coarser area-derived rows, still shifted inward by half wall thickness. Whole-protein radius, PDB geometry, center and selected outward axis are unchanged.
- Native `scipy.spatial.cKDTree` (already bundled in tested ChimeraX versions) computes fixed-site conflicts, avoiding Python neighbor searches on millions of random attempts. Lipid/lipid and protein/protein separation still use spheres and the prior 1%-minimum-radius gap. For lipid/protein pairs, broad sphere bounds are refined against the protein's rotated local bounding box, which encloses its entire mesh. Compute distance from the bead center to that box; reject if less than bead radius plus gap. Check ALL broad-phase protein neighbors, not just the closest center. This permits tight safe placements beside long narrow proteins without pretending the whole enclosing sphere is occupied.
- Preserve the 50,000 accepted-particle and ten-million-protein-triangle limits. Bound candidate allocation at 200,000 per ingredient, proportionally increasing site pitch when necessary; reject unsafe topology/candidate counts rather than allocating indefinitely. Native conflict graphs are limited to two million pairs before constructing adjacency arrays; box neighbor queries use 2048-site blocks and the same pair guard. Store `placement_method`, `candidate_count`, and `protein_lipid_exclusion` with v3 results as diagnostic metadata, without changing exported mesh geometry.
- Preparation and accepted-site loops yield bounded units; the dialog consumes them for about 6 ms per timer callback instead of paying timer/UI overhead for every row. Native batch queries may take longer than this soft budget. No processEvents calls during packing. Cancel closes the suspended generator and releases candidate/conflict arrays; a cancelled packer must not return a partial result or resume. Existing scene/history stay untouched until normal completion. Initial PDB fetch/surface preparation remains synchronous before packing starts.
- README and in-app tool help explain denser repeated rows, shared-mesh duplication, tighter conservative protein boxes, limits, and repacking old results. Keep "some planned sites were excluded" wording instead of falsely claiming random surface saturation. The smooth guide stays hidden after success; particle-only display, clipping, colors, JSON/Undo/Redo and relative APR/CIF export behavior are unchanged.
- Tests add flat-leaflet coverage above 80%, bounded candidate work, exactly one shared lipid mesh, sites/normals on the distorted/domed mesh, per-type sphere exclusion plus oriented protein-box exclusion, a non-nearest-protein collision case, v2 restoration without repacking, and explicit cancellation cleanup. Existing seed/batch-independence, real PDB, GUI, JSON, export, mask and distortion tests remain.
- Validation: all 26 packing tests and all 8 membrane-distortion tests pass in normal GUI ChimeraX 1.7.1 and 1.11; compile and straight-builder output hash checks pass. Controlled default-size comparison (length 3000, diameter 2700, thickness 40, distortion .6/seed 1, dome, lipid radius 20, PDB 1AFO, 20% protein): old random placement 21,798 particles in 20.24 s, new rows/box refinement 28,600 particles in 0.58 s, both 19.998% nominal protein coverage. Lipid-only comparison: 28,601 particles in 17.17 s versus 43,300 in 0.51 s. These timings cover placement calculation, not fetching/rendering. A real dialog run with a cached/prepared PDB template completed the 28,600-particle pack and scene/history update in 1.31 s on this machine. Performance is hardware/geometry dependent. Before/after renders were inspected; the guide remains hidden and the particle layer is visibly denser.

### Randomized Ingredient Recipes (2026-10-30, v4)

The v5 small-radius correction below supersedes the fixed 50,000 default budget
and constant search effort. Ingredient semantics and geometric rules remain.

- User rejected global patterned rows and explicitly chose "build my own" rather than installing upstream cellPACK. Keep the no-extra-installation independent implementation. `RecipePacker` in `src/membrane_recipe.py` is the active dialog backend; legacy `SurfacePacker` and `MembraneFillPacker` remain compatible and are not the active GUI algorithm.
- Research: Johnson et al., Nature Methods 12, 85-91 (2015), https://doi.org/10.1038/nmeth.3204, specifically ingredient priority and neighbor-biased closePacking; official source https://github.com/mesoscope/cellpack. Our continuous triangle/contact-front implementation is an adaptation, NOT their distance-grid engine. Never claim globally closest/optimal packing, a validated bilayer, or atomic lipid structures.
- Dialog remains under Build > Membrane > cellPACK-style membrane. It now has an ingredient table: Use, Type, Name, Amount (%), Radius (A), PDB ID, Outward axis, Leaflet, Remove; Add lipid / Add protein / Add other bead buttons. Up to 20 entries. Types are selected by the Add buttons, labels are editable, and disabled or zero-amount entries are not fetched/packed. Empty recipes and duplicate keys are rejected. No hidden ingredient is added. Existing hidden composition widgets elsewhere remain hidden and unchanged.
- Initial recipe: enabled lipid beads with radius half stored wall thickness and amount 100; disabled protein entry with amount 20 and no PDB ID. Maximum particles 50,000, seed 1. Each protein has its own PDB ID and +/-X/Y/Z axis. Lipid/other bead radii are editable; protein radius comes from its prepared mesh and is never scaled. Other components (e.g. named cholesterol proxies) are beads, not automatically supplied atomic lipid structures.
- Protein amount is nominal projected-bounding-disk coverage of the outer leaflet, not particle count; all enabled protein amounts must sum to <=100. Protein anchor remains half wall thickness inward from an actual outer face, with its selected axis aligned to that face normal. Each placement gets a seeded random spin around that normal, stored in radians. The PDB ID alone does not define transmembrane orientation.
- Bead amount is a relative AREA weight among enabled non-protein entries available on each leaflet. Reserve the summed protein coverage first, then divide the remaining area proportionally; 70/30 weights mean a 70:30 area split, not count split. Targets use 90% nominal coverage, not a guarantee. Beads may use outer, inner or both leaflets. Disabling all beads makes proteins only; disabling all proteins requires no network. Flat annular rims remain excluded.
- MeshLeaflet samples faces by actual area and projects against local neighboring triangles, including edges, returning real face positions/normals. No ideal cylinder or row coordinates are used. Random seeds initialize independent fronts. Bounded randomized near-contact proposals favor two-neighbor sites, then one-neighbor sites, then new seeds. Intersect exclusion spheres with the local face plane; only reproject across a face boundary, rather than shortening separation by blindly projecting planar circle positions. This is a local surface construction, not an exact global geodesic solver. Tilted axes, nine-wave distortion and domes retain existing geometry formulas.
- Ingredients with protein geometry go first, then larger beads. Native SciPy cKDTree queries and conflict graphs reject collisions in 3D across BOTH leaflets and ALL ingredient types. Bead/bead and protein/protein exclusion use spheres; bead/protein exclusion refines each protein's sphere with its oriented enclosing box, including its random spin. Conservative protein bounds may leave space around irregular proteins; do not pretend to use atom-level collision detection. Same-class minimum gap is 0.001 radius; unlike-class sphere gap is 0.001 times the smaller radius. No accepted overlap is introduced to claim greater density.
- Fixed seed and settings produce batch-independent results. Random starts and front/neighbor choices prevent global row patterns; local dense coordination is expected. 240 rounds maximum per ingredient/leaflet; stop after five empty rounds. Fronts sample up to 512 active anchors, retire after three visits, and may revisit when exhausted. Candidate batches are bounded (MAX_BATCH=8192), not an unbounded all-pairs allocation. The existing two-million-conflict guard remains. Actual achieved counts and protein coverage, not just requested ratios, appear after packing.
- Initial seed count adapts to the requested nominal area fraction: below 30%, try twice the quota as uniform samples; below 70%, seed 10% of the quota; otherwise seed 0.2%, each bounded to 8-8192 candidates. This avoids sparse/minority ingredients growing as isolated macroscopic patches while reducing grain-boundary gaps in dense layers. Later rounds add four fresh random seeds alongside neighbor proposals. These are geometric heuristics, not a biological clustering model.
- Mixed bead recipes override initial seeding to 10% per task and interleave ingredient/leaflet generators in seeded random round order after proteins. A single bead type keeps the sequential leaflet path. For mixed beads, contact proposals use ALL existing bead types on the same leaflet with their individual radii, rather than only like-type neighbors; intersect spheres of radii (new radius + each neighbor radius). This prevents avoidable holes and unintended species bands. The interleaved child generators must also close on cancellation. Existing conservative collision checks still apply to every accepted point across both leaflets.
- Within each mixed-bead cycle, give each ingredient 1-4 attempts based on rounded radius/minimum-bead-radius. Favoring larger beads prevents small ones from prematurely blocking all large sites; cycle order remains seeded random, not a lattice. Cancel also clears the auxiliary cross-species site cache. Tests retain explicit mixed-size density and angular-distribution checks and verify child-generator cleanup, not only the outer generator.
- When a global particle cap reduces quotas and can still represent every positive ingredient/leaflet task, reserve at least one for each before proportionally allocating the remainder. Do not silently round a user-selected rare protein to zero merely because its much more numerous beads dominate the quota. If the original area or triangle budget cannot support one protein, its zero achieved/requested count remains explicitly reported; do not violate size or rendering limits to create it.
- Ingredient-table buttons must not be QDialog auto-default buttons: Enter while editing a number must not add an ingredient, remove a row, start packing or export accidentally. The type column is at least 120 logical pixels wide so Protein (PDB) is not clipped. Add/remove/enable rows are persisted and restored from the recipe, not inferred from colors or names.
- Preserve 50,000 accepted particles and ten-million-instanced-protein-triangle budgets. Reduce protein quotas for triangle budget, then proportionally scale all quotas for the total count cap using largest-remainder rounding, including a maximum count of 1. Limit/count reductions are reported. Cancel closes the generator; no partial result or scene/history changes. Qt timer work keeps the prior completion-only transaction, although each native query/projection batch can exceed the 6ms soft timer budget. Preparation/fetch remains synchronous with Cancel disabled until packing starts.
- Cache each distinct PDB ID/outward-axis mesh once in the dialog and save it once in `templates`. Fetch only enabled positive-amount proteins, reuse cached templates, delete temporary opened atomic models, and never create a separate AtomicStructure per placement. Existing PDB atom/extent/mesh safety limits and 6-Angstrom Gaussian surface representation remain unchanged. Protein templates are first deposited protein models, not inferred biological assemblies.
- New results use algorithm_version=4 within the existing v1 schema, with `recipe`, `templates`, group `template_key`, group `spins`, leaflet/role metadata, areas, seed, requested/actual counts and placement_method=random-neighbor-close-packing. Validate recipe/group correspondence, IDs/axes/template radii, finite spin arrays, count limits, area/coverage consistency and total render budget. Disabled entries persist in the recipe so reopening the dialog preserves choices; they do not create groups or templates.
- `group_protein` handles v4 template references and older single-protein results without rewriting attachment or session logic. `instance_matrices(..., spins=None)` preserves old transforms exactly; v4 adds local-Z spin before normal alignment. APR rotations compose the full scene rotation with those local matrices. JSON/Undo/Redo embed recipes, meshes, positions and spins and restore offline, without fetching/repacking. Existing v1/v2/v3 positions remain unchanged on load; only an explicit Pack membrane applies the new algorithm.
- Preserve one shared instanced Surface per non-empty ingredient, hidden guide triangles (not parent display), original guide masks, clipping, model hierarchy, colors, source-selector exclusion, stale-mesh rejection and distortion invalidation. APR retains actual protein meshes; CIF remains particle centers, not replicated protein atoms. Export paths remain relative in unique directories; no changes to the old whole-scene exporter, attachments, STARs, pixel sizes, GLB or general session source paths.
- Tests: existing `verify_membrane_cellpack.py` retains legacy v1-v3 packing tests and now exercises the new dialog; `verify_membrane_recipe.py` covers density/no-global-rows, deterministic seeds/batching, face-constrained coordinates/normals, multiple templates and bead species, cross-species exclusions, spin-correct export, offline JSON/Undo/Redo, corrupted inputs, single-particle cap, inner-only packing, real PDB 1AFO+4HHB, cancellation and the add/remove/enable GUI. Keep `verify_membrane_distortion.py` passing too. README and HTML tool help document these active rules rather than the superseded row algorithm.
- Final validation: all 45 GUI tests (26 legacy/packing, 11 recipe, 8 distortion) pass in ChimeraX 1.11 and 1.7.1. The distortion GUI test now explicitly activates its Qt window before testing focus-loss commits; scripted launches may otherwise leave focus in another Mac app and give a false failure. Production distortion code is unchanged. Compile, straight-builder output hashes and diff whitespace checks pass. Headless 1.11 attachment-center/Z-offset, STAR rotations, clipping, GLB source/anchor and command tests pass; the optional EMDB download anchor case was skipped.
- Measured examples, not density/runtime guarantees: single radius-20 bead type on the default-size distorted/domed membrane (length 3000, diameter 2700, thickness 40, distortion .6/seed 1) placed 42,865 of 50,000 targets in about 10.2 seconds, nominal two-leaflet disk-area coverage 74.5%. A smaller length-600/diameter-400 membrane with PDB 1AFO at 15%, radius-10 lipid beads and radius-6 other beads at area weights 100:25 placed 5,141 particles in about 2.5 seconds after its template was prepared. Random fronts are slower than the rejected fixed lattice; do not present the old v3 half-second benchmark as current performance. Inspected both the real Qt table and a rendered mixed-particle membrane. Instancing and all coordinates are non-overlapping within the stated conservative collision proxies, not atomically validated packing.

### Small-Radius Dense-Fill Budget (2026-10-30, v5)

The v6 protein-gap correction below supersedes box-only bead/protein exclusion.
The automatic/manual density-budget behavior and limits remain unchanged.

- User reported sparse packing with radius 10 Angstroms. Reproduced on the default length-3000/diameter-2700/thickness-40 distorted domed membrane: area-derived radius-10 target is about 207,234 beads, but v4 proportionally reduced it to 50,000, yielding only 21.7% nominal disk-area coverage. Radius 5 fell to 5.4%. This was count-limited thinning, not bead scaling, missing meshes, or an attachment problem.
- `RecipePacker(..., max_particles=None)` now defaults to automatic area-based budgeting. Halving bead radius approximately quadruples the target. The dialog has a checked-by-default `Automatic dense-fill budget` checkbox; the `Manual preview limit` field is enabled only when unchecked. Existing pre-v5 layouts stay unchanged on load, but opening their dialog defaults to automatic budgeting for an explicit repack. V5 saves/restores the chosen automatic/manual mode and manual cap.
- New recipe results are algorithm_version=5 within the unchanged v1 packing schema. Persist `automatic_particle_budget` and `area_target_count` alongside existing settings. Both v4 and v5 retain recipe/templates/spins; older v1-v4 results still validate and restore without repacking. Do not change general session JSON, source paths, attachment, GLB, STAR, voxel sizes, or membrane distortion.
- `MAX_RECIPE_PARTICLES=1,000,000` is a v5-only safety ceiling; legacy `MAX_FILL_PARTICLES=50,000` and v1-v3 APIs retain their behavior. Automatic targets exceeding the new ceiling fail before placement/scene mutation with actionable advice to enlarge beads or reduce membrane area. Never silently downsample an automatic fill, enlarge the requested bead radius, or accept overlaps to claim higher density. The ten-million protein-triangle cap remains separate and reported.
- Explicit manual limits still proportionally allocate quotas and reserve nonzero ingredient/leaflet representation when possible. During packing and on completion, label a reduced target `SPARSE PREVIEW` and show the area-based target; do not present reaching a low manual count as dense filling. Manual cap exists for quick previews, not as the default density control. Large populations require more time/memory; shared mesh instancing is unchanged.
- Search rounds now grow as `240 + task_quota // 100` per ingredient/leaflet rather than stopping at a constant 240. Existing saturation stop, bounded proposal batches, random contacts, gap filling, cross-leaflet collision checks and mixed-ingredient scheduling remain. This keeps small-radius populations from exhausting search effort solely because they need more sites.
- `GrowingSites` maintains preallocated append-only point/normal arrays and a cached cKDTree with a freshly indexed tail. Rebuild the bulk tree when the tail reaches max(512, min(4096, indexed_count//4)); combine exact nearest-neighbor results from both trees. Never ignore pending sites in collision/neighbor checks. This avoids repeatedly converting whole growing Python lists and rebuilding all trees on every iteration. Cancellation releases these caches and mixed-ingredient child generators.
- Protein collision trees, mesh bounds and spin-aware rotations are cached per group/accepted count. Protein placement finishes before beads, so do not recompute every protein rotation for every bead batch. Invalidate on count changes and clear on cancellation; never change the conservative collision geometry. A regression checks one calculation per protein group for the mixed recipe.
- Regression coverage now includes the full default-size radius-10 automatic fill (>50,000 actual placements), independent gap probes on both leaflets, collision rejection, large JSON/instanced restore, inverse-square budget scaling, automatic ceiling failures without scene changes, v4 compatibility, incremental-index comparisons against a fresh full tree, and actual GUI automatic/manual transitions and warning text. Preserve all preexisting recipe/legacy packing/distortion tests.
- Validation: all 48 membrane GUI tests (26 legacy/packing, 14 recipe, 8 distortion) pass in ChimeraX 1.11 and 1.7.1, including the cached-protein-bound regression. Compile, whitespace checks and straight-builder output hashes pass. For the default distorted/domed membrane at bead radius 10 and seed 1, automatic fill placed 171,284 beads (74.4% nominal disk-area coverage) versus the old 50,000 cap (21.7%). None of 100,000 independently sampled positions on either leaflet admitted an additional radius-10 bead without overlap in this bead-only test. Radius 5 also completed headlessly with 684,766 beads and 74.3% nominal coverage. These are finite geometric examples, not a proof of globally optimal packing or a no-hole guarantee for all protein mixtures.
- Real PDB mixed render: same default membrane, radius-10 beads and PDB 1AFO at 20% nominal coverage placed 140,381 total particles versus the manual-cap preview's 50,000. Automatic protein coverage was 19.998%, versus 5.966% after the old cap's proportional reduction. Caching unchanged protein bounds reduced this placement calculation from about 63.8 s to 28.8 s on this machine, with identical positions/counts. About 0.075%/0.1% of 100,000 outer/inner probes still admitted an additional bead in this conservative mixed geometry. Inspected the dense render and actual automatic/manual GUI; never call this a proof of globally closest packing or guaranteed timing.

### Protein-Surface Gap Filling (2026-10-30, v6, Active)

- User showed large lipid-free halos around irregular proteins and requested a fix. Do not enlarge display beads, shrink collision radii, permit intersections, reintroduce a lattice, or alter existing protein dimensions to disguise gaps. Replace bead/protein exclusion only; protein/protein enclosing-sphere checks remain conservative and bead/bead spacing remains unchanged.
- `src/membrane_collision.py` uses exactly the validated float32 triangle mesh rendered by ChimeraX. A cached axis-aligned bounding-box hierarchy prunes triangle candidates, then ChimeraX's native `surface_distance` computes the true nearest triangle distance (not nearest vertex/sample). Nearest-vertex distance initializes a safe upper bound only. Leaves hold at most 32 faces and point batches at most 512. Meshes/indices are cached once per PDB-ID/outward-axis template; translated/rotated/spun instance queries transform bead centers into that template's coordinates.
- ChimeraX 1.7.1 does not expose native `surface_distance`; use the bounded NumPy point-to-triangle fallback (plane projection for face interiors plus all three clamped edges) with the same hierarchy and ray test, not a bounding-box approximation. Compare the fallback against native 1.11 distances and analytic cases. Temporary arrays are limited to 128 points by 128 faces even in standalone reference calls. No new installation or optional dependency is required.
- Protein center spheres and oriented mesh boxes are only broad-phase rejection of obviously distant pairs. For every remaining pair, a bead must lie outside the protein AND have mesh clearance at least bead radius plus the unchanged 0.001-radius gap and a small float32 numerical tolerance (2e-6 times max(1, mesh extent)). Check ALL nearby protein instances, not only the nearest center. Never treat all empty corners of an enclosing box as occupied protein.
- Do NOT use the side of one nearest triangle as the sole inside test. Native closest distances agreed exactly during tests, but nearest-triangle side signs differed at shared concave vertices/edges depending on traversal order. Inside/outside instead uses closed-surface ray-crossing parity over the cached hierarchy. Retry ambiguous edge/vertex hits with a second fixed non-axis-aligned ray; conservatively reject an unresolved ambiguous center. Ray parity supports concavities, closed cavities and reversed winding. Tests compare it independently with solid-angle winding, not just with itself.
- New packing requires a closed, consistently triangulated protein mesh with nondegenerate faces; fail safely before committing any scene/history changes for open/inconsistent/degenerate geometry. This is intended for the bundle's generated Gaussian isosurfaces, not arbitrary self-intersecting imported meshes. Legacy saved meshes/placements still restore without running these new packing checks. Protein meshes remain 6-Angstrom Gaussian representations, not atom-level excluded volume.
- After a bead front stalls beside proteins, use up to eight additional area-weighted random probe batches of 8192 points per ingredient/leaflet, restarting contact growth when new pockets are found. Also permit these bounded probes if the ordinary round budget expires. No extra pass when the requested quota has already been met; bead-only recipes keep their existing placement sequence. Candidate count, cancellation, random-seed determinism, recipe proportions and automatic/manual limits remain intact.
- Results use algorithm_version=6 in the unchanged namespaced v1 packing schema and record `protein_lipid_exclusion=triangle-mesh`. Versions 4/5/6 share recipe/templates/spins handling; v5/v6 share the one-million count ceiling and density-budget metadata. Continue accepting v1-v5 and restoring their exact positions without repacking/fetching. JSON, Undo/Redo, APR rotations/meshes, pseudo-site CIF, masks/clipping, colors and scene hierarchy remain unchanged. No edits to attachment, source paths, GLB, pixel sizes, STAR generation or membrane distortion.
- Regression scripts: new `verify_membrane_collision.py` checks actual box-corner freedom, deep-inside rejection, concave torus holes, nested cavities, reversed winding, exact edge-ray cases, bead/face clearance, non-nearest rotated protein collisions, invalid open meshes, and real 1AFO/4HHB distances plus independent winding classification. `verify_membrane_recipe.py` checks accepted particles in formerly excluded protein halos, actual native triangle clearance, interior exclusion, bead/bead separation, remaining gap probes, v4/v5 compatibility and v6 metadata validation. Keep all prior legacy packing, GUI, distortion, JSON/history and export regressions.
- Validation: all 57 tests (8 mesh collision, 26 legacy/packing, 15 recipe, 8 distortion) pass in normal GUI ChimeraX 1.11 and 1.7.1. Tests explicitly exercise the ambiguous-ray retry and NumPy fallback, including upper-bound updates and native/reference distance agreement. Compilation, diff whitespace and straight-builder hash checks pass. Saved layouts/history/export use the same mesh and transforms and remain offline-restorable; no source-path or attachment edits were made.
- Measured 4HHB comparison (length 600, diameter 600, thickness 40, distortion .6/seed 1, dome, radius-10 beads, 20% protein, packing seed 1): original v5 boxes placed 5,727 particles; v6 mesh checks plus gap probes placed 6,290, with identical protein instances and unchanged radii. With the extra gap probes applied to both variants to isolate collision geometry, boxes placed 5,785 versus mesh 6,290. Only 2/50,000 outer and 1/50,000 inner independent probes still admitted a bead after v6 packing. Native full-triangle distances and interior checks verify the accepted halo particles; sphere checks verify bead separation. Compare renders were inspected, not just counts.
- Full default-size 1AFO/20%-protein/radius-10 benchmark: 165,257 particles versus v5's 140,381 at the same dimensions/seed; new placement calculation took about 34.4 s versus the earlier measured 28.8 s. These are measured examples, not guarantees of optimal density, gap-free tiling, biological validity or runtime. Open the packing dialog and explicitly repack after updating; loading an older JSON retains its existing layout by design.

### Membrane Packing Target Selector (2026-11-01)

- The particle packing dialog now has a `Target membrane` combo box listing live generated membranes by name and model ID, including packed membranes. Never include particle children, STARs, maps/models, or other surfaces. Initial selection retains the existing selected/latest-membrane rule. Reopening the already-visible dialog through the build button selects that requested membrane unless a calculation is running.
- Changing target loads that membrane's saved recipe, automatic/manual budget, count, seed and cached protein templates. Unpacked membranes use the existing half-thickness bead default. Preserve unfinished edits per target for this dialog's lifetime, without writing them into scene/JSON or creating history. If a saved packing was replaced/cleared while away, its new saved state supersedes the stale draft. Cache prepared PDB meshes across target changes to avoid unnecessary fetching. Closing/reopening uses saved state, not unsaved drafts.
- Target changes do not move, delete or automatically repack existing particles. Pack/Export apply only to the chosen membrane, with the existing completion-only history action and result validation. Pin the export target before the folder dialog and verify it still exists afterward. No packing algorithm, source attachment, GLB, voxel, STAR, membrane-distortion or general JSON changes.
- Disable target switching throughout packing AND synchronous protein preparation. Programmatic combo changes and repeated build-button clicks must not redirect an active result. Cancel first to switch. If the target is deleted, discard the run without committing it to a fallback membrane; then select another available membrane. Empty lists disable packing/export and recover when a new membrane is built.
- Defer add/remove/name/ID-trigger refreshes through a single-shot Qt timer so scene transactions finish before rebuilding the list. Preserve the selected target and edits on refresh. Remove trigger handlers and stop refresh timers when the dialog closes or its Qt parent is destroyed. No automatic scene-selection following while the window stays open; use the explicit target combo (or invoke the build entry point again).
- Remove the static multi-line explanatory paragraphs from the window. Keep useful tooltips, validation/errors and runtime progress, plus one linked acknowledgment: `Inspired by cellPACK (Johnson et al., 2015). Independent implementation.` Link to https://doi.org/10.1038/nmeth.3204. Do not imply that the upstream cellPACK engine is running or endorses this implementation. Full explanations remain in README/tool help.
- Regression: `runscript tests/verify_membrane_packing_targets.py` exercises real Qt target selection, same-name IDs, per-target drafts/defaults, isolated packing/history/export, runtime and preparation locks, cached PDB templates, stale-draft replacement, live add/rename/ID/remove, empty-list recovery and handler cleanup. Keep all prior packing/collision/recipe/distortion checks passing.
- Validation: all 64 membrane tests (7 target UI, 8 collision, 26 legacy/packing, 15 recipe, 8 distortion) pass in normal GUI ChimeraX 1.11 and 1.7.1. The target-switching window was rendered and visually inspected. Python compilation, diff whitespace and the straight-builder output hash test pass. No bundle install or user-session changes were performed; tests ran in separate ChimeraX processes against the workspace sources.

### Molecular Lipid Sources (2026-11-01)

- Lipid rows now choose `Source: Bead / PDB ID / Local file`. Bead remains the backward-compatible default. Protein rows keep PDB-only sourcing and other-bead rows remain beads. Keep the concise dialog and cellPACK acknowledgment; use tooltips/help rather than explanatory paragraphs. The source panel has PDB/path input, `Browse...` for files and an optional residue/component-name input. Radius is editable only for beads; source dimensions are never rescaled. Outward axis remains manual.
- `src/membrane_molecule.py` owns molecular lipid loading, validation, reusable atom meshes and atom-sphere collision helpers. Use standard cached RCSB fetch for four-character PDB IDs. Local files are restricted to atomic PDB/ENT, CIF/mmCIF, MOL2 and SDF, with compressed PDB/CIF supported; never dispatch arbitrary scripts/commands as lipid inputs. Browse and committed manually edited paths become absolute. Saved path strings are provenance, not required for restoring embedded geometry on other computers.
- Use the first atomic model and one non-polymer residue containing at least three non-hydrogen atoms, excluding HOH/WAT/DOD/H2O and simple ions. If more than one component name remains, require the user's residue name instead of guessing. Repeated copies of the same component supply only the first matching residue. Do not pack the entire protein complex or all its ligands as one lipid. Example verified against RCSB: PDB 1K4C, residue DGA (https://www.rcsb.org/structure/1K4C). This is a component selector, not proof that a selected ligand is chemically a lipid. No biological-assembly expansion, missing-atom repair, force field, flexible relaxation or transmembrane-orientation inference.
- A molecular lipid template stores its source identity, selected/resolved residue, axis, atom coordinates, default van der Waals radii, element numbers and one combined atomic-sphere mesh. Use 80 triangles per atom, at most 500 atoms and 200-Angstrom source-coordinate extent. Temporary atomic structures are never added to the scene and are deleted on success/failure. Proteins retain their existing amino-only 6-Angstrom Gaussian mesh path unchanged.
- Rotate the selected signed source axis to local +Z. Center the atom envelope in X/Y and anchor its maximum Z at zero. Instance origins remain on the actual leaflet triangles, with +Z following that leaflet's outward normal and seeded random axial spin; molecular geometry extends inward into the wall. Thus inner/outer leaflets use opposite physical directions without a special world-axis assumption. User must choose the appropriate head/tail direction; no size fitting to thickness. A too-thin wall can prevent placements through real cross-leaflet collisions, not scaling.
- Lipids remain non-protein relative AREA shares, usable on outer/inner/both leaflets. Molecular area quotas/contact proposals use the projected atomic-envelope footprint, not the long molecule's enclosing sphere; protein amount/coverage must not include molecular lipid counts. Keep protein-first packing and interleaved lipid/other-bead rounds. Bead-only/protein recipes retain version 6 and their previous random placement sequence; recipes with molecular lipid settings use version 7 in the same namespaced v1 schema. Accept versions 1-7 without regenerating old layouts.
- Final molecular collision checks use the union of the same atomic van der Waals spheres used to generate the displayed mesh. Radius-specific cKDTrees give exact nearest-sphere exclusion without unbounded atom-pair arrays. Molecular-lipid vs molecular-lipid, vs bead, and cross-leaflet checks include full normal/spin transforms and the unchanged 0.001-minimum-radius gap. Against proteins, query each lipid atom against the existing triangle mesh/inside test, not a whole-molecule or whole-protein box. Candidate/candidate broad sphere conflicts are refined against template atom spheres before greedy acceptance; existing-placement atom indices are cached by accepted count. Query/transformation blocks are bounded to about 8192 atoms and the existing conflict-pair guard remains. Cancellation releases lipid collision caches too.
- One instanced Surface mesh per ingredient, not one AtomicStructure per copy. Existing ten-million instanced-triangle safety budget now covers protein and molecular lipid templates together; the UI reports molecular rendering reductions. The one-million particle ceiling and manual/automatic budget semantics stay unchanged. Full-atom molecular geometry can hit the rendering budget at lower particle counts than beads; do not hide that reduction or claim globally closest packing.
- Template keys distinguish protein vs lipid, PDB vs file, axis and residue. File-key hashing uses the stored path string without filesystem access so relocated/missing originals do not invalidate saved templates. Embed geometry once per template, shared across matching rows and retained across target switches. Only enabled positive-amount sources are opened/fetched. Reopening/repacking saved molecular lipids must use their embedded template before trying the original path or network.
- Validation checks atom counts/coordinates/radii/elements, source identity, bounds, normals/indices, and that saved molecular vertices/triangles are exactly the atom-derived mesh (within float tolerances). Reject mismatched visual/collision geometry, invalid source types, missing components and oversized inputs before scene mutation. Molecular lipids in old pre-v7 result envelopes must be rejected, not silently treated as beads/proteins.
- Session JSON and global Undo/Redo restore recipes, templates, orientations and placements offline without source reopening; no general JSON/source-path/attachment/GLB/voxel/STAR/membrane-distortion changes. APR/CPR export includes actual lipid meshes and full normal/spin/scene rotations, with relative asset paths. Ingredient metadata records source provenance; package restoration needs the embedded meshes, not the original file. CIF remains one pseudo-site per particle, NOT replicated lipid/protein atoms. Preserve this distinction in README/export documentation.
- Regression: `runscript tests/verify_membrane_lipids.py` covers real PDB 1K4C/DGA extraction/ambiguity, local PDB/CIF/MOL2/SDF, source dimensions and signed axes, source model cleanup, molecular candidate collision graphs against brute-force atom pairs, actual accepted atom/bead/protein clearances, placements closer than enclosing spheres would allow, one-mesh instancing, corrupted template/version rejection, cancellation, offline JSON/Undo/Redo/APR after deleting the original file, complete APR rotations, and real GUI source/file/PDB switching and cached repacking. Keep all existing membrane tests passing.
- Validation: all 72 membrane tests (8 molecular lipid, 7 target selector, 8 collision, 26 legacy packing, 15 recipe, 8 distortion) pass in normal GUI ChimeraX 1.11 and 1.7.1. The source table with PDB and local-file lipid rows and a real DGA molecular membrane render were visually inspected. Compile, diff whitespace and straight-builder output hash checks pass. Geometry is visibly molecular, but density/orientation remain dependent on the selected lipid, manual outward axis and geometric limits; do not claim a validated bilayer or optimal packing. Tests ran in separate applications using workspace sources, without installing the bundle or altering the user's open scene.

Current export button:

- `Export cellPACK package`

Current load button:

- `Load cellPACK`

Current UI note:

- the cellPACK load/export buttons are intentionally hidden from the `Save/Load` page for now
- the underlying code paths still exist and should not be removed casually

Current exporter writes:

- `recipe.json`
- `ciliabuilder_manifest.json`
- `assets/outputs/`
- `assets/sources/`

And for the membrane/cellPACK bundle path:

- `*.cpr.json`
- `*.apr.json`
- `*_membrane_cellpack.cif`
- `meshes/`
- `ingredients/`

Current local load entry points:

- `*.apr.json`
- `ciliabuilder_manifest.json`
- `recipe.json`

Current note about membrane mmCIF:

- the membrane mmCIF is exported for direct structure opening, not through the current `Load cellPACK` JSON/APR helper
- ChimeraX can open the exported membrane mmCIF directly with `open <file>.cif`

There is also:

- `Load cellPACK`

which uses local APR/loading helpers for local packages, not just fetched remote IDs.

Current detailed membrane bundle behavior:

- it can be exported from generated membrane state or autobuilt membrane settings
- it writes a cellPACK-style membrane APR/CPR package in addition to the normal CiliaBuilder export package
- it also writes a membrane mmCIF file containing one explicit pseudo-atom site per packed membrane particle
- the detailed membrane uses colored sphere ingredients for:
  - `receptors`
  - `channels`
  - `signaling`
  - `scaffold`
  - `lipids`
- default hidden composition is currently:
  - receptors `8`
  - channels `7`
  - signaling `7`
  - scaffold `8`
  - lipids `70`
- the current packer is a local approximation of cellPACK behavior, not the upstream engine
- current packing strategy is:
  - place larger protein-like ingredients first
  - then let lipids fill remaining valid sites
- membrane particle radii were intentionally reduced relative to the earlier sparse export so the membrane reads as a filled wall
- the exporter can expand the membrane cylinder outward to clear attached geometry before packing
- the membrane mmCIF currently stores particle positions explicitly in `_atom_site`, not as assembly transforms
- the membrane mmCIF includes local synthetic `chem_comp` rows so ChimeraX does not need to fetch CCD entries for the synthetic membrane particle codes

Current tool log behavior:

- successful export logs package directory and cellPACK bundle paths
- successful load logs APR path and loaded model name/info

Important:

- the recent experimental Mol* / Mesoscope zip exporter was rolled back
- do not assume Mol* export currently exists


## Mol* / Mesoscope Status

Current status:

- Mesoscope / Mol* export attempt was **rolled back**
- do not re-add it casually

Current known format facts from the official Mesoscope docs:

- supported top-level inputs include:
  - standard mmCIF / bcif
  - cellPACK mmCIF / bcif
  - Petworld mmCIF / bcif
  - Explorer manifest `.zip`
  - Mol* session `.molx`

Practical conclusion from prior investigation:

- a custom scene for Mesoscope is more naturally a manifest zip
- a “single big CIF” is only a good fit for strongly atomic-only data
- mixed maps / meshes / GLB / STL are not naturally representable as one clean giant mmCIF
- the user was not satisfied with the earlier attempted Mesoscope export, so this area should be revisited only with a deliberate new implementation pass


## IFT

IFT has two modes in the build UI:

- train-based mode
- picked-placement mode

Current startup defaults for the visible IFT controls are:

- mode `Train`
- type `Anterograde`
- distance from STAR center `1250`
- anterograde angle `-5`
- train microtubule number `3`
- train angle `0`
- train offset `1500`
- train periodicity `65`
- train repeating number `10`

Recent user preferences that must be preserved:

- the visible UI was simplified around a single angle control flow
- anterograde / retrograde direction behavior matters and has been tuned multiple times
- changes here should be narrow and verified against existing placement expectations
- train mode fields are intended for per-train setup, not generic “parameters” wording
- visible UI wording now says `Microtubule number`, not `Filament number`
- the user cares a lot about clockwise/anticlockwise semantics, so sign conventions must not be changed casually


## Central Pair Attachment Expectations

The user wants two possible workflows:

1. separate C1 and C2 STAR lines so different models can be attached independently
2. or attach the same model to both and separate them with X movement

Therefore:

- keep C1/C2 dual-line support
- keep fixed X-movement support


## Map/Model Selector Invariant

The user stated this very explicitly:

- the map/model selector should **NEVER** read the STAR model section

Treat this as a hard rule.


## Devel Install / ChimeraX Reload Notes

ChimeraX development installs are awkward because the bundle is considered “in use” once imported.

Important history:

- there were earlier unsupported XML tag warnings from `bundle_info.xml`
- those were cleaned up
- `bundle_info.xml` now uses older CiliaBuilder-style metadata fields
  - real author/email/url
  - `Cilia Model Builder` synopsis
  - richer ChimeraX/Python classifiers
  - but it still keeps the current local bundle name, package, tool name, and command ids
- for older ChimeraX compatibility, `bundle_info.xml` should avoid top-level `Tools` and `Commands` blocks and rely on ChimeraX classifiers plus `bundle_api.register_command()` / `start_tool()`
- current upstream bundle version is `0.2.1`; do not revert to the older local `0.1.4` metadata
- generic JSON opener takeover was also removed because it made development installs worse

Current recommended philosophy:

- avoid making optional features block the normal ChimeraX update workflow
- keep JSON loading behind the tool and dedicated code paths, not global file-format hijacks

Additional lesson learned:

- generic `.json` opener/provider integration caused too much development friction and should not be reintroduced lightly
- history/session model-tree walkers must guard against cyclic or oddly re-parented ChimeraX attachment trees
  - especially during undo/redo with multiple STAR models and multiple archived/attached sources
  - do not use naive unguarded recursive child-model walks in those paths
- session/history model-structure restore must also refuse any reparent edge that would make a model become its own ancestor
  - wrapper-parent recursion should be guarded too


## Release Packaging

- Release identity is `ChimeraX-CiliaBuilder2` version `0.2.1`, with tool name
  `CiliaBuilder2` and Python package `chimerax.ciliabuilder2`; preserve these names when
  making small release updates. CiliaBuilder2 is a separate Toolshed bundle
  from the original CiliaBuilder, not a renamed replacement for it.
- Build from this repository root using ChimeraX `devel build`. A nested local
  `CiliaBuilder2/` checkout is not the release source.
- Build the distributed wheel in ChimeraX 1.7.1 to retain metadata version 2.1.
  The tested 1.11 builder emits metadata 2.4, which the 1.7.1 Toolshed parser
  cannot discover. A pure-Python wheel tag alone does not guarantee discovery
  by the older ChimeraX release.
- Upstream `bundle_info.xml` declares ChimeraX-Core `>=1.7`, bundled module dependency
  minimums from ChimeraX 1.7, and NumPy `>=1.25`. Do not copy pandas/SciPy
  requirements from CiliaBuilder1; this implementation does not import them.
- Keep the project URL pointed at `builab/CiliaBuilder2` and metadata consistent
  with this repository's BSD-2-Clause `LICENSE`.
- Bundle session metadata range is `1` through `999`; this is not the ChimeraX version
  and does not change the separate session JSON format version `5`.
- `buildcentralpair` is the advertised command. The legacy Python `buildcentriole` callable remains a direct alias so it retains
  the explicit `session` and keyword signature required by ChimeraX command
  registration. Do not replace it with an untyped `*args, **kwargs` wrapper.
  Verify in a fresh ChimeraX session with `runscript tests/verify_bundle_commands.py`.
- Distribute offline help under `src/docs/user/`, listed in `DataFiles`.
  The main tool Help action points at `help:user/tools/ciliabuilder2_tools.html`.
  Update that upstream page for new UI/workflow changes; older local help files are retained separately.
- `README.md` contains current install instructions; `RELEASE.md` retains historical
  0.1.4 release naming, submission steps, and the scope of earlier compatibility checks.
- The universal wheel is pure Python. Do not imply all operating systems were
  tested merely because its filename ends in `py3-none-any.whl`.
- The 0.1.4 wheel passed metadata/dependency checks, command registration,
  STAR rendering, membrane construction, GUI creation, and the existing
  attachment geometry regression scripts in macOS ChimeraX 1.7.1 and 1.11.
  This is smoke-test coverage, not exhaustive validation of every workflow.


## ChimeraX Paths Learned During Development

Useful local paths on this machine:

- bundle workspace:
  - `/Users/qs/PycharmProjects/CiliaBuilder2`
- ChimeraX cache:
  - `/Users/qs/Library/Caches/ChimeraX/1.11/`
- ChimeraX application support:
  - `/Users/qs/Library/Application Support/ChimeraX/1.11/`

Fetched/cached models may appear under those ChimeraX directories depending on source.


## Current User Preferences

These are important. Prefer to keep them unless the user asks for a change.

- preserve working code paths, especially:
  - attachment
  - JSON save/load
  - GLB handling
- make narrow changes
- do not widen selector logic
- do not auto-read STAR particle children as map/model sources
- keep manual tweak code but hide its UI
- keep the hidden pixel-size widget, not a visible pixel-size UI
- keep the hidden membrane composition controls hidden unless the user asks to expose them
- keep attachment X movement fixed to world/view X
- keep membrane in its own model group
- keep membrane distortion in the older smooth style, now with 9 separate same-style curves
- keep lipids visible in the cellPACK membrane export/load path
- keep the membrane mmCIF export path working and self-contained
- keep the source selector conservative rather than permissive
- prefer hiding noisy/generated/internal models over trying to expose every possible subtree
- keep generated marker-path guide models out of the attach-source selector


## Editing Guidance for Future Agents

When making changes:

1. check whether the target behavior is already stabilized by user feedback
2. change the smallest possible area
3. avoid redesigning working flows
4. compile-check changed Python files
5. if touching export/session/attach behavior, be especially conservative

Preferred sanity check:

```bash
PYTHONPYCACHEPREFIX=/tmp python3 -m py_compile /Users/qs/PycharmProjects/CiliaBuilder2/src/tool.py /Users/qs/PycharmProjects/CiliaBuilder2/src/map.py /Users/qs/PycharmProjects/CiliaBuilder2/src/cmd.py /Users/qs/PycharmProjects/CiliaBuilder2/src/draw.py /Users/qs/PycharmProjects/CiliaBuilder2/src/cellpack_export.py
```

Optional follow-up checks when relevant:

- re-open the tool and confirm hidden controls stay hidden
- if touching membrane export, confirm the hidden membrane composition controls still stay hidden
- if touching membrane mmCIF export, verify ChimeraX can open the `.cif` directly without CCD fetch warnings
- verify `Map model` selector does not show STAR particles
- verify session load ends with `view orient`
- verify file-backed GLB/GLTF JSON records reference the original file (including `.gz`) without exporting a copy; STL copies and in-memory export fallbacks must not overwrite originals


## Known Sensitive Areas

These have broken repeatedly in earlier iterations, so treat them carefully:

- GLB attachment
- selector filtering
- JSON source-path persistence
- JSON attachment replay
- central pair C1/C2 separation logic
- membrane distortion algorithm
- membrane cellPACK packing/export behavior
- membrane mmCIF export behavior
- marker-path placement/session-restore behavior
- ChimeraX development install behavior
- hidden pixel-size state
- hidden membrane composition state
- source reset timing before attach
- STAR child / particle leakage into source selectors


## What Not To Do Without Explicit User Approval

- do not broadly refactor `tool.py`
- do not replace the working GLB attach logic with a “simpler” tree walk
- do not change JSON format structure casually
- do not remove the hidden pixel-size widget
- do not reintroduce STAR child models into the source selector
- do not revive experimental Mol* / Mesoscope export code without a clear new request
- do not overwrite original GLB/STL files during session export
- do not auto-show hidden tweak UI unless the user asks for it
- do not casually remove or rename the lipid membrane ingredient without checking the cellPACK load/export path
- do not silently change the membrane mmCIF from explicit positions to an assembly-based encoding without a deliberate format decision
