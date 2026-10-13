"""JSON state for scene clipping planes and managed drawing permissions."""

import numpy as np


def capture_scene_clipping(view):
    from chimerax.graphics import SceneClipPlane

    return {"planes": [
        {"name": plane.name,
         "normal": np.asarray(plane.normal, dtype=float).tolist(),
         "plane_point": np.asarray(plane.plane_point, dtype=float).tolist()}
        for plane in view.clip_planes.planes() if isinstance(plane, SceneClipPlane)
    ]}


def restore_scene_clipping(view, state):
    """Restore after view orient; an absent field means legacy JSON behavior."""
    if state is None:
        return
    from chimerax.graphics import SceneClipPlane
    from chimerax import surface

    planes = []
    names = set()
    for item in state["planes"]:
        name = item["name"]
        normal = np.asarray(item["normal"], dtype=float)
        point = np.asarray(item["plane_point"], dtype=float)
        if (not isinstance(name, str) or not name or name in names
                or normal.shape != (3,) or point.shape != (3,)
                or not np.all(np.isfinite(normal)) or not np.all(np.isfinite(point))
                or np.linalg.norm(normal) < 1e-12):
            raise ValueError("Invalid scene clipping plane in session JSON")
        names.add(name)
        planes.append(SceneClipPlane(name, normal, point))
    # Camera near/far planes are not scene cuts and retain their normal view behavior.
    keep = [p for p in view.clip_planes.planes() if not isinstance(p, SceneClipPlane)]
    view.clip_planes.replace_planes(keep + planes)
    surface.update_clip_caps(view)
    view.redraw_needed = True


def _children(drawing):
    # Caps are derived geometry; including them shifts saved paths on reload.
    return [child for child in drawing.child_drawings()
            if not hasattr(child, "clip_cap_owner")]


def _drawing_tree(model):
    from chimerax.map import Volume

    pending = [(model, [])]
    while pending:
        drawing, path = pending.pop()
        if isinstance(drawing, Volume):
            drawing.update_drawings()
        yield drawing, path
        pending.extend((child, path + [index])
                       for index, child in reversed(list(enumerate(_children(drawing)))))


def set_model_clipping(model, allow):
    for drawing, _path in _drawing_tree(model):
        drawing.allow_clipping = bool(allow)


def capture_model_clipping(model):
    entries = []
    for drawing, path in _drawing_tree(model):
        entry = {"path": path, "allow_clipping": bool(drawing.allow_clipping)}
        if hasattr(drawing, "clip_cap"):
            entry["clip_cap"] = bool(drawing.clip_cap)
        entries.append(entry)
    return entries


def restore_model_clipping(model, state):
    if state is None:
        return
    drawings = {tuple(path): drawing for drawing, path in _drawing_tree(model)}
    for entry in state:
        drawing = drawings.get(tuple(entry.get("path", [])))
        if drawing is not None:
            if isinstance(entry.get("allow_clipping"), bool):
                drawing.allow_clipping = entry["allow_clipping"]
            if isinstance(entry.get("clip_cap"), bool):
                drawing.clip_cap = entry["clip_cap"]
