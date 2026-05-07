# vim: set expandtab shiftwidth=4 softtabstop=4:

import math
import random


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
    class_number=1,
    random_spacing=False,
    random_max_diff=0.0,
    rng_seed=None,
):
    """
    Outer lines on a perfect circle.
    Pixel size is stored in STAR and coordinates are converted to pixels.
    """

    n = int(max(1, min(9, n_lines)))
    length_ang = float(length_ang)
    bead_spacing_ang = float(bead_spacing_ang)
    outer_radius_ang = float(outer_radius_ang)
    pixel_size_ang = float(pixel_size_ang)

    if pixel_size_ang <= 0.0:
        raise ValueError("pixel_size_ang must be > 0")
    if bead_spacing_ang <= 0.0:
        raise ValueError("bead_spacing_ang must be > 0")

    angle_set_deg = float(angle_set_deg)
    doublet_offset_deg = float(doublet_offset_deg)
    z_offset_ang = float(z_offset_ang)

    class_number = int(class_number)
    step_deg = 360.0 / float(n)

    use_random = bool(random_spacing)
    max_diff = abs(float(random_max_diff))
    if bool(random_spacing):
        default_cap = 0.49 * bead_spacing_ang
        if max_diff <= 0.0:
            max_diff = default_cap
        else:
            max_diff = min(max_diff, default_cap)

    if rng_seed is None:
        rng = random.Random()
    else:
        rng = random.Random(int(rng_seed))

    rows = []

    for k in range(n):
        # perfect circle placement
        phi_deg = angle_set_deg + k * step_deg
        phi = math.radians(phi_deg)

        x_ang = outer_radius_ang * math.cos(phi)
        y_ang = outer_radius_ang * math.sin(phi)
        tube_id = int(tube_id_offset) + (k + 1)

        # Interpret 180 degrees in the UI as neutral, then rotate each line
        # an additional 90 degrees clockwise.
        rot_deg = -(phi_deg + (doublet_offset_deg - 180.0) + 90.0)

        line_offset = rng.uniform(-max_diff, max_diff) if use_random else 0.0
        current_z = float(z_offset_ang)
        z_list = []

        while current_z <= float(z_offset_ang) + length_ang + 1e-6:
            z_list.append(current_z + line_offset)
            current_z += bead_spacing_ang

        for z_ang in z_list:
            rows.append(
                {
                    "rlnTomoName": str(tomo_name),
                    # convert Angstrom world coords into STAR pixel coords
                    "rlnCoordinateX": float(x_ang) / pixel_size_ang,
                    "rlnCoordinateY": float(y_ang) / pixel_size_ang,
                    "rlnCoordinateZ": float(z_ang) / pixel_size_ang,
                    "rlnAngleRot": float(rot_deg),
                    "rlnAngleTilt": 0.0,
                    "rlnAnglePsi": 0.0,
                    # store the real pixel size from UI
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
    """
    One single center line.
    Pixel size is stored in STAR and coordinates are converted to pixels.
    """

    length_ang = float(length_ang)
    bead_spacing_ang = float(bead_spacing_ang)
    pixel_size_ang = float(pixel_size_ang)

    if pixel_size_ang <= 0.0:
        raise ValueError("pixel_size_ang must be > 0")
    if bead_spacing_ang <= 0.0:
        raise ValueError("bead_spacing_ang must be > 0")

    if rng_seed is None:
        rng = random.Random()
    else:
        rng = random.Random(int(rng_seed))

    use_random = bool(random_spacing)
    max_diff = abs(float(random_max_diff))
    if use_random:
        default_cap = 0.49 * bead_spacing_ang
        if max_diff <= 0.0:
            max_diff = default_cap
        else:
            max_diff = min(max_diff, default_cap)
    line_offset = rng.uniform(-max_diff, max_diff) if use_random else 0.0
    current_z = float(z_offset_ang)
    z_list = []

    while current_z <= float(z_offset_ang) + length_ang + 1e-6:
        z_list.append(current_z + line_offset)
        current_z += bead_spacing_ang

    rows = []

    for z_ang in z_list:
        rows.append(
            {
                "rlnTomoName": str(tomo_name),
                "rlnCoordinateX": 0.0,
                "rlnCoordinateY": 0.0,
                "rlnCoordinateZ": float(z_ang) / pixel_size_ang,
                "rlnAngleRot": 0.0,
                "rlnAngleTilt": 0.0,
                "rlnAnglePsi": 0.0,
                # store the real pixel size from UI
                "rlnImagePixelSize": float(pixel_size_ang),
                "rlnHelicalTubeID": int(tube_id),
                "rlnClassNumber": int(class_number),
            }
        )

    return rows


def build_ift_star_rows(
    n_lines,
    n_particles,
    length_ang,
    outer_radius_ang,
    radial_offset_ang,
    tomo_name,
    pixel_size_ang,
    angle_set_deg=0.0,
    z_offset_ang=0.0,
    class_number=1,
    line_mode=False,
    rng_seed=None,
):
    """
    IFT particles distributed on a larger circle around an origin ring.
    """

    n = int(max(1, min(9, n_lines)))
    n_particles = int(max(1, n_particles))
    length_ang = float(length_ang)
    outer_radius_ang = float(outer_radius_ang)
    radial_offset_ang = float(radial_offset_ang)
    pixel_size_ang = float(pixel_size_ang)
    angle_set_deg = float(angle_set_deg)
    z_offset_ang = float(z_offset_ang)
    class_number = int(class_number)

    if pixel_size_ang <= 0.0:
        raise ValueError("pixel_size_ang must be > 0")

    if rng_seed is None:
        rng = random.Random()
    else:
        rng = random.Random(int(rng_seed))

    step_deg = 360.0 / float(n)
    radius_ang = outer_radius_ang + radial_offset_ang
    rows = []

    if bool(line_mode):
        per_line = max(1, int(math.ceil(float(n_particles) / float(n))))
        spacing = max(1e-6, float(length_ang) / float(max(1, per_line)))
        created = 0
        for k in range(n):
            phi_deg = angle_set_deg + k * step_deg
            phi = math.radians(phi_deg)
            x_ang = radius_ang * math.cos(phi)
            y_ang = radius_ang * math.sin(phi)
            tube_id = k + 1
            rot_deg = -phi_deg + 90.0
            start_shift = rng.uniform(0.0, max(0.0, min(spacing, length_ang)))
            for j in range(per_line):
                if created >= n_particles:
                    break
                z_ang = z_offset_ang + start_shift + j * spacing
                if z_ang > z_offset_ang + length_ang:
                    break
                rows.append(
                    {
                        "rlnTomoName": str(tomo_name),
                        "rlnCoordinateX": float(x_ang) / pixel_size_ang,
                        "rlnCoordinateY": float(y_ang) / pixel_size_ang,
                        "rlnCoordinateZ": float(z_ang) / pixel_size_ang,
                        "rlnAngleRot": float(rot_deg),
                        "rlnAngleTilt": 0.0,
                        "rlnAnglePsi": 0.0,
                        "rlnImagePixelSize": float(pixel_size_ang),
                        "rlnHelicalTubeID": int(tube_id),
                        "rlnClassNumber": int(class_number),
                    }
                )
                created += 1
    else:
        for _ in range(n_particles):
            k = rng.randrange(n)
            phi_deg = angle_set_deg + k * step_deg
            phi = math.radians(phi_deg)

            x_ang = radius_ang * math.cos(phi)
            y_ang = radius_ang * math.sin(phi)
            z_ang = z_offset_ang + rng.uniform(0.0, max(0.0, length_ang))
            tube_id = k + 1
            rot_deg = -phi_deg + 90.0

            rows.append(
                {
                    "rlnTomoName": str(tomo_name),
                    "rlnCoordinateX": float(x_ang) / pixel_size_ang,
                    "rlnCoordinateY": float(y_ang) / pixel_size_ang,
                    "rlnCoordinateZ": float(z_ang) / pixel_size_ang,
                    "rlnAngleRot": float(rot_deg),
                    "rlnAngleTilt": 0.0,
                    "rlnAnglePsi": 0.0,
                    "rlnImagePixelSize": float(pixel_size_ang),
                    "rlnHelicalTubeID": int(tube_id),
                    "rlnClassNumber": int(class_number),
                }
            )

    return rows
