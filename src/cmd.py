# vim: set expandtab shiftwidth=4 softtabstop=4:

import math
import numpy as np

from chimerax.core.commands import CmdDesc, FloatArg, IntArg, BoolArg, StringArg, OpenFileNameArg
from chimerax.core.commands import run as _run
from chimerax.core.models import Model

from .io import rows_to_star_text, write_star_tempfile
from .draw import build_cilia_lines_star_rows, buildcentriole_star_rows, build_ift_star_rows


_CB_CLASS_COUNTER = 0


def _next_class_number():
    global _CB_CLASS_COUNTER
    _CB_CLASS_COUNTER += 1
    return _CB_CLASS_COUNTER


def _safe_unit(v):
    n = math.sqrt(sum(float(c) * float(c) for c in v))
    if n < 1e-12:
        return (0.0, 0.0, 1.0)
    return tuple(float(c) / n for c in v)


def _rot_x(deg):
    a = math.radians(float(deg))
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _rot_y(deg):
    a = math.radians(float(deg))
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rot_z(deg):
    a = math.radians(float(deg))
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _matmul(a, b):
    return tuple(
        tuple(sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3))
        for r in range(3)
    )


def _matvec(a, v):
    return tuple(sum(a[r][k] * v[k] for k in range(3)) for r in range(3))


def _row_world_center(row):
    try:
        wx = row.get("_cbWorldCoordinateX", None)
        wy = row.get("_cbWorldCoordinateY", None)
        wz = row.get("_cbWorldCoordinateZ", None)
        if wx is not None and wy is not None and wz is not None:
            return (float(wx), float(wy), float(wz))
    except Exception:
        pass
    return (
        float(row.get("rlnCoordinateX", 0.0)),
        float(row.get("rlnCoordinateY", 0.0)),
        float(row.get("rlnCoordinateZ", 0.0)),
    )


def _particle_axes_from_row(row):
    try:
        ex = row.get("_cbAxisX", None)
        ey = row.get("_cbAxisY", None)
        ez = row.get("_cbAxisZ", None)
        if ex is not None and ey is not None and ez is not None:
            return _safe_unit(ex), _safe_unit(ey), _safe_unit(ez)
    except Exception:
        pass
    rot = float(row.get("rlnAngleRot", 0.0))
    tilt = float(row.get("rlnAngleTilt", 0.0))
    psi = float(row.get("rlnAnglePsi", 0.0))
    r = _matmul(_rot_z(psi), _matmul(_rot_y(tilt), _rot_z(rot)))
    rt = tuple(tuple(r[c][rr] for c in range(3)) for rr in range(3))
    ex = _safe_unit(_matvec(rt, (1.0, 0.0, 0.0)))
    ey = _safe_unit(_matvec(rt, (0.0, 1.0, 0.0)))
    ez = _safe_unit(_matvec(rt, (0.0, 0.0, 1.0)))
    return ex, ey, ez


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _arrow_head_basis(axis):
    axis = _safe_unit(axis)
    ref = (0.0, 0.0, 1.0)
    if abs(sum(axis[i] * ref[i] for i in range(3))) > 0.95:
        ref = (0.0, 1.0, 0.0)
    side = _safe_unit(_cross(axis, ref))
    return side


def _rotation_align_vector_to_vector(v_from, v_to):
    v = np.array(v_from, dtype=float)
    z = np.array(v_to, dtype=float)
    nv = float(np.linalg.norm(v))
    nz = float(np.linalg.norm(z))
    if nv < 1e-12 or nz < 1e-12:
        return np.eye(3, dtype=float)
    v /= nv
    z /= nz
    c = float(np.clip(np.dot(v, z), -1.0, 1.0))
    if c > 1.0 - 1e-8:
        return np.eye(3, dtype=float)
    if c < -1.0 + 1e-8:
        return np.array(((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)), dtype=float)
    axis = np.cross(v, z)
    n = float(np.linalg.norm(axis))
    if n < 1e-12:
        return np.eye(3, dtype=float)
    axis /= n
    x, y, zz = axis
    K = np.array(
        [
            [0.0, -zz, y],
            [zz, 0.0, -x],
            [-y, x, 0.0],
        ],
        dtype=float,
    )
    return np.eye(3, dtype=float) + K + (K @ K) * ((1.0 - c) / (n * n))


def _find_child_group(parent, tag):
    for child in parent.child_models():
        if getattr(child, "_cb_group_tag", None) == tag:
            return child
    return None


def _ensure_cb_root(session):
    for model in session.models.list():
        if getattr(model, "_cb_root", False):
            _ensure_cb_default_groups(session, model)
            return model
    root = Model("CiliaBuilder2", session)
    root._cb_root = True
    session.models.add([root])
    _ensure_cb_default_groups(session, root)
    return root


def _ensure_cb_default_groups(session, root=None):
    if root is None:
        root = _ensure_cb_root(session)
    wanted = (
        ("star_models", "STAR Models"),
        ("maps", "Maps/Models"),
        ("membrane", "Membrane"),
    )
    groups = {}
    for tag, name in wanted:
        group = _find_child_group(root, tag)
        if group is None:
            group = Model(name, session)
            group._cb_group_tag = tag
            root.add([group])
        else:
            try:
                group.name = name
            except Exception:
                pass
        groups[tag] = group
    return groups


def _ensure_cb_group(session, tag, name):
    groups = _ensure_cb_default_groups(session)
    group = groups.get(tag)
    if group is not None:
        return group
    root = _ensure_cb_root(session)
    group = Model(name, session)
    group._cb_group_tag = tag
    root.add([group])
    return group


def _ensure_cb_star_group(session):
    return _ensure_cb_group(session, "star_models", "STAR Models")


def _ensure_cb_map_group(session):
    return _ensure_cb_group(session, "maps", "Maps")


def _ensure_cb_membrane_group(session):
    return _ensure_cb_group(session, "membrane", "Membrane")


def _add_to_cb_star_group(session, model):
    _ensure_cb_star_group(session).add([model])
    return model


def _add_to_cb_map_group(session, model):
    _ensure_cb_map_group(session).add([model])
    return model


def _add_to_cb_membrane_group(session, model):
    _ensure_cb_membrane_group(session).add([model])
    return model


def _marker_path_tangents(control_points):
    points = [np.array(p, dtype=float) for p in (control_points or [])]
    if len(points) < 2:
        return []
    tangents = []
    for index, point in enumerate(points):
        if index == 0:
            vec = points[1] - point
        elif index == len(points) - 1:
            vec = point - points[index - 1]
        else:
            vec = points[index + 1] - points[index - 1]
        norm = float(np.linalg.norm(vec))
        if norm <= 1e-9:
            vec = np.array((0.0, 0.0, 1.0), dtype=float)
            norm = 1.0
        tangents.append(tuple(float(v) for v in (vec / norm)))
    return tangents


def build_marker_path_model(
    session,
    name,
    control_points,
    path_mode="curve",
    color=(255, 170, 70, 255),
    tube_radius=20.0,
    segment_subdivisions=12,
    circle_subdivisions=18,
):
    from chimerax.core.models import Surface
    from chimerax.surface.tube import tube_spline, tube_through_points

    points = []
    for point in control_points or []:
        try:
            xyz = tuple(float(v) for v in point[:3])
        except Exception:
            continue
        if len(xyz) == 3:
            points.append(xyz)
    if len(points) < 2:
        raise ValueError("Marker path needs at least 2 control points")

    mode = str(path_mode or "curve").strip().lower()
    if mode not in ("curve", "line"):
        mode = "curve"
    tube_radius = max(0.1, float(tube_radius))

    if mode == "curve" and len(points) >= 3:
        varray, narray, tarray = tube_spline(
            np.array(points, dtype=np.float32),
            radius=float(tube_radius),
            segment_subdivisions=max(2, int(segment_subdivisions)),
            circle_subdivisions=max(6, int(circle_subdivisions)),
        )
    else:
        tangents = _marker_path_tangents(points)
        varray, narray, tarray = tube_through_points(
            np.array(points, dtype=np.float32),
            np.array(tangents, dtype=np.float32),
            radius=float(tube_radius),
            circle_subdivisions=max(6, int(circle_subdivisions)),
        )

    root = Model(name, session)
    root._cb_generated_marker_path = True
    root._cb_attach_source = False
    root._cb_marker_path_state = {
        "control_points": [[float(v) for v in point] for point in points],
        "path_mode": mode,
        "tube_radius": float(tube_radius),
        "display_mode": "tube_surface",
    }
    _add_to_cb_map_group(session, root)

    surface = Surface("Tube", session)
    surface.set_geometry(
        np.array(varray, dtype=np.float32),
        np.array(narray, dtype=np.float32),
        np.array(tarray, dtype=np.int32),
    )
    surface._cb_generated_marker_path = True
    surface._cb_attach_source = False
    try:
        surface.color = color
    except Exception:
        pass
    root.add([surface])
    return root


def _annulus_cap_triangles(outer_ring, inner_ring, reverse=False):
    tris = []
    nc = len(outer_ring)
    for i in range(nc):
        j = (i + 1) % nc
        if reverse:
            tris.append((outer_ring[i], inner_ring[i], inner_ring[j]))
            tris.append((outer_ring[i], inner_ring[j], outer_ring[j]))
        else:
            tris.append((outer_ring[i], inner_ring[j], inner_ring[i]))
            tris.append((outer_ring[i], outer_ring[j], inner_ring[j]))
    return tris


def buildmembrane_surface(
    session,
    name,
    center,
    axis,
    length,
    diameter,
    thickness,
    distortion_level=1.0,
    distortion_seed=None,
    color=(180, 180, 190, 180),
):
    from chimerax.core.models import Surface
    from chimerax.shape.shape import cylinder_geometry
    from chimerax.surface import calculate_vertex_normals

    length = float(length)
    diameter = float(diameter)
    thickness = float(thickness)
    distortion_level = max(0.0, float(distortion_level))
    if length <= 0.0:
        raise ValueError("Membrane length must be > 0")
    if diameter <= 0.0:
        raise ValueError("Membrane diameter must be > 0")
    if thickness <= 0.0:
        raise ValueError("Membrane thickness must be > 0")

    outer_radius = 0.5 * diameter
    inner_radius = max(1e-6, outer_radius - thickness)
    if inner_radius >= outer_radius:
        raise ValueError("Membrane thickness must be smaller than half the diameter")

    nc = max(32, int(math.ceil((2.0 * math.pi * outer_radius) / 80.0)))
    nz = max(2, int(math.ceil(length / max(80.0, thickness))))

    outer_v, outer_t = cylinder_geometry(outer_radius, length, nz, nc, caps=False)
    inner_v, inner_t = cylinder_geometry(inner_radius, length, nz, nc, caps=False)
    inner_t = inner_t[:, ::-1]

    inner_offset = len(outer_v)
    inner_t = inner_t + inner_offset

    outer_bottom = list(range(0, nc))
    outer_top_start = (nz - 1) * nc
    outer_top = list(range(outer_top_start, outer_top_start + nc))
    inner_bottom = [inner_offset + i for i in range(0, nc)]
    inner_top_start = inner_offset + (nz - 1) * nc
    inner_top = [inner_top_start + i for i in range(0, nc)]

    bottom_tris = _annulus_cap_triangles(outer_bottom, inner_bottom, reverse=True)
    top_tris = _annulus_cap_triangles(outer_top, inner_top, reverse=False)

    if distortion_seed is None:
        distortion_seed = int(np.random.default_rng().integers(0, 2**31 - 1))

    vertices = np.concatenate((outer_v, inner_v), axis=0).astype(np.float32)
    rng = np.random.default_rng(distortion_seed)
    radial_amp = distortion_level * min(0.45 * thickness, 0.05 * diameter)
    axial_amp = distortion_level * min(0.20 * thickness, 0.015 * length)
    distortion_modes = [
        (
            mode,
            rng.uniform(0.0, 2.0 * math.pi),
            rng.uniform(-1.0, 1.0),
            rng.uniform(-1.0, 1.0),
        )
        for mode in range(1, 10)
    ]

    def field(verts):
        xy = verts[:, :2]
        z = verts[:, 2]
        theta = np.arctan2(xy[:, 1], xy[:, 0])
        zn = (z / max(length, 1e-6)) + 0.5
        radial_wave = np.zeros(len(theta), dtype=np.float32)
        axial_wave = np.zeros(len(theta), dtype=np.float32)
        for mode, phase, radial_weight, axial_weight in distortion_modes:
            radial_wave += (
                radial_weight
                * np.cos((mode * theta) + phase + (0.45 * mode) * math.pi * zn)
            ).astype(np.float32)
            axial_wave += (
                axial_weight
                * np.sin((mode * theta) + phase - (0.35 * mode + 0.65) * math.pi * zn)
            ).astype(np.float32)
        radial_wave /= float(len(distortion_modes))
        axial_wave /= float(len(distortion_modes))
        return radial_wave.astype(np.float32), axial_wave.astype(np.float32)

    def distort(verts):
        radial_wave, axial_wave = field(verts)
        xy = verts[:, :2]
        radii = np.linalg.norm(xy, axis=1)
        radial_dir = np.zeros_like(xy)
        mask = radii > 1e-6
        radial_dir[mask] = xy[mask] / radii[mask, None]
        verts[:, :2] += radial_dir * (radial_amp * radial_wave)[:, None]
        verts[:, 2] += axial_amp * axial_wave
        return verts

    vertices[:len(outer_v)] = distort(vertices[:len(outer_v)])
    vertices[len(outer_v):] = distort(vertices[len(outer_v):])
    triangles = np.concatenate(
        (
            np.array(outer_t, dtype=np.int32),
            np.array(inner_t, dtype=np.int32),
            np.array(bottom_tris, dtype=np.int32),
            np.array(top_tris, dtype=np.int32),
        ),
        axis=0,
    )
    normals = calculate_vertex_normals(vertices, triangles)

    axis = np.array(axis, dtype=float)
    naxis = float(np.linalg.norm(axis))
    axis = np.array((0.0, 0.0, 1.0), dtype=float) if naxis < 1e-12 else axis / naxis
    R = _rotation_align_vector_to_vector((0.0, 0.0, 1.0), axis)
    vertices = (vertices @ R.T) + np.array(center, dtype=float)
    normals = normals @ R.T

    surface = Surface(name, session)
    surface.set_geometry(vertices.astype(np.float32), normals.astype(np.float32), triangles.astype(np.int32))
    try:
        surface.color = color
    except Exception:
        pass
    surface._cb_generated_membrane = True
    surface._cb_attach_source = False
    surface._cb_membrane_state = {
        "center": [float(v) for v in center],
        "axis": [float(v) for v in axis],
        "length": float(length),
        "diameter": float(diameter),
        "thickness": float(thickness),
        "distortion_level": float(distortion_level),
        "distortion_seed": int(distortion_seed),
    }
    _add_to_cb_membrane_group(session, surface)
    return surface


def _render_star_model(session, parent_model, rows, show_arrows):
    try:
        from chimerax.markers.markers import MarkerSet, create_link
    except Exception:
        return None

    for child in list(parent_model.child_models()):
        if getattr(child, "_cb_rendered_particles", False):
            try:
                session.models.close([child])
            except Exception:
                pass

    marker_set = MarkerSet(session, name="Particles")
    marker_set._cb_rendered_particles = True
    parent_model.add([marker_set])

    for row_index, row in enumerate(rows):
        px = float(row.get("rlnImagePixelSize", 1.0) or 1.0)
        cx, cy, cz = _row_world_center(row)
        center = (cx, cy, cz)
        glyph_scale = max(0.25, min(4.0, 10.0 / max(px, 1e-6)))
        center_radius = 8.0 * glyph_scale
        axis_len = 24.0 * glyph_scale
        link_radius = 2.4 * glyph_scale
        base = marker_set.create_marker(center, (50, 80, 255, 255), center_radius)
        for atom in (base,):
            try:
                atom._cb_star_row_index = int(row_index)
            except Exception:
                pass
        if not bool(show_arrows):
            continue
        ex, ey, ez = _particle_axes_from_row(row)
        axes = (
            ((255, 0, 0, 255), ex),
            ((255, 255, 0, 255), ey),
            ((0, 0, 255, 255), ez),
        )
        for color, vec in axes:
            tip_xyz = (
                center[0] + axis_len * vec[0],
                center[1] + axis_len * vec[1],
                center[2] + axis_len * vec[2],
            )
            shaft_len = 0.78 * axis_len
            shaft_xyz = (
                center[0] + shaft_len * vec[0],
                center[1] + shaft_len * vec[1],
                center[2] + shaft_len * vec[2],
            )
            shaft = marker_set.create_marker(shaft_xyz, color, max(0.6, 1.4 * glyph_scale))
            tip = marker_set.create_marker(tip_xyz, color, max(0.2, 0.5 * glyph_scale))
            for atom in (shaft, tip):
                try:
                    atom._cb_star_row_index = int(row_index)
                except Exception:
                    pass
            create_link(base, shaft, rgba=color, radius=link_radius)
            create_link(shaft, tip, rgba=color, radius=max(0.8, 1.4 * glyph_scale))

            side = _arrow_head_basis(vec)
            head_back = 0.18 * axis_len
            head_side = 0.10 * axis_len
            for sign in (-1.0, 1.0):
                head_xyz = (
                    tip_xyz[0] - head_back * vec[0] + sign * head_side * side[0],
                    tip_xyz[1] - head_back * vec[1] + sign * head_side * side[1],
                    tip_xyz[2] - head_back * vec[2] + sign * head_side * side[2],
                )
                head = marker_set.create_marker(head_xyz, color, max(0.2, 0.4 * glyph_scale))
                try:
                    head._cb_star_row_index = int(row_index)
                except Exception:
                    pass
                create_link(tip, head, rgba=color, radius=max(0.7, 1.1 * glyph_scale))
    return marker_set


def _open_star(session, star_text, star_format):
    return write_star_tempfile(star_text, suffix=".star")


def _create_star_model(session, name, rows, star_text, open_star, star_format, show_arrows, view_orient=True):
    created = Model(name, session)
    _add_to_cb_star_group(session, created)
    created._cb_star_rows = rows
    created._cb_star_text = star_text
    if bool(open_star):
        created._cb_star_path = _open_star(session, star_text, star_format)
        _render_star_model(session, created, rows, show_arrows)
        if bool(view_orient):
            try:
                _run(session, "view orient")
            except Exception:
                pass
    return created


def cbui(session):
    from chimerax.core.commands import run
    run(session, "tool show CiliaBuilder2")


cbui_desc = CmdDesc(synopsis="Open CiliaBuilder2 UI")


def cbopenapr(session, apr_path, name=""):
    from .local_apr import open_local_cellpack_package

    model, info = open_local_cellpack_package(session, apr_path, name=name)
    _add_to_cb_map_group(session, model)
    _log_local_cellpack_load(session, info)
    return model


cbopenapr_desc = CmdDesc(
    required=[("apr_path", OpenFileNameArg)],
    keyword=[
        ("name", StringArg),
    ],
    synopsis="Open a local cellPACK package from disk.",
)


def _log_local_cellpack_load(session, info):
    kind = str(info.get("package_kind", "apr") or "apr").lower()
    if kind == "manifest":
        detail = ""
        if info.get("membrane_bundle_loaded", False):
            detail = (
                " Loaded membrane APR "
                f"{info.get('membrane_apr_path', '')} "
                f"({int(info.get('membrane_compartment_count', 0))} compartments, "
                f"{int(info.get('membrane_ingredient_count', 0))} ingredient entries, "
                f"{int(info.get('membrane_placement_count', 0))} placements)."
            )
        session.logger.info(
            "Opened exported cellPACK manifest package "
            f"{info['path']} "
            f"({int(info.get('output_count', 0))} outputs, "
            f"{int(info.get('model_count', 0))} opened models)."
            f"{detail}"
        )
        return
    if kind == "recipe":
        detail = ""
        if info.get("membrane_bundle_loaded", False):
            detail = (
                " Loaded membrane APR "
                f"{info.get('membrane_apr_path', '')} "
                f"({int(info.get('membrane_compartment_count', 0))} compartments, "
                f"{int(info.get('membrane_ingredient_count', 0))} ingredient entries, "
                f"{int(info.get('membrane_placement_count', 0))} placements)."
            )
        session.logger.info(
            "Opened exported cellPACK recipe package "
            f"{info['path']} "
            f"({int(info.get('output_count', 0))} outputs, "
            f"{int(info.get('model_count', 0))} opened models)."
            f"{detail}"
        )
        return
    session.logger.info(
        "Opened local cellPACK APR package "
        f"{info['apr_path']} "
        f"({int(info['compartment_count'])} compartments, "
        f"{int(info['ingredient_count'])} ingredient entries, "
        f"{int(info['placement_count'])} placements)."
    )


def cbstraight(
    session,
    angle_set=0.0,
    length=9000.0,
    n_doublet=9,
    radius=700.0,
    spacing=960.0,
    z_offset=0.0,
    doublet_offset=0.0,
    random_spacing=False,
    random_max_diff=0.0,
    show_arrows=False,
    tomo_name="TS_001",
    pixel_size=1.0,
    open_star=True,
    star_format="relion",
    print_star=False,
):
    class_num = _next_class_number()

    rows = build_cilia_lines_star_rows(
        n_lines=int(n_doublet),
        length_ang=float(length),
        bead_spacing_ang=float(spacing),
        outer_radius_ang=float(radius),
        tomo_name=str(tomo_name),
        pixel_size_ang=float(pixel_size),
        tube_id_offset=0,
        angle_set_deg=float(angle_set),
        doublet_offset_deg=float(doublet_offset),
        z_offset_ang=float(z_offset),
        random_spacing=bool(random_spacing),
        random_max_diff=float(random_max_diff),
        class_number=int(class_num),
        rng_seed=None,
    )

    star_text = rows_to_star_text(rows)
    if print_star:
        session.logger.info("===== CiliaBuilder2 STAR output =====")
        for ln in star_text.splitlines():
            session.logger.info(ln)
        session.logger.info("===== end STAR output =====")

    return _create_star_model(
        session,
        f"Microtubules STAR {class_num}",
        rows,
        star_text,
        open_star,
        star_format,
        show_arrows,
    )


cbstraight_desc = CmdDesc(
    keyword=[
        ("angle_set", FloatArg),
        ("length", FloatArg),
        ("n_doublet", IntArg),
        ("radius", FloatArg),
        ("spacing", FloatArg),
        ("z_offset", FloatArg),
        ("doublet_offset", FloatArg),
        ("random_spacing", BoolArg),
        ("random_max_diff", FloatArg),
        ("show_arrows", BoolArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("open_star", BoolArg),
        ("star_format", StringArg),
        ("print_star", BoolArg),
    ],
    synopsis="Build outer cilia STAR only (ordered lines, outward red axis).",
)


def buildcentriole(
    session,
    length=2000.0,
    spacing=320.0,
    z_offset=0.0,
    tube_id=100,
    x_offset=0.0,
    random_spacing=False,
    random_max_diff=0.0,
    show_arrows=False,
    tomo_name="TS_001",
    pixel_size=1.0,
    open_star=True,
    star_format="relion",
    print_star=False,
    name_prefix="Central pair STAR",
):
    class_num = _next_class_number()

    rows = buildcentriole_star_rows(
        length_ang=float(length),
        bead_spacing_ang=float(spacing),
        tomo_name=str(tomo_name),
        pixel_size_ang=float(pixel_size),
        tube_id=int(tube_id),
        x_offset_ang=float(x_offset),
        z_offset_ang=float(z_offset),
        class_number=int(class_num),
        random_spacing=bool(random_spacing),
        random_max_diff=float(random_max_diff),
        rng_seed=None,
    )

    star_text = rows_to_star_text(rows)
    if print_star:
        session.logger.info("===== CiliaBuilder2 STAR output =====")
        for ln in star_text.splitlines():
            session.logger.info(ln)
        session.logger.info("===== end STAR output =====")

    return _create_star_model(
        session,
        f"{name_prefix} {class_num}",
        rows,
        star_text,
        open_star,
        star_format,
        show_arrows,
    )


buildcentriole_desc = CmdDesc(
    keyword=[
        ("length", FloatArg),
        ("spacing", FloatArg),
        ("z_offset", FloatArg),
        ("tube_id", IntArg),
        ("x_offset", FloatArg),
        ("random_spacing", BoolArg),
        ("random_max_diff", FloatArg),
        ("show_arrows", BoolArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("open_star", BoolArg),
        ("star_format", StringArg),
        ("print_star", BoolArg),
        ("name_prefix", StringArg),
    ],
    synopsis="Build central pair STAR only (single center line).",
)


def buildift(
    session,
    n_particles=100,
    length=9000.0,
    n_doublet=9,
    radius=700.0,
    radial_offset=0.0,
    angle_set=0.0,
    z_offset=0.0,
    tomo_name="TS_001",
    pixel_size=1.0,
    line_mode=False,
    open_star=True,
    star_format="relion",
    print_star=False,
):
    class_num = _next_class_number()

    rows = build_ift_star_rows(
        n_lines=int(n_doublet),
        n_particles=int(n_particles),
        length_ang=float(length),
        outer_radius_ang=float(radius),
        radial_offset_ang=float(radial_offset),
        tomo_name=str(tomo_name),
        pixel_size_ang=float(pixel_size),
        angle_set_deg=float(angle_set),
        z_offset_ang=float(z_offset),
        class_number=int(class_num),
        line_mode=bool(line_mode),
        rng_seed=None,
    )

    star_text = rows_to_star_text(rows)
    if print_star:
        session.logger.info("===== CiliaBuilder2 STAR output =====")
        for ln in star_text.splitlines():
            session.logger.info(ln)
        session.logger.info("===== end STAR output =====")

    return _create_star_model(
        session,
        f"IFT STAR {class_num}",
        rows,
        star_text,
        open_star,
        star_format,
        True,
    )


buildift_desc = CmdDesc(
    keyword=[
        ("n_particles", IntArg),
        ("length", FloatArg),
        ("n_doublet", IntArg),
        ("radius", FloatArg),
        ("radial_offset", FloatArg),
        ("angle_set", FloatArg),
        ("z_offset", FloatArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("line_mode", BoolArg),
        ("open_star", BoolArg),
        ("star_format", StringArg),
        ("print_star", BoolArg),
    ],
    synopsis="Build random IFT particle STAR on microtubules.",
)
