import numpy as np


def get_top_by_id(session, id1):
    id1 = int(id1)
    for m in session.models.list():
        if getattr(m, "id", None) and len(m.id) == 1 and int(m.id[0]) == id1:
            return m
    return None


def walk(model):
    yield model
    for c in getattr(model, "child_models", lambda: [])():
        yield from walk(c)


def center_of(model):
    try:
        b = model.bounds()
        if b is not None:
            c = b.center()
            return np.array([c.x, c.y, c.z], dtype=float)
    except Exception:
        pass
    return np.array([0.0, 0.0, 0.0], dtype=float)


def verts_of(surf):
    for attr in ("vertices", "_vertices"):
        v = getattr(surf, attr, None)
        if v is not None:
            return np.array(v, dtype=float)
    try:
        g = surf.geometry
        if g and len(g) >= 1:
            return np.array(g[0], dtype=float)
    except Exception:
        pass
    return None


def farthest_point(model, origin):
    v = verts_of(model)
    if v is None or len(v) == 0:
        return None
    o = np.array(origin, dtype=float)
    d2 = np.sum((v - o) ** 2, axis=1)
    return v[int(np.argmax(d2))]


def unit(v):
    v = np.array(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return np.array([0.0, 0.0, 1.0], dtype=float)
    return v / n


def orthonormal(ex, ey, ez):
    ex = unit(ex)
    ez = unit(ez)
    ey = ey - np.dot(ey, ex) * ex
    ey = ey - np.dot(ey, ez) * ez
    ey = unit(ey)
    ez = unit(np.cross(ex, ey))
    return ex, ey, ez


def copy_volume(session, src):
    try:
        dst = src.copy()
    except Exception as e:
        session.logger.error(f"cbsubmap: map model does not support copy(): {e}")
        return None

    try:
        dst.display = True
    except Exception:
        pass
    try:
        dst.visible = True
    except Exception:
        pass

    for attr in (
        "region", "surface_levels", "image_levels", "rendering_options",
        "display_style", "color", "colors"
    ):
        if hasattr(src, attr) and hasattr(dst, attr):
            try:
                setattr(dst, attr, getattr(src, attr))
            except Exception:
                pass

    return dst
