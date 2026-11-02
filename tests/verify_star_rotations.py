"""Run in a fresh ChimeraX: runscript tests/verify_star_rotations.py."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from chimerax.core.models import Model, Surface
from chimerax.geometry import rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import cmd, map as attachment
from src.io import rows_to_star_text
from src.star import ciliabuilder_rows_from_text
from src.tool import CiliaBuilder2Tool


def reference_basis(rot, tilt, psi):
    # RELION/ArtiaX: negative rotations in the order M3 * M2 * M1.
    place = (rotation((0, 0, 1), -psi)
             * rotation((0, 1, 0), -tilt)
             * rotation((0, 0, 1), -rot))
    return place.matrix[:, :3]


def make_row(center, angles, tube=1):
    return dict(zip(
        ("rlnCoordinateX", "rlnCoordinateY", "rlnCoordinateZ",
         "rlnAngleRot", "rlnAngleTilt", "rlnAnglePsi"),
        (*center, *angles),
    ), rlnTomoName="TS_001", rlnImagePixelSize=1.0,
        rlnHelicalTubeID=tube, rlnClassNumber=1)


class BuilderHarness:
    # Exercise the real builder methods without creating a Qt tool window.
    for name in ("_safe_unit_array", "_relion_angles_from_axes", "_row_world_center",
                 "_axes_from_star_row", "_resolved_axes_from_row", "_tube_id_from_row",
                 "_orthogonal_basis_about_axis", "_normalize_angle_delta_deg",
                 "_filament_geometry_for_tube", "_build_substitution_filament_rows",
                 "_continue_outer_star_rows"):
        locals()[name] = getattr(CiliaBuilder2Tool, name)


class StarRotationTests(unittest.TestCase):
    def test_imported_angles_match_relion(self):
        for angles in ((20, 60, -35), (0, 90, 90), (-70, 135, 25), (42, 0, -12)):
            with self.subTest(angles=angles):
                row = ciliabuilder_rows_from_text(rows_to_star_text([make_row((1, 2, 3), angles)]))[0]
                expected = reference_basis(*angles)
                for reader in (cmd._particle_axes_from_row, attachment._particle_axes_from_row):
                    np.testing.assert_allclose(np.column_stack(reader(row)), expected, atol=1e-12)

    def test_axes_to_angles_round_trip_including_poles(self):
        rng = np.random.default_rng(508)
        angles = [(r, t, p) for r, p in rng.uniform(-180, 180, (12, 2))
                  for t in (0, 1e-6, 27, 90, 143, 179.999999, 180)]
        builder = BuilderHarness()
        for triplet in angles:
            with self.subTest(angles=triplet):
                basis = reference_basis(*triplet)
                recovered = builder._relion_angles_from_axes(*basis.T)
                np.testing.assert_allclose(reference_basis(*recovered), basis, atol=1e-10)

    def test_arrows_are_rigid_and_follow_the_axis(self):
        pairs = [((0, 0, 1), (0.1, 0.3, 1)), ((0, 0, 1), (1, 2, -0.4)),
                 ((0, 0, 1), (0, 0, -1)), ((1, 2, 3), (-1, -2, -3)),
                 ((0, 0, 1), (1e-7, 0, 1))]
        for before, after in pairs:
            before = np.array(before, dtype=float)
            after = np.array(after, dtype=float)
            before /= np.linalg.norm(before)
            after /= np.linalg.norm(after)
            for helper in (cmd._rotation_align_vector_to_vector, attachment._rotation_align_vector_to_vector):
                with self.subTest(helper=helper.__module__, target=after):
                    matrix = helper(before, after)
                    np.testing.assert_allclose(matrix @ before, after, atol=1e-10)
                    np.testing.assert_allclose(matrix.T @ matrix, np.eye(3), atol=1e-10)
                    self.assertAlmostEqual(np.linalg.det(matrix), 1.0)

    def test_export_preserves_explicit_axes(self):
        basis = reference_basis(34, 57, -83)
        row = make_row((4, 5, 6), (0, 0, 0))
        row.update({"_cbAxis" + name: axis.tolist() for name, axis in zip("XYZ", basis.T)})
        restored = ciliabuilder_rows_from_text(rows_to_star_text([row]))[0]
        np.testing.assert_allclose(np.column_stack(attachment._particle_axes_from_row(restored)), basis, atol=1e-7)
        # Serialization must not modify the live row or its cached axes.
        self.assertEqual(row["rlnAngleTilt"], 0)

    def test_builders_honor_cached_axes_from_older_sessions(self):
        builder = BuilderHarness()
        basis = reference_basis(-17, 108, 62)
        source = SimpleNamespace(_cb_star_rows=[])
        for distance in (0, 30, 60):
            row = make_row(basis[:, 2] * distance, (0, 0, 0))
            row.update({"_cbAxis" + a: axis.tolist() for a, axis in zip("XYZ", basis.T)})
            source._cb_star_rows.append(row)
            np.testing.assert_allclose(np.column_stack(builder._axes_from_star_row(row)), basis, atol=1e-12)
        continued, _, _ = builder._continue_outer_star_rows(source, 60, 30)
        for row in continued:
            np.testing.assert_allclose(reference_basis(*(row["rlnAngle" + a] for a in ("Rot", "Tilt", "Psi"))), basis, atol=1e-12)

    def test_rendered_arrow_geometry_keeps_its_shape_when_tilted(self):
        center = np.array([20, -30, 40])
        basis = reference_basis(37, 63, -28)
        neutral = Model("neutral STAR arrows", session)
        tilted = Model("tilted STAR arrows", session)
        session.models.add([neutral, tilted])
        try:
            cmd._render_star_model(session, neutral, [make_row((0, 0, 0), (0, 0, 0))], True)
            cmd._render_star_model(session, tilted, [make_row(center, (37, 63, -28))], True)
            neutral_arrows = [m for m in neutral.child_models() if isinstance(m, Surface)]
            tilted_arrows = [m for m in tilted.child_models() if isinstance(m, Surface)]
            self.assertEqual(len(tilted_arrows), 3)
            for i, (before, after) in enumerate(zip(neutral_arrows, tilted_arrows)):
                before_vertices = np.array(before.vertices, dtype=float)
                after_vertices = np.array(after.vertices, dtype=float) - center
                before_axis = np.eye(3)[:, i]
                after_axis = basis[:, i]
                before_axial = before_vertices @ before_axis
                after_axial = after_vertices @ after_axis
                np.testing.assert_allclose(after_axial, before_axial, atol=1e-5)
                before_radial = np.linalg.norm(before_vertices - before_axial[:, None] * before_axis, axis=1)
                after_radial = np.linalg.norm(after_vertices - after_axial[:, None] * after_axis, axis=1)
                np.testing.assert_allclose(after_radial, before_radial, atol=1e-5)
        finally:
            session.models.close([neutral, tilted])

    def test_generated_tilted_rows_survive_export(self):
        builder = BuilderHarness()
        basis = reference_basis(23, 67, -39)
        axis = basis[:, 2]
        source = SimpleNamespace(_cb_star_rows=[make_row(axis * d, (23, 67, -39)) for d in (0, 30, 60)])
        substituted = builder._build_substitution_filament_rows(source, 1, 90, 30, 0, 17)
        continued, _, _ = builder._continue_outer_star_rows(source, 90, 30)
        for rows in (substituted, continued):
            restored = ciliabuilder_rows_from_text(rows_to_star_text(rows))
            for live, loaded in zip(rows, restored):
                expected = np.column_stack([live["_cbAxis" + a] for a in "XYZ"])
                np.testing.assert_allclose(reference_basis(*(live["rlnAngle" + a] for a in ("Rot", "Tilt", "Psi"))), expected, atol=1e-10)
                np.testing.assert_allclose(np.column_stack(attachment._particle_axes_from_row(loaded)), expected, atol=1e-7)
                np.testing.assert_allclose(expected[:, 2], axis, atol=1e-10)

    def test_attachment_follows_each_curved_star_orientation(self):
        star = Model("rotation regression STAR", session)
        star._cb_star_rows = [make_row((100 * np.sin(a), 0, 100 * np.cos(a)), (31, t, -22))
                             for a, t in zip(np.linspace(0, 1.2, 6), (0, 15, 30, 45, 60, 75))]
        session.models.add([star])
        surface = Surface("rotation regression source", session)
        vertices = np.array([[-3, -2, -5], [3, -2, -5], [0, 2, -5], [0, 0, 5]], dtype=np.float32)
        surface.set_geometry(vertices, None, np.array([[0, 1, 2], [0, 1, 3], [1, 2, 3], [2, 0, 3]], dtype=np.int32))
        session.models.add([surface])
        result = None
        try:
            result = attachment.cbsubmap_impl(session, star, surface.id_string, close_source=False,
                single_big_object=True, rotate_xy_90=True, attach_axis_rot_z_deg=-90)
            child, = result.child_models()
            for row, place in zip(star._cb_star_rows, child.positions):
                expected = reference_basis(*(row["rlnAngle" + a] for a in ("Rot", "Tilt", "Psi")))
                np.testing.assert_allclose(place.matrix[:, :3], expected, atol=1e-7)
                np.testing.assert_allclose(place * np.zeros(3), [row["rlnCoordinate" + a] for a in "XYZ"], atol=1e-5)
        finally:
            session.models.close([m for m in (result, surface, star) if m is not None])

    def test_offset_follows_local_tangent_on_a_bent_filament(self):
        star = Model("bent filament regression STAR", session)
        parameters = np.linspace(0, 1.3, 6)
        centers = 100 * np.array([[np.sin(a), 0, np.cos(a)] for a in parameters])
        star._cb_star_rows = [make_row(center, (17, 90 + np.degrees(a), 180))
                             for center, a in zip(centers, parameters)]
        session.models.add([star])
        surface = Surface("bent filament test source", session)
        vertices = np.array([[-3, -2, 0], [3, -2, 0], [3, 2, 0], [-3, 2, 0]], dtype=np.float32)
        surface.set_geometry(vertices, None, np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32))
        session.models.add([surface])
        result = None
        try:
            result = attachment.cbsubmap_impl(session, star, surface.id_string, close_source=False,
                single_big_object=True, rotate_xy_90=True, attach_axis_rot_z_deg=-90,
                attach_all_z_offset_deg=38, attach_axis_rot_y_deg=-23)
            child, = result.child_models()
            for i, (row, place) in enumerate(zip(star._cb_star_rows, child.positions)):
                tangent = centers[min(i + 1, len(centers) - 1)] - centers[max(i - 1, 0)]
                basis = reference_basis(*(row["rlnAngle" + a] for a in ("Rot", "Tilt", "Psi")))
                expected = rotation(tangent, 38).matrix[:, :3] @ basis @ rotation((0, 1, 0), -23).matrix[:, :3]
                np.testing.assert_allclose(place.matrix[:, :3], expected, atol=1e-7)
                np.testing.assert_allclose(place * np.zeros(3), centers[i], atol=1e-5)
        finally:
            session.models.close([m for m in (result, surface, star) if m is not None])


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StarRotationTests))
if not result.wasSuccessful():
    raise RuntimeError("STAR rotation regression checks failed")
