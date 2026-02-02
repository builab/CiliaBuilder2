# vim: set expandtab shiftwidth=4 softtabstop=4:

import tempfile


STAR_COLS = [
    "rlnTomoName",
    "rlnCoordinateX",
    "rlnCoordinateY",
    "rlnCoordinateZ",
    "rlnAngleRot",
    "rlnAngleTilt",
    "rlnAnglePsi",
    "rlnImagePixelSize",
    "rlnHelicalTubeID",
]


def normalize_star_format(fmt):
    """
    Map UI text or user input to ChimeraX open format tokens.
    Valid open tokens include relion and relion5.
    """
    if fmt is None:
        return "relion"
    s = str(fmt).strip().lower()

    if s in ["relion", "rln"]:
        return "relion"
    if s in ["relion5", "rln5", "relion 5", "relion5 star file", "relion5 star"]:
        return "relion5"

    # UI often shows these labels
    if "relion5" in s:
        return "relion5"
    if "relion" in s:
        return "relion"

    # fallback
    return "relion"


def rows_to_star_text(rows):
    lines = []
    lines.append("data_")
    lines.append("")
    lines.append("loop_")
    for i, c in enumerate(STAR_COLS, start=1):
        lines.append(f"_{c} #{i}")

    for r in rows:
        vals = []
        for c in STAR_COLS:
            v = r.get(c, "")
            if isinstance(v, float):
                vals.append(f"{v:.6f}")
            else:
                vals.append(str(v))
        lines.append(" ".join(vals))

    return "\n".join(lines) + "\n"


def write_star_tempfile(star_text, suffix=".star"):
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=suffix)
    f.write(star_text)
    f.flush()
    f.close()
    return f.name
