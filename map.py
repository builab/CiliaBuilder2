# vim: set expandtab shiftwidth=4 softtabstop=4:

import numpy as np

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
        raise RuntimeError("Need a star model created by cbstraight or buildcentriole")
    if not isinstance(rows, (list, tuple)) or len(rows) == 0:
        raise RuntimeError("Star model has no stored STAR rows")
    return rows


def _safe_unit(v):
    v = np.array(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return v / n


def _axes_from_relion_angles_match_artiax_arrow(rot_deg, tilt_deg, psi_deg):
    """
    Returns axes that match the orientation shown by ArtiaX arrows.

    Important
    ArtiaX displays axes using the transpose of the Relion rotation.
    So use R^T when mapping unit axes.
    """
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
    Rt = R.T

    ex = _safe_unit(Rt @ np.array([1.0, 0.0, 0.0], dtype=float))
    ey = _safe_unit(Rt @ np.array([0.0, 1.0, 0.0], dtype=float))
    ez = _safe_unit(Rt @ np.array([0.0, 0.0, 1.0], dtype=float))
    return ex, ey, ez


def _copy_volume_instance(session, src):
    try:
        if hasattr(src, "copy"):
            return src.copy()
    except Exception:
        pass

    grid = None
    for attr in ("data", "grid_data"):
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
            return volume_from_grid_data(grid, session)
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


def _map_voxel_size_ang(vol):
    def _try_step(obj):
        try:
            st = obj.step
            if st is None:
                return None
            return (float(st[0]), float(st[1]), float(st[2]))
        except Exception:
            return None

    candidates = []
    try:
        if hasattr(vol, "data") and hasattr(vol.data, "grid_data") and vol.data.grid_data is not None:
            s = _try_step(vol.data.grid_data)
            if s:
                candidates.append(s)
    except Exception:
        pass

    try:
        if hasattr(vol, "grid_data") and vol.grid_data is not None:
            s = _try_step(vol.grid_data)
            if s:
                candidates.append(s)
    except Exception:
        pass

    try:
        if hasattr(vol, "data") and vol.data is not None:
            s = _try_step(vol.data)
            if s:
                candidates.append(s)
    except Exception:
        pass

    if not candidates:
        return 1.0

    sx = abs(float(candidates[0][0]))
    if sx < 1e-12:
        return 1.0
    return sx


def _local_center_of_model(model_obj):
    """
    Return the local center of the model in its own coordinates.
    Used so the map is centered on the STAR point.
    """
    try:
        model_obj.position = Place()
    except Exception:
        pass

    try:
        b = model_obj.bounds()
    except Exception:
        b = None

    if b is None:
        return np.array([0.0, 0.0, 0.0], dtype=float)

    try:
        c = b.center()
        return np.array([float(c[0]), float(c[1]), float(c[2])], dtype=float)
    except Exception:
        try:
            mn = b.xyz_min
            mx = b.xyz_max
            return np.array(
                [0.5 * (mn[0] + mx[0]), 0.5 * (mn[1] + mx[1]), 0.5 * (mn[2] + mx[2])],
                dtype=float,
            )
        except Exception:
            return np.array([0.0, 0.0, 0.0], dtype=float)


def cbsubmap_impl(
    session,
    star_model_obj,
    map_model_id,
    close_source=True,
    show_result=True,
):
    """
    Attach one map to each STAR row.

    Behavior changes requested
    Remove the original source map model.
    Parent each attached map under the STAR model so there is no extra group model.
    Orientation follows the arrow shown on the STAR point.
    Map is centered on the STAR point.
    Scale so map voxel size equals particle pixel size.
    """
    rows = _parse_star_rows_from_model(star_model_obj)

    src_map = _get_top_by_id(session, map_model_id)
    if src_map is None:
        session.logger.error("cbsubmap cannot find map_model by that id")
        return None

    map_vox = float(_map_voxel_size_ang(src_map))
    if map_vox < 1e-12:
        map_vox = 1.0

    placed = 0

    for i, r in enumerate(rows):
        try:
            particle_px = float(r.get("rlnImagePixelSize", 1.0))
        except Exception:
            particle_px = 1.0
        if particle_px < 1e-12:
            particle_px = 1.0

        try:
            cx = float(r.get("rlnCoordinateX", 0.0)) * particle_px
            cy = float(r.get("rlnCoordinateY", 0.0)) * particle_px
            cz = float(r.get("rlnCoordinateZ", 0.0)) * particle_px
        except Exception:
            continue

        center = np.array([cx, cy, cz], dtype=float)

        ex, ey, ez = _axes_from_relion_angles_match_artiax_arrow(
            r.get("rlnAngleRot", 0.0),
            r.get("rlnAngleTilt", 0.0),
            r.get("rlnAnglePsi", 0.0),
        )

        scale = float(particle_px) / float(map_vox)
        exs = ex * scale
        eys = ey * scale
        ezs = ez * scale

        mcopy = _copy_volume_instance(session, src_map)
        if mcopy is None:
            raise RuntimeError("cbsubmap could not create a volume instance from the source map")

        local_c = _local_center_of_model(mcopy)

        origin = center - exs * local_c[0] - eys * local_c[1] - ezs * local_c[2]

        try:
            tid = int(r.get("rlnHelicalTubeID", 0))
        except Exception:
            tid = 0

        try:
            mcopy.name = f"Submap_t{tid}_{i}"
        except Exception:
            pass

        try:
            mcopy.position = Place(axes=(exs, eys, ezs), origin=origin)
        except Exception:
            try:
                mcopy.position = Place(origin=center)
            except Exception:
                pass

        session.models.add([mcopy], parent=star_model_obj)
        placed += 1

    session.logger.info(f"cbsubmap placed {placed} submaps under model {star_model_obj.id_string}")

    if show_result:
        try:
            star_model_obj.display = True
        except Exception:
            pass
        try:
            for m in star_model_obj.child_models():
                m.display = True
        except Exception:
            pass

    # Remove the original source map on purpose
    try:
        session.models.close([src_map])
    except Exception:
        pass

    # Keep or close the star model depending on caller
    if close_source:
        try:
            session.models.close([star_model_obj])
        except Exception:
            pass

    return star_model_obj
