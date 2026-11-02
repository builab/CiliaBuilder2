"""Close-packed rows on the actual membrane triangles, with bounded bulk queries."""

import math

import numpy as np

MAX_CANDIDATES = 200000
MAX_CONFLICTS = 2000000


class Leaflet:
    """Slice the existing triangulated leaflet; never approximate it by a new cylinder."""

    def __init__(self, model, inner=False):
        state = model._cb_membrane_state
        radius = state["diameter"] * 0.5
        nc = max(32, int(math.ceil(2 * math.pi * radius / 80)))
        nz = max(2, int(math.ceil(state["length"] / max(80, state["thickness"]))))
        vertices = np.asarray(model.vertices, dtype=float)
        start = nc * nz if inner else 0
        rings = [np.arange(start + i*nc, start + (i+1)*nc) for i in range(nz)]
        outer_steps = inner_steps = 0
        if state.get("tip_dome_enabled"):
            outer_steps = max(4, int(math.ceil(max(radius, state["tip_dome_outer_height"]) / 80)))
            inner_steps = max(4, int(math.ceil(max(max(1e-6, radius - state["thickness"]),
                                                 state["tip_dome_inner_height"]) / 80)))
            start = 2*nc*nz + ((outer_steps-1)*nc + 1 if inner else 0)
            steps = inner_steps if inner else outer_steps
            rings.extend(np.arange(start + i*nc, start + (i+1)*nc) for i in range(steps-1))
            rings.append(np.array([start + (steps-1)*nc]))
        expected = 2*nc*nz + ((outer_steps + inner_steps - 2)*nc + 2 if outer_steps else 0)
        if len(vertices) != expected:
            raise ValueError("Membrane topology changed. Rebuild the membrane before packing it.")

        from .orientation import rotation_align_vector_to_vector
        rotation = rotation_align_vector_to_vector((0, 0, 1), state["axis"])
        local = (vertices - state["center"]) @ rotation
        angles = np.arctan2(local[:, 1], local[:, 0]) / (2 * math.pi) % 1
        levels = np.full(len(vertices), -1, dtype=int)
        aligned = []
        for level, ring in enumerate(rings):
            levels[ring] = level
            if len(ring) == 1:
                aligned.append(np.repeat(vertices[ring], nc, axis=0))
            else:
                order = np.argsort(angles[ring])
                u, xyz = angles[ring][order], vertices[ring][order]
                aligned.append(np.column_stack([np.interp(np.arange(nc)/nc, u, xyz[:, d], period=1)
                                                for d in range(3)]))
        # Compare equal-angle points, not staggered cylinder vertex indices.
        lengths = np.linalg.norm(np.diff(aligned, axis=0), axis=2).mean(axis=1)
        self.arc = np.r_[0, np.cumsum(lengths)]
        self.pole = vertices[rings[-1][0]] if len(rings[-1]) == 1 else None
        mask = model._cb_membrane_inner_faces if inner else model._cb_membrane_outer_faces
        triangles = np.asarray(model.triangles)[mask]
        self.faces = vertices[triangles]
        self.levels = levels[triangles]
        self.angles = angles[triangles]
        seam = np.ptp(self.angles, axis=1) > 0.5
        self.angles[seam] += self.angles[seam] < 0.5
        if self.pole is not None:
            for i in np.flatnonzero(np.any(self.levels == len(rings)-1, axis=1)):
                at_pole = self.levels[i] == len(rings)-1
                uv = angles[triangles[i]][~at_pole].copy()
                if np.ptp(uv) > 0.5:
                    uv += uv < 0.5
                self.angles[i, ~at_pole] = uv
                self.angles[i, at_pole] = uv.mean()
        cross = np.cross(self.faces[:, 1]-self.faces[:, 0], self.faces[:, 2]-self.faces[:, 0])
        self.normals = cross / np.maximum(np.linalg.norm(cross, axis=1)[:, None], 1e-30)
        self.bands = [np.flatnonzero(self.levels.min(axis=1) == i) for i in range(len(rings)-1)]

    def row(self, distance, pitch, phase):
        band = min(np.searchsorted(self.arc, distance, side="right")-1, len(self.bands)-1)
        if self.arc[band+1] - self.arc[band] < 1e-12:
            return np.empty((0, 3)), np.empty((0, 3))
        height = band + (distance-self.arc[band])/(self.arc[band+1]-self.arc[band])
        ids = self.bands[band]
        faces, levels, angles = self.faces[ids], self.levels[ids], self.angles[ids]
        nxt = np.array([1, 2, 0])
        crossing = levels != levels[:, nxt]
        fi, edge = np.nonzero(crossing)
        alpha = (height-levels[fi, edge])/(levels[fi, nxt[edge]]-levels[fi, edge])
        points = faces[fi, edge] + alpha[:, None]*(faces[fi, nxt[edge]]-faces[fi, edge])
        uv = angles[fi, edge] + alpha*(angles[fi, nxt[edge]]-angles[fi, edge])
        segments = points.reshape((-1, 2, 3))
        uv = uv.reshape((-1, 2))
        reverse = uv[:, 0] > uv[:, 1]
        segments[reverse] = segments[reverse, ::-1]
        uv[reverse] = uv[reverse, ::-1]
        normals = self.normals[ids]
        # Split at the seam so row phases share one angular origin.
        split = (uv[:, 0] < 1) & (uv[:, 1] > 1)
        if split.any():
            fraction = (1-uv[split, 0])/(uv[split, 1]-uv[split, 0])
            middle = segments[split, 0] + fraction[:, None]*(segments[split, 1]-segments[split, 0])
            extra = np.stack((middle, segments[split, 1]), axis=1)
            segments[split, 1] = middle
            segments = np.concatenate((segments, extra))
            uv = np.concatenate((uv, np.column_stack((np.ones(len(extra)), uv[split, 1]))))
            normals = np.concatenate((normals, normals[split]))
        order = np.argsort(uv[:, 0] % 1, kind="stable")
        segments, normals = segments[order], normals[order]
        lengths = np.linalg.norm(segments[:, 1]-segments[:, 0], axis=1)
        usable = lengths > 1e-10
        segments, normals, lengths = segments[usable], normals[usable], lengths[usable]
        arc = np.r_[0, np.cumsum(lengths)]
        count = int(arc[-1]/pitch)
        if count > MAX_CANDIDATES:
            raise ValueError("Too many membrane sites in one row. Increase the particle radius.")
        if count == 0:
            return np.empty((0, 3)), np.empty((0, 3))
        samples = ((np.arange(count) + phase) % count) * arc[-1]/count
        index = np.searchsorted(arc, samples, side="right")-1
        fraction = (samples-arc[index])/lengths[index]
        return segments[index, 0] + fraction[:, None]*(segments[index, 1]-segments[index, 0]), normals[index]

    def rows(self, pitch, phase, offset=0.5):
        height = pitch * math.sqrt(3)/2
        count = max(1, int(self.arc[-1]/height))
        if count > MAX_CANDIDATES:
            raise ValueError("Membrane is too long for this particle radius. Increase the radius.")
        for i in range(count):
            distance = (i+offset)*self.arc[-1]/count
            yield self.row(distance, pitch, phase + 0.5*(i % 2))
        if self.pole is not None and offset == 0.5:
            yield self.pole[None, :], self.normals[self.bands[-1][-1]][None, :]


def conflict_graph(points, distance):
    """CSR forward neighbors for one greedy pass, computed in compiled SciPy code."""
    from scipy.spatial import cKDTree
    tree = cKDTree(points)
    if tree.count_neighbors(tree, distance) > 2*MAX_CONFLICTS + len(points):
        raise ValueError("Too many intersecting packing sites. Reduce distortion or increase particle radius.")
    pairs = tree.query_pairs(distance, output_type="ndarray")
    if len(pairs):
        pairs.sort(axis=1)
        pairs = pairs[np.argsort(pairs[:, 0], kind="stable")]
        offsets = np.r_[0, np.cumsum(np.bincount(pairs[:, 0], minlength=len(points)))].astype(int)
        neighbors = pairs[:, 1]
    else:
        offsets, neighbors = np.zeros(len(points)+1, dtype=int), np.empty(0, dtype=int)
    return offsets, neighbors


def outside_protein_boxes(points, tree, rotations, bounds, protein_radius, lipid_radius, gap):
    """Refine broad sphere bounds with oriented boxes enclosing the protein mesh.

    A sphere outside a protein's enclosing box cannot intersect that protein.
    Check every broad-phase neighbor, not just the nearest protein center.
    """
    keep = np.ones(len(points), dtype=bool)
    distance = protein_radius + lipid_radius + gap
    for start in range(0, len(points), 2048):
        block = points[start:start+2048]
        counts = tree.query_ball_point(block, distance, return_length=True)
        if counts.sum() > MAX_CONFLICTS:
            raise ValueError("Too many protein neighbors. Increase particle radius or reduce protein coverage.")
        if not counts.any():
            continue
        neighbors = tree.query_ball_point(block, distance)
        sites = np.repeat(np.arange(len(block)), counts)
        proteins = np.concatenate(neighbors).astype(int)
        delta = block[sites] - tree.data[proteins]
        local = np.einsum("ni,nij->nj", delta, rotations[proteins])
        outside = np.maximum(np.maximum(bounds[0]-local, local-bounds[1]), 0)
        collision = np.sum(outside*outside, axis=1) < (lipid_radius+gap)**2
        keep[start + sites[collision]] = False
    return keep
