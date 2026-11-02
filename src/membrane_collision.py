"""Cached, mesh-accurate bead/protein collisions without extra dependencies."""

import numpy as np
from scipy.spatial import cKDTree

from .membrane_lattice import MAX_CONFLICTS

try:
    from chimerax.surface import surface_distance as _native_surface_distance
except ImportError:  # ChimeraX 1.7 has no native point-to-triangle distance API.
    _native_surface_distance = None


def _numpy_surface_distance(points, vertices, triangles, distances=None):
    """Exact plane/interior and clamped-edge distances, in bounded array blocks."""
    points = np.asarray(points, float)
    vertices = np.asarray(vertices)
    if distances is None:
        distances = np.zeros((len(points), 5), np.float32)
        distances[:, 0] = np.inf
    for start in range(0, len(points), 128):
        p = points[start:start+128, None, :]
        for first in range(0, len(triangles), 128):
            faces = vertices[triangles[first:first+128]].astype(float)
            a, b = faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]
            normal = np.cross(a, b)
            norm2 = np.sum(normal*normal, axis=1)
            delta = p-faces[:, 0]
            projected = p - (np.sum(delta*normal, 2)/norm2)[:, :, None]*normal
            aa, ab, bb = np.sum(a*a, 1), np.sum(a*b, 1), np.sum(b*b, 1)
            d = projected-faces[:, 0]
            ad, bd = np.sum(a*d, 2), np.sum(b*d, 2)
            det = aa*bb-ab*ab
            u, v = (bb*ad-ab*bd)/det, (aa*bd-ab*ad)/det
            inside = (u >= 0) & (v >= 0) & (u+v <= 1)
            best = projected.copy()
            distance2 = np.sum((p-best)**2, 2)
            distance2[~inside] = np.inf
            for i, j in ((0, 1), (1, 2), (2, 0)):
                edge = faces[:, j]-faces[:, i]
                t = np.clip(np.sum((p-faces[:, i])*edge, 2)/np.sum(edge*edge, 1), 0, 1)
                candidate = faces[:, i]+t[:, :, None]*edge
                dd = np.sum((p-candidate)**2, 2)
                nearer = dd < distance2
                best[nearer], distance2[nearer] = candidate[nearer], dd[nearer]
            nearest = np.argmin(distance2, axis=1)
            rows = np.arange(len(p))
            dist = np.sqrt(distance2[rows, nearest])
            better = dist < distances[start+rows, 0]
            closest = best[rows, nearest]
            side = np.where(np.sum((p[:, 0]-closest)*normal[nearest], 1) >= 0, 1, -1)
            values = np.column_stack((dist, closest, side))
            distances[start+rows[better]] = values[better]
    return distances


def surface_distance(points, vertices, triangles, distances=None):
    if _native_surface_distance is None:
        return _numpy_surface_distance(points, vertices, triangles, distances)
    if distances is None:
        return _native_surface_distance(points, vertices, triangles)
    return _native_surface_distance(points, vertices, triangles, distances)


class ProteinMesh:
    """Nearest triangle distance and ray parity, accelerated by a reusable box tree.

    Use exactly the float32 mesh displayed by ChimeraX. A closed, consistently
    oriented surface is required. Ray parity handles concave corners and cavities;
    the side of one nearest triangle can be ambiguous at shared vertices/edges.
    """

    def __init__(self, vertices, triangles):
        self.vertices = np.asarray(vertices, np.float32)
        triangles = np.asarray(triangles, np.int32)
        edges = triangles[:, ((0, 1), (1, 2), (2, 0))].reshape((-1, 2))
        ordered = np.sort(edges, axis=1)
        _, inverse, counts = np.unique(ordered, axis=0, return_inverse=True, return_counts=True)
        directions = np.where(edges[:, 0] < edges[:, 1], 1, -1)
        winding = np.bincount(inverse, weights=directions)
        if np.any(counts != 2) or np.any(winding != 0):
            raise ValueError("Protein surface is not closed and consistently oriented. "
                             "Re-fetch/rebuild its template before surface-accurate packing.")
        self.bounds = (self.vertices.min(0), self.vertices.max(0))
        self.tolerance = 2e-6 * max(1., float(np.ptp(self.vertices, axis=0).max()))
        self.vertex_tree = cKDTree(self.vertices)
        faces = self.vertices[triangles]
        e1, e2 = faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]
        e1, e2 = e1.astype(float), e2.astype(float)
        aa, ab, bb = np.sum(e1*e1, 1), np.sum(e1*e2, 1), np.sum(e2*e2, 1)
        determinant = aa*bb-ab*ab
        if np.any(determinant <= 0):
            raise ValueError("Protein surface contains degenerate triangles. Rebuild its template before packing.")
        self.ray_normals = np.cross(e1, e2)
        self.ray_u = (bb[:, None]*e1-ab[:, None]*e2)/determinant[:, None]
        self.ray_v = (aa[:, None]*e2-ab[:, None]*e1)/determinant[:, None]
        self.ray_origin = faces[:, 0].astype(float)
        self.triangles = triangles
        low, high = faces.min(1), faces.max(1)
        centers = faces.mean(1)
        self.nodes = []

        def build(indices):
            lo, hi = low[indices].min(0), high[indices].max(0)
            node = len(self.nodes)
            self.nodes.append(None)
            if len(indices) <= 32:
                self.nodes[node] = (lo, hi, None, None, indices)
            else:
                axis = np.argmax(np.ptp(centers[indices], axis=0))
                order = indices[np.argsort(centers[indices, axis], kind="stable")]
                mid = len(order)//2
                left, right = build(order[:mid]), build(order[mid:])
                self.nodes[node] = (lo, hi, left, right, None)
            return node

        build(np.arange(len(triangles)))

    def distances(self, points):
        """Return ChimeraX's (distance, closest XYZ, side) for every local point."""
        points = np.asarray(points, np.float32)
        result = np.zeros((len(points), 5), np.float32)
        # A nearest vertex is an upper bound on nearest surface distance. This
        # tight initial bound makes pruning useful even on the first tree visit.
        result[:, 0] = self.vertex_tree.query(points)[0] + self.tolerance
        for start in range(0, len(points), 512):
            stack = [(0, np.arange(start, min(start+512, len(points))))]
            while stack:
                node, indices = stack.pop()
                lo, hi, left, right, triangles = self.nodes[node]
                outside = np.maximum(np.maximum(lo-points[indices], points[indices]-hi), 0)
                near = np.sum(outside.astype(float)**2, axis=1) <= (result[indices, 0]+self.tolerance)**2
                indices = indices[near]
                if not len(indices):
                    continue
                if triangles is None:
                    stack.extend(((right, indices), (left, indices)))
                else:
                    distance = result[indices].copy()
                    surface_distance(points[indices], self.vertices, self.triangles[triangles], distance)
                    result[indices] = distance
        if np.any(result[:, 4] == 0):
            raise ValueError("Could not determine the protein surface side safely.")
        return result

    def _ray_inside(self, points, direction):
        crossings = np.zeros(len(points), int)
        ambiguous = np.zeros(len(points), bool)
        denominator = self.ray_normals @ direction
        denominator[np.abs(denominator) < 1e-15] = np.inf
        plane = np.sum(self.ray_origin*self.ray_normals, axis=1)
        u0, v0 = np.sum(self.ray_origin*self.ray_u, 1), np.sum(self.ray_origin*self.ray_v, 1)
        du, dv = self.ray_u @ direction, self.ray_v @ direction
        for start in range(0, len(points), 512):
            stack = [(0, np.arange(start, min(start+512, len(points))))]
            while stack:
                node, indices = stack.pop()
                lo, hi, left, right, faces = self.nodes[node]
                t0, t1 = (lo-points[indices])/direction, (hi-points[indices])/direction
                near, far = np.minimum(t0, t1).max(1), np.maximum(t0, t1).min(1)
                indices = indices[far >= np.maximum(near, 0)]
                if not len(indices):
                    continue
                if faces is None:
                    stack.extend(((right, indices), (left, indices)))
                    continue
                p = points[indices]
                t = (plane[faces]-p @ self.ray_normals[faces].T)/denominator[faces]
                u = p @ self.ray_u[faces].T-u0[faces] + t*du[faces]
                v = p @ self.ray_v[faces].T-v0[faces] + t*dv[faces]
                possible = (t > 0) & (u >= -1e-7) & (v >= -1e-7) & (u+v <= 1+1e-7)
                edge = (abs(u) < 1e-7) | (abs(v) < 1e-7) | (abs(1-u-v) < 1e-7)
                ambiguous[indices] |= np.any(possible & edge, axis=1)
                crossings[indices] += np.sum((t > 0) & (u >= 0) & (v >= 0) & (u+v <= 1), axis=1)
        return crossings % 2 == 1, ambiguous

    def inside(self, points):
        points = np.asarray(points, float)
        inside = np.zeros(len(points), bool)
        lo, hi = self.bounds
        ids = np.flatnonzero(np.all((points >= lo) & (points <= hi), axis=1))
        if len(ids):
            inside[ids], ambiguous = self._ray_inside(points[ids], np.array([1., .37139067, .69473891]))
            ids = ids[ambiguous]
            if len(ids):
                second, ambiguous = self._ray_inside(points[ids], np.array([.52918713, 1., -.23178119]))
                inside[ids] = second | ambiguous  # Conservative only at unresolved exact edge hits.
        return inside

    def clear(self, points, radius, gap=0):
        distance = self.distances(points)
        # A center deep inside a protein has a large unsigned distance: it must
        # still be rejected. The tiny tolerance protects float32 contact tests.
        keep = distance[:, 0] >= radius+gap+self.tolerance
        keep[keep] &= ~self.inside(np.asarray(points)[keep])
        return keep


def outside_protein_meshes(points, tree, rotations, mesh, protein_radius, bead_radius, gap):
    """Sphere/box broad phase, actual mesh narrow phase for ALL nearby proteins."""
    keep = np.ones(len(points), bool)
    distance = protein_radius + bead_radius + gap + mesh.tolerance
    for start in range(0, len(points), 512):
        block = points[start:start+512]
        counts = tree.query_ball_point(block, distance, return_length=True)
        if counts.sum() > MAX_CONFLICTS:
            raise ValueError("Too many protein neighbors. Increase particle radius or reduce protein coverage.")
        if not counts.any():
            continue
        neighbors = tree.query_ball_point(block, distance)
        sites = np.repeat(np.arange(len(block)), counts)
        proteins = np.concatenate(neighbors).astype(int)
        local = np.einsum("ni,nij->nj", block[sites]-tree.data[proteins], rotations[proteins])
        lo, hi = mesh.bounds
        outside = np.maximum(np.maximum(lo-local, local-hi), 0)
        near = np.sum(outside*outside, axis=1) <= (bead_radius+gap+mesh.tolerance)**2
        collision = ~mesh.clear(local[near], bead_radius, gap)
        keep[start+sites[near][collision]] = False
    return keep
