# vim: set expandtab shiftwidth=4 softtabstop=4:

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
            QPushButton,
            QCheckBox,
        )
        from chimerax.ui import MainToolWindow

        self.tool_window = MainToolWindow(self)
        parent = self.tool_window.ui_area

        if parent.layout() is None:
            parent.setLayout(QVBoxLayout())

        main = QWidget(parent)
        main_layout = QVBoxLayout(main)

        panels = QHBoxLayout()
        main_layout.addLayout(panels)

        # Outer panel
        outer_box = QGroupBox("Outer cilia", main)
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

        # Centriole panel
        cent_box = QGroupBox("Centriole", main)
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
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)

        build_outer_btn = QPushButton("Build outer", btn_row)
        build_outer_btn.clicked.connect(lambda: self._build_outer(continue_mode=False))
        btn_lay.addWidget(build_outer_btn)

        cont_outer_btn = QPushButton("Continue outer", btn_row)
        cont_outer_btn.clicked.connect(lambda: self._build_outer(continue_mode=True))
        btn_lay.addWidget(cont_outer_btn)

        build_cent_btn = QPushButton("Build centriole", btn_row)
        build_cent_btn.clicked.connect(self._build_centriole)
        btn_lay.addWidget(build_cent_btn)

        main_layout.addWidget(btn_row)

        # Selection-based attachment controls
        attach_select = QGroupBox("Attach by selected/open models", main)
        attach_select_lay = QVBoxLayout(attach_select)

        sel_ids_row = QWidget(main)
        sel_ids_lay = QHBoxLayout(sel_ids_row)
        sel_ids_lay.setContentsMargins(0, 0, 0, 0)
        sel_ids_lay.addWidget(QLabel("STAR model id", sel_ids_row))
        self.sel_star_model_id = QSpinBox(sel_ids_row)
        self.sel_star_model_id.setRange(1, 999999)
        sel_ids_lay.addWidget(self.sel_star_model_id)
        sel_ids_lay.addWidget(QLabel("Map model id", sel_ids_row))
        self.sel_map_model_id = QSpinBox(sel_ids_row)
        self.sel_map_model_id.setRange(1, 999999)
        sel_ids_lay.addWidget(self.sel_map_model_id)
        attach_select_lay.addWidget(sel_ids_row)

        attach_tune_row = QWidget(main)
        attach_tune_lay = QHBoxLayout(attach_tune_row)
        attach_tune_lay.setContentsMargins(0, 0, 0, 0)
        attach_tune_lay.addWidget(QLabel("Attach px scale", attach_tune_row))
        self.attach_pixel_scale = QDoubleSpinBox(attach_tune_row)
        self.attach_pixel_scale.setRange(1e-6, 1000.0)
        self.attach_pixel_scale.setDecimals(3)
        self.attach_pixel_scale.setSingleStep(0.01)
        self.attach_pixel_scale.setValue(0.100)
        attach_tune_lay.addWidget(self.attach_pixel_scale)
        attach_tune_lay.addWidget(QLabel("Map axis X", attach_tune_row))
        self.attach_axis_x = QDoubleSpinBox(attach_tune_row)
        self.attach_axis_x.setRange(-360.0, 360.0)
        self.attach_axis_x.setDecimals(2)
        self.attach_axis_x.setSingleStep(1.0)
        self.attach_axis_x.setValue(0.0)
        attach_tune_lay.addWidget(self.attach_axis_x)
        attach_tune_lay.addWidget(QLabel("Y", attach_tune_row))
        self.attach_axis_y = QDoubleSpinBox(attach_tune_row)
        self.attach_axis_y.setRange(-360.0, 360.0)
        self.attach_axis_y.setDecimals(2)
        self.attach_axis_y.setSingleStep(1.0)
        self.attach_axis_y.setValue(0.0)
        attach_tune_lay.addWidget(self.attach_axis_y)
        attach_tune_lay.addWidget(QLabel("Z", attach_tune_row))
        self.attach_axis_z = QDoubleSpinBox(attach_tune_row)
        self.attach_axis_z.setRange(-360.0, 360.0)
        self.attach_axis_z.setDecimals(2)
        self.attach_axis_z.setSingleStep(1.0)
        self.attach_axis_z.setValue(0.0)
        attach_tune_lay.addWidget(self.attach_axis_z)
        attach_tune_lay.addStretch(1)
        attach_select_lay.addWidget(attach_tune_row)

        sel_btn_row = QWidget(main)
        sel_btn_lay = QHBoxLayout(sel_btn_row)
        sel_btn_lay.setContentsMargins(0, 0, 0, 0)
        attach_selected_btn = QPushButton("Attach selected STAR + map", sel_btn_row)
        attach_selected_btn.clicked.connect(self._attach_selected_models)
        sel_btn_lay.addWidget(attach_selected_btn)
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
                tid = self._top_level_id(model)
                if tid is not None:
                    self.sel_star_model_id.setValue(int(tid))
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

    def _use_selected_models_for_attach(self):
        from Qt.QtWidgets import QMessageBox

        try:
            selected = list(self.session.selection.models())
            if not selected:
                raise RuntimeError("Select one STAR model and one map model first")

            top_by_id = {}
            for m in selected:
                tid = self._top_level_id(m)
                if tid is None:
                    continue
                if tid not in top_by_id:
                    topm = self._top_level_model_by_id(tid)
                    if topm is not None:
                        top_by_id[tid] = topm

            star_tid = None
            map_tid = None
            for tid, m in top_by_id.items():
                if star_tid is None and hasattr(m, "_cb_star_rows"):
                    star_tid = tid
                if map_tid is None and self._is_volume_like(m):
                    map_tid = tid

            if star_tid is None or map_tid is None:
                raise RuntimeError("Could not detect both STAR and map from selected models")

            self.sel_star_model_id.setValue(int(star_tid))
            self.sel_map_model_id.setValue(int(map_tid))
            self.session.logger.info(f"Selected STAR #{star_tid}, map #{map_tid}")

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _attach_selected_models(self):
        from Qt.QtWidgets import QMessageBox
        from .map import cbsubmap_impl

        try:
            star_id = int(self.sel_star_model_id.value())
            map_id = int(self.sel_map_model_id.value())

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
                attach_pixel_scale=float(self.attach_pixel_scale.value()),
                attach_axis_rot_x_deg=float(self.attach_axis_x.value()),
                attach_axis_rot_y_deg=float(self.attach_axis_y.value()),
                attach_axis_rot_z_deg=float(self.attach_axis_z.value()),
            )
            # Delete original source map after successful attachment.
            try:
                self.session.models.close([map_model])
            except Exception:
                pass

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))


def start_tool(session, tool_name):
    return CiliaBuilder2Tool(session, tool_name)
