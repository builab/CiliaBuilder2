import inspect

_STAR_COLS = [
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


def rows_to_star_text(rows):
    lines = []
    lines.append("data_")
    lines.append("")
    lines.append("loop_")
    for i, c in enumerate(_STAR_COLS, start=1):
        lines.append(f"_{c} #{i}")
    for r in rows:
        vals = []
        for c in _STAR_COLS:
            v = r.get(c, "")
            if isinstance(v, float):
                vals.append(f"{v:.6f}")
            else:
                vals.append(str(v))
        lines.append(" ".join(vals))
    return "\n".join(lines) + "\n"


def parse_star_text(star_text):
    lines = [ln.strip() for ln in star_text.splitlines() if ln.strip() != ""]
    cols = []
    data_rows = []
    in_loop = False

    for ln in lines:
        if ln.lower().startswith("loop_"):
            in_loop = True
            continue
        if not in_loop:
            continue
        if ln.startswith("_"):
            parts = ln.split()
            col = parts[0].lstrip("_")
            cols.append(col)
            continue
        parts = ln.split()
        if cols and len(parts) >= len(cols):
            data_rows.append(parts[: len(cols)])

    rows = []
    for parts in data_rows:
        r = {}
        for c, v in zip(cols, parts):
            if c in ("rlnTomoName",):
                r[c] = v
            else:
                try:
                    if "." in v or "e" in v.lower():
                        r[c] = float(v)
                    else:
                        r[c] = int(v)
                except Exception:
                    r[c] = v
        rows.append(r)

    return cols, rows


def filter_kwargs_for_func(func, kwargs):
    sig = inspect.signature(func)
    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    allowed = set(params.keys())
    return {k: v for k, v in kwargs.items() if k in allowed}


def normalize_builder_return(ret):
    root = None
    beads = []
    star_rows = None
    star_text = None

    if isinstance(ret, tuple):
        if len(ret) >= 1:
            root = ret[0]
        if len(ret) >= 2:
            beads = ret[1]
        if len(ret) >= 3:
            star_rows = ret[2]
        if len(ret) >= 4:
            star_text = ret[3]
    else:
        root = ret

    return root, beads, star_rows, star_text
