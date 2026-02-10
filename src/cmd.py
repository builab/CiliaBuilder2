# vim: set expandtab shiftwidth=4 softtabstop=4:

from chimerax.core.commands import CmdDesc, FloatArg, IntArg, BoolArg, StringArg
from chimerax.core.commands import run as _run
from chimerax.core.models import Model

from .io import rows_to_star_text, write_star_tempfile
from .draw import build_cilia_lines_star_rows, buildcentriole_star_rows


_CB_CLASS_COUNTER = 0


def _next_class_number():
    global _CB_CLASS_COUNTER
    _CB_CLASS_COUNTER += 1
    return _CB_CLASS_COUNTER


def _open_star(session, star_text, star_format):
    fmt = str(star_format).strip().lower()
    if fmt not in ("relion", "relion5"):
        fmt = "relion"
    star_path = write_star_tempfile(star_text, suffix=".star")
    _run(session, f'open "{star_path}" format {fmt}')
    return star_path


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
    pixel_size=10.0,
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

    created = Model(f"CB_STAR_Outer_{class_num}", session)
    session.models.add([created])
    created._cb_star_rows = rows
    created._cb_star_text = star_text

    if bool(open_star):
        try:
            created._cb_star_path = _open_star(session, star_text, star_format)
        except Exception as e:
            session.logger.warning(f"open STAR failed: {e}")

    return created


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
    pixel_size=10.0,
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

    created = Model(f"CB_STAR_Centriole_{class_num}", session)
    session.models.add([created])
    created._cb_star_rows = rows
    created._cb_star_text = star_text

    if bool(open_star):
        try:
            created._cb_star_path = _open_star(session, star_text, star_format)
        except Exception as e:
            session.logger.warning(f"open STAR failed: {e}")

    return created


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
