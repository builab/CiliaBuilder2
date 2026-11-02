"""Run in ChimeraX: runscript tests/verify_session_clipping.py."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import weakref

import numpy as np
from chimerax.core.commands import run, StringArg
from chimerax.core.models import Model
from chimerax.map import Volume, volume_from_grid_data
from chimerax.map_data import ArrayGridData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import cmd
from src.draw import build_central_pair_star_rows
from src.source_paths import track_glb_sources
from src.tool import CiliaBuilder2Tool


class SessionClippingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cb-clipping-")
        self.folder = Path(self.temp.name)
        self.before = set(session.models.list())
        self.original_planes = [p.copy() for p in session.main_view.clip_planes.planes()]
        session.main_view.clip_planes.clear()
        track_glb_sources(session)
        self.tool = object.__new__(CiliaBuilder2Tool)
        self.tool._session = weakref.ref(session)
        self.tool._attached_results = {}
        self.tool._cb_attachment_clip_plane_name = "cb_random_start_clip"
        self.tool._cb_attachment_clip_states = None
        self.tool._cb_active_attachment_clip = None
        self.tool.attach_line_rotation = SimpleNamespace(value=lambda: 0)
        self.tool.attach_y_rotation = SimpleNamespace(value=lambda: 0)
        # Only the Qt controls are bypassed; use real save/restore and attachment.
        self.tool._ui_state = lambda: {}
        self.tool._session_selected_state = lambda: {}
        self.tool._apply_ui_state = lambda state: None
        self.tool._restore_session_combo_state = lambda state: None
        self.tool._refresh_model_selectors = lambda: None

    def close_created(self):
        run(session, "wait 1", log=False)
        created = set(session.models.list()) - self.before
        session.models.close([m for m in created if m.parent not in created])
        run(session, "wait 1", log=False)

    def tearDown(self):
        self.close_created()
        session.main_view.clip_planes.replace_planes(self.original_planes)
        self.temp.cleanup()

    def make_attachment(self, extension="mrc", name="central pair"):
        z, y, x = np.indices((20, 20, 20))
        values = np.exp(-((x - 9.5)**2 + (y - 9.5)**2 + (z - 9.5)**2) / 30).astype(np.float32)
        volume = volume_from_grid_data(ArrayGridData(values, name="clip source"), session, show_dialog=False)
        volume.set_parameters(surface_levels=[0.3])
        volume.update_drawings()
        path = self.folder / (name.replace(" ", "_") + "." + extension)
        option = " center false" if extension == "glb" else ""
        run(session, "save %s models #%s%s" % (StringArg.unparse(str(path)), volume.id_string, option))
        session.models.close([volume])
        before = set(session.models.list())
        run(session, "open " + StringArg.unparse(str(path)))
        opened = set(session.models.list()) - before
        source, = [m for m in opened if m.parent not in opened]
        self.tool._store_model_saved_path(source, str(path))
        star = Model(name, session)
        star._cb_star_rows = build_central_pair_star_rows(20, 20, "clip-test", 1)
        cmd._add_to_cb_star_group(session, star)
        self.tool._perform_attachment(star.id_string, source.id_string)
        result = self.tool._last_attached_result
        for model in result.all_models():
            if isinstance(model, Volume):
                model.update_drawings()
        return source, star, result

    def clip_slab(self):
        run(session, "clip front 0 position 0,0,2 axis 0,0,1")
        run(session, "clip back 0 position 0,0,18 axis 0,0,-1")

    def save_payload(self):
        payload = self.tool._session_payload(str(self.folder), "clipped", {})
        path = self.folder / "clipped.json"
        path.write_text(json.dumps(payload))
        return json.loads(path.read_text())

    def assert_can_clip(self, result):
        drawings = [d for d in result.all_drawings() if not hasattr(d, "clip_cap_owner")]
        self.assertTrue(drawings)
        for drawing in drawings:
            self.assertTrue(drawing.allow_clipping, drawing.name)

    def test_front_back_enabled_on_normal_attachment(self):
        for extension in ("mrc", "stl", "glb"):
            with self.subTest(extension=extension):
                _, _, result = self.make_attachment(extension, "normal " + extension)
                self.clip_slab()
                self.assert_can_clip(result)
                run(session, "clip off")

    def test_json_restores_front_back_and_map_attachment(self):
        self.make_attachment()
        self.clip_slab()
        expected = {p.name: np.array(p.opengl_vec4()) for p in session.main_view.clip_planes.planes()}
        payload = self.save_payload()
        self.assertIn("scene_clipping", payload)
        self.close_created()
        run(session, "clip off")
        self.tool._apply_session_payload_to_scene(payload, str(self.folder))
        actual = {p.name: np.array(p.opengl_vec4()) for p in session.main_view.clip_planes.planes()}
        self.assertEqual(set(actual), {"front", "back"})
        for name in expected:
            np.testing.assert_allclose(actual[name], expected[name], atol=1e-7)
        result, = self.tool._attached_results.values()
        self.assertTrue(getattr(result, "_cb_generated_attached", False), "restore reused the source as the attached result")
        self.assert_can_clip(result)
        volume, = [m for m in result.all_models() if isinstance(m, Volume)]
        self.assertEqual(len(volume.positions), 2)
        caps = [d for d in result.all_drawings() if hasattr(d, "clip_cap_owner")]
        self.assertEqual({d.clip_plane_name for d in caps if d.triangles is not None}, {"front", "back"})

    def test_mixed_attachments_and_model_clip_off_survive_reload(self):
        results = []
        for extension in ("mrc", "stl", "glb"):
            _, _, result = self.make_attachment(extension, "mixed " + extension)
            results.append(result)
        self.clip_slab()
        run(session, "clip model #%s false" % results[1].id_string)
        payload = self.save_payload()
        self.close_created()
        self.tool._apply_session_payload_to_scene(payload, str(self.folder))
        self.assertEqual(len(self.tool._attached_results), 3)
        for result in self.tool._attached_results.values():
            self.assertTrue(getattr(result, "_cb_generated_attached", False))
            if result.name.startswith("mixed stl"):
                for drawing in result.all_drawings():
                    if not hasattr(drawing, "clip_cap_owner"):
                        self.assertFalse(drawing.allow_clipping)
            else:
                self.assert_can_clip(result)
        self.assertEqual({p.name for p in session.main_view.clip_planes.planes()}, {"front", "back"})

    def test_explicit_glb_center_and_clipping_survive_reload_together(self):
        # An explicit user center must override the automatic GLB grid anchor.
        fixed_anchor = [2.0, -3.0, 7.0]
        self.tool._attach_fixed_anchor = lambda: fixed_anchor
        _, star, result = self.make_attachment("glb", "fixed center")
        instance, = result.child_models()
        positions = instance.positions.array().copy()
        for position, row in zip(instance.positions, star._cb_star_rows):
            np.testing.assert_allclose(position * np.array(fixed_anchor),
                                       [row["rlnCoordinate" + axis] for axis in "XYZ"], atol=1e-6)
        self.clip_slab()
        payload = self.save_payload()
        self.assertEqual(payload["attachments"][0]["fixed_anchor"], fixed_anchor)
        self.close_created()
        self.tool._apply_session_payload_to_scene(payload, str(self.folder))
        restored, = self.tool._attached_results.values()
        instance, = [m for m in restored.child_models() if not hasattr(m, "clip_cap_owner")]
        np.testing.assert_allclose(instance.positions.array(), positions, atol=1e-6)
        self.assertEqual(restored._cb_attachment_fixed_anchor, fixed_anchor)
        self.assert_can_clip(restored)
        self.assertEqual({p.name for p in session.main_view.clip_planes.planes()}, {"front", "back"})

    def test_clip_off_overrides_recreated_random_start_cut(self):
        _, star, result = self.make_attachment()
        star._cb_random_clip_info = {
            "plane_point": [0, 0, 0], "axis": [0, 0, 1], "spread": 10, "clip_start": 0,
        }
        self.tool._apply_attachment_clip_if_needed(result, star)
        self.clip_slab()
        run(session, "clip off")
        payload = self.save_payload()
        self.assertEqual(payload["scene_clipping"]["planes"], [])
        self.close_created()
        self.tool._apply_session_payload_to_scene(payload, str(self.folder))
        self.assertEqual(session.main_view.clip_planes.planes(), [])

    def test_legacy_json_still_recreates_random_start_cut(self):
        _, star, result = self.make_attachment()
        star._cb_random_clip_info = {
            "plane_point": [0, 0, 3], "axis": [0, 0, 1], "spread": 10, "clip_start": 3,
        }
        self.tool._apply_attachment_clip_if_needed(result, star)
        payload = self.save_payload()
        payload.pop("scene_clipping")
        for field in ("attach_sources", "attachments", "generated_star_models"):
            for item in payload[field]:
                item.pop("clipping_state", None)
        self.close_created()
        run(session, "clip off")
        self.tool._apply_session_payload_to_scene(payload, str(self.folder))
        plane = session.main_view.clip_planes.find_plane("cb_random_start_clip")
        self.assertIsNotNone(plane)
        np.testing.assert_allclose(plane.plane_point, [0, 0, 3])

    def test_plane_geometry_is_scene_fixed_and_front_off_is_saved(self):
        from src.clipping import capture_scene_clipping, restore_scene_clipping
        from chimerax.geometry import rotation

        self.make_attachment()
        run(session, "clip front 0 position 1,2,3 axis 1,2,3")
        run(session, "clip back 0 position 8,10,15 axis -1,-2,-3")
        run(session, "clip front off")
        expected = np.array(session.main_view.clip_planes.find_plane("back").opengl_vec4())
        payload = json.loads(json.dumps(capture_scene_clipping(session.main_view)))
        session.main_view.camera.position = rotation((1, 0, 0), 67) * session.main_view.camera.position
        run(session, "clip off")
        run(session, "view orient")
        restore_scene_clipping(session.main_view, payload)
        self.assertIsNone(session.main_view.clip_planes.find_plane("front"))
        np.testing.assert_allclose(session.main_view.clip_planes.find_plane("back").opengl_vec4(), expected)

    def test_non_model_glb_drawings_are_enabled_and_restored(self):
        from chimerax.graphics import Drawing
        from src.clipping import capture_model_clipping, restore_model_clipping, set_model_clipping

        root = Model("nested GLB", session)
        session.models.add([root])
        child = Drawing("non-model mesh")
        root.add_drawing(child)
        child.allow_clipping = False
        set_model_clipping(root, True)
        self.assertTrue(child.allow_clipping)
        child.allow_clipping = False
        state = json.loads(json.dumps(capture_model_clipping(root)))
        set_model_clipping(root, True)
        restore_model_clipping(root, state)
        self.assertTrue(root.allow_clipping)
        self.assertFalse(child.allow_clipping)


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SessionClippingTests))
if not result.wasSuccessful():
    raise RuntimeError("Clipping/session regression checks failed")
