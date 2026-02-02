# vim: set expandtab shiftwidth=4 softtabstop=4:

import math
import numpy as np


def build_cilia_lines_star_rows(
    n_lines,
    length_ang,
    bead_spacing_ang,
    outer_radius_ang,
    tomo_name,
    pixel_size_ang,
    tube_id_offset=0,
    angle_set_deg=0.0,
    z_offset_ang=0.0,
    doublet_offset_deg=0.0,
):
    """
    STAR rows for outer cilia lines

    ArtiaX axis display uses R transpose on unit axes, so use negative rot
    This makes X outward, Y tangential, Z upward

    angle_set_deg and doublet_offset_deg are applied as a global ring rotation
    so the red axis remains outward
    """
    n = int(max(1, min(9, int(n_lines))))
    px = float(pixel_size_ang)
    z_vals = np.arange(0.0, float(length_ang) + 1e-6, float(bead_spacing_ang))

    rows = []
    base_offset = float(angle_set_deg) + float(doublet_offset_deg)

    for k in range(n):
        phi = 2.0 * math.pi * k / float(n)
        phi_deg = float(math.degrees(phi)) + base_offset

        # rotate the ring itself by base_offset to keep ordering stable
        phi_pos = math.radians(phi_deg)
        x = float(outer_radius_ang) * math.cos(phi_pos)
        y = float(outer_radius_ang) * math.sin(phi_pos)

        tube_id = int(tube_id_offset) + (k + 1)

        for z in z_vals:
            rows.append(
                {
                    "rlnTomoName": str(tomo_name),
                    "rlnCoordinateX": float(x) / px,
                    "rlnCoordinateY": float(y) / px,
                    "rlnCoordinateZ": float(z + float(z_offset_ang)) / px,

                    # IMPORTANT
                    # ArtiaX shows axes as R transpose applied to unit axes
                    # use negative phi so red points outward
                    "rlnAngleRot": -phi_deg,
                    "rlnAngleTilt": 0.0,
                    "rlnAnglePsi": 0.0,

                    "rlnImagePixelSize": px,
                    "rlnHelicalTubeID": int(tube_id),
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
):
    """
    One single line in the center, not a ring.
    """
    px = float(pixel_size_ang)
    z_vals = np.arange(0.0, float(length_ang) + 1e-6, float(bead_spacing_ang))

    rows = []
    for z in z_vals:
        rows.append(
            {
                "rlnTomoName": str(tomo_name),
                "rlnCoordinateX": 0.0,
                "rlnCoordinateY": 0.0,
                "rlnCoordinateZ": float(z + float(z_offset_ang)) / px,

                "rlnAngleRot": 0.0,
                "rlnAngleTilt": 0.0,
                "rlnAnglePsi": 0.0,

                "rlnImagePixelSize": px,
                "rlnHelicalTubeID": int(tube_id),
            }
        )

    return rows
