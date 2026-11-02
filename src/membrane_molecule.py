"""Reusable molecular lipid templates and bounded atom-sphere collision queries."""

import hashlib
from pathlib import Path
import re

import numpy as np
from scipy.spatial import cKDTree

from .membrane_protein import instance_matrices, validate_pdb_id, validate_protein
from .orientation import rotation_align_vector_to_vector

MAX_LIPID_ATOMS = 500
ATOMIC_FORMATS = {".pdb", ".ent", ".cif", ".mmcif", ".mol2", ".sdf"}


def ingredient_source(entry):
    return entry.get("source", "pdb" if entry.get("kind", "protein") == "protein" else "bead")


def molecular_lipid(entry):
    return entry.get("kind") == "lipid" and ingredient_source(entry) != "bead"


def lipid_key(entry):
    source = ingredient_source(entry)
    if source == "pdb":
        identity = validate_pdb_id(entry.get("pdb_id", ""))
    elif source == "file":
        path = str(entry.get("file_path", "")).strip()
        if not path:
            raise ValueError("Choose a local lipid structure file.")
        # Do not touch the filesystem here: embedded templates must restore offline.
        identity = hashlib.sha256(path.encode("utf-8")).hexdigest()
    else:
        raise ValueError("Choose a PDB ID or local file for a molecular lipid.")
    residue = str(entry.get("residue_name", "")).strip().upper()
    if residue and not re.fullmatch(r"[A-Z0-9_+-]{1,8}", residue):
        raise ValueError("Use a residue/component name such as DGA, or leave it blank.")
    axis = entry.get("axis")
    if axis not in ("X", "Y", "Z", "-X", "-Y", "-Z"):
        raise ValueError("Choose the lipid axis pointing toward the leaflet exterior.")
    return f"lipid:{source}:{identity}:{residue}:{axis}"


def atom_mesh(coords, radii):
    from chimerax.surface import sphere_geometry
    v, n, t = sphere_geometry(80)
    vertices = (coords[:, None, :] + radii[:, None, None]*v).reshape((-1, 3))
    normals = np.tile(n, (len(coords), 1))
    triangles = (t[None, :, :] + len(v)*np.arange(len(coords))[:, None, None]).reshape((-1, 3))
    return vertices.astype(np.float32), normals, triangles


def load_lipid(session, entry):
    """Use one non-water, non-polymer residue, never an entire protein complex."""
    lipid_key(entry)
    source = ingredient_source(entry)
    if source == "pdb":
        from chimerax.core.fetch import fetch_file
        pdb_id = validate_pdb_id(entry["pdb_id"])
        path = fetch_file(session, f"https://files.rcsb.org/download/{pdb_id.upper()}.cif",
                          f"membrane lipid {pdb_id.upper()}", f"{pdb_id}.cif", "PDB")
    else:
        path = str(Path(entry["file_path"]).expanduser().resolve())
        suffixes = Path(path).suffixes
        suffix = suffixes[-2] if len(suffixes) > 1 and suffixes[-1].lower() == ".gz" else Path(path).suffix
        if suffix.lower() not in ATOMIC_FORMATS:
            raise ValueError("Choose a lipid PDB, mmCIF, MOL2 or SDF structure file.")
        if not Path(path).is_file():
            raise ValueError(f"Lipid structure file not found: {path}")
    models = []
    try:
        from chimerax.atomic import Residue
        models, _ = session.open_command.open_data(path)
        structure = next((m for m in models if hasattr(m, "atoms")), None)
        if structure is None:
            raise ValueError("The lipid source contains no atomic structure.")
        residue_name = str(entry.get("residue_name", "")).strip().upper()
        residues = [r for r in structure.residues if r.polymer_type == Residue.PT_NONE
                    and r.name.upper() not in ("HOH", "WAT", "DOD", "H2O")
                    and np.count_nonzero(r.atoms.element_numbers > 1) >= 3]
        if residue_name:
            residues = [r for r in residues if r.name.upper() == residue_name]
        names = sorted({r.name.upper() for r in residues})
        if not residues:
            raise ValueError("No matching lipid/ligand residue found. Use a lipid-only file or specify its residue name.")
        if len(names) > 1:
            raise ValueError("Several components found: " + ", ".join(names[:20]) + ". Enter the lipid residue name.")
        atoms = residues[0].atoms
        if not 1 <= len(atoms) <= MAX_LIPID_ATOMS:
            raise ValueError(f"Use one lipid residue with at most {MAX_LIPID_ATOMS} atoms.")
        coords, radii = np.asarray(atoms.coords, float), np.asarray(atoms.default_radii, float)
        if not np.isfinite(coords).all() or np.max(np.ptp(coords, axis=0)) > 200:
            raise ValueError("Lipid coordinates are invalid or exceed 200 Angstroms.")
        axis = entry["axis"]
        direction = np.eye(3)["XYZ".index(axis[-1])] * (-1 if axis.startswith("-") else 1)
        coords = coords @ rotation_align_vector_to_vector(direction, (0, 0, 1)).T
        lo, hi = (coords-radii[:, None]).min(0), (coords+radii[:, None]).max(0)
        anchor = (lo+hi)/2
        anchor[2] = hi[2]  # Outermost atom envelope on the leaflet; tails extend into the wall.
        coords -= anchor
        vertices, normals, triangles = atom_mesh(coords, radii)
        result = dict(template_kind="lipid-molecule", kind="lipid", source=source,
                      pdb_id=entry.get("pdb_id", "") if source == "pdb" else "",
                      file_path=entry.get("file_path", "") if source == "file" else "",
                      residue_name=residue_name, resolved_residue=residues[0].name, axis=axis,
                      representation="atomic van der Waals spheres; one lipid residue",
                      atom_count=len(atoms), atom_coords=coords.tolist(), atom_radii=radii.tolist(),
                      atom_elements=atoms.element_numbers.tolist(),
                      vertices=vertices.tolist(), normals=normals.tolist(), triangles=triangles.tolist(),
                      radius=float((np.linalg.norm(coords, axis=1)+radii).max()),
                      footprint_radius=float((np.linalg.norm(coords[:, :2], axis=1)+radii).max()))
        validate_template(result)
        return result
    finally:
        for model in models:
            model.delete()


def validate_template(template):
    if not isinstance(template, dict) or template.get("template_kind") != "lipid-molecule":
        return validate_protein(template)
    lipid_key(template)
    coords, radii = np.asarray(template.get("atom_coords"), float), np.asarray(template.get("atom_radii"), float)
    elements = np.asarray(template.get("atom_elements"), int)
    if (coords.ndim != 2 or coords.shape[1] != 3 or not 1 <= len(coords) <= MAX_LIPID_ATOMS
            or radii.shape != (len(coords),) or elements.shape != radii.shape
            or not np.isfinite(coords).all() or not np.isfinite(radii).all()
            or np.any(radii <= 0) or np.any(radii > 5) or np.any(elements < 1) or np.any(elements > 118)
            or template.get("atom_count") != len(coords)):
        raise ValueError("Invalid molecular lipid atoms/radii.")
    v, n, t = validate_protein(dict(template, pdb_id="1AFO"))
    expected_v, expected_n, expected_t = atom_mesh(coords, radii)
    if (v.shape != expected_v.shape or t.shape != expected_t.shape
            or not np.allclose(v, expected_v, atol=1e-5) or not np.array_equal(t, expected_t)
            or not np.allclose(n, expected_n, atol=1e-5)
            or abs(template["radius"]-(np.linalg.norm(coords, axis=1)+radii).max()) > 1e-5
            or abs(template["footprint_radius"]-(np.linalg.norm(coords[:, :2], axis=1)+radii).max()) > 1e-5):
        raise ValueError("Lipid collision geometry does not match its displayed atomic mesh.")
    return v, n, t


class AtomSpheres:
    """Exact sphere-union exclusion; separate radius trees avoid all-pairs arrays."""

    def __init__(self, coords, radii):
        coords, radii = np.asarray(coords), np.asarray(radii)
        self.trees = [(float(r), cKDTree(coords[radii == r])) for r in np.unique(radii)]

    def clear(self, points, radii):
        radii = np.broadcast_to(radii, (len(points),))
        keep = np.ones(len(points), bool)
        for radius, tree in self.trees:
            keep &= tree.query(points)[0] >= radii+radius+.001*np.minimum(radii, radius)
        return keep


def atom_positions(template, positions, normals, spins):
    matrices = instance_matrices(positions, normals, spins)
    return (np.asarray(template["atom_coords"]) @ matrices[:, :, :3].transpose(0, 2, 1)
            + matrices[:, None, :, 3])


def molecular_conflicts(template, points, normals, spins):
    """Refine only broad-phase candidate pairs against the same atom spheres we show."""
    from .membrane_lattice import conflict_graph
    offsets, neighbors = conflict_graph(points, 2*template["radius"]*1.001)
    owners = np.repeat(np.arange(len(points)), np.diff(offsets))
    matrices = instance_matrices(points, normals, spins)
    spheres = AtomSpheres(template["atom_coords"], template["atom_radii"])
    conflicts = np.zeros(len(neighbors), bool)
    coords, radii = np.asarray(template["atom_coords"]), np.asarray(template["atom_radii"])
    block = max(1, 8192//len(coords))
    for start in range(0, len(neighbors), block):
        a, b = owners[start:start+block], neighbors[start:start+block]
        world = coords @ matrices[a, :, :3].transpose(0, 2, 1) + matrices[a, None, :, 3]
        local = (world-matrices[b, None, :, 3]) @ matrices[b, :, :3]
        clear = spheres.clear(local.reshape((-1, 3)), np.tile(radii, len(a)))
        conflicts[start:start+block] = ~clear.reshape((-1, len(coords))).all(1)
    owners, neighbors = owners[conflicts], neighbors[conflicts]
    offsets = np.r_[0, np.cumsum(np.bincount(owners, minlength=len(points)))].astype(int)
    return offsets, neighbors
