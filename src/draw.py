import math
import numpy as np

from chimerax.core.models import Model, Surface


def safe_normalize(v):
    n = float(np.linalg.norm(v))
    if n <= 1e-12:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return np.array(v, dtype=float) / n


def euler_relion_zyz(rot_deg, tilt_deg, psi_deg):
    r = math.radians(float(rot_deg))
    t = math.radians(float(tilt_deg))
    p = math.radians(float(psi_deg))

    cr, sr = math.cos(r), math.sin(r)
    ct, st = math.cos(t), math.sin(t)
    cp, sp = math.cos(p), math.sin(p)

    Rz_r = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]], dtype=float)
    Ry_t = np.array([[ct, 0.0, st], [0.0, 1.0, 0.0], [-st, 0.0, ct]], dtype=float)
    Rz_p = np.array([[cp, -sp, 0.0], [sp, cp, 0.0], [0.0, 0.0, 1.0]], dtype=float)

    return Rz_p @ Ry_t @ Rz_r


def make_sphere_surface(session, name, center_xyz, radius, subdivisions=10, color=(220, 220, 220, 255)):
    from chimerax.surface.shapes import sphere_geometry
    va, na, ta = sphere_geometry(int(subdivisions))
    va = np.array(va, dtype=float)
    va = va * float(radius)
    va = va + np.array(center_xyz, dtype=float)
    s = Surface(name, session)
    s.set_geometry(va, na, ta)
    s.color = color
    return s


def make_cylinder_surface(session, name, p0, p1, radius, segments=16, color=(80, 80, 255, 255)):
    p0 = np.array(p0, dtype=float)
    p1 = np.array(p1, dtype=float)
    axis = p1 - p0
    axis_u = safe_normalize(axis)

    if abs(float(axis_u[2])) < 0.9:
        a = np.array([0.0, 0.0, 1.0], dtype=float)
    else:
        a = np.array([0.0, 1.0, 0.0], dtype=float)

    u = safe_normalize(np.cross(axis_u, a))
    v = safe_normalize(np.cross(axis_u, u))

    seg = int(max(6, segments))
    verts = []
    norms = []
    for i in range(seg):
        ang = 2.0 * math.pi * i / seg
        c = math.cos(ang)
        s = math.sin(ang)
        n = c * u + s * v
        norms.append(n)
        verts.append(p0 + float(radius) * n)
    for i in range(seg):
        ang = 2.0 * math.pi * i / seg
        c = math.cos(ang)
        s = math.sin(ang)
        n = c * u + s * v
        norms.append(n)
        verts.append(p1 + float(radius) * n)

    verts = np.array(verts, dtype=float)
    norms = np.array(norms, dtype=float)

    tris = []
    for i in range(seg):
        j = (i + 1) % seg
        tris.append([i, seg + i, seg + j])
        tris.append([i, seg + j, j])
    tris = np.array(tris, dtype=np.int32)

    srf = Surface(name, session)
    srf.set_geometry(verts, norms, tris)
    srf.color = color
    return srf


def make_cone_surface(session, name, base_center, tip, base_radius, segments=16, color=(80, 80, 255, 255)):
    base_center = np.array(base_center, dtype=float)
    tip = np.array(tip, dtype=float)
    axis = tip - base_center
    axis_u = safe_normalize(axis)

    if abs(float(axis_u[2])) < 0.9:
        a = np.array([0.0, 0.0, 1.0], dtype=float)
    else:
        a = np.array([0.0, 1.0, 0.0], dtype=float)

    u = safe_normalize(np.cross(axis_u, a))
    v = safe_normalize(np.cross(axis_u, u))

    seg = int(max(6, segments))
    verts = []
    norms = []
    for i in range(seg):
        ang = 2.0 * math.pi * i / seg
        c = math.cos(ang)
        s = math.sin(ang)
        ring_dir = c * u + s * v
        verts.append(base_center + float(base_radius) * ring_dir)
        n = safe_normalize(ring_dir * float(np.linalg.norm(axis)) + ring_dir)
        norms.append(n)

    tip_index = len(verts)
    verts.append(tip)
    norms.append(axis_u)

    verts = np.array(verts, dtype=float)
    norms = np.array(norms, dtype=float)

    tris = []
    for i in range(seg):
        j = (i + 1) % seg
        tris.append([i, j, tip_index])
    tris = np.array(tris, dtype=np.int32)

    srf = Surface(name, session)
    srf.set_geometry(verts, norms, tris)
    srf.color = color
    return srf


def make_arrow_surfaces(session, name_prefix, p0, p1, shaft_radius, head_radius, head_length, segments, color):
    p0 = np.array(p0, dtype=float)
    p1 = np.array(p1, dtype=float)
    v = p1 - p0
    L = float(np.linalg.norm(v))
    if L <= 1e-6:
        return []

    u = v / L
    hl = float(min(head_length, 0.7 * L))
    shaft_end = p1 - hl * u

    shaft = make_cylinder_surface(session, f"{name_prefix}_shaft", p0, shaft_end, shaft_radius, segments, color)
    head = make_cone_surface(session, f"{name_prefix}_head", shaft_end, p1, head_radius, segments, color)
    return [shaft, head]


def fallback_build_straight(session,
                            length_ang=9000.0,
                            bead_spacing_ang=250.0,
                            outer_radius_ang=700.0,
                            bead_radius_ang=70.0,
                            n_outer=9,
                            make_central_pair=True,
                            cp_sep_ang=300.0,
                            tomo_name="TS_001",
                            pixel_size_ang=10.0,
                            subdivisions=10,
                            outer_color=(220, 220, 220, 255),
                            inner_color=(255, 220, 120, 255)):
    root = Model("CB_Cilia", session)
    session.models.add([root])

    bead_models = []
    star_rows = []
    z_vals = np.arange(0.0, float(length_ang) + 1e-6, float(bead_spacing_ang))

    for k in range(int(n_outer)):
        phi = 2.0 * math.pi * k / float(n_outer)
        phi_deg = math.degrees(phi)
        x = float(outer_radius_ang) * math.cos(phi)
        y = float(outer_radius_ang) * math.sin(phi)
        tube_id = k + 1

        for z in z_vals:
            center = (x, y, float(z))
            s = make_sphere_surface(session, f"Bead_T{tube_id}", center, bead_radius_ang, subdivisions, outer_color)
            session.models.add([s], parent=root)
            bead_models.append(s)

            star_rows.append({
                "rlnTomoName": tomo_name,
                "rlnCoordinateX": float(center[0]) / float(pixel_size_ang),
                "rlnCoordinateY": float(center[1]) / float(pixel_size_ang),
                "rlnCoordinateZ": float(center[2]) / float(pixel_size_ang),
                "rlnAngleRot": float(phi_deg),
                "rlnAngleTilt": 0.0,
                "rlnAnglePsi": 0.0,
                "rlnImagePixelSize": float(pixel_size_ang),
                "rlnHelicalTubeID": int(tube_id),
            })

    if make_central_pair:
        cx1 = +float(cp_sep_ang) * 0.5
        cx2 = -float(cp_sep_ang) * 0.5
        tube_id_1 = int(n_outer) + 1
        tube_id_2 = int(n_outer) + 2

        for cx, rot_deg, tube_id in [
            (cx1, 0.0, tube_id_1),
            (cx2, 180.0, tube_id_2),
        ]:
            for z in z_vals:
                center = (cx, 0.0, float(z))
                s = make_sphere_surface(session, f"Bead_T{tube_id}", center, bead_radius_ang, subdivisions, inner_color)
                session.models.add([s], parent=root)
                bead_models.append(s)

                star_rows.append({
                    "rlnTomoName": tomo_name,
                    "rlnCoordinateX": float(center[0]) / float(pixel_size_ang),
                    "rlnCoordinateY": float(center[1]) / float(pixel_size_ang),
                    "rlnCoordinateZ": float(center[2]) / float(pixel_size_ang),
                    "rlnAngleRot": float(rot_deg),
                    "rlnAngleTilt": 0.0,
                    "rlnAnglePsi": 0.0,
                    "rlnImagePixelSize": float(pixel_size_ang),
                    "rlnHelicalTubeID": int(tube_id),
                })

    return root, bead_models, star_rows


def render_from_star_rows(session,
                          star_rows,
                          scale_by_pixel_size=True,
                          bead_radius_ang=70.0,
                          bead_subdivisions=10,
                          outer_color=(220, 220, 220, 255),
                          inner_color=(255, 220, 120, 255),
                          outer_only=True,
                          outer_n=9,
                          show_vectors=True,
                          arrow_length_ang=220.0,
                          shaft_radius_ang=10.0,
                          head_radius_ang=18.0,
                          head_length_ang=50.0,
                          arrow_segments=16):
    root = Model("CB_From_STAR", session)
    session.models.add([root])

    col_x = (255, 80, 80, 255)
    col_y = (80, 255, 80, 255)
    col_z = (80, 80, 255, 255)

    for idx, r in enumerate(star_rows):
        tube_id = int(r.get("rlnHelicalTubeID", 0))
        if outer_only and tube_id > int(outer_n):
            continue

        px = float(r.get("rlnImagePixelSize", 10.0))
        cx = float(r.get("rlnCoordinateX", 0.0))
        cy = float(r.get("rlnCoordinateY", 0.0))
        cz = float(r.get("rlnCoordinateZ", 0.0))

        if scale_by_pixel_size:
            center = (cx * px, cy * px, cz * px)
        else:
            center = (cx, cy, cz)

        bead_color = outer_color if tube_id <= int(outer_n) else inner_color
        bead = make_sphere_surface(
            session=session,
            name=f"STAR_Bead_T{tube_id}_{idx}",
            center_xyz=center,
            radius=bead_radius_ang,
            subdivisions=int(bead_subdivisions),
            color=bead_color,
        )
        session.models.add([bead], parent=root)

        if not show_vectors:
            continue

        rot = float(r.get("rlnAngleRot", 0.0))
        tilt = float(r.get("rlnAngleTilt", 0.0))
        psi = float(r.get("rlnAnglePsi", 0.0))
        R = euler_relion_zyz(rot, tilt, psi)

        ex = R @ np.array([1.0, 0.0, 0.0], dtype=float)
        ey = R @ np.array([0.0, 1.0, 0.0], dtype=float)
        ez = R @ np.array([0.0, 0.0, 1.0], dtype=float)

        p0 = np.array(center, dtype=float)
        p1x = p0 + float(arrow_length_ang) * safe_normalize(ex)
        p1y = p0 + float(arrow_length_ang) * safe_normalize(ey)
        p1z = p0 + float(arrow_length_ang) * safe_normalize(ez)

        for surf in make_arrow_surfaces(session, f"ArrowX_T{tube_id}_{idx}", p0, p1x,
                                        shaft_radius_ang, head_radius_ang, head_length_ang, arrow_segments, col_x):
            session.models.add([surf], parent=root)
        for surf in make_arrow_surfaces(session, f"ArrowY_T{tube_id}_{idx}", p0, p1y,
                                        shaft_radius_ang, head_radius_ang, head_length_ang, arrow_segments, col_y):
            session.models.add([surf], parent=root)
        for surf in make_arrow_surfaces(session, f"ArrowZ_T{tube_id}_{idx}", p0, p1z,
                                        shaft_radius_ang, head_radius_ang, head_length_ang, arrow_segments, col_z):
            session.models.add([surf], parent=root)

    return root
