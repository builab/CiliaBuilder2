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
    "rlnClassNumber",
]


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
