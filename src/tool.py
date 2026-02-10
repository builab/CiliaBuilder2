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
            QGroupBox,
            QLabel,
            QDoubleSpinBox,
            QSpinBox,
            QLineEdit,
            QPushButton,
            QCheckBox,
            QFileDialog,
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

        self.z_offset = QDoubleSpinBox(main)
        self.z_offset.setRange(-1e9, 1e9)
        self.z_offset.setDecimals(2)
        self.z_offset.setValue(0.0)
        outer_row_spin("Z offset", self.z_offset)

        self.doublet_offset = QDoubleSpinBox(main)
        self.doublet_offset.setRange(-360.0, 360.0)
        self.doublet_offset.setDecimals(2)
        self.doublet_offset.setValue(0.0)
        outer_row_spin("Doublet offset (deg)", self.doublet_offset)

        outer_map_row = QWidget(main)
        outer_map_lay = QHBoxLayout(outer_map_row)
        outer_map_lay.setContentsMargins(0, 0, 0, 0)
        outer_map_lay.addWidget(QLabel("Map path", outer_map_row))
        self.outer_map_path = QLineEdit(outer_map_row)
        outer_map_lay.addWidget(self.outer_map_path)
        outer_browse = QPushButton("Browse", outer_map_row)
        outer_browse.clicked.connect(lambda: self._browse_for_map(self.outer_map_path))
        outer_map_lay.addWidget(outer_browse)
        outer_layout.addWidget(outer_map_row)

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

        cent_map_row = QWidget(main)
        cent_map_lay = QHBoxLayout(cent_map_row)
        cent_map_lay.setContentsMargins(0, 0, 0, 0)
        cent_map_lay.addWidget(QLabel("Map path", cent_map_row))
        self.cent_map_path = QLineEdit(cent_map_row)
        cent_map_lay.addWidget(self.cent_map_path)
        cent_browse = QPushButton("Browse", cent_map_row)
        cent_browse.clicked.connect(lambda: self._browse_for_map(self.cent_map_path))
        cent_map_lay.addWidget(cent_browse)
        cent_layout.addWidget(cent_map_row)

        panels.addWidget(cent_box)

        # Bottom controls
        bottom = QWidget(main)
        bottom_lay = QHBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 0, 0, 0)

        bottom_lay.addWidget(QLabel("Pixel size", bottom))
        self.pixel_size = QDoubleSpinBox(bottom)
        self.pixel_size.setRange(1e-6, 1e9)
        self.pixel_size.setDecimals(6)
        self.pixel_size.setValue(10.0)
        bottom_lay.addWidget(self.pixel_size)

        self.open_star = QCheckBox("Open STAR", bottom)
        self.open_star.setChecked(True)
        bottom_lay.addWidget(self.open_star)

        self.show_arrows = QCheckBox("Show arrows", bottom)
        self.show_arrows.setChecked(False)
        bottom_lay.addWidget(self.show_arrows)

        main_layout.addWidget(bottom)

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

        attach_outer_btn = QPushButton("Attach map to outer", btn_row)
        attach_outer_btn.clicked.connect(self._attach_map_to_outer)
        btn_lay.addWidget(attach_outer_btn)

        attach_cent_btn = QPushButton("Attach map to centriole", btn_row)
        attach_cent_btn.clicked.connect(self._attach_map_to_centriole)
        btn_lay.addWidget(attach_cent_btn)

        main_layout.addWidget(btn_row)

        parent.layout().addWidget(main)

        self.tool_window.manage(placement="side")
        self.tool_window.shown = True

    def _browse_for_map(self, line_edit):
        from Qt.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self.tool_window.ui_area,
            "Select map file",
            "",
            "Map files (*.mrc *.map *.ccp4 *.em);;All files (*)",
        )
        if path:
            line_edit.setText(path)

    def _top_level_id(self, model):
        mid = getattr(model, "id", None)
        if not mid:
            return None
        try:
            return int(mid[0])
        except Exception:
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

    def _ensure_map_open(self, path):
        import os

        path = str(path).strip()
        if not path:
            self.session.logger.error("Map path field is empty")
            return None

        path = os.path.expanduser(path)
        path = os.path.abspath(path)

        if not os.path.exists(path):
            self.session.logger.error(f'Map path does not exist: "{path}"')
            return None

        # Reuse already opened map if possible
        for m in self.session.models.list():
            try:
                mp = getattr(m, "path", None)
                if mp and os.path.abspath(os.path.expanduser(str(mp))) == path:
                    tid = self._top_level_id(m)
                    if tid is not None:
                        return tid
            except Exception:
                pass
            try:
                dp = getattr(getattr(m, "data", None), "path", None)
                if dp and os.path.abspath(os.path.expanduser(str(dp))) == path:
                    tid = self._top_level_id(m)
                    if tid is not None:
                        return tid
            except Exception:
                pass

        before = set(self.session.models.list())

        try:
            _run(self.session, f'open "{path}"')
        except Exception as e:
            self.session.logger.error(f'open failed for "{path}": {e}')
            return None

        after = [m for m in self.session.models.list() if m not in before]
        if not after:
            # Sometimes open does not add models in a way we detect, try to locate by data.path
            for m in self.session.models.list():
                try:
                    dp = getattr(getattr(m, "data", None), "path", None)
                    if dp and os.path.abspath(os.path.expanduser(str(dp))) == path:
                        tid = self._top_level_id(m)
                        if tid is not None:
                            return tid
                except Exception:
                    pass
            self.session.logger.error(f'open created no new models for "{path}"')
            return None

        # Prefer a volume model among newly opened ones
        chosen = None
        for m in reversed(after):
            if self._is_volume_like(m):
                chosen = m
                break
        if chosen is None:
            chosen = after[-1]

        tid = self._top_level_id(chosen)
        if tid is None:
            for m in reversed(after):
                tid = self._top_level_id(m)
                if tid is not None:
                    break

        if tid is None:
            self.session.logger.error(f'Could not determine map model id for "{path}"')
            return None

        self.session.logger.info(f'Opened map "{path}" as top level model #{tid}')
        return tid

    def _build_outer(self, continue_mode=False):
        from Qt.QtWidgets import QMessageBox
        from . import cmd

        try:
            angle_set = float(self.angle_set.value())
            length = float(self.length.value())
            n_doublet = int(self.n_doublet.value())
            radius = float(self.radius.value())
            spacing = float(self.spacing.value())
            z_offset = float(self.z_offset.value())
            doublet_offset = float(self.doublet_offset.value())

            random_spacing = bool(self.random_enable.isChecked())
            random_max_diff = float(self.random_max_diff.value())
            if random_max_diff < 0.0:
                random_max_diff = -random_max_diff

            if continue_mode:
                if self._last_outer_end_z_ang is not None:
                    z_offset = float(self._last_outer_end_z_ang) + float(spacing)
                self.z_offset.setValue(float(z_offset))

            pixel_size = float(self.pixel_size.value())
            show_arrows = bool(self.show_arrows.isChecked())

            model = cmd.cbstraight(
                self.session,
                angle_set=angle_set,
                length=length,
                n_doublet=n_doublet,
                radius=radius,
                spacing=spacing,
                z_offset=z_offset,
                doublet_offset=doublet_offset,
                pixel_size=pixel_size,
                random_spacing=random_spacing,
                random_max_diff=random_max_diff,
                show_arrows=show_arrows,
                open_star=bool(self.open_star.isChecked()),
                print_star=False,
            )

            self._last_outer_star_model = model

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
            show_arrows = bool(self.show_arrows.isChecked())

            model = cmd.buildcentriole(
                self.session,
                length=length,
                spacing=spacing,
                z_offset=z_offset,
                tube_id=tube_id,
                pixel_size=pixel_size,
                show_arrows=show_arrows,
                open_star=bool(self.open_star.isChecked()),
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

    def _attach_map_to_outer(self):
        from Qt.QtWidgets import QMessageBox
        from .map import cbsubmap_impl

        try:
            if self._last_outer_star_model is None:
                raise RuntimeError("Build outer first")

            path = str(self.outer_map_path.text()).strip()
            mid = self._ensure_map_open(path)
            if mid is None:
                raise RuntimeError("Outer map path is empty or failed to open")

            cbsubmap_impl(
                session=self.session,
                star_model_obj=self._last_outer_star_model,
                map_model_id=int(mid),
                close_source=False,
                show_result=True,
            )

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _attach_map_to_centriole(self):
        from Qt.QtWidgets import QMessageBox
        from .map import cbsubmap_impl

        try:
            if self._last_cent_star_model is None:
                raise RuntimeError("Build centriole first")

            path = str(self.cent_map_path.text()).strip()
            mid = self._ensure_map_open(path)
            if mid is None:
                raise RuntimeError("Centriole map path is empty or failed to open")

            cbsubmap_impl(
                session=self.session,
                star_model_obj=self._last_cent_star_model,
                map_model_id=int(mid),
                close_source=False,
                show_result=True,
            )

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))


def start_tool(session, tool_name):
    return CiliaBuilder2Tool(session, tool_name)
