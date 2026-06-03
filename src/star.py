# vim: set expandtab shiftwidth=4 softtabstop=4:

from __future__ import annotations
import shlex
from typing import Dict, List, Tuple


STAR_COLUMNS = [
    ("_rlnTomoName", 1),
    ("_rlnCoordinateX", 2),
    ("_rlnCoordinateY", 3),
    ("_rlnCoordinateZ", 4),
    ("_rlnAngleRot", 5),
    ("_rlnAngleTilt", 6),
    ("_rlnAnglePsi", 7),
    ("_rlnImagePixelSize", 8),
    ("_rlnHelicalTubeID", 9),
]


def star_text_from_rows(rows: List[Dict[str, object]]) -> str:
    lines: List[str] = []
    lines.append("data_")
    lines.append("")
    lines.append("loop_")
    for name, idx in STAR_COLUMNS:
        lines.append(f"{name} #{idx}")

    for r in rows:
        lines.append(
            f"{str(r['tomo_name']): <8}"
            f"{float(r['x']): >12.6f} "
            f"{float(r['y']): >12.6f} "
            f"{float(r['z']): >12.6f} "
            f"{float(r['rot']): >12.6f} "
            f"{float(r['tilt']): >12.6f} "
            f"{float(r['psi']): >12.6f} "
            f"{float(r['pixel']): >12.6f} "
            f"{int(r['tube_id']): >3d}"
        )
    return "\n".join(lines)


def parse_star_text(star_text: str) -> Tuple[List[str], List[List[str]]]:
    loops = []
    headers: List[str] = []
    rows: List[List[str]] = []
    in_loop = False

    def flush_loop():
        if headers:
            loops.append((list(headers), list(rows)))

    for raw in star_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.lower().startswith("data_"):
            if in_loop:
                flush_loop()
            in_loop = False
            headers = []
            rows = []
            continue

        if line.lower() == "loop_":
            if in_loop:
                flush_loop()
            in_loop = True
            headers = []
            rows = []
            continue

        if not in_loop:
            continue

        if line.startswith("_"):
            headers.append(line.split()[0])
            continue

        try:
            tokens = shlex.split(raw, posix=True)
        except Exception:
            tokens = raw.split()
        if tokens:
            rows.append(tokens)

    if in_loop:
        flush_loop()

    required = {"_rlnCoordinateX", "_rlnCoordinateY", "_rlnCoordinateZ"}
    for loop_headers, loop_rows in loops:
        if required.issubset(set(loop_headers)):
            return loop_headers, loop_rows
    if loops:
        return loops[0]
    return [], []


def read_star_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def star_points_from_text(star_text: str) -> List[Dict[str, object]]:
    headers, rows = parse_star_text(star_text)
    col = {h: i for i, h in enumerate(headers)}

    need = ["_rlnCoordinateX", "_rlnCoordinateY", "_rlnCoordinateZ"]
    for k in need:
        if k not in col:
            raise ValueError(f"STAR missing column {k}")

    pts: List[Dict[str, object]] = []
    for tok in rows:
        px = float(tok[col["_rlnImagePixelSize"]]) if "_rlnImagePixelSize" in col and col["_rlnImagePixelSize"] < len(tok) else 1.0
        pts.append({
            "tomo_name": tok[col["_rlnTomoName"]] if "_rlnTomoName" in col and col["_rlnTomoName"] < len(tok) else "TS_001",
            "x": float(tok[col["_rlnCoordinateX"]]),
            "y": float(tok[col["_rlnCoordinateY"]]),
            "z": float(tok[col["_rlnCoordinateZ"]]),
            "rot": float(tok[col["_rlnAngleRot"]]) if "_rlnAngleRot" in col and col["_rlnAngleRot"] < len(tok) else 0.0,
            "tilt": float(tok[col["_rlnAngleTilt"]]) if "_rlnAngleTilt" in col and col["_rlnAngleTilt"] < len(tok) else 0.0,
            "psi": float(tok[col["_rlnAnglePsi"]]) if "_rlnAnglePsi" in col and col["_rlnAnglePsi"] < len(tok) else 0.0,
            "pixel": px if px > 0.0 else 1.0,
            "tube_id": int(float(tok[col["_rlnHelicalTubeID"]])) if "_rlnHelicalTubeID" in col and col["_rlnHelicalTubeID"] < len(tok) else 1,
        })
    return pts


def ciliabuilder_rows_from_text(
    star_text: str,
    default_pixel_size: float = 1.0,
    default_tomo_name: str = "TS_001",
    default_tube_id: int = 1,
    default_class_number: int = 1,
) -> List[Dict[str, object]]:
    headers, rows = parse_star_text(star_text)
    col = {h: i for i, h in enumerate(headers)}

    need = ["_rlnCoordinateX", "_rlnCoordinateY", "_rlnCoordinateZ"]
    for key in need:
        if key not in col:
            raise ValueError(f"STAR missing column {key}")

    try:
        default_px = float(default_pixel_size)
    except Exception:
        default_px = 1.0
    if default_px <= 0.0:
        default_px = 1.0

    out: List[Dict[str, object]] = []

    def token_value(tokens, header_name, default_value):
        index = col.get(header_name, None)
        if index is None or index < 0 or index >= len(tokens):
            return default_value
        value = tokens[index]
        return default_value if value in ("", None) else value

    for tokens in rows:
        tomo_name = str(token_value(tokens, "_rlnTomoName", default_tomo_name) or default_tomo_name)
        try:
            px = float(token_value(tokens, "_rlnImagePixelSize", default_px))
        except Exception:
            px = default_px
        if px <= 0.0:
            px = default_px

        x = float(token_value(tokens, "_rlnCoordinateX", 0.0))
        y = float(token_value(tokens, "_rlnCoordinateY", 0.0))
        z = float(token_value(tokens, "_rlnCoordinateZ", 0.0))
        rot = float(token_value(tokens, "_rlnAngleRot", 0.0))
        tilt = float(token_value(tokens, "_rlnAngleTilt", 0.0))
        psi = float(token_value(tokens, "_rlnAnglePsi", 0.0))
        try:
            tube_id = int(float(token_value(tokens, "_rlnHelicalTubeID", default_tube_id)))
        except Exception:
            tube_id = int(default_tube_id)
        try:
            class_number = int(float(token_value(tokens, "_rlnClassNumber", default_class_number)))
        except Exception:
            class_number = int(default_class_number)

        out.append(
            {
                "rlnTomoName": tomo_name,
                "rlnCoordinateX": float(x),
                "rlnCoordinateY": float(y),
                "rlnCoordinateZ": float(z),
                "rlnAngleRot": float(rot),
                "rlnAngleTilt": float(tilt),
                "rlnAnglePsi": float(psi),
                "rlnImagePixelSize": float(px),
                "rlnHelicalTubeID": int(tube_id),
                "rlnClassNumber": int(class_number),
                "_cbWorldCoordinateX": float(x) * float(px),
                "_cbWorldCoordinateY": float(y) * float(px),
                "_cbWorldCoordinateZ": float(z) * float(px),
            }
        )

    return out
