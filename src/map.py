# vim: set expandtab shiftwidth=4 softtabstop=4:

import math
import os
import numpy as np

from chimerax.core.models import Model
from chimerax.core.commands import run as _run
from chimerax.geometry import Place
try:
    from chimerax.geometry import Places
except Exception:
    Places = None


# ----------------------------------------------------------------------
# CALIBRATION
# ----------------------------------------------------------------------
# This is the deep fix.
# These constants define how the source map's local coordinates should be
# converted into the particle's local coordinates before placement.
#
# Tune these once, then all copies will place consistently.
#
# local translation, in source-map local units
CALIB_SHIFT_X = 0.0
CALIB_SHIFT_Y = 0.0
CALIB_SHIFT_Z = 0.0

# local extra rotation, degrees
CALIB_ROT_X_DEG = 0.0
CALIB_ROT_Y_DEG = 0.0
CALIB_ROT_Z_DEG = -90.0

# uniform extra scale
CALIB_SCALE = 1.0

# keep original source map for iterative tuning/debug
CLOSE_SOURCE_MAP = False

# map-fit scaling follows physical units directly (no hidden fudge factors)
PARTICLE_PIXEL_SIZE_SCALE_FOR_MAP = 1.0


def _get_model_by_ref(session, id1):
    want = str(id1)
    for m in session.models.list():
        if m.id_string == want:
            return m
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
        raise RuntimeError("Star model has no STAR rows")
    return rows


def _safe_unit(v):
    v = np.array(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return v / n


def _rot_x(deg):
    a = math.radians(float(deg))
    c = math.cos(a)
    s = math.sin(a)
    return np.array(
        [[1.0, 0.0, 0.0],
         [0.0, c, -s],
         [0.0, s,  c]],
        dtype=float,
    )


def _rot_y(deg):
    a = math.radians(float(deg))
    c = math.cos(a)
    s = math.sin(a)
    return np.array(
        [[ c, 0.0, s],
         [0.0, 1.0, 0.0],
         [-s, 0.0, c]],
        dtype=float,
    )


def _rot_z(deg):
    a = math.radians(float(deg))
    c = math.cos(a)
    s = math.sin(a)
    return np.array(
        [[c, -s, 0.0],
         [s,  c, 0.0],
         [0.0, 0.0, 1.0]],
        dtype=float,
    )


def _rotation_align_vector_to_vector(v_from, v_to):
    v = _safe_unit(v_from)
    z = _safe_unit(v_to)
    c = float(np.clip(np.dot(v, z), -1.0, 1.0))
    if c > 1.0 - 1e-8:
        return np.eye(3, dtype=float)
    if c < -1.0 + 1e-8:
        return _rot_x(180.0)
    axis = _safe_unit(np.cross(v, z))
    x, y, zz = axis
    s = float(np.linalg.norm(np.cross(v, z)))
    K = np.array(
        [
            [0.0, -zz, y],
            [zz, 0.0, -x],
            [-y, x, 0.0],
        ],
        dtype=float,
    )
    return np.eye(3, dtype=float) + K + (K @ K) * ((1.0 - c) / (s * s))


def _rotation_about_axis(axis, deg):
    axis = _safe_unit(axis)
    a = math.radians(float(deg))
    c = math.cos(a)
    s = math.sin(a)
    x, y, z = axis
    K = np.array(
        [
            [0.0, -z, y],
            [z, 0.0, -x],
            [-y, x, 0.0],
        ],
        dtype=float,
    )
    outer = np.outer(axis, axis)
    return c * np.eye(3, dtype=float) + s * K + (1.0 - c) * outer


def _relion_rotation_matrix(rot_deg, tilt_deg, psi_deg):
    """
    Relion ZYZ:
    R = Rz(psi) * Ry(tilt) * Rz(rot)
    """
    return _rot_z(float(psi_deg)) @ _rot_y(float(tilt_deg)) @ _rot_z(float(rot_deg))


def _particle_axes_from_star(rot_deg, tilt_deg, psi_deg):
    """
    Use the same conceptual model as ArtiaX style particle display:
    compute one stable particle transform from metadata.

    We use R^T here because that usually matches the displayed particle axes
    in ChimeraX style viewers better than raw R.
    """
    R = _relion_rotation_matrix(rot_deg, tilt_deg, psi_deg)
    Rt = R.T

    ex = _safe_unit(Rt @ np.array([1.0, 0.0, 0.0], dtype=float))
    ey = _safe_unit(Rt @ np.array([0.0, 1.0, 0.0], dtype=float))
    ez = _safe_unit(Rt @ np.array([0.0, 0.0, 1.0], dtype=float))
    return ex, ey, ez


def _copy_source_instance(session, src):
    # 1 direct copy
    try:
        if hasattr(src, "copy"):
            return src.copy()
    except Exception:
        pass

    # 1b direct surface geometry clone for STL / generic surfaces
    if _is_surface_like(src):
        try:
            surf_type = src.__class__
            clone = surf_type(str(getattr(src, "name", "surface copy")), session)
            va = getattr(src, "vertices", None)
            na = getattr(src, "normals", None)
            ta = getattr(src, "triangles", None)
            if va is not None and ta is not None:
                clone.set_geometry(va, na, ta)
                try:
                    clone.color = src.color
                except Exception:
                    pass
                return clone
        except Exception:
            pass

    # 2 rebuild from grid data if this is a volume-like model
    if _is_volume_like(src):
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

    # 3 reopen from path
    path = getattr(src, "path", None)
    if not path:
        try:
            path = src.data.path
        except Exception:
            path = None
    if not path:
        try:
            path = src.filename
        except Exception:
            path = None

    if path:
        try:
            _run(session, f'open "{path}"')
            return session.models.list()[-1]
        except Exception:
            return None

    return None


def _is_volume_like(model_obj):
    cls_name = model_obj.__class__.__name__.lower()
    if "volume" in cls_name or "map" in cls_name:
        return True
    try:
        d = getattr(model_obj, "data", None)
        if d is not None and hasattr(d, "matrix"):
            return True
    except Exception:
        pass
    try:
        gd = getattr(model_obj, "grid_data", None)
        if gd is not None:
            return True
    except Exception:
        pass
    model_name = str(getattr(model_obj, "name", "") or "").lower()
    return model_name.endswith((".mrc", ".map", ".ccp4", ".mrcs"))


def _is_surface_like(model_obj):
    cls_name = model_obj.__class__.__name__.lower()
    if "surface" in cls_name or "stl" in cls_name:
        return True
    try:
        vertices = getattr(model_obj, "vertices", None)
        triangles = getattr(model_obj, "triangles", None)
        if vertices is not None and triangles is not None:
            return True
    except Exception:
        pass
    model_name = str(getattr(model_obj, "name", "") or "").lower()
    return model_name.endswith(".stl")


def _matching_volume_for_surface(session, src_surface):
    names = []
    src_name = str(getattr(src_surface, "name", "") or "")
    if src_name:
        names.append(os.path.splitext(os.path.basename(src_name))[0].lower())
    src_path = getattr(src_surface, "path", None)
    if src_path:
        names.append(os.path.splitext(os.path.basename(str(src_path)))[0].lower())
    want = {n for n in names if n}
    if not want:
        return None
    for model in session.models.list():
        if model is src_surface or not _is_volume_like(model):
            continue
        candidates = []
        model_name = str(getattr(model, "name", "") or "")
        if model_name:
            candidates.append(os.path.splitext(os.path.basename(model_name))[0].lower())
        model_path = getattr(model, "path", None)
        if model_path:
            candidates.append(os.path.splitext(os.path.basename(str(model_path)))[0].lower())
        if any(c in want for c in candidates if c):
            return model
    return None


def _try_get_step(obj):
    try:
        st = obj.step
        if st is None:
            return None
        return (float(st[0]), float(st[1]), float(st[2]))
    except Exception:
        return None


def _get_map_voxel_size_ang(vol):
    """
    Best effort read of voxel size in angstrom.
    """
    candidates = []

    try:
        if hasattr(vol, "data") and hasattr(vol.data, "grid_data") and vol.data.grid_data is not None:
            s = _try_get_step(vol.data.grid_data)
            if s:
                candidates.append(s)
    except Exception:
        pass

    try:
        if hasattr(vol, "grid_data") and vol.grid_data is not None:
            s = _try_get_step(vol.grid_data)
            if s:
                candidates.append(s)
    except Exception:
        pass

    try:
        if hasattr(vol, "data") and vol.data is not None:
            s = _try_get_step(vol.data)
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


def _bounds_center_local(model_obj):
    """
    Only used as a fallback anchor.
    The deep fix is the explicit CALIB_SHIFT above.
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
                [
                    0.5 * (mn[0] + mx[0]),
                    0.5 * (mn[1] + mx[1]),
                    0.5 * (mn[2] + mx[2]),
                ],
                dtype=float,
            )
        except Exception:
            return np.array([0.0, 0.0, 0.0], dtype=float)


def _bounds_size_local(model_obj):
    try:
        model_obj.position = Place()
    except Exception:
        pass
    try:
        b = model_obj.bounds()
    except Exception:
        b = None
    if b is None:
        return np.array([1.0, 1.0, 1.0], dtype=float)
    try:
        mn = np.array([float(v) for v in b.xyz_min], dtype=float)
        mx = np.array([float(v) for v in b.xyz_max], dtype=float)
        d = mx - mn
        if np.all(np.isfinite(d)):
            return np.abs(d)
    except Exception:
        pass
    return np.array([1.0, 1.0, 1.0], dtype=float)


def _long_axis_vector_local(model_obj):
    try:
        vertices = getattr(model_obj, "vertices", None)
        if vertices is not None and len(vertices) >= 3:
            va = np.array(vertices, dtype=float)
            center = va.mean(axis=0)
            dv = va - center
            cov = dv.T @ dv
            evals, evecs = np.linalg.eigh(cov)
            axis = evecs[:, int(np.argmax(evals))]
            return _safe_unit(axis)
    except Exception:
        pass

    size = _bounds_size_local(model_obj)
    axis = int(np.argmax(size))
    basis = np.eye(3, dtype=float)
    return basis[:, axis]


def _map_data_origin_local(vol):
    for owner in (getattr(vol, "data", None), getattr(vol, "grid_data", None)):
        if owner is None:
            continue
        o = getattr(owner, "origin", None)
        if o is None:
            continue
        try:
            return np.array([float(o[0]), float(o[1]), float(o[2])], dtype=float)
        except Exception:
            pass
    return None


def _shared_map_anchor_local(session, src_map):
    """
    Use the map's own offset if it has one; otherwise use ChimeraX's built-in
    density center-of-mass for the selected map. Compute once and reuse.
    """
    probe = _copy_source_instance(session, src_map)
    if probe is None:
        return np.array([0.0, 0.0, 0.0], dtype=float)
    try:
        try:
            probe.position = Place()
        except Exception:
            pass

        origin = _map_data_origin_local(probe)
        if origin is not None and float(np.linalg.norm(origin)) > 1e-12:
            return origin

        try:
            from chimerax.map.measure import volume_center_of_mass

            center = volume_center_of_mass(probe)
            return np.array([float(center[0]), float(center[1]), float(center[2])], dtype=float)
        except Exception:
            return _bounds_center_local(probe)
    finally:
        try:
            session.models.close([probe])
        except Exception:
            pass


def _shared_source_anchor_local(session, src_model):
    if _is_volume_like(src_model):
        return _shared_map_anchor_local(session, src_model)

    if _is_surface_like(src_model):
        match = _matching_volume_for_surface(session, src_model)
        if match is not None:
            return _shared_map_anchor_local(session, match)
        probe = _copy_source_instance(session, src_model)
        if probe is not None:
            try:
                return _bounds_center_local(probe)
            finally:
                try:
                    session.models.close([probe])
                except Exception:
                    pass
        return _bounds_center_local(src_model)

    return np.array([0.0, 0.0, 0.0], dtype=float)


def _calibration_rotation_matrix(rx_deg=CALIB_ROT_X_DEG, ry_deg=CALIB_ROT_Y_DEG, rz_deg=CALIB_ROT_Z_DEG):
    return (
        _rot_z(rz_deg)
        @ _rot_y(ry_deg)
        @ _rot_x(rx_deg)
    )


def _source_long_axis_local(session, src_model):
    probe = _copy_source_instance(session, src_model)
    if probe is None:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    try:
        axis = _long_axis_vector_local(probe)
    finally:
        try:
            session.models.close([probe])
        except Exception:
            pass
    return _safe_unit(axis)


def cbsubmap_impl(
    session,
    star_model_obj,
    map_model_id,
    close_source=True,
    show_result=True,
    rotate_xy_90=False,
    single_big_object=False,
    attach_diameter_scale=1.0,
    attach_pixel_scale=0.1,
    attach_z_offset_deg=0.0,
    attach_all_z_offset_deg=0.0,
    attach_vertical_shift=0.0,
    attach_auto_align_long_axis=False,
    attach_inout_flip=False,
    attach_updown_flip=False,
    attach_axis_rot_x_deg=CALIB_ROT_X_DEG,
    attach_axis_rot_y_deg=CALIB_ROT_Y_DEG,
    attach_axis_rot_z_deg=CALIB_ROT_Z_DEG,
):
    """
    Deep-fix placement pipeline

    T_world = T_particle × T_calibration

    T_particle comes from STAR row
    T_calibration is one fixed local correction for the source map
    """
    rows = _parse_star_rows_from_model(star_model_obj)

    src_map = _get_model_by_ref(session, map_model_id)
    if src_map is None:
        session.logger.error("cbsubmap cannot find map_model by that id")
        return None
    try:
        from .cmd import _add_to_cb_map_group
        _add_to_cb_map_group(session, src_map)
    except Exception:
        pass

    source_is_volume = _is_volume_like(src_map)
    map_vox_ang = float(_get_map_voxel_size_ang(src_map)) if source_is_volume else 1.0
    if map_vox_ang < 1e-12:
        map_vox_ang = 1.0

    out_root = Model(f"{star_model_obj.name} maps", session)
    try:
        from .cmd import _add_to_cb_map_group
        _add_to_cb_map_group(session, out_root)
    except Exception:
        session.models.add([out_root])

    Rc = _calibration_rotation_matrix(
        rx_deg=float(attach_axis_rot_x_deg),
        ry_deg=float(attach_axis_rot_y_deg),
        rz_deg=float(attach_axis_rot_z_deg),
    )
    calib_shift = np.array([CALIB_SHIFT_X, CALIB_SHIFT_Y, CALIB_SHIFT_Z], dtype=float)
    shared_anchor = _shared_source_anchor_local(session, src_map)
    source_long_axis = _source_long_axis_local(session, src_map) if bool(attach_auto_align_long_axis) else None

    placed = 0
    places = []
    base_copy = None
    tube_ids = sorted({int(float(r.get("rlnHelicalTubeID", 0))) for r in rows})
    tube_index = {tid: i for i, tid in enumerate(tube_ids)}

    for i, r in enumerate(rows):
        try:
            particle_px_ang = float(r.get("rlnImagePixelSize", 1.0))
        except Exception:
            particle_px_ang = 1.0
        if particle_px_ang < 1e-12:
            particle_px_ang = 1.0

        # STAR coords are already in model/particle units.
        try:
            cx = float(r.get("rlnCoordinateX", 0.0))
            cy = float(r.get("rlnCoordinateY", 0.0))
            cz = float(r.get("rlnCoordinateZ", 0.0))
        except Exception:
            continue

        # Diameter tuning is applied in XY only, relative to model coordinates.
        center = np.array(
            [
                cx * float(attach_diameter_scale),
                cy * float(attach_diameter_scale),
                cz,
            ],
            dtype=float,
        )

        # Particle basis from STAR
        ex, ey, ez = _particle_axes_from_star(
            r.get("rlnAngleRot", 0.0),
            r.get("rlnAngleTilt", 0.0),
            r.get("rlnAnglePsi", 0.0),
        )
        display_blue_axis = _safe_unit(ez)
        Rp = np.column_stack((ex, ey, ez))

        # Copy map
        if bool(single_big_object):
            if base_copy is None:
                base_copy = _copy_source_instance(session, src_map)
                if base_copy is None:
                    raise RuntimeError("cbsubmap could not create an instance from the source model")
            mcopy = base_copy
        else:
            mcopy = _copy_source_instance(session, src_map)
            if mcopy is None:
                raise RuntimeError("cbsubmap could not create an instance from the source model")

        # Use map offset if present, otherwise built-in ChimeraX center-of-mass.
        local_anchor = shared_anchor + calib_shift

        # Scale rule from physical units: map voxel angstrom / particle pixel angstrom.
        effective_particle_px_ang = float(particle_px_ang) * float(PARTICLE_PIXEL_SIZE_SCALE_FOR_MAP)
        if effective_particle_px_ang < 1e-12:
            effective_particle_px_ang = float(particle_px_ang)
        if source_is_volume:
            base_scale = float(map_vox_ang) / float(effective_particle_px_ang)
            base_scale *= float(attach_pixel_scale)
        else:
            base_scale = 1.0
        scale = base_scale * float(CALIB_SCALE)
        if scale < 1e-12:
            scale = 1.0

        # Final world basis
        Rw = Rp @ Rc
        exw = _safe_unit(Rw[:, 0]) * scale
        eyw = _safe_unit(Rw[:, 1]) * scale
        ezw = _safe_unit(Rw[:, 2]) * scale
        if bool(rotate_xy_90):
            # +90 degrees in the local XY plane (about local Z).
            exw, eyw = eyw, -exw
        if bool(attach_inout_flip):
            exw, eyw = -exw, -eyw
        try:
            tid = int(float(r.get("rlnHelicalTubeID", 0)))
        except Exception:
            tid = 0
        line_idx = int(tube_index.get(tid, 0))
        per_line_z_offset = float(attach_z_offset_deg) * float(line_idx)
        all_z_offset = float(attach_all_z_offset_deg)
        total_z_offset = per_line_z_offset + all_z_offset
        if abs(total_z_offset) > 1e-12:
            a = math.radians(total_z_offset)
            ca = math.cos(a)
            sa = math.sin(a)
            ex0 = exw.copy()
            ey0 = eyw.copy()
            exw = ex0 * ca - ey0 * sa
            eyw = ex0 * sa + ey0 * ca
        if source_long_axis is not None:
            current_long_world = _safe_unit(
                source_long_axis[0] * exw
                + source_long_axis[1] * eyw
                + source_long_axis[2] * ezw
            )
            target_long_world = -display_blue_axis if bool(attach_updown_flip) else display_blue_axis
            Ralign = _rotation_align_vector_to_vector(current_long_world, target_long_world)
            exw = Ralign @ exw
            eyw = Ralign @ eyw
            ezw = Ralign @ ezw

        # Make chosen local anchor land exactly on STAR point
        origin = (
            center
            - exw * float(local_anchor[0])
            - eyw * float(local_anchor[1])
            - ezw * float(local_anchor[2])
        )
        if abs(float(attach_vertical_shift)) > 1e-12:
            origin = origin + _safe_unit(ezw) * float(attach_vertical_shift)

        place = Place(axes=(exw, eyw, ezw), origin=origin)

        if bool(single_big_object):
            places.append(place)
            placed += 1
            continue

        try:
            mcopy.name = f"Attached_t{tid}_{i}"
        except Exception:
            pass

        try:
            mcopy.position = place
        except Exception:
            try:
                mcopy.position = Place(origin=center)
            except Exception:
                pass

        session.models.add([mcopy], parent=out_root)
        placed += 1

    if bool(single_big_object) and base_copy is not None and len(places) > 0:
        single_added = False
        if Places is not None:
            try:
                base_copy.positions = Places(places)
                base_copy.name = f"Attached_All_{len(places)}"
                session.models.add([base_copy], parent=out_root)
                single_added = True
            except Exception:
                single_added = False
        if not single_added:
            # Fallback if volume instancing is unavailable in current runtime.
            session.models.close([out_root])
            out_root = Model(f"{star_model_obj.name} maps", session)
            try:
                from .cmd import _add_to_cb_map_group
                _add_to_cb_map_group(session, out_root)
            except Exception:
                session.models.add([out_root])
            for i, p in enumerate(places):
                mcopy = _copy_source_instance(session, src_map)
                if mcopy is None:
                    continue
                try:
                    mcopy.name = f"Attached_fallback_{i}"
                except Exception:
                    pass
                try:
                    mcopy.position = p
                except Exception:
                    pass
                session.models.add([mcopy], parent=out_root)

    session.logger.info(
        f"cbsubmap placed {placed} maps under model {out_root.id_string}. "
        f"base calibration uses voxel match and explicit local calibration transform."
    )

    try:
        out_root.display = bool(show_result)
    except Exception:
        pass
    try:
        out_root.set_selected(True)
    except Exception:
        pass

    if close_source:
        try:
            session.models.close([star_model_obj])
        except Exception:
            pass

    if CLOSE_SOURCE_MAP:
        try:
            session.models.close([src_map])
        except Exception:
            pass

    return out_root
