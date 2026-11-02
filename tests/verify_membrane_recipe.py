"""ChimeraX runscript tests/verify_membrane_recipe.py; no new dependencies."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from scipy.spatial import cKDTree
from chimerax.core.commands import run
from chimerax.geometry import rotation, translation
from chimerax.surface import sphere_geometry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cmd import buildmembrane_surface
from src.tool import CiliaBuilder2Tool
from src.membrane_recipe import GrowingSites, RecipePacker, default_recipe, validate_recipe
from src.membrane_cellpack import PACKING_KEY, apply_result, restore_packing, validate_result, export_packing
from src.membrane_protein import instance_matrices


class Control:
    def value(self):
        return .6

    def setValue(self, value):
        pass


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        session.selection.clear()
        self.model = buildmembrane_surface(session, "recipe membrane", (12, 34, 56), (1, 2, 3),
                         300, 200, 20, distortion_level=.6, distortion_seed=1, tip_dome_enabled=True)
        self.tool = object.__new__(CiliaBuilder2Tool)
        self.tool._session = weakref.ref(session)
        self.tool._attached_results = {}
        self.tool._last_attached_result = None
        self.tool._history_replaying = False
        self.tool._reset_history()
        self.tool.membrane_distortion = Control()
        self.tool._last_membrane_model = self.model
        self.tool._refresh_model_selectors = lambda: None
        self.tool._keep_tool_visible = lambda: None
        self.tool._cancel_active_tool_interactions_for_history = lambda: None

    def tearDown(self):
        run(session, "wait 1", log=False)
        created = set(session.models.list())-self.before
        session.models.close([m for m in created if m.parent not in created])

    def protein(self, pdb="1AFO"):
        v, n, t = sphere_geometry(80)
        v = v * [8, 12, 20]
        return dict(pdb_id=pdb, axis="Z", vertices=v.tolist(), normals=n.tolist(), triangles=t.tolist(),
                    radius=20., footprint_radius=12.)

    def mixture(self):
        recipe = default_recipe(7)
        recipe[1].update(enabled=True, pdb_id="1AFO", amount=10.)
        recipe.append(dict(recipe[1], key="second", label="Second protein", pdb_id="4HHB", amount=10.))
        recipe.append(dict(recipe[0], key="small", label="Small lipid", radius=5., amount=30.))
        recipe.append(dict(recipe[0], key="other", label="Other bead", kind="other", radius=6., amount=20.))
        recipe.append(dict(recipe[0], key="disabled", label="Disabled", enabled=False))
        return recipe, {"1afo:Z": self.protein(), "4hhb:Z": self.protein("4HHB")}

    def pack(self, recipe=None, templates=None, seed=17, limit=250, model=None, batch=256):
        packer = RecipePacker(model or self.model, recipe or default_recipe(7), templates, limit, seed)
        while not packer.step(batch):
            pass
        result = packer.result()
        validate_result(result)
        return result

    def test_seed_reproducibility_and_random_spins(self):
        result = self.pack()
        self.assertEqual(result, self.pack(batch=1))
        self.assertNotEqual(result["groups"][0]["positions"], self.pack(seed=19)["groups"][0]["positions"])
        self.assertGreater(np.std(result["groups"][0]["spins"]), 1.)
        points = np.array(result["groups"][0]["positions"])
        nearest = cKDTree(points).query(points, k=2)[0][:, 1]
        self.assertGreaterEqual(nearest.min(), 14.)

    def test_every_point_and_normal_on_real_distorted_faces(self):
        result = self.pack()
        faces = self.model.vertices[self.model.triangles[self.model._cb_membrane_outer_faces |
                                                       self.model._cb_membrane_inner_faces]].astype(float)
        u, v = faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]
        normals = np.cross(u, v)
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        uu, uv, vv = np.sum(u*u, 1), np.sum(u*v, 1), np.sum(v*v, 1)
        for point, normal in zip(result["groups"][0]["positions"], result["groups"][0]["normals"]):
            w = point-faces[:, 0]
            wu, wv = np.sum(w*u, 1), np.sum(w*v, 1)
            a, b = (wu*vv-wv*uv)/(uu*vv-uv*uv), (wv*uu-wu*uv)/(uu*vv-uv*uv)
            self.assertTrue(((abs(np.sum(w*normals, 1)) < 1e-5) & (a >= -1e-6) & (b >= -1e-6)
                             & (a+b <= 1+1e-6) & (np.linalg.norm(normals-normal, axis=1) < 1e-5)).any())

    def test_dense_random_curved_surface_and_no_global_rows(self):
        model = buildmembrane_surface(session, "density", (0, 0, 0), (0, 0, 1), 600, 400, 40,
                                     distortion_level=.6, distortion_seed=1, tip_dome_enabled=True)
        result = self.pack(default_recipe(10), limit=50000, model=model)
        fraction = result["placed_count"]*np.pi*100/(result["outer_area"]+result["inner_area"])
        self.assertGreater(fraction, .73)
        points = np.array(result["groups"][0]["positions"])
        self.assertGreaterEqual(cKDTree(points).query(points, k=2)[0][:, 1].min(), 20.)
        # The old rows shared only a few axial levels. Continuous random starts
        # and locally grown domains must not recreate those global bands.
        z = points[points[:, 2] < 550, 2]
        self.assertGreater(len(np.unique(np.round(z, 3)))/len(z), .9)

    def test_small_radius_automatic_budget_and_no_bead_sized_holes(self):
        model = buildmembrane_surface(session, "radius 10 density", (0, 0, 0), (0, 0, 1),
                                     3000, 2700, 40, distortion_level=.6, distortion_seed=1,
                                     tip_dome_enabled=True)
        packer = RecipePacker(model, default_recipe(10))
        self.assertGreater(packer.count, 200000)
        self.assertFalse(packer.limit_reached)
        while not packer.step():
            pass
        result = packer.result()
        validate_result(result)
        area = result["outer_area"]+result["inner_area"]
        self.assertGreater(result["placed_count"]*np.pi*100/area, .73)
        points = np.array(result["groups"][0]["positions"])
        tree = cKDTree(points)
        self.assertGreaterEqual(tree.query(points, k=2)[0][:, 1].min(), 20.)
        for leaflet in packer.leaflets.values():
            probes, _ = leaflet.sample(np.random.default_rng(567), 100000)
            self.assertLess(np.mean(tree.query(probes)[0] >= 20.01), .001)
        # Save/reload a real >50,000-particle result, not merely a raised limit.
        loaded = json.loads(json.dumps(result))
        root = restore_packing(model, loaded)
        self.assertEqual(len(root.child_models()), 1)
        self.assertEqual(len(root.child_models()[0].positions), result["placed_count"])
        self.assertEqual(model._cb_membrane_state[PACKING_KEY]["groups"], result["groups"])

    def test_area_budget_scaling_manual_preview_and_safety_ceiling(self):
        a = RecipePacker(self.model, default_recipe(10))
        b = RecipePacker(self.model, default_recipe(5))
        self.assertAlmostEqual(b.count/a.count, 4., delta=.01)
        a.cancel()
        b.cancel()
        before = copy.deepcopy(self.model._cb_membrane_state)
        with self.assertRaisesRegex(ValueError, "Dense fill needs.*safety ceiling"):
            RecipePacker(self.model, default_recipe(.1))
        self.assertEqual(self.model._cb_membrane_state, before)
        result = self.pack(limit=100)
        self.assertFalse(result["automatic_particle_budget"])
        self.assertTrue(result["particle_limit_reached"])
        self.assertGreater(result["area_target_count"], result["requested_count"])
        for version in (4, 5):
            old = dict(result, algorithm_version=version)
            old.pop("protein_lipid_exclusion", None)
            validate_result(old)
            restore_packing(self.model, old)
            self.assertEqual(self.model._cb_membrane_state[PACKING_KEY]["groups"], old["groups"])
        bad = dict(result, automatic_particle_budget=True)
        with self.assertRaisesRegex(ValueError, "density budget"):
            validate_result(bad)
        with self.assertRaisesRegex(ValueError, "collision method"):
            validate_result(dict(result, protein_lipid_exclusion="bounding-box"))

    def test_incremental_neighbor_index_matches_full_tree(self):
        rng = np.random.default_rng(88)
        points = rng.normal(size=(6000, 3))
        sites = GrowingSites(len(points))
        probes = rng.normal(size=(80, 3))
        for end in (3, 12, 200, 520, 1000, 1300, 1800, 2200, 6000):
            sites.add(points[sites.count:end], np.zeros_like(points[sites.count:end]))
            for k in (1, min(9, end)):
                actual, indices = sites.query(probes, k=k)
                expected, wanted = cKDTree(points[:end]).query(probes, k=k)
                np.testing.assert_allclose(actual, expected)
                np.testing.assert_array_equal(indices, wanted)

    def test_multiple_ingredients_collision_and_offline_restore(self):
        recipe, templates = self.mixture()
        with patch("src.membrane_recipe.instance_matrices", wraps=instance_matrices) as matrices:
            result = self.pack(recipe, templates, limit=400)
        self.assertEqual(matrices.call_count, 2, "Compute fixed protein collision bounds only once per group")
        self.assertEqual(len(result["templates"]), 2)
        self.assertNotIn("disabled", [g["suffix"] for g in result["groups"]])
        root = restore_packing(self.model, result)
        self.assertEqual(len(root.child_models()), len([g for g in result["groups"] if g["positions"]]))
        self.assertFalse(self.model.triangle_mask.any())
        protein_groups = [g for g in result["groups"] if g["template_key"]]
        beads = [g for g in result["groups"] if not g["template_key"]]
        for a in beads:
            for b in beads:
                d = np.linalg.norm(np.asarray(a["positions"])[:, None]-np.asarray(b["positions"])[None, :], axis=2)
                if a is b:
                    np.fill_diagonal(d, np.inf)
                self.assertTrue((d >= a["radius"]+b["radius"]-1e-6).all())
        for protein in protein_groups:
            from src.membrane_collision import ProteinMesh
            template = templates[protein["template_key"]]
            mesh = ProteinMesh(template["vertices"], template["triangles"])
            for matrix in instance_matrices(protein["positions"], protein["normals"], protein["spins"]):
                for bead in beads:
                    local = (np.array(bead["positions"])-matrix[:, 3]) @ matrix[:, :3]
                    self.assertTrue(mesh.clear(local, bead["radius"], .001*bead["radius"]).all())
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Network during restore")):
            restore_packing(self.model, json.loads(json.dumps(result)))
        self.assertEqual(self.model._cb_membrane_state[PACKING_KEY]["recipe"], recipe)

    def test_dense_mixed_sizes_fill_each_others_gaps_without_bands(self):
        recipe = default_recipe(7)[:1]
        recipe.append(dict(recipe[0], key="small", label="Small lipids", radius=4.2, amount=25.))
        result = self.pack(recipe, limit=50000)
        area = result["outer_area"]+result["inner_area"]
        fraction = sum(len(g["positions"])*np.pi*g["radius"]**2 for g in result["groups"])/area
        self.assertGreater(fraction, .70)
        from src.orientation import rotation_align_vector_to_vector
        rotation = rotation_align_vector_to_vector((0, 0, 1), self.model._cb_membrane_state["axis"])
        for group in result["groups"]:
            points = (np.array(group["positions"])-self.model._cb_membrane_state["center"]) @ rotation
            angles = np.arctan2(points[:, 1], points[:, 0])
            counts, _ = np.histogram(angles, bins=4, range=(-np.pi, np.pi))
            self.assertGreater(counts.min()/counts.sum(), .10)

    def test_real_protein_halos_fill_without_mesh_intersections(self):
        from src.membrane_collision import ProteinMesh, surface_distance
        from src.membrane_lattice import outside_protein_boxes
        from src.membrane_protein import fetch_protein
        model = buildmembrane_surface(session, "protein halo", (0, 0, 0), (0, 0, 1), 600, 600, 40,
                                     distortion_level=.6, distortion_seed=1, tip_dome_enabled=True)
        template = fetch_protein(session, "4HHB")
        recipe = default_recipe(10)
        recipe[1].update(enabled=True, pdb_id="4HHB", amount=20)
        packer = RecipePacker(model, recipe, {"4hhb:Z": template}, seed=1)
        while not packer.step():
            pass
        result = packer.result()
        beads = np.array(result["groups"][0]["positions"])
        protein = result["groups"][1]
        matrices = instance_matrices(protein["positions"], protein["normals"], protein["spins"])
        mesh = ProteinMesh(template["vertices"], template["triangles"])
        old_allowed = outside_protein_boxes(beads, cKDTree(protein["positions"]), matrices[:, :, :3],
                                            mesh.bounds, template["radius"], 10, .01)
        self.assertGreater(np.count_nonzero(~old_allowed), 100, "Fill space formerly rejected by protein boxes")
        self.assertGreaterEqual(cKDTree(beads).query(beads, k=2)[0][:, 1].min(), 20.)
        for matrix in matrices:
            local = (beads-matrix[:, 3]) @ matrix[:, :3]
            nearby = local[np.linalg.norm(local, axis=1) <= template["radius"]+10.01]
            reference = surface_distance(nearby.astype(np.float32), mesh.vertices, mesh.triangles)
            self.assertTrue((reference[:, 0] >= 10.01-1e-4).all())
            self.assertFalse(mesh.inside(nearby).any())
        for leaflet in packer.leaflets.values():
            probes, _ = leaflet.sample(np.random.default_rng(782), 20000)
            self.assertLess(packer._clear(probes, 10, packer.groups[0]).mean(), .001)

    def test_recipe_json_undo_redo_and_offline_membrane_reload(self):
        recipe, templates = self.mixture()
        result = self.pack(recipe, templates)
        apply_result(self.tool, self.model, result)
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        self.tool._undo_last_action()
        self.assertIsNone(self.model.triangle_mask)
        self.tool._redo_last_action()
        self.assertFalse(self.model.triangle_mask.any())
        session.models.close([self.model])
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Network during JSON restore")):
            self.tool._restore_generated_membranes(records)
        restored = self.tool._last_membrane_model
        self.assertEqual(restored._cb_membrane_state[PACKING_KEY]["groups"], result["groups"])

    def test_export_preserves_multiple_templates_and_random_rotations(self):
        from src.local_apr import open_local_apr_package
        recipe, templates = self.mixture()
        result = self.pack(recipe, templates)
        self.model.position = translation((100, 200, 300))*rotation((1, 2, 3), 37)
        with tempfile.TemporaryDirectory() as directory:
            export_packing(self.tool, self.model, result, directory)
            apr = json.loads((Path(directory)/"membrane.apr.json").read_text())
            ingredients = apr["compartments"]["membrane"]["surface"]["ingredients"]
            for index, group in enumerate(result["groups"]):
                if not group["positions"] or not group["template_key"]:
                    continue
                expected = instance_matrices(group["positions"], group["normals"], group["spins"])
                exported = ingredients[f"ingredient_{index+1}"]["results"]
                np.testing.assert_allclose(np.array([r for p, r in exported])[:, :3, :3],
                                            self.model.scene_position.matrix[:, :3] @ expected[:, :, :3])
            with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Network during CIF open")):
                root, info = open_local_apr_package(session, str(Path(directory)/"membrane.apr.json"))
                if root not in session.models.list():
                    session.models.add([root])
                models, _ = session.open_command.open_data(str(Path(directory)/"membrane_particles.cif"))
            try:
                self.assertEqual(models[0].num_atoms, result["placed_count"])
            finally:
                for model in models:
                    model.delete()

    def test_validation_and_limits_and_cancel(self):
        recipe, templates = self.mixture()
        bad = copy.deepcopy(recipe)
        bad[1]["amount"] = bad[2]["amount"] = 80
        with self.assertRaises(ValueError):
            validate_recipe(bad)
        for e in bad:
            e["enabled"] = False
        with self.assertRaises(ValueError):
            validate_recipe(bad)
        result = self.pack(recipe, templates, limit=60)
        self.assertLessEqual(result["placed_count"], 60)
        self.assertTrue(result["particle_limit_reached"])
        bad = copy.deepcopy(result)
        bad["groups"][0]["spins"] = [float("nan")]*len(bad["groups"][0]["positions"])
        with self.assertRaises(ValueError):
            validate_result(bad)
        bad = copy.deepcopy(result)
        bad["templates"]["1afo:Z"]["pdb_id"] = "4HHB"
        with self.assertRaises(ValueError):
            validate_result(bad)
        before = copy.deepcopy(self.model._cb_membrane_state)
        packer = RecipePacker(self.model, recipe, templates)
        packer.step()
        packer.cancel()
        self.assertIsNone(packer._work.gi_frame)
        with self.assertRaises(ValueError):
            packer.result()
        self.assertEqual(self.model._cb_membrane_state, before)
        beads = [e for e in recipe if e["kind"] != "protein"]
        packer = RecipePacker(self.model, beads)
        packer.step()
        workers = list(packer._work.gi_frame.f_locals["workers"])
        packer.cancel()
        self.assertTrue(all(w[0].gi_frame is None for w in workers if w is not None))
        self.assertFalse(packer._bead_sites)

    def test_single_particle_limit_and_inner_only_recipe(self):
        result = self.pack(limit=1)
        self.assertEqual(result["placed_count"], 1)
        recipe = default_recipe(7)[:1]
        recipe[0]["region"] = "inner"
        result = self.pack(recipe, limit=3)
        self.assertEqual(result["placed_count"], 3)

    def test_two_real_pdb_templates_fetched_once_and_no_source_models(self):
        from src.membrane_protein import fetch_protein
        before = set(session.models.list())
        templates = {"1afo:Z": fetch_protein(session, "1AFO"), "4hhb:Z": fetch_protein(session, "4HHB")}
        self.assertEqual(before, set(session.models.list()))
        recipe, _ = self.mixture()
        result = self.pack(recipe, templates, limit=300)
        proteins = [g for g in result["groups"] if g["role"] == "protein"]
        self.assertTrue(all(g["positions"] for g in proteins),
                        [(g["label"], g["requested_count"], len(g["positions"])) for g in proteins])
        self.assertEqual(set(result["templates"]), {"1afo:Z", "4hhb:Z"})

    @unittest.skipUnless(session.ui.is_gui, "GUI required")
    def test_ingredient_table_add_remove_enable_and_multiple_pdb_cache(self):
        from src.membrane_cellpack_ui import MembraneCellpackDialog
        tool = CiliaBuilder2Tool(session, "CiliaBuilder2")
        dialog = MembraneCellpackDialog(tool, self.model)
        try:
            recipe, templates = self.mixture()
            while dialog.rows:
                dialog.remove_ingredient(dialog.rows[-1])
            for entry in recipe:
                dialog.add_ingredient(entry["kind"], entry)
            self.assertEqual(dialog.recipe(), recipe)
            self.assertFalse(dialog.run_button.autoDefault())
            dialog.templates = templates
            self.assertTrue(dialog.automatic_count.isChecked())
            self.assertFalse(dialog.count.isEnabled())
            dialog.automatic_count.setChecked(False)
            self.assertTrue(dialog.count.isEnabled())
            dialog.count.setValue(150)
            with patch("src.membrane_cellpack_ui.fetch_protein", side_effect=AssertionError("Unexpected refetch")):
                dialog.start()
                self.assertIsNotNone(dialog.packer, dialog.status.text())
                while dialog.packer:
                    dialog._advance()
            self.assertIn("SPARSE PREVIEW", dialog.status.text())
            self.assertEqual(self.model._cb_membrane_state[PACKING_KEY]["recipe"], recipe)
            dialog.reject()
            dialog = MembraneCellpackDialog(tool, self.model)
            self.assertFalse(dialog.automatic_count.isChecked())
            self.assertEqual(dialog.count.value(), 150)
            dialog.automatic_count.setChecked(True)
            with patch("src.membrane_cellpack_ui.fetch_protein", side_effect=AssertionError("Unexpected refetch")):
                dialog.start()
                self.assertIsNotNone(dialog.packer, dialog.status.text())
                self.assertTrue(dialog.packer.automatic_budget)
                self.assertGreater(dialog.packer.count, 150)
                while dialog.packer:
                    dialog._advance()
            self.assertNotIn("SPARSE PREVIEW", dialog.status.text())
            self.assertTrue(self.model._cb_membrane_state[PACKING_KEY]["automatic_particle_budget"])
        finally:
            dialog.reject()
            tool.delete()


result = unittest.TextTestRunner(stream=sys.__stderr__, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(RecipeTests))
if not result.wasSuccessful():
    raise RuntimeError("Membrane recipe regression checks failed")
