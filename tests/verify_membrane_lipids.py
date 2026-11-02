"""ChimeraX: runscript tests/verify_membrane_lipids.py (GUI checks need normal GUI)."""

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
from chimerax.geometry import rotation, translation
from chimerax.surface import sphere_geometry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cmd import buildmembrane_surface
from src.tool import CiliaBuilder2Tool
from src.membrane_cellpack import PACKING_KEY, apply_result, restore_packing, validate_result, export_packing
from src.membrane_molecule import (AtomSpheres, atom_positions, load_lipid, molecular_conflicts, validate_template)
from src.membrane_protein import instance_matrices
from src.membrane_recipe import RecipePacker, default_recipe, template_key


class Control:
    def value(self):
        return .6

    def setValue(self, value):
        pass


class LipidTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        session.selection.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name).resolve()
        self.path = self.folder / "lipid.pdb"
        self.coords = np.array([(0, 0, 8), (-2, 0, 6), (2, 0, 6), (-2, 0, 3),
                                (2, 0, 3), (-2, 0, 0), (2, 0, 0), (-2, 0, -3), (2, 0, -3)])
        lines = []
        for i, (x, y, z) in enumerate(self.coords, 1):
            element = "O" if i == 1 else "C"
            lines.append(f"HETATM{i:5d} {element+str(i):<4s} LIP A   1    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2s}\n")
        self.path.write_text("".join(lines) + "END\n")
        self.entry = dict(default_recipe(5)[0], source="file", file_path=str(self.path), residue_name="")
        self.template = load_lipid(session, self.entry)
        self.model = buildmembrane_surface(session, "molecular lipids", (12, 34, 56), (1, 2, 3),
                         120, 100, 40, distortion_level=.6, distortion_seed=1, tip_dome_enabled=True)
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
        created = set(session.models.list()) - self.before
        session.models.close([m for m in created if m.parent not in created])
        self.temp.cleanup()

    def pack(self, recipe=None, templates=None, limit=80):
        packer = RecipePacker(self.model, recipe or [self.entry],
                             templates or {template_key(self.entry): self.template}, limit, 17)
        while not packer.step():
            pass
        result = packer.result()
        validate_result(result)
        return result

    def test_file_atoms_shape_dimensions_and_no_session_leak(self):
        self.assertEqual(self.template["atom_count"], len(self.coords))
        self.assertEqual(self.template["resolved_residue"], "LIP")
        self.assertEqual(self.template["file_path"], str(self.path))
        coords, radii = np.array(self.template["atom_coords"]), np.array(self.template["atom_radii"])
        np.testing.assert_allclose(coords[1:]-coords[0], self.coords[1:]-self.coords[0])
        self.assertAlmostEqual((coords[:, 2]+radii).max(), 0.)
        self.assertGreater(len(self.template["vertices"]), 300)
        self.assertGreater(self.template["radius"], self.template["footprint_radius"])
        before = set(session.models.list())
        turned = load_lipid(session, dict(self.entry, axis="X"))
        self.assertNotEqual(turned["vertices"], self.template["vertices"])
        self.assertEqual(set(session.models.list()), before)

    def test_local_cif_sdf_mol2_and_ambiguous_or_missing_input(self):
        models, _ = session.open_command.open_data(str(self.path))
        try:
            from chimerax.mmcif.mmcif_write import write_mmcif
            cif = self.folder / "lipid.cif"
            write_mmcif(session, str(cif), models=models)
            restored = load_lipid(session, dict(self.entry, file_path=str(cif)))
            self.assertEqual(restored["atom_count"], len(self.coords))
        finally:
            for model in models:
                model.delete()
        sdf = self.folder / "lipid.sdf"
        atom_lines = [f"{x:10.4f}{y:10.4f}{z:10.4f} C   0  0  0  0  0  0  0  0  0  0  0  0\n" for x, y, z in self.coords]
        sdf.write_text("LIP\n test\n\n" + f"{len(self.coords):3d}  0  0  0  0  0            999 V2000\n" + "".join(atom_lines) + "M  END\n$$$$\n")
        self.assertEqual(load_lipid(session, dict(self.entry, file_path=str(sdf)))["atom_count"], len(self.coords))
        mol2 = self.folder / "lipid.mol2"
        mol2.write_text("@<TRIPOS>MOLECULE\nLIP\n9 0 1 0 0\nSMALL\nNO_CHARGES\n\n@<TRIPOS>ATOM\n" +
                       "".join(f"{i} C{i} {x} {y} {z} C.3 1 LIP 0.0\n" for i, (x, y, z) in enumerate(self.coords, 1)) +
                       "@<TRIPOS>SUBSTRUCTURE\n1 LIP 1\n")
        self.assertEqual(load_lipid(session, dict(self.entry, file_path=str(mol2)))["atom_count"], 9)
        for entry in (dict(self.entry, file_path=str(self.folder/"absent.pdb")),
                      dict(self.entry, file_path=str(self.folder/"script.py")), dict(self.entry, residue_name="NONE")):
            with self.assertRaises(ValueError):
                load_lipid(session, entry)

    def test_real_pdb_lipid_selection_and_cached_id(self):
        before = set(session.models.list())
        entry = dict(self.entry, source="pdb", pdb_id="1K4C", residue_name="DGA", file_path="")
        template = load_lipid(session, entry)
        self.assertEqual(template["resolved_residue"], "DGA")
        self.assertGreater(template["atom_count"], 20)
        self.assertLess(template["atom_count"], 100)
        self.assertEqual(template_key(entry), template_key(template))
        with self.assertRaisesRegex(ValueError, "Several components"):
            load_lipid(session, dict(entry, residue_name=""))
        self.assertEqual(set(session.models.list()), before)
        self.pack([entry], {template_key(entry): template}, limit=20)

    def test_collision_index_and_candidate_graph_match_brute_force(self):
        rng = np.random.default_rng(14)
        points = rng.uniform(-9, 9, (32, 3))
        normals = rng.normal(size=(32, 3))
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        spins = rng.uniform(0, 6, 32)
        atoms = atom_positions(self.template, points, normals, spins)
        radii = np.array(self.template["atom_radii"])
        threshold = radii[:, None]+radii[None, :]+.001*np.minimum(radii[:, None], radii[None, :])
        offsets, neighbors = molecular_conflicts(self.template, points, normals, spins)
        pairs = set(zip(np.repeat(np.arange(len(points)), np.diff(offsets)), neighbors))
        expected = {(i, j) for i in range(32) for j in range(i+1, 32)
                    if np.any(np.linalg.norm(atoms[i, :, None]-atoms[j, None, :], axis=2) < threshold)}
        self.assertEqual(pairs, expected)
        spheres = AtomSpheres(atoms[0], radii)
        test = rng.uniform(-20, 20, (100, 3))
        brute = (np.linalg.norm(test[:, None]-atoms[0], axis=2) >= 2+radii+.001*np.minimum(2, radii)).all(1)
        np.testing.assert_array_equal(spheres.clear(test, 2), brute)

    def test_molecule_packing_no_atom_overlap_and_not_enclosing_beads(self):
        result = self.pack(limit=180)
        self.assertEqual(result["algorithm_version"], 7)
        self.assertEqual(result["protein_percent"], 0.)
        self.assertEqual(result["achieved_protein_percent"], 0.)
        group = result["groups"][0]
        atoms = atom_positions(self.template, group["positions"], group["normals"], group["spins"])
        radii = np.array(self.template["atom_radii"])
        threshold = radii[:, None]+radii[None, :]+.001*np.minimum(radii[:, None], radii[None, :])
        for i in range(len(atoms)):
            for j in range(i):
                self.assertTrue((np.linalg.norm(atoms[i, :, None]-atoms[j, None, :], axis=2) >= threshold-1e-7).all())
        from scipy.spatial import cKDTree
        self.assertLess(cKDTree(group["positions"]).query(group["positions"], k=2)[0][:, 1].min(), 2*self.template["radius"])
        root = restore_packing(self.model, result)
        surface = root.child_models()[0]
        self.assertEqual(len(surface.positions), len(group["positions"]))
        np.testing.assert_allclose(surface.vertices, self.template["vertices"])

    def test_mixed_beads_proteins_molecules_and_offline_json_undo_export(self):
        v, n, t = sphere_geometry(80)
        protein = dict(pdb_id="1AFO", axis="Z", vertices=(v*10).tolist(), normals=n.tolist(),
                       triangles=t.tolist(), radius=10., footprint_radius=10.)
        bead, protein_entry = default_recipe(4)
        bead.update(key="beads", amount=30)
        protein_entry.update(enabled=True, pdb_id="1AFO", amount=10)
        recipe = [dict(self.entry, amount=70), bead, protein_entry]
        templates = {template_key(self.entry): self.template, "1afo:Z": protein}
        result = self.pack(recipe, templates, limit=160)
        self.assertEqual(result["protein_percent"], 10)
        self.assertTrue(all(g["positions"] for g in result["groups"]))
        lipid_group, bead_group, protein_group = result["groups"]
        atoms = atom_positions(self.template, lipid_group["positions"], lipid_group["normals"], lipid_group["spins"])
        radii = np.tile(self.template["atom_radii"], len(atoms))
        atoms = atoms.reshape((-1, 3))
        bead_points = np.asarray(bead_group["positions"])
        separation = np.linalg.norm(atoms[:, None]-bead_points, axis=2)
        self.assertTrue((separation >= radii[:, None]+4+.001*np.minimum(radii[:, None], 4)-1e-7).all())
        from src.membrane_collision import ProteinMesh
        mesh = ProteinMesh(protein["vertices"], protein["triangles"])
        matrices = instance_matrices(protein_group["positions"], protein_group["normals"], protein_group["spins"])
        for matrix in matrices:
            local = (atoms-matrix[:, 3]) @ matrix[:, :3]
            self.assertTrue((mesh.distances(local)[:, 0] >= radii+.001*radii-1e-5).all())
            self.assertFalse(mesh.inside(local).any())
        apply_result(self.tool, self.model, result)
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        self.tool._undo_last_action()
        self.assertNotIn(PACKING_KEY, self.model._cb_membrane_state)
        self.tool._redo_last_action()
        self.path.unlink()
        session.models.close([self.model])
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Must be offline")):
            self.tool._restore_generated_membranes(records)
        self.model = self.tool._last_membrane_model
        self.assertEqual(self.model._cb_membrane_state[PACKING_KEY]["groups"], result["groups"])
        self.model.position = translation((100, 200, 300))*rotation((1, 2, 3), 37)
        directory = self.folder/"export"
        export_packing(self.tool, self.model, result, directory)
        apr = json.loads((directory/"membrane.apr.json").read_text())
        lipid = result["groups"][0]
        matrices = instance_matrices(lipid["positions"], lipid["normals"], lipid["spins"])
        exported = apr["compartments"]["membrane"]["surface"]["ingredients"]["ingredient_1"]["results"]
        np.testing.assert_allclose(np.array([r for p, r in exported])[:, :3, :3], self.model.scene_position.matrix[:, :3] @ matrices[:, :, :3])
        from src.local_apr import open_local_apr_package
        with patch("chimerax.core.fetch.fetch_file", side_effect=AssertionError("Must be offline")):
            root, _ = open_local_apr_package(session, str(directory/"membrane.apr.json"))
            session.models.add([root])
        self.assertTrue(root.child_models())

    def test_corrupt_geometry_rejected_and_cancel_safe(self):
        bad = copy.deepcopy(self.template)
        bad["atom_radii"][0] *= .5
        with self.assertRaises(ValueError):
            validate_template(bad)
        result = self.pack()
        result["algorithm_version"] = 6
        with self.assertRaises(ValueError):
            validate_result(result)
        packer = RecipePacker(self.model, [self.entry], {template_key(self.entry): self.template}, 1000)
        packer.step()
        packer.cancel()
        self.assertFalse(packer._lipid_atoms)
        self.assertIsNone(packer._work.gi_frame)
        self.assertNotIn(PACKING_KEY, self.model._cb_membrane_state)

    @unittest.skipUnless(session.ui.is_gui, "GUI required")
    def test_dialog_source_file_pdb_switch_saved_recipe_and_no_reopen(self):
        from src.membrane_cellpack_ui import MembraneCellpackDialog
        tool = CiliaBuilder2Tool(session, "CiliaBuilder2")
        dialog = MembraneCellpackDialog(tool, self.model)
        try:
            row = dialog.rows[0]
            row["source"].setCurrentIndex(row["source"].findData("file"))
            self.assertFalse(row["radius"].isEnabled())
            self.assertTrue(row["axis"].isEnabled())
            with patch("Qt.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(self.path), "")):
                row["browse"].click()
            self.assertEqual(row["file_path"].text(), str(self.path))
            dialog.automatic_count.setChecked(False)
            dialog.count.setValue(60)
            dialog.start()
            self.assertIsNotNone(dialog.packer, dialog.status.text())
            while dialog.packer:
                dialog._advance()
            saved = copy.deepcopy(self.model._cb_membrane_state[PACKING_KEY])
            dialog.reject()
            self.path.unlink()
            dialog = MembraneCellpackDialog(tool, self.model)
            self.assertEqual(dialog.recipe(), saved["recipe"])
            with patch("src.membrane_cellpack_ui.load_lipid", side_effect=AssertionError("Must reuse embedded lipid")):
                dialog.start()
                self.assertIsNotNone(dialog.packer, dialog.status.text())
                dialog.cancel()
            row = dialog.rows[0]
            row["source"].setCurrentIndex(row["source"].findData("pdb"))
            row["pdb_id"].setText("1K4C")
            row["residue_name"].setText("DGA")
            self.assertEqual(dialog.recipe()[0]["source"], "pdb")
            self.assertEqual(dialog.recipe()[0]["residue_name"], "DGA")
            row["source"].setCurrentIndex(row["source"].findData("bead"))
            self.assertTrue(row["radius"].isEnabled())
            self.assertNotIn("source", dialog.recipe()[0])
        finally:
            dialog.reject()
            tool.delete()


result = unittest.TextTestRunner(stream=sys.__stderr__, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(LipidTests))
if not result.wasSuccessful():
    raise RuntimeError("Molecular lipid checks failed")
