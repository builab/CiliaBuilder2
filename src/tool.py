# vim: set expandtab shiftwidth=4 softtabstop=4:

import math

from chimerax.core.tools import ToolInstance
from chimerax.core.commands import run as _run


class CiliaBuilder2Tool(ToolInstance):
    SESSION_ENDURING = True

    def __init__(self, session, tool_name):
        super().__init__(session, tool_name)

        self.display_name = tool_name

        self._last_outer_end_z_ang = None
        self._last_cent_end_z_ang = None

        self._last_outer_star_model = None
        self._last_cent_star_model = None

        self.tool_window = None
        self._build_ui()

    def _build_ui(self):
        from Qt.QtWidgets import (
            QWidget,
            QVBoxLayout,
            QHBoxLayout,
            QScrollArea,
            QGroupBox,
            QLabel,
            QDoubleSpinBox,
            QSpinBox,
            QComboBox,
            QPushButton,
            QCheckBox,
        )
        from chimerax.ui import MainToolWindow

        class RefreshingComboBox(QComboBox):
            def __init__(self, refresh_cb, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._refresh_cb = refresh_cb

            def showPopup(self):
                try:
                    self._refresh_cb()
                except Exception:
                    pass
                super().showPopup()

        self.tool_window = MainToolWindow(self)
        parent = self.tool_window.ui_area

        if parent.layout() is None:
            parent.setLayout(QVBoxLayout())

        main = QWidget(parent)
        main_layout = QVBoxLayout(main)

        panels = QVBoxLayout()
        main_layout.addLayout(panels)

        # Microtubules panel
        outer_box = QGroupBox("Microtubules", main)
        outer_layout = QVBoxLayout(outer_box)

        def outer_row_spin(label, spin):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(spin)
            outer_layout.addWidget(w)

        self.angle_set = QDoubleSpinBox(main)
        self.angle_set.setRange(-360.0, 360.0)
        self.angle_set.setDecimals(2)
        self.angle_set.setValue(0.0)
        outer_row_spin("Angle of set (deg)", self.angle_set)

        self.length = QDoubleSpinBox(main)
        self.length.setRange(0.0, 1e9)
        self.length.setDecimals(2)
        self.length.setValue(9000.0)
        outer_row_spin("Length", self.length)

        self.n_doublet = QSpinBox(main)
        self.n_doublet.setRange(1, 9)
        self.n_doublet.setValue(9)
        outer_row_spin("No. of doublet", self.n_doublet)

        self.radius = QDoubleSpinBox(main)
        self.radius.setRange(0.0, 1e9)
        self.radius.setDecimals(2)
        self.radius.setValue(700.0)
        outer_row_spin("Radius", self.radius)

        self.spacing = QDoubleSpinBox(main)
        self.spacing.setRange(0.0, 1e9)
        self.spacing.setDecimals(2)
        self.spacing.setValue(400.0)
        outer_row_spin("Periodicity (spacing)", self.spacing)

        self.doublet_offset = QDoubleSpinBox(main)
        self.doublet_offset.setRange(-360.0, 360.0)
        self.doublet_offset.setDecimals(2)
        self.doublet_offset.setValue(0.0)
        outer_row_spin("Z offset", self.doublet_offset)

        rand_row = QWidget(main)
        rand_lay = QHBoxLayout(rand_row)
        rand_lay.setContentsMargins(0, 0, 0, 0)
        rand_lay.addWidget(QLabel("Random", rand_row))
        self.random_enable = QCheckBox("Enable", rand_row)
        rand_lay.addWidget(self.random_enable)
        rand_lay.addWidget(QLabel("Max diff", rand_row))
        self.random_max_diff = QDoubleSpinBox(rand_row)
        self.random_max_diff.setRange(0.0, 1e9)
        self.random_max_diff.setDecimals(2)
        self.random_max_diff.setValue(0.0)
        rand_lay.addWidget(self.random_max_diff)
        outer_layout.addWidget(rand_row)

        panels.addWidget(outer_box)

        # Central apparatus panel
        cent_box = QGroupBox("Central apparatus", main)
        cent_layout = QVBoxLayout(cent_box)

        def cent_row_spin(label, spin):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(spin)
            cent_layout.addWidget(w)

        self.centriole_length = QDoubleSpinBox(main)
        self.centriole_length.setRange(0.0, 1e9)
        self.centriole_length.setDecimals(2)
        self.centriole_length.setValue(2000.0)
        cent_row_spin("Length", self.centriole_length)

        self.centriole_spacing = QDoubleSpinBox(main)
        self.centriole_spacing.setRange(0.0, 1e9)
        self.centriole_spacing.setDecimals(2)
        self.centriole_spacing.setValue(400.0)
        cent_row_spin("Periodicity (spacing)", self.centriole_spacing)

        self.centriole_z_offset = QDoubleSpinBox(main)
        self.centriole_z_offset.setRange(-1e9, 1e9)
        self.centriole_z_offset.setDecimals(2)
        self.centriole_z_offset.setValue(0.0)
        cent_row_spin("Z offset", self.centriole_z_offset)

        self.centriole_tube_id = QSpinBox(main)
        self.centriole_tube_id.setRange(1, 999999)
        self.centriole_tube_id.setValue(100)
        cent_row_spin("Tube id", self.centriole_tube_id)

        panels.addWidget(cent_box)

        # IFT panel
        ift_box = QGroupBox("IFT particles", main)
        ift_layout = QVBoxLayout(ift_box)

        def ift_row_spin(label, spin):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(spin)
            ift_layout.addWidget(w)

        ift_origin_row = QWidget(main)
        ift_origin_lay = QHBoxLayout(ift_origin_row)
        ift_origin_lay.setContentsMargins(0, 0, 0, 0)
        ift_origin_lay.addWidget(QLabel("Origin model", ift_origin_row))
        self.ift_origin_model = RefreshingComboBox(self._refresh_model_selectors, ift_origin_row)
        self.ift_origin_model.setMinimumContentsLength(24)
        self.ift_origin_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        ift_origin_lay.addWidget(self.ift_origin_model, 1)
        ift_layout.addWidget(ift_origin_row)

        self.ift_count = QSpinBox(main)
        self.ift_count.setRange(1, 1000000)
        self.ift_count.setValue(100)
        ift_row_spin("No. of particles", self.ift_count)

        self.ift_distance = QDoubleSpinBox(main)
        self.ift_distance.setRange(-1e9, 1e9)
        self.ift_distance.setDecimals(2)
        self.ift_distance.setValue(100.0)
        ift_row_spin("Distance from model", self.ift_distance)

        self.ift_z_offset = QDoubleSpinBox(main)
        self.ift_z_offset.setRange(-1e9, 1e9)
        self.ift_z_offset.setDecimals(2)
        self.ift_z_offset.setValue(0.0)
        ift_row_spin("Z offset", self.ift_z_offset)

        ift_line_row = QWidget(main)
        ift_line_lay = QHBoxLayout(ift_line_row)
        ift_line_lay.setContentsMargins(0, 0, 0, 0)
        ift_line_lay.addWidget(QLabel("Line mode", ift_line_row))
        self.ift_line_mode = QCheckBox("One by one", ift_line_row)
        ift_line_lay.addWidget(self.ift_line_mode)
        ift_line_lay.addStretch(1)
        ift_layout.addWidget(ift_line_row)

        panels.addWidget(ift_box)

        pixel_row = QWidget(main)
        pixel_lay = QHBoxLayout(pixel_row)
        pixel_lay.setContentsMargins(0, 0, 0, 0)
        pixel_lay.addWidget(QLabel("Pixel size (A/px)", pixel_row))
        self.pixel_size = QDoubleSpinBox(pixel_row)
        self.pixel_size.setRange(1e-6, 1e9)
        self.pixel_size.setDecimals(6)
        self.pixel_size.setValue(10.0)
        pixel_lay.addWidget(self.pixel_size)
        pixel_lay.addStretch(1)
        main_layout.addWidget(pixel_row)

        # Buttons
        btn_row = QWidget(main)
        btn_lay = QVBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)

        build_outer_btn = QPushButton("Build microtubules", btn_row)
        build_outer_btn.clicked.connect(lambda: self._build_outer(continue_mode=False))
        btn_lay.addWidget(build_outer_btn)

        cont_outer_btn = QPushButton("Continue microtubules", btn_row)
        cont_outer_btn.clicked.connect(lambda: self._build_outer(continue_mode=True))
        btn_lay.addWidget(cont_outer_btn)

        build_cent_btn = QPushButton("Build central apparatus", btn_row)
        build_cent_btn.clicked.connect(self._build_centriole)
        btn_lay.addWidget(build_cent_btn)

        build_ift_btn = QPushButton("Build IFT", btn_row)
        build_ift_btn.clicked.connect(self._build_ift)
        btn_lay.addWidget(build_ift_btn)
        btn_lay.addStretch(1)

        main_layout.addWidget(btn_row)

        # Selection-based attachment controls
        attach_select = QGroupBox("Attach by selected/open models", main)
        attach_select_lay = QVBoxLayout(attach_select)

        star_row = QWidget(main)
        star_lay = QHBoxLayout(star_row)
        star_lay.setContentsMargins(0, 0, 0, 0)
        star_lay.addWidget(QLabel("STAR model", star_row))
        self.sel_star_model = RefreshingComboBox(self._refresh_model_selectors, star_row)
        self.sel_star_model.setMinimumContentsLength(24)
        self.sel_star_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        star_lay.addWidget(self.sel_star_model, 1)
        attach_select_lay.addWidget(star_row)

        map_row = QWidget(main)
        map_lay = QHBoxLayout(map_row)
        map_lay.setContentsMargins(0, 0, 0, 0)
        map_lay.addWidget(QLabel("Map model", map_row))
        self.sel_map_model = RefreshingComboBox(self._refresh_model_selectors, map_row)
        self.sel_map_model.setMinimumContentsLength(24)
        self.sel_map_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        map_lay.addWidget(self.sel_map_model, 1)
        attach_select_lay.addWidget(map_row)

        sel_btn_row = QWidget(main)
        sel_btn_lay = QHBoxLayout(sel_btn_row)
        sel_btn_lay.setContentsMargins(0, 0, 0, 0)
        self.attach_selected_btn = QPushButton("Attach selected STAR + map", sel_btn_row)
        self.attach_selected_btn.clicked.connect(self._attach_selected_models)
        sel_btn_lay.addWidget(self.attach_selected_btn)
        sel_btn_lay.addStretch(1)
        attach_select_lay.addWidget(sel_btn_row)

        main_layout.addWidget(attach_select)

        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setWidget(main)
        parent.layout().addWidget(scroll)

        self.tool_window.manage(placement="side")
        self.tool_window.shown = True
        try:
            _run(self.session, "ui tool show Models")
        except Exception:
            pass
        self._refresh_model_selectors()

    def _top_level_id(self, model):
        mid = getattr(model, "id", None)
        if not mid:
            return None
        try:
            return int(mid[0])
        except Exception:
            return None

    def _top_level_model_by_id(self, model_id):
        try:
            want = int(model_id)
        except Exception:
            return None
        for m in self.session.models.list():
            tid = self._top_level_id(m)
            if tid is not None and tid == want:
                return m
        return None

    def _refresh_model_selectors(self):
        star_current = self.sel_star_model.currentData() if hasattr(self, "sel_star_model") else None
        map_current = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
        ift_origin_current = self.ift_origin_model.currentData() if hasattr(self, "ift_origin_model") else None
        star_has_models = False
        map_has_models = False
        star_items = []

        if hasattr(self, "sel_star_model"):
            self.sel_star_model.blockSignals(True)
            self.sel_star_model.clear()
            self.sel_star_model.addItem("No STAR models", None)
            for m in self.session.models.list():
                tid = self._top_level_id(m)
                if tid is None or not hasattr(m, "_cb_star_rows"):
                    continue
                label = f"{m.name} (#{tid})"
                star_items.append((label, int(tid)))
                self.sel_star_model.addItem(label, int(tid))
                star_has_models = True
            if star_current is not None:
                idx = self.sel_star_model.findData(int(star_current))
                if idx >= 0:
                    self.sel_star_model.setCurrentIndex(idx)
                else:
                    self.sel_star_model.setCurrentIndex(1 if self.sel_star_model.count() > 1 else 0)
            else:
                self.sel_star_model.setCurrentIndex(1 if self.sel_star_model.count() > 1 else 0)
            self.sel_star_model.setEnabled(star_has_models)
            self.sel_star_model.blockSignals(False)

        if hasattr(self, "sel_map_model"):
            self.sel_map_model.blockSignals(True)
            self.sel_map_model.clear()
            self.sel_map_model.addItem("No map models", None)
            for m in self.session.models.list():
                tid = self._top_level_id(m)
                if tid is None or not self._is_volume_like(m):
                    continue
                label = f"{m.name} (#{tid})"
                self.sel_map_model.addItem(label, int(tid))
                map_has_models = True
            if map_current is not None:
                idx = self.sel_map_model.findData(int(map_current))
                if idx >= 0:
                    self.sel_map_model.setCurrentIndex(idx)
                else:
                    self.sel_map_model.setCurrentIndex(1 if self.sel_map_model.count() > 1 else 0)
            else:
                self.sel_map_model.setCurrentIndex(1 if self.sel_map_model.count() > 1 else 0)
            self.sel_map_model.setEnabled(map_has_models)
            self.sel_map_model.blockSignals(False)

        if hasattr(self, "ift_origin_model"):
            self.ift_origin_model.blockSignals(True)
            self.ift_origin_model.clear()
            self.ift_origin_model.addItem("No origin models", None)
            for label, tid in star_items:
                self.ift_origin_model.addItem(label, int(tid))
            if ift_origin_current is not None:
                idx = self.ift_origin_model.findData(int(ift_origin_current))
                if idx >= 0:
                    self.ift_origin_model.setCurrentIndex(idx)
                else:
                    self.ift_origin_model.setCurrentIndex(1 if self.ift_origin_model.count() > 1 else 0)
            else:
                self.ift_origin_model.setCurrentIndex(1 if self.ift_origin_model.count() > 1 else 0)
            self.ift_origin_model.setEnabled(bool(star_items))
            self.ift_origin_model.blockSignals(False)

        if hasattr(self, "attach_selected_btn"):
            self.attach_selected_btn.setEnabled(star_has_models and map_has_models)

    def _select_star_model(self, model):
        self._refresh_model_selectors()
        tid = self._top_level_id(model)
        if tid is None:
            return
        idx = self.sel_star_model.findData(int(tid))
        if idx >= 0:
            self.sel_star_model.setCurrentIndex(idx)

    def _select_map_model(self, model):
        self._refresh_model_selectors()
        tid = self._top_level_id(model)
        if tid is None:
            return
        idx = self.sel_map_model.findData(int(tid))
        if idx >= 0:
            self.sel_map_model.setCurrentIndex(idx)

    def _is_volume_like(self, model):
        name = model.__class__.__name__.lower()
        if "volume" in name:
            return True
        try:
            d = getattr(model, "data", None)
            if d is not None and hasattr(d, "matrix"):
                return True
        except Exception:
            pass
        return False

    def _build_outer(self, continue_mode=False):
        from Qt.QtWidgets import QMessageBox
        from . import cmd

        try:
            angle_set = float(self.angle_set.value())
            length = float(self.length.value())
            n_doublet = int(self.n_doublet.value())
            radius = float(self.radius.value())
            spacing = float(self.spacing.value())
            doublet_offset = float(self.doublet_offset.value())

            random_spacing = bool(self.random_enable.isChecked())
            random_max_diff = float(self.random_max_diff.value())
            if random_max_diff < 0.0:
                random_max_diff = -random_max_diff

            pixel_size = float(self.pixel_size.value())
            model = cmd.cbstraight(
                self.session,
                angle_set=angle_set,
                length=length,
                n_doublet=n_doublet,
                radius=radius,
                spacing=spacing,
                z_offset=0.0,
                doublet_offset=doublet_offset,
                pixel_size=pixel_size,
                random_spacing=random_spacing,
                random_max_diff=random_max_diff,
                show_arrows=True,
                open_star=True,
                print_star=False,
            )

            self._last_outer_star_model = model
            try:
                self._select_star_model(model)
            except Exception:
                pass

            # Update last outer end z
            try:
                rows = getattr(model, "_cb_star_rows", None) or []
                px = float(pixel_size)
                max_outer = None
                for r in rows:
                    tid = int(r.get("rlnHelicalTubeID", 0))
                    if 1 <= tid <= n_doublet:
                        z_ang = float(r.get("rlnCoordinateZ", 0.0)) * px
                        if max_outer is None or z_ang > max_outer:
                            max_outer = z_ang
                if max_outer is not None:
                    self._last_outer_end_z_ang = float(max_outer)
            except Exception:
                pass

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _build_centriole(self):
        from Qt.QtWidgets import QMessageBox
        from . import cmd

        try:
            length = float(self.centriole_length.value())
            spacing = float(self.centriole_spacing.value())
            z_offset = float(self.centriole_z_offset.value())
            tube_id = int(self.centriole_tube_id.value())

            pixel_size = float(self.pixel_size.value())
            model = cmd.buildcentriole(
                self.session,
                length=length,
                spacing=spacing,
                z_offset=z_offset,
                tube_id=tube_id,
                pixel_size=pixel_size,
                show_arrows=True,
                open_star=True,
                print_star=False,
            )

            self._last_cent_star_model = model
            try:
                self._select_star_model(model)
            except Exception:
                pass

            # Update last centriole end z
            try:
                rows = getattr(model, "_cb_star_rows", None) or []
                px = float(pixel_size)
                max_cent = None
                for r in rows:
                    tid = int(r.get("rlnHelicalTubeID", 0))
                    if tid == tube_id:
                        z_ang = float(r.get("rlnCoordinateZ", 0.0)) * px
                        if max_cent is None or z_ang > max_cent:
                            max_cent = z_ang
                if max_cent is not None:
                    self._last_cent_end_z_ang = float(max_cent)
            except Exception:
                pass

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _build_ift(self):
        from Qt.QtWidgets import QMessageBox
        from . import cmd

        try:
            self._refresh_model_selectors()
            origin_id = self.ift_origin_model.currentData()
            if origin_id is None:
                raise RuntimeError("Select an origin STAR model for IFT first")
            origin_model = self._top_level_model_by_id(origin_id)
            if origin_model is None or not hasattr(origin_model, "_cb_star_rows"):
                raise RuntimeError("Selected IFT origin model is not available")

            geo = self._star_geometry(origin_model)
            model = cmd.buildift(
                self.session,
                n_particles=int(self.ift_count.value()),
                length=float(geo["length_ang"]),
                n_doublet=int(geo["n_lines"]),
                radius=float(geo["radius_ang"]),
                radial_offset=float(self.ift_distance.value()),
                angle_set=float(geo["angle_set_deg"]),
                z_offset=float(self.ift_z_offset.value()),
                tomo_name=str(geo["tomo_name"]),
                pixel_size=float(geo["pixel_size_ang"]),
                line_mode=bool(self.ift_line_mode.isChecked()),
                open_star=True,
                print_star=False,
            )

            try:
                self._select_star_model(model)
            except Exception:
                pass

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _star_geometry(self, model):
        rows = getattr(model, "_cb_star_rows", None) or []
        if not rows:
            raise RuntimeError("Origin STAR model has no STAR rows")

        px = float(rows[0].get("rlnImagePixelSize", 0.0) or 0.0)
        if px <= 0.0:
            raise RuntimeError("Origin STAR model has invalid pixel size")

        coords = []
        tube_ids = set()
        for row in rows:
            x = float(row.get("rlnCoordinateX", 0.0)) * px
            y = float(row.get("rlnCoordinateY", 0.0)) * px
            z = float(row.get("rlnCoordinateZ", 0.0)) * px
            coords.append((x, y, z, row))
            try:
                tube_ids.add(int(row.get("rlnHelicalTubeID", 0)))
            except Exception:
                pass
        if not coords:
            raise RuntimeError("Origin STAR model has no coordinates")

        radii = [((x * x) + (y * y)) ** 0.5 for x, y, _z, _row in coords]
        radius_ang = sum(radii) / float(len(radii))
        z_values = [z for _x, _y, z, _row in coords]
        length_ang = max(0.0, max(z_values) - min(z_values))

        first = None
        for x, y, _z, row in coords:
            if abs(x) > 1e-6 or abs(y) > 1e-6:
                first = (x, y, row)
                break
        if first is None:
            angle_set_deg = 0.0
        else:
            angle_set_deg = math.degrees(math.atan2(first[1], first[0]))

        return {
            "pixel_size_ang": px,
            "radius_ang": radius_ang,
            "length_ang": length_ang,
            "n_lines": max(1, len([tid for tid in tube_ids if tid > 0])),
            "angle_set_deg": angle_set_deg,
            "tomo_name": str(rows[0].get("rlnTomoName", "TS_001")),
        }

    def _attach_selected_models(self):
        from Qt.QtWidgets import QMessageBox
        from .map import cbsubmap_impl

        try:
            self._refresh_model_selectors()
            star_id = self.sel_star_model.currentData()
            map_id = self.sel_map_model.currentData()
            if star_id is None:
                raise RuntimeError("Select a STAR model first")
            if map_id is None:
                raise RuntimeError("Select a map model first")

            star_model = self._top_level_model_by_id(star_id)
            if star_model is None:
                raise RuntimeError(f"STAR model #{star_id} not found")
            if not hasattr(star_model, "_cb_star_rows"):
                raise RuntimeError(f"Model #{star_id} is not a CiliaBuilder2 STAR model")

            map_model = self._top_level_model_by_id(map_id)
            if map_model is None:
                raise RuntimeError(f"Map model #{map_id} not found")
            if not self._is_volume_like(map_model):
                raise RuntimeError(f"Model #{map_id} is not volume-like")

            cbsubmap_impl(
                session=self.session,
                star_model_obj=star_model,
                map_model_id=map_id,
                close_source=False,
                show_result=True,
                rotate_xy_90=True,
                single_big_object=True,
                attach_axis_rot_z_deg=-90.0,
            )
            # Keep the original source map loaded for reference, but hide it.
            try:
                map_model.display = False
            except Exception:
                pass
            self._refresh_model_selectors()

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))


def start_tool(session, tool_name):
    return CiliaBuilder2Tool(session, tool_name)
