#!/usr/bin/env python3
"""
Generate a RELION-style .star file for the transition zone of a centriole / cilium.

Geometry (all along Z, units = pixels, same as the template STAR file):

    z = 0                                       proximal cylinder (radius = proximal_diameter / 2)
    z = proximal_length                         ---- start of transition ----
    z = proximal_length + transition_length     ---- end of transition ----
                                                distal cylinder (radius = distal_diameter / 2)
    z = proximal_length + transition_length + distal_length

Each doublet is a curve: straight line (proximal) -> transition curve -> straight line
(distal). In the transition zone the radius follows

    r(z) = r_prox + (r_dist - r_prox) * s(u),     u = (z - z_start) / transition_length

where s(u) is the chosen --profile (s(0) = 0, s(1) = 1):

    smootherstep  (default) 6u^5 - 15u^4 + 10u^3   slope AND curvature are 0 at both ends (C2)
    smoothstep              3u^2 - 2u^3            slope is 0 at both ends (C1)
    cosine                  (1 - cos(pi u)) / 2    slope is 0 at both ends (C1)
    linear                  u                      straight cone with a kink at both ends

With a smooth profile the doublet joins the straight parts tangentially, so the axis
lean (rlnAngleTilt) ramps from 0, peaks in the middle of the transition, and returns to 0.
`transition_length` is the Z extent of the transition, not its arc length.

Particles are placed every `periodicity` along the ARC LENGTH of the whole path,
starting at z = 0 (the transition arc length is integrated numerically).

Angles (RELION ZYZ convention, as used by the template):
    Particle axes in the tomogram frame are the columns of the RELION matrix A(rot, tilt, psi):
        z axis (filament axis) = (-cos(psi) sin(tilt), sin(psi) sin(tilt), cos(tilt))
        rot spins the particle around that axis.

    Straight cylinders (identical to the template):
        rot = 90 - phi, tilt = 0, psi = 0        (phi = azimuth of the doublet, 40 deg steps for N = 9)
        -> z axis = tomogram Z, x axis = -(circumferential direction), y axis = radial (outward)

    Transition zone (axis_mode = follow, default):
        The local tangent (dx/dz, dy/dz) = dr/dz * (cos phi, sin phi) is computed for each
        doublet at each particle; tilt = atan(|dr/dz|). The spin about the filament axis is
        kept at the proximal value (90 - phi), which in RELION's ZYZ convention needs
        rot = (90 - phi) - psi.
        With axis_mode = fixed, all particles keep the template angles (tilt = 0 everywhere).

Usage:
    python draw_transition_zone_star_smooth.py
    python draw_transition_zone_star_smooth.py --profile linear -o cone.star
    python draw_transition_zone_star_smooth.py --proximal_length 3000 --transition_length 1500 \
        --distal_length 2000 --distal_diameter 1900 -o transition_zone.star
"""

import argparse
import bisect
import math

# profile name -> (s(u), ds/du)
PROFILES = {
    "smootherstep": (lambda u: u * u * u * (u * (6.0 * u - 15.0) + 10.0),
                     lambda u: 30.0 * u * u * (1.0 - u) ** 2),
    "smoothstep": (lambda u: u * u * (3.0 - 2.0 * u),
                   lambda u: 6.0 * u * (1.0 - u)),
    "cosine": (lambda u: 0.5 * (1.0 - math.cos(math.pi * u)),
               lambda u: 0.5 * math.pi * math.sin(math.pi * u)),
    "linear": (lambda u: u,
               lambda u: 1.0),
}
DEFAULT_PROFILE = "smootherstep"
TABLE_STEPS = 20000


def wrap180(a):
    """Wrap an angle in degrees to [-180, 180)."""
    return (a + 180.0) % 360.0 - 180.0


def euler_from_tangent(phi, dx_dz, dy_dz, rot):
    """Return RELION (rot, tilt, psi) for a local tangent vector.

    RELION convention used by this script:
        tx = -cos(psi) * sin(tilt)
        ty =  sin(psi) * sin(tilt)
        tz =  cos(tilt)

    The tangent is directed toward increasing Z. The spin of the particle about
    its own filament axis must stay equal to the proximal template value
    (90 - phi) so the x axis remains circumferential. In RELION's ZYZ convention
    A = [Rz(psi) Ry(tilt) Rz(-psi)] . Rz(psi + rot), so this requires
    rot = (90 - phi) - psi. ``rot`` passed in is the template value (90 - phi).
    """
    transverse = math.hypot(dx_dz, dy_dz)
    tilt = math.degrees(math.atan2(transverse, 1.0))
    if transverse < 1e-12:
        psi = 0.0
    else:
        psi = math.degrees(math.atan2(dy_dz, -dx_dz))
    return wrap180(rot - psi), tilt, wrap180(psi)


class Transition:
    """Radius profile of the transition zone with numerical arc length."""

    def __init__(self, length, r_p, r_d, profile):
        self.length = length
        self.r_p = r_p
        self.dr = r_d - r_p
        self.s_fn, self.ds_fn = PROFILES[profile]
        if length <= 0:
            # Step change in radius at a single z: no Z extent, no tilt.
            self.arc = abs(self.dr)
            self.cum = None
            return
        n = TABLE_STEPS
        dz = length / n
        slopes = [self.dr / length * self.ds_fn(i / n) for i in range(n + 1)]
        cum = [0.0]
        for i in range(n):
            a = math.sqrt(1.0 + slopes[i] ** 2)
            b = math.sqrt(1.0 + slopes[i + 1] ** 2)
            cum.append(cum[-1] + 0.5 * (a + b) * dz)
        self.cum = cum
        self.arc = cum[-1]

    def at(self, s):
        """(u, r, dr/dz) at arc length s (0 <= s <= arc) measured from the transition start."""
        if self.cum is None:
            f = s / self.arc if self.arc > 0 else 0.0
            return f, self.r_p + f * self.dr, 0.0
        cum = self.cum
        n = len(cum) - 1
        i = min(max(bisect.bisect_right(cum, s) - 1, 0), n - 1)
        seg = cum[i + 1] - cum[i]
        frac = (s - cum[i]) / seg if seg > 0 else 0.0
        u = (i + frac) / n
        r = self.r_p + self.dr * self.s_fn(u)
        slope = self.dr / self.length * self.ds_fn(u)
        return u, r, slope


def build_particles(proximal_length, proximal_diameter, transition_length,
                    distal_length, distal_diameter, number_of_doublets,
                    periodicity, tomo_name, pixel_size, axis_mode,
                    profile=DEFAULT_PROFILE):
    r_p = proximal_diameter / 2.0
    r_d = distal_diameter / 2.0

    trans = Transition(transition_length, r_p, r_d, profile)
    arc_t = trans.arc
    total = proximal_length + arc_t + distal_length

    # Arc-length positions of the particles along the path
    positions = []
    k = 0
    eps = 1e-9
    while k * periodicity <= total + eps:
        positions.append(k * periodicity)
        k += 1

    # (z, radius, dr/dz, in_transition) for each sampled point (same for all doublets).
    # A point exactly at a junction is treated as straight.
    samples = []
    for s in positions:
        if s <= proximal_length:
            samples.append((s, r_p, 0.0, False))
        elif s < proximal_length + arc_t:
            u, r, slope = trans.at(s - proximal_length)
            z = proximal_length + u * transition_length
            samples.append((z, r, slope, True))
        else:
            z = proximal_length + transition_length + (s - proximal_length - arc_t)
            samples.append((z, r_d, 0.0, False))

    angular_step = 360.0 / number_of_doublets
    rows = []
    max_tilt = 0.0
    for i in range(number_of_doublets):
        phi = i * angular_step                  # azimuth of the doublet
        phi_rad = math.radians(phi)
        for z, r, slope, in_t in samples:
            x = r * math.cos(phi_rad)
            y = r * math.sin(phi_rad)
            rot0 = 90.0 - phi  # proximal-region rotation for this tube
            if in_t and axis_mode == "follow" and abs(slope) > 1e-12:
                dx_dz = slope * math.cos(phi_rad)
                dy_dz = slope * math.sin(phi_rad)
                rot, tilt, psi = euler_from_tangent(phi, dx_dz, dy_dz, rot0)
            else:
                rot, tilt, psi = rot0, 0.0, 0.0  # template angles
            max_tilt = max(max_tilt, tilt)
            rows.append((tomo_name, x, y, z, rot, tilt, psi, pixel_size, i + 1, 1))
    return rows, total, max_tilt, (-1 if r_d > r_p else 1 if r_d < r_p else 0)


def write_star(path, rows):
    header = [
        "data_", "", "loop_",
        "_rlnTomoName #1",
        "_rlnCoordinateX #2",
        "_rlnCoordinateY #3",
        "_rlnCoordinateZ #4",
        "_rlnAngleRot #5",
        "_rlnAngleTilt #6",
        "_rlnAnglePsi #7",
        "_rlnImagePixelSize #8",
        "_rlnHelicalTubeID #9",
        "_rlnClassNumber #10",
    ]
    with open(path, "w") as f:
        f.write("\n".join(header) + "\n")
        for (name, x, y, z, rot, tilt, psi, px, tube, cls) in rows:
            # avoid printing "-0.000000"
            vals = [0.0 if abs(v) < 5e-7 else v for v in (x, y, z, rot, tilt, psi, px)]
            f.write("{} {:.6f} {:.6f} {:.6f} {:.6f} {:.6f} {:.6f} {:.6f} {} {}\n".format(
                name, *vals, tube, cls))


def main():
    p = argparse.ArgumentParser(
        description="Create a STAR file of the centriole/cilium transition zone.")
    p.add_argument("--proximal_length", type=float, default=3000)
    p.add_argument("--proximal_diameter", type=float, default=2200)
    p.add_argument("--transition_length", type=float, default=1500,
                   help="Z extent of the transition zone (not the arc length)")
    p.add_argument("--distal_length", type=float, default=2000)
    p.add_argument("--distal_diameter", type=float, default=1900)
    p.add_argument("--number_of_doublets", type=int, default=9)
    p.add_argument("--periodicity", type=float, default=165,
                   help="Spacing between particles along each doublet (arc length)")
    p.add_argument("--tomo_name", default="TS_001")
    p.add_argument("--pixel_size", type=float, default=1.0)
    p.add_argument("--profile", choices=list(PROFILES), default=DEFAULT_PROFILE,
                   help="shape of the radius change in the transition zone "
                        "(default: %(default)s; 'linear' = straight cone with kinks)")
    p.add_argument("--axis_mode", choices=["follow", "fixed"], default="follow",
                   help="follow: filament axis (particle z) leans along the doublet in the "
                        "transition zone (tilt != 0 there, x axis unchanged); "
                        "fixed: template angles everywhere (tilt = 0)")
    p.add_argument("-o", "--output", default="transition_zone.star")
    a = p.parse_args()

    if a.periodicity <= 0 or a.number_of_doublets < 1:
        p.error("periodicity must be > 0 and number_of_doublets >= 1")

    rows, total, max_tilt, direction = build_particles(
        a.proximal_length, a.proximal_diameter, a.transition_length,
        a.distal_length, a.distal_diameter, a.number_of_doublets,
        a.periodicity, a.tomo_name, a.pixel_size, a.axis_mode, a.profile)
    write_star(a.output, rows)
    print("Wrote {} particles ({} doublets x {} points) to {}".format(
        len(rows), a.number_of_doublets, len(rows) // a.number_of_doublets, a.output))
    print("Transition profile: {}".format(a.profile))
    print("Path length along each doublet: {:.2f}".format(total))
    print("Max axis lean in transition zone: {:.3f} deg ({})".format(
        max_tilt, "inward" if direction > 0 else "outward" if direction < 0 else "none"))


if __name__ == "__main__":
    main()
