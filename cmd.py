import numpy as np

from chimerax.core.commands import CmdDesc, FloatArg, IntArg, BoolArg, StringArg, Color8Arg
from chimerax.core.models import Model
from chimerax.geometry import Place

from .io import rows_to_star_text, parse_star_text, filter_kwargs_for_func, normalize_builder_return
from .draw import fallback_build_straight, render_from_star_rows
from .map import (
    get_top_by_id, walk, center_of, farthest_point, unit, orthonormal, copy_volume
)


def cbstraight(session,
               length=9000.0,
               bead_spacing=400.0,
               outer_radius=700.0,
               bead_radius=110.0,
               n_outer=9,
               central_pair=True,
               cp_sep=300.0,
               tomo_name="TS_001",
               pixel_size=10.0,
               smooth=12,
               outer_color=(220, 220, 220, 255),
               inner_color=(255, 220, 120, 255),
               print_star=True,
               read_star=True,
               star_outer_only=True,
               show_vectors=True,
               arrow_length=260.0,
               shaft_radius=10.0,
               head_radius=18.0,
               head_length=60.0):

    used_fallback = False
    root = None
    beads = []
    star_rows = None
    star_text = None

    try:
        from .builder import build_straight_cilia_beads
        kwargs = dict(
            session=session,
            length=length,
            bead_spacing=bead_spacing,
            outer_radius=outer_radius,
            bead_radius=bead_radius,
            n_outer=n_outer,
            central_pair=central_pair,
            cp_sep=cp_sep,
            tomo_name=tomo_name,
            pixel_size=pixel_size,
            smooth=smooth,
            outer_color=outer_color,
            inner_color=inner_color,
        )
        kwargs2 = filter_kwargs_for_func(build_straight_cilia_beads, kwargs)
        ret = build_straight_cilia_beads(**kwargs2)
        root, beads, star_rows, star_text = normalize_builder_return(ret)

    except Exception as e:
        session.logger.warning(f"Builder not used, fallback generator active: {e}")
        used_fallback = True
        root, beads, star_rows = fallback_build_straight(
            session=session,
            length_ang=length,
            bead_spacing_ang=bead_spacing,
            outer_radius_ang=outer_radius,
            bead_radius_ang=bead_radius,
            n_outer=n_outer,
            make_central_pair=bool(central_pair),
            cp_sep_ang=cp_sep,
            tomo_name=tomo_name,
            pixel_size_ang=pixel_size,
            subdivisions=int(smooth),
            outer_color=outer_color,
            inner_color=inner_color,
        )

    if star_rows is None:
        if star_text is not None:
            _, rows = parse_star_text(star_text)
            star_rows = rows
        else:
            star_rows = []

    if star_text is None and star_rows:
        star_text = rows_to_star_text(star_rows)

    if print_star and star_text:
        session.logger.info("===== CiliaBuilder2 STAR output =====")
        for ln in star_text.splitlines():
            session.logger.info(ln)
        session.logger.info("===== end STAR output =====")

    if read_star and star_text:
        _, rows = parse_star_text(star_text)
        render_from_star_rows(
            session=session,
            star_rows=rows,
            scale_by_pixel_size=True,
            bead_radius_ang=bead_radius,
            bead_subdivisions=int(smooth),
            outer_color=outer_color,
            inner_color=inner_color,
            outer_only=bool(star_outer_only),
            outer_n=int(n_outer),
            show_vectors=show_vectors,
            arrow_length_ang=arrow_length,
            shaft_radius_ang=shaft_radius,
            head_radius_ang=head_radius,
            head_length_ang=head_length,
            arrow_segments=16,
        )

    if used_fallback:
        session.logger.info("cbstraight finished using fallback generator.")
    else:
        session.logger.info("cbstraight finished using builder module.")

    return root


cbstraight_desc = CmdDesc(
    keyword=[
        ("length", FloatArg),
        ("bead_spacing", FloatArg),
        ("outer_radius", FloatArg),
        ("bead_radius", FloatArg),
        ("n_outer", IntArg),
        ("central_pair", BoolArg),
        ("cp_sep", FloatArg),
        ("tomo_name", StringArg),
        ("pixel_size", FloatArg),
        ("smooth", IntArg),
        ("outer_color", Color8Arg),
        ("inner_color", Color8Arg),
        ("print_star", BoolArg),
        ("read_star", BoolArg),
        ("star_outer_only", BoolArg),
        ("show_vectors", BoolArg),
        ("arrow_length", FloatArg),
        ("shaft_radius", FloatArg),
        ("head_radius", FloatArg),
        ("head_length", FloatArg),
    ],
    synopsis="Build straight bead tubes, generate STAR, render arrows, optionally render only outer 9 from STAR",
)


def cbsubmap(session,
             star_model, map_model,
             close_source=True,
             show_result=True):

    star_root = get_top_by_id(session, star_model)
    map_root = get_top_by_id(session, map_model)

    if star_root is None:
        session.logger.error("cbsubmap: cannot find star_model by that #id.")
        return None
    if map_root is None:
        session.logger.error("cbsubmap: cannot find map_model by that #id.")
        return None

    beads = []
    arrows = []

    for m in walk(star_root):
        nm = getattr(m, "name", "") or ""
        if nm.startswith("STAR_Bead_T"):
            beads.append(m)
        elif nm.startswith("ArrowX_") or nm.startswith("ArrowY_") or nm.startswith("ArrowZ_"):
            arrows.append(m)

    if not beads:
        session.logger.error("cbsubmap: no STAR_Bead_* found inside star_model.")
        return None

    arrow_heads = {}
    for a in arrows:
        nm = getattr(a, "name", "") or ""
        if not nm.endswith("_head"):
            continue

        if "ArrowX_" in nm:
            key = "x"
        elif "ArrowY_" in nm:
            key = "y"
        else:
            key = "z"

        tag = nm.replace("ArrowX_", "").replace("ArrowY_", "").replace("ArrowZ_", "")
        tag = tag.replace("_head", "")
        arrow_heads.setdefault(tag, {})[key] = a

    out_root = Model("CB_Submaps", session)
    session.models.add([out_root])

    placed = 0
    for b in beads:
        bnm = getattr(b, "name", "") or ""
        tag = bnm.replace("STAR_Bead_", "")
        center = center_of(b)

        h = arrow_heads.get(tag, {})

        if "z" in h:
            pz = farthest_point(h["z"], center)
            ez = unit(pz - center) if pz is not None else np.array([0.0, 0.0, 1.0])
        else:
            ez = np.array([0.0, 0.0, 1.0], dtype=float)

        if "x" in h:
            px = farthest_point(h["x"], center)
            ex = unit(px - center) if px is not None else np.array([1.0, 0.0, 0.0])
        else:
            ex = unit([center[0], center[1], 0.0])

        if "y" in h:
            py = farthest_point(h["y"], center)
            ey = unit(py - center) if py is not None else unit(np.cross(ez, ex))
        else:
            ey = unit(np.cross(ez, ex))

        ex, ey, ez = orthonormal(ex, ey, ez)

        mcopy = copy_volume_like_artiax(session, map_root)
        if mcopy is None:
            session.logger.error("cbsubmap: failed to copy map model.")
            return None

        mcopy.name = f"Submap_{tag}"
        mcopy.position = Place(axes=(ex, ey, ez), origin=center)

        session.models.add([mcopy], parent=out_root)
        placed += 1

    session.logger.info(f"cbsubmap: placed {placed} submaps under model #{out_root.id_string}.")

    if show_result:
        try:
            out_root.display = True
        except Exception:
            pass
        for m in out_root.child_models():
            try:
                m.display = True
            except Exception:
                pass

    if close_source:
        session.models.close([star_root])

    return out_root


cbsubmap_desc = CmdDesc(
    required=[("star_model", IntArg), ("map_model", IntArg)],
    keyword=[("close_source", BoolArg), ("show_result", BoolArg)],
    synopsis="Substitute each STAR bead by a placed copy of a volume map (ArtiaX-like behavior).",
)
