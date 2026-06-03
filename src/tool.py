# vim: set expandtab shiftwidth=4 softtabstop=4:

import json
import math
import os
import tempfile
import numpy as np

from chimerax.core.tools import ToolInstance
from chimerax.core.commands import run as _run
from chimerax.core.models import Model


class EmbeddedModelsBrowser:
    NAME_COLUMN = 0
    ID_COLUMN = 1
    COLOR_COLUMN = 2
    SHOWN_COLUMN = 3
    SELECT_COLUMN = 4

    def __init__(self, session, parent=None):
        self.session = session
        self.models = []
        self._updating = False
        self._handlers = []

        from Qt.QtWidgets import (
            QWidget,
            QHBoxLayout,
            QVBoxLayout,
            QTreeWidget,
            QAbstractItemView,
            QPushButton,
            QScrollArea,
            QSizePolicy,
        )

        class SizedTreeWidget(QTreeWidget):
            def sizeHint(self):
                from Qt.QtCore import QSize
                width = self.header().length() if self.header() is not None else 0
                return QSize(max(width, 440), 300)

        self.widget = QWidget(parent)
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tree = SizedTreeWidget(self.widget)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tree.setHeaderLabels(["Name", "ID", " ", "", ""])
        from chimerax.ui.icons import get_qt_icon
        self.tree.headerItem().setIcon(self.SHOWN_COLUMN, get_qt_icon("shown"))
        self.tree.headerItem().setToolTip(self.SHOWN_COLUMN, "Shown")
        self.tree.headerItem().setIcon(self.SELECT_COLUMN, get_qt_icon("select"))
        self.tree.headerItem().setToolTip(self.SELECT_COLUMN, "Selected")
        self.tree.setColumnWidth(self.NAME_COLUMN, 300)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemChanged.connect(self._tree_change_cb)
        self.tree.expanded.connect(lambda *_: self.tree.resizeColumnToContents(self.ID_COLUMN))
        layout.addWidget(self.tree, 1)

        scrolled_button_area = QScrollArea(self.widget)
        layout.addWidget(scrolled_button_area)
        button_area = QWidget(scrolled_button_area)
        buttons_layout = QVBoxLayout(button_area)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(0)
        for label, cb in (
            ("Close", self._close_models),
            ("Hide", self._hide_models),
            ("Show", self._show_models),
            ("View", self._view_models),
            ("Info", self._info_models),
        ):
            button = QPushButton(label, button_area)
            button.clicked.connect(cb)
            buttons_layout.addWidget(button)
        buttons_layout.addStretch(1)
        scrolled_button_area.setWidget(button_area)

        self._register_handlers()
        self.refresh()

    def _register_handlers(self):
        from chimerax.core.models import (
            ADD_MODELS,
            REMOVE_MODELS,
            MODEL_COLOR_CHANGED,
            MODEL_DISPLAY_CHANGED,
            MODEL_ID_CHANGED,
            MODEL_NAME_CHANGED,
        )
        from chimerax.core.selection import SELECTION_CHANGED

        for trig in (
            SELECTION_CHANGED,
            MODEL_COLOR_CHANGED,
            MODEL_DISPLAY_CHANGED,
            ADD_MODELS,
            REMOVE_MODELS,
            MODEL_ID_CHANGED,
            MODEL_NAME_CHANGED,
        ):
            h = self.session.triggers.add_handler(trig, lambda *args, self=self: self.refresh())
            self._handlers.append((self.session.triggers, h))
        try:
            from chimerax import atomic
            h = atomic.get_triggers().add_handler("changes", lambda *args, self=self: self.refresh())
            self._handlers.append((atomic.get_triggers(), h))
        except Exception:
            pass

    def _selected_models(self):
        return [item._model for item in self.tree.selectedItems() if hasattr(item, "_model")]

    def _models_for_action(self):
        selected = self._selected_models()
        return selected if selected else list(self.models)

    def _model_color(self, model):
        try:
            return model.overall_color
        except Exception:
            return None

    def _model_info(self, model, all_selected, part_selected):
        try:
            model_id = model.id
            model_id_string = model.id_string
        except Exception:
            return None
        if model_id is None:
            return None
        return {
            "id": model_id,
            "id_string": model_id_string,
            "name": getattr(model, "name", "(unnamed)"),
            "display": bool(getattr(model, "display", False)),
            "selected": model in all_selected,
            "part_selected": model in part_selected,
            "color": self._model_color(model),
        }

    def refresh(self):
        if self._updating:
            return
        self._updating = True
        try:
            from Qt.QtCore import Qt
            from Qt.QtWidgets import QTreeWidgetItem
            self.tree.blockSignals(True)
            selected_ids = {getattr(m, "id_string", None) for m in self._selected_models()}
            expanded_ids = set()
            root = self.tree.invisibleRootItem()
            stack = [root]
            while stack:
                item = stack.pop()
                if hasattr(item, "_model") and item.isExpanded():
                    expanded_ids.add(getattr(item._model, "id_string", None))
                for i in range(item.childCount()):
                    stack.append(item.child(i))

            self.tree.clear()
            item_by_model = {}
            self.models = sorted(self.session.models.list(), key=lambda m: m.id)
            all_selected_models = set(self.session.selection.models(all_selected=True))
            part_selected_models = set(self.session.selection.models())

            for model in self.models:
                info = self._model_info(model, all_selected_models, part_selected_models)
                if info is None:
                    continue
                parent_model = getattr(model, "parent", None)
                parent_item = item_by_model.get(parent_model, self.tree.invisibleRootItem())
                item = QTreeWidgetItem(parent_item)
                item._model = model
                item_by_model[model] = item
                item.setText(self.NAME_COLUMN, str(info["name"]))
                item.setText(self.ID_COLUMN, str(info["id_string"]))
                color = info["color"]
                if color is not None:
                    try:
                        from Qt.QtGui import QColor, QBrush
                        qcolor = QColor(*[int(c) for c in color[:4]])
                        item.setBackground(self.COLOR_COLUMN, QBrush(qcolor))
                    except Exception:
                        pass
                item.setCheckState(self.SHOWN_COLUMN, Qt.CheckState.Checked if info["display"] else Qt.CheckState.Unchecked)
                if info["selected"]:
                    item.setCheckState(self.SELECT_COLUMN, Qt.CheckState.Checked)
                elif info["part_selected"]:
                    item.setCheckState(self.SELECT_COLUMN, Qt.CheckState.PartiallyChecked)
                else:
                    item.setCheckState(self.SELECT_COLUMN, Qt.CheckState.Unchecked)
                expand_default = bool(info["display"] and len(info["id"]) <= 1 and len(model.child_models()) <= 10)
                if info["id_string"] in expanded_ids or expand_default:
                    self.tree.expandItem(item)
                if info["id_string"] in selected_ids:
                    item.setSelected(True)

            for i in range(1, self.tree.columnCount()):
                self.tree.resizeColumnToContents(i)
            self.tree.setColumnWidth(self.NAME_COLUMN, min(max(220, self.tree.sizeHintForColumn(self.NAME_COLUMN)), 420))
        finally:
            self.tree.blockSignals(False)
            self._updating = False

    def _model_spec(self, models):
        from chimerax.core.commands import concise_model_spec
        return concise_model_spec(self.session, models).replace("#!", "#")

    def _close_models(self):
        models = self._models_for_action()
        if not models:
            return
        _run(self.session, f"close {self._model_spec(models)}")

    def _hide_models(self):
        models = self._models_for_action()
        if not models:
            return
        _run(self.session, f"hide {self._model_spec(models)} target m")

    def _show_models(self):
        models = self._models_for_action()
        if not models:
            return
        _run(self.session, f"show {self._model_spec(models)} target m")

    def _view_models(self):
        models = self._models_for_action()
        if not models:
            return
        _run(self.session, f"view {self._model_spec(models)} clip false")

    def _info_models(self):
        models = self._models_for_action()
        for model in models:
            try:
                model.show_info()
            except Exception:
                pass

    def _tree_change_cb(self, item, column):
        if self._updating or not hasattr(item, "_model"):
            return
        from Qt.QtCore import Qt
        model = item._model
        if column == self.SHOWN_COLUMN:
            cmd = "show" if item.checkState(self.SHOWN_COLUMN) == Qt.CheckState.Checked else "hide"
            _run(self.session, f"{cmd} #{model.id_string} target m")
        elif column == self.SELECT_COLUMN:
            mode = "add" if item.checkState(self.SELECT_COLUMN) == Qt.CheckState.Checked else "subtract"
            _run(self.session, f"select {mode} #{model.id_string}")

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
        self._manual_tweak_source_is_external = False
        self._last_attached_result = None
        self._attached_results = {}
        self._last_attach_star_id = None
        self._last_attach_map_id = None
        self._attach_rebuild_in_progress = False
        self._cb_attachment_clip_states = None
        self._cb_attachment_clip_plane_name = "cb_random_start_clip"
        self._cb_active_attachment_clip = None
        self._known_star_models = []
        self._membrane_counter = 0
        self._ift_target_snapshot = None
        self._ift_pick_pending = False
        self._ift_pick_handlers = []
        self._ift_pick_hidden_models = []
        self._ift_prev_left_mouse_mode_name = None
        self._marker_path_counter = 0
        self._marker_path_pick_pending = False
        self._marker_path_pick_handlers = []
        self._marker_path_prev_left_mouse_mode_name = None
        self._marker_path_prev_marker_settings = None
        self._marker_path_temp_root = None
        self._marker_path_temp_set = None
        self._marker_path_pick_hidden_models = []
        self._marker_path_target_count = 0
        self._marker_path_output_mode = "curve"
        self._marker_path_pick_action = "tube"
        self._marker_path_template_ref = None
        self._marker_path_source_star_ref = None
        self._marker_path_poll_timer = None
        self._geometric_draw_counter = 0
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
            QAbstractSpinBox,
            QDoubleSpinBox,
            QSpinBox,
            QComboBox,
            QPushButton,
            QCheckBox,
            QFileDialog,
            QLineEdit,
            QStackedWidget,
            QTabBar,
            QTabWidget,
        )
        from Qt.QtGui import QDoubleValidator, QIntValidator
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

        class TypedOnlyDoubleSpinBox(QDoubleSpinBox):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.setButtonSymbols(QAbstractSpinBox.NoButtons)
                self.setKeyboardTracking(False)

            def wheelEvent(self, event):
                event.ignore()

        class TypedOnlySpinBox(QSpinBox):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.setButtonSymbols(QAbstractSpinBox.NoButtons)
                self.setKeyboardTracking(False)

            def wheelEvent(self, event):
                event.ignore()

        class NumericLineEdit(QLineEdit):
            def wheelEvent(self, event):
                event.ignore()

        self.tool_window = MainToolWindow(self, close_destroys=False)
        parent = self.tool_window.ui_area

        if parent.layout() is None:
            parent.setLayout(QVBoxLayout())

        main = QWidget(parent)
        main_layout = QVBoxLayout(main)

        sidebar_tabs = QTabWidget(main)
        sidebar_tabs.setTabPosition(QTabWidget.West)
        main_layout.addWidget(sidebar_tabs)

        build_page = QWidget(main)
        build_page_layout = QVBoxLayout(build_page)
        build_page_layout.setContentsMargins(0, 0, 0, 0)

        panels = QTabWidget(build_page)
        build_page_layout.addWidget(panels)
        sidebar_tabs.addTab(build_page, "Build")

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

        self.angle_set = TypedOnlyDoubleSpinBox(main)
        self.angle_set.setRange(-360.0, 360.0)
        self.angle_set.setDecimals(2)
        self.angle_set.setValue(0.0)
        self.angle_set.hide()

        self.length = TypedOnlyDoubleSpinBox(main)
        self.length.setRange(0.0, 1e9)
        self.length.setDecimals(2)
        self.length.setValue(9000.0)
        outer_row_spin("Length", self.length)

        self.n_doublet = TypedOnlySpinBox(main)
        self.n_doublet.setRange(1, 9)
        self.n_doublet.setValue(9)
        outer_row_spin("No. of doublet", self.n_doublet)

        self.radius = TypedOnlyDoubleSpinBox(main)
        self.radius.setRange(0.0, 1e9)
        self.radius.setDecimals(2)
        self.radius.setValue(960.0)
        outer_row_spin("Radius", self.radius)

        self.spacing = TypedOnlyDoubleSpinBox(main)
        self.spacing.setRange(0.0, 1e9)
        self.spacing.setDecimals(2)
        self.spacing.setValue(1000.0)
        outer_row_spin("Periodicity (spacing)", self.spacing)

        self.doublet_offset = TypedOnlyDoubleSpinBox(main)
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
        rand_lay.addStretch(1)
        outer_layout.addWidget(rand_row)

        outer_tab = QWidget(main)
        outer_tab_layout = QVBoxLayout(outer_tab)
        outer_tab_layout.setContentsMargins(0, 0, 0, 0)
        outer_tab_layout.addWidget(outer_box)

        outer_btn_row = QWidget(outer_tab)
        outer_btn_lay = QVBoxLayout(outer_btn_row)
        outer_btn_lay.setContentsMargins(0, 0, 0, 0)
        build_outer_btn = QPushButton("Build microtubules", outer_btn_row)
        build_outer_btn.clicked.connect(lambda: self._build_outer(continue_mode=False))
        outer_btn_lay.addWidget(build_outer_btn)
        cont_outer_btn = QPushButton("Continue microtubules", outer_btn_row)
        cont_outer_btn.clicked.connect(lambda: self._build_outer(continue_mode=True))
        outer_btn_lay.addWidget(cont_outer_btn)
        outer_tab_layout.addWidget(outer_btn_row)
        outer_tab_layout.addStretch(1)
        panels.addTab(outer_tab, "Microtubules")

        # Central pair panel
        cent_box = QGroupBox("Central pair", main)
        cent_layout = QVBoxLayout(cent_box)

        def cent_row_spin(label, spin):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(spin)
            cent_layout.addWidget(w)

        self.centriole_length = TypedOnlyDoubleSpinBox(main)
        self.centriole_length.setRange(0.0, 1e9)
        self.centriole_length.setDecimals(2)
        self.centriole_length.setValue(9000.0)
        cent_row_spin("Length", self.centriole_length)

        self.centriole_spacing = TypedOnlyDoubleSpinBox(main)
        self.centriole_spacing.setRange(0.0, 1e9)
        self.centriole_spacing.setDecimals(2)
        self.centriole_spacing.setValue(333.0)
        cent_row_spin("Periodicity (spacing)", self.centriole_spacing)

        self.centriole_z_offset = TypedOnlyDoubleSpinBox(main)
        self.centriole_z_offset.setRange(-1e9, 1e9)
        self.centriole_z_offset.setDecimals(2)
        self.centriole_z_offset.setValue(0.0)
        cent_row_spin("Z offset", self.centriole_z_offset)

        cent_mode_row = QWidget(main)
        cent_mode_lay = QHBoxLayout(cent_mode_row)
        cent_mode_lay.setContentsMargins(0, 0, 0, 0)
        cent_mode_lay.addWidget(QLabel("Central pair mode", cent_mode_row))
        self.centriole_mode = QComboBox(cent_mode_row)
        self.centriole_mode.addItem("Singlet line", "singlet")
        self.centriole_mode.addItem("C1 + C2 lines", "doublet")
        cent_mode_lay.addWidget(self.centriole_mode, 1)
        cent_layout.addWidget(cent_mode_row)

        self.centriole_c1c2_distance = TypedOnlyDoubleSpinBox(main)
        self.centriole_c1c2_distance.setRange(0.0, 1e9)
        self.centriole_c1c2_distance.setDecimals(2)
        self.centriole_c1c2_distance.setValue(100.0)
        cent_row_spin("C1/C2 distance", self.centriole_c1c2_distance)

        cent_tab = QWidget(main)
        cent_tab_layout = QVBoxLayout(cent_tab)
        cent_tab_layout.setContentsMargins(0, 0, 0, 0)
        cent_tab_layout.addWidget(cent_box)

        cent_btn_row = QWidget(cent_tab)
        cent_btn_lay = QVBoxLayout(cent_btn_row)
        cent_btn_lay.setContentsMargins(0, 0, 0, 0)
        build_cent_btn = QPushButton("Build central pair", cent_btn_row)
        build_cent_btn.clicked.connect(self._build_centriole)
        cent_btn_lay.addWidget(build_cent_btn)
        cent_tab_layout.addWidget(cent_btn_row)
        cent_tab_layout.addStretch(1)
        panels.addTab(cent_tab, "Central Pair")

        # Membrane panel
        mem_box = QGroupBox("Membrane", main)
        mem_layout = QVBoxLayout(mem_box)

        def mem_row_spin(label, spin):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(spin)
            mem_layout.addWidget(w)
            return w

        self.membrane_length = TypedOnlyDoubleSpinBox(main)
        self.membrane_length.setRange(0.0, 1e9)
        self.membrane_length.setDecimals(2)
        self.membrane_length.setValue(9000.0)
        mem_row_spin("Length", self.membrane_length)

        self.membrane_radius = TypedOnlyDoubleSpinBox(main)
        self.membrane_radius.setRange(0.0, 1e9)
        self.membrane_radius.setDecimals(2)
        self.membrane_radius.setValue(1350.0)
        mem_row_spin("Radius", self.membrane_radius)

        self.membrane_thickness = TypedOnlyDoubleSpinBox(main)
        self.membrane_thickness.setRange(0.0, 1e9)
        self.membrane_thickness.setDecimals(2)
        self.membrane_thickness.setValue(40.0)
        mem_row_spin("Thickness", self.membrane_thickness)

        self.membrane_offset = TypedOnlyDoubleSpinBox(main)
        self.membrane_offset.setRange(-1e9, 1e9)
        self.membrane_offset.setDecimals(2)
        self.membrane_offset.setValue(0.0)
        mem_row_spin("Offset", self.membrane_offset)

        self.membrane_distortion = TypedOnlyDoubleSpinBox(main)
        self.membrane_distortion.setRange(0.0, 10.0)
        self.membrane_distortion.setDecimals(2)
        self.membrane_distortion.setValue(0.60)
        mem_row_spin("Distortion level", self.membrane_distortion)

        membrane_tip_dome_row = QWidget(main)
        membrane_tip_dome_lay = QHBoxLayout(membrane_tip_dome_row)
        membrane_tip_dome_lay.setContentsMargins(0, 0, 0, 0)
        self.membrane_tip_dome = QCheckBox("Tip dome cap", membrane_tip_dome_row)
        self.membrane_tip_dome.setChecked(False)
        membrane_tip_dome_lay.addWidget(self.membrane_tip_dome)
        membrane_tip_dome_lay.addStretch(1)
        mem_layout.addWidget(membrane_tip_dome_row)

        self.membrane_particle_receptors_pct = TypedOnlyDoubleSpinBox(main)
        self.membrane_particle_receptors_pct.setRange(0.0, 100.0)
        self.membrane_particle_receptors_pct.setDecimals(2)
        self.membrane_particle_receptors_pct.setSingleStep(1.0)
        self.membrane_particle_receptors_pct.setValue(8.0)
        self._membrane_particle_receptors_pct_row = mem_row_spin(
            "Receptors (%)",
            self.membrane_particle_receptors_pct,
        )
        self._membrane_particle_receptors_pct_row.hide()

        self.membrane_particle_channels_pct = TypedOnlyDoubleSpinBox(main)
        self.membrane_particle_channels_pct.setRange(0.0, 100.0)
        self.membrane_particle_channels_pct.setDecimals(2)
        self.membrane_particle_channels_pct.setSingleStep(1.0)
        self.membrane_particle_channels_pct.setValue(7.0)
        self._membrane_particle_channels_pct_row = mem_row_spin(
            "Channels (%)",
            self.membrane_particle_channels_pct,
        )
        self._membrane_particle_channels_pct_row.hide()

        self.membrane_particle_signaling_pct = TypedOnlyDoubleSpinBox(main)
        self.membrane_particle_signaling_pct.setRange(0.0, 100.0)
        self.membrane_particle_signaling_pct.setDecimals(2)
        self.membrane_particle_signaling_pct.setSingleStep(1.0)
        self.membrane_particle_signaling_pct.setValue(7.0)
        self._membrane_particle_signaling_pct_row = mem_row_spin(
            "Signaling (%)",
            self.membrane_particle_signaling_pct,
        )
        self._membrane_particle_signaling_pct_row.hide()

        self.membrane_particle_scaffold_pct = TypedOnlyDoubleSpinBox(main)
        self.membrane_particle_scaffold_pct.setRange(0.0, 100.0)
        self.membrane_particle_scaffold_pct.setDecimals(2)
        self.membrane_particle_scaffold_pct.setSingleStep(1.0)
        self.membrane_particle_scaffold_pct.setValue(8.0)
        self._membrane_particle_scaffold_pct_row = mem_row_spin(
            "Scaffold (%)",
            self.membrane_particle_scaffold_pct,
        )
        self._membrane_particle_scaffold_pct_row.hide()

        self.membrane_particle_lipids_pct = TypedOnlyDoubleSpinBox(main)
        self.membrane_particle_lipids_pct.setRange(0.0, 100.0)
        self.membrane_particle_lipids_pct.setDecimals(2)
        self.membrane_particle_lipids_pct.setSingleStep(1.0)
        self.membrane_particle_lipids_pct.setValue(70.0)
        self._membrane_particle_lipids_pct_row = mem_row_spin(
            "Lipids (%)",
            self.membrane_particle_lipids_pct,
        )
        self._membrane_particle_lipids_pct_row.hide()

        mem_tab = QWidget(main)
        mem_tab_layout = QVBoxLayout(mem_tab)
        mem_tab_layout.setContentsMargins(0, 0, 0, 0)
        mem_tab_layout.addWidget(mem_box)

        mem_btn_row = QWidget(mem_tab)
        mem_btn_lay = QVBoxLayout(mem_btn_row)
        mem_btn_lay.setContentsMargins(0, 0, 0, 0)
        build_mem_btn = QPushButton("Build membrane", mem_btn_row)
        build_mem_btn.clicked.connect(self._build_membrane)
        mem_btn_lay.addWidget(build_mem_btn)
        mem_tab_layout.addWidget(mem_btn_row)
        mem_tab_layout.addStretch(1)
        panels.addTab(mem_tab, "Membrane")

        # IFT panel
        ift_box = QGroupBox("IFT placement", main)
        ift_layout = QVBoxLayout(ift_box)

        def ift_row_spin(label, spin):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(spin)
            ift_layout.addWidget(w)
            return w

        def ift_row_edit(label, edit):
            w = QWidget(main)
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(label, w))
            lay.addWidget(edit)
            ift_layout.addWidget(w)

        ift_mode_row = QWidget(main)
        ift_mode_lay = QHBoxLayout(ift_mode_row)
        ift_mode_lay.setContentsMargins(0, 0, 0, 0)
        ift_mode_lay.addWidget(QLabel("IFT mode", ift_mode_row))
        self.ift_mode = QComboBox(ift_mode_row)
        self.ift_mode.addItem("Train", "train")
        self.ift_mode.addItem("Pick STAR point", "pick")
        ift_mode_lay.addWidget(self.ift_mode, 1)
        ift_layout.addWidget(ift_mode_row)

        ift_type_row = QWidget(main)
        ift_type_lay = QHBoxLayout(ift_type_row)
        ift_type_lay.setContentsMargins(0, 0, 0, 0)
        ift_type_lay.addWidget(QLabel("IFT type", ift_type_row))
        self.ift_type = QComboBox(ift_type_row)
        self.ift_type.addItem("Anterograde", "anterograde")
        self.ift_type.addItem("Retrograde", "retrograde")
        ift_type_lay.addWidget(self.ift_type, 1)
        ift_layout.addWidget(ift_type_row)

        self.ift_distance = TypedOnlyDoubleSpinBox(main)
        self.ift_distance.setRange(-1e9, 1e9)
        self.ift_distance.setDecimals(2)
        self.ift_distance.setValue(1250.0)
        ift_row_spin("Distance from STAR center", self.ift_distance)

        self.ift_anterograde_angle = TypedOnlyDoubleSpinBox(main)
        self.ift_anterograde_angle.setRange(-360.0, 360.0)
        self.ift_anterograde_angle.setDecimals(2)
        self.ift_anterograde_angle.setValue(-5.0)
        self.ift_anterograde_angle_row = ift_row_spin("Anterograde angle (deg)", self.ift_anterograde_angle)

        self.ift_retrograde_angle = TypedOnlyDoubleSpinBox(main)
        self.ift_retrograde_angle.setRange(-360.0, 360.0)
        self.ift_retrograde_angle.setDecimals(2)
        self.ift_retrograde_angle.setValue(12.0)
        self.ift_retrograde_angle_row = ift_row_spin("Retrograde angle (deg)", self.ift_retrograde_angle)
        self.ift_type.currentIndexChanged.connect(self._update_ift_type_visibility)

        self.ift_mode_stack = QStackedWidget(main)

        train_page = QWidget(main)
        train_layout = QVBoxLayout(train_page)
        train_layout.setContentsMargins(0, 0, 0, 0)

        def train_row_widget(label, widget):
            row = QWidget(train_page)
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.addWidget(QLabel(label, row))
            row_lay.addWidget(widget)
            train_layout.addWidget(row)

        self.ift_train_star_model = RefreshingComboBox(self._refresh_model_selectors, train_page)
        self.ift_train_star_model.setMinimumContentsLength(24)
        self.ift_train_star_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        train_row_widget("Target STAR model", self.ift_train_star_model)

        self.ift_train_doublet = NumericLineEdit(train_page)
        self.ift_train_doublet.setPlaceholderText("required")
        self.ift_train_doublet.setValidator(QIntValidator(1, 10**9, self.ift_train_doublet))
        self.ift_train_doublet.setText("3")
        train_row_widget("Microtubule number", self.ift_train_doublet)

        self.ift_train_angle = NumericLineEdit(train_page)
        self.ift_train_angle.setPlaceholderText("required")
        self.ift_train_angle.setValidator(QDoubleValidator(-1e9, 1e9, 6, self.ift_train_angle))
        self.ift_train_angle.setText("0")
        train_row_widget("Angle (deg)", self.ift_train_angle)

        self.ift_train_offset = NumericLineEdit(train_page)
        self.ift_train_offset.setPlaceholderText("required")
        self.ift_train_offset.setValidator(QDoubleValidator(-1e9, 1e9, 6, self.ift_train_offset))
        self.ift_train_offset.setText("1500")
        train_row_widget("Offset", self.ift_train_offset)

        self.ift_train_periodicity = NumericLineEdit(train_page)
        self.ift_train_periodicity.setPlaceholderText("required")
        self.ift_train_periodicity.setValidator(QDoubleValidator(0.0, 1e9, 6, self.ift_train_periodicity))
        self.ift_train_periodicity.setText("65")
        train_row_widget("Periodicity", self.ift_train_periodicity)

        self.ift_train_repeat = NumericLineEdit(train_page)
        self.ift_train_repeat.setPlaceholderText("required")
        self.ift_train_repeat.setValidator(QIntValidator(1, 10**9, self.ift_train_repeat))
        self.ift_train_repeat.setText("10")
        train_row_widget("Repeating number", self.ift_train_repeat)

        train_btn_row = QWidget(train_page)
        train_btn_lay = QHBoxLayout(train_btn_row)
        train_btn_lay.setContentsMargins(0, 0, 0, 0)
        train_build_btn = QPushButton("Build IFT train STAR", train_btn_row)
        train_build_btn.clicked.connect(self._build_ift_train_star)
        train_btn_lay.addWidget(train_build_btn)
        train_btn_lay.addStretch(1)
        train_layout.addWidget(train_btn_row)
        train_layout.addStretch(1)

        pick_page = QWidget(main)
        pick_layout = QVBoxLayout(pick_page)
        pick_layout.setContentsMargins(0, 0, 0, 0)

        ift_target_row = QWidget(main)
        ift_target_lay = QHBoxLayout(ift_target_row)
        ift_target_lay.setContentsMargins(0, 0, 0, 0)
        use_target_btn = QPushButton("Select STAR point for IFT", ift_target_row)
        use_target_btn.clicked.connect(self._start_ift_pick_mode)
        ift_target_lay.addWidget(use_target_btn)
        self.ift_target_label = QLabel("Press button, then click one STAR point", ift_target_row)
        ift_target_lay.addWidget(self.ift_target_label, 1)
        pick_layout.addWidget(ift_target_row)
        pick_layout.addStretch(1)

        self.ift_mode_stack.addWidget(train_page)
        self.ift_mode_stack.addWidget(pick_page)
        self.ift_mode.currentIndexChanged.connect(self.ift_mode_stack.setCurrentIndex)
        self.ift_mode_stack.setCurrentIndex(self.ift_mode.currentIndex())
        ift_layout.addWidget(self.ift_mode_stack)

        ift_tab = QWidget(main)
        ift_tab_layout = QVBoxLayout(ift_tab)
        ift_tab_layout.setContentsMargins(0, 0, 0, 0)
        ift_tab_layout.addWidget(ift_box)
        ift_tab_layout.addStretch(1)
        panels.addTab(ift_tab, "IFT")

        self.pixel_size = TypedOnlyDoubleSpinBox(main)
        self.pixel_size.setRange(1e-6, 1e9)
        self.pixel_size.setDecimals(6)
        self.pixel_size.setValue(1.0)
        self.pixel_size.hide()

        # Save / load sidebar
        session_page = QWidget(main)
        session_page_layout = QVBoxLayout(session_page)
        session_page_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_tabs.addTab(session_page, "Save/Load")

        btn_row = QWidget(session_page)
        btn_lay = QVBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)

        save_session_btn = QPushButton("Save session JSON", btn_row)
        save_session_btn.clicked.connect(self._save_session_json)
        btn_lay.addWidget(save_session_btn)

        load_session_btn = QPushButton("Load session JSON", btn_row)
        load_session_btn.clicked.connect(self._load_session_json)
        btn_lay.addWidget(load_session_btn)

        load_star_btn = QPushButton("Load STAR file", btn_row)
        load_star_btn.clicked.connect(self._load_star_file)
        btn_lay.addWidget(load_star_btn)

        load_cellpack_btn = QPushButton("Load cellPACK", btn_row)
        load_cellpack_btn.clicked.connect(self._load_cellpack_package)
        load_cellpack_btn.hide()
        btn_lay.addWidget(load_cellpack_btn)

        export_cellpack_btn = QPushButton("Export cellPACK package", btn_row)
        export_cellpack_btn.clicked.connect(self._export_cellpack_package)
        export_cellpack_btn.hide()
        btn_lay.addWidget(export_cellpack_btn)

        align_box = QGroupBox("Auto Z-align map/model", session_page)
        align_layout = QVBoxLayout(align_box)

        align_model_row = QWidget(session_page)
        align_model_lay = QHBoxLayout(align_model_row)
        align_model_lay.setContentsMargins(0, 0, 0, 0)
        align_model_lay.addWidget(QLabel("Model", align_model_row))
        self.align_z_model = RefreshingComboBox(self._refresh_model_selectors, align_model_row)
        self.align_z_model.setMinimumContentsLength(24)
        self.align_z_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        align_model_lay.addWidget(self.align_z_model, 1)
        align_layout.addWidget(align_model_row)

        align_run_row = QWidget(session_page)
        align_run_lay = QHBoxLayout(align_run_row)
        align_run_lay.setContentsMargins(0, 0, 0, 0)
        auto_align_btn = QPushButton("Auto Z-align", align_run_row)
        auto_align_btn.clicked.connect(self._auto_z_align_selected_model)
        align_run_lay.addWidget(auto_align_btn)
        align_run_lay.addStretch(1)
        align_layout.addWidget(align_run_row)
        btn_lay.addWidget(align_box)

        btn_lay.addStretch(1)

        session_page_layout.addWidget(btn_row)
        session_page_layout.addStretch(1)

        # Selection-based attachment controls
        attach_page = QWidget(main)
        attach_page_layout = QVBoxLayout(attach_page)
        attach_page_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_tabs.addTab(attach_page, "Attach")

        attach_modes = QTabWidget(attach_page)
        attach_page_layout.addWidget(attach_modes)

        attach_controls_page = QWidget(attach_page)
        attach_controls_layout = QVBoxLayout(attach_controls_page)
        attach_controls_layout.setContentsMargins(0, 0, 0, 0)
        attach_modes.addTab(attach_controls_page, "Attachment")

        attach_select = QGroupBox("Attach by selected/open models", attach_controls_page)
        attach_select_lay = QVBoxLayout(attach_select)

        star_row = QWidget(main)
        star_lay = QHBoxLayout(star_row)
        star_lay.setContentsMargins(0, 0, 0, 0)
        star_lay.addWidget(QLabel("STAR model", star_row))
        self.sel_star_model = RefreshingComboBox(self._refresh_model_selectors, star_row)
        self.sel_star_model.setMinimumContentsLength(24)
        self.sel_star_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.sel_star_model.currentIndexChanged.connect(self._on_attach_selector_changed)
        star_lay.addWidget(self.sel_star_model, 1)
        attach_select_lay.addWidget(star_row)

        map_row = QWidget(main)
        map_lay = QHBoxLayout(map_row)
        map_lay.setContentsMargins(0, 0, 0, 0)
        map_lay.addWidget(QLabel("Map model", map_row))
        self.sel_map_model = RefreshingComboBox(self._refresh_model_selectors, map_row)
        self.sel_map_model.setMinimumContentsLength(24)
        self.sel_map_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.sel_map_model.currentIndexChanged.connect(self._on_attach_selector_changed)
        map_lay.addWidget(self.sel_map_model, 1)
        attach_select_lay.addWidget(map_row)

        attach_rot_row = QWidget(main)
        attach_rot_lay = QHBoxLayout(attach_rot_row)
        attach_rot_lay.setContentsMargins(0, 0, 0, 0)
        attach_rot_lay.addWidget(QLabel("Attachment Z offset (deg)", attach_rot_row))
        self.attach_line_rotation = TypedOnlyDoubleSpinBox(attach_rot_row)
        self.attach_line_rotation.setRange(-360.0, 360.0)
        self.attach_line_rotation.setDecimals(2)
        self.attach_line_rotation.setSingleStep(1.0)
        self.attach_line_rotation.setValue(0.0)
        self.attach_line_rotation.valueChanged.connect(self._reattach_with_current_settings)
        attach_rot_lay.addWidget(self.attach_line_rotation)
        attach_rot_lay.addStretch(1)
        attach_select_lay.addWidget(attach_rot_row)

        attach_y_row = QWidget(main)
        attach_y_lay = QHBoxLayout(attach_y_row)
        attach_y_lay.setContentsMargins(0, 0, 0, 0)
        attach_y_lay.addWidget(QLabel("Attachment Y rotation (deg)", attach_y_row))
        self.attach_y_rotation = TypedOnlyDoubleSpinBox(attach_y_row)
        self.attach_y_rotation.setRange(-360.0, 360.0)
        self.attach_y_rotation.setDecimals(2)
        self.attach_y_rotation.setSingleStep(1.0)
        self.attach_y_rotation.setValue(0.0)
        self.attach_y_rotation.valueChanged.connect(self._reattach_with_current_settings)
        attach_y_lay.addWidget(self.attach_y_rotation)
        attach_y_lay.addStretch(1)
        attach_select_lay.addWidget(attach_y_row)

        sel_btn_row = QWidget(main)
        sel_btn_lay = QHBoxLayout(sel_btn_row)
        sel_btn_lay.setContentsMargins(0, 0, 0, 0)
        self.attach_selected_btn = QPushButton("Attach selected STAR + map", sel_btn_row)
        self.attach_selected_btn.clicked.connect(self._attach_selected_models)
        sel_btn_lay.addWidget(self.attach_selected_btn)
        self.undo_last_attachment_btn = QPushButton("Undo last attachment", sel_btn_row)
        self.undo_last_attachment_btn.clicked.connect(self._undo_last_attachment)
        self.undo_last_attachment_btn.setEnabled(False)
        sel_btn_lay.addWidget(self.undo_last_attachment_btn)
        sel_btn_lay.addStretch(1)
        attach_select_lay.addWidget(sel_btn_row)

        attach_controls_layout.addWidget(attach_select)
        attach_advanced = QGroupBox("Advanced options", attach_controls_page)
        attach_advanced.setCheckable(True)
        attach_advanced.setChecked(False)
        attach_advanced_lay = QVBoxLayout(attach_advanced)

        attach_advanced_content = QWidget(attach_advanced)
        attach_advanced_content_lay = QVBoxLayout(attach_advanced_content)
        attach_advanced_content_lay.setContentsMargins(0, 0, 0, 0)

        attach_y90_row = QWidget(main)
        attach_y90_lay = QHBoxLayout(attach_y90_row)
        attach_y90_lay.setContentsMargins(0, 0, 0, 0)
        self.attach_pre_rotate_y_90 = QCheckBox("Rotate model 90 deg clockwise around Y before attach", attach_y90_row)
        self.attach_pre_rotate_y_90.setChecked(False)
        self.attach_pre_rotate_y_90.toggled.connect(self._reattach_with_current_settings)
        attach_y90_lay.addWidget(self.attach_pre_rotate_y_90)
        attach_y90_lay.addStretch(1)
        attach_advanced_content_lay.addWidget(attach_y90_row)

        attach_advanced_lay.addWidget(attach_advanced_content)
        attach_advanced.toggled.connect(attach_advanced_content.setVisible)
        attach_advanced_content.setVisible(False)

        attach_controls_layout.addWidget(attach_advanced)
        attach_controls_layout.addStretch(1)

        marker_page = QWidget(attach_page)
        marker_page_layout = QVBoxLayout(marker_page)
        marker_page_layout.setContentsMargins(0, 0, 0, 0)
        attach_modes.addTab(marker_page, "Geometric drawing")

        draw_box = QGroupBox("Geometric drawing", marker_page)
        draw_layout = QVBoxLayout(draw_box)

        draw_mode_row = QWidget(marker_page)
        draw_mode_lay = QHBoxLayout(draw_mode_row)
        draw_mode_lay.setContentsMargins(0, 0, 0, 0)
        draw_mode_lay.addWidget(QLabel("Draw type", draw_mode_row))
        self._geometric_draw_mode_order = ["point", "sphere", "cylinder", "curve", "line"]
        self.geometric_draw_mode_bar = QTabBar(draw_mode_row)
        self.geometric_draw_mode_bar.setExpanding(False)
        for label in ("Point", "Sphere", "Cylinder", "Curve", "Line"):
            self.geometric_draw_mode_bar.addTab(label)
        self.geometric_draw_mode_bar.currentChanged.connect(self._on_geometric_draw_mode_changed)
        draw_mode_lay.addWidget(self.geometric_draw_mode_bar, 1)
        draw_layout.addWidget(draw_mode_row)

        marker_count_row = QWidget(marker_page)
        marker_count_lay = QHBoxLayout(marker_count_row)
        marker_count_lay.setContentsMargins(0, 0, 0, 0)
        marker_count_lay.addWidget(QLabel("No. of markers", marker_count_row))
        self.marker_path_count = TypedOnlySpinBox(marker_count_row)
        self.marker_path_count.setRange(2, 1000)
        self.marker_path_count.setValue(4)
        marker_count_lay.addWidget(self.marker_path_count)
        draw_layout.addWidget(marker_count_row)
        self._geometric_draw_count_row = marker_count_row

        marker_target_row = QWidget(marker_page)
        marker_target_lay = QHBoxLayout(marker_target_row)
        marker_target_lay.setContentsMargins(0, 0, 0, 0)
        marker_target_lay.addWidget(QLabel("Draw on model", marker_target_row))
        self.marker_target_model = RefreshingComboBox(self._refresh_model_selectors, marker_target_row)
        self.marker_target_model.setMinimumContentsLength(24)
        self.marker_target_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.marker_target_model.currentIndexChanged.connect(self._on_marker_target_model_changed)
        marker_target_lay.addWidget(self.marker_target_model, 1)
        draw_layout.addWidget(marker_target_row)

        self.marker_path_mode = QComboBox(marker_page)
        self.marker_path_mode.addItem("Curve", "curve")
        self.marker_path_mode.addItem("Line", "line")
        self.marker_path_mode.hide()

        draw_radius_row = QWidget(marker_page)
        draw_radius_lay = QHBoxLayout(draw_radius_row)
        draw_radius_lay.setContentsMargins(0, 0, 0, 0)
        draw_radius_lay.addWidget(QLabel("Primitive radius", draw_radius_row))
        self.draw_marker_radius = TypedOnlyDoubleSpinBox(draw_radius_row)
        self.draw_marker_radius.setRange(0.1, 1e9)
        self.draw_marker_radius.setDecimals(2)
        self.draw_marker_radius.setValue(12.0)
        draw_radius_lay.addWidget(self.draw_marker_radius)
        draw_layout.addWidget(draw_radius_row)
        self._geometric_draw_primitive_radius_row = draw_radius_row

        marker_radius_row = QWidget(marker_page)
        marker_radius_lay = QHBoxLayout(marker_radius_row)
        marker_radius_lay.setContentsMargins(0, 0, 0, 0)
        marker_radius_lay.addWidget(QLabel("Tube radius", marker_radius_row))
        self.marker_path_radius = TypedOnlyDoubleSpinBox(marker_radius_row)
        self.marker_path_radius.setRange(0.1, 1e9)
        self.marker_path_radius.setDecimals(2)
        self.marker_path_radius.setValue(20.0)
        marker_radius_lay.addWidget(self.marker_path_radius)
        draw_layout.addWidget(marker_radius_row)
        self._geometric_draw_tube_radius_row = marker_radius_row

        draw_btn_row = QWidget(marker_page)
        draw_btn_lay = QHBoxLayout(draw_btn_row)
        draw_btn_lay.setContentsMargins(0, 0, 0, 0)
        self.geometric_draw_pick_btn = QPushButton("Place curve markers", draw_btn_row)
        self.geometric_draw_pick_btn.clicked.connect(self._start_selected_geometric_draw_pick_mode)
        draw_btn_lay.addWidget(self.geometric_draw_pick_btn)
        draw_btn_lay.addStretch(1)
        draw_layout.addWidget(draw_btn_row)

        marker_apply_row = QWidget(marker_page)
        marker_apply_lay = QVBoxLayout(marker_apply_row)
        marker_apply_lay.setContentsMargins(0, 0, 0, 0)
        marker_apply_select_row = QWidget(marker_apply_row)
        marker_apply_select_lay = QHBoxLayout(marker_apply_select_row)
        marker_apply_select_lay.setContentsMargins(0, 0, 0, 0)
        marker_apply_select_lay.addWidget(QLabel("Drawing model", marker_apply_select_row))
        self.geometric_draw_model = RefreshingComboBox(self._refresh_model_selectors, marker_apply_select_row)
        self.geometric_draw_model.setMinimumContentsLength(18)
        self.geometric_draw_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.geometric_draw_model.currentIndexChanged.connect(self._update_marker_path_buttons)
        marker_apply_select_lay.addWidget(self.geometric_draw_model, 1)
        marker_apply_lay.addWidget(marker_apply_select_row)
        self.geometric_draw_save_glb_btn = QPushButton("Save drawing as GLB", marker_apply_row)
        self.geometric_draw_save_glb_btn.clicked.connect(self._save_selected_geometric_drawing_glb)
        marker_apply_lay.addWidget(self.geometric_draw_save_glb_btn)
        draw_layout.addWidget(marker_apply_row)

        self.marker_path_status = QLabel("Press button, then click in ChimeraX to draw", draw_box)
        draw_layout.addWidget(self.marker_path_status)
        marker_page_layout.addWidget(draw_box)
        marker_page_layout.addStretch(1)

        tweak_box = QGroupBox("Manual tweak to template", main)
        tweak_layout = QVBoxLayout(tweak_box)

        tweak_open_row = QWidget(main)
        tweak_open_lay = QHBoxLayout(tweak_open_row)
        tweak_open_lay.setContentsMargins(0, 0, 0, 0)
        tweak_open_lay.addWidget(QLabel("Open model", tweak_open_row))
        self.tweak_open_model = RefreshingComboBox(self._refresh_model_selectors, tweak_open_row)
        self.tweak_open_model.setMinimumContentsLength(24)
        self.tweak_open_model.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        tweak_open_lay.addWidget(self.tweak_open_model, 1)
        tweak_layout.addWidget(tweak_open_row)

        tweak_source_row = QWidget(main)
        tweak_source_lay = QHBoxLayout(tweak_source_row)
        tweak_source_lay.setContentsMargins(0, 0, 0, 0)
        tweak_source_lay.addWidget(QLabel("Or user model path", tweak_source_row))
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

        tweak_box.hide()

        scroll = QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setWidget(main)
        self.models_browser = None
        parent.layout().addWidget(scroll)

        self.tool_window.manage(placement=None)
        self.tool_window.shown = True
        try:
            from Qt.QtCore import Qt
            dw = self.tool_window._dock_widget
            dw.setFloating(True)
            dw.setAttribute(Qt.WA_DeleteOnClose, False)
            dw.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            dw.resize(500, 450)
            dw.show()
        except Exception:
            pass
        try:
            tab_bar = sidebar_tabs.tabBar()
            attach_index = sidebar_tabs.indexOf(attach_page)
            if attach_index >= 0:
                tab_bar.moveTab(attach_index, 1)
            session_index = sidebar_tabs.indexOf(session_page)
            if session_index >= 0:
                tab_bar.moveTab(session_index, 2)
        except Exception:
            pass
        self._refresh_model_selectors()
        self._update_ift_type_visibility()
        self._set_geometric_draw_mode("curve")
        self._update_marker_path_buttons()

    def _model_ref(self, model):
        ref = getattr(model, "id_string", "")
        return str(ref) if ref else None

    def _normalize_rgba(self, rgba):
        if rgba is None:
            return None
        try:
            values = [int(round(float(v))) for v in list(rgba)[:4]]
        except Exception:
            return None
        if len(values) == 3:
            values.append(255)
        if len(values) < 4:
            return None
        return [max(0, min(255, int(v))) for v in values[:4]]

    def _model_direct_color(self, model):
        for attr in ("color", "overall_color"):
            try:
                rgba = getattr(model, attr, None)
            except Exception:
                rgba = None
            normalized = self._normalize_rgba(rgba)
            if normalized is not None:
                return normalized
        return None

    def _capture_model_color_state(self, model):
        if model is None:
            return []

        entries = []

        def walk(node, path):
            color = self._model_direct_color(node)
            if color is not None:
                entries.append(
                    {
                        "path": [int(p) for p in path],
                        "name": str(getattr(node, "name", "") or ""),
                        "rgba": color,
                    }
                )
            try:
                children = list(node.child_models())
            except Exception:
                children = []
            for index, child in enumerate(children):
                walk(child, path + [int(index)])

        walk(model, [])
        return entries

    def _model_tree_node_by_path(self, model, path):
        node = model
        for index in path or []:
            try:
                children = list(node.child_models())
            except Exception:
                return None
            if index < 0 or index >= len(children):
                return None
            node = children[int(index)]
        return node

    def _apply_model_color_state(self, model, color_state):
        if model is None:
            return
        for entry in color_state or []:
            if not isinstance(entry, dict):
                continue
            rgba = self._normalize_rgba(entry.get("rgba", None))
            if rgba is None:
                continue
            node = self._model_tree_node_by_path(model, entry.get("path", []))
            if node is None:
                continue
            try:
                node.color = tuple(rgba)
            except Exception:
                try:
                    node.overall_color = tuple(rgba)
                except Exception:
                    pass

    def _apply_source_color_state_to_attached_result(self, out_root, source_color_state):
        if out_root is None:
            return
        source_root_name = ""
        for entry in source_color_state or []:
            if isinstance(entry, dict) and list(entry.get("path", []) or []) == []:
                source_root_name = str(entry.get("name", "") or "").strip()
                break
        try:
            children = list(out_root.child_models())
        except Exception:
            children = []
        targets = children if children else [out_root]
        for target in targets:
            self._apply_model_color_state(target, source_color_state)
            if source_root_name:
                try:
                    child_models = list(target.child_models())
                except Exception:
                    child_models = []
                for child in child_models:
                    child_name = str(getattr(child, "name", "") or "").strip()
                    if child_name == source_root_name:
                        self._apply_model_color_state(child, source_color_state)
                        break

    def _candidate_model_paths(self, model):
        paths = []
        seen = set()

        def add_path(value):
            if not value:
                return
            try:
                norm = os.path.abspath(os.path.expanduser(str(value)))
            except Exception:
                return
            if not norm or norm in seen:
                return
            seen.add(norm)
            paths.append(norm)

        try:
            scan_models = list(self._iter_model_tree(model))
        except Exception:
            scan_models = [model]
        for obj in scan_models:
            for attr in ("path", "filename"):
                try:
                    add_path(getattr(obj, attr, None))
                except Exception:
                    pass
            try:
                data = getattr(obj, "data", None)
                add_path(getattr(data, "path", None))
            except Exception:
                pass
            try:
                grid = getattr(obj, "grid_data", None)
                add_path(getattr(grid, "path", None))
            except Exception:
                pass
            try:
                for extra in getattr(obj, "_cb_saved_session_paths", []) or []:
                    add_path(extra)
            except Exception:
                pass
        return paths

    def _model_source_path(self, model):
        paths = self._candidate_model_paths(model)
        return paths[0] if paths else None

    def _store_model_saved_path(self, model, path):
        norm = os.path.abspath(os.path.expanduser(str(path or "")))
        if not norm:
            return None
        try:
            targets = list(self._iter_model_tree(model))
        except Exception:
            targets = [model]
        for obj in targets:
            try:
                aliases = list(getattr(obj, "_cb_saved_session_paths", []) or [])
                if norm not in aliases:
                    aliases.append(norm)
                obj._cb_saved_session_paths = aliases
            except Exception:
                pass
        return norm

    def _remember_restored_session_source(self, model, item):
        if model is None:
            return
        store = getattr(self, "_restored_session_sources", None)
        if store is None:
            store = {}
            self._restored_session_sources = store

        path = item.get("path", None)
        if path:
            try:
                store[("path", os.path.abspath(os.path.expanduser(str(path))))] = model
            except Exception:
                pass

        fetch_type = str(item.get("fetch_type", "") or "").strip().lower()
        fetch_id = str(item.get("fetch_id", "") or "").strip().lower()
        if fetch_type and fetch_id:
            store[("fetch", fetch_type, fetch_id)] = model

        source_id = str(item.get("session_source_id", "") or "").strip()
        if source_id:
            store[("source_id", source_id)] = model
            self._remember_restored_session_layout_model("source", source_id, model)

        name = str(item.get("name", "") or "").strip()
        if name:
            store[("name", name)] = model

    def _restored_session_source_model(self, item):
        store = getattr(self, "_restored_session_sources", None) or {}

        map_path = item.get("map_path", None)
        if map_path:
            try:
                model = store.get(("path", os.path.abspath(os.path.expanduser(str(map_path)))))
                if model is not None:
                    return model
            except Exception:
                pass

        fetch_type = str(item.get("fetch_type", "") or "").strip().lower()
        fetch_id = str(item.get("fetch_id", "") or "").strip().lower()
        if fetch_type and fetch_id:
            model = store.get(("fetch", fetch_type, fetch_id))
            if model is not None:
                return model

        source_id = str(item.get("source_session_id", "") or "").strip()
        if source_id:
            model = store.get(("source_id", source_id))
            if model is not None:
                return model

        map_name = str(item.get("map_name", "") or "").strip()
        if map_name:
            model = store.get(("name", map_name))
            if model is not None:
                return model
        return None

    def _remember_restored_session_star(self, model, item):
        if model is None:
            return
        store = getattr(self, "_restored_session_stars", None)
        if store is None:
            store = {}
            self._restored_session_stars = store

        star_id = str(item.get("session_star_id", "") or "").strip()
        if star_id:
            store[("star_id", star_id)] = model
            self._remember_restored_session_layout_model("star", star_id, model)

        name = str(item.get("name", "") or "").strip()
        if name:
            store[("name", name)] = model

    def _restored_session_star_model(self, item):
        store = getattr(self, "_restored_session_stars", None) or {}

        star_id = str(item.get("star_session_id", "") or "").strip()
        if star_id:
            model = store.get(("star_id", star_id))
            if model is not None:
                return model

        star_name = str(item.get("star_name", "") or "").strip()
        if star_name:
            model = store.get(("name", star_name))
            if model is not None:
                return model
        return None

    def _remember_restored_session_layout_model(self, model_type, model_id, model):
        model_key = str(model_id or "").strip()
        if model is None or not model_key:
            return
        store = getattr(self, "_restored_session_layout_models", None)
        if store is None:
            store = {}
            self._restored_session_layout_models = store
        store[(str(model_type or "").strip().lower(), model_key)] = model

    def _restored_session_layout_model(self, model_type, model_id):
        store = getattr(self, "_restored_session_layout_models", None) or {}
        model_key = str(model_id or "").strip()
        if not model_key:
            return None
        return store.get((str(model_type or "").strip().lower(), model_key))

    def _cb_root_model(self):
        for model in self.session.models.list():
            if getattr(model, "_cb_root", False):
                return model
        return None

    def _cb_group_model(self, tag):
        root = self._cb_root_model()
        if root is None:
            return None
        try:
            children = list(root.child_models())
        except Exception:
            children = []
        for child in children:
            if getattr(child, "_cb_group_tag", None) == tag:
                return child
        return None

    def _saved_source_item_model(self, item):
        source_id = str(item.get("session_source_id", "") or "").strip()
        if source_id:
            model = self._model_by_ref(source_id)
            if model is not None:
                return model
        path = item.get("path", None)
        if path:
            model = self._find_model_by_path(path)
            if model is not None:
                return model
        name = str(item.get("name", "") or "").strip()
        if name:
            model = self._find_model_by_name(name, require_star=False)
            if model is not None:
                return model
        return None

    def _saved_star_item_model(self, item):
        star_id = str(item.get("session_star_id", "") or "").strip()
        if star_id:
            model = self._model_by_ref(star_id)
            if model is not None:
                return model
        name = str(item.get("name", "") or "").strip()
        if name:
            model = self._find_model_by_name(name, require_star=True)
            if model is not None:
                return model
        return None

    def _saved_membrane_item_model(self, item):
        membrane_id = str(item.get("session_membrane_id", "") or "").strip()
        if membrane_id:
            model = self._model_by_ref(membrane_id)
            if model is not None:
                return model
        name = str(item.get("name", "") or "").strip()
        if name:
            for model in self._all_session_models():
                if getattr(model, "_cb_membrane_state", None) and str(getattr(model, "name", "") or "") == name:
                    return model
        return None

    def _saved_marker_path_item_model(self, item):
        marker_id = str(item.get("session_marker_path_id", "") or "").strip()
        if marker_id:
            model = self._model_by_ref(marker_id)
            if model is not None:
                return model
        name = str(item.get("name", "") or "").strip()
        if name:
            for model in self._all_session_models():
                if getattr(model, "_cb_marker_path_state", None) and str(getattr(model, "name", "") or "") == name:
                    return model
        return None

    def _saved_attachment_item_model(self, item):
        attachment_id = str(item.get("session_attachment_id", "") or "").strip()
        if attachment_id:
            model = self._model_by_ref(attachment_id)
            if model is not None:
                return model
        name = str(item.get("name", "") or "").strip()
        if name:
            for model in self._all_session_models():
                if getattr(model, "_cb_generated_attached", False) and str(getattr(model, "name", "") or "") == name:
                    return model
        return None

    def _saved_session_content_lookup(
        self,
        attach_sources,
        generated_star_models,
        generated_membranes,
        generated_marker_paths,
        attachments,
    ):
        lookup = {}
        for item in attach_sources or []:
            model = self._saved_source_item_model(item)
            model_id = str(item.get("session_source_id", "") or "").strip()
            if model is None or not model_id:
                continue
            lookup[id(model)] = {"model_type": "source", "model_id": model_id}
        for item in generated_star_models or []:
            model = self._saved_star_item_model(item)
            model_id = str(item.get("session_star_id", "") or "").strip()
            if model is None or not model_id:
                continue
            lookup[id(model)] = {"model_type": "star", "model_id": model_id}
        for item in generated_membranes or []:
            model = self._saved_membrane_item_model(item)
            model_id = str(item.get("session_membrane_id", "") or "").strip()
            if model is None or not model_id:
                continue
            lookup[id(model)] = {"model_type": "membrane", "model_id": model_id}
        for item in generated_marker_paths or []:
            model = self._saved_marker_path_item_model(item)
            model_id = str(item.get("session_marker_path_id", "") or "").strip()
            if model is None or not model_id:
                continue
            lookup[id(model)] = {"model_type": "marker_path", "model_id": model_id}
        for item in attachments or []:
            model = self._saved_attachment_item_model(item)
            model_id = str(item.get("session_attachment_id", "") or "").strip()
            if model is None or not model_id:
                continue
            lookup[id(model)] = {"model_type": "attachment", "model_id": model_id}
        return lookup

    def _session_model_structure_state(
        self,
        attach_sources,
        generated_star_models,
        generated_membranes,
        generated_marker_paths,
        attachments,
    ):
        root = self._cb_root_model()
        if root is None:
            return {"nodes": []}

        content_lookup = self._saved_session_content_lookup(
            attach_sources,
            generated_star_models,
            generated_membranes,
            generated_marker_paths,
            attachments,
        )
        wrapper_ids = {}
        nodes = []
        wrapper_counter = 0

        def wrapper_id_for(model):
            nonlocal wrapper_counter
            wid = wrapper_ids.get(id(model), None)
            if wid is None:
                wrapper_counter += 1
                wid = f"wrapper_{wrapper_counter}"
                wrapper_ids[id(model)] = wid
            return wid

        def parent_ref_for(model):
            if model is None:
                return {"kind": "root"}
            if getattr(model, "_cb_root", False):
                return {"kind": "root"}
            tag = getattr(model, "_cb_group_tag", None)
            if tag in ("star_models", "maps", "membrane"):
                return {"kind": "group", "tag": str(tag)}
            wid = wrapper_ids.get(id(model), None)
            if wid is not None:
                return {"kind": "wrapper", "id": wid}
            return None

        def walk(parent):
            try:
                children = list(parent.child_models())
            except Exception:
                children = []
            for order, child in enumerate(children):
                tag = getattr(child, "_cb_group_tag", None)
                if tag in ("star_models", "maps", "membrane"):
                    walk(child)
                    continue
                pref = parent_ref_for(parent)
                if pref is None:
                    continue
                content_info = content_lookup.get(id(child), None)
                if content_info is not None:
                    nodes.append(
                        {
                            "node_kind": "model",
                            "model_type": str(content_info["model_type"]),
                            "model_id": str(content_info["model_id"]),
                            "parent": pref,
                            "order": int(order),
                        }
                    )
                    continue
                wrapper_id = wrapper_id_for(child)
                nodes.append(
                    {
                        "node_kind": "wrapper",
                        "wrapper_id": wrapper_id,
                        "name": str(getattr(child, "name", "Group") or "Group"),
                        "display": bool(getattr(child, "display", True)),
                        "parent": pref,
                        "order": int(order),
                    }
                )
                walk(child)

        walk(root)
        return {"nodes": nodes}

    def _restore_session_model_structure(self, structure_state):
        from chimerax.core.models import Model

        if not isinstance(structure_state, dict):
            return
        nodes = structure_state.get("nodes", None) or []
        if not nodes:
            return
        root = self._cb_root_model()
        if root is None:
            return

        def ref_key(ref):
            if not isinstance(ref, dict):
                return ("root", "")
            kind = str(ref.get("kind", "root") or "root").strip().lower()
            if kind == "group":
                return ("group", str(ref.get("tag", "") or ""))
            if kind == "wrapper":
                return ("wrapper", str(ref.get("id", "") or ""))
            return ("root", "")

        children_by_parent = {}
        for entry in nodes:
            children_by_parent.setdefault(ref_key(entry.get("parent", {"kind": "root"})), []).append(entry)

        wrapper_models = {}

        def resolve_parent(ref):
            if not isinstance(ref, dict):
                return root
            kind = str(ref.get("kind", "root") or "root").strip().lower()
            if kind == "group":
                return self._cb_group_model(ref.get("tag", None))
            if kind == "wrapper":
                return wrapper_models.get(str(ref.get("id", "") or ""), None)
            return root

        def materialize_entry(entry):
            node_kind = str(entry.get("node_kind", "model") or "model").strip().lower()
            if node_kind == "wrapper":
                wrapper_id = str(entry.get("wrapper_id", "") or "").strip()
                if not wrapper_id:
                    return None
                model = wrapper_models.get(wrapper_id, None)
                if model is None:
                    model = Model(str(entry.get("name", "Group") or "Group"), self.session)
                    model._cb_attach_source = False
                    model._cb_saved_structure_wrapper = True
                    wrapper_models[wrapper_id] = model
                try:
                    model.display = bool(entry.get("display", True))
                except Exception:
                    pass
                return model
            return self._restored_session_layout_model(entry.get("model_type", None), entry.get("model_id", None))

        def apply_children(parent_ref):
            parent_model = resolve_parent(parent_ref)
            if parent_model is None:
                return
            entries = list(children_by_parent.get(ref_key(parent_ref), []))
            entries.sort(
                key=lambda entry: (
                    int(entry.get("order", 0) or 0),
                    str(entry.get("name", "") or ""),
                    str(entry.get("model_id", "") or ""),
                )
            )
            for entry in entries:
                child_model = materialize_entry(entry)
                if child_model is None or child_model is parent_model:
                    continue
                try:
                    parent_model.add([child_model])
                except Exception:
                    try:
                        self.session.models.add([child_model], parent=parent_model)
                    except Exception:
                        pass
                if str(entry.get("node_kind", "model") or "model").strip().lower() == "wrapper":
                    apply_children({"kind": "wrapper", "id": entry.get("wrapper_id", "")})

        apply_children({"kind": "root"})
        for tag in ("star_models", "maps", "membrane"):
            apply_children({"kind": "group", "tag": tag})

    def _session_copy_name(self, model, session_stem, ext):
        import re

        name = str(getattr(model, "name", "") or "model")
        stem = os.path.splitext(name)[0]
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
        session_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(session_stem or "session")).strip("._") or "session"
        return f"{stem or 'model'}__{session_stem}{ext}"

    def _copy_source_file_for_session(self, model, save_dir, session_stem, ext, export_cache):
        if model is None or not save_dir:
            return None
        cache_key = (id(model), str(ext or "").lower())
        if cache_key in export_cache:
            return export_cache[cache_key]

        out_path = os.path.join(save_dir, self._session_copy_name(model, session_stem, ext))
        source_path = self._model_source_path(model)
        if str(ext or "").lower() in (".glb", ".gltf"):
            # Export the live scene model so session saves preserve current recoloring.
            self._export_live_model_copy_for_session(model, out_path, ext)
        elif source_path and os.path.exists(source_path):
            import shutil
            shutil.copy2(source_path, out_path)
        else:
            self._export_live_model_copy_for_session(model, out_path, ext)

        stored = self._store_model_saved_path(model, out_path) or out_path
        export_cache[cache_key] = stored
        return stored

    def _export_live_model_copy_for_session(self, model, out_path, ext):
        display_state = []
        try:
            scan_models = list(self._iter_model_tree(model))
        except Exception:
            scan_models = [model]
        for obj in scan_models:
            try:
                display_state.append((obj, bool(getattr(obj, "display", True))))
                obj.display = True
            except Exception:
                pass
        try:
            ext = str(ext or "").lower()
            if ext in (".glb", ".gltf"):
                from chimerax.gltf.gltf import write_gltf
                write_gltf(self.session, filename=out_path, models=[model])
            elif ext == ".stl":
                from chimerax.stl.stl import write_stl
                write_stl(self.session, out_path, [model])
            else:
                raise RuntimeError(f"Unsupported automatic export type: {ext}")
        finally:
            for obj, shown in display_state:
                try:
                    obj.display = shown
                except Exception:
                    pass

    def _session_model_path(self, model, save_dir=None, session_stem=None, export_cache=None):
        if model is None:
            return None
        if save_dir and session_stem is not None and export_cache is not None:
            source_path = self._model_source_path(model)
            ext = ""
            if source_path:
                ext = os.path.splitext(str(source_path))[1].lower()
            model_name = str(getattr(model, "name", "") or "").lower()
            if ext not in (".glb", ".gltf", ".stl"):
                if self._is_glb_like(model) or model_name.endswith((".glb", ".gltf")):
                    ext = ".glb"
                elif model_name.endswith(".stl") or ("stl" in model.__class__.__name__.lower()):
                    ext = ".stl"
            if ext in (".glb", ".gltf", ".stl"):
                return self._copy_source_file_for_session(model, save_dir, session_stem, ext, export_cache)
        return self._model_source_path(model)

    def _materialize_session_source_replacement(self, target_path, replacement_path):
        target = os.path.abspath(os.path.expanduser(str(target_path or "")))
        replacement = os.path.abspath(os.path.expanduser(str(replacement_path or "")))
        if not target or not replacement:
            return replacement or target
        if target == replacement:
            return target
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
        except Exception:
            pass
        try:
            import shutil
            shutil.copy2(replacement, target)
            return target
        except Exception:
            return replacement

    def _fetch_spec_for_model(self, model):
        if model is None:
            return None
        try:
            emdb_id = getattr(model, "fetch_emdb_id", None)
            if emdb_id:
                return {"fetch_type": "emdb", "fetch_id": str(emdb_id)}
        except Exception:
            pass

        import re

        name = str(getattr(model, "name", "") or "").strip()
        low = name.lower()
        m = re.match(r"^emdb\s+(\d+)$", low)
        if m:
            return {"fetch_type": "emdb", "fetch_id": m.group(1)}
        m = re.match(r"^emd[_ -]?(\d+)(?:\.map)?$", low)
        if m:
            return {"fetch_type": "emdb", "fetch_id": m.group(1)}
        m = re.match(r"^pdb\s+([0-9a-z]{4})$", low)
        if m:
            return {"fetch_type": "pdb", "fetch_id": m.group(1)}
        if self._is_atomic_like(model) and re.match(r"^[0-9a-z]{4}$", low):
            return {"fetch_type": "pdb", "fetch_id": low}
        return None

    def _find_model_by_fetch(self, fetch_type, fetch_id):
        want_type = str(fetch_type or "").strip().lower()
        want_id = str(fetch_id or "").strip().lower()
        if not want_type or not want_id:
            return None
        for model in self._all_session_models():
            spec = self._fetch_spec_for_model(model)
            if spec is None:
                continue
            if str(spec.get("fetch_type", "")).lower() == want_type and str(spec.get("fetch_id", "")).lower() == want_id:
                return model
        return None

    def _choose_opened_source_model(self, opened_models):
        for model in opened_models:
            if self._is_glb_like(model):
                return model
        source_model = self._pick_opened_model(
            opened_models,
            lambda m: self._is_volume_like(m) or self._is_surface_like(m) or self._is_atomic_like(m),
        )
        if source_model is not None:
            return source_model
        return opened_models[-1] if opened_models else None

    def _prompt_session_source_replacement(self, missing_path, label="", reason=""):
        from Qt.QtWidgets import QFileDialog

        title_label = str(label or os.path.basename(str(missing_path or "")) or "session model")
        title = f"Locate model for {title_label}"
        if reason:
            title = f"{title} ({reason})"
        replacement, _ = QFileDialog.getOpenFileName(
            self.tool_window.ui_area,
            title,
            os.path.dirname(str(missing_path or "")) or "",
            "Model files (*.mrc *.map *.ccp4 *.mrcs *.stl *.glb *.gltf *.pdb *.cif *.mmcif);;All files (*)",
        )
        if not replacement:
            raise RuntimeError(f"Session load cancelled. Provide a replacement for {title_label} to continue.")
        return os.path.abspath(os.path.expanduser(str(replacement)))

    def _open_fetch_source_item(self, fetch_type, fetch_id):
        existing = self._find_model_by_fetch(fetch_type, fetch_id)
        if existing is not None:
            return existing
        before = set(self.session.models.list())
        _run(self.session, f"open {fetch_type}:{fetch_id}")
        opened = [m for m in self.session.models.list() if m not in before]
        if not opened:
            return None
        return self._choose_opened_source_model(opened)

    def _open_saved_source_item(self, item, base_dir=""):
        path = item.get("path", None)
        if path:
            path = str(path)
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(base_dir or "", path))
            else:
                path = os.path.abspath(os.path.expanduser(path))
            item["path"] = path

        fetch_type = item.get("fetch_type", None)
        fetch_id = item.get("fetch_id", None)
        if fetch_type and fetch_id:
            try:
                source_model = self._open_fetch_source_item(fetch_type, fetch_id)
                if source_model is not None:
                    if path:
                        self._store_model_saved_path(source_model, path)
                    return source_model
            except Exception:
                pass

        if not path:
            return None

        existing = self._find_model_by_path(path)
        if existing is not None:
            return existing

        open_path = path
        while True:
            if not os.path.exists(open_path):
                replacement_path = self._prompt_session_source_replacement(open_path, item.get("name", ""), "file missing")
                open_path = self._materialize_session_source_replacement(path or open_path, replacement_path)
                item["path"] = open_path
                continue
            before = set(self.session.models.list())
            try:
                _run(self.session, f'open "{open_path}"')
            except Exception as err:
                replacement_path = self._prompt_session_source_replacement(open_path, item.get("name", ""), str(err))
                open_path = self._materialize_session_source_replacement(path or open_path, replacement_path)
                item["path"] = open_path
                continue
            opened = [m for m in self.session.models.list() if m not in before]
            source_model = self._choose_opened_source_model(opened)
            if source_model is None:
                replacement_path = self._prompt_session_source_replacement(
                    open_path, item.get("name", ""), "opened file did not produce a usable map/model"
                )
                open_path = self._materialize_session_source_replacement(path or open_path, replacement_path)
                item["path"] = open_path
                continue
            self._store_model_saved_path(source_model, open_path)
            return source_model

    def _required_float_edit(self, edit, label):
        text = edit.text().strip()
        if not text:
            raise RuntimeError(f"Enter {label}")
        return float(text)

    def _required_int_edit(self, edit, label):
        text = edit.text().strip()
        if not text:
            raise RuntimeError(f"Enter {label}")
        return int(text)

    def _rot_y_matrix(self, deg):
        a = math.radians(float(deg))
        c = math.cos(a)
        s = math.sin(a)
        return np.array(
            [[c, 0.0, s],
             [0.0, 1.0, 0.0],
             [-s, 0.0, c]],
            dtype=float,
        )

    def _rot_x_matrix(self, deg):
        a = math.radians(float(deg))
        c = math.cos(a)
        s = math.sin(a)
        return np.array(
            [[1.0, 0.0, 0.0],
             [0.0, c, -s],
             [0.0, s,  c]],
            dtype=float,
        )

    def _rot_z_matrix(self, deg):
        a = math.radians(float(deg))
        c = math.cos(a)
        s = math.sin(a)
        return np.array(
            [[c, -s, 0.0],
             [s,  c, 0.0],
             [0.0, 0.0, 1.0]],
            dtype=float,
        )

    def _xy90_adjust_matrix(self):
        return self._rot_z_matrix(90.0)

    def _y_control_matrix(self, deg):
        m = self._xy90_adjust_matrix()
        return m.T @ self._rot_y_matrix(deg) @ m

    def _attach_pre_rotate_y_90_enabled(self):
        return bool(self.attach_pre_rotate_y_90.isChecked()) if hasattr(self, "attach_pre_rotate_y_90") else False

    def _attach_pre_rotate_y_90_matrix(self):
        return self._rot_y_matrix(-90.0)

    def _current_attach_adjust_matrix(self, y_deg=None, pre_rotate_y_90=None):
        adjust = np.eye(3, dtype=float)
        if pre_rotate_y_90 is None:
            pre_rotate_y_90 = self._attach_pre_rotate_y_90_enabled()
        if bool(pre_rotate_y_90):
            adjust = self._attach_pre_rotate_y_90_matrix() @ adjust
        if y_deg is None:
            y_deg = float(self.attach_y_rotation.value())
        if abs(y_deg) > 1e-12:
            adjust = self._y_control_matrix(y_deg) @ adjust
        return adjust

    def _model_parent(self, model):
        try:
            return model.parent
        except Exception:
            return None

    def _is_under_cb_group(self, model, tag):
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_group_tag", None) == tag:
                return True
            cur = self._model_parent(cur)
        return False

    def _is_generated_attached_model(self, model):
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_generated_attached", False):
                return True
            cur = self._model_parent(cur)
        return False

    def _is_generated_membrane_model(self, model):
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_generated_membrane", False):
                return True
            cur = self._model_parent(cur)
        return False

    def _is_generated_marker_path_model(self, model):
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_generated_marker_path", False):
                return True
            cur = self._model_parent(cur)
        return False

    def _is_selector_attach_source(self, model):
        if self._is_under_cb_group(model, "star_models"):
            return False
        if not self._is_attach_source(model):
            return False
        if self._is_generated_attached_model(model):
            return False
        if self._is_generated_membrane_model(model):
            return False
        if self._is_generated_marker_path_model(model):
            return False
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_rendered_particles", False):
                return False
            cur = self._model_parent(cur)
        if self._is_surface_like(model):
            parent = self._model_parent(model)
            if parent is not None and self._is_attach_source(parent):
                return False
        return True

    def _model_by_ref(self, model_id):
        want = str(model_id)
        for m in self._all_session_models():
            if m.id_string == want:
                return m
        return None

    def _archive_attach_source_model(self, model):
        if model is None:
            return
        try:
            from .cmd import _add_to_cb_map_group
            model._cb_attach_source = True
            _add_to_cb_map_group(self.session, model)
        except Exception:
            pass
        try:
            model.display = False
        except Exception:
            pass

    def _attach_key(self, star_model, map_model):
        return (id(star_model), id(map_model))

    def _latest_attached_result(self):
        live_items = []
        latest = None
        for attach_key, out_root in list(getattr(self, "_attached_results", {}).items()):
            if out_root is None or self._model_ref(out_root) is None:
                continue
            live_items.append((attach_key, out_root))
            latest = out_root
        if len(live_items) != len(getattr(self, "_attached_results", {})):
            self._attached_results = dict(live_items)
        return latest

    def _update_attachment_undo_button(self):
        if not hasattr(self, "undo_last_attachment_btn"):
            return
        self.undo_last_attachment_btn.setEnabled(self._latest_attached_result() is not None)

    def _register_star_model(self, model):
        if model is None:
            return
        self._known_star_models = [m for m in self._known_star_models if m is not None]
        if any(m is model for m in self._known_star_models):
            return
        self._known_star_models.append(model)

    def _iter_registered_star_models(self):
        seen = set()
        alive = []
        for model in list(self._known_star_models):
            try:
                ref = self._model_ref(model)
            except Exception:
                ref = None
            if model is None or ref is None or not hasattr(model, "_cb_star_rows"):
                continue
            if id(model) in seen:
                continue
            seen.add(id(model))
            alive.append(model)
            yield model
        self._known_star_models = alive

    def _zero_map_origin_index(self, model):
        if model is None:
            return
        if self._is_volume_like(model):
            ref = self._model_ref(model)
            if ref is None:
                return
            try:
                _run(self.session, f"volume #{ref} origin 0,0,0", log=False)
            except Exception:
                pass
            return
        if self._is_surface_like(model) and not self._is_glb_like(model):
            try:
                from chimerax.geometry import Place
                model.position = Place()
            except Exception:
                pass

    def _focus_volume_in_viewer(self, model):
        if model is None or not self._is_volume_like(model):
            return
        ref = self._model_ref(model)
        if ref is None:
            return
        try:
            _run(self.session, "select clear", log=False)
        except Exception:
            pass
        try:
            _run(self.session, f"select #{ref}", log=False)
        except Exception:
            pass
        try:
            _run(self.session, "ui tool show Volume Viewer", log=False)
        except Exception:
            pass

    def _on_attach_selector_changed(self, *_args):
        star_id = self.sel_star_model.currentData() if hasattr(self, "sel_star_model") else None
        map_id = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
        new_key = (str(star_id) if star_id is not None else None, str(map_id) if map_id is not None else None)
        old_key = getattr(self, "_attach_selector_key", None)
        if old_key != new_key:
            self._clear_active_attachment_runtime_state()
        self._attach_selector_key = new_key
        if hasattr(self, "attach_selected_btn"):
            star_ok = bool(star_id)
            map_ok = bool(map_id)
            self.attach_selected_btn.setEnabled(star_ok and map_ok)
        try:
            if map_id:
                self._focus_volume_in_viewer(self._model_by_ref(map_id))
        except Exception:
            pass

    def _clear_active_attachment_runtime_state(self):
        try:
            _run(self.session, "select clear", log=False)
        except Exception:
            pass
        self._last_attach_star_id = None
        self._last_attach_map_id = None
        self._last_attached_result = None

    def _refresh_model_selectors(self):
        star_current = self.sel_star_model.currentData() if hasattr(self, "sel_star_model") else None
        map_current = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
        marker_target_current = self.marker_target_model.currentData() if hasattr(self, "marker_target_model") else None
        geometric_draw_current = self.geometric_draw_model.currentData() if hasattr(self, "geometric_draw_model") else None
        align_z_current = self.align_z_model.currentData() if hasattr(self, "align_z_model") else None
        star_has_models = False
        map_has_models = False

        if hasattr(self, "sel_star_model"):
            self.sel_star_model.blockSignals(True)
            self.sel_star_model.clear()
            self.sel_star_model.addItem("None", None)
            for m in self._all_session_models():
                ref = self._model_ref(m)
                if ref is None or not hasattr(m, "_cb_star_rows"):
                    continue
                label = f"{m.name} (#{ref})"
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
            self.sel_star_model.setEnabled(True)
            self.sel_star_model.blockSignals(False)

        if hasattr(self, "ift_train_star_model"):
            train_star_current = self.ift_train_star_model.currentData()
            self.ift_train_star_model.blockSignals(True)
            self.ift_train_star_model.clear()
            self.ift_train_star_model.addItem("None", None)
            train_star_has_models = False
            for m in self._all_session_models():
                ref = self._model_ref(m)
                if ref is None or not hasattr(m, "_cb_star_rows"):
                    continue
                label = f"{m.name} (#{ref})"
                self.ift_train_star_model.addItem(label, str(ref))
                train_star_has_models = True
            if train_star_current is not None:
                idx = self.ift_train_star_model.findData(str(train_star_current))
                if idx >= 0:
                    self.ift_train_star_model.setCurrentIndex(idx)
                else:
                    self.ift_train_star_model.setCurrentIndex(0)
            else:
                preferred = self.sel_star_model.currentData() if hasattr(self, "sel_star_model") else None
                idx = self.ift_train_star_model.findData(str(preferred)) if preferred is not None else -1
                self.ift_train_star_model.setCurrentIndex(idx if idx >= 0 else 0)
            self.ift_train_star_model.setEnabled(True)
            self.ift_train_star_model.blockSignals(False)

        if hasattr(self, "sel_map_model"):
            self.sel_map_model.blockSignals(True)
            self.sel_map_model.clear()
            self.sel_map_model.addItem("None", None)
            for m in self._selector_attach_models():
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
            self.sel_map_model.setEnabled(True)
            self.sel_map_model.blockSignals(False)

        if hasattr(self, "marker_target_model"):
            self.marker_target_model.blockSignals(True)
            self.marker_target_model.clear()
            self.marker_target_model.addItem("None", None)
            marker_has_models = False
            for m in self._marker_placeable_models():
                ref = self._model_ref(m)
                if ref is None:
                    continue
                label = f"{m.name} (#{ref})"
                self.marker_target_model.addItem(label, str(ref))
                marker_has_models = True
            if marker_target_current is not None:
                idx = self.marker_target_model.findData(str(marker_target_current))
                if idx >= 0:
                    self.marker_target_model.setCurrentIndex(idx)
                else:
                    self.marker_target_model.setCurrentIndex(1 if self.marker_target_model.count() > 1 else 0)
            else:
                preferred = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
                idx = self.marker_target_model.findData(str(preferred)) if preferred is not None else -1
                if idx >= 0:
                    self.marker_target_model.setCurrentIndex(idx)
                else:
                    self.marker_target_model.setCurrentIndex(1 if self.marker_target_model.count() > 1 else 0)
            self.marker_target_model.setEnabled(True)
            self.marker_target_model.blockSignals(False)

        if hasattr(self, "geometric_draw_model"):
            self.geometric_draw_model.blockSignals(True)
            self.geometric_draw_model.clear()
            self.geometric_draw_model.addItem("None", None)
            draw_has_models = False
            for m in self._generated_geometric_drawing_models():
                ref = self._model_ref(m)
                if ref is None:
                    continue
                label = f"{m.name} (#{ref})"
                self.geometric_draw_model.addItem(label, str(ref))
                draw_has_models = True
            if geometric_draw_current is not None:
                idx = self.geometric_draw_model.findData(str(geometric_draw_current))
                if idx >= 0:
                    self.geometric_draw_model.setCurrentIndex(idx)
                else:
                    self.geometric_draw_model.setCurrentIndex(1 if self.geometric_draw_model.count() > 1 else 0)
            else:
                self.geometric_draw_model.setCurrentIndex(1 if self.geometric_draw_model.count() > 1 else 0)
            self.geometric_draw_model.setEnabled(draw_has_models)
            self.geometric_draw_model.blockSignals(False)

        if hasattr(self, "tweak_open_model"):
            tweak_current = self.tweak_open_model.currentData()
            self.tweak_open_model.blockSignals(True)
            self.tweak_open_model.clear()
            self.tweak_open_model.addItem("No open map/STL/GLB/PDB/CIF models", None)
            tweak_has_models = False
            for m in self._selector_attach_models():
                ref = self._model_ref(m)
                if ref is None or not self._is_selector_attach_source(m):
                    continue
                label = f"{m.name} (#{ref})"
                self.tweak_open_model.addItem(label, str(ref))
                tweak_has_models = True
            if tweak_current is not None:
                idx = self.tweak_open_model.findData(str(tweak_current))
                if idx >= 0:
                    self.tweak_open_model.setCurrentIndex(idx)
                else:
                    self.tweak_open_model.setCurrentIndex(1 if self.tweak_open_model.count() > 1 else 0)
            else:
                self.tweak_open_model.setCurrentIndex(1 if self.tweak_open_model.count() > 1 else 0)
            self.tweak_open_model.setEnabled(tweak_has_models)
            self.tweak_open_model.blockSignals(False)

        if hasattr(self, "align_z_model"):
            self.align_z_model.blockSignals(True)
            self.align_z_model.clear()
            self.align_z_model.addItem("None", None)
            align_has_models = False
            for m in self._selector_attach_models():
                ref = self._model_ref(m)
                if ref is None or not self._is_selector_attach_source(m):
                    continue
                label = f"{m.name} (#{ref})"
                self.align_z_model.addItem(label, str(ref))
                align_has_models = True
            if align_z_current is not None:
                idx = self.align_z_model.findData(str(align_z_current))
                if idx >= 0:
                    self.align_z_model.setCurrentIndex(idx)
                else:
                    preferred = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
                    idx = self.align_z_model.findData(str(preferred)) if preferred is not None else -1
                    self.align_z_model.setCurrentIndex(idx if idx >= 0 else (1 if self.align_z_model.count() > 1 else 0))
            else:
                preferred = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
                idx = self.align_z_model.findData(str(preferred)) if preferred is not None else -1
                self.align_z_model.setCurrentIndex(idx if idx >= 0 else (1 if self.align_z_model.count() > 1 else 0))
            self.align_z_model.setEnabled(align_has_models)
            self.align_z_model.blockSignals(False)

        if hasattr(self, "attach_selected_btn"):
            self.attach_selected_btn.setEnabled(star_has_models and map_has_models)
        self._update_attachment_undo_button()
        self._on_attach_selector_changed()
        self._update_marker_path_buttons()

    def _marker_placeable_models(self):
        seen = set()
        maps_group = None
        for model in self._all_session_models():
            if getattr(model, "_cb_group_tag", None) == "maps":
                maps_group = model
                break
        if maps_group is None:
            for model in self._selector_attach_models():
                if model is None or id(model) in seen:
                    continue
                if self._is_generated_marker_path_model(model):
                    continue
                seen.add(id(model))
                yield model
            return
        try:
            children = list(maps_group.child_models())
        except Exception:
            children = []
        for child in children:
            if child is None or id(child) in seen:
                continue
            if self._is_generated_marker_path_model(child):
                continue
            if bool(getattr(child, "_cb_saved_structure_wrapper", False)):
                continue
            seen.add(id(child))
            yield child

    def _generated_geometric_drawing_models(self):
        candidates = []
        for model in self._all_session_models():
            try:
                state = getattr(model, "_cb_marker_path_state", None) or {}
                if not state:
                    continue
                if bool(getattr(model, "_cb_generated_marker_path_temp", False)):
                    continue
                control_points = state.get("control_points", None) or []
                if not control_points:
                    continue
                try:
                    creation_index = int(state.get("creation_index", 0) or 0)
                except Exception:
                    creation_index = 0
                candidates.append(
                    (
                        creation_index,
                        str(getattr(model, "name", "") or ""),
                        model,
                    )
                )
            except Exception:
                continue
        candidates.sort(key=lambda item: (int(item[0]), item[1]))
        for _creation_index, _name, model in candidates:
            yield model

    def _select_star_model(self, model):
        self._refresh_model_selectors()
        ref = self._model_ref(model)
        if ref is None:
            return
        idx = self.sel_star_model.findData(str(ref))
        if idx >= 0:
            self.sel_star_model.setCurrentIndex(idx)

    def _next_loaded_star_name(self, base_name):
        base = str(base_name or "").strip() or "Loaded STAR"
        used = {
            str(getattr(model, "name", "") or "")
            for model in self._all_session_models()
            if hasattr(model, "_cb_star_rows")
        }
        if base not in used:
            return base
        index = 2
        while True:
            candidate = f"{base} {index}"
            if candidate not in used:
                return candidate
            index += 1

    def _remember_loaded_star_role(self, model):
        rows = getattr(model, "_cb_star_rows", None) or []
        if not rows:
            return
        tube_ids = set()
        for row in rows:
            try:
                tube_ids.add(int(float(row.get("rlnHelicalTubeID", 0) or 0)))
            except Exception:
                continue
        positive_ids = sorted(tid for tid in tube_ids if tid > 0)
        model_name = str(getattr(model, "name", "") or "").strip().lower()
        if "central pair" in model_name or (positive_ids and all(tid >= 100 for tid in positive_ids)):
            self._last_cent_star_model = model
            return
        if "microtubule" in model_name:
            self._last_outer_star_model = model

    def _update_ift_type_visibility(self):
        if not hasattr(self, "ift_type"):
            return
        current = str(self.ift_type.currentData() or "anterograde")
        if hasattr(self, "ift_anterograde_angle_row"):
            self.ift_anterograde_angle_row.setVisible(current == "anterograde")
        if hasattr(self, "ift_retrograde_angle_row"):
            self.ift_retrograde_angle_row.setVisible(current == "retrograde")

    def _select_map_model(self, model):
        self._refresh_model_selectors()
        ref = self._model_ref(model)
        if ref is None:
            return
        idx = self.sel_map_model.findData(str(ref))
        if idx >= 0:
            self.sel_map_model.setCurrentIndex(idx)
        self._focus_volume_in_viewer(model)

    def _keep_tool_visible(self):
        try:
            self.tool_window.shown = True
            dw = getattr(self.tool_window, "_dock_widget", None)
            if dw is not None:
                from Qt.QtCore import Qt
                dw.setWindowFlag(Qt.WindowStaysOnTopHint, True)
                dw.show()
                dw.raise_()
                dw.activateWindow()
        except Exception:
            pass

    def _browse_align_z_save(self):
        from Qt.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self.tool_window.ui_area,
            "Save aligned model",
            self.align_z_save_path.text().strip() if hasattr(self, "align_z_save_path") else "",
            "Model files (*.mrc *.map *.ccp4 *.mrcs *.glb *.gltf *.stl *.pdb *.cif *.mmcif);;All files (*)",
        )
        if path and hasattr(self, "align_z_save_path"):
            self.align_z_save_path.setText(str(path))

    def _model_local_center(self, model):
        from .map import _copy_source_instance
        from chimerax.geometry import Place

        probe = _copy_source_instance(self.session, model) if model is not None else None
        target = probe if probe is not None else model
        if target is None:
            return np.zeros(3, dtype=float)
        try:
            try:
                target.position = Place()
            except Exception:
                pass
            bounds = target.bounds()
            if bounds is None:
                return np.zeros(3, dtype=float)
            center = bounds.center()
            return np.array([float(center[0]), float(center[1]), float(center[2])], dtype=float)
        except Exception:
            return np.zeros(3, dtype=float)
        finally:
            if probe is not None:
                try:
                    self.session.models.close([probe])
                except Exception:
                    pass

    def _volume_density_long_axis_local(self, model, max_points=200000):
        if model is None or not self._is_volume_like(model):
            return None
        try:
            matrix = np.array(model.full_matrix(), dtype=np.float32)
        except Exception:
            try:
                data = getattr(model, "data", None)
                matrix = np.array(data.full_matrix(), dtype=np.float32)
            except Exception:
                return None
        if matrix.size == 0:
            return None
        values = np.abs(matrix)
        nz = values[values > 0]
        if nz.size == 0:
            return None
        threshold = float(np.percentile(nz, 80.0))
        mask = values >= threshold
        coords = np.argwhere(mask)
        if len(coords) < 3:
            return None
        weights = values[mask].astype(np.float64)
        if len(coords) > int(max_points):
            step = int(math.ceil(float(len(coords)) / float(max_points)))
            coords = coords[::step]
            weights = weights[::step]
        step_xyz = self._volume_voxel_size(model) or (1.0, 1.0, 1.0)
        xyz = np.column_stack(
            (
                coords[:, 2].astype(np.float64) * float(step_xyz[0]),
                coords[:, 1].astype(np.float64) * float(step_xyz[1]),
                coords[:, 0].astype(np.float64) * float(step_xyz[2]),
            )
        )
        total_weight = float(np.sum(weights))
        if total_weight <= 1e-12:
            return None
        center = np.sum(xyz * weights[:, None], axis=0) / total_weight
        dv = xyz - center[None, :]
        cov = (dv * weights[:, None]).T @ dv
        evals, evecs = np.linalg.eigh(cov)
        axis = np.array(evecs[:, int(np.argmax(evals))], dtype=float)
        norm = float(np.linalg.norm(axis))
        if norm <= 1e-12:
            return None
        axis = axis / norm
        if axis[2] < 0.0:
            axis = -axis
        return axis

    def _auto_z_alignment_axis_local(self, model):
        from .map import _source_long_axis_local

        axis = None
        if self._is_volume_like(model):
            axis = self._volume_density_long_axis_local(model)
        if axis is None:
            try:
                axis = np.array(_source_long_axis_local(self.session, model), dtype=float)
            except Exception:
                axis = None
        if axis is None:
            raise RuntimeError("Could not determine a long axis for the selected model")
        norm = float(np.linalg.norm(axis))
        if norm <= 1e-12:
            raise RuntimeError("Selected model has an invalid long axis")
        axis = axis / norm
        if axis[2] < 0.0:
            axis = -axis
        return axis

    def _rotation_place_about_center(self, center, rotation_matrix):
        from chimerax.geometry import Place

        rot = np.array(rotation_matrix, dtype=float).reshape((3, 3))
        center = np.array(center, dtype=float).reshape((3,))
        origin = center - (rot @ center)
        return Place(axes=(rot[:, 0], rot[:, 1], rot[:, 2]), origin=origin)

    def _default_aligned_save_path(self, model):
        source_path = self._model_source_path(model)
        if source_path:
            stem, ext = os.path.splitext(os.path.abspath(os.path.expanduser(str(source_path))))
            if ext:
                return f"{stem}_z_aligned{ext}"
        name = str(getattr(model, "name", "") or "aligned_model").strip() or "aligned_model"
        if self._is_volume_like(model):
            ext = ".mrc"
        elif self._is_glb_like(model):
            ext = ".glb"
        elif self._is_atomic_like(model):
            ext = ".cif"
        else:
            ext = ".stl"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name).strip("._") or "aligned_model"
        return os.path.abspath(os.path.join(os.path.expanduser("~/"), f"{safe}_z_aligned{ext}"))

    def _unique_output_path(self, path):
        candidate = os.path.abspath(os.path.expanduser(str(path or "")))
        if not candidate:
            return candidate
        if not os.path.exists(candidate):
            return candidate
        stem, ext = os.path.splitext(candidate)
        suffix = 2
        while True:
            probe = f"{stem}_{suffix}{ext}"
            if not os.path.exists(probe):
                return probe
            suffix += 1

    def _auto_z_align_selected_model(self):
        from Qt.QtWidgets import QMessageBox
        from .cmd import _add_to_cb_map_group
        from .map import _copy_source_instance, _rotation_align_vector_to_vector

        def ensure_model_added(model):
            if model is None:
                return
            try:
                if model in self.session.models.list():
                    return
            except Exception:
                pass
            self.session.models.add([model])

        temp_models = []
        temp_paths = []
        try:
            self._refresh_model_selectors()
            model_id = self.align_z_model.currentData() if hasattr(self, "align_z_model") else None
            if model_id is None:
                model_id = self.sel_map_model.currentData() if hasattr(self, "sel_map_model") else None
            if model_id is None:
                raise RuntimeError("Select a map/model to align first")
            source_model = self._model_by_ref(model_id)
            if source_model is None or not self._is_attach_source(source_model):
                raise RuntimeError("Selected model is no longer available for Z alignment")

            save_path = os.path.expanduser(self.align_z_save_path.text().strip()) if hasattr(self, "align_z_save_path") else ""
            if not save_path:
                save_path = self._unique_output_path(self._default_aligned_save_path(source_model))
            save_dir = os.path.dirname(save_path)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True)

            axis = self._auto_z_alignment_axis_local(source_model)
            target_axis = np.array([0.0, 0.0, 1.0], dtype=float)
            rot = np.array(_rotation_align_vector_to_vector(axis, target_axis), dtype=float)
            center = self._model_local_center(source_model)
            transform = self._rotation_place_about_center(center, rot)
            source_color_state = self._capture_model_color_state(source_model)

            if self._is_volume_like(source_model):
                ref_grid = _copy_source_instance(self.session, source_model)
                if ref_grid is None:
                    suffix = os.path.splitext(str(self._model_source_path(source_model) or ""))[1].lower() or ".mrc"
                    fd, temp_ref_path = tempfile.mkstemp(prefix="cb_align_ref_", suffix=suffix)
                    os.close(fd)
                    temp_paths.append(temp_ref_path)
                    _run(self.session, f'save "{temp_ref_path}" #{self._model_ref(source_model)}')
                    before = set(self.session.models.list())
                    _run(self.session, f'open "{temp_ref_path}"')
                    opened = [m for m in self.session.models.list() if m not in before]
                    ref_grid = self._pick_opened_model(opened, self._is_volume_like)
                if ref_grid is None:
                    source_path = self._model_source_path(source_model)
                    if source_path and os.path.exists(source_path):
                        before = set(self.session.models.list())
                        _run(self.session, f'open "{source_path}"')
                        opened = [m for m in self.session.models.list() if m not in before]
                        ref_grid = self._pick_opened_model(opened, self._is_volume_like)
                if ref_grid is None:
                    raise RuntimeError("Could not create a temporary reference grid for the selected map")
                temp_models.append(ref_grid)
                ensure_model_added(ref_grid)
                self._zero_map_origin_index(ref_grid)
                try:
                    ref_grid.position = transform
                except Exception:
                    raise RuntimeError("Could not orient the temporary reference grid")
                try:
                    ref_grid.display = False
                except Exception:
                    pass
                resampled_new = self._command_created_models(
                    f"volume resample #{self._model_ref(source_model)} onGrid #{self._model_ref(ref_grid)}"
                )
                if not resampled_new:
                    raise RuntimeError("volume resample did not create an aligned map")
                aligned_live = self._pick_opened_model(resampled_new, self._is_volume_like)
                if aligned_live is None:
                    raise RuntimeError("volume resample did not create a usable aligned map")
                temp_models.append(aligned_live)
                self._zero_map_origin_index(aligned_live)
            else:
                aligned_live = _copy_source_instance(self.session, source_model)
                if aligned_live is None:
                    raise RuntimeError("Could not copy the selected model for Z alignment")
                temp_models.append(aligned_live)
                ensure_model_added(aligned_live)
                try:
                    aligned_live.position = transform
                except Exception:
                    raise RuntimeError("Could not apply the Z-alignment transform")

            self._apply_model_color_state(aligned_live, source_color_state)
            _run(self.session, f'save "{save_path}" #{self._model_ref(aligned_live)}')

            before = set(self.session.models.list())
            _run(self.session, f'open "{save_path}"')
            reopened = [m for m in self.session.models.list() if m not in before]
            aligned_model = self._choose_opened_source_model(reopened)
            if aligned_model is None:
                raise RuntimeError("Aligned file saved but could not be reopened")
            self._store_model_saved_path(aligned_model, save_path)
            aligned_model._cb_attach_source = True
            self._apply_model_color_state(aligned_model, source_color_state)
            try:
                _add_to_cb_map_group(self.session, aligned_model)
            except Exception:
                pass
            try:
                aligned_model.display = True
            except Exception:
                pass
            self._select_map_model(aligned_model)
            self.session.logger.info(f"Auto Z-aligned model saved: {save_path}")
        except Exception as e:
            self.session.logger.error(str(e))
            if getattr(getattr(self, "tool_window", None), "ui_area", None) is not None:
                QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            for model in temp_models:
                try:
                    self.session.models.close([model])
                except Exception:
                    pass
            for path in temp_paths:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
            self._refresh_model_selectors()
            self._keep_tool_visible()

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

    def _restore_manual_tweak_scene(self):
        for model, visible in self._manual_tweak_hidden:
            try:
                model.display = bool(visible)
            except Exception:
                pass
        self._manual_tweak_hidden = []

    def _model_chain(self, model):
        chain = []
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            chain.append(cur)
            cur = self._model_parent(cur)
        return chain

    def _model_chain_ids(self, model):
        return {id(m) for m in self._model_chain(model)}

    def _set_model_chain_visible(self, model, visible=True):
        for m in reversed(self._model_chain(model)):
            try:
                m.display = bool(visible)
            except Exception:
                pass

    def _iter_top_models(self):
        for model in self.session.models.list():
            if self._model_parent(model) is None:
                yield model

    def _restore_attachment_clip(self):
        planes = getattr(self.session.main_view, "clip_planes", None)
        if planes is not None:
            try:
                planes.remove_plane(self._cb_attachment_clip_plane_name)
            except Exception:
                pass
        if self._cb_attachment_clip_states:
            for model, allow in self._cb_attachment_clip_states:
                try:
                    model.allow_clipping = bool(allow)
                except Exception:
                    pass
        self._cb_attachment_clip_states = None
        try:
            from chimerax import surface
            surface.update_clip_caps(self.session.main_view)
        except Exception:
            pass

    def _set_tree_allow_clipping(self, model, allow):
        for child in self._iter_model_tree(model):
            try:
                child.allow_clipping = bool(allow)
            except Exception:
                pass

    def _apply_attachment_clip_if_needed(self, out_root, star_model):
        clip_info = self._star_random_clip_info(star_model)
        if clip_info is None:
            self._set_tree_allow_clipping(out_root, False)
            return

        self._set_tree_allow_clipping(out_root, True)

        from chimerax.graphics import SceneClipPlane

        planes = self.session.main_view.clip_planes
        try:
            planes.remove_plane(self._cb_attachment_clip_plane_name)
        except Exception:
            pass
        plane = SceneClipPlane(
            self._cb_attachment_clip_plane_name,
            clip_info["axis"],
            clip_info["plane_point"],
        )
        planes.add_plane(plane)
        self._cb_active_attachment_clip = dict(clip_info)
        try:
            from chimerax import surface
            surface.update_clip_caps(self.session.main_view)
        except Exception:
            pass
        self.session.logger.info(
            "Applied random-start clip to attached result at "
            f"{clip_info['clip_start']:.3f} along axis "
            f"({clip_info['axis'][0]:.3f}, {clip_info['axis'][1]:.3f}, {clip_info['axis'][2]:.3f})."
        )

    def _nearest_generated_attached_root(self, model):
        cur = model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            if getattr(cur, "_cb_generated_attached", False):
                return cur
            cur = self._model_parent(cur)
        return None

    def _selected_instance_place(self, model):
        info = self._selected_instance_info(model)
        return None if info is None else info["place"]

    def _selected_instance_info(self, model):
        try:
            spos = model.selected_positions
        except Exception:
            spos = None
        try:
            positions = model.positions
        except Exception:
            positions = None

        if spos is not None and positions is not None:
            try:
                indices = [i for i, flag in enumerate(spos) if bool(flag)]
            except Exception:
                indices = []
            if indices:
                try:
                    idx = int(indices[0])
                    return {"place": positions[idx], "index": idx}
                except Exception:
                    pass

        if positions is not None:
            try:
                if len(positions) == 1:
                    return {"place": positions[0], "index": 0}
            except Exception:
                pass

        try:
            return {"place": model.position, "index": None}
        except Exception:
            return None

    def _selected_attachment_target(self):
        for model in list(self.session.selection.models()):
            root = self._nearest_generated_attached_root(model)
            if root is None:
                continue
            if getattr(root, "_cb_ift_type", None) is not None:
                continue
            place_info = self._selected_instance_info(model)
            if place_info is None:
                continue
            place = place_info["place"]
            star_ref = getattr(root, "_cb_attached_star_ref", None)
            star_model = self._model_by_ref(star_ref) if star_ref is not None else None
            if star_model is None:
                prefix = str(getattr(root, "name", "") or "").split(" <- ", 1)[0].strip()
                if prefix:
                    for candidate in self.session.models.list():
                        if hasattr(candidate, "_cb_star_rows") and str(getattr(candidate, "name", "") or "").strip() == prefix:
                            star_model = candidate
                            break
            if star_model is None:
                continue
            return {
                "selected_model": model,
                "attached_root": root,
                "place": place,
                "selected_index": place_info.get("index", None),
                "star_model": star_model,
            }
        raise RuntimeError("Select one attached filament copy first")

    def _snapshot_attachment_target(self, target):
        place = target["place"]
        return {
            "selected_model_name": str(getattr(target["selected_model"], "name", "") or "").strip(),
            "attached_root_name": str(getattr(target["attached_root"], "name", "") or "").strip(),
            "star_ref": self._model_ref(target["star_model"]),
            "selected_index": target.get("selected_index", None),
            "origin": tuple(float(v) for v in place.origin()),
            "axes": tuple(tuple(float(c) for c in axis) for axis in place.axes()),
        }

    def _attachment_target_from_snapshot(self, snap):
        if not snap:
            return None
        from chimerax.geometry import Place
        star_ref = snap.get("star_ref", None)
        star_model = self._model_by_ref(star_ref) if star_ref is not None else None
        if star_model is None:
            return None
        return {
            "selected_model": None,
            "attached_root": None,
            "place": Place(axes=tuple(snap["axes"]), origin=tuple(snap["origin"])),
            "selected_index": snap.get("selected_index", None),
            "star_model": star_model,
        }

    def _set_ift_pick_hidden_models(self, hidden):
        self._ift_pick_hidden_models = []
        for model in hidden:
            try:
                was_display = bool(getattr(model, "display", True))
            except Exception:
                was_display = True
            self._ift_pick_hidden_models.append((model, was_display))
            try:
                model.display = False
            except Exception:
                pass

    def _restore_ift_pick_hidden_models(self):
        for model, was_display in self._ift_pick_hidden_models:
            try:
                model.display = bool(was_display)
            except Exception:
                pass
        self._ift_pick_hidden_models = []

    def _visible_attached_models(self):
        out = []
        for model in self.session.models.list():
            if not getattr(model, "_cb_generated_attached", False):
                continue
            if getattr(model, "_cb_ift_type", None) is not None:
                continue
            try:
                if not bool(getattr(model, "display", True)):
                    continue
            except Exception:
                pass
            out.append(model)
        return out

    def _selected_star_marker_target(self):
        from chimerax.markers.markers import selected_markers, MarkerSet

        markers = selected_markers(self.session)
        for marker in reversed(list(markers)):
            try:
                marker_set = marker.structure
            except Exception:
                continue
            if not isinstance(marker_set, MarkerSet):
                continue
            cur = marker_set
            seen = set()
            star_model = None
            while cur is not None and id(cur) not in seen:
                seen.add(id(cur))
                if hasattr(cur, "_cb_star_rows"):
                    star_model = cur
                    break
                cur = self._model_parent(cur)
            if star_model is None:
                continue
            row_index = getattr(marker, "_cb_star_row_index", None)
            if row_index is None:
                try:
                    row_index = int(marker.residue.number) - 1
                except Exception:
                    row_index = None
            rows = getattr(star_model, "_cb_star_rows", None) or []
            if row_index is None or not (0 <= int(row_index) < len(rows)):
                continue
            return {
                "star_model": star_model,
                "row_index": int(row_index),
                "row": rows[int(row_index)],
                "marker": marker,
            }
        raise RuntimeError("Click one STAR marker point first")

    def _enable_ift_select_mouse_mode(self):
        try:
            mm = self.session.ui.mouse_modes
            prev = mm.mode('left', [])
            self._ift_prev_left_mouse_mode_name = getattr(prev, "name", None)
            select_mode = mm.named_mode('select')
            if select_mode is not None:
                mm.bind_mouse_mode(mouse_button='left', mouse_modifiers=[], mode=select_mode)
        except Exception:
            try:
                _run(self.session, "ui mousemode left select", log=False)
            except Exception:
                pass

    def _restore_ift_mouse_mode(self):
        name = self._ift_prev_left_mouse_mode_name
        self._ift_prev_left_mouse_mode_name = None
        if not name:
            return
        try:
            mm = self.session.ui.mouse_modes
            mode = mm.named_mode(name)
            if mode is not None:
                mm.bind_mouse_mode(mouse_button='left', mouse_modifiers=[], mode=mode)
                return
        except Exception:
            pass
        try:
            _run(self.session, f"ui mousemode left '{name}'", log=False)
        except Exception:
            pass

    def _ensure_ift_pick_handler(self):
        if self._ift_pick_handlers:
            return
        from chimerax.core.selection import SELECTION_CHANGED
        from chimerax.core.models import MODEL_SELECTION_CHANGED
        self._ift_pick_handlers = [
            self.session.triggers.add_handler(SELECTION_CHANGED, self._on_ift_pick_selection_changed),
            self.session.triggers.add_handler(MODEL_SELECTION_CHANGED, self._on_ift_pick_selection_changed),
        ]

    def _start_ift_pick_mode(self):
        from Qt.QtWidgets import QMessageBox

        try:
            self._restore_ift_pick_hidden_models()
            self._ensure_ift_pick_handler()
            self._ift_pick_pending = True
            self._ift_target_snapshot = None
            self._enable_ift_select_mouse_mode()
            self._set_ift_pick_hidden_models(self._visible_attached_models())
            try:
                _run(self.session, "select clear", log=False)
            except Exception:
                pass
            self.ift_target_label.setText("Click one STAR marker point in ChimeraX")
            self.session.logger.info("IFT pick mode enabled. Attached models hidden temporarily; click one STAR marker point.")
        except Exception as e:
            self._restore_ift_pick_hidden_models()
            self._restore_ift_mouse_mode()
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

    def _on_ift_pick_selection_changed(self, *_args):
        if not self._ift_pick_pending:
            return
        try:
            try:
                star_pick = self._selected_star_marker_target()
            except Exception:
                star_pick = None
            if star_pick is None:
                return
        except Exception:
            return
        try:
            self._ift_pick_pending = False
            self._generate_ift_star_from_star_pick(star_pick)
        except Exception as e:
            from Qt.QtWidgets import QMessageBox
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._restore_ift_pick_hidden_models()
            self._restore_ift_mouse_mode()
            self._keep_tool_visible()

    def _set_marker_path_status(self, text):
        if hasattr(self, "marker_path_status"):
            self.marker_path_status.setText(str(text))

    def _current_geometric_draw_mode(self):
        modes = list(getattr(self, "_geometric_draw_mode_order", ["point", "sphere", "cylinder", "curve", "line"]))
        bar = getattr(self, "geometric_draw_mode_bar", None)
        if bar is not None:
            idx = int(bar.currentIndex())
            if 0 <= idx < len(modes):
                return str(modes[idx])
        if hasattr(self, "marker_path_mode"):
            return "line" if str(self.marker_path_mode.currentData() or "curve").strip().lower() == "line" else "curve"
        return "curve"

    def _set_geometric_draw_mode(self, mode):
        mode = str(mode or "").strip().lower()
        modes = list(getattr(self, "_geometric_draw_mode_order", ["point", "sphere", "cylinder", "curve", "line"]))
        if hasattr(self, "marker_path_mode") and mode in ("curve", "line"):
            idx = self.marker_path_mode.findData(mode)
            if idx >= 0 and self.marker_path_mode.currentIndex() != idx:
                self.marker_path_mode.setCurrentIndex(idx)
        bar = getattr(self, "geometric_draw_mode_bar", None)
        if bar is not None and mode in modes:
            want = modes.index(mode)
            if bar.currentIndex() != want:
                bar.setCurrentIndex(want)

    def _active_geometric_draw_mode(self):
        action = str(getattr(self, "_marker_path_pick_action", "tube") or "tube").strip().lower()
        if action in ("point", "sphere", "cylinder"):
            return action
        if action == "tube":
            return "line" if str(getattr(self, "_marker_path_output_mode", "curve") or "curve").strip().lower() == "line" else "curve"
        return None

    def _geometric_draw_button_text(self, mode=None):
        mode = str(mode or self._current_geometric_draw_mode()).strip().lower()
        return {
            "point": "Place point",
            "sphere": "Place sphere",
            "cylinder": "Draw cylinder",
            "line": "Place line markers",
            "curve": "Place curve markers",
        }.get(mode, "Place curve markers")

    def _geometric_draw_idle_status(self, mode=None):
        mode = str(mode or self._current_geometric_draw_mode()).strip().lower()
        return {
            "point": "Press button, then click in ChimeraX to place a point",
            "sphere": "Press button, then click in ChimeraX to place a sphere",
            "cylinder": "Press button, then click twice in ChimeraX to draw a cylinder",
            "line": "Press button, then click in ChimeraX to place line markers",
            "curve": "Press button, then click in ChimeraX to place curve markers",
        }.get(mode, "Press button, then click in ChimeraX to draw")

    def _update_geometric_draw_controls(self):
        mode = self._current_geometric_draw_mode()
        if mode in ("curve", "line") and hasattr(self, "marker_path_mode"):
            idx = self.marker_path_mode.findData(mode)
            if idx >= 0 and self.marker_path_mode.currentIndex() != idx:
                self.marker_path_mode.setCurrentIndex(idx)
        if hasattr(self, "_geometric_draw_count_row"):
            self._geometric_draw_count_row.setVisible(mode in ("curve", "line"))
        if hasattr(self, "_geometric_draw_primitive_radius_row"):
            self._geometric_draw_primitive_radius_row.setVisible(mode in ("point", "sphere", "cylinder"))
        if hasattr(self, "_geometric_draw_tube_radius_row"):
            self._geometric_draw_tube_radius_row.setVisible(mode in ("curve", "line"))
        if hasattr(self, "geometric_draw_mode_bar"):
            self.geometric_draw_mode_bar.setEnabled(not self._marker_path_pick_pending)
        if not self._marker_path_pick_pending:
            self._set_marker_path_status(self._geometric_draw_idle_status(mode))

    def _on_geometric_draw_mode_changed(self, *_args):
        self._update_geometric_draw_controls()
        self._update_marker_path_buttons()

    def _on_marker_target_model_changed(self, *_args):
        if self._marker_path_pick_pending:
            self._cancel_marker_path_pick_mode(remove_temp=True, log_message=False)

    def _selected_marker_target_model(self):
        model_id = self.marker_target_model.currentData() if hasattr(self, "marker_target_model") else None
        if model_id is None:
            raise RuntimeError("Select a model to mark first")
        model = self._model_by_ref(model_id)
        if model is None:
            raise RuntimeError("Selected marker target model is no longer available")
        return model

    def _set_marker_pick_hidden_models(self, target_model):
        self._restore_marker_pick_hidden_models()
        keep = set()
        for model in self._iter_model_tree(target_model):
            keep.add(id(model))
        cur = target_model
        seen = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            keep.add(id(cur))
            cur = self._model_parent(cur)
        self._marker_path_pick_hidden_models = []
        for model in self.session.models.list():
            if id(model) in keep:
                continue
            try:
                was_display = bool(getattr(model, "display", True))
            except Exception:
                was_display = True
            self._marker_path_pick_hidden_models.append((model, was_display))
            if was_display:
                try:
                    model.display = False
                except Exception:
                    pass

    def _restore_marker_pick_hidden_models(self):
        for model, was_display in self._marker_path_pick_hidden_models:
            try:
                model.display = bool(was_display)
            except Exception:
                pass
        self._marker_path_pick_hidden_models = []

    def _select_marker_target_for_pick(self, model):
        try:
            _run(self.session, "select clear", log=False)
        except Exception:
            pass
        ref = self._model_ref(model)
        if ref is not None:
            try:
                _run(self.session, f"select #{ref}", log=False)
                return
            except Exception:
                pass
        try:
            model.set_selected(True)
        except Exception:
            pass

    def _update_marker_path_buttons(self):
        current_mode = self._current_geometric_draw_mode()
        active_mode = self._active_geometric_draw_mode()
        if hasattr(self, "geometric_draw_pick_btn"):
            same_mode_active = bool(self._marker_path_pick_pending and active_mode == current_mode)
            self.geometric_draw_pick_btn.setText("Cancel drawing" if same_mode_active else self._geometric_draw_button_text(current_mode))
            self.geometric_draw_pick_btn.setEnabled((not self._marker_path_pick_pending) or same_mode_active)
        if hasattr(self, "geometric_draw_save_glb_btn"):
            has_model = bool(
                hasattr(self, "geometric_draw_model")
                and self.geometric_draw_model.currentData() is not None
            )
            self.geometric_draw_save_glb_btn.setEnabled((not self._marker_path_pick_pending) and has_model)
        self._update_geometric_draw_controls()

    def _ensure_marker_path_pick_handler(self):
        if self._marker_path_pick_handlers:
            return
        from chimerax.core.selection import SELECTION_CHANGED
        from chimerax.core.models import MODEL_SELECTION_CHANGED
        from chimerax import atomic

        self._marker_path_pick_handlers = [
            self.session.triggers.add_handler(SELECTION_CHANGED, self._on_marker_path_selection_changed),
            self.session.triggers.add_handler(MODEL_SELECTION_CHANGED, self._on_marker_path_selection_changed),
            atomic.get_triggers().add_handler("changes", self._on_marker_path_atomic_changed),
        ]

    def _ensure_marker_path_poll_timer(self):
        if self._marker_path_poll_timer is not None:
            return self._marker_path_poll_timer
        from Qt.QtCore import QTimer

        parent = getattr(getattr(self, "tool_window", None), "ui_area", None)
        timer = QTimer(parent)
        timer.setInterval(60)
        timer.timeout.connect(self._poll_marker_path_progress)
        self._marker_path_poll_timer = timer
        return timer

    def _enable_marker_path_mouse_mode(self):
        try:
            mm = self.session.ui.mouse_modes
            prev = mm.mode('left', [])
            self._marker_path_prev_left_mouse_mode_name = getattr(prev, "name", None)
            mark_mode = mm.named_mode('mark surface') or mm.named_mode('mark point')
            if mark_mode is not None:
                mm.bind_mouse_mode(mouse_button='left', mouse_modifiers=[], mode=mark_mode)
                return
        except Exception:
            pass
        self._marker_path_prev_left_mouse_mode_name = None
        try:
            _run(self.session, "ui mousemode left 'mark surface'", log=False)
        except Exception:
            try:
                _run(self.session, "ui mousemode left 'mark point'", log=False)
            except Exception:
                pass

    def _restore_marker_path_mouse_mode(self):
        name = self._marker_path_prev_left_mouse_mode_name
        self._marker_path_prev_left_mouse_mode_name = None
        if not name:
            return
        try:
            mm = self.session.ui.mouse_modes
            mode = mm.named_mode(name)
            if mode is not None:
                mm.bind_mouse_mode(mouse_button='left', mouse_modifiers=[], mode=mode)
                return
        except Exception:
            pass
        try:
            _run(self.session, f"ui mousemode left '{name}'", log=False)
        except Exception:
            pass

    def _detach_marker_path_temp_models(self):
        root = self._marker_path_temp_root
        self._marker_path_temp_root = None
        self._marker_path_temp_set = None
        return root

    def _restore_marker_path_marker_settings(self):
        previous = self._marker_path_prev_marker_settings
        self._marker_path_prev_marker_settings = None
        if previous is None:
            return
        try:
            from chimerax.markers.mouse import _mouse_marker_settings

            settings = _mouse_marker_settings(self.session)
            settings.clear()
            settings.update(previous)
        except Exception:
            pass

    def _close_marker_path_temp_root(self):
        root = self._detach_marker_path_temp_models()
        if root is None:
            return
        try:
            self.session.models.close([root])
        except Exception:
            pass

    def _cancel_marker_path_pick_mode(self, remove_temp=True, log_message=False):
        was_pending = bool(self._marker_path_pick_pending)
        self._marker_path_pick_pending = False
        self._marker_path_target_count = 0
        self._marker_path_output_mode = "curve"
        self._marker_path_pick_action = "tube"
        self._marker_path_source_star_ref = None
        try:
            if self._marker_path_poll_timer is not None:
                self._marker_path_poll_timer.stop()
        except Exception:
            pass
        self._restore_marker_path_mouse_mode()
        self._restore_marker_path_marker_settings()
        self._restore_marker_pick_hidden_models()
        if remove_temp:
            self._close_marker_path_temp_root()
        if log_message and was_pending:
            self.session.logger.info("Cancelled drawing mode.")
        self._set_marker_path_status(self._geometric_draw_idle_status())
        self._update_marker_path_buttons()

    def _start_marker_path_pick_mode(self):
        self._start_marker_pick_mode("tube")

    def _start_selected_geometric_draw_pick_mode(self):
        mode = self._current_geometric_draw_mode()
        if mode == "point":
            self._start_marker_pick_mode("point")
        elif mode == "sphere":
            self._start_marker_pick_mode("sphere")
        elif mode == "cylinder":
            self._start_marker_pick_mode("cylinder")
        else:
            self._start_marker_pick_mode("tube", output_mode_override=mode)

    def _start_draw_point_pick_mode(self):
        self._start_marker_pick_mode("point")

    def _start_draw_sphere_pick_mode(self):
        self._start_marker_pick_mode("sphere")

    def _start_draw_cylinder_pick_mode(self):
        self._start_marker_pick_mode("cylinder")

    def _start_marker_pattern_star_pick_mode(self):
        from Qt.QtWidgets import QMessageBox

        try:
            if self._marker_path_pick_pending:
                raise RuntimeError("Finish or cancel marker placement first")
            source_star_model = self._selected_marker_pattern_star_model()
            _template_model, control_points, output_mode, tube_radius = self._marker_path_template_details()
            created = self._create_marker_pattern_star_from_points(
                control_points,
                self._model_ref(source_star_model),
            )
            auto_paths = self._auto_draw_marker_pattern_paths(created, output_mode, tube_radius)
            self._hide_generated_marker_pattern_star(created)
            self._set_marker_path_status(f"Generated: {created.name}")
            self.session.logger.info(
                f"Generated {created.name} from {len(control_points)} template markers "
                f"({len(getattr(created, '_cb_star_rows', None) or [])} STAR points, {len(auto_paths)} auto paths). "
                "Use the normal map attachment section to attach your model."
            )
            self._refresh_model_selectors()
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

    def _selected_geometric_drawing_model(self):
        model_id = self.geometric_draw_model.currentData() if hasattr(self, "geometric_draw_model") else None
        if model_id is None:
            raise RuntimeError("Select a geometric drawing model first")
        model = self._model_by_ref(model_id)
        if model is None or not getattr(model, "_cb_marker_path_state", None):
            raise RuntimeError("Select a geometric drawing model first")
        return model

    def _save_selected_geometric_drawing_glb(self):
        from Qt.QtWidgets import QFileDialog, QMessageBox

        try:
            if self._marker_path_pick_pending:
                raise RuntimeError("Finish or cancel drawing first")
            drawing_model = self._selected_geometric_drawing_model()
            default_name = self._session_copy_name(drawing_model, "drawing", ".glb")
            path, _ = QFileDialog.getSaveFileName(
                self.tool_window.ui_area,
                "Save geometric drawing as GLB",
                default_name,
                "GLB files (*.glb);;All files (*)",
            )
            if not path:
                return
            if not str(path).lower().endswith(".glb"):
                path = f"{path}.glb"
            out_path = os.path.abspath(os.path.expanduser(str(path)))
            out_dir = os.path.dirname(out_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            self._export_live_model_copy_for_session(drawing_model, out_path, ".glb")
            self._store_model_saved_path(drawing_model, out_path)

            before = set(self.session.models.list())
            _run(self.session, f'open "{out_path}"')
            opened = [m for m in self.session.models.list() if m not in before]
            opened_model = self._choose_opened_source_model(opened)
            if opened_model is not None:
                self._store_model_saved_path(opened_model, out_path)
                self._select_map_model(opened_model)
            self._set_marker_path_status(f"Saved GLB: {os.path.basename(out_path)}")
            if opened_model is not None:
                self.session.logger.info(
                    f"Saved geometric drawing {drawing_model.name} as GLB: {out_path}. "
                    f"Opened attachable model {opened_model.name}."
                )
            else:
                self.session.logger.info(f"Saved geometric drawing {drawing_model.name} as GLB: {out_path}.")
            self._refresh_model_selectors()
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

    def _selected_marker_pattern_star_model(self):
        star_id = self.sel_star_model.currentData() if hasattr(self, "sel_star_model") else None
        if star_id is None:
            raise RuntimeError("Select a STAR model first")
        star_model = self._model_by_ref(star_id)
        if star_model is None or not hasattr(star_model, "_cb_star_rows"):
            raise RuntimeError("Select a STAR model first")
        return star_model

    def _marker_path_template_details(self):
        def _state_for(model):
            state = getattr(model, "_cb_marker_path_state", None) or {}
            control_points = state.get("control_points", None) or []
            if len(control_points) < 2:
                return None
            role = str(state.get("role", getattr(model, "_cb_marker_path_role", "") or "") or "").strip().lower()
            if role and role != "template":
                return None
            try:
                creation_index = int(state.get("creation_index", 0) or 0)
            except Exception:
                creation_index = 0
            path_mode = str(state.get("path_mode", "curve") or "curve").strip().lower() or "curve"
            if path_mode not in ("curve", "line"):
                path_mode = "curve"
            try:
                tube_radius = max(0.1, float(state.get("tube_radius", state.get("radius", 20.0)) or 20.0))
            except Exception:
                tube_radius = 20.0
            return {
                "model": model,
                "state": state,
                "control_points": [[float(v) for v in point[:3]] for point in control_points],
                "path_mode": path_mode,
                "tube_radius": tube_radius,
                "creation_index": creation_index,
            }

        template_model = self._model_by_ref(self._marker_path_template_ref) if self._marker_path_template_ref else None
        preferred = _state_for(template_model) if template_model is not None else None
        if preferred is None:
            candidates = []
            for model in self._all_session_models():
                info = _state_for(model)
                if info is not None:
                    candidates.append(info)
            if candidates:
                preferred = max(
                    candidates,
                    key=lambda item: (
                        int(item["creation_index"]),
                        str(getattr(item["model"], "name", "") or ""),
                    ),
                )
        if preferred is None:
            raise RuntimeError("Create a marker path first with 'Place markers for path'")
        self._marker_path_template_ref = self._model_ref(preferred["model"])
        return (
            preferred["model"],
            preferred["control_points"],
            preferred["path_mode"],
            preferred["tube_radius"],
        )

    def _start_marker_pick_mode(self, pick_action, output_mode_override=None):
        from Qt.QtWidgets import QMessageBox
        from chimerax.markers.markers import MarkerSet
        from chimerax.markers.mouse import _mouse_marker_settings
        from . import cmd

        try:
            if self._marker_path_pick_pending:
                if str(self._marker_path_pick_action or "tube") == str(pick_action or "tube"):
                    self._cancel_marker_path_pick_mode(remove_temp=True, log_message=True)
                    return
                self._cancel_marker_path_pick_mode(remove_temp=True, log_message=False)

            target_count = int(self.marker_path_count.value()) if hasattr(self, "marker_path_count") else 2
            output_mode = str(output_mode_override or (self.marker_path_mode.currentData() if hasattr(self, "marker_path_mode") else "curve") or "curve")
            output_mode = output_mode.strip().lower() or "curve"
            if output_mode not in ("curve", "line"):
                output_mode = "curve"
            pick_action = str(pick_action or "tube").strip().lower()
            if pick_action not in ("tube", "replicated_star", "point", "sphere", "cylinder"):
                pick_action = "tube"
            if pick_action in ("point", "sphere"):
                target_count = 1
            elif pick_action == "cylinder":
                target_count = 2
            elif target_count < 2:
                raise RuntimeError("Marker path needs at least 2 markers")
            target_model = self._selected_marker_target_model()
            source_star_model = None
            if pick_action == "replicated_star":
                source_star_model = self._selected_marker_pattern_star_model()

            self._cancel_marker_path_pick_mode(remove_temp=True, log_message=False)
            self._ensure_marker_path_pick_handler()
            self._set_marker_pick_hidden_models(target_model)
            temp_set = MarkerSet(self.session, name="Control markers")
            temp_set._cb_generated_marker_path = True
            temp_set._cb_generated_marker_path_temp = True
            temp_set._cb_attach_source = False
            cmd._add_to_cb_map_group(self.session, temp_set)
            try:
                temp_set.display = True
            except Exception:
                pass
            try:
                temp_set.ball_scale = 1.0
            except Exception:
                pass

            settings = _mouse_marker_settings(self.session)
            self._marker_path_prev_marker_settings = dict(settings)
            settings["marker set"] = temp_set
            settings["next_marker_num"] = 1
            settings["marker color"] = (255, 170, 70, 255)
            settings["marker radius"] = 6.0
            settings["link_new_markers"] = False

            self._marker_path_temp_root = temp_set
            self._marker_path_temp_set = temp_set
            self._marker_path_target_count = int(target_count)
            self._marker_path_output_mode = output_mode
            self._marker_path_pick_action = pick_action
            self._marker_path_source_star_ref = self._model_ref(source_star_model) if source_star_model is not None else None
            self._marker_path_pick_pending = True
            self._ensure_marker_path_poll_timer().start()
            self._enable_marker_path_mouse_mode()
            self._select_marker_target_for_pick(target_model)
            self._set_marker_path_status(
                f"Drawing active: 0/{self._marker_path_target_count} placed. Click in ChimeraX."
            )
            self._update_marker_path_buttons()
            target_name = str(getattr(target_model, "name", "") or "").strip() or "selected model"
            if pick_action == "replicated_star":
                source_name = str(getattr(source_star_model, "name", "") or "").strip() or "selected STAR"
                self.session.logger.info(
                    "Marker placement mode enabled. "
                    f"Place {self._marker_path_target_count} markers on {target_name} in ChimeraX to build a replicated STAR from {source_name}."
                )
            elif pick_action == "point":
                self.session.logger.info(
                    "Marker placement mode enabled. "
                    f"Click once on {target_name} in ChimeraX to place a point."
                )
            elif pick_action == "sphere":
                self.session.logger.info(
                    "Marker placement mode enabled. "
                    f"Click once on {target_name} in ChimeraX to place a sphere."
                )
            elif pick_action == "cylinder":
                self.session.logger.info(
                    "Marker placement mode enabled. "
                    f"Click twice on {target_name} in ChimeraX to draw a cylinder."
                )
            else:
                self.session.logger.info(
                    "Marker placement mode enabled. "
                    f"Place {self._marker_path_target_count} markers on {target_name} in ChimeraX to build a {output_mode} tube."
                )
        except Exception as e:
            self._cancel_marker_path_pick_mode(remove_temp=True, log_message=False)
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

    def _marker_path_control_points_from_set(self, marker_set):
        if marker_set is None:
            return []
        try:
            atoms = list(marker_set.atoms)
        except Exception:
            atoms = []
        ordered = []
        for atom in atoms:
            try:
                order = int(atom.residue.number)
            except Exception:
                order = len(ordered) + 1
            try:
                xyz = atom.scene_coord
                point = [float(xyz[0]), float(xyz[1]), float(xyz[2])]
            except Exception:
                continue
            ordered.append((order, point))
        ordered.sort(key=lambda item: item[0])
        return [point for _order, point in ordered]

    def _next_marker_path_name(self, mode):
        display_mode = "Curve" if str(mode or "").lower() == "curve" else "Line"
        while True:
            self._marker_path_counter += 1
            name = f"Marker {display_mode} {self._marker_path_counter}"
            if self._find_model_by_name(name, require_star=False) is None:
                return name

    def _next_marker_pattern_group_name(self, star_model_name):
        base = f"{str(star_model_name or '').strip() or 'Marker Applied STAR'} Paths"
        name = base
        suffix = 2
        while self._find_model_by_name(name, require_star=False) is not None:
            name = f"{base} {suffix}"
            suffix += 1
        return name

    def _next_geometric_drawing_name(self, kind):
        base = str(kind or "Drawing").strip() or "Drawing"
        while True:
            self._geometric_draw_counter += 1
            name = f"{base} {self._geometric_draw_counter}"
            if self._find_model_by_name(name, require_star=False) is None:
                return name

    def _create_marker_path_from_points(self, control_points, path_mode):
        from . import cmd

        mode = str(path_mode or "curve").strip().lower()
        if mode not in ("curve", "line"):
            mode = "curve"
        name = self._next_marker_path_name(mode)
        tube_radius = float(self.marker_path_radius.value()) if hasattr(self, "marker_path_radius") else 20.0
        created = cmd.build_marker_path_model(
            self.session,
            name=name,
            control_points=control_points,
            path_mode=mode,
            tube_radius=tube_radius,
        )
        try:
            state = getattr(created, "_cb_marker_path_state", None) or {}
            state["role"] = "template"
            state["creation_index"] = int(self._marker_path_counter)
            created._cb_marker_path_state = state
            created._cb_marker_path_role = "template"
            self._marker_path_template_ref = self._model_ref(created)
        except Exception:
            pass
        return created

    def _create_point_drawing_from_points(self, control_points, sphere_mode=False):
        from . import cmd

        if not control_points:
            raise RuntimeError("Point drawing needs at least 1 picked point")
        radius = float(self.draw_marker_radius.value()) if hasattr(self, "draw_marker_radius") else 12.0
        point_radius = max(1.0, radius if sphere_mode else (0.35 * radius))
        name = self._next_geometric_drawing_name("Sphere" if sphere_mode else "Point")
        created = cmd.build_marker_point_model(
            self.session,
            name=name,
            control_points=[control_points[0]],
            marker_radius=point_radius,
            display_mode="sphere_marker" if sphere_mode else "point_marker",
        )
        try:
            state = getattr(created, "_cb_marker_path_state", None) or {}
            state["role"] = "drawing"
            created._cb_marker_path_state = state
            created._cb_marker_path_role = "drawing"
        except Exception:
            pass
        return created

    def _create_cylinder_from_points(self, control_points):
        from . import cmd

        if len(control_points) < 2:
            raise RuntimeError("Cylinder drawing needs 2 picked points")
        radius = float(self.draw_marker_radius.value()) if hasattr(self, "draw_marker_radius") else 12.0
        name = self._next_geometric_drawing_name("Cylinder")
        created = cmd.build_marker_path_model(
            self.session,
            name=name,
            control_points=control_points[:2],
            path_mode="line",
            tube_radius=radius,
        )
        try:
            state = getattr(created, "_cb_marker_path_state", None) or {}
            state["role"] = "drawing"
            state["display_mode"] = "cylinder_tube"
            created._cb_marker_path_state = state
            created._cb_marker_path_role = "drawing"
        except Exception:
            pass
        return created

    def _resolved_axes_from_row(self, row):
        from .map import _particle_axes_from_row

        ex, ey, ez = _particle_axes_from_row(row)
        return (
            np.array(ex, dtype=float),
            np.array(ey, dtype=float),
            np.array(ez, dtype=float),
        )

    def _nearest_star_row_for_point(self, star_model, point):
        rows = getattr(star_model, "_cb_star_rows", None) or []
        if not rows:
            raise RuntimeError("Selected STAR model has no rows")
        want = np.array(point, dtype=float)
        best = None
        for row_index, row in enumerate(rows):
            center = self._row_world_center(row)
            delta = want - center
            distance_sq = float(np.dot(delta, delta))
            if best is None or distance_sq < best["distance_sq"]:
                best = {
                    "row_index": int(row_index),
                    "row": row,
                    "center": center,
                    "distance_sq": distance_sq,
                }
        if best is None:
            raise RuntimeError("Could not find a nearest STAR row for a placed marker")
        return best

    def _create_marker_pattern_star_from_points(self, control_points, source_star_ref):
        from . import cmd
        from .io import rows_to_star_text

        star_model = self._model_by_ref(source_star_ref) if source_star_ref is not None else None
        if star_model is None or not hasattr(star_model, "_cb_star_rows"):
            raise RuntimeError("Selected STAR model is no longer available")
        source_rows = getattr(star_model, "_cb_star_rows", None) or []
        if not source_rows:
            raise RuntimeError("Selected STAR model has no rows")

        pattern_specs = []
        for marker_index, point in enumerate(control_points):
            nearest = self._nearest_star_row_for_point(star_model, point)
            ex, ey, ez = self._resolved_axes_from_row(nearest["row"])
            delta = np.array(point, dtype=float) - nearest["center"]
            local_offset = np.array(
                [
                    float(np.dot(delta, ex)),
                    float(np.dot(delta, ey)),
                    float(np.dot(delta, ez)),
                ],
                dtype=float,
            )
            pattern_specs.append(
                {
                    "marker_index": int(marker_index),
                    "source_row_index": int(nearest["row_index"]),
                    "local_offset": local_offset,
                }
            )

        class_num = cmd._next_class_number()
        star_rows = []
        for target_index, target_row in enumerate(source_rows):
            target_center = self._row_world_center(target_row)
            ex, ey, ez = self._resolved_axes_from_row(target_row)
            try:
                target_px = float(target_row.get("rlnImagePixelSize", 1.0) or 1.0)
            except Exception:
                target_px = 1.0
            if target_px <= 0.0:
                target_px = 1.0
            try:
                tube_id = int(float(target_row.get("rlnHelicalTubeID", 1)))
            except Exception:
                tube_id = 1
            for spec in pattern_specs:
                local_offset = np.array(spec["local_offset"], dtype=float)
                world = target_center + ex * local_offset[0] + ey * local_offset[1] + ez * local_offset[2]
                star_rows.append(
                    {
                        "rlnTomoName": str(target_row.get("rlnTomoName", "TS_001")),
                        "rlnCoordinateX": float(world[0]) / float(target_px),
                        "rlnCoordinateY": float(world[1]) / float(target_px),
                        "rlnCoordinateZ": float(world[2]) / float(target_px),
                        "rlnAngleRot": float(target_row.get("rlnAngleRot", 0.0) or 0.0),
                        "rlnAngleTilt": float(target_row.get("rlnAngleTilt", 0.0) or 0.0),
                        "rlnAnglePsi": float(target_row.get("rlnAnglePsi", 0.0) or 0.0),
                        "rlnImagePixelSize": float(target_px),
                        "rlnHelicalTubeID": int(tube_id),
                        "rlnClassNumber": int(class_num),
                        "_cbWorldCoordinateX": float(world[0]),
                        "_cbWorldCoordinateY": float(world[1]),
                        "_cbWorldCoordinateZ": float(world[2]),
                        "_cbAxisX": [float(v) for v in ex],
                        "_cbAxisY": [float(v) for v in ey],
                        "_cbAxisZ": [float(v) for v in ez],
                        "_cb_source_star_ref": source_star_ref,
                        "_cb_source_star_row_index": int(target_index),
                        "_cb_marker_pattern_target_row_index": int(target_index),
                        "_cb_marker_pattern_marker_index": int(spec["marker_index"]),
                        "_cb_marker_pattern_anchor_row_index": int(spec["source_row_index"]),
                        "_cb_marker_pattern_local_offset": [float(v) for v in local_offset],
                    }
                )

        if not star_rows:
            raise RuntimeError("No STAR rows were generated from the placed markers")

        name = f"Marker Applied STAR {class_num}"
        star_text = rows_to_star_text(star_rows)
        created = cmd._create_star_model(
            self.session,
            name,
            star_rows,
            star_text,
            True,
            "relion",
            True,
            False,
        )
        try:
            created._cb_marker_pattern_source_star_ref = source_star_ref
            created._cb_marker_pattern_marker_count = int(len(pattern_specs))
        except Exception:
            pass
        self._inherit_clip_info(created, star_model)
        self._select_star_model(created)
        return created

    def _auto_draw_marker_pattern_paths(self, star_model, path_mode, tube_radius):
        from . import cmd
        from chimerax.core.models import Model

        rows = getattr(star_model, "_cb_star_rows", None) or []
        groups = {}
        for row in rows:
            try:
                target_row_index = int(
                    row.get(
                        "_cb_marker_pattern_target_row_index",
                        row.get("_cb_source_star_row_index", -1),
                    )
                )
            except Exception:
                target_row_index = -1
            if target_row_index < 0:
                continue
            groups.setdefault(target_row_index, []).append(row)

        created_paths = []
        mode = str(path_mode or "curve").strip().lower()
        if mode not in ("curve", "line"):
            mode = "curve"
        radius = max(0.1, float(tube_radius))
        group_root = None
        group_name = self._next_marker_pattern_group_name(getattr(star_model, "name", "Marker Applied STAR"))

        for target_row_index, group_rows in sorted(groups.items()):
            group_rows.sort(
                key=lambda row: (
                    int(row.get("_cb_marker_pattern_marker_index", 0) or 0),
                    int(row.get("_cb_marker_pattern_anchor_row_index", 0) or 0),
                )
            )
            control_points = [
                [float(v) for v in self._row_world_center(row)]
                for row in group_rows
            ]
            if len(control_points) < 2:
                continue
            first_row = group_rows[0]
            try:
                tube_id = int(float(first_row.get("rlnHelicalTubeID", 0)))
            except Exception:
                tube_id = 0
            if group_root is None:
                group_root = Model(group_name, self.session)
                group_root._cb_generated_marker_path = True
                group_root._cb_attach_source = False
                group_root._cb_marker_path_role = "replicated_auto_group"
                group_root._cb_marker_pattern_source_star_ref = self._model_ref(star_model)
                cmd._add_to_cb_map_group(self.session, group_root)
            name = f"{star_model.name} Path t{tube_id} g{target_row_index + 1}"
            created = cmd.build_marker_path_model(
                self.session,
                name=name,
                control_points=control_points,
                path_mode=mode,
                tube_radius=radius,
            )
            try:
                state = getattr(created, "_cb_marker_path_state", None) or {}
                state["role"] = "replicated_auto"
                state["marker_pattern_source_star_ref"] = self._model_ref(star_model)
                state["marker_pattern_target_row_index"] = int(target_row_index)
                state["marker_pattern_group_name"] = str(group_name)
                created._cb_marker_path_state = state
                created._cb_marker_path_role = "replicated_auto"
            except Exception:
                pass
            try:
                group_root.add([created])
            except Exception:
                pass
            created_paths.append(created)
        if group_root is not None and not created_paths:
            try:
                self.session.models.close([group_root])
            except Exception:
                pass
        return created_paths

    def _hide_generated_marker_pattern_star(self, star_model):
        if star_model is None:
            return
        try:
            star_model.display = False
        except Exception:
            pass

    def _finalize_marker_path_pick_result(self, control_points, output_mode, pick_action, source_star_ref, temp_root):
        from Qt.QtCore import QTimer
        from Qt.QtWidgets import QMessageBox

        def _finish():
            try:
                try:
                    _run(self.session, "select clear", log=False)
                except Exception:
                    pass
                if temp_root is not None:
                    try:
                        self.session.models.close([temp_root])
                    except Exception:
                        pass
                if str(pick_action or "tube") == "replicated_star":
                    created = self._create_marker_pattern_star_from_points(control_points, source_star_ref)
                    auto_paths = self._auto_draw_marker_pattern_paths(
                        created,
                        output_mode,
                        float(self.marker_path_radius.value()) if hasattr(self, "marker_path_radius") else 20.0,
                    )
                    self._hide_generated_marker_pattern_star(created)
                    self._set_marker_path_status(f"Generated: {created.name}")
                    self.session.logger.info(
                        f"Generated {created.name} from {len(control_points)} placed markers "
                        f"({len(getattr(created, '_cb_star_rows', None) or [])} STAR points, {len(auto_paths)} auto paths). "
                        "Use the normal map attachment section to attach your model."
                    )
                elif str(pick_action or "tube") == "point":
                    created = self._create_point_drawing_from_points(control_points, sphere_mode=False)
                    self._set_marker_path_status(f"Generated: {created.name}")
                    self.session.logger.info(f"Generated {created.name} from 1 placed point.")
                elif str(pick_action or "tube") == "sphere":
                    created = self._create_point_drawing_from_points(control_points, sphere_mode=True)
                    self._set_marker_path_status(f"Generated: {created.name}")
                    self.session.logger.info(f"Generated {created.name} from 1 placed point.")
                elif str(pick_action or "tube") == "cylinder":
                    created = self._create_cylinder_from_points(control_points)
                    self._set_marker_path_status(f"Generated: {created.name}")
                    self.session.logger.info(f"Generated {created.name} from 2 placed points.")
                else:
                    created = self._create_marker_path_from_points(control_points, output_mode)
                    self._set_marker_path_status(f"Generated: {created.name}")
                    self.session.logger.info(
                        f"Generated {created.name} from {len(control_points)} placed markers."
                    )
            except Exception as e:
                self.session.logger.error(str(e))
                QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
            finally:
                self._refresh_model_selectors()
                self._keep_tool_visible()

        QTimer.singleShot(0, _finish)

    def _poll_marker_path_progress(self):
        if not self._marker_path_pick_pending:
            try:
                if self._marker_path_poll_timer is not None:
                    self._marker_path_poll_timer.stop()
            except Exception:
                pass
            return
        marker_set = self._marker_path_temp_set
        if marker_set is None:
            self._cancel_marker_path_pick_mode(remove_temp=False, log_message=False)
            return
        try:
            count = int(len(marker_set.residues))
        except Exception:
            try:
                count = int(len(marker_set.atoms))
            except Exception:
                count = 0
        if count <= 0:
            return
        self._set_marker_path_status(
            f"Drawing active: {count}/{self._marker_path_target_count} placed. Click in ChimeraX."
        )
        if count < self._marker_path_target_count:
            return
        try:
            control_points = self._marker_path_control_points_from_set(marker_set)
            output_mode = self._marker_path_output_mode
            pick_action = self._marker_path_pick_action
            source_star_ref = self._marker_path_source_star_ref
            temp_root = self._detach_marker_path_temp_models()
            self._cancel_marker_path_pick_mode(remove_temp=False, log_message=False)
            self._finalize_marker_path_pick_result(
                control_points,
                output_mode,
                pick_action,
                source_star_ref,
                temp_root,
            )
        except Exception as e:
            from Qt.QtWidgets import QMessageBox

            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _on_marker_path_selection_changed(self, *_args):
        self._poll_marker_path_progress()

    def _on_marker_path_atomic_changed(self, *_args):
        self._poll_marker_path_progress()

    def _ift_train_geometry(self, star_model, tube_id):
        rows = getattr(star_model, "_cb_star_rows", None) or []
        tube_rows = []
        for row in rows:
            try:
                if int(float(row.get("rlnHelicalTubeID", 0))) != int(tube_id):
                    continue
            except Exception:
                continue
            tube_rows.append(row)
        if not tube_rows:
            raise RuntimeError(f"Target STAR model has no rows for doublet {tube_id}")

        points = [self._row_world_center(row) for row in tube_rows]
        if len(points) >= 2:
            line_vec = np.array(points[-1], dtype=float) - np.array(points[0], dtype=float)
            norm = float(np.linalg.norm(line_vec))
            line_axis = (line_vec / norm) if norm > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=float)
        else:
            ex, ey, ez = self._axes_from_star_row(tube_rows[0])
            line_axis = np.array(ez, dtype=float)
        line_axis = line_axis / max(float(np.linalg.norm(line_axis)), 1e-12)

        scalars = [float(np.dot(np.array(p, dtype=float), line_axis)) for p in points]
        order = np.argsort(scalars)
        ordered_rows = [tube_rows[i] for i in order]
        ordered_points = [np.array(points[i], dtype=float) for i in order]
        start_point = np.array(ordered_points[0], dtype=float)
        start_scalar = float(np.dot(start_point, line_axis))

        return {
            "rows": ordered_rows,
            "points": ordered_points,
            "line_axis": line_axis,
            "start_point": start_point,
            "start_scalar": start_scalar,
        }

    def _build_ift_train_star(self):
        from Qt.QtWidgets import QMessageBox
        from . import cmd
        from .io import rows_to_star_text
        from .map import _rotation_about_axis

        try:
            self._refresh_model_selectors()
            star_ref = self.ift_train_star_model.currentData() if hasattr(self, "ift_train_star_model") else None
            if star_ref is None:
                raise RuntimeError("Select a target STAR model for the IFT train")
            star_model = self._model_by_ref(star_ref)
            if star_model is None or not hasattr(star_model, "_cb_star_rows"):
                raise RuntimeError("Target STAR model for the IFT train is not available")

            tube_id = self._required_int_edit(self.ift_train_doublet, "Microtubule number")
            base_angle_deg = self._required_float_edit(self.ift_train_angle, "Angle")
            offset_ang = self._required_float_edit(self.ift_train_offset, "Offset")
            periodicity_ang = self._required_float_edit(self.ift_train_periodicity, "Periodicity")
            repeat_count = self._required_int_edit(self.ift_train_repeat, "Repeating number")
            if periodicity_ang <= 0.0:
                raise RuntimeError("Periodicity must be > 0")
            if repeat_count <= 0:
                raise RuntimeError("Repeating number must be > 0")

            ift_type = str(self.ift_type.currentData() or "anterograde")
            anterograde_angle = float(self.ift_anterograde_angle.value())
            retrograde_angle = float(self.ift_retrograde_angle.value())
            type_angle_deg = -float(retrograde_angle) if ift_type == "retrograde" else float(anterograde_angle)
            angle_deg = base_angle_deg + type_angle_deg

            geom = self._ift_train_geometry(star_model, tube_id)
            source_rows = geom["rows"]
            line_axis = np.array(geom["line_axis"], dtype=float)
            start_point = np.array(geom["start_point"], dtype=float)
            star_center = self._star_scene_center(star_model)

            radial_seed = start_point - np.array(star_center, dtype=float)
            radial_seed = radial_seed - line_axis * float(np.dot(radial_seed, line_axis))
            radial_norm = float(np.linalg.norm(radial_seed))
            if radial_norm < 1e-9:
                raise RuntimeError("Could not determine radial direction for the selected doublet")
            radial_dir = radial_seed / radial_norm

            spin_rot = _rotation_about_axis(line_axis, angle_deg)
            rotated_radial = spin_rot @ radial_dir
            class_num = cmd._next_class_number()

            try:
                pixel_size = float(source_rows[0].get("rlnImagePixelSize", 1.0) or 1.0)
            except Exception:
                pixel_size = 1.0
            if pixel_size <= 0.0:
                pixel_size = 1.0

            ex, ey, ez = self._axes_from_star_row(source_rows[0])
            base_axes = [np.array(ex, dtype=float), np.array(ey, dtype=float), np.array(ez, dtype=float)]
            basis_axes = [spin_rot @ axis for axis in base_axes]

            star_rows = []
            for idx in range(repeat_count):
                target_point = start_point + line_axis * float(offset_ang + idx * periodicity_ang)
                axial_component = float(np.dot(target_point - np.array(star_center, dtype=float), line_axis))
                ift_origin = (
                    np.array(star_center, dtype=float)
                    + rotated_radial * float(self.ift_distance.value())
                    + line_axis * axial_component
                )
                star_rows.append(
                    {
                        "rlnTomoName": str(source_rows[0].get("rlnTomoName", "TS_001")),
                        "rlnCoordinateX": float(ift_origin[0]),
                        "rlnCoordinateY": float(ift_origin[1]),
                        "rlnCoordinateZ": float(ift_origin[2]),
                        "rlnAngleRot": 0.0,
                        "rlnAngleTilt": 0.0,
                        "rlnAnglePsi": 0.0,
                        "rlnImagePixelSize": float(pixel_size),
                        "rlnHelicalTubeID": int(tube_id),
                        "rlnClassNumber": int(class_num),
                        "_cbWorldCoordinateX": float(ift_origin[0]),
                        "_cbWorldCoordinateY": float(ift_origin[1]),
                        "_cbWorldCoordinateZ": float(ift_origin[2]),
                        "_cbAxisX": [float(v) for v in basis_axes[0]],
                        "_cbAxisY": [float(v) for v in basis_axes[1]],
                        "_cbAxisZ": [float(v) for v in basis_axes[2]],
                        "_cb_ift_type": ift_type,
                        "_cb_source_star_ref": self._model_ref(star_model),
                        "_cb_source_star_row_index": int(idx),
                    }
                )

            star_text = rows_to_star_text(star_rows)
            created = cmd._create_star_model(
                self.session,
                f"IFT {ift_type.capitalize()} Train STAR {class_num}",
                star_rows,
                star_text,
                True,
                "relion",
                True,
                False,
            )
            self._inherit_clip_info(created, star_model)
            self._select_star_model(created)
            self.ift_target_label.setText(f"Generated: {created.name}")
            self.session.logger.info(
                f"Generated {created.name} from train parameters. Use the normal map attachment section to attach your IFT model."
            )
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _generate_ift_star_from_target(self, target):
        from . import cmd
        from .io import rows_to_star_text

        place = target["place"]
        star_model = target["star_model"]
        rows = getattr(star_model, "_cb_star_rows", None) or []
        if not rows:
            raise RuntimeError("Selected attached filament has no source STAR rows")

        try:
            pixel_size = float(rows[0].get("rlnImagePixelSize", 1.0) or 1.0)
        except Exception:
            pixel_size = 1.0
        if pixel_size <= 0.0:
            pixel_size = 1.0

        star_center = self._star_scene_center(star_model)
        target_origin = np.array(place.origin(), dtype=float)
        target_row = None
        target_index = target.get("selected_index", None)
        if target_index is not None and 0 <= int(target_index) < len(rows):
            target_row = rows[int(target_index)]
        if target_row is not None:
            target_point = self._row_world_center(target_row)
        else:
            target_point = np.array(target_origin, dtype=float)
        radial_vec = np.array(
            [
                target_point[0] - star_center[0],
                target_point[1] - star_center[1],
                0.0,
            ],
            dtype=float,
        )
        radial_norm = float(np.linalg.norm(radial_vec))
        if radial_norm < 1e-9:
            raise RuntimeError("Could not determine radial direction from the STAR center")
        radial_dir = radial_vec / radial_norm

        ift_type = str(self.ift_type.currentData() or "anterograde")
        anterograde_angle = float(self.ift_anterograde_angle.value())
        retrograde_angle = float(self.ift_retrograde_angle.value())
        angle_deg = -float(retrograde_angle) if ift_type == "retrograde" else float(anterograde_angle)
        angle_rad = math.radians(angle_deg)
        macro_rot = np.array(
            [
                [math.cos(angle_rad), -math.sin(angle_rad), 0.0],
                [math.sin(angle_rad),  math.cos(angle_rad), 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=float,
        )
        rotated_radial = macro_rot @ radial_dir
        ift_origin = np.array(star_center, dtype=float)
        ift_origin[0] += rotated_radial[0] * float(self.ift_distance.value())
        ift_origin[1] += rotated_radial[1] * float(self.ift_distance.value())
        ift_origin[2] = target_point[2]

        basis_axes = [np.array(v, dtype=float) for v in place.axes()]
        if abs(angle_deg) > 1e-12:
            basis_axes = [macro_rot @ axis for axis in basis_axes]

        class_num = cmd._next_class_number()
        tube_id = 1
        try:
            if target_row is not None:
                tube_id = int(float(target_row.get("rlnHelicalTubeID", 1)))
            else:
                selected_name = str(self._ift_target_snapshot.get("selected_model_name", "") or "")
                if "Attached_t" in selected_name:
                    suffix = selected_name.split("Attached_t", 1)[1]
                    tube_id = int(suffix.split("_", 1)[0])
        except Exception:
            tube_id = 1

        row = {
            "rlnTomoName": str(rows[0].get("rlnTomoName", "TS_001")),
            "rlnCoordinateX": float(ift_origin[0]),
            "rlnCoordinateY": float(ift_origin[1]),
            "rlnCoordinateZ": float(ift_origin[2]),
            "rlnAngleRot": 0.0,
            "rlnAngleTilt": 0.0,
            "rlnAnglePsi": 0.0,
            "rlnImagePixelSize": float(pixel_size),
            "rlnHelicalTubeID": int(tube_id),
            "rlnClassNumber": int(class_num),
            "_cbWorldCoordinateX": float(ift_origin[0]),
            "_cbWorldCoordinateY": float(ift_origin[1]),
            "_cbWorldCoordinateZ": float(ift_origin[2]),
            "_cbAxisX": [float(v) for v in basis_axes[0]],
            "_cbAxisY": [float(v) for v in basis_axes[1]],
            "_cbAxisZ": [float(v) for v in basis_axes[2]],
            "_cb_ift_type": ift_type,
        }
        star_rows = [row]
        star_text = rows_to_star_text(star_rows)
        created = cmd._create_star_model(
            self.session,
            f"IFT {ift_type.capitalize()} STAR {class_num}",
            star_rows,
            star_text,
            True,
            "relion",
            True,
            False,
        )
        self._inherit_clip_info(created, star_model)
        self._select_star_model(created)
        self.session.logger.info(
            f"Generated {created.name} from selected filament. Use the normal map attachment section to attach your IFT model."
        )
        self.ift_target_label.setText(f"Generated: {created.name}")

    def _generate_ift_star_from_star_pick(self, pick):
        from . import cmd
        from .io import rows_to_star_text

        star_model = pick["star_model"]
        row = pick["row"]
        row_index = int(pick["row_index"])
        rows = getattr(star_model, "_cb_star_rows", None) or []
        if not rows:
            raise RuntimeError("Selected STAR model has no rows")

        try:
            pixel_size = float(rows[0].get("rlnImagePixelSize", 1.0) or 1.0)
        except Exception:
            pixel_size = 1.0
        if pixel_size <= 0.0:
            pixel_size = 1.0

        star_center = self._star_scene_center(star_model)
        target_point = self._row_world_center(row)
        radial_vec = np.array(
            [
                target_point[0] - star_center[0],
                target_point[1] - star_center[1],
                0.0,
            ],
            dtype=float,
        )
        radial_norm = float(np.linalg.norm(radial_vec))
        if radial_norm < 1e-9:
            raise RuntimeError("Could not determine radial direction from the picked STAR point")
        radial_dir = radial_vec / radial_norm

        ift_type = str(self.ift_type.currentData() or "anterograde")
        anterograde_angle = float(self.ift_anterograde_angle.value())
        retrograde_angle = float(self.ift_retrograde_angle.value())
        angle_deg = -float(retrograde_angle) if ift_type == "retrograde" else float(anterograde_angle)
        angle_rad = math.radians(angle_deg)
        macro_rot = np.array(
            [
                [math.cos(angle_rad), -math.sin(angle_rad), 0.0],
                [math.sin(angle_rad),  math.cos(angle_rad), 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=float,
        )
        rotated_radial = macro_rot @ radial_dir
        ift_origin = np.array(star_center, dtype=float)
        ift_origin[0] += rotated_radial[0] * float(self.ift_distance.value())
        ift_origin[1] += rotated_radial[1] * float(self.ift_distance.value())
        ift_origin[2] = target_point[2]

        ex, ey, ez = self._axes_from_star_row(row)
        basis_axes = [np.array(ex, dtype=float), np.array(ey, dtype=float), np.array(ez, dtype=float)]
        if abs(angle_deg) > 1e-12:
            basis_axes = [macro_rot @ axis for axis in basis_axes]

        class_num = cmd._next_class_number()
        tube_id = 1
        try:
            tube_id = int(float(row.get("rlnHelicalTubeID", 1)))
        except Exception:
            tube_id = 1

        star_row = {
            "rlnTomoName": str(row.get("rlnTomoName", "TS_001")),
            "rlnCoordinateX": float(ift_origin[0]),
            "rlnCoordinateY": float(ift_origin[1]),
            "rlnCoordinateZ": float(ift_origin[2]),
            "rlnAngleRot": 0.0,
            "rlnAngleTilt": 0.0,
            "rlnAnglePsi": 0.0,
            "rlnImagePixelSize": float(pixel_size),
            "rlnHelicalTubeID": int(tube_id),
            "rlnClassNumber": int(class_num),
            "_cbWorldCoordinateX": float(ift_origin[0]),
            "_cbWorldCoordinateY": float(ift_origin[1]),
            "_cbWorldCoordinateZ": float(ift_origin[2]),
            "_cbAxisX": [float(v) for v in basis_axes[0]],
            "_cbAxisY": [float(v) for v in basis_axes[1]],
            "_cbAxisZ": [float(v) for v in basis_axes[2]],
            "_cb_ift_type": ift_type,
            "_cb_source_star_ref": self._model_ref(star_model),
            "_cb_source_star_row_index": int(row_index),
        }
        star_rows = [star_row]
        star_text = rows_to_star_text(star_rows)
        created = cmd._create_star_model(
            self.session,
            f"IFT {ift_type.capitalize()} STAR {class_num}",
            star_rows,
            star_text,
            True,
            "relion",
            True,
            False,
        )
        self._inherit_clip_info(created, star_model)
        self._select_star_model(created)
        self.session.logger.info(
            f"Generated {created.name} from picked STAR point. Use the normal map attachment section to attach your IFT model."
        )
        self.ift_target_label.setText(f"Generated: {created.name}")

    def _axes_from_star_row(self, row):
        from .map import _particle_axes_from_star
        return _particle_axes_from_star(
            row.get("rlnAngleRot", 0.0),
            row.get("rlnAngleTilt", 0.0),
            row.get("rlnAnglePsi", 0.0),
        )

    def _row_world_center(self, row):
        try:
            wx = row.get("_cbWorldCoordinateX", None)
            wy = row.get("_cbWorldCoordinateY", None)
            wz = row.get("_cbWorldCoordinateZ", None)
            if wx is not None and wy is not None and wz is not None:
                return np.array([float(wx), float(wy), float(wz)], dtype=float)
        except Exception:
            pass
        return np.array(
            [
                float(row.get("rlnCoordinateX", 0.0)),
                float(row.get("rlnCoordinateY", 0.0)),
                float(row.get("rlnCoordinateZ", 0.0)),
            ],
            dtype=float,
        )

    def _star_scene_center(self, star_model):
        rows = getattr(star_model, "_cb_star_rows", None) or []
        if not rows:
            return np.zeros(3, dtype=float)
        coords = []
        for row in rows:
            try:
                wx = row.get("_cbWorldCoordinateX", None)
                wy = row.get("_cbWorldCoordinateY", None)
                wz = row.get("_cbWorldCoordinateZ", None)
                if wx is not None and wy is not None and wz is not None:
                    coords.append((float(wx), float(wy), float(wz)))
                else:
                    coords.append(
                        (
                            float(row.get("rlnCoordinateX", 0.0)),
                            float(row.get("rlnCoordinateY", 0.0)),
                            float(row.get("rlnCoordinateZ", 0.0)),
                        )
                    )
            except Exception:
                continue
        if not coords:
            return np.zeros(3, dtype=float)
        return np.array(coords, dtype=float).mean(axis=0)

    def _star_axis_span_info(self, star_model):
        rows = getattr(star_model, "_cb_star_rows", None) or []
        if not rows:
            center = np.zeros(3, dtype=float)
            axis = np.array([0.0, 0.0, 1.0], dtype=float)
            return center, axis, 0.0, 0.0

        by_tube = {}
        direction_vectors = []
        for row in rows:
            try:
                tid = int(float(row.get("rlnHelicalTubeID", 0)))
            except Exception:
                tid = 0
            point = self._row_world_center(row)
            by_tube.setdefault(tid, []).append(point)

        axis = np.array([0.0, 0.0, 1.0], dtype=float)
        for points in by_tube.values():
            if len(points) < 2:
                continue
            pts = [np.array(p, dtype=float) for p in points]
            line_vec = pts[-1] - pts[0]
            norm = float(np.linalg.norm(line_vec))
            if norm > 1e-9:
                direction_vectors.append(line_vec / norm)
        if direction_vectors:
            axis = np.sum(direction_vectors, axis=0)
            norm = float(np.linalg.norm(axis))
            axis = (axis / norm) if norm > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=float)

        all_scalars = []
        tube_centers = []
        for points in by_tube.values():
            if not points:
                continue
            pts = np.array(points, dtype=float)
            tube_centers.append(pts.mean(axis=0))
            all_scalars.extend(float(np.dot(p, axis)) for p in pts)

        if tube_centers:
            center = np.array(tube_centers, dtype=float).mean(axis=0)
        else:
            center = np.zeros(3, dtype=float)
        if not all_scalars:
            return center, axis, 0.0, 0.0
        return center, axis, float(min(all_scalars)), float(max(all_scalars))

    def _membrane_anchor_info(self):
        star_model = self._last_outer_star_model
        axis_center = np.zeros(3, dtype=float)
        axis = np.array([0.0, 0.0, 1.0], dtype=float)
        start_scalar = 0.0
        if star_model is not None and hasattr(star_model, "_cb_star_rows"):
            axis_center, axis, start_scalar, _end_scalar = self._star_axis_span_info(star_model)
            clip_info = self._star_random_clip_info(star_model)
            if clip_info is not None:
                axis = np.array(clip_info["axis"], dtype=float)
                anorm = float(np.linalg.norm(axis))
                axis = axis / anorm if anorm > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=float)
                start_scalar = float(clip_info["clip_start"])
        return {
            "star_model": star_model,
            "axis_center": axis_center,
            "axis": axis,
            "start_scalar": float(start_scalar),
        }

    def _model_bounds_scalar_range(self, model, axis):
        if model is None:
            return None
        try:
            bounds = model.bounds()
        except Exception:
            bounds = None
        if bounds is None:
            return None
        try:
            mn = np.array([float(v) for v in bounds.xyz_min], dtype=float)
            mx = np.array([float(v) for v in bounds.xyz_max], dtype=float)
        except Exception:
            return None
        corners = np.array(
            [
                [mn[0], mn[1], mn[2]],
                [mn[0], mn[1], mx[2]],
                [mn[0], mx[1], mn[2]],
                [mn[0], mx[1], mx[2]],
                [mx[0], mn[1], mn[2]],
                [mx[0], mn[1], mx[2]],
                [mx[0], mx[1], mn[2]],
                [mx[0], mx[1], mx[2]],
            ],
            dtype=float,
        )
        scalars = corners @ np.array(axis, dtype=float)
        return float(np.min(scalars)), float(np.max(scalars))

    def _membrane_tip_dome_heights(self, star_model, axis, tip_scalar, radius, thickness):
        outer_height = max(float(radius), float(thickness))
        dome_margin = max(5.0, 0.5 * float(thickness))
        target_star_ref = self._model_ref(star_model) if star_model is not None else None
        if target_star_ref is None:
            inner_height = max(0.25 * float(thickness), float(outer_height) - float(thickness))
            return float(outer_height), float(inner_height)

        seen = set()
        tip_max_scalar = None
        for out_root in getattr(self, "_attached_results", {}).values():
            if out_root is None or id(out_root) in seen:
                continue
            seen.add(id(out_root))
            star_ref = getattr(out_root, "_cb_attachment_star_ref", None)
            if star_ref is None:
                star_ref = getattr(out_root, "_cb_attached_star_ref", None)
            if target_star_ref is not None and str(star_ref) != str(target_star_ref):
                continue
            scalar_range = self._model_bounds_scalar_range(out_root, axis)
            if scalar_range is None:
                continue
            _min_scalar, max_scalar = scalar_range
            if tip_max_scalar is None or max_scalar > tip_max_scalar:
                tip_max_scalar = max_scalar

        if tip_max_scalar is not None:
            outer_height = max(outer_height, float(tip_max_scalar) - float(tip_scalar) + dome_margin)
        inner_height = max(0.25 * float(thickness), float(outer_height) - float(thickness))
        return float(outer_height), float(inner_height)

    def _star_random_clip_info(self, star_model):
        stored = getattr(star_model, "_cb_random_clip_info", None)
        if isinstance(stored, dict):
            try:
                return {
                    "plane_point": np.array(stored["plane_point"], dtype=float),
                    "axis": np.array(stored["axis"], dtype=float),
                    "spread": float(stored["spread"]),
                    "clip_start": float(stored["clip_start"]),
                }
            except Exception:
                pass

        rows = getattr(star_model, "_cb_star_rows", None) or []
        if not rows:
            return None

        by_tube = {}
        for row in rows:
            try:
                tid = int(float(row.get("rlnHelicalTubeID", 0)))
            except Exception:
                continue
            point = self._row_world_center(row)
            by_tube.setdefault(tid, []).append(point)

        if len(by_tube) < 2:
            return None

        start_by_tube = {}
        start_point_by_tube = {}
        direction_vectors = []
        for tid, points in by_tube.items():
            if not points:
                continue
            pts = [np.array(p, dtype=float) for p in points]
            if len(pts) >= 2:
                line_vec = pts[-1] - pts[0]
                norm = float(np.linalg.norm(line_vec))
                axis = (line_vec / norm) if norm > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=float)
            else:
                axis = np.array([0.0, 0.0, 1.0], dtype=float)
            scalars = [float(np.dot(p, axis)) for p in pts]
            order = np.argsort(scalars)
            pts = [pts[i] for i in order]
            scalars = [scalars[i] for i in order]
            start_by_tube[tid] = scalars[0]
            start_point_by_tube[tid] = pts[0]
            if len(pts) >= 2:
                direction_vectors.append(axis)

        if not start_by_tube:
            return None

        starts = list(start_by_tube.values())
        spread = float(max(starts) - min(starts))
        if spread <= 1e-6:
            return None

        clip_tube = max(start_by_tube, key=start_by_tube.get)
        plane_point = start_point_by_tube[clip_tube]
        if direction_vectors:
            axis = np.sum(direction_vectors, axis=0)
            norm = float(np.linalg.norm(axis))
            axis = (axis / norm) if norm > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=float)
        else:
            axis = np.array([0.0, 0.0, 1.0], dtype=float)

        clip_info = {
            "plane_point": np.array(plane_point, dtype=float),
            "axis": np.array(axis, dtype=float),
            "spread": spread,
            "clip_start": float(start_by_tube[clip_tube]),
        }
        try:
            star_model._cb_random_clip_info = {
                "plane_point": clip_info["plane_point"].tolist(),
                "axis": clip_info["axis"].tolist(),
                "spread": float(clip_info["spread"]),
                "clip_start": float(clip_info["clip_start"]),
            }
        except Exception:
            pass
        return clip_info

    def _inherit_clip_info(self, new_star_model, source_star_model):
        clip_info = self._star_random_clip_info(source_star_model)
        if clip_info is None:
            return
        try:
            new_star_model._cb_random_clip_info = {
                "plane_point": np.array(clip_info["plane_point"], dtype=float).tolist(),
                "axis": np.array(clip_info["axis"], dtype=float).tolist(),
                "spread": float(clip_info["spread"]),
                "clip_start": float(clip_info["clip_start"]),
            }
        except Exception:
            pass

    def _close_manual_tweak_models(self):
        for model in (
            self._manual_tweak_template,
            None if self._manual_tweak_source_is_external else self._manual_tweak_source,
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
        self._manual_tweak_source_is_external = False

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

    def _all_session_models(self):
        seen = set()
        for model in self.session.models.list():
            for candidate in self._iter_model_tree(model):
                if id(candidate) in seen:
                    continue
                seen.add(id(candidate))
                yield candidate

    def _selector_attach_models(self):
        seen = set()

        def add(model):
            if model is None or id(model) in seen:
                return
            seen.add(id(model))
            yield model

        for model in self.session.models.list():
            if getattr(model, "_cb_group_tag", None) in ("star_models", "maps", "membrane"):
                continue
            if self._is_under_cb_group(model, "star_models"):
                continue
            yield from add(model)

        for model in self._all_session_models():
            if getattr(model, "_cb_group_tag", None) == "maps":
                try:
                    children = list(model.child_models())
                except Exception:
                    children = []
                for child in children:
                    yield from add(child)

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
        def _norm_step(step):
            try:
                vals = tuple(abs(float(s)) for s in step[:3])
            except Exception:
                try:
                    v = abs(float(step))
                except Exception:
                    return None
                vals = (v, v, v)
            if all(v > 1e-12 for v in vals):
                return vals
            return None

        try:
            data = getattr(model, "data", None)
            step = getattr(data, "step", None)
            if step is not None:
                vals = _norm_step(step)
                if vals is not None:
                    return vals
        except Exception:
            pass
        try:
            grid = getattr(model, "grid_data", None)
            step = getattr(grid, "step", None)
            if step is not None:
                vals = _norm_step(step)
                if vals is not None:
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
        return

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
            self._zero_map_origin_index(fit_src)
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
            self._zero_map_origin_index(fit_src)
            try:
                fit_src.display = True
            except Exception:
                pass
            return fit_src

        raise RuntimeError("Manual tweak supports map, STL/GLB surface, and PDB-like atomic models")

    def _start_manual_tweak(self):
        from Qt.QtWidgets import QMessageBox

        try:
            self._refresh_model_selectors()
            source_ref = self.tweak_open_model.currentData() if hasattr(self, "tweak_open_model") else None
            source_path = os.path.expanduser(self.tweak_source_path.text().strip())
            template_path = os.path.expanduser(self.tweak_template_path.text().strip())
            selected_source = None
            if source_ref is not None:
                selected_source = self._model_by_ref(source_ref)
                if selected_source is None:
                    raise RuntimeError(f"Open model #{source_ref} not found")
                if not self._is_attach_source(selected_source):
                    raise RuntimeError("Selected open model is not a map/STL/GLB/PDB/CIF attach source")
            elif source_path:
                if not os.path.exists(source_path):
                    raise RuntimeError(f"User model path does not exist: {source_path}")
            else:
                raise RuntimeError("Select an open model or choose a user model path first")
            if not template_path:
                raise RuntimeError("Choose a template map path first")
            if not os.path.exists(template_path):
                raise RuntimeError(f"Template map not found: {template_path}")

            self._close_manual_tweak_models()
            self._restore_manual_tweak_scene()

            source_chain_ids = self._model_chain_ids(selected_source)
            self._manual_tweak_hidden = []
            for model in self.session.models.list():
                try:
                    if id(model) in source_chain_ids:
                        continue
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
            self._zero_map_origin_index(self._manual_tweak_template)

            if selected_source is not None:
                self._manual_tweak_source = selected_source
                self._manual_tweak_source_is_external = True
                self._zero_map_origin_index(self._manual_tweak_source)
            else:
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
                self._manual_tweak_source_is_external = False
                self._zero_map_origin_index(self._manual_tweak_source)
            self._match_template_voxel_size_to_source()

            try:
                self._manual_tweak_template.display = True
            except Exception:
                pass
            self._set_model_chain_visible(self._manual_tweak_source, True)

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
        finally:
            self._keep_tool_visible()

    def _finish_manual_tweak(self):
        from Qt.QtWidgets import QMessageBox

        try:
            if self._manual_tweak_template is None or self._manual_tweak_source is None:
                raise RuntimeError("Start manual tweak first")
            if not self._is_volume_like(self._manual_tweak_template):
                raise RuntimeError("Template model must be a volume map")

            self._manual_tweak_fit_source = self._prepare_manual_tweak_fit_source()
            fit_pre_position = None
            if self._manual_tweak_fit_source is not self._manual_tweak_source:
                try:
                    fit_pre_position = self._manual_tweak_fit_source.position
                except Exception:
                    fit_pre_position = None

            _run(
                self.session,
                f"fitmap #{self._manual_tweak_fit_source.id_string} inMap #{self._manual_tweak_template.id_string}",
            )

            if self._manual_tweak_source_is_external:
                live_source = self._manual_tweak_source
                if self._manual_tweak_fit_source is not self._manual_tweak_source:
                    try:
                        fit_post_position = self._manual_tweak_fit_source.position
                        if fit_pre_position is not None:
                            delta = fit_post_position * fit_pre_position.inverse()
                            live_source.position = delta * live_source.position
                    except Exception:
                        pass
                try:
                    live_source.display = True
                    live_source.set_selected(True)
                except Exception:
                    pass
                self._close_manual_tweak_models()
                self._restore_manual_tweak_scene()
                self._set_model_chain_visible(live_source, True)
                try:
                    live_source.set_selected(True)
                except Exception:
                    pass
                self._refresh_model_selectors()
                self.session.logger.info("Manual tweak finished and applied directly to the selected open model.")
                return

            save_path = os.path.expanduser(self.tweak_save_path.text().strip())
            if not save_path:
                raise RuntimeError("Choose a save path for the tweaked model")

            resampled_new = self._command_created_models(
                f"volume resample #{self._manual_tweak_fit_source.id_string} onGrid #{self._manual_tweak_template.id_string}"
            )
            if not resampled_new:
                raise RuntimeError("volume resample did not create a new model")
            self._manual_tweak_resampled = self._pick_opened_model(resampled_new, self._is_volume_like)
            if self._manual_tweak_resampled is None:
                raise RuntimeError("volume resample did not create a usable map")
            self._zero_map_origin_index(self._manual_tweak_resampled)

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
                self._zero_map_origin_index(tweaked_model)
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
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

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
            try:
                rows = getattr(model, "_cb_star_rows", None)
                if rows is None:
                    continue
                out.append(
                    {
                        "session_star_id": self._model_ref(model) or f"star_{len(out)+1}",
                        "name": str(model.name),
                        "rows": rows,
                        "star_text": getattr(model, "_cb_star_text", None),
                        "display": bool(getattr(model, "display", True)),
                        "color_state": self._capture_model_color_state(model),
                        "clip_info": getattr(model, "_cb_random_clip_info", None),
                        "under_cb_star_group": self._is_under_cb_group(model, "star_models"),
                    }
                )
            except Exception as e:
                self.session.logger.warning(f"Skipping STAR model during JSON save: {getattr(model, 'name', '(unnamed)')} ({e})")
        return out

    def _generated_membrane_models(self):
        out = []
        for model in self._all_session_models():
            try:
                state = getattr(model, "_cb_membrane_state", None)
                if not state:
                    continue
                out.append(
                    {
                        "session_membrane_id": self._model_ref(model) or f"membrane_{len(out)+1}",
                        "name": str(getattr(model, "name", "Membrane") or "Membrane"),
                        "state": state,
                        "display": bool(getattr(model, "display", True)),
                        "color_state": self._capture_model_color_state(model),
                    }
                )
            except Exception as e:
                self.session.logger.warning(f"Skipping membrane model during JSON save: {getattr(model, 'name', '(unnamed)')} ({e})")
        return out

    def _generated_marker_path_models(self):
        out = []
        for model in self._all_session_models():
            try:
                state = getattr(model, "_cb_marker_path_state", None)
                if not state:
                    continue
                out.append(
                    {
                        "session_marker_path_id": self._model_ref(model) or f"marker_path_{len(out)+1}",
                        "name": str(getattr(model, "name", "Marker path") or "Marker path"),
                        "state": state,
                        "display": bool(getattr(model, "display", True)),
                        "color_state": self._capture_model_color_state(model),
                    }
                )
            except Exception as e:
                self.session.logger.warning(
                    f"Skipping marker path model during JSON save: {getattr(model, 'name', '(unnamed)')} ({e})"
                )
        return out

    def _attach_source_models_state(self, save_dir, session_stem, export_cache):
        out = []
        seen_paths = set()
        seen_fetches = set()
        for model in self.session.models.list():
            try:
                if not self._is_selector_attach_source(model):
                    continue
                path = self._session_model_path(model, save_dir=save_dir, session_stem=session_stem, export_cache=export_cache)
                fetch_spec = self._fetch_spec_for_model(model)
                fetch_key = None
                if fetch_spec is not None:
                    fetch_key = (str(fetch_spec.get("fetch_type", "")).lower(), str(fetch_spec.get("fetch_id", "")).lower())
                if path and path in seen_paths:
                    continue
                if fetch_key and fetch_key in seen_fetches:
                    continue
                if path:
                    seen_paths.add(path)
                if fetch_key:
                    seen_fetches.add(fetch_key)
                out.append(
                    {
                        "session_source_id": self._model_ref(model) or f"source_{len(out)+1}",
                        "name": str(model.name),
                        "path": path,
                        "fetch_type": fetch_spec.get("fetch_type") if fetch_spec else None,
                        "fetch_id": fetch_spec.get("fetch_id") if fetch_spec else None,
                        "display": bool(getattr(model, "display", True)),
                        "color_state": self._capture_model_color_state(model),
                        "under_cb_map_group": self._is_under_cb_group(model, "maps"),
                    }
                )
            except Exception as e:
                self.session.logger.warning(f"Skipping attach source during JSON save: {getattr(model, 'name', '(unnamed)')} ({e})")
        return out

    def _attachment_models_state(self, save_dir, session_stem, export_cache):
        items = []
        seen = set()
        for out_root in self._attached_results.values():
            try:
                if out_root is None or id(out_root) in seen:
                    continue
                seen.add(id(out_root))
                map_model = None
                source_ref = getattr(out_root, "_cb_attachment_source_ref", None)
                if source_ref:
                    map_model = self._model_by_ref(source_ref)
                if map_model is None:
                    map_model = self._find_model_by_name(getattr(out_root, "_cb_attachment_map_name", None), require_star=False)
                map_path = self._session_model_path(map_model, save_dir=save_dir, session_stem=session_stem, export_cache=export_cache)
                fetch_spec = self._fetch_spec_for_model(map_model)
                if map_path is None:
                    map_path = getattr(out_root, "_cb_attachment_map_path", None)
                if fetch_spec is None:
                    fetch_type = getattr(out_root, "_cb_attachment_fetch_type", None)
                    fetch_id = getattr(out_root, "_cb_attachment_fetch_id", None)
                    if fetch_type and fetch_id:
                        fetch_spec = {"fetch_type": fetch_type, "fetch_id": fetch_id}
                items.append(
                    {
                        "session_attachment_id": self._model_ref(out_root) or f"attachment_{len(items)+1}",
                        "name": str(getattr(out_root, "name", "") or ""),
                        "star_session_id": getattr(out_root, "_cb_attachment_star_session_id", None) or getattr(out_root, "_cb_attachment_star_ref", None),
                        "source_session_id": getattr(out_root, "_cb_attachment_source_session_id", None) or source_ref,
                        "star_name": str(getattr(out_root, "_cb_attachment_star_name", "") or ""),
                        "map_name": str(getattr(out_root, "_cb_attachment_map_name", "") or ""),
                        "map_path": map_path,
                        "fetch_type": fetch_spec.get("fetch_type") if fetch_spec else None,
                        "fetch_id": fetch_spec.get("fetch_id") if fetch_spec else None,
                        "line_rotation": float(getattr(out_root, "_cb_attachment_line_rotation", 0.0) or 0.0),
                        "y_rotation": float(getattr(out_root, "_cb_attachment_y_rotation", 0.0) or 0.0),
                        "pre_rotate_y_90": bool(
                            getattr(
                                out_root,
                                "_cb_attachment_pre_rotate_y_90",
                                getattr(
                                    out_root,
                                    "_cb_attachment_pre_rotate_x_90",
                                    getattr(out_root, "_cb_attachment_auto_z_align", False),
                                ),
                            )
                        ),
                        "display": bool(getattr(out_root, "display", True)),
                        "color_state": self._capture_model_color_state(out_root),
                    }
                )
            except Exception as e:
                self.session.logger.warning(f"Skipping attached result during JSON save: {getattr(out_root, 'name', '(unnamed)')} ({e})")
        return items

    def _ui_state(self):
        return {
            "angle_set": float(self.angle_set.value()),
            "length": float(self.length.value()),
            "n_doublet": int(self.n_doublet.value()),
            "radius": float(self.radius.value()),
            "spacing": float(self.spacing.value()),
            "doublet_offset": float(self.doublet_offset.value()),
            "random_enable": bool(self.random_enable.isChecked()),
            "centriole_length": float(self.centriole_length.value()),
            "centriole_spacing": float(self.centriole_spacing.value()),
            "centriole_z_offset": float(self.centriole_z_offset.value()),
            "centriole_mode": str(self.centriole_mode.currentData() or "singlet"),
            "centriole_c1c2_distance": float(self.centriole_c1c2_distance.value()),
            "membrane_length": float(self.membrane_length.value()),
            "membrane_radius": float(self.membrane_radius.value()),
            "membrane_thickness": float(self.membrane_thickness.value()),
            "membrane_offset": float(self.membrane_offset.value()),
            "membrane_distortion": float(self.membrane_distortion.value()),
            "membrane_tip_dome": bool(self.membrane_tip_dome.isChecked()),
            "membrane_particle_receptors_pct": float(self.membrane_particle_receptors_pct.value()),
            "membrane_particle_channels_pct": float(self.membrane_particle_channels_pct.value()),
            "membrane_particle_signaling_pct": float(self.membrane_particle_signaling_pct.value()),
            "membrane_particle_scaffold_pct": float(self.membrane_particle_scaffold_pct.value()),
            "membrane_particle_lipids_pct": float(self.membrane_particle_lipids_pct.value()),
            "marker_path_count": int(self.marker_path_count.value()) if hasattr(self, "marker_path_count") else 4,
            "geometric_draw_mode": self._current_geometric_draw_mode(),
            "marker_path_mode": str(self.marker_path_mode.currentData() or "curve") if hasattr(self, "marker_path_mode") else "curve",
            "marker_path_radius": float(self.marker_path_radius.value()) if hasattr(self, "marker_path_radius") else 20.0,
            "draw_marker_radius": float(self.draw_marker_radius.value()) if hasattr(self, "draw_marker_radius") else 12.0,
            "ift_distance": float(self.ift_distance.value()),
            "ift_mode": str(self.ift_mode.currentData() or "train"),
            "ift_type": str(self.ift_type.currentData() or "anterograde"),
            "ift_anterograde_angle": float(self.ift_anterograde_angle.value()),
            "ift_retrograde_angle": float(self.ift_retrograde_angle.value()),
            "ift_train_star_model": self._combo_state(self.ift_train_star_model) if hasattr(self, "ift_train_star_model") else {"id": None, "text": ""},
            "ift_train_doublet": self.ift_train_doublet.text().strip(),
            "ift_train_angle": self.ift_train_angle.text().strip(),
            "ift_train_offset": self.ift_train_offset.text().strip(),
            "ift_train_periodicity": self.ift_train_periodicity.text().strip(),
            "ift_train_repeat": self.ift_train_repeat.text().strip(),
            "attach_line_rotation": float(self.attach_line_rotation.value()),
            "attach_y_rotation": float(self.attach_y_rotation.value()),
            "attach_x_movement": 0.0,
            "attach_pre_rotate_y_90": bool(self.attach_pre_rotate_y_90.isChecked()) if hasattr(self, "attach_pre_rotate_y_90") else False,
            "pixel_size": float(self.pixel_size.value()),
            "align_z_model": self._combo_state(self.align_z_model) if hasattr(self, "align_z_model") else {"id": None, "text": ""},
            "align_z_save_path": self.align_z_save_path.text().strip() if hasattr(self, "align_z_save_path") else "",
            "tweak_source_path": self.tweak_source_path.text().strip() if hasattr(self, "tweak_source_path") else "",
            "tweak_template_path": self.tweak_template_path.text().strip() if hasattr(self, "tweak_template_path") else "",
            "tweak_save_path": self.tweak_save_path.text().strip() if hasattr(self, "tweak_save_path") else "",
        }

    def _apply_ui_state(self, state):
        self.angle_set.setValue(float(state.get("angle_set", self.angle_set.value())))
        self.length.setValue(float(state.get("length", self.length.value())))
        self.n_doublet.setValue(int(state.get("n_doublet", self.n_doublet.value())))
        self.radius.setValue(float(state.get("radius", self.radius.value())))
        self.spacing.setValue(float(state.get("spacing", self.spacing.value())))
        self.doublet_offset.setValue(float(state.get("doublet_offset", self.doublet_offset.value())))
        self.random_enable.setChecked(bool(state.get("random_enable", self.random_enable.isChecked())))
        self.centriole_length.setValue(float(state.get("centriole_length", self.centriole_length.value())))
        self.centriole_spacing.setValue(float(state.get("centriole_spacing", self.centriole_spacing.value())))
        self.centriole_z_offset.setValue(float(state.get("centriole_z_offset", self.centriole_z_offset.value())))
        self.centriole_c1c2_distance.setValue(
            float(state.get("centriole_c1c2_distance", self.centriole_c1c2_distance.value()))
        )
        if hasattr(self, "centriole_mode"):
            idx = self.centriole_mode.findData(str(state.get("centriole_mode", self.centriole_mode.currentData())))
            if idx >= 0:
                self.centriole_mode.setCurrentIndex(idx)
        self.membrane_length.setValue(float(state.get("membrane_length", self.membrane_length.value())))
        membrane_radius = state.get("membrane_radius", None)
        if membrane_radius is None:
            old_diameter = float(state.get("membrane_diameter", self.membrane_radius.value() * 2.0))
            membrane_radius = 0.5 * old_diameter
        self.membrane_radius.setValue(float(membrane_radius))
        self.membrane_thickness.setValue(float(state.get("membrane_thickness", self.membrane_thickness.value())))
        self.membrane_offset.setValue(float(state.get("membrane_offset", self.membrane_offset.value())))
        self.membrane_distortion.setValue(float(state.get("membrane_distortion", self.membrane_distortion.value())))
        self.membrane_tip_dome.setChecked(bool(state.get("membrane_tip_dome", self.membrane_tip_dome.isChecked())))
        self.membrane_particle_receptors_pct.setValue(
            float(state.get("membrane_particle_receptors_pct", self.membrane_particle_receptors_pct.value()))
        )
        self.membrane_particle_channels_pct.setValue(
            float(state.get("membrane_particle_channels_pct", self.membrane_particle_channels_pct.value()))
        )
        self.membrane_particle_signaling_pct.setValue(
            float(state.get("membrane_particle_signaling_pct", self.membrane_particle_signaling_pct.value()))
        )
        self.membrane_particle_scaffold_pct.setValue(
            float(state.get("membrane_particle_scaffold_pct", self.membrane_particle_scaffold_pct.value()))
        )
        self.membrane_particle_lipids_pct.setValue(
            float(state.get("membrane_particle_lipids_pct", self.membrane_particle_lipids_pct.value()))
        )
        if hasattr(self, "marker_path_count"):
            self.marker_path_count.setValue(int(state.get("marker_path_count", self.marker_path_count.value())))
        if hasattr(self, "marker_path_mode"):
            idx = self.marker_path_mode.findData(str(state.get("marker_path_mode", self.marker_path_mode.currentData())))
            if idx >= 0:
                self.marker_path_mode.setCurrentIndex(idx)
        if hasattr(self, "geometric_draw_mode_bar"):
            geometric_mode = str(state.get("geometric_draw_mode", "") or "").strip().lower()
            if not geometric_mode:
                geometric_mode = str(state.get("marker_path_mode", self._current_geometric_draw_mode()) or "").strip().lower() or "curve"
            self._set_geometric_draw_mode(geometric_mode)
        if hasattr(self, "marker_path_radius"):
            self.marker_path_radius.setValue(float(state.get("marker_path_radius", self.marker_path_radius.value())))
        if hasattr(self, "draw_marker_radius"):
            self.draw_marker_radius.setValue(float(state.get("draw_marker_radius", self.draw_marker_radius.value())))
        self.ift_distance.setValue(float(state.get("ift_distance", self.ift_distance.value())))
        if hasattr(self, "ift_mode"):
            idx = self.ift_mode.findData(str(state.get("ift_mode", self.ift_mode.currentData())))
            if idx >= 0:
                self.ift_mode.setCurrentIndex(idx)
        self.ift_anterograde_angle.setValue(float(state.get("ift_anterograde_angle", self.ift_anterograde_angle.value())))
        self.ift_retrograde_angle.setValue(float(state.get("ift_retrograde_angle", self.ift_retrograde_angle.value())))
        if hasattr(self, "ift_type"):
            idx = self.ift_type.findData(str(state.get("ift_type", self.ift_type.currentData())))
            if idx >= 0:
                self.ift_type.setCurrentIndex(idx)
        self._update_ift_type_visibility()
        if hasattr(self, "ift_train_doublet"):
            self.ift_train_doublet.setText(str(state.get("ift_train_doublet", "") or ""))
            self.ift_train_angle.setText(str(state.get("ift_train_angle", "") or ""))
            self.ift_train_offset.setText(str(state.get("ift_train_offset", "") or ""))
            self.ift_train_periodicity.setText(str(state.get("ift_train_periodicity", "") or ""))
            self.ift_train_repeat.setText(str(state.get("ift_train_repeat", "") or ""))
        self.attach_line_rotation.setValue(float(state.get("attach_line_rotation", self.attach_line_rotation.value())))
        self.attach_y_rotation.setValue(float(state.get("attach_y_rotation", self.attach_y_rotation.value())))
        if hasattr(self, "attach_pre_rotate_y_90"):
            self.attach_pre_rotate_y_90.setChecked(
                bool(
                    state.get(
                        "attach_pre_rotate_y_90",
                        state.get(
                            "attach_pre_rotate_x_90",
                            state.get("attach_auto_z_align", self.attach_pre_rotate_y_90.isChecked()),
                        ),
                    )
                )
            )
        self.pixel_size.setValue(float(state.get("pixel_size", self.pixel_size.value())))
        if hasattr(self, "align_z_save_path"):
            self.align_z_save_path.setText(str(state.get("align_z_save_path", self.align_z_save_path.text()) or ""))
        if hasattr(self, "tweak_source_path"):
            self.tweak_source_path.setText(str(state.get("tweak_source_path", self.tweak_source_path.text()) or ""))
        if hasattr(self, "tweak_template_path"):
            self.tweak_template_path.setText(str(state.get("tweak_template_path", self.tweak_template_path.text()) or ""))
        if hasattr(self, "tweak_save_path"):
            self.tweak_save_path.setText(str(state.get("tweak_save_path", self.tweak_save_path.text()) or ""))
        self._update_marker_path_buttons()

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
                    self._remember_restored_session_star(model, item)
                    exists = True
                    break
            if exists:
                continue
            created = Model(name, self.session)
            cmd._add_to_cb_star_group(self.session, created)
            created._cb_star_rows = rows
            created._cb_star_text = item.get("star_text", None)
            created._cb_random_clip_info = item.get("clip_info", None)
            cmd._render_star_model(self.session, created, rows, True)
            self._remember_restored_session_star(created, item)
            self._apply_model_color_state(created, item.get("color_state", []))
            try:
                created.display = bool(item.get("display", True))
            except Exception:
                pass
            try:
                if str(name).startswith("Microtubules STAR"):
                    self._last_outer_star_model = created
                elif str(name).startswith("Central pair"):
                    self._last_cent_star_model = created
            except Exception:
                pass

    def _restore_generated_membranes(self, models_state):
        from . import cmd
        for item in models_state or []:
            state = item.get("state", None) or {}
            name = str(item.get("name", "") or "").strip() or "Membrane"
            session_membrane_id = str(item.get("session_membrane_id", "") or "").strip()
            if not state:
                continue
            exists = False
            for model in self.session.models.list():
                if getattr(model, "_cb_generated_membrane", False) and str(getattr(model, "name", "") or "") == name:
                    self._remember_restored_session_layout_model("membrane", session_membrane_id, model)
                    exists = True
                    break
            if exists:
                continue
            try:
                created = cmd.buildmembrane_surface(
                    self.session,
                    name=name,
                    center=state.get("center", [0.0, 0.0, 0.0]),
                    axis=state.get("axis", [0.0, 0.0, 1.0]),
                    length=float(state.get("length", 1.0)),
                    diameter=float(state.get("diameter", 1.0)),
                    thickness=float(state.get("thickness", 1.0)),
                    distortion_level=float(state.get("distortion_level", 1.0) or 0.0),
                    distortion_seed=state.get("distortion_seed", None),
                    tip_dome_enabled=bool(state.get("tip_dome_enabled", False)),
                    tip_dome_outer_height=state.get("tip_dome_outer_height", None),
                    tip_dome_inner_height=state.get("tip_dome_inner_height", None),
                )
                try:
                    created_state = getattr(created, "_cb_membrane_state", None) or {}
                    created_state.update(state)
                    created._cb_membrane_state = created_state
                except Exception:
                    pass
                self._remember_restored_session_layout_model("membrane", session_membrane_id, created)
                self._apply_model_color_state(created, item.get("color_state", []))
                created.display = bool(item.get("display", True))
            except Exception:
                pass

    def _restore_generated_marker_paths(self, models_state):
        from . import cmd

        for item in models_state or []:
            state = item.get("state", None) or {}
            name = str(item.get("name", "") or "").strip() or "Marker path"
            session_marker_path_id = str(item.get("session_marker_path_id", "") or "").strip()
            control_points = state.get("control_points", None) or []
            path_mode = str(state.get("path_mode", "curve") or "curve")
            display_mode = str(state.get("display_mode", "") or "").strip().lower()
            min_points = 1 if display_mode in ("point_marker", "sphere_marker") else 2
            if len(control_points) < min_points:
                continue
            exists = False
            for model in self._all_session_models():
                if getattr(model, "_cb_marker_path_state", None) and str(getattr(model, "name", "") or "") == name:
                    self._remember_restored_session_layout_model("marker_path", session_marker_path_id, model)
                    exists = True
                    break
            if exists:
                continue
            try:
                if display_mode in ("point_marker", "sphere_marker"):
                    created = cmd.build_marker_point_model(
                        self.session,
                        name=name,
                        control_points=control_points,
                        marker_radius=float(state.get("marker_radius", state.get("radius", 8.0)) or 8.0),
                        display_mode=display_mode,
                    )
                else:
                    created = cmd.build_marker_path_model(
                        self.session,
                        name=name,
                        control_points=control_points,
                        path_mode=path_mode,
                        tube_radius=float(state.get("tube_radius", state.get("radius", 20.0)) or 20.0),
                    )
                try:
                    created_state = getattr(created, "_cb_marker_path_state", None) or {}
                    created_state.update(state)
                    created._cb_marker_path_state = created_state
                except Exception:
                    pass
                self._remember_restored_session_layout_model("marker_path", session_marker_path_id, created)
                self._apply_model_color_state(created, item.get("color_state", []))
                created.display = bool(item.get("display", True))
            except Exception:
                pass

    def _find_model_by_name(self, name, require_star=False):
        want = str(name or "").strip()
        if not want:
            return None
        for model in self._all_session_models():
            if str(getattr(model, "name", "") or "") != want:
                continue
            if require_star and not hasattr(model, "_cb_star_rows"):
                continue
            return model
        return None

    def _find_model_by_path(self, path):
        want = os.path.abspath(os.path.expanduser(str(path or "")))
        if not want:
            return None
        for model in self._all_session_models():
            for source_path in self._candidate_model_paths(model):
                if source_path and os.path.abspath(os.path.expanduser(source_path)) == want:
                    return model
        return None

    def _restore_attach_source_models(self, models_state, base_dir=""):
        from .cmd import _add_to_cb_map_group

        for item in models_state or []:
            source_model = self._open_saved_source_item(item, base_dir=base_dir)
            if source_model is None:
                continue
            try:
                source_model._cb_attach_source = True
                if bool(item.get("under_cb_map_group", False)):
                    _add_to_cb_map_group(self.session, source_model)
                source_model.display = bool(item.get("display", True))
                self._zero_map_origin_index(source_model)
                path = item.get("path", None)
                if path:
                    self._store_model_saved_path(source_model, path)
                self._remember_restored_session_source(source_model, item)
                self._apply_model_color_state(source_model, item.get("color_state", []))
            except Exception:
                pass

    def _restore_attachments(self, attachment_state):
        from .map import cbsubmap_impl

        self._attached_results = {}
        self._last_attached_result = None

        for item in attachment_state or []:
            star_model = self._restored_session_star_model(item)
            if star_model is None:
                star_model = self._find_model_by_name(item.get("star_name"), require_star=True)
            if star_model is None:
                continue
            map_model = self._restored_session_source_model(item)
            fetch_type = item.get("fetch_type", None)
            fetch_id = item.get("fetch_id", None)
            if map_model is None and fetch_type and fetch_id:
                map_model = self._find_model_by_fetch(fetch_type, fetch_id)
                if map_model is None:
                    map_model = self._open_fetch_source_item(fetch_type, fetch_id)
            map_path = item.get("map_path", None)
            if map_model is None and map_path:
                map_model = self._find_model_by_path(map_path)
            if map_model is None:
                map_model = self._find_model_by_name(item.get("map_name"), require_star=False)
            if map_model is None or not self._is_attach_source(map_model):
                continue
            source_color_state = self._capture_model_color_state(map_model)
            try:
                self._zero_map_origin_index(map_model)
            except Exception:
                pass

            line_rotation = float(item.get("line_rotation", 0.0) or 0.0)
            y_rotation = float(item.get("y_rotation", 0.0) or 0.0)
            pre_rotate_y_90 = bool(
                item.get(
                    "pre_rotate_y_90",
                    item.get("pre_rotate_x_90", item.get("auto_z_align", False)),
                )
            )
            adjust_matrix = self._current_attach_adjust_matrix(
                y_deg=y_rotation,
                pre_rotate_y_90=pre_rotate_y_90,
            ).tolist()

            out_root = cbsubmap_impl(
                session=self.session,
                star_model_obj=star_model,
                map_model_id=self._model_ref(map_model),
                close_source=False,
                show_result=bool(item.get("display", True)),
                rotate_xy_90=True,
                single_big_object=True,
                attach_all_z_offset_deg=line_rotation,
                attach_auto_align_long_axis=False,
                attach_inout_flip=False,
                attach_updown_flip=False,
                attach_axis_rot_y_deg=0.0,
                attach_axis_rot_z_deg=-90.0,
                attach_x_movement=0.0,
                attach_local_adjust_matrix=adjust_matrix,
            )
            if out_root is None:
                continue
            self._apply_source_color_state_to_attached_result(out_root, source_color_state)
            try:
                out_root._cb_attachment_line_rotation = line_rotation
                out_root._cb_attachment_y_rotation = y_rotation
                out_root._cb_attachment_x_movement = 0.0
                out_root._cb_attachment_pre_rotate_y_90 = pre_rotate_y_90
                out_root._cb_attachment_star_session_id = item.get("star_session_id", None)
                out_root._cb_attachment_source_session_id = item.get("source_session_id", None)
                out_root._cb_attachment_star_name = str(star_model.name)
                out_root._cb_attachment_map_name = str(map_model.name)
                out_root._cb_attachment_map_path = self._model_source_path(map_model)
                out_root._cb_attachment_source_ref = self._model_ref(map_model)
                out_root._cb_attachment_star_ref = self._model_ref(star_model)
                out_root._cb_attachment_fetch_type = fetch_type
                out_root._cb_attachment_fetch_id = fetch_id
                out_root.display = bool(item.get("display", True))
            except Exception:
                pass
            self._remember_restored_session_layout_model(
                "attachment",
                str(item.get("session_attachment_id", "") or ""),
                out_root,
            )
            self._apply_model_color_state(out_root, item.get("color_state", []))
            attach_key = self._attach_key(star_model, map_model)
            self._attached_results[attach_key] = out_root
            self._last_attached_result = out_root
            try:
                map_model.display = False
            except Exception:
                pass
            try:
                star_model.display = False
            except Exception:
                pass
            try:
                self._apply_attachment_clip_if_needed(out_root, star_model)
            except Exception:
                pass

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
            if not str(path).lower().endswith(".json"):
                path = f"{path}.json"
            save_dir = os.path.dirname(os.path.abspath(path))
            session_stem = os.path.splitext(os.path.basename(path))[0]
            os.makedirs(save_dir, exist_ok=True)
            export_cache = {}
            ui_state = self._ui_state()
            selected_state = {
                "star_model": self._combo_state(self.sel_star_model),
                "map_model": self._combo_state(self.sel_map_model),
                "ift_train_star_model": self._combo_state(self.ift_train_star_model) if hasattr(self, "ift_train_star_model") else {"id": None, "text": ""},
            }
            attach_sources = self._attach_source_models_state(save_dir, session_stem, export_cache)
            generated_star_models = self._generated_star_models()
            generated_membranes = self._generated_membrane_models()
            generated_marker_paths = self._generated_marker_path_models()
            attachments = self._attachment_models_state(save_dir, session_stem, export_cache)
            model_structure = self._session_model_structure_state(
                attach_sources,
                generated_star_models,
                generated_membranes,
                generated_marker_paths,
                attachments,
            )
            payload = {
                "format": "ciliabuilder2_session",
                "version": 5,
                "ui": ui_state,
                "selected": selected_state,
                "attach_sources": attach_sources,
                "generated_star_models": generated_star_models,
                "generated_membranes": generated_membranes,
                "generated_marker_paths": generated_marker_paths,
                "attachments": attachments,
                "model_structure": model_structure,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self.session.logger.info(f"Saved CiliaBuilder2 session JSON: {path}")
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

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

            base_dir = os.path.dirname(os.path.abspath(path))
            self._restored_session_sources = {}
            self._restored_session_stars = {}
            self._restored_session_layout_models = {}
            source_items = []
            for item in payload.get("attach_sources", []) or []:
                source_items.append(dict(item))
            for item in payload.get("attachments", []) or []:
                source_items.append(
                    {
                        "name": item.get("map_name", ""),
                        "path": item.get("map_path", None),
                        "fetch_type": item.get("fetch_type", None),
                        "fetch_id": item.get("fetch_id", None),
                        "display": False,
                        "under_cb_map_group": True,
                    }
                )

            deduped_source_items = []
            seen = set()
            for item in source_items:
                key = (
                    str(item.get("fetch_type", "") or "").lower(),
                    str(item.get("fetch_id", "") or "").lower(),
                    os.path.abspath(os.path.expanduser(str(item.get("path", "") or ""))) if item.get("path", None) else "",
                    str(item.get("name", "") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped_source_items.append(item)
            source_items = deduped_source_items

            for item in source_items:
                self._open_saved_source_item(item, base_dir=base_dir)

            self._apply_ui_state(payload.get("ui", {}))
            self._restore_attach_source_models(source_items, base_dir=base_dir)
            self._restore_generated_star_models(payload.get("generated_star_models", []))
            self._restore_generated_membranes(payload.get("generated_membranes", []))
            self._restore_generated_marker_paths(payload.get("generated_marker_paths", []))
            self._restore_attachments(payload.get("attachments", []))
            self._restore_session_model_structure(payload.get("model_structure", {}))
            self._refresh_model_selectors()

            selected = payload.get("selected", {})
            self._select_combo_saved(self.sel_star_model, selected.get("star_model"))
            self._select_combo_saved(self.sel_map_model, selected.get("map_model"))
            if hasattr(self, "ift_train_star_model"):
                self._select_combo_saved(self.ift_train_star_model, selected.get("ift_train_star_model"))
            if hasattr(self, "align_z_model"):
                self._select_combo_saved(self.align_z_model, payload.get("ui", {}).get("align_z_model"))

            try:
                _run(self.session, "view orient")
            except Exception:
                pass
            self.session.logger.info(f"Loaded CiliaBuilder2 session JSON: {path}")
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _export_cellpack_package(self):
        from Qt.QtWidgets import QMessageBox, QFileDialog
        from .cellpack_export import export_cellpack_package

        try:
            out_dir = QFileDialog.getExistingDirectory(
                self.tool_window.ui_area,
                "Choose cellPACK export folder",
                os.path.expanduser("~/"),
            )
            if not out_dir:
                return
            result = export_cellpack_package(self, out_dir)
            msg = (
                "Exported cellPACK package to "
                f"{result['package_dir']} "
                f"({result['n_outputs']} outputs, {result['n_sources']} sources)."
            )
            if result.get("cellpack_recipe_path", None) and result.get("cellpack_result_path", None):
                msg += (
                    " Membrane bundle: "
                    f"{result['cellpack_recipe_path']} "
                    f"and {result['cellpack_result_path']} "
                    f"({int(result.get('n_membrane_particles', 0))} particles across "
                    f"{int(result.get('n_membranes', 0))} membrane compartments)."
                )
            if result.get("cellpack_cif_path", None):
                msg += f" Membrane mmCIF: {result['cellpack_cif_path']}."
            self.session.logger.info(msg)
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

    def _load_cellpack_package(self):
        from Qt.QtWidgets import QMessageBox, QFileDialog
        from . import cmd
        from .local_apr import open_local_cellpack_package

        try:
            path, _selected_filter = QFileDialog.getOpenFileName(
                self.tool_window.ui_area,
                "Choose cellPACK file",
                os.path.expanduser("~/"),
                "cellPACK files (*.apr.json ciliabuilder_manifest.json recipe.json *.json);;All files (*)",
            )
            if not path:
                return
            model, info = open_local_cellpack_package(self.session, path)
            cmd._add_to_cb_map_group(self.session, model)
            cmd._log_local_cellpack_load(self.session, info)
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _load_star_file(self):
        from Qt.QtWidgets import QMessageBox, QFileDialog
        from . import cmd
        from .star import read_star_file, ciliabuilder_rows_from_text

        try:
            path, _selected_filter = QFileDialog.getOpenFileName(
                self.tool_window.ui_area,
                "Choose STAR file",
                os.path.expanduser("~/"),
                "STAR files (*.star);;All files (*)",
            )
            if not path:
                return
            star_text = read_star_file(path)
            rows = ciliabuilder_rows_from_text(
                star_text,
                default_pixel_size=float(self.pixel_size.value()),
            )
            if not rows:
                raise RuntimeError("STAR file contains no particle rows")

            base_name = os.path.splitext(os.path.basename(str(path)))[0]
            created = Model(self._next_loaded_star_name(base_name), self.session)
            cmd._add_to_cb_star_group(self.session, created)
            created._cb_star_rows = rows
            created._cb_star_text = star_text
            created._cb_star_path = os.path.abspath(os.path.expanduser(str(path)))
            cmd._render_star_model(self.session, created, rows, True)
            self._store_model_saved_path(created, created._cb_star_path)
            self._remember_loaded_star_role(created)
            self._select_star_model(created)
            try:
                created.display = True
                created.set_selected(True)
            except Exception:
                pass
            self.session.logger.info(
                f"Loaded STAR file {created._cb_star_path} as {created.name} "
                f"({len(rows)} STAR points)."
            )
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

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

    def _is_glb_like(self, model):
        if model is None:
            return False
        cls_name = model.__class__.__name__.lower()
        if "gltf" in cls_name or "glb" in cls_name:
            return True
        model_name = str(getattr(model, "name", "") or "").lower()
        return model_name.endswith((".glb", ".gltf"))

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
        if self._is_volume_like(model) or self._is_surface_like(model) or self._is_atomic_like(model):
            return True
        if self._is_glb_like(model):
            try:
                children = list(model.child_models())
            except Exception:
                children = []
            for child in children:
                if self._is_volume_like(child) or self._is_surface_like(child) or self._is_atomic_like(child):
                    return True
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
            random_max_diff = max(0.0, 0.49 * spacing)

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
                if random_spacing:
                    self._star_random_clip_info(model)
                else:
                    model._cb_random_clip_info = None
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
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _build_centriole(self):
        from Qt.QtWidgets import QMessageBox
        from . import cmd

        try:
            length = float(self.centriole_length.value())
            spacing = float(self.centriole_spacing.value())
            z_offset = float(self.centriole_z_offset.value())
            mode = str(self.centriole_mode.currentData() or "singlet")
            c1c2_distance = float(self.centriole_c1c2_distance.value())

            pixel_size = float(self.pixel_size.value())
            built_models = []
            cp_half_sep = 0.5 * float(c1c2_distance)

            def build_one(name_prefix, tube_id, x_offset):
                model = cmd.buildcentriole(
                    self.session,
                    length=length,
                    spacing=spacing,
                    z_offset=z_offset,
                    tube_id=tube_id,
                    x_offset=x_offset,
                    pixel_size=pixel_size,
                    show_arrows=True,
                    open_star=True,
                    print_star=False,
                    name_prefix=name_prefix,
                )
                built_models.append((model, tube_id))
                try:
                    if self._last_outer_star_model is not None:
                        self._inherit_clip_info(model, self._last_outer_star_model)
                except Exception:
                    pass
                return model

            if mode == "doublet":
                build_one("Central pair C1 STAR", 100, -cp_half_sep)
                build_one("Central pair C2 STAR", 101, cp_half_sep)
                self._last_cent_star_model = built_models[-1][0]
            else:
                self._last_cent_star_model = build_one("Central pair STAR", 100, 0.0)

            try:
                max_cent = None
                for model, tube_id in built_models:
                    rows = getattr(model, "_cb_star_rows", None) or []
                    px = float(pixel_size)
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
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _build_membrane(self):
        from Qt.QtWidgets import QMessageBox
        from . import cmd

        try:
            length = float(self.membrane_length.value())
            radius = float(self.membrane_radius.value())
            thickness = float(self.membrane_thickness.value())
            offset = float(self.membrane_offset.value())
            distortion_level = float(self.membrane_distortion.value())
            tip_dome_enabled = bool(self.membrane_tip_dome.isChecked())
            diameter = 2.0 * radius

            if length <= 0.0:
                raise RuntimeError("Membrane length must be > 0")
            if radius <= 0.0:
                raise RuntimeError("Membrane radius must be > 0")
            if thickness <= 0.0:
                raise RuntimeError("Membrane thickness must be > 0")
            if thickness >= radius:
                raise RuntimeError("Membrane thickness must be smaller than the radius")

            anchor = self._membrane_anchor_info()
            axis = np.array(anchor["axis"], dtype=float)
            axis_norm = float(np.linalg.norm(axis))
            axis = axis / axis_norm if axis_norm > 1e-9 else np.array([0.0, 0.0, 1.0], dtype=float)
            axis_center = np.array(anchor.get("axis_center", (0.0, 0.0, 0.0)), dtype=float)
            center_scalar = float(np.dot(axis_center, axis))
            start_scalar = float(anchor["start_scalar"]) + offset
            start_center = axis_center + axis * (start_scalar - center_scalar)
            membrane_center = start_center + axis * (0.5 * length)
            tip_scalar = float(start_scalar + length)
            tip_dome_outer_height = None
            tip_dome_inner_height = None
            if tip_dome_enabled:
                tip_dome_outer_height, tip_dome_inner_height = self._membrane_tip_dome_heights(
                    anchor.get("star_model", None),
                    axis,
                    tip_scalar,
                    radius,
                    thickness,
                )

            model = cmd.buildmembrane_surface(
                self.session,
                name=f"Membrane {getattr(self, '_membrane_counter', 0) + 1}",
                center=membrane_center,
                axis=axis,
                length=length,
                diameter=diameter,
                thickness=thickness,
                distortion_level=distortion_level,
                tip_dome_enabled=tip_dome_enabled,
                tip_dome_outer_height=tip_dome_outer_height,
                tip_dome_inner_height=tip_dome_inner_height,
            )
            self._membrane_counter = getattr(self, "_membrane_counter", 0) + 1
            try:
                state = getattr(model, "_cb_membrane_state", None) or {}
                state["offset"] = float(offset)
                state["distortion_level"] = float(distortion_level)
                state["radius"] = float(radius)
                state["tip_dome_enabled"] = bool(tip_dome_enabled)
                state["tip_dome_outer_height"] = (
                    None if tip_dome_outer_height is None else float(tip_dome_outer_height)
                )
                state["tip_dome_inner_height"] = (
                    None if tip_dome_inner_height is None else float(tip_dome_inner_height)
                )
                state["source_star_name"] = str(getattr(anchor.get("star_model", None), "name", "") or "")
                state["start_scalar"] = float(start_scalar)
                model._cb_membrane_state = state
            except Exception:
                pass
            try:
                model.display = True
                model.set_selected(True)
            except Exception:
                pass
            self.session.logger.info(f"Built membrane model {model.name}.")

        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _place_ift_on_selected_filament(self):
        from Qt.QtWidgets import QMessageBox

        try:
            target = self._attachment_target_from_snapshot(self._ift_target_snapshot)
            if target is None:
                target = self._selected_attachment_target()
                self._ift_target_snapshot = self._snapshot_attachment_target(target)
                label = self._ift_target_snapshot["selected_model_name"] or self._ift_target_snapshot["attached_root_name"] or "selected filament"
                self.ift_target_label.setText(label)
            self._generate_ift_star_from_target(target)
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

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

        try:
            self._refresh_model_selectors()
            star_id = self.sel_star_model.currentData()
            map_id = self.sel_map_model.currentData()
            self._perform_attachment(star_id=star_id, map_id=map_id, remember_selection=True)
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._keep_tool_visible()

    def _undo_last_attachment(self):
        from Qt.QtWidgets import QMessageBox

        try:
            out_root = self._latest_attached_result()
            if out_root is None:
                raise RuntimeError("No attached result to undo")
            removed_name = str(getattr(out_root, "name", "") or "attached result")
            star_ref = str(getattr(out_root, "_cb_attachment_star_ref", "") or "").strip()
            star_name = str(getattr(out_root, "_cb_attachment_star_name", "") or "").strip()
            star_model = self._model_by_ref(star_ref) if star_ref else None
            if star_model is None and star_name:
                star_model = self._find_model_by_name(star_name, require_star=True)
            for attach_key, candidate in list(self._attached_results.items()):
                if candidate is out_root:
                    self._attached_results.pop(attach_key, None)
            try:
                self.session.models.close([out_root])
            except Exception:
                pass
            if star_model is not None:
                try:
                    star_model.display = True
                except Exception:
                    pass
            self._last_attached_result = self._latest_attached_result()
            self._last_attach_star_id = None
            self._last_attach_map_id = None
            try:
                _run(self.session, "select clear", log=False)
            except Exception:
                pass
            self.session.logger.info(f"Removed most recent attachment {removed_name}.")
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._refresh_model_selectors()
            self._keep_tool_visible()

    def _perform_attachment(self, star_id=None, map_id=None, remember_selection=False):
        from .map import cbsubmap_impl

        if star_id is None:
            star_id = self._last_attach_star_id
        if map_id is None:
            map_id = self._last_attach_map_id
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
            raise RuntimeError(f"Model #{map_id} is not a map/STL/GLB/PDB/CIF attach source")

        source_color_state = self._capture_model_color_state(map_model)
        self._zero_map_origin_index(map_model)
        pre_rotate_y_90 = self._attach_pre_rotate_y_90_enabled()

        star_id = str(star_id)
        map_id = str(map_id)
        attach_key = self._attach_key(star_model, map_model)
        old_result = self._attached_results.get(attach_key)
        if old_result is not None:
            try:
                self.session.models.close([old_result])
            except Exception:
                pass
            self._attached_results.pop(attach_key, None)
            if self._last_attached_result is old_result:
                self._last_attached_result = None

        out_root = cbsubmap_impl(
            session=self.session,
            star_model_obj=star_model,
            map_model_id=map_id,
            close_source=False,
            show_result=True,
            rotate_xy_90=True,
            single_big_object=True,
            attach_all_z_offset_deg=float(self.attach_line_rotation.value()),
            attach_auto_align_long_axis=False,
            attach_inout_flip=False,
            attach_updown_flip=False,
            attach_axis_rot_y_deg=0.0,
            attach_axis_rot_z_deg=-90.0,
            attach_x_movement=0.0,
            attach_local_adjust_matrix=self._current_attach_adjust_matrix(
                pre_rotate_y_90=pre_rotate_y_90,
            ).tolist(),
        )
        self._apply_source_color_state_to_attached_result(out_root, source_color_state)
        try:
            out_root._cb_attachment_line_rotation = float(self.attach_line_rotation.value())
            out_root._cb_attachment_y_rotation = float(self.attach_y_rotation.value())
            out_root._cb_attachment_x_movement = 0.0
            out_root._cb_attachment_pre_rotate_y_90 = pre_rotate_y_90
            out_root._cb_attachment_star_name = str(star_model.name)
            out_root._cb_attachment_map_name = str(map_model.name)
            out_root._cb_attachment_map_path = self._model_source_path(map_model)
            out_root._cb_attachment_source_ref = self._model_ref(map_model)
            fetch_spec = self._fetch_spec_for_model(map_model)
            if fetch_spec is not None:
                out_root._cb_attachment_fetch_type = fetch_spec.get("fetch_type")
                out_root._cb_attachment_fetch_id = fetch_spec.get("fetch_id")
        except Exception:
            pass
        self._last_attached_result = out_root
        self._attached_results[attach_key] = out_root

        self._archive_attach_source_model(map_model)
        current_star_id = self._model_ref(star_model) or str(star_id)
        current_map_id = self._model_ref(map_model) or str(map_id)
        self._last_attach_star_id = current_star_id
        self._last_attach_map_id = current_map_id
        try:
            out_root._cb_attachment_source_ref = current_map_id
            out_root._cb_attachment_star_ref = current_star_id
        except Exception:
            pass
        try:
            star_model.display = False
        except Exception:
            pass
        try:
            self._apply_attachment_clip_if_needed(out_root, star_model)
        except Exception:
            # Keep attachment usable even if clip application fails.
            pass
        self._refresh_model_selectors()
        if remember_selection:
            try:
                self._select_star_model(star_model)
            except Exception:
                pass
            try:
                self._select_map_model(map_model)
            except Exception:
                pass

    def _reattach_with_current_settings(self, _value):
        from Qt.QtWidgets import QMessageBox

        if self._attach_rebuild_in_progress:
            return
        if self._last_attach_star_id is None or self._last_attach_map_id is None:
            return

        try:
            self._attach_rebuild_in_progress = True
            self._perform_attachment(remember_selection=False)
        except Exception as e:
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._attach_rebuild_in_progress = False
            self._keep_tool_visible()


def start_tool(session, tool_name):
    return CiliaBuilder2Tool(session, tool_name)
