"""One reusable PDB-derived mesh for membrane packing, never one atom model per site."""

import re

import numpy as np

from .orientation import rotation_align_vector_to_vector


def validate_pdb_id(value):
    value = str(value).strip().lower()
    if not re.fullmatch(r"[1-9][a-z0-9]{3}", value):
        raise ValueError("Enter a four-character PDB ID, for example 1AFO.")
    return value


def fetch_protein(session, pdb_id, axis="Z"):
    """Fetch the deposited structure; use its first model and protein atoms only."""
    pdb_id = validate_pdb_id(pdb_id)
    if axis not in ("X", "Y", "Z", "-X", "-Y", "-Z"):
        raise ValueError("Choose the PDB axis that should point out of the membrane.")
    from chimerax.core.fetch import fetch_file
    from chimerax.atomic import Residue
    from chimerax.surface import gaussian_surface

    path = fetch_file(session, f"https://files.rcsb.org/download/{pdb_id.upper()}.cif",
                      f"membrane protein {pdb_id.upper()}", f"{pdb_id}.cif", "PDB")
    models = []
    try:
        models, _ = session.open_command.open_data(path)
        structure = next((m for m in models if hasattr(m, "atoms")), None)
        if structure is None:
            raise ValueError("The PDB entry contains no atomic model.")
        atoms = structure.atoms
        atoms = atoms.filter(atoms.residues.polymer_types == Residue.PT_AMINO)
        if not 1 <= len(atoms) <= 50000:
            raise ValueError("Choose a protein structure with 1-50,000 protein atoms.")
        coords = np.asarray(atoms.coords, dtype=np.float32)
        if not np.isfinite(coords).all() or np.max(np.ptp(coords, axis=0)) > 600:
            raise ValueError("Protein coordinates are invalid or exceed the 600-Angstrom packing limit.")
        vertices, normals, triangles, _ = gaussian_surface(
            coords, atoms.element_numbers, resolution=6.0, level=None, grid_spacing=3.0)
        if len(vertices) == 0:
            raise ValueError("Could not build a surface for this PDB protein.")
        center = (vertices.min(axis=0) + vertices.max(axis=0)) * 0.5
        direction = np.eye(3)["XYZ".index(axis[-1])] * (-1 if axis.startswith("-") else 1)
        rotation = rotation_align_vector_to_vector(direction, (0, 0, 1))
        vertices = (vertices - center) @ rotation.T
        normals = normals @ rotation.T
        result = {"pdb_id": pdb_id.upper(), "axis": axis, "atom_count": len(atoms),
                  "representation": "6-Angstrom Gaussian protein surface; first deposited model",
                  "vertices": vertices.tolist(), "normals": normals.tolist(),
                  "triangles": triangles.tolist(),
                  "radius": float(np.linalg.norm(vertices, axis=1).max()),
                  "footprint_radius": float(np.linalg.norm(vertices[:, :2], axis=1).max())}
        validate_protein(result)
        return result
    finally:
        for model in models:
            model.delete()


def validate_protein(protein):
    if not isinstance(protein, dict):
        raise ValueError("Missing packed protein geometry.")
    validate_pdb_id(protein.get("pdb_id", ""))
    if protein.get("axis") not in ("X", "Y", "Z", "-X", "-Y", "-Z"):
        raise ValueError("Invalid packed protein outward axis.")
    v = np.asarray(protein.get("vertices"), dtype=np.float32)
    n = np.asarray(protein.get("normals"), dtype=np.float32)
    t = np.asarray(protein.get("triangles"), dtype=np.int32)
    radius = float(protein.get("radius", 0))
    footprint = float(protein.get("footprint_radius", 0))
    if (v.ndim != 2 or v.shape[1] != 3 or not 3 <= len(v) <= 50000
            or n.shape != v.shape or not np.isfinite(v).all() or not np.isfinite(n).all()
            or t.ndim != 2 or t.shape[1] != 3 or not 1 <= len(t) <= 100000
            or t.min() < 0 or t.max() >= len(v)
            or not np.isfinite(radius) or not 0 < footprint <= radius
            or np.linalg.norm(v, axis=1).max() > radius + 1e-3
            or np.linalg.norm(v[:, :2], axis=1).max() > footprint + 1e-3):
        raise ValueError("Invalid or oversized packed protein mesh.")
    return v, n, t


def instance_matrices(positions, normals, spins=None):
    matrices = np.empty((len(positions), 3, 4), dtype=np.float64)
    for index, (position, normal) in enumerate(zip(positions, normals)):
        matrices[index, :, :3] = rotation_align_vector_to_vector((0, 0, 1), normal)
        matrices[index, :, 3] = position
    if spins is not None:
        angles = np.asarray(spins, float)
        rotations = np.zeros((len(angles), 3, 3))
        rotations[:, 0, 0] = rotations[:, 1, 1] = np.cos(angles)
        rotations[:, 1, 0], rotations[:, 0, 1] = np.sin(angles), -np.sin(angles)
        rotations[:, 2, 2] = 1
        matrices[:, :, :3] = matrices[:, :, :3] @ rotations
    return matrices
