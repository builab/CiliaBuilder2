# vim: set expandtab shiftwidth=4 softtabstop=4:

from chimerax.core.commands import CmdDesc, FloatArg, IntArg, BoolArg, StringArg
from chimerax.core.commands import run as _run
from chimerax.core.models import Model

from .io import rows_to_star_text, write_star_tempfile, normalize_star_format
from .draw import build_cilia_lines_star_rows, buildcentriole_star_rows
from .map import cbsubmap_impl


def _open_map_return_id(session, map_path):
    if not map_path:
        return None
    try:
        _run(session, f'open "{map_path}"')
        m = session.models.list()[-1]
        if getattr(m, "id", None) and len(m.id) == 1:
            return int(m.id[0])
    except Exception as e:
        session.logger.warning(f"open map failed {e}")
    return None


def cbstraight(
    session,
    n_cilia=9,
    length=9000.0,
    spacing=400.0,
    radius=700.0,
    angle_set=0.0,
    z_offset=0.0,
    doublet_offset=0.0,
    tomo_name="TS_001",
    pixel_size=10.0,
    open_star=True,
    star_format="relion",
    print_star=False,
    map_path="",
    auto_map=False,
    close_source_after_map=True,
    build_centriole=False,
    centriole_length=2000.0,
    centriole_spacing=400.0,
    centriole_map_path="",
    **_ignored,
):
    """
    Build outer cilia STAR, optionally also build one central centriole line.
    No geometry models are created, only STAR that ArtiaX can load.
    """

    n = int(max(1, min(9, int(n_cilia))))

    rows = []
    rows.extend(
        build_cilia_lines_star_rows(
            n_lines=n,
            length_ang=float(length),
            bead_spacing_ang=float(spacing),
            outer_radius_ang=float(radius),
            tomo_name=str(tomo_name),
            pixel_size_ang=float(pixel_size),
            tube_id_offset=0,
            angle_set_deg=float(angle_set),
            z_offset_ang=float(z_offset),
            doublet_offset_deg=float(doublet_offset),
        )
    )

    if bool(build_centriole):
        rows.extend(
            buildcentriole_star_rows(
                length_ang=float(centriole_length),
                bead_spacing_ang=float(centriole_spacing),
                tomo_name=str(tomo_name),
                pixel_size_ang=float(pixel_size),
                tube_id=100,
                z_offset_ang=float(z_offset),
            )
        )

    star_text = rows_to_star_text(rows)

    if bool(print_star):
        session.logger.info("===== CiliaBuilder2 STAR output =====")
        for ln in star_text.splitlines():
            session.logger.info(ln)
        session.logger.info("===== end STAR output =====")

    created = Model("CB_STAR", session)
    session.models.add([created])
    created._cb_star_rows = rows
    created._cb_star_text = star_text

    star_path = write_star_tempfile(star_text, suffix=".star")
    created._cb_star_path = star_path

    if bool(open_star):
        fmt = normalize_star_format(star_format)
        try:
            _run(session, f'open "{star_path}" format {fmt}')
        except Exception as e:
            session.logger.warning(f"open STAR failed with format {fmt}, error {e}")

    if bool(auto_map):
        # prefer user map_path, else do nothing
        mid = _open_map_return_id(session, map_path)
        if mid is None:
            session.logger.error("auto_map true but map_path could not be opened")
        else:
            cbsubmap_impl(
                session=session,
                star_model_obj=created,
                map_model_id=int(mid),
                close_source=bool(close_source_after_map),
                show_result=True,
            )

    # optional centriole map placement, if user wants different template
    if bool(auto_map) and bool(build_centriole) and centriole_map_path:
        mid2 = _open_map_return_id(session, centriole_map_path)
        if mid2 is not None:
            cbsubmap_impl(
                session=session,
                star_model_obj=created,
                map_model_id=int(mid2),
                close_source=False,
                show_result=True,
            )

    return created


cbstraight_desc = CmdDesc(
    keyword=[
        ("n_cilia", IntArg),
        ("length", FloatArg),
        ("spacing", FloatArg),
        ("radius", FloatArg),
        ("angle_set", FloatArg),
        ("z_offset", FloatArg),
        ("doublet_offset", FloatArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("open_star", BoolArg),
        ("star_format", StringArg),
        ("print_star", BoolArg),
        ("map_path", StringArg),
        ("auto_map", BoolArg),
        ("close_source_after_map", BoolArg),
        ("build_centriole", BoolArg),
        ("centriole_length", FloatArg),
        ("centriole_spacing", FloatArg),
        ("centriole_map_path", StringArg),
    ],
    synopsis="Build ordered outer cilia STAR with outward axes, optional central centriole line, optional map placement.",
)


def buildcentriole(
    session,
    length=2000.0,
    spacing=400.0,
    z_offset=0.0,
    tomo_name="TS_001",
    pixel_size=10.0,
    open_star=True,
    star_format="relion",
    print_star=False,
    map_path="",
    auto_map=False,
    close_source_after_map=True,
    **_ignored,
):
    rows = buildcentriole_star_rows(
        length_ang=float(length),
        bead_spacing_ang=float(spacing),
        tomo_name=str(tomo_name),
        pixel_size_ang=float(pixel_size),
        tube_id=100,
        z_offset_ang=float(z_offset),
    )

    star_text = rows_to_star_text(rows)

    if bool(print_star):
        session.logger.info("===== CiliaBuilder2 STAR output =====")
        for ln in star_text.splitlines():
            session.logger.info(ln)
        session.logger.info("===== end STAR output =====")

    created = Model("CB_Centriole_STAR", session)
    session.models.add([created])
    created._cb_star_rows = rows
    created._cb_star_text = star_text

    star_path = write_star_tempfile(star_text, suffix=".star")
    created._cb_star_path = star_path

    if bool(open_star):
        fmt = normalize_star_format(star_format)
        try:
            _run(session, f'open "{star_path}" format {fmt}')
        except Exception as e:
            session.logger.warning(f"open STAR failed with format {fmt}, error {e}")

    if bool(auto_map):
        mid = _open_map_return_id(session, map_path)
        if mid is None:
            session.logger.error("auto_map true but map_path could not be opened")
        else:
            cbsubmap_impl(
                session=session,
                star_model_obj=created,
                map_model_id=int(mid),
                close_source=bool(close_source_after_map),
                show_result=True,
            )

    return created


buildcentriole_desc = CmdDesc(
    keyword=[
        ("length", FloatArg),
        ("spacing", FloatArg),
        ("z_offset", FloatArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("open_star", BoolArg),
        ("star_format", StringArg),
        ("print_star", BoolArg),
        ("map_path", StringArg),
        ("auto_map", BoolArg),
        ("close_source_after_map", BoolArg),
    ],
    synopsis="Build one central centriole line STAR, optional map placement.",
)


def cbui(session):
    from .tool import get_or_create_tool
    return get_or_create_tool(session)


cbui_desc = CmdDesc(synopsis="Open CiliaBuilder2 UI")
