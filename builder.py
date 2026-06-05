from __future__ import annotations
import math
from typing import Dict, List, Tuple, Optional

from chimerax.core.models import Surface
from chimerax.surface.shapes import sphere_geometry

from .star import star_text_from_rows, star_points_from_text

import numpy as np
from chimerax.surface.shapes import cylinder_geometry



def _rgba8(color) -> Tuple[int, int, int, int]:
    try:
        return (int(color[0]), int(color[1]), int(color[2]), int(color[3]))
    except Exception:
        return (200, 200, 200, 255)


def make_sphere_surface(session, center_xyz, radius: float, subdivisions: int,
                        color=(200, 200, 200, 255), name: str = "Bead") -> Surface:
    subdivisions = max(1, int(subdivisions))

    # ChimeraX sphere_geometry takes only subdivisions and returns a unit sphere
    va, na, ta = sphere_geometry(subdivisions)

    va = va * float(radius)
    va[:, 0] += float(center_xyz[0])
    va[:, 1] += float(center_xyz[1])
    va[:, 2] += float(center_xyz[2])

    s = Surface(name, session)
    s.set_geometry(va, na, ta)
    s.color = _rgba8(color)
    return s


def build_straight_cilia_beads(session,
                              length: float,
                              outer_radius: float,
                              spacing: float,
                              bead_radius: float,
                              subdivisions: int,
                              outer_count: int = 9,
                              make_central_pair: bool = True,
                              cp_separation: float = 200.0,
                              color_outer=(120, 180, 255, 255),
                              color_cp=(255, 180, 120, 255),
                              tomo_name: str = "TS_001",
                              pixel_size: float = 1.0,
                              angles_rot_tilt_psi: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                              make_star: bool = True
                              ) -> Tuple[Surface, List[Surface], List[Dict[str, object]], str]:
    length = float(length)
    outer_radius = float(outer_radius)
    spacing = max(1.0, float(spacing))
    bead_radius = max(1.0, float(bead_radius))
    subdivisions = max(3, int(subdivisions))

    root = Surface("CB_Cilia", session)
    session.models.add([root])

    bead_models: List[Surface] = []
    star_rows: List[Dict[str, object]] = []
    rot, tilt, psi = angles_rot_tilt_psi

    n = int(math.floor(length / spacing)) + 1
    z_list = [i * spacing for i in range(n)]

    def add_tube(tube_id: int, base_xy: Tuple[float, float], color):
        tube_group = Surface(f"Tube_{tube_id}", session)
        session.models.add([tube_group], parent=root)

        for i, z in enumerate(z_list):
            x = base_xy[0]

            y = base_xy[1]
            center = (x, y, z)

            bead = make_sphere_surface(
                session=session,
                center_xyz=center,
                radius=bead_radius,
                subdivisions=subdivisions,
                color=color,
                name=f"Bead_{tube_id}_{i}"
            )
            session.models.add([bead], parent=tube_group)
            bead_models.append(bead)

            if make_star:
                star_rows.append({
                    "tomo_name": tomo_name,
                    "x": x,
                    "y": y,
                    "z": z,
                    "rot": rot,
                    "tilt": tilt,
                    "psi": psi,
                    "pixel": float(pixel_size),
                    "tube_id": int(tube_id),
                })

    for k in range(int(outer_count)):
        ang = 2.0 * math.pi * (k / float(outer_count))
        x = outer_radius * math.cos(ang)
        y = outer_radius * math.sin(ang)
        add_tube(tube_id=k + 1, base_xy=(x, y), color=color_outer)

    if make_central_pair:
        half = float(cp_separation) / 2.0
        add_tube(tube_id=outer_count + 1, base_xy=(half, 0.0), color=color_cp)
        add_tube(tube_id=outer_count + 2, base_xy=(-half, 0.0), color=color_cp)

    star_text = star_text_from_rows(star_rows) if make_star else ""
    return root, bead_models, star_rows, star_text


def build_models_from_star(session,
                           star_text: str,
                           bead_radius: float,
                           subdivisions: int,
                           color=(180, 255, 180, 255),
                           name: str = "CB_From_STAR",
                           show_axes: bool = True,
                           axis_len: float = 80.0,
                           axis_radius: float = 6.0) -> Surface:
    pts = star_points_from_text(star_text)

    root = Surface(name, session)
    session.models.add([root])

    by_tube: Dict[int, List[Dict[str, object]]] = {}
    for p in pts:
        by_tube.setdefault(int(p["tube_id"]), []).append(p)

    for tube_id, plist in sorted(by_tube.items(), key=lambda kv: kv[0]):
        tube_group = Surface(f"Tube_{tube_id}", session)
        session.models.add([tube_group], parent=root)

        for i, p in enumerate(plist):
            center = (p["x"], p["y"], p["z"])

            bead = make_sphere_surface(
                session=session,
                center_xyz=center,
                radius=float(bead_radius),
                subdivisions=int(subdivisions),
                color=color,
                name=f"Bead_{tube_id}_{i}"
            )
            session.models.add([bead], parent=tube_group)

            if show_axes:
                R = euler_zyz_to_matrix(p["rot"], p["tilt"], p["psi"])
                axes_group = Surface(f"Axes_{tube_id}_{i}", session)
                session.models.add([axes_group], parent=tube_group)
                add_axis_triad(
                    session=session,
                    parent=axes_group,
                    center_xyz=center,
                    R=R,
                    axis_len=float(axis_len),
                    axis_radius=float(axis_radius),
                )

    return root


def euler_zyz_to_matrix(rot_deg: float, tilt_deg: float, psi_deg: float) -> np.ndarray:
    """
    RELION style angles are commonly treated as Z Y Z intrinsic rotations.
    R = Rz(rot) * Ry(tilt) * Rz(psi)
    """
    r = math.radians(float(rot_deg))
    t = math.radians(float(tilt_deg))
    p = math.radians(float(psi_deg))

    cr, sr = math.cos(r), math.sin(r)
    ct, st = math.cos(t), math.sin(t)
    cp, sp = math.cos(p), math.sin(p)

    Rz1 = np.array([[cr, -sr, 0.0],
                    [sr,  cr, 0.0],
                    [0.0, 0.0, 1.0]], dtype=float)

    Ry  = np.array([[ct, 0.0, st],
                    [0.0, 1.0, 0.0],
                    [-st, 0.0, ct]], dtype=float)

    Rz2 = np.array([[cp, -sp, 0.0],
                    [sp,  cp, 0.0],
                    [0.0, 0.0, 1.0]], dtype=float)

    return Rz1 @ Ry @ Rz2

def make_cylinder_between(session, p0, p1, radius: float, color, name: str) -> Surface:
    # Create a unit cylinder along Z, then rotate and translate it to span p0->p1
    va, na, ta = cylinder_geometry(24)  # 24 sides, smoother if you want 32

    p0 = np.array(p0, dtype=float)
    p1 = np.array(p1, dtype=float)
    v = p1 - p0
    L = float(np.linalg.norm(v))
    if L <= 1e-6:
        s = Surface(name, session)
        s.color = _rgba8(color)
        return s

    # Scale unit cylinder (z from 0..1) into radius and length
    va = va.copy()
    va[:, 0] *= float(radius)
    va[:, 1] *= float(radius)
    va[:, 2] *= L

    # Build rotation taking +Z to direction v
    z = np.array([0.0, 0.0, 1.0], dtype=float)
    d = v / L
    c = float(np.dot(z, d))

    if c > 0.999999:
        R = np.eye(3)
    elif c < -0.999999:
        # 180 degree flip around X
        R = np.array([[1, 0, 0],
                      [0, -1, 0],
                      [0, 0, -1]], dtype=float)
    else:
        axis = np.cross(z, d)
        axis /= np.linalg.norm(axis)
        x, y, zc = axis
        s = math.sqrt((1 + c) * 2)
        invs = 1 / s
        # quaternion to matrix
        qx, qy, qz, qw = x * invs, y * invs, zc * invs, s * 0.5
        R = np.array([
            [1 - 2*(qy*qy + qz*qz),     2*(qx*qy - qz*qw),     2*(qx*qz + qy*qw)],
            [    2*(qx*qy + qz*qw), 1 - 2*(qx*qx + qz*qz),     2*(qy*qz - qx*qw)],
            [    2*(qx*qz - qy*qw),     2*(qy*qz + qx*qw), 1 - 2*(qx*qx + qy*qy)],
        ], dtype=float)

    va = (va @ R.T)
    va[:, 0] += p0[0]
    va[:, 1] += p0[1]
    va[:, 2] += p0[2]

    s = Surface(name, session)
    s.set_geometry(va, na, ta)
    s.color = _rgba8(color)
    return s


def add_axis_triad(session, parent, center_xyz, R: np.ndarray,
                   axis_len: float = 80.0, axis_radius: float = 6.0):
    """
    Draw local X, Y, Z axes at center_xyz.
    R columns give rotated basis vectors if R maps local->world.
    """
    c = np.array(center_xyz, dtype=float)

    ex = R @ np.array([1.0, 0.0, 0.0])
    ey = R @ np.array([0.0, 1.0, 0.0])
    ez = R @ np.array([0.0, 0.0, 1.0])

    x_end = c + axis_len * ex
    y_end = c + axis_len * ey
    z_end = c + axis_len * ez

    sx = make_cylinder_between(session, c, x_end, axis_radius, (255, 60, 60, 255), "Axis_X")
    sy = make_cylinder_between(session, c, y_end, axis_radius, (60, 255, 60, 255), "Axis_Y")
    sz = make_cylinder_between(session, c, z_end, axis_radius, (60, 120, 255, 255), "Axis_Z")

    session.models.add([sx, sy, sz], parent=parent)
