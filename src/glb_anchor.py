"""Preserve volume-grid attachment pivots without recentering GLB geometry."""

import gzip
import json
import os
import shutil
import struct
import tempfile

import numpy as np


def validated_anchor(value):
    try:
        anchor = np.asarray(value, dtype=float)
        if anchor.shape == (3,) and np.all(np.isfinite(anchor)):
            return anchor
    except (TypeError, ValueError):
        pass
    return None


def _read_header(stream):
    header = stream.read(20)
    if len(header) != 20:
        raise ValueError("Incomplete GLB header")
    magic, version, length, json_length, kind = struct.unpack("<5I", header)
    if magic != 0x46546C67 or version != 2 or kind != 0x4E4F534A:
        raise ValueError("Not a binary glTF 2 file")
    if json_length > length - 20:
        raise ValueError("Invalid GLB JSON length")
    return json.loads(stream.read(json_length)), length, json_length


def read_glb_anchor(path):
    try:
        opener = gzip.open if str(path).lower().endswith(".gz") else open
        with opener(path, "rb") as stream:
            header, _, _ = _read_header(stream)
        return validated_anchor(header.get("extras", {}).get("ciliabuilder2", {}).get("volume_grid_anchor"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def write_glb_anchor(path, anchor):
    """Add optional glTF extras; leave all mesh buffers and transforms intact."""
    anchor = validated_anchor(anchor)
    if anchor is None:
        return
    temporary = None
    try:
        with open(path, "rb") as source:
            header, length, old_length = _read_header(source)
            header.setdefault("extras", {}).setdefault("ciliabuilder2", {})["volume_grid_anchor"] = anchor.tolist()
            encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
            encoded += b" " * (-len(encoded) % 4)
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(os.path.abspath(path)), delete=False) as output:
                temporary = output.name
                output.write(struct.pack("<5I", 0x46546C67, 2, length - old_length + len(encoded), len(encoded), 0x4E4F534A))
                output.write(encoded)
                shutil.copyfileobj(source, output)
        shutil.copymode(path, temporary)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _meshes(root):
    """Mesh coordinates relative to the attachment root, including child nodes."""
    from chimerax.geometry import Place

    meshes = []
    pending = [(root, Place())]
    while pending:
        drawing, transform = pending.pop()
        vertices = getattr(drawing, "vertices", None)
        triangles = getattr(drawing, "triangles", None)
        if vertices is not None and triangles is not None and len(vertices):
            meshes.append((vertices, triangles, transform))
        for child in reversed(drawing.child_drawings()):
            if not child.display:
                continue
            # Do not mistake one part of an instanced composite for the source.
            if len(child.positions) != 1:
                return []
            pending.append((child, transform * child.position))
    return meshes


def _mesh_translation(mesh, reference):
    vertices, triangles, transform = mesh
    ref_vertices, ref_triangles, ref_transform = reference
    if vertices.shape != ref_vertices.shape or not np.array_equal(triangles, ref_triangles):
        return None
    shift = transform * vertices[0] - ref_transform * ref_vertices[0]
    # Float32 node centering introduces small roundoff. Verify every vertex,
    # in bounded chunks, rather than matching a name, bounding box, or sample.
    for start in range(0, len(vertices), 65536):
        actual = transform * vertices[start:start + 65536]
        expected = ref_transform * ref_vertices[start:start + 65536]
        tolerance = max(1e-4, float(np.max(np.abs(expected))) * 5e-7)
        if not np.allclose(actual - shift, expected, rtol=0, atol=tolerance):
            return None
    return shift


def _anchor_sources(session, excluded=None):
    from chimerax.map import Volume
    from .source_paths import original_glb_path

    for source in session.models.list():
        if source is excluded or len(source.positions) != 1:
            continue
        ancestor = source
        while ancestor is not None and not getattr(ancestor, "_cb_generated_attached", False):
            ancestor = ancestor.parent
        if ancestor is not None:
            continue
        if isinstance(source, Volume):
            # Origin reset can leave hidden archived surface vertices stale.
            source.update_drawings()
            yield source, np.asarray(source.center(), dtype=float)
        elif getattr(source, "_cb_original_source_path", None) or hasattr(source, "_cb_glb_volume_anchor"):
            anchor = validated_anchor(getattr(source, "_cb_glb_volume_anchor", None))
            if anchor is None:
                anchor = read_glb_anchor(original_glb_path(source))
            if anchor is not None:
                yield source, anchor


def matching_volume_anchor(session, model):
    meshes = _meshes(model)
    if not meshes:
        return None
    anchors = []
    for source, source_anchor in _anchor_sources(session, excluded=model):
        references = _meshes(source)
        if len(meshes) != len(references):
            continue
        shifts = []
        remaining = list(references)
        for mesh in meshes:
            for index, reference in enumerate(remaining):
                shift = _mesh_translation(mesh, reference)
                if shift is not None:
                    shifts.append(shift)
                    remaining.pop(index)
                    break
            else:
                break
        if remaining or not shifts or not np.allclose(shifts, shifts[0], atol=1e-3, rtol=0):
            continue
        anchors.append(source_anchor + shifts[0])
    # Identical surfaces in differently padded grids are ambiguous; never guess.
    if anchors and np.allclose(anchors, anchors[0], atol=1e-3, rtol=0):
        return anchors[0]
    return None


def volume_glb_anchor(session, model):
    from .source_paths import original_glb_path

    anchor = validated_anchor(getattr(model, "_cb_glb_volume_anchor", None))
    if anchor is None:
        path = original_glb_path(model)
        if path:
            anchor = read_glb_anchor(path)
    if anchor is None:
        anchor = matching_volume_anchor(session, model)
    if anchor is not None:
        model._cb_glb_volume_anchor = anchor.tolist()
    return anchor


def preserve_export_anchor(session, path, source):
    from chimerax.map import Volume
    from .source_paths import is_glb_path, original_glb_path

    if isinstance(source, Volume):
        anchor = source.center()
    elif hasattr(source, "_cb_glb_volume_anchor") or is_glb_path(original_glb_path(source)):
        anchor = volume_glb_anchor(session, source)
    else:
        return
    if anchor is not None:
        write_glb_anchor(path, source.scene_position * anchor)


def preserve_command_export_anchor(session, path):
    """Recognize volume exports from the saved geometry, not save-command guesses."""
    from chimerax.gltf.gltf import read_gltf

    if next(_anchor_sources(session), None) is None:
        return
    roots = []
    try:
        with open(path, "rb") as stream:
            roots, _ = read_gltf(session, stream, os.path.basename(path))
        if len(roots) == 1:
            anchor = matching_volume_anchor(session, roots[0])
            if anchor is not None:
                write_glb_anchor(path, anchor)
    finally:
        for model in roots:
            model.delete()
