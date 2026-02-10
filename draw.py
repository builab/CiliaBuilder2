# vim: set expandtab shiftwidth=4 softtabstop=4:

import math
import numpy as np


def _z_positions_with_jitter(length_ang, spacing_ang, z_offset_ang, random_enable, random_max_diff, rng):
    length_ang = float(length_ang)
    spacing_ang = float(spacing_ang)
    z_offset_ang = float(z_offset_ang)

    if spacing_ang <= 0.0:
        return np.array([z_offset_ang], dtype=float)

    zs = [z_offset_ang]
    while True:
        z = zs[-1]
        if (z - z_offset_ang) >= length_ang - 1e-9:
            break

        step = spacing_ang
        if random_enable and random_max_diff > 0.0:
            step += float(rng.uniform(-random_max_diff, random_max_diff))

        step = max(step, spacing_ang * 0.05, 1e-6)
        zs.append(z + step)

    if zs[-1] > z_offset_ang + length_ang + 1e-6:
        zs[-1] = z_offset_ang + length_ang

    return np.array(zs, dtype=float)


def build_cilia_lines_star_rows(
    n_lines,
    length_ang,
    bead_spacing_ang,
    outer_radius_ang,
    tomo_name,
    pixel_size_ang,
    tube_id_offset=0,
    angle_set_deg=0.0,
    doublet_offset_deg=0.0,
    z_offset_ang=0.0,
    random_spacing=False,
    random_max_diff=0.0,
    class_number=1,
    rng_seed=None,
):
    n = int(max(1, min(9, int(n_lines))))
    rows = []

    base_rng = np.random.default_rng(rng_seed)

    for k in range(n):
        rng = np.random.default_rng(base_rng.integers(0, 2**63 - 1))

        phi = 2.0 * math.pi * k / float(n)
        phi_deg = float(math.degrees(phi))

        phi_deg_total = phi_deg + float(angle_set_deg) + float(doublet_offset_deg)

        x = float(outer_radius_ang) * math.cos(math.radians(phi_deg_total))
        y = float(outer_radius_ang) * math.sin(math.radians(phi_deg_total))
        tube_id = int(tube_id_offset) + (k + 1)

        z_vals = _z_positions_with_jitter(
            length_ang=length_ang,
            spacing_ang=bead_spacing_ang,
            z_offset_ang=z_offset_ang,
            random_enable=bool(random_spacing),
            random_max_diff=float(abs(random_max_diff)),
            rng=rng,
        )

        for z in z_vals:
            rows.append(
                {
                    "rlnTomoName": str(tomo_name),
                    "rlnCoordinateX": float(x) / float(pixel_size_ang),
                    "rlnCoordinateY": float(y) / float(pixel_size_ang),
                    "rlnCoordinateZ": float(z) / float(pixel_size_ang),
                    # IMPORTANT, keep outward red axis in ArtiaX
                    "rlnAngleRot": -float(phi_deg_total),
                    "rlnAngleTilt": 0.0,
                    "rlnAnglePsi": 0.0,
                    "rlnImagePixelSize": float(pixel_size_ang),
                    "rlnHelicalTubeID": int(tube_id),
                    "rlnClassNumber": int(class_number),
                }
            )

    return rows


def buildcentriole_star_rows(
    length_ang,
    bead_spacing_ang,
    tomo_name,
    pixel_size_ang,
    tube_id=100,
    z_offset_ang=0.0,
    class_number=1,
    random_spacing=False,
    random_max_diff=0.0,
    rng_seed=None,
):
    rng = np.random.default_rng(rng_seed)

    z_vals = _z_positions_with_jitter(
        length_ang=length_ang,
        spacing_ang=bead_spacing_ang,
        z_offset_ang=z_offset_ang,
        random_enable=bool(random_spacing),
        random_max_diff=float(abs(random_max_diff)),
        rng=rng,
    )

    rows = []
    for z in z_vals:
        rows.append(
            {
                "rlnTomoName": str(tomo_name),
                "rlnCoordinateX": 0.0,
                "rlnCoordinateY": 0.0,
                "rlnCoordinateZ": float(z) / float(pixel_size_ang),
                "rlnAngleRot": 0.0,
                "rlnAngleTilt": 0.0,
                "rlnAnglePsi": 0.0,
                "rlnImagePixelSize": float(pixel_size_ang),
                "rlnHelicalTubeID": int(tube_id),
                "rlnClassNumber": int(class_number),
            }
        )

    return rows
