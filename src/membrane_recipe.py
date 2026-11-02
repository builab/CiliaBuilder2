"""Stochastic, neighbor-biased packing on membrane triangles.

Inspired by cellPACK's ingredient priorities and closePacking neighbor bias
(Johnson et al., Nature Methods 12, 85-91, doi:10.1038/nmeth.3204).
This is an independent surface implementation, not the upstream engine: random
area samples seed the surface, then tangent-neighbor proposals fill its gaps.
There is no lattice and no claim of globally optimal or atomistic packing.
"""

import copy
import math

import numpy as np
from scipy.spatial import cKDTree

from .membrane_cellpack import (ENGINE, MAX_FILL_PARTICLES, MAX_RECIPE_PARTICLES, MAX_PROTEIN_TRIANGLES,
                               SurfacePacker, mesh_digest)
from .membrane_lattice import conflict_graph
from .membrane_collision import ProteinMesh, outside_protein_meshes
from .membrane_protein import instance_matrices, validate_pdb_id, validate_protein
from .membrane_molecule import (AtomSpheres, atom_positions, ingredient_source, lipid_key,
                               molecular_conflicts, molecular_lipid, validate_template)

MAX_BATCH = 8192
MAX_ROUNDS = 240
PALETTE = [(214, 196, 128, 255), (86, 143, 214, 255), (84, 190, 168, 255),
           (240, 151, 88, 255), (201, 118, 164, 255)]


def default_recipe(radius=20):
    return [dict(key="lipids", label="Lipids", kind="lipid", enabled=True,
                 amount=100., radius=float(radius), region="both", pdb_id="", axis="Z"),
            dict(key="protein", label="Protein", kind="protein", enabled=False,
                 amount=20., radius=20., region="outer", pdb_id="", axis="Z")]


def validate_recipe(recipe):
    if not isinstance(recipe, list) or not 1 <= len(recipe) <= 20:
        raise ValueError("Choose 1-20 ingredient entries.")
    seen, total_protein, active = set(), 0., []
    for entry in recipe:
        if not isinstance(entry, dict):
            raise ValueError("Invalid ingredient entry.")
        key = entry.get("key")
        kind = entry.get("kind")
        amount, radius = float(entry.get("amount", -1)), float(entry.get("radius", 0))
        if (not isinstance(key, str) or not key or key in seen
                or kind not in ("lipid", "protein", "other")
                or not isinstance(entry.get("enabled"), bool)
                or not isinstance(entry.get("label"), str) or not entry["label"].strip()
                or not math.isfinite(amount) or not 0 <= amount <= 100
                or not math.isfinite(radius) or not 0 < radius <= 10000
                or entry.get("region") not in ("both", "outer", "inner")
                or entry.get("axis") not in ("X", "Y", "Z", "-X", "-Y", "-Z")):
            raise ValueError("Invalid ingredient name, type, amount, radius or leaflet.")
        seen.add(key)
        source = ingredient_source(entry)
        if source not in (("bead", "pdb", "file") if kind == "lipid" else
                          ("pdb",) if kind == "protein" else ("bead",)):
            raise ValueError("Invalid ingredient source; lipids support beads, PDB IDs or local files.")
        if entry["enabled"] and amount > 0:
            if molecular_lipid(entry):
                lipid_key(entry)
            if kind == "protein":
                validate_pdb_id(entry.get("pdb_id", ""))
                if entry["region"] != "outer":
                    raise ValueError("Proteins use the outer normal and span the membrane mid-plane.")
                total_protein += amount
            active.append(entry)
    if total_protein > 100 + 1e-8:
        raise ValueError("Total enabled protein coverage must not exceed 100%.")
    if not active:
        raise ValueError("Enable at least one ingredient with a positive amount.")
    return active


def template_key(entry):
    if molecular_lipid(entry):
        return lipid_key(entry)
    return validate_pdb_id(entry["pdb_id"]) + ":" + entry["axis"]


class MeshLeaflet:
    """Area sampling and local triangle projection, without cylinder coordinates."""

    def __init__(self, model, mask):
        faces = np.asarray(model.vertices, float)[np.asarray(model.triangles)[mask]]
        cross = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
        area = np.linalg.norm(cross, axis=1) / 2
        valid = area > 1e-12
        self.faces, area = faces[valid], area[valid]
        if not len(area):
            raise ValueError("Membrane leaflet has no usable faces.")
        self.normals = cross[valid] / (2*area[:, None])
        self.cumulative = np.cumsum(area)
        self.area = float(self.cumulative[-1])
        self.tree = cKDTree(self.faces.mean(axis=1))

    def sample(self, rng, count):
        samples = rng.random((count, 3))
        indices = np.searchsorted(self.cumulative, samples[:, 0]*self.area)
        u, v = np.sqrt(samples[:, 1]), samples[:, 2]
        faces = self.faces[indices]
        points = ((1-u)[:, None]*faces[:, 0] + (u*(1-v))[:, None]*faces[:, 1]
                  + (u*v)[:, None]*faces[:, 2])
        return points, self.normals[indices]

    def project(self, points, return_faces=False):
        # Local projection tests several triangles, including edges. Every output
        # lies on an actual face; it is not a bilinear/ideal-cylinder approximation.
        _, indices = self.tree.query(points, k=min(8, len(self.faces)))
        indices = indices.reshape((len(points), -1))
        faces, normals = self.faces[indices], self.normals[indices]
        delta = points[:, None, :]-faces[:, :, 0]
        projected = points[:, None, :] - np.sum(delta*normals, axis=2)[:, :, None]*normals
        a, b = faces[:, :, 1]-faces[:, :, 0], faces[:, :, 2]-faces[:, :, 0]
        d = projected-faces[:, :, 0]
        aa, ab, bb = np.sum(a*a, 2), np.sum(a*b, 2), np.sum(b*b, 2)
        ad, bd = np.sum(a*d, 2), np.sum(b*d, 2)
        det = np.maximum(aa*bb-ab*ab, 1e-30)
        u, v = (bb*ad-ab*bd)/det, (aa*bd-ab*ad)/det
        inside = (u >= 0) & (v >= 0) & (u+v <= 1)
        best = projected.copy()
        distance = np.sum((best-points[:, None, :])**2, 2)
        distance[~inside] = np.inf
        for i, j in ((0, 1), (1, 2), (2, 0)):
            edge = faces[:, :, j]-faces[:, :, i]
            t = np.clip(np.sum((points[:, None, :]-faces[:, :, i])*edge, 2)
                        / np.maximum(np.sum(edge*edge, 2), 1e-30), 0, 1)
            candidate = faces[:, :, i] + t[:, :, None]*edge
            dist = np.sum((candidate-points[:, None, :])**2, 2)
            better = dist < distance
            best[better], distance[better] = candidate[better], dist[better]
        nearest = np.argmin(distance, axis=1)
        rows = np.arange(len(points))
        if return_faces:
            return best[rows, nearest], normals[rows, nearest], indices[rows, nearest]
        return best[rows, nearest], normals[rows, nearest]

    def contains(self, points, indices):
        faces = self.faces[indices]
        a, b, d = faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0], points-faces[:, 0]
        aa, ab, bb = np.sum(a*a, 1), np.sum(a*b, 1), np.sum(b*b, 1)
        ad, bd = np.sum(a*d, 1), np.sum(b*d, 1)
        det = np.maximum(aa*bb-ab*ab, 1e-30)
        u, v = (bb*ad-ab*bd)/det, (aa*bd-ab*ad)/det
        return (u >= 0) & (v >= 0) & (u+v <= 1)


class GrowingSites:
    """Append-only sites with a bulk tree plus a small, freshly indexed tail."""

    def __init__(self, capacity):
        self.points = np.empty((capacity, 3))
        self.normals = np.empty((capacity, 3))
        self.count = self.indexed = 0
        self.tree = None

    def add(self, points, normals):
        end = self.count + len(points)
        self.points[self.count:end] = points
        self.normals[self.count:end] = normals
        self.count = end

    def query(self, points, k=1):
        if self.tree is None or self.count-self.indexed >= max(512, min(4096, self.indexed//4)):
            self.tree = cKDTree(self.points[:self.count])
            self.indexed = self.count
        distances, indices = self.tree.query(points, k=k)
        if self.count > self.indexed:
            td, ti = cKDTree(self.points[self.indexed:self.count]).query(points, k=k)
            ti = ti+self.indexed
            if k == 1:
                nearer = td < distances
                distances[nearer], indices[nearer] = td[nearer], ti[nearer]
            else:
                all_d = np.column_stack((distances, td))
                all_i = np.column_stack((indices, ti))
                order = np.argsort(all_d, axis=1, kind="stable")[:, :k]
                distances = np.take_along_axis(all_d, order, axis=1)
                indices = np.take_along_axis(all_i, order, axis=1)
        return distances, indices


class RecipePacker:
    """Random area seeding followed by collision-checked near-contact gap filling."""

    def __init__(self, model, recipe, templates=None, max_particles=None, seed=1):
        active = validate_recipe(recipe)
        # Reuse the legacy mesh validation without changing its placement API.
        SurfacePacker(model, [dict(suffix="check", label="check", role="lipid", color=[0]*4,
                      particle_radius=1, abundance_weight=1, target_percentage=100)], 1, seed)
        if max_particles is not None and not 1 <= int(max_particles) <= MAX_RECIPE_PARTICLES:
            raise ValueError("Use 1-1,000,000 maximum particles, or automatic dense fill.")
        self.recipe, self.templates = copy.deepcopy(recipe), {}
        for entry in active:
            if entry["kind"] == "protein" or molecular_lipid(entry):
                key = template_key(entry)
                template = (templates or {}).get(key)
                validate_template(template)
                if template_key(template) != key:
                    raise ValueError("Molecular template does not match its source and axis.")
                self.templates[key] = copy.deepcopy(template)
        outer = getattr(model, "_cb_membrane_outer_faces", None)
        inner = getattr(model, "_cb_membrane_inner_faces", None)
        if outer is None or inner is None:
            raise ValueError("Rebuild or reload this membrane to initialize its leaflets.")
        self.leaflets = {"outer": MeshLeaflet(model, outer), "inner": MeshLeaflet(model, inner)}
        self.thickness = float(model._cb_membrane_state["thickness"])
        self.seed = int(seed)
        self.automatic_budget = max_particles is None
        self.rng = np.random.default_rng(seed)
        self.digest = mesh_digest(model)
        self.groups, self.tasks = [], []
        self._bead_sites = {}
        self.mixed_beads = sum(e["kind"] != "protein" for e in active) > 1
        protein_fraction = sum(e["amount"] for e in active if e["kind"] == "protein") / 100
        quotas = []
        for index, entry in enumerate(active):
            protein = self.templates.get(template_key(entry)) if entry["kind"] == "protein" or molecular_lipid(entry) else None
            radius = protein["radius"] if protein else entry["radius"]
            group = dict(suffix=entry["key"], label=entry["label"], role=entry["kind"],
                         color=list(PALETTE[index % len(PALETTE)]), radius=float(radius),
                         percentage=entry["amount"], requested_count=0, positions=[], normals=[], spins=[],
                         template_key=template_key(entry) if protein else None, region=entry["region"])
            self.groups.append(group)
            if entry["kind"] == "protein":
                quota = int(self.leaflets["outer"].area * entry["amount"]/100
                            / (math.pi*protein["footprint_radius"]**2))
                quotas.append([index, "outer", quota])
            else:
                for region in ("outer", "inner"):
                    if entry["region"] not in ("both", region):
                        continue
                    weight = sum(e["amount"] for e in active if e["kind"] != "protein"
                                 and e["region"] in ("both", region))
                    quota = int(.90*self.leaflets[region].area*(1-protein_fraction)
                                * entry["amount"]/weight/(math.pi*(protein["footprint_radius"] if protein else radius)**2))
                    quotas.append([index, region, quota])
        triangle_count = sum(q*len(self.templates[self.groups[i]["template_key"]]["triangles"])
                             for i, _, q in quotas if self.groups[i]["template_key"])
        self.render_limited = triangle_count > MAX_PROTEIN_TRIANGLES
        if self.render_limited:
            for task in quotas:
                if self.groups[task[0]]["template_key"]:
                    task[2] = int(task[2]*MAX_PROTEIN_TRIANGLES/triangle_count)
        total = sum(q[2] for q in quotas)
        self.area_target = total
        if self.automatic_budget and total > MAX_RECIPE_PARTICLES:
            raise ValueError(f"Dense fill needs about {total:,} particles at these radii, above the "
                             f"{MAX_RECIPE_PARTICLES:,} safety ceiling. Increase bead radius or reduce "
                             "membrane area. A manual particle limit makes a sparse preview, not dense fill.")
        self.limit = max(1, total) if self.automatic_budget else int(max_particles)
        self.limit_reached = total > self.limit
        if self.limit_reached:
            raw = np.array([task[2] for task in quotas])
            # When the cap permits, retain every nonzero requested ingredient /
            # leaflet rather than rounding rare proteins out of the recipe.
            base = (raw > 0).astype(int) if self.limit >= np.count_nonzero(raw) else np.zeros(len(raw), int)
            remainder = raw-base
            scaled = base + remainder*(self.limit-base.sum())/remainder.sum()
            counts = np.floor(scaled).astype(int)
            for i in np.argsort(-(scaled-counts), kind="stable")[:self.limit-counts.sum()]:
                counts[i] += 1
            for task, count in zip(quotas, counts):
                task[2] = int(count)
        for i, region, quota in quotas:
            self.groups[i]["requested_count"] += quota
            if quota:
                self.tasks.append((i, region, quota))
        self.tasks.sort(key=lambda t: (self.groups[t[0]]["role"] != "protein",
                                       -self.groups[t[0]]["radius"]))
        self.count = sum(g["requested_count"] for g in self.groups)
        if not self.count:
            raise ValueError("No requested particles fit the area/limits. Increase the limit or reduce sizes.")
        self.placed, self.candidate_count = 0, 0
        self._sites = [GrowingSites(g["requested_count"]) for g in self.groups]
        self._protein_boxes = {}
        self._protein_meshes = {}
        self._lipid_atoms = {}
        self.done, self._cancelled = False, False
        self._work = self._pack()

    def _clear(self, points, radius, group, normals=None, spins=None):
        if group.get("role") == "lipid" and group["template_key"]:
            template = self.templates[group["template_key"]]
            radii = np.asarray(template["atom_radii"])
            keep = np.ones(len(points), bool)
            block = max(1, 8192//len(radii))
            for start in range(0, len(points), block):
                atoms = atom_positions(template, points[start:start+block], normals[start:start+block], spins[start:start+block])
                allowed = np.ones(atoms.shape[:2], bool)
                for r in np.unique(radii):
                    mask = radii == r
                    allowed[:, mask] = self._clear(atoms[:, mask].reshape((-1, 3)), r,
                                                   {"template_key": None}).reshape((len(atoms), -1))
                keep[start:start+block] = allowed.all(1)
            return keep
        keep = np.ones(len(points), bool)
        for other, sites in zip(self.groups, self._sites):
            if not sites.count:
                continue
            if other["role"] == "lipid" and other["template_key"]:
                cached = self._lipid_atoms.get(other["suffix"])
                if cached is None or cached[0] != sites.count:
                    template = self.templates[other["template_key"]]
                    atoms = atom_positions(template, other["positions"], other["normals"], other["spins"])
                    cached = (sites.count, AtomSpheres(atoms.reshape((-1, 3)),
                                                    np.tile(template["atom_radii"], sites.count)))
                    self._lipid_atoms[other["suffix"]] = cached
                keep[keep] &= cached[1].clear(points[keep], radius)
            elif other["template_key"] and not group["template_key"]:
                cached = self._protein_boxes.get(other["suffix"])
                if cached is None or cached[0] != sites.count:
                    key = other["template_key"]
                    if key not in self._protein_meshes:
                        template = self.templates[key]
                        self._protein_meshes[key] = ProteinMesh(template["vertices"], template["triangles"])
                    rotations = instance_matrices(other["positions"], other["normals"], other["spins"])[:, :, :3]
                    cached = (sites.count, cKDTree(sites.points[:sites.count]), rotations,
                              self._protein_meshes[key])
                    self._protein_boxes[other["suffix"]] = cached
                _, tree, rotations, mesh = cached
                # Do not spend exact mesh queries on candidates already rejected
                # by beads/other proteins. Bounds alone must never reject a site.
                keep[keep] &= outside_protein_meshes(points[keep], tree, rotations,
                            mesh, other["radius"], radius, .001*radius)
            else:
                distance, _ = sites.query(points)
                keep &= distance >= radius+other["radius"]+.001*min(radius, other["radius"])
        return keep

    def _contacts(self, points, normals, radius, leaflet, visits, radii=None, tree=None):
        # Random tangent directions near one neighbor, plus two-neighbor contact
        # intersections. Random front order avoids a coherent hexagonal lattice.
        front = np.flatnonzero(visits < 3)
        if not len(front):
            front = np.arange(len(points))
        size = min(len(front), MAX_BATCH//16)
        choose = self.rng.choice(front, size=size, replace=False)
        visits[choose] += 1
        centers, n = points[choose], normals[choose]
        if radii is None:
            radii = np.full(len(points), radius)
        helper = np.zeros_like(n)
        helper[np.arange(len(n)), np.argmin(abs(n), axis=1)] = 1
        x = np.cross(n, helper)
        x /= np.linalg.norm(x, axis=1)[:, None]
        y = np.cross(n, x)
        angle = self.rng.uniform(0, 2*math.pi, (size, 2))
        distance = (radii[choose]+radius)*1.002
        proposals = (centers[:, None, :] + distance[:, None, None]*(np.cos(angle)[:, :, None]*x[:, None, :]
                                                    + np.sin(angle)[:, :, None]*y[:, None, :])).reshape((-1, 3))
        if tree is None:
            tree = cKDTree(points)
        distances, neighbors = tree.query(centers, k=min(9, len(points)))
        distances = distances.reshape((len(centers), -1))
        neighbors = neighbors.reshape((len(centers), -1))
        distances, neighbors = distances[:, 1:], neighbors[:, 1:]
        other_distance = (radii[neighbors]+radius)*1.002
        a, b = np.nonzero((distances > np.abs(distance[:, None]-other_distance))
                         & (distances < distance[:, None]+other_distance))
        contact, contact_normals = np.empty((0, 3)), np.empty((0, 3))
        if len(a):
            order = self.rng.permutation(len(a))[:MAX_BATCH//4]
            a, b = a[order], b[order]
            p, q = centers[a], points[neighbors[a, b]]
            da, db = distance[a], other_distance[a, b]
            delta = q-p
            d = np.linalg.norm(delta, axis=1)
            normal = n[a]+normals[neighbors[a, b]]
            tangent = np.cross(normal, delta)
            tangent /= np.maximum(np.linalg.norm(tangent, axis=1)[:, None], 1e-30)
            along = (da*da-db*db+d*d)/(2*d)
            h = np.sqrt(np.maximum(da*da-along*along, 0))
            mid = p+(along/d)[:, None]*delta
            contact = np.concatenate((mid+h[:, None]*tangent, mid-h[:, None]*tangent))
            contact_normals = np.empty_like(contact)
            p, q = np.tile(p, (2, 1)), np.tile(q, (2, 1))
            da, db = np.tile(da, 2), np.tile(db, 2)
            # Intersect the two exclusion spheres with the current face plane.
            # Reprojection alone shortens chord distances on curved surfaces.
            pending = np.arange(len(contact))
            for _ in range(3):
                if not len(pending):
                    break
                current, normal, faces = leaflet.project(contact[pending], return_faces=True)
                pa = np.sum((p[pending]-current)*normal, axis=1)
                pb = np.sum((q[pending]-current)*normal, axis=1)
                pc, qc = p[pending]-pa[:, None]*normal, q[pending]-pb[:, None]*normal
                line = qc-pc
                length = np.maximum(np.linalg.norm(line, axis=1), 1e-12)
                line /= length[:, None]
                ra2, rb2 = da[pending]**2-pa*pa, db[pending]**2-pb*pb
                along = (ra2-rb2+length*length)/(2*length)
                height = np.sqrt(np.maximum(ra2-along*along, 0))
                side = np.cross(normal, line)
                center = pc+along[:, None]*line
                sign = np.where(np.sum((current-center)*side, axis=1) < 0, -1, 1)
                candidate = center+(sign*height)[:, None]*side
                contact[pending], contact_normals[pending] = candidate, normal
                pending = pending[~leaflet.contains(candidate, faces)]
            if len(pending):
                contact[pending], contact_normals[pending] = leaflet.project(contact[pending])
        projected, face_normals = leaflet.project(proposals)
        close = np.linalg.norm(projected-proposals, axis=1) < radius*.5
        return np.concatenate((contact, projected[close])), np.concatenate((contact_normals, face_normals[close]))

    def _pack(self):
        proteins = [t for t in self.tasks if self.groups[t[0]]["role"] == "protein"]
        beads = [t for t in self.tasks if self.groups[t[0]]["role"] != "protein"]
        yield from self._pack_tasks(proteins)
        if len({t[0] for t in beads}) <= 1:
            yield from self._pack_tasks(beads)
            return
        # Mixed beads must grow together, not fill one species' domains first
        # and force every later species into a macroscopic leftover patch.
        minimum_radius = min(self.groups[t[0]]["radius"] for t in beads)
        workers = [(self._pack_tasks([task]), min(4, max(1, round(self.groups[task[0]]["radius"]/minimum_radius))))
                   for task in beads]
        try:
            while workers:
                for index in self.rng.permutation(len(workers)):
                    item = workers[index]
                    if item is None:
                        continue
                    worker, priority = item
                    for _ in range(priority):
                        try:
                            next(worker)
                            yield
                        except StopIteration:
                            workers[index] = None
                            break
                workers = [w for w in workers if w is not None]
        finally:
            for item in workers:
                if item is not None:
                    item[0].close()

    def _pack_tasks(self, tasks):
        for index, region, quota in tasks:
            group, leaflet = self.groups[index], self.leaflets[region]
            is_protein = group["role"] == "protein"
            molecule = self.templates[group["template_key"]] if group["template_key"] and not is_protein else None
            radius, accepted = molecule["footprint_radius"] if molecule else group["radius"], 0
            sites = GrowingSites(quota)
            if not is_protein:
                self._bead_sites[index, region] = (sites, radius)
            visits = np.zeros(quota, dtype=np.int32)
            stagnant = 0
            gap_sweeps, probe_pending = 0, False
            protein_gaps = not is_protein and any(
                g["role"] == "protein" and len(g["positions"]) for g in self.groups)
            coverage = quota*math.pi*radius**2/leaflet.area
            # The search budget must grow with surface population, just as its
            # particle budget does. A fixed 240 rounds starves small-radius layers.
            normal_rounds = MAX_ROUNDS + quota//100
            for round_index in range(normal_rounds + (8 if protein_gaps else 0)):
                if accepted >= quota:
                    break
                # A fixed work schedule keeps the seed independent of GUI timer batches.
                # Sparse/minority recipes need dispersed seeds, not a few growing
                # islands. Dense layers use fewer nuclei to reduce grain-boundary gaps.
                seed_fraction = 2. if coverage < .3 else (.1 if coverage < .7 else .002)
                if self.mixed_beads:
                    seed_fraction = .1
                samples = min(MAX_BATCH, max(8, int(quota*seed_fraction))) if not accepted else 4
                # Four new seeds can miss isolated pockets beside a protein.
                # After front saturation, probe the whole leaflet in bounded
                # batches and let any new sites restart contact growth.
                if probe_pending or round_index >= normal_rounds:
                    if gap_sweeps >= 8:
                        break
                    samples = MAX_BATCH
                    gap_sweeps += 1
                    probe_pending = False
                if is_protein:
                    samples = min(MAX_BATCH, max(256, 2*(quota-accepted)))
                points, normals = leaflet.sample(self.rng, samples)
                if accepted and not is_protein:
                    if self.mixed_beads:
                        shared = [(s, r) for (i, side), (s, r) in self._bead_sites.items()
                                  if side == region and s.count]
                        pp = np.concatenate([s.points[:s.count] for s, r in shared])
                        nn = np.concatenate([s.normals[:s.count] for s, r in shared])
                        rr = np.concatenate([np.full(s.count, r) for s, r in shared])
                        contact, contact_normals = self._contacts(pp, nn, radius, leaflet,
                                                                   np.zeros(len(pp), int), rr)
                    else:
                        contact, contact_normals = self._contacts(sites.points[:accepted], sites.normals[:accepted],
                                                                  radius, leaflet, visits[:accepted], tree=sites)
                    points, normals = np.concatenate((contact, points)), np.concatenate((contact_normals, normals))
                self.candidate_count += len(points)
                if is_protein:
                    points = points-normals*self.thickness/2
                spins = self.rng.uniform(0, 2*math.pi, len(points)) if molecule else None
                keep = self._clear(points, radius, group, normals, spins)
                points, normals = points[keep], normals[keep]
                # Randomized two-neighbor contacts precede one-neighbor contacts
                # and new seeds. This is a proximity bias, never a row/lattice order.
                if molecule:
                    spins = spins[keep]
                    offsets, neighbors = molecular_conflicts(molecule, points, normals, spins)
                else:
                    offsets, neighbors = conflict_graph(points, 2*radius+.001*radius)
                blocked, chosen = np.zeros(len(points), bool), []
                for candidate in range(len(points)):
                    if not blocked[candidate]:
                        chosen.append(candidate)
                        blocked[neighbors[offsets[candidate]:offsets[candidate+1]]] = True
                        if len(chosen)+accepted >= quota:
                            break
                if chosen:
                    selected, ns = points[chosen], normals[chosen]
                    group["positions"].extend(selected.tolist())
                    group["normals"].extend(ns.tolist())
                    group["spins"].extend((spins[chosen] if molecule else self.rng.uniform(0, 2*math.pi, len(chosen))).tolist())
                    sites.add(selected, ns)
                    self._sites[index].add(selected, ns)
                    accepted += len(chosen)
                    self.placed += len(chosen)
                    stagnant = 0
                else:
                    stagnant += 1
                yield
                if stagnant >= 5:
                    if protein_gaps and gap_sweeps < 8:
                        probe_pending, stagnant = True, 0
                    else:
                        break

    def step(self, batch_size=256):
        if self._cancelled:
            raise ValueError("Packing was cancelled.")
        if not self.done:
            try:
                next(self._work)
            except StopIteration:
                self.done = True
        return self.done

    def cancel(self):
        self._cancelled = True
        self._work.close()
        self._bead_sites.clear()
        self._sites.clear()
        self._protein_boxes.clear()
        self._protein_meshes.clear()
        self._lipid_atoms.clear()

    def result(self):
        if self._cancelled or not self.done:
            raise ValueError("Packing has not finished or was cancelled.")
        if not self.placed:
            raise ValueError("No particles fitted. Reduce sizes or protein coverage.")
        version = 7 if any(molecular_lipid(e) for e in self.recipe) else 6
        return dict(schema="ciliabuilder_membrane_packing_v1", engine=ENGINE, algorithm_version=version,
                    particle_only=True, placement_method="random-neighbor-close-packing",
                    protein_lipid_exclusion="triangle-mesh",
                    seed=self.seed, mesh_digest=self.digest, recipe=copy.deepcopy(self.recipe),
                    templates=copy.deepcopy(self.templates), groups=copy.deepcopy(self.groups),
                    requested_count=self.count, placed_count=self.placed, particle_limit=self.limit,
                    automatic_particle_budget=self.automatic_budget, area_target_count=self.area_target,
                    candidate_count=self.candidate_count, particle_limit_reached=self.limit_reached,
                    protein_render_limit_reached=self.render_limited,
                    outer_area=self.leaflets["outer"].area, inner_area=self.leaflets["inner"].area,
                    protein_percent=sum(e["amount"] for e in self.recipe if e["enabled"] and e["kind"] == "protein"),
                    achieved_protein_percent=sum(len(g["positions"])*math.pi
                        * self.templates[g["template_key"]]["footprint_radius"]**2
                        / self.leaflets["outer"].area*100 for g in self.groups if g["role"] == "protein"))


def validate_recipe_result(result):
    active = {e["key"]: e for e in validate_recipe(result.get("recipe"))}
    groups, templates = result["groups"], result.get("templates")
    if not isinstance(templates, dict) or len(templates) > 20 or set(active) != {g["suffix"] for g in groups}:
        raise ValueError("Saved ingredients do not match the packing recipe.")
    used, triangles = set(), 0
    for group in groups:
        entry = active[group["suffix"]]
        spin = np.asarray(group.get("spins"), float)
        if spin.shape != (len(group["positions"]),) or not np.isfinite(spin).all():
            raise ValueError("Invalid saved particle spin angles.")
        if group["role"] != entry["kind"] or group.get("region") != entry["region"]:
            raise ValueError("Saved ingredient type/leaflet does not match the recipe.")
        key = group.get("template_key")
        if entry["kind"] == "protein" or molecular_lipid(entry):
            if molecular_lipid(entry) and result.get("algorithm_version") != 7:
                raise ValueError("Molecular lipids require packing format version 7.")
            if key != template_key(entry):
                raise ValueError("Saved molecular reference does not match its recipe.")
            protein = templates.get(key)
            validate_template(protein)
            if template_key(protein) != key or abs(group["radius"]-protein["radius"]) > 1e-5:
                raise ValueError("Invalid molecular template identity/radius.")
            used.add(key)
            triangles += len(group["positions"])*len(protein["triangles"])
        elif key is not None or abs(group["radius"]-entry["radius"]) > 1e-5:
            raise ValueError("Invalid bead template/radius.")
    if set(templates) != used or triangles > MAX_PROTEIN_TRIANGLES:
        raise ValueError("Invalid or oversized packed molecular templates.")
    if (not 0 <= int(result.get("seed", -1)) <= 2147483647
            or not 1 <= int(result.get("particle_limit", 0)) <= (MAX_RECIPE_PARTICLES
                if result.get("algorithm_version") in (5, 6, 7) else MAX_FILL_PARTICLES)
            or result["requested_count"] > result["particle_limit"]):
        raise ValueError("Invalid saved packing limits/seed.")
    if result.get("algorithm_version") in (5, 6, 7):
        automatic, target = result.get("automatic_particle_budget"), result.get("area_target_count")
        if (not isinstance(automatic, bool) or not isinstance(target, int) or target < result["requested_count"]
                or (automatic and (target != result["requested_count"] or result["particle_limit_reached"]))):
            raise ValueError("Invalid saved density budget.")
    if result.get("algorithm_version") in (6, 7) and result.get("protein_lipid_exclusion") != "triangle-mesh":
        raise ValueError("Invalid saved protein collision method.")
    for key in ("outer_area", "inner_area"):
        area = float(result.get(key, 0))
        if not math.isfinite(area) or area <= 0:
            raise ValueError("Invalid saved leaflet area.")
    expected = sum(e["amount"] for e in active.values() if e["kind"] == "protein")
    achieved = sum(len(g["positions"])*math.pi*templates[g["template_key"]]["footprint_radius"]**2
                   / result["outer_area"]*100 for g in groups if g["role"] == "protein")
    for key, target in (("protein_percent", expected), ("achieved_protein_percent", achieved)):
        value = float(result.get(key, float("nan")))
        if not math.isfinite(value) or abs(value-target) > 1e-5 or not 0 <= value <= 100+1e-5:
            raise ValueError("Saved protein coverage does not match its placements/recipe.")


def group_protein(result, group):
    if result.get("algorithm_version") in (4, 5, 6, 7):
        key = group.get("template_key")
        return result["templates"][key] if key else None
    return result.get("protein") if result.get("particle_only") and group["suffix"] == "protein" else None
