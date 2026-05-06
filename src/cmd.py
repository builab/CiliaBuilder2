# vim: set expandtab shiftwidth=4 softtabstop=4:

import math

from chimerax.core.commands import CmdDesc, FloatArg, IntArg, BoolArg, StringArg
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


def _particle_axes_from_row(row):
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


def _find_child_group(parent, tag):
    for child in parent.child_models():
        if getattr(child, "_cb_group_tag", None) == tag:
            return child
    return None


def _ensure_cb_root(session):
    for model in session.models.list():
        if getattr(model, "_cb_root", False):
            return model
    root = Model("CiliaBuilder2", session)
    root._cb_root = True
    session.models.add([root])
    return root


def _ensure_cb_group(session, tag, name):
    root = _ensure_cb_root(session)
    group = _find_child_group(root, tag)
    if group is not None:
        return group
    group = Model(name, session)
    group._cb_group_tag = tag
    root.add([group])
    return group


def _ensure_cb_star_group(session):
    return _ensure_cb_group(session, "star_models", "STAR Models")


def _ensure_cb_map_group(session):
    return _ensure_cb_group(session, "maps", "Maps")


def _add_to_cb_star_group(session, model):
    _ensure_cb_star_group(session).add([model])
    return model


def _add_to_cb_map_group(session, model):
    _ensure_cb_map_group(session).add([model])
    return model


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

    for row in rows:
        px = float(row.get("rlnImagePixelSize", 1.0) or 1.0)
        cx = float(row.get("rlnCoordinateX", 0.0))
        cy = float(row.get("rlnCoordinateY", 0.0))
        cz = float(row.get("rlnCoordinateZ", 0.0))
        center = (cx, cy, cz)
        glyph_scale = max(0.25, min(4.0, 10.0 / max(px, 1e-6)))
        center_radius = 8.0 * glyph_scale
        axis_len = 24.0 * glyph_scale
        link_radius = 2.4 * glyph_scale
        base = marker_set.create_marker(center, (50, 80, 255, 255), center_radius)
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
                create_link(tip, head, rgba=color, radius=max(0.7, 1.1 * glyph_scale))
    return marker_set


def _open_star(session, star_text, star_format):
    return write_star_tempfile(star_text, suffix=".star")


def _create_star_model(session, name, rows, star_text, open_star, star_format, show_arrows):
    created = Model(name, session)
    _add_to_cb_star_group(session, created)
    created._cb_star_rows = rows
    created._cb_star_text = star_text
    if bool(open_star):
        created._cb_star_path = _open_star(session, star_text, star_format)
        _render_star_model(session, created, rows, show_arrows)
        try:
            _run(session, "view orient")
        except Exception:
            pass
    return created


def cbui(session):
    from chimerax.core.commands import run
    run(session, "tool show CiliaBuilder2")


cbui_desc = CmdDesc(synopsis="Open CiliaBuilder2 UI")


def cbstraight(
    session,
    angle_set=0.0,
    length=9000.0,
    n_doublet=9,
    radius=700.0,
    spacing=400.0,
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
    spacing=400.0,
    z_offset=0.0,
    tube_id=100,
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

    rows = buildcentriole_star_rows(
        length_ang=float(length),
        bead_spacing_ang=float(spacing),
        tomo_name=str(tomo_name),
        pixel_size_ang=float(pixel_size),
        tube_id=int(tube_id),
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
        f"Central apparatus STAR {class_num}",
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
        ("random_spacing", BoolArg),
        ("random_max_diff", FloatArg),
        ("show_arrows", BoolArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("open_star", BoolArg),
        ("star_format", StringArg),
        ("print_star", BoolArg),
    ],
    synopsis="Build centriole STAR only (single center line).",
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
