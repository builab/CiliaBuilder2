"""Run in ChimeraX with: runscript tests/verify_attach_model_center.py"""

import sys
from pathlib import Path

import numpy as np
from chimerax.core.models import Model, Surface
from chimerax.geometry import Place
from chimerax.map import volume_from_grid_data
from chimerax.map_data import ArrayGridData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.map import _shared_source_anchor_local, _zero_volume_origin, cbsubmap_impl


values = np.zeros((4, 6, 8), dtype=np.float32)
values[0, 0, 0] = 100.0  # Density center is deliberately not the grid center.
grid = ArrayGridData(values, origin=(10, 20, 30), step=(2, 3, 4), name="center-test.mrc")
volume = volume_from_grid_data(grid, session, show_dialog=False)
_zero_volume_origin(session, volume)
volume_anchor = _shared_source_anchor_local(session, volume)
assert np.allclose(volume_anchor, [7, 7.5, 6]), f"wrong MRC grid center: {volume_anchor}"

surface = Surface("center-test.stl", session)
vertices = np.array(
    [[100, 0, 0], [110, 0, 0], [110, 20, 0], [100, 20, 0]], dtype=np.float32
)
surface.set_geometry(
    vertices,
    np.tile([0, 0, 1], (4, 1)).astype(np.float32),
    np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
)
session.models.add([surface])
surface_anchor = _shared_source_anchor_local(session, surface)
assert np.allclose(surface_anchor, [105, 10, 0]), (
    f"surface used another model's center: {surface_anchor}"
)
surface.display = False
hidden_surface_anchor = _shared_source_anchor_local(session, surface)
assert np.allclose(hidden_surface_anchor, surface_anchor), (
    f"hidden surface lost its geometry center: {hidden_surface_anchor}"
)
surface.display = True

composite = Model("center-test.glb", session)
session.models.add([composite])
child = Surface("nested colored part", session)
child.set_geometry(
    vertices,
    np.tile([0, 0, 1], (4, 1)).astype(np.float32),
    np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
)
session.models.add([child], parent=composite)
child.position = Place(origin=(20, 30, 0))
composite_anchor = _shared_source_anchor_local(session, composite)
assert np.allclose(composite_anchor, [125, 40, 0]), (
    f"composite GLB did not use its nested geometry center: {composite_anchor}"
)
composite.display = False
hidden_composite_anchor = _shared_source_anchor_local(session, composite)
assert np.allclose(hidden_composite_anchor, composite_anchor), (
    f"hidden composite GLB lost its geometry center: {hidden_composite_anchor}"
)
composite.display = True

star = Model("attachment center test STAR", session)
star._cb_star_rows = [{
    "rlnCoordinateX": 200.0,
    "rlnCoordinateY": 300.0,
    "rlnCoordinateZ": 400.0,
    "rlnImagePixelSize": 1.0,
    "rlnHelicalTubeID": 1,
}]
session.models.add([star])
for source, anchor in (
    (volume, volume_anchor), (surface, surface_anchor), (composite, composite_anchor)
):
    for angle in (0, 45):
        result = cbsubmap_impl(
            session, star, source.id_string, close_source=False, single_big_object=True,
            attach_axis_rot_z_deg=0, attach_all_z_offset_deg=angle,
        )
        placed = list(result.child_models())
        assert len(placed) == 1
        center = list(placed[0].positions)[0] * anchor
        assert np.allclose(center, [200, 300, 400], atol=1e-5), (
            f"{source.name} attached around {center} instead of its geometric center"
        )
        session.models.close([result])

print("MRC, surface, and composite GLB attachments use each source's own geometric center")
