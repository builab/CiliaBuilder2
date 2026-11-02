"""ChimeraX: runscript tests/verify_glb_volume_anchor.py.

Set CB_TEST_EMDB_2132=1 to include the user's real EMDB export/attach case.
"""

import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import weakref

import numpy as np
from chimerax.core.commands import run, StringArg
from chimerax.core.models import Model
from chimerax.gltf.gltf import write_gltf
from chimerax.map import volume_from_grid_data, Volume
from chimerax.map_data import ArrayGridData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.draw import build_cilia_lines_star_rows
from src.glb_anchor import _meshes, read_glb_anchor, volume_glb_anchor
from src.map import cbsubmap_impl
from src.source_paths import track_glb_sources
from src.tool import CiliaBuilder2Tool


class GlbVolumeAnchorTests(unittest.TestCase):
    def setUp(self):
        self.before = set(session.models.list())
        self.temp = tempfile.TemporaryDirectory(prefix="cb-volume-glb-")
        self.folder = Path(self.temp.name)
        track_glb_sources(session)
        self.tool = object.__new__(CiliaBuilder2Tool)
        self.tool._session = weakref.ref(session)
        self.tool._attached_results = {}

    def tearDown(self):
        session.models.close([m for m in session.models.list() if m not in self.before])
        self.temp.cleanup()

    def volume(self):
        z, y, x = np.indices((20, 24, 28))
        values = np.exp(-((x - 8) ** 2 / 12 + (y - 15) ** 2 / 30 + (z - 7) ** 2 / 20)).astype(np.float32)
        grid = ArrayGridData(values, origin=(13, -31, 47), step=(2, 3, 4), name="off-center density")
        volume = volume_from_grid_data(grid, session, show_dialog=False)
        volume.set_parameters(surface_levels=[0.3])
        volume.update_drawings()
        return volume

    def open_glb(self, path):
        before = set(session.models.list())
        run(session, "open " + StringArg.unparse(str(path)))
        opened = set(session.models.list()) - before
        root, = [m for m in opened if m.parent not in opened]
        return root

    def save_glb(self, volume, name="export.glb", command=True):
        path = self.folder / name
        if command:
            before = set(session.models.list())
            run(session, "save %s models #%s center false" % (StringArg.unparse(str(path)), volume.id_string))
            self.assertEqual(set(session.models.list()), before)
        else:
            # Old exports have no CiliaBuilder center metadata.
            write_gltf(session, filename=str(path), models=[volume], center=False)
        return path

    def assert_overlap(self, volume, glb):
        max_error = 0.0
        for angle in (0, 43):
            roots = []
            stars = []
            for source in (volume, glb):
                star = Model("identical microtubule build", session)
                star._cb_star_rows = build_cilia_lines_star_rows(9, 1000, 1000, 960, "test", 1)
                session.models.add([star])
                stars.append(star)
                result = cbsubmap_impl(
                    session, star, source.id_string, close_source=False,
                    single_big_object=True, rotate_xy_90=True,
                    attach_all_z_offset_deg=angle, attach_axis_rot_y_deg=21,
                )
                roots.append(result)
            first, = roots[0].child_models()
            second, = roots[1].child_models()
            first.update_drawings()
            meshes_a, meshes_b = _meshes(first), _meshes(second)
            self.assertEqual(len(meshes_a), len(meshes_b))
            self.assertGreater(len(meshes_a), 0)
            self.assertEqual(len(first.positions), 18)
            self.assertEqual(len(first.positions), len(second.positions))
            for (va, ta, pa), (vb, tb, pb) in zip(meshes_a, meshes_b):
                np.testing.assert_array_equal(ta, tb)
                for position_a, position_b in zip(first.positions, second.positions):
                    # Compare actual mesh vertices, not just chosen anchor points.
                    error = float(np.max(np.abs((position_a * pa) * va - (position_b * pb) * vb)))
                    max_error = max(max_error, error)
                    self.assertLess(error, 0.002)
            session.models.close(roots + stars)
        print("Volume/GLB attachment maximum vertex error: %.8f Angstrom" % max_error)

    def test_export_attachments_overlap_and_metadata_survives_without_volume(self):
        volume = self.volume()
        center = np.array(volume.center())
        path = self.save_glb(volume)
        np.testing.assert_allclose(read_glb_anchor(path), center, atol=1e-4)
        glb = self.open_glb(path)
        self.assert_overlap(volume, glb)
        session.models.close([volume, glb])
        gz = Path(str(path) + ".gz")
        with gzip.open(gz, "wb") as stream:
            stream.write(path.read_bytes())
        restored = self.open_glb(gz)
        np.testing.assert_allclose(volume_glb_anchor(session, restored), center, atol=1e-4)
        # A re-export must not lose the pivot after the original map is closed.
        exported_again = self.save_glb(restored, "second.glb")
        np.testing.assert_allclose(read_glb_anchor(exported_again), center, atol=1e-4)

    def test_old_export_recovers_exact_mesh_match_and_json_preserves_it(self):
        volume = self.volume()
        center = np.array(volume.center())
        path = self.save_glb(volume, command=False)
        original_bytes = path.read_bytes()
        self.assertIsNone(read_glb_anchor(path))
        glb = self.open_glb(path)
        self.assert_overlap(volume, glb)
        # Session export now includes only sources archived under CiliaBuilder2.
        self.assertEqual(self.tool._attach_source_models_state(str(self.folder), "test", {}), [])
        from src.cmd import _add_to_cb_map_group
        _add_to_cb_map_group(session, glb)
        records = self.tool._attach_source_models_state(str(self.folder), "test", {})
        record, = [r for r in records if r.get("path") == str(path)]
        record = json.loads(json.dumps(record))
        np.testing.assert_allclose(record["glb_volume_anchor"], center, atol=1e-4)
        self.assertEqual(path.read_bytes(), original_bytes)
        session.models.close([volume, glb])
        self.tool._restore_attach_source_models([record], str(self.folder))
        restored = self.tool._find_model_by_path(str(path))
        np.testing.assert_allclose(volume_glb_anchor(session, restored), center, atol=1e-4)

    def test_unrelated_geometry_does_not_borrow_volume_center(self):
        volume = self.volume()
        path = self.save_glb(volume, command=False)
        glb = self.open_glb(path)
        mesh = next(m for m in glb.all_models() if m.vertices is not None)
        vertices = mesh.vertices.copy()
        vertices[len(vertices) // 2, 0] += 2
        mesh.set_geometry(vertices, mesh.normals, mesh.triangles)
        self.assertIsNone(volume_glb_anchor(session, glb))

    def test_ambiguous_grid_centers_are_not_guessed(self):
        first = self.volume()
        path = self.save_glb(first, command=False)
        second = self.volume()
        # Change the second grid's padding without changing its surface.
        second.center = lambda: np.asarray(first.center()) + (10, 0, 0)
        glb = self.open_glb(path)
        self.assertIsNone(volume_glb_anchor(session, glb))

    @unittest.skipUnless(os.environ.get("CB_TEST_EMDB_2132"), "opt-in EMDB download")
    def test_emdb_2132(self):
        before = set(session.models.list())
        run(session, "open emdb:2132")
        volume, = [m for m in session.models.list(type=Volume) if m not in before]
        volume.update_drawings()
        path = self.folder / "test.glb"
        run(session, "save %s center false" % StringArg.unparse(str(path)))
        glb = self.open_glb(path)
        self.assert_overlap(volume, glb)


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GlbVolumeAnchorTests))
if not result.wasSuccessful():
    raise RuntimeError("GLB/volume center regression checks failed")
