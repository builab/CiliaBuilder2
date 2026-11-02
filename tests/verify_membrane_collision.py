"""ChimeraX runscript tests/verify_membrane_collision.py; mesh contact regressions."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from scipy.spatial import cKDTree
from chimerax.surface import sphere_geometry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.membrane_collision import ProteinMesh, outside_protein_meshes, surface_distance, _numpy_surface_distance
from src.membrane_lattice import outside_protein_boxes
from src.membrane_protein import fetch_protein, instance_matrices


def winding_inside(points, vertices, triangles):
    """Independent solid-angle reference, not the production ray-parity test."""
    faces = np.asarray(vertices, float)[triangles]
    result = []
    for start in range(0, len(points), 32):
        delta = faces[None, :]-points[start:start+32, None, None, :]
        a, b, c = delta[:, :, 0], delta[:, :, 1], delta[:, :, 2]
        la, lb, lc = (np.linalg.norm(v, axis=2) for v in (a, b, c))
        numerator = np.sum(a*np.cross(b, c), axis=2)
        denominator = la*lb*lc + np.sum(a*b, 2)*lc + np.sum(b*c, 2)*la + np.sum(c*a, 2)*lb
        angle = np.sum(2*np.arctan2(numerator, denominator), axis=1)
        result.extend(abs(angle) > 2*np.pi)
    return np.array(result)


def torus():
    nu, nv = 64, 32
    u, v = np.meshgrid(np.arange(nu)*2*np.pi/nu, np.arange(nv)*2*np.pi/nv, indexing="ij")
    vertices = np.stack(((20+6*np.cos(v))*np.cos(u), (20+6*np.cos(v))*np.sin(u), 6*np.sin(v)), axis=2)
    triangles = []
    for i in range(nu):
        for j in range(nv):
            a, b, c, d = i*nv+j, ((i+1)%nu)*nv+j, ((i+1)%nu)*nv+(j+1)%nv, i*nv+(j+1)%nv
            triangles.extend(((a, b, c), (a, c, d)))
    return vertices.reshape((-1, 3)), np.array(triangles, np.int32)


class CollisionTests(unittest.TestCase):
    def test_empty_box_corners_are_free_but_protein_interior_is_not(self):
        v, _, t = sphere_geometry(320)
        mesh = ProteinMesh(v*[10, 10, 20], t)
        points = np.array([[9, 9, 0], [0, 0, 0], [10.5, 0, 0], [12.1, 0, 0]], float)
        np.testing.assert_array_equal(mesh.clear(points, 2), [True, False, False, True])
        tree, rotations = cKDTree([[0., 0., 0.]]), np.eye(3)[None]
        self.assertFalse(outside_protein_boxes(points, tree, rotations, mesh.bounds, 20, 2, 0)[0])
        np.testing.assert_array_equal(outside_protein_meshes(points, tree, rotations, mesh, 20, 2, 0),
                                      [True, False, False, True])

    def test_concave_hole_and_inside_solid(self):
        vertices, triangles = torus()
        mesh = ProteinMesh(vertices, triangles)
        points = np.array([[0, 0, 0], [8, 0, 0], [20, 0, 0], [25, 0, 0], [29, 0, 0]], float)
        np.testing.assert_array_equal(mesh.clear(points, 2), [True, True, False, False, True])
        points = np.random.default_rng(273).uniform([-28, -28, -8], [28, 28, 8], (2000, 3))
        np.testing.assert_array_equal(mesh.inside(points), winding_inside(points, vertices, triangles))
        np.testing.assert_allclose(mesh.distances(points)[:, 0],
                                   surface_distance(points.astype(np.float32), vertices.astype(np.float32), triangles)[:, 0],
                                   atol=1e-4)

    def test_closed_cavity_and_reversed_winding(self):
        v, _, t = sphere_geometry(320)
        vertices = np.concatenate((v*20, v*8))
        triangles = np.concatenate((t, t[:, ::-1]+len(v)))
        points = np.array([[0, 0, 0], [12, 0, 0], [23, 0, 0]], float)
        for tri in (triangles, triangles[:, ::-1]):
            np.testing.assert_array_equal(ProteinMesh(vertices, tri).clear(points, 2), [True, False, True])

    def test_all_instances_and_spins_not_only_nearest_center(self):
        v, _, t = sphere_geometry(320)
        mesh = ProteinMesh(v*[1, 10, 10], t)
        centers = np.array([[0., 0., 0.], [12., 0., 0.]])
        matrices = instance_matrices(centers, [[0, 0, 1]]*2, [0, np.pi/2])
        points = np.array([[4., 0., 0.], [-4., 0., 0.]])
        self.assertTrue(mesh.clear(points[:1], 2)[0])
        clear = outside_protein_meshes(points, cKDTree(centers), matrices[:, :, :3], mesh, 10., 2., .002)
        np.testing.assert_array_equal(clear, [False, True])

    def test_exact_edge_ray_retries_and_face_clearance(self):
        v, _, t = sphere_geometry(320)
        mesh = ProteinMesh(v*20, t)
        direction = np.array([1., .37139067, .69473891])
        points = mesh.vertices.astype(float)-direction*.5
        points = points[np.all((points >= mesh.bounds[0]) & (points <= mesh.bounds[1]), axis=1)]
        self.assertTrue(mesh._ray_inside(points, direction)[1].any(), "Exercise actual ambiguous vertex hits")
        np.testing.assert_array_equal(mesh.inside(points), winding_inside(points, mesh.vertices, t))
        faces = mesh.vertices[t[:10]].astype(float)
        normals = np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0])
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        centers = faces.mean(1)
        self.assertTrue(mesh.clear(centers+normals*2.02, 2, .002).all())
        self.assertFalse(mesh.clear(centers+normals*1.98, 2).any())
        self.assertFalse(mesh.clear(centers-normals*4, 2).any())

    def test_open_mesh_fails_safely(self):
        v, _, t = sphere_geometry(80)
        with self.assertRaisesRegex(ValueError, "not closed"):
            ProteinMesh(v, t[:-1])

    def test_numpy_fallback_matches_native_and_updates_upper_bounds(self):
        v, _, t = sphere_geometry(320)
        v = (v*[10, 15, 20]).astype(np.float32)
        points = np.random.default_rng(932).uniform(-25, 25, (300, 3)).astype(np.float32)
        expected = surface_distance(points, v, t)
        computed = _numpy_surface_distance(points, v, t)
        np.testing.assert_allclose(computed[:, 0], expected[:, 0], atol=1e-4)
        mesh = ProteinMesh(v, t)
        with patch("src.membrane_collision._native_surface_distance", None):
            np.testing.assert_allclose(mesh.distances(points)[:, 0], expected[:, 0], atol=1e-4)
            np.testing.assert_array_equal(mesh.clear(points, 2),
                                          ~mesh.inside(points) & (expected[:, 0] >= 2+mesh.tolerance))
        initial = computed.copy()
        initial[:, 0] *= .5
        actual = _numpy_surface_distance(points, v, t, initial.copy())
        np.testing.assert_array_equal(actual, initial)

    def test_real_protein_distances_and_independent_inside_reference(self):
        before = set(session.models.list())
        for pdb in ("1AFO", "4HHB"):
            p = fetch_protein(session, pdb)
            v, t = np.array(p["vertices"], np.float32), np.array(p["triangles"], np.int32)
            mesh = ProteinMesh(v, t)
            points = np.random.default_rng(81).uniform(v.min(0)-5, v.max(0)+5, (1000, 3))
            reference = surface_distance(points.astype(np.float32), v, t)[:, 0]
            np.testing.assert_allclose(mesh.distances(points)[:, 0], reference, atol=1e-4)
            inside = winding_inside(points, v, t)
            np.testing.assert_array_equal(mesh.inside(points), inside)
            expected = ~inside & (reference >= 3+.003+mesh.tolerance)
            np.testing.assert_array_equal(mesh.clear(points, 3, .003), expected)
        self.assertEqual(before, set(session.models.list()))


result = unittest.TextTestRunner(stream=sys.__stderr__, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(CollisionTests))
if not result.wasSuccessful():
    raise RuntimeError("Protein mesh collision regression checks failed")
