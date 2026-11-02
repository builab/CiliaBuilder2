"""Built-in membrane packing preview. This is cellPACK-style, not its engine."""

import copy
import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np

PACKING_KEY = "cellpack_packing"
MAX_PARTICLES = 10000
MAX_FILL_PARTICLES = 50000
MAX_RECIPE_PARTICLES = 1000000
MAX_PROTEIN_TRIANGLES = 10000000
ENGINE = "builtin-cellpack-style"


def mesh_digest(model):
    digest = hashlib.sha256()
    for array, dtype in ((model.vertices, "<f4"), (model.triangles, "<i4")):
        digest.update(np.asarray(array, dtype=dtype).tobytes())
    return digest.hexdigest()


def packing_classes(tool, base_radius):
    from .cellpack_export import _CellPackExporter
    return _CellPackExporter(tool, ".")._membrane_particle_class_defs(base_radius)


class SurfacePacker:
    """Seeded area-weighted surface sampling with spatial-hash sphere exclusion.

    Large ingredient classes are placed first, then small lipids fill remaining
    sites. Bounded steps allow the GUI to remain responsive without worker threads.
    """

    def __init__(self, model, classes, count=5000, seed=1):
        if not getattr(model, "_cb_generated_membrane", False):
            raise ValueError("Build or select a generated membrane first.")
        count, seed = int(count), int(seed)
        if not 1 <= count <= MAX_PARTICLES or not 0 <= seed <= 2147483647:
            raise ValueError(f"Use 1-{MAX_PARTICLES} particles and a non-negative 32-bit seed.")
        vertices = np.asarray(model.vertices, dtype=float)
        triangles = np.asarray(model.triangles, dtype=int)
        if (vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices)
                or not np.isfinite(vertices).all() or len(vertices) > 200000
                or triangles.ndim != 2 or triangles.shape[1] != 3 or not len(triangles)
                or len(triangles) > 400000
                or triangles.min() < 0 or triangles.max() >= len(vertices)):
            raise ValueError("Membrane mesh is invalid or too large for the preview packer.")
        self.faces = vertices[triangles].copy()
        cross = np.cross(self.faces[:, 1] - self.faces[:, 0], self.faces[:, 2] - self.faces[:, 0])
        areas = np.linalg.norm(cross, axis=1)
        valid = areas > 1e-12
        if not valid.any():
            raise ValueError("Membrane has no usable surface area.")
        self.faces = self.faces[valid]
        self.valid_faces = valid
        self.normals = cross[valid] / areas[valid, None]
        self.cumulative_area = np.cumsum(areas[valid])
        classes = [copy.deepcopy(c) for c in classes if float(c["abundance_weight"]) > 0]
        if not classes or len(classes) > 20:
            raise ValueError("No valid membrane ingredient classes.")
        radii = np.array([c["particle_radius"] for c in classes], dtype=float)
        weights = np.array([c["abundance_weight"] for c in classes], dtype=float)
        if not np.isfinite(radii).all() or np.min(radii) <= 0 or not np.isfinite(weights).all():
            raise ValueError("Ingredient radii and weights must be positive and finite.")
        quotas = count * weights / weights.sum()
        counts = np.floor(quotas).astype(int)
        for index in np.argsort(-(quotas - counts), kind="stable")[:count - counts.sum()]:
            counts[index] += 1
        self.groups = []
        for cls, target in sorted(zip(classes, counts), key=lambda pair: -pair[0]["particle_radius"]):
            self.groups.append({"suffix": cls["suffix"], "label": cls["label"],
                                "role": cls["role"], "color": list(cls["color"]),
                                "radius": float(cls["particle_radius"]),
                                "percentage": float(cls["target_percentage"]),
                                "requested_count": int(target), "positions": [], "normals": []})
        self.count, self.seed = count, seed
        self.digest = mesh_digest(model)
        self.rng = np.random.default_rng(seed)
        self.padding = float(radii.min()) * 0.01
        self.bin_size = float(2 * radii.max() + self.padding)
        self.bins = {}
        self.neighbors = list(itertools.product((-1, 0, 1), repeat=3))
        self.current_group = 0
        self.attempts = 0
        self.placed = 0

    @property
    def done(self):
        return self.current_group >= len(self.groups)

    def _candidate(self, point, index, group):
        return point, self.normals[index]

    def step(self, batch_size=256):
        if self.done:
            return True
        # Three random values per attempt keeps output independent of timer batching.
        samples = self.rng.random((batch_size, 3))
        indices = np.searchsorted(self.cumulative_area, samples[:, 0] * self.cumulative_area[-1])
        faces = self.faces[indices]
        u = np.sqrt(samples[:, 1])
        v = samples[:, 2]
        points = ((1 - u)[:, None] * faces[:, 0] + (u * (1 - v))[:, None] * faces[:, 1]
                  + (u * v)[:, None] * faces[:, 2])
        for point, index in zip(points, indices):
            while not self.done:
                group = self.groups[self.current_group]
                target = group["requested_count"]
                if len(group["positions"]) < target and self.attempts < max(200, target * 50):
                    break
                self.current_group += 1
                self.attempts = 0
            if self.done:
                break
            self.attempts += 1
            candidate = self._candidate(point, index, group)
            if candidate is None:
                continue
            point, normal = candidate
            radius = group["radius"]
            key = tuple(np.floor(point / self.bin_size).astype(np.int64))
            collision = False
            for offset in self.neighbors:
                nearby = tuple(key[i] + offset[i] for i in range(3))
                for other, other_radius in self.bins.get(nearby, ()):
                    delta = point - other
                    if np.dot(delta, delta) < (radius + other_radius + self.padding) ** 2:
                        collision = True
                        break
                if collision:
                    break
            if collision:
                continue
            self.bins.setdefault(key, []).append((point.copy(), radius))
            group["positions"].append(point.tolist())
            group["normals"].append(normal.tolist())
            self.placed += 1
        return self.done

    def result(self):
        if not self.done:
            raise ValueError("Packing has not finished.")
        if not self.placed:
            raise ValueError("No particles fitted. Try smaller ingredient radii.")
        return {"schema": "ciliabuilder_membrane_packing_v1", "engine": ENGINE,
                "algorithm_version": 1, "seed": self.seed, "mesh_digest": self.digest,
                "requested_count": self.count, "placed_count": self.placed,
                "groups": copy.deepcopy(self.groups)}


class MembraneFillPacker(SurfacePacker):
    """Legacy v3 row packer, retained for compatibility and regression comparisons.

    The interactive dialog now uses membrane_recipe.RecipePacker, not this path.
    Protein percentage is nominal outer-surface disk coverage, not particle count.
    Protein/protein exclusion uses conservative spheres; lipid/protein checks
    refine those bounds with the protein's oriented bounding box.
    """

    def __init__(self, model, lipid_radius=20, protein_percent=0, protein=None,
                 max_particles=MAX_FILL_PARTICLES, seed=1):
        radius, fraction = float(lipid_radius), float(protein_percent) / 100
        if (not math.isfinite(radius) or radius <= 0 or not math.isfinite(fraction)
                or not 0 <= fraction <= 1 or not 1 <= int(max_particles) <= MAX_FILL_PARTICLES):
            raise ValueError("Use a positive lipid radius, 0-100% protein coverage, and 1-50,000 particles.")
        if fraction:
            from .membrane_protein import validate_protein
            validate_protein(protein)
        self.protein = copy.deepcopy(protein) if fraction else None
        self.protein_percent = fraction * 100
        self.thickness = float(model._cb_membrane_state["thickness"])
        v = np.asarray(model.vertices, dtype=float)[model.triangles]
        areas = np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1) / 2
        outer = getattr(model, "_cb_membrane_outer_faces", None)
        inner = getattr(model, "_cb_membrane_inner_faces", None)
        if outer is None or inner is None:
            raise ValueError("Rebuild or reload this membrane to initialize its packing leaflets.")
        self.outer_area = float(areas[outer].sum())
        leaflet_area = float(areas[outer | inner].sum())
        protein_count = int(self.outer_area * fraction / (math.pi * protein["footprint_radius"]**2)) if fraction else 0
        # Near-hexagonal rows fill much more area than random sequential adsorption.
        lipid_count = int(round(0.90 * leaflet_area * (1 - fraction) / (math.pi * radius**2)))
        counts = np.array([protein_count, lipid_count], dtype=int)
        self.render_limited = False
        if fraction:
            protein_limit = MAX_PROTEIN_TRIANGLES // len(protein["triangles"])
            self.render_limited = counts[0] > protein_limit
            counts[0] = min(counts[0], protein_limit)
        self.limited = int(counts.sum()) > int(max_particles)
        self.particle_limit = int(max_particles)
        self.lipid_radius = radius
        if self.limited:
            quotas = counts * (int(max_particles) / counts.sum())
            counts = np.floor(quotas).astype(int)
            for i in np.argsort(-(quotas - counts), kind="stable")[:int(max_particles) - counts.sum()]:
                counts[i] += 1
        if counts.sum() == 0:
            raise ValueError("No particles fit the requested area. Use a smaller lipid radius or protein.")
        classes = []
        for suffix, label, color, r, number in (
            ("protein", f"PDB {protein['pdb_id']}" if fraction else "Protein", (85, 155, 216, 255),
             protein["radius"] if fraction else radius, counts[0]),
            ("lipids", "Lipid particles", (218, 190, 113, 255), radius, counts[1]),
        ):
            if number:
                classes.append(dict(suffix=suffix, label=label, role=suffix, color=color,
                                    particle_radius=r, abundance_weight=int(number),
                                    target_percentage=fraction * 100 if suffix == "protein" else (1-fraction)*100))
        super().__init__(model, classes, min(MAX_PARTICLES, int(counts.sum())), seed)
        self.outer_faces = np.asarray(outer)[self.valid_faces]
        self.leaflet_faces = np.asarray(outer | inner)[self.valid_faces]
        self.count = int(counts.sum())
        self.groups.sort(key=lambda g: g["suffix"] != "protein")
        for group in self.groups:
            group["requested_count"] = int(counts[0 if group["suffix"] == "protein" else 1])
        from .membrane_lattice import Leaflet
        self.leaflets = [Leaflet(model), Leaflet(model, inner=True)]
        self.leaflet_area = leaflet_area
        self.candidate_count = 0
        self._batch_size = 256
        self._cancelled = False
        self._work = self._pack_lattice()

    def _pack_lattice(self):
        from scipy.spatial import cKDTree
        from .membrane_lattice import MAX_CANDIDATES, conflict_graph, outside_protein_boxes

        protein_tree = None
        protein_radius = 0
        protein_rotations = protein_bounds = None
        for group in self.groups:
            is_protein = group["suffix"] == "protein"
            target, radius = group["requested_count"], group["radius"]
            area = self.outer_area if is_protein else self.leaflet_area
            if is_protein:
                pitch = math.sqrt(2*area / (math.sqrt(3)*max(1, target)*1.15))
            else:
                pitch = 2.02*radius
            # Bound candidates before allocation, even with a tiny user bead radius.
            passes = [(0, 0.5)] if is_protein else [(0, 0.5), (1/3, 1/6), (2/3, 5/6)]
            minimum_pitch = math.sqrt(2*area / (math.sqrt(3)*min(MAX_CANDIDATES/(1.1*len(passes)), self.particle_limit*2)))
            if pitch < minimum_pitch:
                pitch = minimum_pitch
                self.limited = True
            positions, normals = [], []
            total = 0
            phase = self.rng.random()
            # Keep the primary hexagonal rows first. Two fixed shifted passes can
            # fill holes at dome seams/protein boundaries, without random retries.
            for shift, offset in passes:
                for layer, leaflet in enumerate(self.leaflets[:1] if is_protein else self.leaflets):
                    for xyz, normal in leaflet.rows(pitch, phase + shift + 0.5*layer, offset):
                        total += len(xyz)
                        if total > MAX_CANDIDATES:
                            raise ValueError("Too many membrane sites. Increase the particle radius.")
                        if is_protein:
                            xyz = xyz - normal*(self.thickness*0.5)
                        positions.append(xyz)
                        normals.append(normal)
                        yield
            points, axes = np.concatenate(positions), np.concatenate(normals)
            self.candidate_count += len(points)
            if protein_tree is not None and len(points):
                keep = outside_protein_boxes(points, protein_tree, protein_rotations, protein_bounds,
                                             protein_radius, radius, self.padding)
                points, axes = points[keep], axes[keep]
            offsets, neighbors = conflict_graph(points, 2*radius + self.padding)
            blocked = np.zeros(len(points), dtype=bool)
            accepted = []
            previous_count = self.placed
            yield
            for i in range(len(points)):
                if not blocked[i]:
                    blocked[neighbors[offsets[i]:offsets[i+1]]] = True
                    accepted.append(i)
                    self.placed = previous_count + min(len(accepted), target)
                if (i+1) % self._batch_size == 0:
                    yield
            # Keep the close-packed row ordering during collision removal; shuffling
            # that pass creates holes. Apply any quota uniformly only afterward.
            if len(accepted) > target:
                accepted = self.rng.choice(accepted, size=target, replace=False)
            group["positions"] = points[accepted].tolist()
            group["normals"] = axes[accepted].tolist()
            if is_protein and group["positions"]:
                from .membrane_protein import instance_matrices
                protein_tree = cKDTree(group["positions"])
                protein_radius = radius
                protein_rotations = instance_matrices(group["positions"], group["normals"])[:, :, :3]
                vertices = np.asarray(self.protein["vertices"])
                protein_bounds = vertices.min(axis=0), vertices.max(axis=0)
            self.current_group += 1
            yield

    def step(self, batch_size=256):
        if self._cancelled:
            raise ValueError("Membrane packing was cancelled.")
        self._batch_size = max(1, int(batch_size))
        if not self.done:
            try:
                next(self._work)
            except StopIteration:
                self.current_group = len(self.groups)
        if self.done:
            self._work.close()
        return self.done

    def cancel(self):
        self._cancelled = True
        self._work.close()

    def result(self):
        if self._cancelled:
            raise ValueError("Membrane packing was cancelled.")
        result = super().result()
        placed_proteins = sum(len(g["positions"]) for g in self.groups if g["suffix"] == "protein")
        coverage = (placed_proteins * math.pi * self.protein["footprint_radius"]**2 / self.outer_area * 100
                    if self.protein else 0)
        result.update(algorithm_version=3, particle_only=True, protein=self.protein,
                      protein_percent=self.protein_percent, achieved_protein_percent=coverage,
                      lipid_radius=self.lipid_radius, particle_limit=self.particle_limit,
                      outer_area=self.outer_area, particle_limit_reached=self.limited,
                      protein_render_limit_reached=bool(self.render_limited),
                      placement_method="staggered-mesh-rows", candidate_count=self.candidate_count,
                      protein_lipid_exclusion="oriented-bounding-box")
        return result


def validate_result(result):
    if (not isinstance(result, dict) or result.get("schema") != "ciliabuilder_membrane_packing_v1"
            or result.get("engine") != ENGINE):
        raise ValueError("Not a built-in CiliaBuilder membrane packing result.")
    total = 0
    requested_total = 0
    seen = set()
    limit = (MAX_RECIPE_PARTICLES if result.get("algorithm_version") in (5, 6, 7) else
             MAX_FILL_PARTICLES if result.get("particle_only") else MAX_PARTICLES)
    groups = result.get("groups", [])
    if not isinstance(groups, list) or not 1 <= len(groups) <= 20:
        raise ValueError("Invalid membrane ingredient groups.")
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Invalid membrane ingredient group.")
        positions = np.asarray(group.get("positions"), dtype=float)
        normals = np.asarray(group.get("normals"), dtype=float)
        if positions.shape == (0,):
            positions = positions.reshape((0, 3))
        if normals.shape == (0,):
            normals = normals.reshape((0, 3))
        radius = float(group.get("radius", 0))
        color = group.get("color", [])
        suffix = str(group.get("suffix", ""))
        requested = int(group.get("requested_count", 0))
        percentage = float(group.get("percentage", 0))
        if (positions.ndim != 2 or positions.shape[1] != 3
                or not np.isfinite(positions).all() or not np.isfinite(normals).all()
                or normals.shape != positions.shape or not math.isfinite(radius) or radius <= 0
                or not 0 <= len(positions) <= requested <= limit
                or not math.isfinite(percentage) or not 0 <= percentage <= 100
                or not isinstance(group.get("label"), str) or not isinstance(group.get("role"), str)
                or not suffix or suffix in seen or len(color) != 4
                or any(not isinstance(c, int) or not 0 <= c <= 255 for c in color)):
            raise ValueError("Invalid packed membrane coordinates, colors or radii.")
        if len(normals) and not np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-5):
            raise ValueError("Invalid packed membrane surface normals.")
        total += len(positions)
        requested_total += requested
        seen.add(suffix)
    if not 1 <= total <= int(result.get("requested_count", 0)) <= limit:
        raise ValueError("Invalid membrane particle count.")
    if total != result.get("placed_count"):
        raise ValueError("Packed membrane count does not match its coordinates.")
    if requested_total != result.get("requested_count"):
        raise ValueError("Packed membrane class quotas do not match its requested count.")
    if result.get("algorithm_version") in (4, 5, 6, 7):
        from .membrane_recipe import validate_recipe_result
        if not result.get("particle_only"):
            raise ValueError("Recipe packing must have particle-only geometry.")
        validate_recipe_result(result)
    elif result.get("particle_only"):
        if result.get("algorithm_version") not in (2, 3) or not seen <= {"protein", "lipids"}:
            raise ValueError("Invalid particle-only membrane ingredients.")
        if "protein" in seen or result.get("protein") is not None:
            from .membrane_protein import validate_protein
            validate_protein(result.get("protein"))
            count = sum(len(g["positions"]) for g in groups if g["suffix"] == "protein")
            if count * len(result["protein"]["triangles"]) > MAX_PROTEIN_TRIANGLES:
                raise ValueError("Packed protein geometry exceeds the rendering safety limit.")
        for key in ("protein_percent", "achieved_protein_percent"):
            value = float(result.get(key, float("nan")))
            if not math.isfinite(value) or not 0 <= value <= 100 + 1e-5:
                raise ValueError("Invalid membrane protein coverage.")
        radius = float(result.get("lipid_radius", 0))
        if (not math.isfinite(radius) or radius <= 0
                or not 0 <= int(result.get("seed", -1)) <= 2147483647
                or not 1 <= int(result.get("particle_limit", 0)) <= MAX_FILL_PARTICLES):
            raise ValueError("Invalid saved membrane packing settings.")
    return groups


def clear_packing(model):
    children = [child for child in model.child_models()
                if getattr(child, "_cb_membrane_cellpack", False)]
    if children:
        model.session.models.close(children)
    result = model._cb_membrane_state.pop(PACKING_KEY, None)
    if isinstance(result, dict) and result.get("particle_only"):
        # This is also the recovery path for corrupt JSON; never fail to reveal
        # the guide merely because the saved mask itself is invalid.
        mask = None
        try:
            saved = np.asarray(result.get("guide_triangle_mask"), dtype=bool)
            if saved.shape == (len(model.triangles),):
                mask = saved
        except (TypeError, ValueError):
            pass
        model.triangle_mask = mask


def restore_packing(model, result):
    """One instanced drawing per ingredient; protein mesh is shared by every copy."""
    from chimerax.core.models import Model, Surface
    from chimerax.geometry import Places
    from chimerax.surface import sphere_geometry
    from .membrane_recipe import group_protein

    groups = validate_result(result)
    if result.get("mesh_digest") != mesh_digest(model):
        raise ValueError("The membrane geometry changed. Pack this membrane again.")
    result = copy.deepcopy(result)
    previous = model._cb_membrane_state.get(PACKING_KEY, {})
    mask = result.get("guide_triangle_mask", previous.get("guide_triangle_mask"))
    if mask is None and not previous.get("particle_only") and model.triangle_mask is not None:
        mask = model.triangle_mask.tolist()
    if mask is not None and (np.asarray(mask).shape != (len(model.triangles),)):
        raise ValueError("Invalid membrane guide triangle mask.")
    if result.get("particle_only"):
        result["guide_triangle_mask"] = mask
    root = Model("cellPACK-style particles", model.session)
    root._cb_membrane_cellpack = True
    root._cb_attach_source = False
    try:
        vertices, normals, triangles = sphere_geometry(80)
        for group in groups:
            if not group["positions"]:
                continue
            surface = Surface(group["label"], model.session)
            surface._cb_attach_source = False
            protein = group_protein(result, group)
            if protein is not None:
                from .membrane_protein import instance_matrices
                from .membrane_molecule import validate_template
                surface.set_geometry(*validate_template(protein))
                surface.positions = Places(place_array=instance_matrices(group["positions"], group["normals"],
                                                                         group.get("spins")))
            else:
                surface.set_geometry(vertices * group["radius"], normals, triangles)
                surface.positions = Places(shift_and_scale=np.column_stack(
                    (group["positions"], np.ones(len(group["positions"])))).astype(np.float32))
            surface.color = tuple(group["color"])
            surface.allow_clipping = model.allow_clipping
            surface.clip_cap = getattr(model, "clip_cap", False)
            root.add([surface])
        # Build successfully before replacing a previous preview.
        model.add([root])
        old = [child for child in model.child_models()
               if child is not root and getattr(child, "_cb_membrane_cellpack", False)]
        model.session.models.close(old)
        if result.get("particle_only"):
            # Hiding the Model itself would also hide its particle children.
            model.triangle_mask = np.zeros(len(model.triangles), dtype=bool)
        elif previous.get("particle_only"):
            model.triangle_mask = np.asarray(mask, dtype=bool) if mask is not None else None
        model._cb_membrane_state[PACKING_KEY] = copy.deepcopy(result)
    except Exception:
        root.delete()
        raise
    return root


def apply_result(tool, model, result):
    if model not in tool.session.models.list():
        raise ValueError("The target membrane was closed. Build or select another membrane.")
    before = tool._begin_history_action()
    restore_packing(model, result)
    tool._commit_history_action(before)


def export_packing(tool, model, result, folder):
    """Export exactly the preview, not a second random packing or other scene models."""
    from .cellpack_export import _CellPackExporter
    from .membrane_recipe import group_protein

    groups = validate_result(result)
    if model not in tool.session.models.list() or result["mesh_digest"] != mesh_digest(model):
        raise ValueError("Membrane changed or closed. Pack it again before exporting.")
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()):
        raise ValueError("Choose an empty package directory to avoid overwriting earlier exports.")
    exporter = _CellPackExporter(tool, str(folder))
    (folder / "meshes").mkdir()
    (folder / "ingredients").mkdir()
    world_vertices = model.scene_position.transform_points(np.asarray(model.vertices, dtype=float))
    exporter._write_collada_mesh(world_vertices, model.triangles, str(folder / "meshes/membrane.dae"),
                                "membrane", rgba=tuple(model.color))
    compartment = {"name": "membrane", "geom": "meshes/membrane.dae",
                   "rep_file": "meshes/membrane.dae", "surface": {"ingredients": {}}}
    if result.get("particle_only"):
        compartment.pop("rep_file")
    recipe = {"recipe": {"name": "CiliaBuilder membrane", "version": "1.0"},
              "compartments": {"membrane": compartment}, "ciliabuilder_engine": ENGINE}
    placements = {"surface": {"ingredients": {}}}
    apr = {"recipe": {"setupfile": "membrane.cpr.json", "name": "CiliaBuilder membrane", "version": "1.0"},
           "compartments": {"membrane": placements}, "ciliabuilder_engine": ENGINE}
    cif_groups = []
    for index, group in enumerate(groups):
        if not group["positions"]:
            continue
        # Only generated filenames are used, never arbitrary names read from JSON.
        name = f"ingredient_{index + 1}"
        mesh = folder / "meshes" / f"{name}.dae"
        protein = group_protein(result, group)
        if protein is not None:
            from .membrane_molecule import validate_template
            vertices, _, triangles = validate_template(protein)
        else:
            vertices, triangles = exporter._build_uv_sphere_mesh(group["radius"])
        exporter._write_collada_mesh(vertices, triangles, str(mesh), group["label"], rgba=group["color"])
        ingredient = exporter._build_membrane_particle_ingredient(name, str(mesh), group["radius"],
                          len(group["positions"]), {"role": group["role"], "target_percentage": group["percentage"]})
        ingredient["properties"]["ciliabuilder_engine"] = ENGINE
        if protein is not None:
            for key in ("pdb_id", "file_path", "resolved_residue", "representation"):
                if protein.get(key):
                    ingredient["properties"][key] = protein[key]
        with (folder / "ingredients" / f"{name}.json").open("w") as stream:
            json.dump(ingredient, stream, indent=2, allow_nan=False)
        compartment["surface"]["ingredients"][name] = {"name": name, "include": f"ingredients/{name}.json"}
        positions = model.scene_position.transform_points(np.asarray(group["positions"]))
        normals = model.scene_position.transform_vectors(np.asarray(group["normals"]))
        if protein is not None:
            from .membrane_protein import instance_matrices
            matrices = instance_matrices(group["positions"], group["normals"], group.get("spins"))
            rotations = np.tile(np.eye(4), (len(matrices), 1, 1))
            rotations[:, :3, :3] = model.scene_position.matrix[:, :3] @ matrices[:, :, :3]
            results = [[p.tolist(), r.tolist()] for p, r in zip(positions, rotations)]
        else:
            results = [[p.tolist(), exporter._rotation44_from_z_axis(n)] for p, n in zip(positions, normals)]
        placements["surface"]["ingredients"][name] = {"name": name, "compNum": 1,
                "encapsulatingRadius": group["radius"], "results": results}
        cif_groups.append(dict(group, placements=results, ingredient_name=group["label"],
                               compartment_name="membrane", class_suffix=group["suffix"],
                               class_role="particle_center_not_atomic_structure",
                               particle_radius=group["radius"], target_percentage=group["percentage"]))
    for name, payload in (("membrane.cpr.json", recipe), ("membrane.apr.json", apr),
                          ("packing.json", result)):
        with (folder / name).open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
    # UNK is ChimeraX's built-in unknown component: no remote CCD dependency.
    class PreviewCifExporter(_CellPackExporter):
        def _cif_component_id(self, _suffix):
            return "UNK"
    cif_path = folder / "membrane_particles.cif"
    PreviewCifExporter(tool, str(folder))._write_cellpack_membrane_mmcif(
        str(cif_path), cif_groups, [world_vertices.min(axis=0).tolist(), world_vertices.max(axis=0).tolist()])
    (folder / "README.txt").write_text(
        "CiliaBuilder membrane-only, built-in cellPACK-style packing.\n"
        "This was NOT run by the upstream cellPACK engine.\n"
        "Bead lipids are coarse proxies; molecular lipids use one residue's atomic van der Waals geometry.\n"
        "Protein surfaces come from PDB; molecular lipids can come from PDB or a local atomic file.\n"
        "Molecular meshes are embedded, so original files are not required to reopen this package.\n"
        "The CIF contains particle CENTERS, not replicated atoms; APR shows the full ingredient meshes.\n"
        "Protein alignment and embedding are geometric, not validated membrane orientations.\n"
        "Open membrane.apr.json with cbopenapr, or membrane_particles.cif with open.\n"
        "All package references are relative. Keep this entire folder together.\n"
        "packing.json stores model-local positions; APR/CIF use the scene placement at export.\n",
        encoding="utf-8")
    return {"folder": str(folder), "apr": str(folder / "membrane.apr.json"), "cif": str(cif_path)}
