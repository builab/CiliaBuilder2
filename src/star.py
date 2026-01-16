# vim: set expandtab shiftwidth=4 softtabstop=4:

from __future__ import annotations
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
    headers: List[str] = []
    rows: List[List[str]] = []
    in_loop = False

    for raw in star_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.lower() == "loop_":
            in_loop = True
            headers = []
            rows = []
            continue

        if in_loop and line.startswith("_rln"):
            headers.append(line.split()[0])
            continue

        if in_loop and not line.startswith("_"):
            rows.append(raw.split())
            continue

    return headers, rows


def read_star_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def star_points_from_text(star_text: str) -> List[Dict[str, object]]:
    headers, rows = parse_star_text(star_text)
    col = {h: i for i, h in enumerate(headers)}

    need = [c[0] for c in STAR_COLUMNS]
    for k in need:
        if k not in col:
            raise ValueError(f"STAR missing column {k}")

    pts: List[Dict[str, object]] = []
    for tok in rows:
        pts.append({
            "tomo_name": tok[col["_rlnTomoName"]],
            "x": float(tok[col["_rlnCoordinateX"]]),
            "y": float(tok[col["_rlnCoordinateY"]]),
            "z": float(tok[col["_rlnCoordinateZ"]]),
            "rot": float(tok[col["_rlnAngleRot"]]),
            "tilt": float(tok[col["_rlnAngleTilt"]]),
            "psi": float(tok[col["_rlnAnglePsi"]]),
            "pixel": float(tok[col["_rlnImagePixelSize"]]),
            "tube_id": int(float(tok[col["_rlnHelicalTubeID"]])),
        })
    return pts
