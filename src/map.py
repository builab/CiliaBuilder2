# vim: set expandtab shiftwidth=4 softtabstop=4:

import numpy as np

from chimerax.core.models import Model
from chimerax.core.commands import run as _run
from chimerax.geometry import Place


def _get_top_by_id(session, id1):
    id1 = int(id1)
    for m in session.models.list():
        if getattr(m, "id", None) and len(m.id) == 1 and int(m.id[0]) == id1:
            return m
    return None


def _parse_star_rows_from_model(model_obj):
    rows = getattr(model_obj, "_cb_star_rows", None)
    if rows is None:
        raise RuntimeError("cbsubmap needs a star model created by cbstraight or buildcentriole")
    return rows


def _safe_unit(v):
    v = np.array(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return v / n


def _axes_from_relion_angles(rot_deg, tilt_deg, psi_deg):
    # Relion ZYZ
    # R = Rz(psi) * Ry(tilt) * Rz(rot)
    import math

    r = math.radians(float(rot_deg))
    t = math.radians(float(tilt_deg))
    p = math.radians(float(psi_deg))

    cr, sr = math.cos(r), math.sin(r)
    ct, st = math.cos(t), math.sin(t)
    cp, sp = math.cos(p), math.sin(p)

    Rz_r = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]], dtype=float)
    Ry_t = np.array([[ct, 0.0, st], [0.0, 1.0, 0.0], [-st, 0.0, ct]], dtype=float)
    Rz_p = np.array([[cp, -sp, 0.0], [sp, cp, 0.0], [0.0, 0.0, 1.0]], dtype=float)

    R = Rz_p @ Ry_t @ Rz_r
    ex = _safe_unit(R @ np.array([1.0, 0.0, 0.0], dtype=float))
    ey = _safe_unit(R @ np.array([0.0, 1.0, 0.0], dtype=float))
    ez = _safe_unit(R @ np.array([0.0, 0.0, 1.0], dtype=float))
    return ex, ey, ez


def _copy_volume_instance(session, src):
    try:
        if hasattr(src, "copy"):
            dst = src.copy()
            return dst
    except Exception:
        pass

    grid = None
    for attr in ["data", "grid_data"]:
        if hasattr(src, attr):
            try:
                grid = getattr(src, attr)
                break
            except Exception:
                grid = None

    if grid is not None:
        try:
            try:
                from chimerax.map import volume_from_grid_data
            except Exception:
                from chimerax.map.volume import volume_from_grid_data
            dst = volume_from_grid_data(grid, session)
            return dst
        except Exception:
            pass

    path = getattr(src, "path", None)
    if not path:
        try:
            path = src.data.path
        except Exception:
            path = None

    if path:
        try:
            _run(session, f'open "{path}"')
            return session.models.list()[-1]
        except Exception:
            return None

    return None


def cbsubmap_impl(
    session,
    star_model_obj,
    map_model_id,
    close_source=True,
    show_result=True,
):
    rows = _parse_star_rows_from_model(star_model_obj)

    src_map = _get_top_by_id(session, map_model_id)
    if src_map is None:
        session.logger.error("cbsubmap cannot find map_model by that id")
        return None

    out_root = Model("CB_Submaps", session)
    session.models.add([out_root])

    placed = 0
    for i, r in enumerate(rows):
        px = float(r.get("rlnImagePixelSize", 1.0))
        cx = float(r.get("rlnCoordinateX", 0.0)) * px
        cy = float(r.get("rlnCoordinateY", 0.0)) * px
        cz = float(r.get("rlnCoordinateZ", 0.0)) * px
        center = np.array([cx, cy, cz], dtype=float)

        ex, ey, ez = _axes_from_relion_angles(
            r.get("rlnAngleRot", 0.0),
            r.get("rlnAngleTilt", 0.0),
            r.get("rlnAnglePsi", 0.0),
        )

        mcopy = _copy_volume_instance(session, src_map)
        if mcopy is None:
            raise RuntimeError("cbsubmap could not create a volume instance from the source map")

        try:
            mcopy.name = f"Submap_{i}"
        except Exception:
            pass

        try:
            mcopy.position = Place(axes=(ex, ey, ez), origin=center)
        except Exception:
            try:
                mcopy.position = Place(origin=center)
            except Exception:
                pass

        session.models.add([mcopy], parent=out_root)
        placed += 1

    session.logger.info(f"cbsubmap placed {placed} submaps under model {out_root.id_string}")

    if show_result:
        try:
            out_root.display = True
        except Exception:
            pass
        try:
            for m in out_root.child_models():
                m.display = True
        except Exception:
            pass

    if close_source:
        try:
            session.models.close([star_model_obj])
        except Exception:
            pass

    return out_root
