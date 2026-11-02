"""GUI ChimeraX: runscript tests/verify_membrane_packing_targets.py."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from Qt.QtWidgets import QApplication
from chimerax.core.models import Model
from chimerax.surface import sphere_geometry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cmd import buildmembrane_surface
from src.tool import CiliaBuilder2Tool
from src.membrane_cellpack import PACKING_KEY, restore_packing
from src.membrane_cellpack_ui import show_membrane_cellpack
from src.membrane_recipe import RecipePacker, default_recipe


@unittest.skipUnless(session.ui.is_gui, "GUI required")
class PackingTargetTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        session.selection.clear()
        self.first = self.membrane("Same name", 20)
        self.second = self.membrane("Same name", 40)
        self.tool = CiliaBuilder2Tool(session, "CiliaBuilder2")
        self.tool._last_membrane_model = self.first
        self.dialog = show_membrane_cellpack(self.tool)
        QApplication.processEvents()

    def tearDown(self):
        self.dialog.reject()
        self.tool.delete()
        created = set(session.models.list()) - self.before
        session.models.close([m for m in created if m.parent not in created])
        QApplication.processEvents()

    def membrane(self, name, thickness):
        return buildmembrane_surface(session, name, (12, 34, 56), (1, 2, 3),
                                     300, 200, thickness, distortion_level=.6,
                                     distortion_seed=1, tip_dome_enabled=True)

    def choose(self, model):
        index = self.dialog.target.findData(model)
        self.assertGreaterEqual(index, 0)
        self.dialog.target.setCurrentIndex(index)
        self.assertIs(self.dialog.model, model)

    def pack(self, count=60, seed=1):
        self.dialog.automatic_count.setChecked(False)
        self.dialog.count.setValue(count)
        self.dialog.seed.setValue(seed)
        self.dialog.start()
        self.assertIsNotNone(self.dialog.packer, self.dialog.status.text())
        while self.dialog.packer is not None:
            self.dialog._advance()
        self.assertIn("Packed", self.dialog.status.text())
        return self.dialog.model._cb_membrane_state[PACKING_KEY]

    def test_targets_defaults_drafts_and_concise_credit(self):
        dialog = self.dialog
        state = copy.deepcopy(self.first._cb_membrane_state)
        self.assertEqual(dialog.target.count(), 2)
        self.assertNotEqual(dialog.target.itemText(0), dialog.target.itemText(1))
        self.assertEqual(dialog.status.text(), "")
        self.assertIn("cellPACK (Johnson et al., 2015)", dialog.credit.text())
        self.assertIn("https://doi.org/10.1038/nmeth.3204", dialog.credit.text())
        self.assertIn("Independent implementation", dialog.credit.text())
        self.assertTrue(dialog.credit.openExternalLinks())
        self.assertEqual(dialog.rows[0]["radius"].value(), 10.)
        dialog.rows[0]["radius"].setValue(7.)
        dialog.seed.setValue(37)
        dialog.automatic_count.setChecked(False)
        dialog.count.setValue(123)
        dialog.add_ingredient("other")
        draft = dialog.recipe()
        self.choose(self.second)
        self.assertEqual(dialog.rows[0]["radius"].value(), 20.)
        self.assertEqual(dialog.seed.value(), 1)
        self.assertTrue(dialog.automatic_count.isChecked())
        self.assertFalse(dialog.export_button.isEnabled())
        self.choose(self.first)
        self.assertEqual(dialog.recipe(), draft)
        self.assertEqual(dialog.seed.value(), 37)
        self.assertEqual(dialog.count.value(), 123)
        self.assertFalse(dialog.automatic_count.isChecked())
        self.assertEqual(self.first._cb_membrane_state, state)
        self.assertEqual(len(self.tool._history_undo_stack), 0)

    def test_pack_and_export_follow_target_without_touching_other_membrane(self):
        first_result = copy.deepcopy(self.pack(50, 19))
        self.choose(self.second)
        self.assertFalse(self.dialog.export_button.isEnabled())
        second_result = self.pack(70, 23)
        self.assertEqual(self.first._cb_membrane_state[PACKING_KEY], first_result)
        self.assertEqual(len(self.tool._history_undo_stack), 2)
        self.assertEqual(self.dialog.target.count(), 2)  # No particle children.
        with tempfile.TemporaryDirectory() as folder:
            with patch("Qt.QtWidgets.QFileDialog.getExistingDirectory", return_value=folder):
                self.dialog.export()
            paths = list(Path(folder).glob("membrane_cellpack_*/packing.json"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(json.loads(paths[0].read_text()), second_result)
        self.choose(self.first)
        self.assertTrue(self.dialog.export_button.isEnabled())
        self.assertEqual(self.dialog.seed.value(), 19)
        self.assertEqual(self.dialog.count.value(), 50)

    def test_busy_selector_and_existing_window_target(self):
        dialog = self.dialog
        dialog.start()
        self.assertIsNotNone(dialog.packer)
        self.assertFalse(dialog.target.isEnabled())
        dialog.target.setCurrentIndex(dialog.target.findData(self.second))
        self.assertIs(dialog.model, self.first)
        self.assertIs(dialog.target.currentData(), self.first)
        self.tool._last_membrane_model = self.second
        self.assertIs(show_membrane_cellpack(self.tool), dialog)
        self.assertIs(dialog.model, self.first)
        dialog.cancel()
        self.assertTrue(dialog.target.isEnabled())
        self.assertIs(show_membrane_cellpack(self.tool), dialog)
        self.assertIs(dialog.model, self.second)
        self.assertNotIn(PACKING_KEY, self.first._cb_membrane_state)
        self.assertNotIn(PACKING_KEY, self.second._cb_membrane_state)
        self.assertEqual(len(self.tool._history_undo_stack), 0)

    def test_live_add_rename_id_delete_and_empty_recovery(self):
        third = self.membrane("Third", 30)
        unrelated = Model("Not a membrane", session)
        session.models.add([unrelated])
        QApplication.processEvents()
        self.assertEqual(self.dialog.target.count(), 3)
        self.assertIs(self.dialog.model, self.first)
        self.choose(third)
        third.name = "Renamed"
        session.models.assign_id(third, (99,))
        QApplication.processEvents()
        self.assertEqual(self.dialog.target.currentText(), "Renamed (#99)")
        session.models.close([third])
        QApplication.processEvents()
        self.assertIs(self.dialog.model, self.second)
        session.models.close([self.first, self.second])
        QApplication.processEvents()
        self.assertIsNone(self.dialog.model)
        self.assertFalse(self.dialog.run_button.isEnabled())
        self.assertFalse(self.dialog.export_button.isEnabled())
        self.assertFalse(self.dialog.target.isEnabled())
        self.assertEqual(len(self.dialog.rows), 0)
        fourth = self.membrane("Fourth", 18)
        QApplication.processEvents()
        self.assertIs(self.dialog.model, fourth)
        self.assertTrue(self.dialog.run_button.isEnabled())
        self.assertEqual(self.dialog.rows[0]["radius"].value(), 9.)
        self.dialog.reject()
        with patch.object(self.dialog, "_refresh_targets") as refresh:
            fourth.name = "After close"
            QApplication.processEvents()
            refresh.assert_not_called()
            self.assertFalse(self.dialog.refresh_timer.isActive())

    def test_deleted_running_target_cancels_instead_of_retargeting_result(self):
        self.dialog.start()
        self.assertIsNotNone(self.dialog.packer)
        session.models.close([self.first])
        with patch.object(session.logger, "error"):
            self.dialog._advance()
        self.assertIsNone(self.dialog.packer)
        self.assertIs(self.dialog.model, self.second)
        self.assertIs(self.dialog.target.currentData(), self.second)
        self.assertIn("cancelled", self.dialog.status.text())
        self.assertNotIn(PACKING_KEY, self.second._cb_membrane_state)
        self.assertEqual(len(self.tool._history_undo_stack), 0)

    def test_saved_settings_override_stale_draft_and_reuse_protein_template(self):
        self.choose(self.second)
        self.dialog.seed.setValue(17)
        self.choose(self.first)
        v, n, t = sphere_geometry(80)
        protein = dict(pdb_id="1AFO", axis="Z", vertices=(v*12).tolist(),
                       normals=n.tolist(), triangles=t.tolist(), radius=12., footprint_radius=12.)
        recipe = default_recipe(7)
        recipe[1].update(enabled=True, pdb_id="1AFO", amount=10.)
        packer = RecipePacker(self.second, recipe, {"1afo:Z": protein}, 80, 42)
        while not packer.step():
            pass
        restore_packing(self.second, packer.result())
        self.choose(self.second)
        self.assertEqual(self.dialog.seed.value(), 42)
        self.assertEqual(self.dialog.count.value(), 80)
        self.assertEqual(self.dialog.recipe(), recipe)
        self.assertEqual(self.dialog.templates["1afo:Z"], protein)
        with patch("src.membrane_cellpack_ui.fetch_protein", side_effect=AssertionError("Unexpected refetch")):
            self.pack(80, 42)

    def test_target_locked_during_protein_preparation(self):
        self.dialog.rows[1]["enabled"].setChecked(True)
        self.dialog.rows[1]["pdb_id"].setText("1AFO")

        def fetch(*args):
            self.assertFalse(self.dialog.target.isEnabled())
            self.dialog.target.setCurrentIndex(self.dialog.target.findData(self.second))
            self.assertIs(self.dialog.model, self.first)
            session.models.close([self.first])
            QApplication.processEvents()
            self.assertIs(self.dialog.model, self.first)
            return {}  # No packing may start after the target was deleted.

        with patch("src.membrane_cellpack_ui.fetch_protein", side_effect=fetch):
            with patch.object(session.logger, "error"):
                self.dialog.start()
        self.assertIsNone(self.dialog.packer)
        self.assertIs(self.dialog.model, self.second)
        self.assertIn("cancelled", self.dialog.status.text())
        self.assertNotIn(PACKING_KEY, self.second._cb_membrane_state)


result = unittest.TextTestRunner(stream=sys.__stderr__, verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(PackingTargetTests))
if not result.wasSuccessful():
    raise RuntimeError("Membrane packing target regression checks failed")
