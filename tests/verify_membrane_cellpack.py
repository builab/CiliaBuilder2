"""Run without extra installations: runscript tests/verify_membrane_cellpack.py."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from chimerax.core.commands import run
from chimerax.geometry import translation, rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cmd import buildmembrane_surface
from src.tool import CiliaBuilder2Tool
from src.membrane_cellpack import (ENGINE, PACKING_KEY, SurfacePacker, apply_result,
                                   export_packing, packing_classes, restore_packing,
                                   MembraneFillPacker, clear_packing)


class ValueControl:
    def setValue(self, value):
        self.current = value

    def value(self):
        return self.current


class MembranePackingTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        session.selection.clear()
        self.tmp = tempfile.TemporaryDirectory(prefix="cb-membrane-packing-test-")
        self.folder = Path(self.tmp.name)
        self.tool = object.__new__(CiliaBuilder2Tool)
        self.tool._session = weakref.ref(session)
        self.tool._attached_results = {}
        self.tool._last_attached_result = None
        self.tool._history_replaying = False
        self.tool._reset_history()
        self.tool.membrane_distortion = ValueControl()
        self.tool.membrane_distortion.setValue(0.6)
        self.tool._refresh_model_selectors = lambda: None
        self.tool._keep_tool_visible = lambda: None
        self.tool._cancel_active_tool_interactions_for_history = lambda: None
        self.model = buildmembrane_surface(session, "packing test membrane", (40, 50, 60),
                                           (1, 2, 3), 300, 200, 20,
                                           distortion_level=0.6, distortion_seed=123,
                                           tip_dome_enabled=True)
        self.tool._last_membrane_model = self.model

    def tearDown(self):
        run(session, "wait 1", log=False)
        created = set(session.models.list()) - self.before
        session.models.close([m for m in created if m.parent not in created])
        run(session, "wait 1", log=False)
        self.tmp.cleanup()

    def pack(self, count=100, radius=5, seed=1, batch=256, model=None):
        packer = SurfacePacker(model or self.model, packing_classes(self.tool, radius), count, seed)
        while not packer.step(batch):
            pass
        return packer.result()

    def protein(self):
        from chimerax.surface import sphere_geometry
        v, n, t = sphere_geometry(80)
        v = v * [12, 12, 25]
        return dict(pdb_id="1AFO", axis="Z", vertices=v.tolist(), normals=n.tolist(),
                    triangles=t.tolist(), radius=25., footprint_radius=12.)

    def fill(self, percent=20, protein=None, model=None, limit=300, radius=10, batch=256):
        packer = MembraneFillPacker(model or self.model, radius, percent,
                                   protein or self.protein(), limit, seed=7)
        while not packer.step(batch):
            pass
        return packer.result()

    def test_fill_coverage_zero_and_all_protein(self):
        lipid = self.fill(percent=0)
        self.assertEqual([g["suffix"] for g in lipid["groups"]], ["lipids"])
        self.assertIsNone(lipid["protein"])
        protein = self.fill(percent=100)
        self.assertEqual([g["suffix"] for g in protein["groups"]], ["protein"])
        self.assertLessEqual(protein["achieved_protein_percent"], 100)
        result = self.fill()
        self.assertEqual(result, self.fill(batch=7))
        count = sum(len(g["positions"]) for g in result["groups"] if g["suffix"] == "protein")
        self.assertAlmostEqual(result["achieved_protein_percent"],
                               count * np.pi * 12**2 / result["outer_area"] * 100)
        points = np.concatenate([g["positions"] for g in result["groups"]])
        radii = np.concatenate([np.full(len(g["positions"]), g["radius"]) for g in result["groups"]])
        distances = np.linalg.norm(points[:, None] - points[None, :], axis=2)
        np.fill_diagonal(distances, np.inf)
        roles = np.concatenate([np.repeat(g["suffix"], len(g["positions"])) for g in result["groups"]])
        same_kind = roles[:, None] == roles[None, :]
        self.assertTrue(np.all(distances[same_kind] >= (radii[:, None] + radii[None, :])[same_kind]))
        from src.membrane_protein import instance_matrices
        protein = next(g for g in result["groups"] if g["suffix"] == "protein")
        lipid = next(g for g in result["groups"] if g["suffix"] == "lipids")
        vertices = np.array(result["protein"]["vertices"])
        for matrix in instance_matrices(protein["positions"], protein["normals"]):
            local = (np.array(lipid["positions"])-matrix[:, 3]) @ matrix[:, :3]
            outside = np.maximum(np.maximum(vertices.min(axis=0)-local, local-vertices.max(axis=0)), 0)
            self.assertTrue(np.all(np.linalg.norm(outside, axis=1) >= lipid["radius"]))

    def test_dense_rows_high_coverage_bounded_work_and_one_shared_mesh(self):
        from scipy.spatial import cKDTree
        model = buildmembrane_surface(session, "dense rows", (0, 0, 0), (0, 0, 1),
                                     600, 400, 40, distortion_level=0, distortion_seed=1)
        packer = MembraneFillPacker(model, 10, 0, max_particles=50000)
        while not packer.step():
            pass
        result = packer.result()
        faces = model.vertices[model.triangles[model._cb_membrane_outer_faces | model._cb_membrane_inner_faces]].astype(float)
        area = np.linalg.norm(np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]), axis=1).sum()/2
        coverage = result["placed_count"] * np.pi*10**2 / area
        self.assertGreater(coverage, 0.80)
        self.assertLess(result["candidate_count"], 200000)
        points = np.array(result["groups"][0]["positions"])
        nearest, _ = cKDTree(points).query(points, k=2)
        self.assertGreaterEqual(nearest[:, 1].min(), 20)
        root = restore_packing(model, result)
        self.assertEqual(len(root.child_models()), 1)
        drawing = root.child_models()[0]
        self.assertEqual(len(drawing.positions), result["placed_count"])
        self.assertLess(len(drawing.vertices), 200)

    def test_protein_box_refinement_keeps_tight_safe_sites_and_checks_all_neighbors(self):
        from scipy.spatial import cKDTree
        from src.membrane_lattice import outside_protein_boxes
        # Both boxes enclose a long narrow protein; checking only the nearest
        # center would miss the second box at the first test point.
        tree = cKDTree([[0, 0, 0], [0, 0, 6]])
        rotations = np.array([np.eye(3), rotation((1, 0, 0), 90).matrix[:, :3]])
        bounds = np.array([-1, -1, -8]), np.array([1, 1, 8])
        points = np.array([[0, 5, 2.5], [4, 0, 0], [0, 0, 0]])
        keep = outside_protein_boxes(points, tree, rotations, bounds, 9, 3.5, 0)
        np.testing.assert_array_equal(keep, [False, False, False])
        keep = outside_protein_boxes(np.array([[5, 0, 0]]), tree, rotations, bounds, 9, 3.5, 0)
        self.assertTrue(keep[0])  # Inside the broad sphere, outside both actual boxes.

    def test_v2_packing_still_restores_without_repacking(self):
        result = self.fill(percent=0)
        result["algorithm_version"] = 2
        result.pop("placement_method")
        result.pop("candidate_count")
        result.pop("protein_lipid_exclusion")
        with patch.object(MembraneFillPacker, "__init__", side_effect=AssertionError("Unexpected repacking")):
            root = restore_packing(self.model, json.loads(json.dumps(result)))
        self.assertEqual(len(root.child_models()[0].positions), result["placed_count"])

    def test_cancel_releases_pending_work_without_partial_results(self):
        packer = MembraneFillPacker(self.model, 5, 0)
        before = copy.deepcopy(self.model._cb_membrane_state)
        packer.step()
        packer.cancel()
        self.assertIsNone(packer._work.gi_frame)
        with self.assertRaises(ValueError):
            packer.result()
        with self.assertRaises(ValueError):
            packer.step()
        self.assertEqual(self.model._cb_membrane_state, before)

    def test_dense_lipid_sites_follow_distorted_leaflets_and_dome(self):
        result = self.fill(percent=0)
        faces = self.model.vertices[self.model.triangles[self.model._cb_membrane_outer_faces |
                                                        self.model._cb_membrane_inner_faces]].astype(float)
        u, v = faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]
        normals = np.cross(u, v)
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        uu, uv, vv = np.sum(u*u, axis=1), np.sum(u*v, axis=1), np.sum(v*v, axis=1)
        denominator = uu*vv - uv*uv
        for point, normal in zip(result["groups"][0]["positions"], result["groups"][0]["normals"]):
            w = point-faces[:, 0]
            wu, wv = np.sum(w*u, axis=1), np.sum(w*v, axis=1)
            a, b = (wu*vv-wv*uv)/denominator, (wv*uu-wu*uv)/denominator
            inside = ((np.abs(np.sum(w*normals, axis=1)) < 1e-5) & (a >= -1e-6)
                      & (b >= -1e-6) & (a+b <= 1+1e-6)
                      & (np.linalg.norm(normals-normal, axis=1) < 1e-5))
            self.assertTrue(inside.any())

    def test_fill_particle_only_protein_rotation_and_original_mask(self):
        from src.membrane_protein import validate_protein
        mask = np.arange(len(self.model.triangles)) % 2 == 0
        self.model.triangle_mask = mask.copy()
        result = self.fill()
        root = restore_packing(self.model, result)
        self.assertFalse(self.model.triangle_mask.any())
        self.assertTrue(self.model.display)
        protein_group = next(g for g in result["groups"] if g["suffix"] == "protein")
        surface = next(c for c in root.child_models() if c.name.startswith("PDB"))
        np.testing.assert_array_equal(surface.vertices, validate_protein(result["protein"])[0])
        for place, normal, point in zip(surface.positions, protein_group["normals"], protein_group["positions"]):
            np.testing.assert_allclose(place.transform_vector((0, 0, 1)), normal, atol=1e-6)
            np.testing.assert_allclose(place.origin(), point, atol=1e-6)
        restore_packing(self.model, self.fill(percent=0))
        clear_packing(self.model)
        np.testing.assert_array_equal(self.model.triangle_mask, mask)

    def test_fill_json_offline_undo_and_distortion(self):
        apply_result(self.tool, self.model, self.fill())
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        self.tool._undo_last_action()
        self.assertIsNone(self.model.triangle_mask)
        self.tool._redo_last_action()
        self.assertFalse(self.model.triangle_mask.any())
        session.models.close([self.model])
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Unexpected fetch")):
            self.tool._restore_generated_membranes(records)
        self.model = self.tool._last_membrane_model
        self.assertFalse(self.model.triangle_mask.any())
        self.assertEqual(len(self.model.child_models()[0].child_models()), 2)
        self.tool.membrane_distortion.setValue(3)
        self.tool._update_membrane_distortion()
        self.assertIsNone(self.model.triangle_mask)
        self.assertEqual(len(self.model.child_models()), 0)
        self.tool._undo_last_action()
        self.assertFalse(self.model.triangle_mask.any())

    def test_fill_export_protein_mesh_and_hidden_guide(self):
        from src.local_apr import open_local_apr_package
        result = self.fill()
        self.model.position = translation((10, 20, 30)) * rotation((1, 2, 3), 71)
        folder = self.folder / "particles"
        export_packing(self.tool, self.model, result, folder)
        recipe = json.loads((folder / "membrane.cpr.json").read_text())
        self.assertNotIn("rep_file", recipe["compartments"]["membrane"])
        from src.membrane_protein import instance_matrices
        group = next(g for g in result["groups"] if g["suffix"] == "protein")
        expected = instance_matrices(group["positions"], group["normals"])
        expected_rotations = self.model.scene_position.matrix[:, :3] @ expected[:, :, :3]
        apr = json.loads((folder / "membrane.apr.json").read_text())
        placements = apr["compartments"]["membrane"]["surface"]["ingredients"]["ingredient_1"]["results"]
        np.testing.assert_allclose(np.array([r for p, r in placements])[:, :3, :3], expected_rotations)
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Unexpected fetch")):
            root, _ = open_local_apr_package(session, str(folder / "membrane.apr.json"))
            session.models.add([root])
            models, _ = session.open_command.open_data(str(folder / "membrane_particles.cif"))
            session.models.add(models)
        self.assertEqual(models[0].num_atoms, result["placed_count"])
        geometry = [m for m in root.all_models() if m.name == "geometry"]
        self.assertTrue(geometry)
        self.assertTrue(all(not m.display for m in geometry))
        protein_mesh = folder / "meshes/ingredient_1.dae"
        from chimerax.surface.collada import read_collada_surfaces
        surfaces, _ = read_collada_surfaces(session, str(protein_mesh), "protein test")
        try:
            np.testing.assert_allclose(surfaces[0].vertices, result["protein"]["vertices"], atol=1e-5)
        finally:
            for s in surfaces:
                s.delete()

    def test_fill_invalid_input_preserves_scene(self):
        before = self.model.vertices.copy()
        for percent, protein in ((-1, None), (101, None), (20, None), (float("nan"), None)):
            with self.subTest(percent=percent), self.assertRaises(ValueError):
                MembraneFillPacker(self.model, 10, percent, protein)
        np.testing.assert_array_equal(self.model.vertices, before)
        self.assertEqual(len(self.model.child_models()), 0)

    def test_fill_corrupt_json_mask_reveals_guide(self):
        apply_result(self.tool, self.model, self.fill())
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        records[0]["state"][PACKING_KEY]["guide_triangle_mask"] = 123
        session.models.close([self.model])
        with patch.object(session.logger, "warning") as warning:
            self.tool._restore_generated_membranes(records)
            self.assertTrue(warning.called)
        self.model = self.tool._last_membrane_model
        self.assertIsNone(self.model.triangle_mask)
        self.assertNotIn(PACKING_KEY, self.model._cb_membrane_state)

    def test_fill_protein_anchors_on_outer_leaflet_only(self):
        result = self.fill()
        group = next(g for g in result["groups"] if g["suffix"] == "protein")
        anchors = np.array(group["positions"]) + np.array(group["normals"]) * 10
        faces = self.model.vertices[self.model.triangles[self.model._cb_membrane_outer_faces]].astype(float)
        u, v = faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0]
        normals = np.cross(u, v)
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        uu, uv, vv = np.sum(u*u, axis=1), np.sum(u*v, axis=1), np.sum(v*v, axis=1)
        denominator = uu*vv - uv*uv
        for point, normal in zip(anchors, group["normals"]):
            w = point - faces[:, 0]
            wu, wv = np.sum(w*u, axis=1), np.sum(w*v, axis=1)
            a, b = (wu*vv - wv*uv)/denominator, (wv*uu - wu*uv)/denominator
            inside = ((np.abs(np.sum(w*normals, axis=1)) < 1e-5)
                      & (a >= -1e-6) & (b >= -1e-6) & (a+b <= 1+1e-6)
                      & (np.linalg.norm(normals - normal, axis=1) < 1e-5))
            self.assertTrue(inside.any())

    def test_real_pdb_template_reused_without_scene_pollution(self):
        from src.membrane_protein import fetch_protein
        before = set(session.models.list())
        protein = fetch_protein(session, "1AFO", "Z")
        self.assertGreater(protein["atom_count"], 100)
        self.assertEqual(set(session.models.list()), before)
        result = self.fill(protein=protein)
        restore_packing(self.model, result)
        self.assertEqual(result["protein"]["pdb_id"], "1AFO")
        with patch("chimerax.core.fetch.fetch_file", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                fetch_protein(session, "1AFO", "Z")
        self.assertIn(PACKING_KEY, self.model._cb_membrane_state)

    def test_seeded_packing_batch_independence_composition_and_exclusion(self):
        result = self.pack(count=100, batch=7)
        self.assertEqual(result, self.pack(count=100, batch=256))
        self.assertNotEqual(result, self.pack(count=100, seed=2))
        self.assertEqual(result["engine"], ENGINE)
        self.assertEqual([len(g["positions"]) for g in result["groups"]], [8, 7, 7, 8, 70])
        positions = np.concatenate([g["positions"] for g in result["groups"]])
        radii = np.concatenate([np.full(len(g["positions"]), g["radius"]) for g in result["groups"]])
        distances = np.linalg.norm(positions[:, None] - positions[None, :], axis=2)
        np.fill_diagonal(distances, np.inf)
        self.assertTrue(np.all(distances >= radii[:, None] + radii[None, :]))

    def test_sampled_points_lie_on_actual_distorted_domed_surface(self):
        packer = SurfacePacker(self.model, packing_classes(self.tool, 5), 100, 1)
        while not packer.step():
            pass
        for group in packer.result()["groups"]:
            for point in np.array(group["positions"]):
                face = packer.faces
                u, v, w = face[:, 1] - face[:, 0], face[:, 2] - face[:, 0], point - face[:, 0]
                plane_distance = np.abs(np.sum(w * packer.normals, axis=1))
                uu, uv, vv = np.sum(u*u, axis=1), np.sum(u*v, axis=1), np.sum(v*v, axis=1)
                wu, wv = np.sum(w*u, axis=1), np.sum(w*v, axis=1)
                denominator = uu*vv - uv*uv
                a, b = (wu*vv - wv*uv)/denominator, (wv*uu - wu*uv)/denominator
                inside = (plane_distance < 1e-6) & (a >= -1e-6) & (b >= -1e-6) & (a+b <= 1+1e-6)
                self.assertTrue(inside.any())

    def test_partial_packing_is_bounded_and_reported(self):
        result = self.pack(count=100, radius=300)
        self.assertLess(result["placed_count"], 100)
        self.assertGreater(result["placed_count"], 0)

    def test_invalid_inputs(self):
        for count, radius in ((0, 5), (10001, 5), (5, 0), (5, float("nan"))):
            with self.subTest(count=count, radius=radius), self.assertRaises(ValueError):
                SurfacePacker(self.model, packing_classes(self.tool, radius), count)

    def test_preview_grouping_instancing_and_selector_exclusion(self):
        self.model.position = translation((100, 200, 300))
        original = self.model.vertices.copy()
        state = copy.deepcopy(self.model._cb_membrane_state)
        root = restore_packing(self.model, self.pack())
        self.assertIs(root.parent, self.model)
        self.assertEqual(len(root.child_models()), 5)
        self.assertEqual(sum(len(child.positions) for child in root.child_models()), 100)
        for child in [root] + root.child_models():
            self.assertFalse(self.tool._is_selector_attach_source(child))
        np.testing.assert_array_equal(self.model.vertices, original)
        saved = dict(self.model._cb_membrane_state)
        saved.pop(PACKING_KEY)
        self.assertEqual(saved, state)
        restore_packing(self.model, self.pack())
        self.assertEqual(len(self.model.child_models()), 1)

    def test_json_roundtrip_and_undo_redo(self):
        apply_result(self.tool, self.model, self.pack())
        self.assertEqual(len(self.tool._history_undo_stack), 1)
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        self.tool._undo_last_action()
        self.assertNotIn(PACKING_KEY, self.model._cb_membrane_state)
        self.assertEqual(len(self.model.child_models()), 0)
        self.tool._redo_last_action()
        self.assertEqual(len(self.model.child_models()), 1)
        session.models.close([self.model])
        self.tool._restore_generated_membranes(records)
        self.model = self.tool._last_membrane_model
        self.assertEqual(len(self.model.child_models()), 1)
        self.assertEqual(self.model._cb_membrane_state[PACKING_KEY], records[0]["state"][PACKING_KEY])

    def test_edit_invalidates_packing_and_undo_restores_it(self):
        apply_result(self.tool, self.model, self.pack())
        self.tool.membrane_distortion.setValue(3)
        self.tool._update_membrane_distortion()
        self.assertEqual(len(self.model.child_models()), 0)
        self.assertNotIn(PACKING_KEY, self.model._cb_membrane_state)
        self.tool._undo_last_action()
        self.assertEqual(len(self.model.child_models()), 1)
        self.assertIn(PACKING_KEY, self.model._cb_membrane_state)

    def test_stale_or_invalid_result_keeps_existing_preview(self):
        good = self.pack()
        root = restore_packing(self.model, good)
        for change in ({"mesh_digest": "stale"}, {"placed_count": 0}, {"groups": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                restore_packing(self.model, dict(good, **change))
            self.assertIs(self.model.child_models()[0], root)

    def test_invalid_json_preview_warns_but_restores_membrane(self):
        apply_result(self.tool, self.model, self.pack())
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        records[0]["state"][PACKING_KEY]["groups"][0]["positions"] = [1, 2, 3]
        session.models.close([self.model])
        with patch.object(session.logger, "warning") as warning:
            self.tool._restore_generated_membranes(records)
            self.assertTrue(warning.called)
        self.model = self.tool._last_membrane_model
        self.assertTrue(self.model in session.models.list())
        self.assertNotIn(PACKING_KEY, self.model._cb_membrane_state)
        self.assertEqual(len(self.model.child_models()), 0)

    def test_deleted_target_cannot_receive_packing(self):
        result = self.pack()
        session.models.close([self.model])
        with self.assertRaises(ValueError):
            apply_result(self.tool, self.model, result)
        self.assertEqual(len(self.tool._history_undo_stack), 0)

    def test_export_relocated_package_apr_and_cif_match_preview(self):
        from src.local_apr import open_local_apr_package
        self.model.position = translation((100, 200, 300))
        result = self.pack()
        export_packing(self.tool, self.model, result, self.folder / "original")
        (self.folder / "original").rename(self.folder / "moved package")
        folder = self.folder / "moved package"
        with self.assertRaises(ValueError):
            export_packing(self.tool, self.model, result, folder)
        apr = json.loads((folder / "membrane.apr.json").read_text())
        placements = apr["compartments"]["membrane"]["surface"]["ingredients"]
        self.assertEqual(sum(len(v["results"]) for v in placements.values()), result["placed_count"])
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Unexpected network fetch")):
            root, info = open_local_apr_package(session, str(folder / "membrane.apr.json"))
            if root not in session.models.list():
                session.models.add([root])
            models = session.open_command.open_data(str(folder / "membrane_particles.cif"))[0]
            session.models.add(models)
        structure = next(m for m in models if hasattr(m, "atoms"))
        self.assertEqual(structure.num_atoms, result["placed_count"])
        expected = np.concatenate([g["positions"] for g in result["groups"]]) + [100, 200, 300]
        np.testing.assert_allclose(structure.atoms.coords, expected, atol=0.001)
        self.assertEqual(apr["ciliabuilder_engine"], ENGINE)

    def test_default_size_5000_particles(self):
        model = buildmembrane_surface(session, "default size", (0, 0, 0), (0, 0, 1),
                                     3000, 2700, 40, distortion_level=5,
                                     distortion_seed=47, tip_dome_enabled=True)
        result = self.pack(count=5000, radius=12, model=model)
        self.assertEqual(result["placed_count"], 5000)
        restore_packing(model, result)

    @unittest.skipUnless(session.ui.is_gui, "GUI required")
    def test_real_dialog_preview_export_and_cancel(self):
        from Qt.QtCore import QEventLoop, QTimer
        from Qt.QtWidgets import QApplication
        from src.membrane_cellpack_ui import show_membrane_cellpack
        tool = CiliaBuilder2Tool(session, "CiliaBuilder2")
        tool._last_membrane_model = self.model
        dialog = show_membrane_cellpack(tool)
        try:
            dialog.automatic_count.setChecked(False)
            dialog.count.setValue(100)
            dialog.rows[0]["radius"].setValue(5)
            dialog.start()
            self.assertIsNotNone(dialog.packer)
            self.assertFalse(dialog.run_button.isEnabled())
            loop = QEventLoop()
            check = QTimer()
            check.timeout.connect(lambda: loop.quit() if dialog.packer is None else None)
            check.start(10)
            QTimer.singleShot(30000, loop.quit)
            loop.exec()
            check.stop()
            self.assertIsNone(dialog.packer, dialog.status.text())
            self.assertIn("Packed", dialog.status.text())
            with patch("Qt.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(self.folder)):
                dialog.export()
            self.assertEqual(len(list(self.folder.glob("membrane_cellpack_*/membrane.apr.json"))), 1)
            before = copy.deepcopy(self.model._cb_membrane_state)
            history_size = len(tool._history_undo_stack)
            dialog.count.setValue(5000)
            dialog.start()
            dialog._advance()
            self.assertIsNotNone(dialog.packer)
            dialog.cancel()
            QApplication.processEvents()
            self.assertIsNone(dialog.packer)
            self.assertFalse(dialog.timer.isActive())
            self.assertEqual(self.model._cb_membrane_state, before)
            self.assertEqual(len(tool._history_undo_stack), history_size)
            dialog.rows[1]["enabled"].setChecked(True)
            dialog.rows[1]["amount"].setValue(20)
            dialog.rows[1]["pdb_id"].setText("invalid")
            with patch.object(session.logger, "error"):
                dialog.start()
            self.assertIsNone(dialog.packer)
            self.assertEqual(self.model._cb_membrane_state, before)
            dialog.rows[1]["pdb_id"].setText("1AFO")
            dialog.count.setValue(300)
            dialog.start()
            self.assertIsNotNone(dialog.packer, dialog.status.text())
            while dialog.packer is not None:
                dialog._advance()
            self.assertIn("Protein coverage:", dialog.status.text())
            self.assertEqual(self.model._cb_membrane_state[PACKING_KEY]["templates"]["1afo:Z"]["pdb_id"], "1AFO")
            self.assertFalse(self.model.triangle_mask.any())
            dialog.reject()
            dialog = show_membrane_cellpack(tool)
            self.assertEqual(dialog.rows[1]["pdb_id"].text(), "1AFO")
            self.assertEqual(dialog.rows[1]["amount"].value(), 20)
            with patch("src.membrane_cellpack_ui.fetch_protein", side_effect=AssertionError("Unexpected refetch")):
                dialog.start()
            self.assertIsNotNone(dialog.packer, dialog.status.text())
            dialog.cancel()
        finally:
            dialog.reject()
            tool.delete()


result = unittest.TextTestRunner(stream=sys.__stderr__, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(MembranePackingTests))
if not result.wasSuccessful():
    raise RuntimeError("Built-in membrane packing regression checks failed")
