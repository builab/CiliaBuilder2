# vim: set expandtab shiftwidth=4 softtabstop=4:

import json
import math
import os

from chimerax.core.tools import ToolInstance
from chimerax.core.commands import run as _run
from chimerax.core.models import Model


class CiliaBuilder2Tool(ToolInstance):
    SESSION_ENDURING = True

    def __init__(self, session, tool_name):
        super().__init__(session, tool_name)

        self.display_name = tool_name

        self._last_outer_end_z_ang = None
        self._last_cent_end_z_ang = None

        self._last_outer_star_model = None
        self._last_cent_star_model = None
        self._manual_tweak_hidden = []
        self._manual_tweak_template = None
        self._manual_tweak_source = None
        self._manual_tweak_fit_source = None
        self._manual_tweak_resampled = None

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
            QFileDialog,
            QLineEdit,
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

        save_session_btn = QPushButton("Save session JSON", btn_row)
        save_session_btn.clicked.connect(self._save_session_json)
        btn_lay.addWidget(save_session_btn)

        load_session_btn = QPushButton("Load session JSON", btn_row)
        load_session_btn.clicked.connect(self._load_session_json)
        btn_lay.addWidget(load_session_btn)

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

        tweak_box = QGroupBox("Manual tweak to template", main)
        tweak_layout = QVBoxLayout(tweak_box)

        tweak_source_row = QWidget(main)
        tweak_source_lay = QHBoxLayout(tweak_source_row)
        tweak_source_lay.setContentsMargins(0, 0, 0, 0)
        tweak_source_lay.addWidget(QLabel("User model path", tweak_source_row))
        self.tweak_source_path = QLineEdit(tweak_source_row)
        tweak_source_lay.addWidget(self.tweak_source_path, 1)
        tweak_source_browse = QPushButton("Browse", tweak_source_row)
        tweak_source_browse.clicked.connect(self._browse_tweak_source)
        tweak_source_lay.addWidget(tweak_source_browse)
        tweak_layout.addWidget(tweak_source_row)

        tweak_template_row = QWidget(main)
        tweak_template_lay = QHBoxLayout(tweak_template_row)
        tweak_template_lay.setContentsMargins(0, 0, 0, 0)
        tweak_template_lay.addWidget(QLabel("Template map path", tweak_template_row))
        self.tweak_template_path = QLineEdit(tweak_template_row)
        self.tweak_template_path.setText("/Users/qs/Downloads/triplet.mrc")
        tweak_template_lay.addWidget(self.tweak_template_path, 1)
        tweak_template_browse = QPushButton("Browse", tweak_template_row)
        tweak_template_browse.clicked.connect(self._browse_tweak_template)
        tweak_template_lay.addWidget(tweak_template_browse)
        tweak_layout.addWidget(tweak_template_row)

        tweak_save_row = QWidget(main)
        tweak_save_lay = QHBoxLayout(tweak_save_row)
        tweak_save_lay.setContentsMargins(0, 0, 0, 0)
        tweak_save_lay.addWidget(QLabel("Save tweaked path", tweak_save_row))
        self.tweak_save_path = QLineEdit(tweak_save_row)
        tweak_save_lay.addWidget(self.tweak_save_path, 1)
        tweak_save_browse = QPushButton("Browse", tweak_save_row)
        tweak_save_browse.clicked.connect(self._browse_tweak_save)
        tweak_save_lay.addWidget(tweak_save_browse)
        tweak_layout.addWidget(tweak_save_row)

        tweak_btn_row = QWidget(main)
        tweak_btn_lay = QHBoxLayout(tweak_btn_row)
        tweak_btn_lay.setContentsMargins(0, 0, 0, 0)
        tweak_start_btn = QPushButton("Start tweak", tweak_btn_row)
        tweak_start_btn.clicked.connect(self._start_manual_tweak)
        tweak_btn_lay.addWidget(tweak_start_btn)
        tweak_finish_btn = QPushButton("Finish tweak", tweak_btn_row)
        tweak_finish_btn.clicked.connect(self._finish_manual_tweak)
        tweak_btn_lay.addWidget(tweak_finish_btn)
        tweak_btn_lay.addStretch(1)
        tweak_layout.addWidget(tweak_btn_row)

        main_layout.addWidget(tweak_box)

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

    def _model_ref(self, model):
        ref = getattr(model, "id_string", "")
        return str(ref) if ref else None

    def _model_parent(self, model):
        try:
            return model.parent
        except Exception:
            return None

    def _is_generated_attached_model(self, model):
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_generated_attached", False):
                return True
            cur = self._model_parent(cur)
        return False

    def _is_selector_attach_source(self, model):
        if not self._is_attach_source(model):
            return False
        if self._is_generated_attached_model(model):
            return False
        if self._is_surface_like(model):
            parent = self._model_parent(model)
            if parent is not None and self._is_attach_source(parent):
                return False
        return True

    def _model_by_ref(self, model_id):
        want = str(model_id)
        for m in self.session.models.list():
            if m.id_string == want:
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
                ref = self._model_ref(m)
                if ref is None or not hasattr(m, "_cb_star_rows"):
                    continue
                label = f"{m.name} (#{ref})"
                star_items.append((label, str(ref)))
                self.sel_star_model.addItem(label, str(ref))
                star_has_models = True
            if star_current is not None:
                idx = self.sel_star_model.findData(str(star_current))
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
            self.sel_map_model.addItem("No original map/STL/GLB models", None)
            for m in self.session.models.list():
                ref = self._model_ref(m)
                if ref is None or not self._is_selector_attach_source(m):
                    continue
                label = f"{m.name} (#{ref})"
                self.sel_map_model.addItem(label, str(ref))
                map_has_models = True
            if map_current is not None:
                idx = self.sel_map_model.findData(str(map_current))
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
            for label, ref in star_items:
                self.ift_origin_model.addItem(label, str(ref))
            if ift_origin_current is not None:
                idx = self.ift_origin_model.findData(str(ift_origin_current))
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
        ref = self._model_ref(model)
        if ref is None:
            return
        idx = self.sel_star_model.findData(str(ref))
        if idx >= 0:
            self.sel_star_model.setCurrentIndex(idx)

    def _select_map_model(self, model):
        self._refresh_model_selectors()
        ref = self._model_ref(model)
        if ref is None:
            return
        idx = self.sel_map_model.findData(str(ref))
        if idx >= 0:
            self.sel_map_model.setCurrentIndex(idx)

    def _browse_tweak_source(self):
        from Qt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self.tool_window.ui_area,
            "Choose user model to tweak",
            "",
            "Models (*.mrc *.map *.ccp4 *.mrcs *.stl *.glb *.gltf *.pdb *.cif *.mmcif);;All files (*)",
        )
        if path:
            self.tweak_source_path.setText(path)
            base = os.path.splitext(os.path.basename(path))[0]
            self.tweak_save_path.setText(os.path.expanduser(f"~/{base}_tweaked.mrc"))

    def _browse_tweak_save(self):
        from Qt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self.tool_window.ui_area,
            "Save tweaked model",
            self.tweak_save_path.text().strip() or os.path.expanduser("~/tweaked_model.mrc"),
            "MRC files (*.mrc);;All files (*)",
        )
        if path:
            self.tweak_save_path.setText(path)

    def _browse_tweak_template(self):
        from Qt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self.tool_window.ui_area,
            "Choose template map",
            self.tweak_template_path.text().strip() or "",
            "Maps (*.mrc *.map *.ccp4 *.mrcs);;All files (*)",
        )
        if path:
            self.tweak_template_path.setText(path)

    def _restore_manual_tweak_scene(self):
        for model, visible in self._manual_tweak_hidden:
            try:
                model.display = bool(visible)
            except Exception:
                pass
        self._manual_tweak_hidden = []

    def _close_manual_tweak_models(self):
        for model in (
            self._manual_tweak_template,
            self._manual_tweak_source,
            self._manual_tweak_fit_source,
            self._manual_tweak_resampled,
        ):
            if model is None:
                continue
            try:
                self.session.models.close([model])
            except Exception:
                pass
        self._manual_tweak_template = None
        self._manual_tweak_source = None
        self._manual_tweak_fit_source = None
        self._manual_tweak_resampled = None

    def _command_created_models(self, command):
        before = set(self.session.models.list())
        _run(self.session, command)
        return [m for m in self.session.models.list() if m not in before]

    def _iter_model_tree(self, model):
        yield model
        try:
            children = list(model.child_models())
        except Exception:
            children = []
        for child in children:
            yield from self._iter_model_tree(child)

    def _pick_opened_model(self, opened_models, predicate):
        for model in opened_models:
            for candidate in self._iter_model_tree(model):
                try:
                    if predicate(candidate):
                        return candidate
                except Exception:
                    pass
        return None

    def _is_atomic_like(self, model):
        try:
            atoms = getattr(model, "atoms", None)
            if atoms is not None and len(atoms) > 0:
                return True
        except Exception:
            pass
        cls_name = model.__class__.__name__.lower()
        model_name = str(getattr(model, "name", "") or "").lower()
        return (
            "structure" in cls_name
            or "atomic" in cls_name
            or model_name.endswith((".pdb", ".cif", ".mmcif"))
        )

    def _volume_voxel_size(self, model):
        try:
            data = getattr(model, "data", None)
            step = getattr(data, "step", None)
            if step is not None:
                vals = tuple(float(s) for s in step[:3])
                if all(abs(v) > 1e-12 for v in vals):
                    return vals
        except Exception:
            pass
        try:
            grid = getattr(model, "grid_data", None)
            step = getattr(grid, "step", None)
            if step is not None:
                vals = tuple(float(s) for s in step[:3])
                if all(abs(v) > 1e-12 for v in vals):
                    return vals
        except Exception:
            pass
        return None

    def _match_template_voxel_size_to_source(self):
        src = self._manual_tweak_source
        tmpl = self._manual_tweak_template
        if src is None or tmpl is None:
            return
        if not self._is_volume_like(src) or not self._is_volume_like(tmpl):
            return
        src_step = self._volume_voxel_size(src)
        tmpl_step = self._volume_voxel_size(tmpl)
        if src_step is None or tmpl_step is None:
            return
        if all(abs(a - b) < 1e-9 for a, b in zip(src_step, tmpl_step)):
            return
        step_text = ",".join(f"{v:.6g}" for v in src_step)
        _run(self.session, f"volume #{tmpl.id_string} voxelSize {step_text}")
        self.session.logger.info(
            f"Adjusted template voxel size from {tmpl_step} to match source voxel size {src_step}."
        )

    def _prepare_manual_tweak_fit_source(self):
        src = self._manual_tweak_source
        tmpl = self._manual_tweak_template
        if src is None or tmpl is None:
            raise RuntimeError("Manual tweak models are not loaded")

        if self._is_volume_like(src):
            return src

        if self._is_atomic_like(src):
            created = self._command_created_models(
                f"molmap #{src.id_string} 10 onGrid #{tmpl.id_string} replace false"
            )
            if not created:
                raise RuntimeError("molmap did not create a temporary fit map")
            fit_src = self._pick_opened_model(created, self._is_volume_like)
            if fit_src is None:
                raise RuntimeError("molmap did not create a usable temporary fit map")
            try:
                fit_src.display = True
            except Exception:
                pass
            return fit_src

        if self._is_surface_like(src):
            created = self._command_created_models(
                f"volume onesmask #{src.id_string} onGrid #{tmpl.id_string}"
            )
            if not created:
                raise RuntimeError("volume onesmask did not create a temporary fit map")
            fit_src = self._pick_opened_model(created, self._is_volume_like)
            if fit_src is None:
                raise RuntimeError("volume onesmask did not create a usable temporary fit map")
            try:
                fit_src.display = True
            except Exception:
                pass
            return fit_src

        raise RuntimeError("Manual tweak supports map, STL/GLB surface, and PDB-like atomic models")

    def _start_manual_tweak(self):
        from Qt.QtWidgets import QMessageBox

        try:
            source_path = os.path.expanduser(self.tweak_source_path.text().strip())
            template_path = os.path.expanduser(self.tweak_template_path.text().strip())
            if not source_path:
                raise RuntimeError("Choose a user model path first")
            if not os.path.exists(source_path):
                raise RuntimeError(f"User model path does not exist: {source_path}")
            if not template_path:
                raise RuntimeError("Choose a template map path first")
            if not os.path.exists(template_path):
                raise RuntimeError(f"Template map not found: {template_path}")

            self._close_manual_tweak_models()
            self._restore_manual_tweak_scene()

            self._manual_tweak_hidden = []
            for model in self.session.models.list():
                try:
                    self._manual_tweak_hidden.append((model, bool(model.display)))
                    model.display = False
                except Exception:
                    pass

            before = set(self.session.models.list())
            _run(self.session, f'open "{template_path}"')
            template_new = [m for m in self.session.models.list() if m not in before]
            if not template_new:
                raise RuntimeError("Could not open template map")
            self._manual_tweak_template = self._pick_opened_model(template_new, self._is_volume_like)
            if self._manual_tweak_template is None:
                raise RuntimeError("Could not find opened template map volume")

            before = set(self.session.models.list())
            _run(self.session, f'open "{source_path}"')
            source_new = [m for m in self.session.models.list() if m not in before]
            if not source_new:
                raise RuntimeError("Could not open user model")
            self._manual_tweak_source = self._pick_opened_model(
                source_new,
                lambda m: self._is_volume_like(m) or self._is_surface_like(m) or self._is_atomic_like(m),
            )
            if self._manual_tweak_source is None:
                raise RuntimeError("Could not find opened user model geometry")
            self._match_template_voxel_size_to_source()

            try:
                self._manual_tweak_template.display = True
                self._manual_tweak_source.display = True
            except Exception:
                pass

            _run(self.session, f"select #{self._manual_tweak_source.id_string}")
            _run(self.session, "view")
            self.session.logger.info(
                "Manual tweak started. Rotate the selected user model with right mouse, then click Finish tweak."
            )
        except Exception as e:
            self._close_manual_tweak_models()
            self._restore_manual_tweak_scene()
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _finish_manual_tweak(self):
        from Qt.QtWidgets import QMessageBox

        try:
            if self._manual_tweak_template is None or self._manual_tweak_source is None:
                raise RuntimeError("Start manual tweak first")
            if not self._is_volume_like(self._manual_tweak_template):
                raise RuntimeError("Template model must be a volume map")

            save_path = os.path.expanduser(self.tweak_save_path.text().strip())
            if not save_path:
                raise RuntimeError("Choose a save path for the tweaked model")

            self._manual_tweak_fit_source = self._prepare_manual_tweak_fit_source()

            _run(
                self.session,
                f"fitmap #{self._manual_tweak_fit_source.id_string} inMap #{self._manual_tweak_template.id_string}",
            )

            resampled_new = self._command_created_models(
                f"volume resample #{self._manual_tweak_fit_source.id_string} onGrid #{self._manual_tweak_template.id_string}"
            )
            if not resampled_new:
                raise RuntimeError("volume resample did not create a new model")
            self._manual_tweak_resampled = self._pick_opened_model(resampled_new, self._is_volume_like)
            if self._manual_tweak_resampled is None:
                raise RuntimeError("volume resample did not create a usable map")

            save_dir = os.path.dirname(save_path)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            _run(self.session, f'save "{save_path}" #{self._manual_tweak_resampled.id_string}')

            self._close_manual_tweak_models()
            self._restore_manual_tweak_scene()

            before = set(self.session.models.list())
            _run(self.session, f'open "{save_path}"')
            reopened = [m for m in self.session.models.list() if m not in before]
            if reopened:
                tweaked_model = reopened[-1]
                try:
                    from .cmd import _add_to_cb_map_group
                    _add_to_cb_map_group(self.session, tweaked_model)
                except Exception:
                    pass
                tweaked_model._cb_attach_source = True
                try:
                    tweaked_model.display = True
                except Exception:
                    pass
                self._select_map_model(tweaked_model)
            self._refresh_model_selectors()
            self.session.logger.info(f"Manual tweak finished and saved: {save_path}")
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _select_combo_saved(self, combo, saved):
        if combo is None or saved is None:
            return False
        want_id = saved.get("id", None)
        if want_id is not None:
            idx = combo.findData(str(want_id))
            if idx >= 0:
                combo.setCurrentIndex(idx)
                return True
        want_text = str(saved.get("text", "") or "").strip()
        if want_text:
            for idx in range(combo.count()):
                if combo.itemText(idx) == want_text:
                    combo.setCurrentIndex(idx)
                    return True
        return False

    def _combo_state(self, combo):
        if combo is None:
            return {"id": None, "text": ""}
        return {
            "id": combo.currentData(),
            "text": combo.currentText(),
        }

    def _generated_star_models(self):
        out = []
        for model in self.session.models.list():
            rows = getattr(model, "_cb_star_rows", None)
            if rows is None:
                continue
            out.append(
                {
                    "name": str(model.name),
                    "rows": rows,
                    "star_text": getattr(model, "_cb_star_text", None),
                }
            )
        return out

    def _ui_state(self):
        return {
            "angle_set": float(self.angle_set.value()),
            "length": float(self.length.value()),
            "n_doublet": int(self.n_doublet.value()),
            "radius": float(self.radius.value()),
            "spacing": float(self.spacing.value()),
            "doublet_offset": float(self.doublet_offset.value()),
            "random_enable": bool(self.random_enable.isChecked()),
            "random_max_diff": float(self.random_max_diff.value()),
            "centriole_length": float(self.centriole_length.value()),
            "centriole_spacing": float(self.centriole_spacing.value()),
            "centriole_z_offset": float(self.centriole_z_offset.value()),
            "centriole_tube_id": int(self.centriole_tube_id.value()),
            "ift_count": int(self.ift_count.value()),
            "ift_distance": float(self.ift_distance.value()),
            "ift_z_offset": float(self.ift_z_offset.value()),
            "ift_line_mode": bool(self.ift_line_mode.isChecked()),
            "pixel_size": float(self.pixel_size.value()),
        }

    def _apply_ui_state(self, state):
        self.angle_set.setValue(float(state.get("angle_set", self.angle_set.value())))
        self.length.setValue(float(state.get("length", self.length.value())))
        self.n_doublet.setValue(int(state.get("n_doublet", self.n_doublet.value())))
        self.radius.setValue(float(state.get("radius", self.radius.value())))
        self.spacing.setValue(float(state.get("spacing", self.spacing.value())))
        self.doublet_offset.setValue(float(state.get("doublet_offset", self.doublet_offset.value())))
        self.random_enable.setChecked(bool(state.get("random_enable", self.random_enable.isChecked())))
        self.random_max_diff.setValue(float(state.get("random_max_diff", self.random_max_diff.value())))
        self.centriole_length.setValue(float(state.get("centriole_length", self.centriole_length.value())))
        self.centriole_spacing.setValue(float(state.get("centriole_spacing", self.centriole_spacing.value())))
        self.centriole_z_offset.setValue(float(state.get("centriole_z_offset", self.centriole_z_offset.value())))
        self.centriole_tube_id.setValue(int(state.get("centriole_tube_id", self.centriole_tube_id.value())))
        self.ift_count.setValue(int(state.get("ift_count", self.ift_count.value())))
        self.ift_distance.setValue(float(state.get("ift_distance", self.ift_distance.value())))
        self.ift_z_offset.setValue(float(state.get("ift_z_offset", self.ift_z_offset.value())))
        self.ift_line_mode.setChecked(bool(state.get("ift_line_mode", self.ift_line_mode.isChecked())))
        self.pixel_size.setValue(float(state.get("pixel_size", self.pixel_size.value())))

    def _restore_generated_star_models(self, models_state):
        from . import cmd
        for item in models_state or []:
            name = str(item.get("name", "") or "").strip()
            rows = item.get("rows", None)
            if not name or not rows:
                continue
            exists = False
            for model in self.session.models.list():
                if hasattr(model, "_cb_star_rows") and str(model.name) == name:
                    exists = True
                    break
            if exists:
                continue
            created = Model(name, self.session)
            cmd._add_to_cb_star_group(self.session, created)
            created._cb_star_rows = rows
            created._cb_star_text = item.get("star_text", None)
            cmd._render_star_model(self.session, created, rows, True)

    def _save_session_json(self):
        from Qt.QtWidgets import QMessageBox, QFileDialog

        try:
            path, _ = QFileDialog.getSaveFileName(
                self.tool_window.ui_area,
                "Save CiliaBuilder2 session",
                "ciliabuilder2_session.json",
                "JSON files (*.json);;All files (*)",
            )
            if not path:
                return
            payload = {
                "version": 1,
                "ui": self._ui_state(),
                "selected": {
                    "star_model": self._combo_state(self.sel_star_model),
                    "map_model": self._combo_state(self.sel_map_model),
                    "ift_origin_model": self._combo_state(self.ift_origin_model),
                },
                "generated_star_models": self._generated_star_models(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self.session.logger.info(f"Saved CiliaBuilder2 session JSON: {path}")
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _load_session_json(self):
        from Qt.QtWidgets import QMessageBox, QFileDialog

        try:
            path, _ = QFileDialog.getOpenFileName(
                self.tool_window.ui_area,
                "Load CiliaBuilder2 session",
                "",
                "JSON files (*.json);;All files (*)",
            )
            if not path:
                return
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            self._apply_ui_state(payload.get("ui", {}))
            self._restore_generated_star_models(payload.get("generated_star_models", []))
            self._refresh_model_selectors()

            selected = payload.get("selected", {})
            self._select_combo_saved(self.sel_star_model, selected.get("star_model"))
            self._select_combo_saved(self.sel_map_model, selected.get("map_model"))
            self._select_combo_saved(self.ift_origin_model, selected.get("ift_origin_model"))

            self.session.logger.info(f"Loaded CiliaBuilder2 session JSON: {path}")
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))

    def _is_surface_like(self, model):
        cls_name = model.__class__.__name__.lower()
        if "surface" in cls_name or "stl" in cls_name or "gltf" in cls_name or "glb" in cls_name or "mesh" in cls_name:
            return True
        try:
            vertices = getattr(model, "vertices", None)
            triangles = getattr(model, "triangles", None)
            if vertices is not None and triangles is not None:
                return True
        except Exception:
            pass
        model_name = str(getattr(model, "name", "") or "").lower()
        return model_name.endswith((".stl", ".glb", ".gltf"))

    def _is_volume_like(self, model):
        cls_name = model.__class__.__name__.lower()
        model_name = str(getattr(model, "name", "") or "").lower()
        if "volume" in cls_name or "map" in cls_name:
            return True
        try:
            d = getattr(model, "data", None)
            if d is not None and hasattr(d, "matrix"):
                return True
        except Exception:
            pass
        try:
            gd = getattr(model, "grid_data", None)
            if gd is not None:
                return True
        except Exception:
            pass
        for ext in (".mrc", ".map", ".ccp4", ".mrcs"):
            if model_name.endswith(ext):
                return True
        return False

    def _is_attach_source(self, model):
        return self._is_volume_like(model) or self._is_surface_like(model)

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
            origin_model = self._model_by_ref(origin_id)
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

            star_model = self._model_by_ref(star_id)
            if star_model is None:
                raise RuntimeError(f"STAR model #{star_id} not found")
            if not hasattr(star_model, "_cb_star_rows"):
                raise RuntimeError(f"Model #{star_id} is not a CiliaBuilder2 STAR model")

            map_model = self._model_by_ref(map_id)
            if map_model is None:
                raise RuntimeError(f"Map model #{map_id} not found")
            if not self._is_attach_source(map_model):
                raise RuntimeError(f"Model #{map_id} is not a map/STL/GLB attach source")

            cbsubmap_impl(
                session=self.session,
                star_model_obj=star_model,
                map_model_id=map_id,
                close_source=False,
                show_result=True,
                rotate_xy_90=True,
                single_big_object=True,
                attach_auto_align_long_axis=False,
                attach_inout_flip=False,
                attach_updown_flip=False,
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
