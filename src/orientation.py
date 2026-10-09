"""Shared RELION STAR orientations and rigid vector alignment.

Matrices act on column vectors; their columns are the particle's local axes
in the scene. RELION/ArtiaX use Rz(-psi) @ Ry(-tilt) @ Rz(-rot).
"""

import math

import numpy as np


def _unit(vector):
    vector = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        return np.array([0.0, 0.0, 1.0])
    return vector / norm


def relion_rotation_matrix(rot_deg, tilt_deg, psi_deg):
    rot, tilt, psi = map(math.radians, (float(rot_deg), float(tilt_deg), float(psi_deg)))
    cr, sr = math.cos(rot), math.sin(rot)
    ct, st = math.cos(tilt), math.sin(tilt)
    cp, sp = math.cos(psi), math.sin(psi)
    return np.array([
        [cp * ct * cr - sp * sr, cp * ct * sr + sp * cr, -cp * st],
        [-sp * ct * cr - cp * sr, -sp * ct * sr + cp * cr, sp * st],
        [st * cr, st * sr, ct],
    ], dtype=float)


def particle_axes_from_star(rot_deg, tilt_deg, psi_deg):
    basis = relion_rotation_matrix(rot_deg, tilt_deg, psi_deg)
    return tuple(basis[:, i] for i in range(3))


def particle_axes_from_row(row):
    axes = [row.get("_cbAxis" + name) for name in "XYZ"]
    if all(axis is not None for axis in axes):
        return tuple(_unit(axis) for axis in axes)
    return particle_axes_from_star(*(row.get("rlnAngle" + name, 0.0) for name in ("Rot", "Tilt", "Psi")))


def relion_angles_from_axes(ex, ey, ez):
    basis = np.column_stack([_unit(axis) for axis in (ex, ey, ez)])
    sin_tilt = math.hypot(float(basis[2, 0]), float(basis[2, 1]))
    cos_tilt = float(np.clip(basis[2, 2], -1.0, 1.0))
    # atan2 retains tiny tilts which acos can round down to zero.
    tilt = math.atan2(sin_tilt, cos_tilt)
    if sin_tilt > 1e-12:
        rot = math.atan2(float(basis[2, 1]), float(basis[2, 0]))
        psi = math.atan2(float(basis[1, 2]), float(-basis[0, 2]))
    elif cos_tilt >= 0.0:
        rot = math.atan2(float(basis[0, 1]), float(basis[0, 0]))
        psi = 0.0
    else:
        rot = math.atan2(float(-basis[0, 1]), float(-basis[0, 0]))
        psi = 0.0
    return tuple(math.degrees(angle) for angle in (rot, tilt, psi))


def row_with_relion_angles(row):
    """Export cached live axes faithfully, including older rows with stale angles."""
    axes = [row.get("_cbAxis" + name) for name in "XYZ"]
    if not all(axis is not None for axis in axes):
        return row
    angles = relion_angles_from_axes(*axes)
    return dict(row, **dict(zip(("rlnAngleRot", "rlnAngleTilt", "rlnAnglePsi"), angles)))


def rotation_align_vector_to_vector(v_from, v_to):
    before, after = _unit(v_from), _unit(v_to)
    cross = np.cross(before, after)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(before, after), -1.0, 1.0))
    if sine < 1e-12:
        if cosine >= 0.0:
            return np.eye(3)
        # Any perpendicular axis works for a half turn; world X need not be one.
        perpendicular = _unit(np.cross(before, np.eye(3)[np.argmin(np.abs(before))]))
        return 2.0 * np.outer(perpendicular, perpendicular) - np.eye(3)
    axis = cross / sine
    x, y, z = axis
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=float)
    return cosine * np.eye(3) + sine * skew + (1.0 - cosine) * np.outer(axis, axis)
