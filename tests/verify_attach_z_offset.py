"""Run in ChimeraX with: runscript tests/verify_attach_z_offset.py"""

import sys
from pathlib import Path

import numpy as np
from chimerax.core.models import Model, Surface

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.draw import build_cilia_lines_star_rows
from src.map import _rot_y, _rotation_about_axis, cbsubmap_impl


star = Model("Z offset filament rotation test", session)
star._cb_star_rows = build_cilia_lines_star_rows(9, 100, 100, 100, "test", 1)
session.models.add([star])

surface = Surface("asymmetric test surface", session)
vertices = np.array(
    [[-80, -10, 0], [80, -10, 0], [80, 10, 0], [-80, 10, 0]],
    dtype=np.float32,
)
normals = np.tile([0, 0, 1], (4, 1)).astype(np.float32)
triangles = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
surface.set_geometry(vertices, normals, triangles)
session.models.add([surface])


def attachment_geometry(angle, local_adjust=None, per_line=False):
    result = cbsubmap_impl(
        session,
        star,
        surface.id_string,
        close_source=False,
        single_big_object=True,
        rotate_xy_90=True,
        attach_axis_rot_z_deg=-90,
        attach_z_offset_deg=angle if per_line else 0,
        attach_all_z_offset_deg=0 if per_line else angle,
        attach_local_adjust_matrix=local_adjust,
    )
    copies = list(result.child_models())
    assert len(copies) == 1, f"expected one instanced child, got {len(copies)}"
    positions = list(copies[0].positions)
    assert len(positions) == len(star._cb_star_rows)
    transformed = np.array([[position * vertex for vertex in vertices] for position in positions])
    centers = np.mean(transformed, axis=1)
    directions = transformed[:, 0] - centers
    session.models.close([result])
    return centers, directions


for local_adjust in (None, _rot_y(-90)):
    centers_zero, directions_zero = attachment_geometry(0, local_adjust=local_adjust)
    centers_rotated, directions_rotated = attachment_geometry(45, local_adjust=local_adjust)
    expected = np.array([
        [row["rlnCoordinateX"], row["rlnCoordinateY"], row["rlnCoordinateZ"]]
        for row in star._cb_star_rows
    ])
    assert np.allclose(centers_zero, expected, atol=1e-5)
    assert np.allclose(centers_rotated, expected, atol=1e-5), "Z offset moved filament centers"
    assert not np.allclose(directions_zero, directions_rotated), "Z offset did not spin attachments"
    assert np.allclose(
        np.linalg.norm(directions_zero, axis=1),
        np.linalg.norm(directions_rotated, axis=1),
        atol=1e-5,
    ), "Z offset changed attachment size"

centers_zero, directions_zero = attachment_geometry(0)
centers_line, directions_line = attachment_geometry(25, per_line=True)
assert np.allclose(centers_zero, centers_line, atol=1e-5), "per-line rotation moved filaments"
tube_ids = [int(row["rlnHelicalTubeID"]) for row in star._cb_star_rows]
assert np.allclose(
    directions_zero[np.array(tube_ids) == min(tube_ids)],
    directions_line[np.array(tube_ids) == min(tube_ids)],
), "first filament received a nonzero per-line offset"
assert not np.allclose(
    directions_zero[np.array(tube_ids) == max(tube_ids)],
    directions_line[np.array(tube_ids) == max(tube_ids)],
), "other filaments did not receive their per-line offsets"

star._cb_star_rows = [
    {
        **row,
        "_cbWorldCoordinateX": row["rlnCoordinateX"] + 250,
        "_cbWorldCoordinateY": row["rlnCoordinateY"] - 125,
        "_cbWorldCoordinateZ": row["rlnCoordinateZ"],
    }
    for row in star._cb_star_rows
]
centers_zero, _ = attachment_geometry(0)
centers_rotated, _ = attachment_geometry(45)
expected = np.array([
    [row["_cbWorldCoordinateX"], row["_cbWorldCoordinateY"], row["_cbWorldCoordinateZ"]]
    for row in star._cb_star_rows
])
assert np.allclose(centers_zero, expected, atol=1e-5)
assert np.allclose(centers_rotated, expected, atol=1e-5), "world-coordinate filaments moved"

# A slanted filament must spin around its own line, not the scene Z axis.
first_tube = min(tube_ids)
star._cb_star_rows = [
    {
        **row,
        "_cbWorldCoordinateX": row["rlnCoordinateX"] + 0.2 * row["rlnCoordinateZ"],
        "_cbWorldCoordinateY": row["rlnCoordinateY"],
        "_cbWorldCoordinateZ": row["rlnCoordinateZ"],
    }
    for row in star._cb_star_rows
    if int(row["rlnHelicalTubeID"]) == first_tube
]
centers_zero, directions_zero = attachment_geometry(0)
centers_rotated, directions_rotated = attachment_geometry(35)
assert np.allclose(centers_zero, centers_rotated, atol=1e-5)
rotation = _rotation_about_axis([0.2, 0, 1], 35)
assert np.allclose(directions_rotated, directions_zero @ rotation.T, atol=1e-5), (
    "slanted filament did not rotate around its own line"
)
print("Attachment Z offset rotates each filament in place; all STAR centers and source sizes are unchanged")
