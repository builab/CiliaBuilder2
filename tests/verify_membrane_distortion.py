"""Run in ChimeraX: runscript tests/verify_membrane_distortion.py."""

import copy
import json
from pathlib import Path
import sys
import unittest
import weakref

import numpy as np
from chimerax.core.commands import run
from chimerax.geometry import translation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cmd import buildmembrane_surface
from src.tool import CiliaBuilder2Tool


class ValueControl:
    def __init__(self, value):
        self.setValue(value)

    def value(self):
        return self.current

    def setValue(self, value):
        self.current = value


class MembraneDistortionTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        session.selection.clear()
        self.tool = object.__new__(CiliaBuilder2Tool)
        self.tool._session = weakref.ref(session)
        self.tool._attached_results = {}
        self.tool._last_attached_result = None
        self.tool._history_replaying = False
        self.tool._reset_history()
        self.tool.membrane_distortion = ValueControl(0.6)
        self.tool._refresh_model_selectors = lambda: None
        self.tool._keep_tool_visible = lambda: None
        self.tool._cancel_active_tool_interactions_for_history = lambda: None

    def tearDown(self):
        created = set(session.models.list()) - self.before
        session.models.close([m for m in created if m.parent not in created])
        run(session, "wait 1", log=False)

    def membrane(self, name="membrane", dome=False):
        model = buildmembrane_surface(session, name, (40, 50, 60), (1, 2, 3),
                                      3000, 2700, 40, distortion_level=0.6,
                                      distortion_seed=123, tip_dome_enabled=dome,
                                      tip_dome_outer_height=1600, tip_dome_inner_height=1560)
        model._cb_membrane_state.update(offset=50, radius=1350, source_star_name="original STAR")
        self.tool._last_membrane_model = model
        return model

    def edit(self, level):
        self.tool.membrane_distortion.setValue(level)
        self.tool._update_membrane_distortion()

    def test_edit_changes_existing_geometry_without_replacing_model(self):
        model = self.membrane()
        model.set_selected(True)
        model.position = translation((3, 4, 5))
        model.color = (11, 23, 45, 130)
        model.allow_clipping = False
        colors = np.tile([10, 20, 30, 140], (len(model.vertices), 1)).astype(np.uint8)
        model.vertex_colors = colors
        old_vertices = model.vertices.copy()
        old_triangles = model.triangles.copy()
        old_state = copy.deepcopy(model._cb_membrane_state)
        old_models = set(session.models.list())
        old_id, old_parent = model.id, model.parent
        self.edit(5)
        self.assertFalse(np.array_equal(model.vertices, old_vertices))
        self.assertEqual(set(session.models.list()), old_models)
        self.assertEqual((model.id, model.parent), (old_id, old_parent))
        np.testing.assert_array_equal(model.triangles, old_triangles)
        np.testing.assert_array_equal(model.vertex_colors, colors)
        np.testing.assert_array_equal(model.position.origin(), [3, 4, 5])
        self.assertFalse(model.allow_clipping)
        self.assertTrue(model.selected)
        old_state["distortion_level"] = 5.0
        self.assertEqual(model._cb_membrane_state, old_state)
        self.assertEqual(len(self.tool._history_undo_stack), 1)

    def test_selected_membrane_wins_over_latest(self):
        first = self.membrane("first")
        second = self.membrane("second")
        first.set_selected(True)
        untouched = second.vertices.copy()
        self.edit(2)
        self.assertEqual(first._cb_membrane_state["distortion_level"], 2)
        np.testing.assert_array_equal(second.vertices, untouched)

    def test_no_selection_updates_latest_and_deleted_target_is_ignored(self):
        first = self.membrane("first")
        second = self.membrane("second")
        self.edit(3)
        self.assertEqual(first._cb_membrane_state["distortion_level"], 0.6)
        self.assertEqual(second._cb_membrane_state["distortion_level"], 3)
        session.models.close([second])
        self.edit(4)
        self.assertEqual(first._cb_membrane_state["distortion_level"], 4)

    def test_zero_and_restored_level_reproduce_same_random_pattern(self):
        for dome in (False, True):
            with self.subTest(dome=dome):
                model = self.membrane("dome " + str(dome), dome=dome)
                baseline = model.vertices.copy()
                self.edit(0)
                smooth = model.vertices.copy()
                self.assertFalse(np.array_equal(smooth, baseline))
                self.edit(1.2)
                np.testing.assert_allclose(model.vertices - smooth,
                                           2 * (baseline - smooth), atol=0.0005)
                self.edit(0.6)
                np.testing.assert_array_equal(model.vertices, baseline)

    def test_no_model_and_unchanged_value_do_not_create_history(self):
        self.edit(3)
        self.assertEqual(set(session.models.list()), self.before)
        model = self.membrane()
        self.edit(0.6)
        self.assertEqual(self.tool._history_undo_stack, [])
        self.assertEqual(model._cb_membrane_state["distortion_level"], 0.6)

    def test_undo_redo_restore_geometry_in_place_and_control_value(self):
        model = self.membrane()
        old_id = model.id
        before = model.vertices.copy()
        self.edit(5)
        after = model.vertices.copy()
        self.tool._undo_last_action()
        self.assertEqual(model.id, old_id)
        np.testing.assert_array_equal(model.vertices, before)
        self.assertEqual(self.tool.membrane_distortion.value(), 0.6)
        self.tool._redo_last_action()
        self.assertEqual(model.id, old_id)
        np.testing.assert_array_equal(model.vertices, after)
        self.assertEqual(self.tool.membrane_distortion.value(), 5)

    def test_json_restored_membrane_remains_editable(self):
        model = self.membrane(dome=True)
        self.edit(5)
        expected = model.vertices.copy()
        records = json.loads(json.dumps(self.tool._generated_membrane_models()))
        session.models.close([model])
        self.tool._restore_generated_membranes(records)
        restored = self.tool._last_membrane_model
        self.assertIsNot(restored, model)
        np.testing.assert_array_equal(restored.vertices, expected)
        self.assertEqual(restored._cb_membrane_state["distortion_seed"], 123)
        self.edit(0)
        self.assertFalse(np.array_equal(restored.vertices, expected))

    @unittest.skipUnless(session.ui.is_gui, "GUI signal test requires ChimeraX without --nogui")
    def test_real_widget_commits_edits_but_not_programmatic_load_values(self):
        from Qt.QtCore import Qt
        from Qt.QtWidgets import QApplication, QTabWidget
        import Qt as qt_binding
        from importlib import import_module

        binding = next(name for name in ("PyQt6", "PySide6", "PyQt5", "PySide2")
                       if getattr(qt_binding, "using_" + name.lower()))
        QTest = import_module(binding + ".QtTest").QTest

        tool = CiliaBuilder2Tool(session, "CiliaBuilder2")
        try:
            for tabs in tool.tool_window.ui_area.findChildren(QTabWidget):
                for index in range(tabs.count()):
                    if tabs.tabText(index) == "Membrane":
                        tabs.setCurrentIndex(index)
            # Focus-loss commits require an active Qt window. A scripted GUI
            # launch can leave macOS focus on another app despite visible widgets.
            window = tool.tool_window.ui_area.window()
            window.show()
            window.activateWindow()
            QApplication.setActiveWindow(window)
            QApplication.processEvents()
            tool._build_membrane()
            model = tool._last_membrane_model
            self.assertIsNotNone(model)
            original = model.vertices.copy()
            history_size = len(tool._history_undo_stack)
            widget = tool.membrane_distortion
            widget.setFocus()
            QApplication.processEvents()
            widget.lineEdit().selectAll()
            QTest.keyClicks(widget.lineEdit(), "5.00")
            np.testing.assert_array_equal(model.vertices, original)
            QTest.keyClick(widget.lineEdit(), Qt.Key_Return)
            self.assertEqual(model._cb_membrane_state["distortion_level"], 5)
            self.assertEqual(len(tool._history_undo_stack), history_size + 1)
            changed = model.vertices.copy()
            state = tool._ui_state()
            state["membrane_distortion"] = 2.0
            tool._apply_ui_state(state)
            np.testing.assert_array_equal(model.vertices, changed)
            self.assertEqual(len(tool._history_undo_stack), history_size + 1)
            tool.membrane_length.setFocus()
            QApplication.processEvents()
            np.testing.assert_array_equal(model.vertices, changed)
            self.assertEqual(len(tool._history_undo_stack), history_size + 1)
            widget.setFocus()
            QApplication.processEvents()
            widget.lineEdit().selectAll()
            QTest.keyClicks(widget.lineEdit(), "0.00")
            tool.membrane_length.setFocus()
            QApplication.processEvents()
            self.assertEqual(model._cb_membrane_state["distortion_level"], 0)
        finally:
            tool.delete()


result = unittest.TextTestRunner(verbosity=2, stream=sys.__stderr__).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(MembraneDistortionTests))
if not result.wasSuccessful():
    raise RuntimeError("Membrane distortion regression checks failed")
