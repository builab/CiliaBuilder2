# vim: set expandtab shiftwidth=4 softtabstop=4:

from chimerax.core.tools import ToolInstance
from chimerax.ui import MainToolWindow

from Qt.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
    QGroupBox,
    QDoubleSpinBox,
    QSpinBox,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QComboBox,
    QFileDialog,
)
from Qt.QtCore import Qt


def get_or_create_tool(session):
    for t in session.tools.list():
        try:
            if t.display_name == "CiliaBuilder2":
                t.tool_window.manage(placement="side")
                return t
        except Exception:
            pass
    return CiliaBuilder2Tool(session, "CiliaBuilder2")


class CiliaBuilder2Tool(ToolInstance):
    SESSION_ENDURING = False

    def __init__(self, session, tool_name):
        super().__init__(session, tool_name)
        self.display_name = "CiliaBuilder2"

        self.tool_window = MainToolWindow(self)
        self._build_ui()
        self.tool_window.manage(placement="side")

    def _spin_float(self, v, mn, mx, step, decimals=2):
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setRange(mn, mx)
        s.setSingleStep(step)
        s.setValue(v)
        s.setKeyboardTracking(False)
        return s

    def _spin_int(self, v, mn, mx, step=1):
        s = QSpinBox()
        s.setRange(mn, mx)
        s.setSingleStep(step)
        s.setValue(v)
        s.setKeyboardTracking(False)
        return s

    def _build_ui(self):
        main = QWidget()
        outer = QGroupBox("Outer cilia")
        cent = QGroupBox("Centriole")

        outer_form = QFormLayout()
        cent_form = QFormLayout()

        self.angle_set = self._spin_float(0.0, -360.0, 360.0, 1.0, decimals=2)
        self.length = self._spin_float(9000.0, 0.0, 1e7, 100.0, decimals=2)
        self.n_doublet = self._spin_int(9, 1, 9, 1)
        self.radius = self._spin_float(700.0, 0.0, 1e7, 10.0, decimals=2)
        self.spacing = self._spin_float(400.0, 0.0, 1e7, 10.0, decimals=2)
        self.z_offset = self._spin_float(0.0, -1e7, 1e7, 10.0, decimals=2)
        self.doublet_offset = self._spin_float(0.0, -360.0, 360.0, 1.0, decimals=2)

        self.map_path_outer = QLineEdit()
        self.map_path_outer.setPlaceholderText("optional map path")
        self.btn_browse_outer = QPushButton("Browse")
        self.btn_browse_outer.clicked.connect(lambda: self._browse_into(self.map_path_outer))

        row_map_outer = QWidget()
        hmo = QHBoxLayout()
        hmo.setContentsMargins(0, 0, 0, 0)
        hmo.addWidget(self.map_path_outer, 1)
        hmo.addWidget(self.btn_browse_outer)
        row_map_outer.setLayout(hmo)

        outer_form.addRow("Angle of set (deg)", self.angle_set)
        outer_form.addRow("Length", self.length)
        outer_form.addRow("No. of doublet", self.n_doublet)
        outer_form.addRow("Radius", self.radius)
        outer_form.addRow("Periodicity (spacing)", self.spacing)
        outer_form.addRow("Z offset", self.z_offset)
        outer_form.addRow("Doublet offset (deg)", self.doublet_offset)
        outer_form.addRow("Map path", row_map_outer)
        outer.setLayout(outer_form)

        self.cent_length = self._spin_float(2000.0, 0.0, 1e7, 100.0, decimals=2)
        self.cent_spacing = self._spin_float(400.0, 0.0, 1e7, 10.0, decimals=2)

        self.map_path_cent = QLineEdit()
        self.map_path_cent.setPlaceholderText("optional centriole map path")
        self.btn_browse_cent = QPushButton("Browse")
        self.btn_browse_cent.clicked.connect(lambda: self._browse_into(self.map_path_cent))

        row_map_cent = QWidget()
        hmc = QHBoxLayout()
        hmc.setContentsMargins(0, 0, 0, 0)
        hmc.addWidget(self.map_path_cent, 1)
        hmc.addWidget(self.btn_browse_cent)
        row_map_cent.setLayout(hmc)

        self.chk_build_cent = QCheckBox("Build centriole in center")
        self.chk_build_cent.setChecked(False)

        cent_form.addRow("Length", self.cent_length)
        cent_form.addRow("Periodicity (spacing)", self.cent_spacing)
        cent_form.addRow("Map path", row_map_cent)
        cent_form.addRow(self.chk_build_cent)
        cent.setLayout(cent_form)

        misc = QFormLayout()
        self.tomo_name = QLineEdit()
        self.tomo_name.setText("TS_001")
        self.pixel_size = self._spin_float(10.0, 1e-6, 1e6, 0.1, decimals=6)

        self.star_format = QComboBox()
        self.star_format.addItems(["relion", "relion5"])
        self.star_format.setCurrentText("relion")

        self.chk_open_star = QCheckBox("Open STAR")
        self.chk_open_star.setChecked(True)

        misc.addRow("Tomo name", self.tomo_name)
        misc.addRow("Pixel size", self.pixel_size)
        misc.addRow("STAR format", self.star_format)
        misc.addRow(self.chk_open_star)

        btn_build = QPushButton("Build")
        btn_build.setMinimumHeight(28)
        btn_build.clicked.connect(self._on_build)

        left_right = QHBoxLayout()
        left_right.addWidget(outer, 1)
        left_right.addWidget(cent, 1)

        v = QVBoxLayout()
        v.addLayout(left_right)
        v.addLayout(misc)
        v.addWidget(btn_build)

        main.setLayout(v)
        self.tool_window.ui_area.setLayout(QVBoxLayout())
        self.tool_window.ui_area.layout().addWidget(main)

    def _browse_into(self, line_edit):
        p, _ = QFileDialog.getOpenFileName(self.tool_window.ui_area, "Select file")
        if p:
            line_edit.setText(p)

    def _on_build(self):
        from . import cmd

        map_path = self.map_path_outer.text().strip()
        cent_map_path = self.map_path_cent.text().strip()

        auto_map = True if map_path else False

        try:
            cmd.cbstraight(
                self.session,
                n_cilia=int(self.n_doublet.value()),
                length=float(self.length.value()),
                spacing=float(self.spacing.value()),
                radius=float(self.radius.value()),
                angle_set=float(self.angle_set.value()),
                z_offset=float(self.z_offset.value()),
                doublet_offset=float(self.doublet_offset.value()),
                tomo_name=str(self.tomo_name.text()).strip(),
                pixel_size=float(self.pixel_size.value()),
                open_star=bool(self.chk_open_star.isChecked()),
                star_format=str(self.star_format.currentText()),
                print_star=False,
                map_path=map_path,
                auto_map=bool(auto_map),
                close_source_after_map=True,
                build_centriole=bool(self.chk_build_cent.isChecked()),
                centriole_length=float(self.cent_length.value()),
                centriole_spacing=float(self.cent_spacing.value()),
                centriole_map_path=cent_map_path,
            )
        except Exception as e:
            self.session.logger.error(f"Build failed {e}")
            raise
