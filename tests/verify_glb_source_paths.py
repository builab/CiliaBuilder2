"""Run in ChimeraX: runscript tests/verify_glb_source_paths.py."""

import gzip
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import weakref

import numpy as np
from chimerax.core.commands import run, StringArg
from chimerax.core.models import Model, Surface
from chimerax.gltf.gltf import write_gltf
from chimerax.geometry import translation, rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import cmd
from src.draw import build_central_pair_star_rows
from src.map import cbsubmap_impl, _copy_source_instance
from src.source_paths import original_glb_path, track_glb_sources
from src.tool import CiliaBuilder2Tool


class GlbSourcePathTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        self.temp = tempfile.TemporaryDirectory(prefix="cb-glb-source-")
        self.folder = Path(self.temp.name)
        self.tool = object.__new__(CiliaBuilder2Tool)
        self.tool._session = weakref.ref(session)
        self.tool._attached_results = {}
        track_glb_sources(session)

        composite = Model("composite source", session)
        for index in range(2):
            mesh = Surface("part %d" % index, session)
            vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=np.float32)
            vertices[:, 2] += index * 20
            mesh.set_geometry(vertices, None, np.array([[0, 1, 2]], dtype=np.int32))
            mesh.color = (220, 30 + index * 100, 45, 255)
            composite.add([mesh])
        session.models.add([composite])
        self.glb = self.folder / "source [two parts].glb"
        write_gltf(session, filename=str(self.glb), models=[composite])
        session.models.close([composite])
        self.gz = Path(str(self.glb) + ".gz")
        with gzip.open(self.gz, "wb") as stream:
            stream.write(self.glb.read_bytes())

    def tearDown(self):
        session.models.close([model for model in session.models.list() if model not in self.before])
        self.temp.cleanup()

    def open_source(self, path, log=True):
        before = set(session.models.list())
        run(session, "open " + StringArg.unparse(str(path)), log=log)
        opened = set(session.models.list()) - before
        roots = [model for model in opened if model.parent not in opened]
        self.assertEqual(len(roots), 1)
        return roots[0]

    def test_plain_and_gz_json_reference_original_and_reopen(self):
        for path in (self.glb, self.gz):
            with self.subTest(path=path.name):
                original_bytes = path.read_bytes()
                source = self.open_source(path)
                self.assertEqual(source.name, self.glb.name)
                self.assertEqual(original_glb_path(source), str(path))
                self.assertEqual(len([m for m in source.all_models() if getattr(m, "vertices", None) is not None]), 2)

                star = Model("source path STAR", session)
                star._cb_star_rows = build_central_pair_star_rows(30, 30, "TS_001", 1)
                cmd._add_to_cb_star_group(session, star)
                attached = cbsubmap_impl(session, star, source.id_string, close_source=False, single_big_object=True)
                self.tool._archive_attach_source_model(source)
                attached._cb_attachment_source_ref = source.id_string
                attached._cb_attachment_star_ref = star.id_string
                self.tool._attached_results = {(id(star), id(source)): attached}

                save_dir = self.folder / "json output"
                save_dir.mkdir(exist_ok=True)
                cache = {}
                payload = {
                    "attach_sources": self.tool._attach_source_models_state(str(save_dir), "scene", cache),
                    "attachments": self.tool._attachment_models_state(str(save_dir), "scene", cache),
                }
                json_path = save_dir / "scene.json"
                json_path.write_text(json.dumps(payload))
                payload = json.loads(json_path.read_text())
                self.assertEqual(len(payload["attach_sources"]), 1)
                self.assertEqual(payload["attach_sources"][0]["path"], str(path))
                self.assertEqual(payload["attachments"][0]["map_path"], str(path))
                self.assertEqual(list(save_dir.iterdir()), [json_path])
                self.assertEqual(path.read_bytes(), original_bytes)

                session.models.close([attached, source])
                restored = self.tool._open_saved_source_item(payload["attach_sources"][0], str(save_dir))
                self.assertEqual(restored.name, self.glb.name)
                self.assertEqual(original_glb_path(restored), str(path))
                result = cbsubmap_impl(session, star, restored.id_string, close_source=False, single_big_object=True)
                child, = result.child_models()
                self.assertEqual(len(child.positions), 2)
                self.assertEqual(len([m for m in child.all_models() if getattr(m, "vertices", None) is not None]), 2)
                session.models.close([result, restored, star])

    def test_renaming_does_not_lose_the_original_path(self):
        source = self.open_source(self.gz)
        source.name = "my custom source name"
        self.assertEqual(self.tool._session_model_path(source, str(self.folder), "new_session", {}), str(self.gz))
        self.assertEqual(source.name, "my custom source name")

    def test_glb_export_preserves_scene_position(self):
        source = self.open_source(self.glb)
        source.position = translation((170, -250, 430)) * rotation((1, 2, 3), 37)
        expected = source.bounds()
        path = self.folder / "off-origin export.glb"
        self.tool._export_live_model_copy_for_session(source, str(path), ".glb")
        restored = self.open_source(path)
        np.testing.assert_allclose(restored.bounds().xyz_min, expected.xyz_min, atol=1e-4)
        np.testing.assert_allclose(restored.bounds().xyz_max, expected.xyz_max, atol=1e-4)

    def test_temporary_glb_export_preserves_scene_position(self):
        source = self.open_source(self.glb)
        del source._cb_original_source_path
        source.name = "in-memory GLB without source path"
        source.position = translation((170, -250, 430)) * rotation((1, 2, 3), 37)
        expected = source.bounds()
        copied = _copy_source_instance(session, source)
        self.assertIsNotNone(copied)
        np.testing.assert_allclose(copied.bounds().xyz_min, expected.xyz_min, atol=1e-4)
        np.testing.assert_allclose(copied.bounds().xyz_max, expected.xyz_max, atol=1e-4)
        temp_path = getattr(copied, "_cb_temp_copy_path", None)
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

    def test_recover_preexisting_model_from_unique_history_entry(self):
        source = self.open_source(self.gz, log=False)
        previous = getattr(session, "file_history", None)
        session.file_history = SimpleNamespace(files=[
            SimpleNamespace(path=str(self.glb), database=None),
            SimpleNamespace(path=str(self.gz), database=None),
        ])
        try:
            self.assertEqual(self.tool._session_model_path(source, str(self.folder), "scene", {}), str(self.gz))
        finally:
            session.file_history = previous

    def test_different_files_with_same_basename_stay_distinct(self):
        other_dir = self.folder / "second"
        other_dir.mkdir()
        other = other_dir / self.gz.name
        other.write_bytes(self.gz.read_bytes())
        first, second = self.open_source(self.gz), self.open_source(other)
        self.assertEqual(original_glb_path(first), str(self.gz))
        self.assertEqual(original_glb_path(second), str(other))


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GlbSourcePathTests))
if not result.wasSuccessful():
    raise RuntimeError("GLB source-path regression checks failed")
