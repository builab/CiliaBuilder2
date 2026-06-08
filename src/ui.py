# vim: set expandtab shiftwidth=4 softtabstop=4:

from chimerax.core.tools import ToolInstance
from chimerax.ui import MainToolWindow
from chimerax.core.commands import run as _run

from Qt.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QFileDialog,
    QComboBox,
    QLabel,
)
from Qt.QtCore import Qt


class CiliaBuilder2Panel(ToolInstance):
    SESSION_ENDURING = False
    SESSION_SAVE = False

    def __init__(self, session, tool_name):
        super().__init__(session, tool_name)
        self.tool_window = MainToolWindow(self)
        self._build_ui()
        self.tool_window.manage(placement="side")

    def _build_ui(self):
        root = QWidget()
        main = QHBoxLayout()
        root.setLayout(main)

        left = self._make_outer_panel()
        right = self._make_central_pair_panel()

        main.addWidget(left, 1)
        main.addWidget(right, 1)

        bottom = QVBoxLayout()
        bottom.addLayout(main)

        controls = QHBoxLayout()
        self.btn_build = QPushButton("Build STAR and open")
        self.btn_build.clicked.connect(self._on_build)

        self.btn_help = QPushButton("Print command")
        self.btn_help.clicked.connect(self._on_print_cmd)

        controls.addWidget(self.btn_build)
        controls.addWidget(self.btn_help)
        controls.addStretch(1)

        outer_layout = QVBoxLayout()
        outer_layout.addLayout(bottom)
        outer_layout.addLayout(controls)

        wrapper = QWidget()
        wrapper.setLayout(outer_layout)

        self.tool_window.ui_area.setLayout(QVBoxLayout())
        self.tool_window.ui_area.layout().addWidget(wrapper)

    def _make_outer_panel(self):
        box = QGroupBox("Microtubules")
        form = QFormLayout()
        box.setLayout(form)

        self.outer_n = QSpinBox()
        self.outer_n.setRange(1, 9)
        self.outer_n.setValue(9)

        self.outer_length = QDoubleSpinBox()
        self.outer_length.setRange(1.0, 1e9)
        self.outer_length.setDecimals(1)
        self.outer_length.setValue(9000.0)

        self.outer_radius = QDoubleSpinBox()
        self.outer_radius.setRange(0.0, 1e9)
        self.outer_radius.setDecimals(1)
        self.outer_radius.setValue(700.0)

        self.outer_period = QDoubleSpinBox()
        self.outer_period.setRange(1.0, 1e9)
        self.outer_period.setDecimals(1)
        self.outer_period.setValue(960.0)

        self.angle_set = QDoubleSpinBox()
        self.angle_set.setRange(-3600.0, 3600.0)
        self.angle_set.setDecimals(1)
        self.angle_set.setValue(0.0)

        self.psi_offset = QDoubleSpinBox()
        self.psi_offset.setRange(-3600.0, 3600.0)
        self.psi_offset.setDecimals(1)
        self.psi_offset.setValue(0.0)

        self.z_offset = QDoubleSpinBox()
        self.z_offset.setRange(-1e9, 1e9)
        self.z_offset.setDecimals(1)
        self.z_offset.setValue(0.0)

        self.tomo_name = QLineEdit("TS_001")

        self.pixel_size = QDoubleSpinBox()
        self.pixel_size.setRange(0.0001, 1e6)
        self.pixel_size.setDecimals(4)
        self.pixel_size.setValue(1.0)

        self.star_format = QComboBox()
        self.star_format.addItem("RELION STAR file")
        self.star_format.addItem("RELION5 STAR file")

        self.auto_map = QCheckBox("Auto map attachment")
        self.map_model = QSpinBox()
        self.map_model.setRange(0, 999999)
        self.map_model.setValue(0)


        self.btn_open_map = QPushButton("Open map file")
        self.btn_open_map.clicked.connect(self._on_open_map)

        form.addRow("No of doublets", self.outer_n)
        form.addRow("Length", self.outer_length)
        form.addRow("Radius", self.outer_radius)
        form.addRow("Periodicity", self.outer_period)
        form.addRow("Angle of set", self.angle_set)
        form.addRow("Psi offset", self.psi_offset)
        form.addRow("Z offset", self.z_offset)
        form.addRow("Tomo name", self.tomo_name)
        form.addRow("Pixel size", self.pixel_size)
        form.addRow("STAR format", self.star_format)
        form.addRow(self.auto_map, QLabel(""))
        form.addRow("Map model id", self.map_model)
        form.addRow(self.btn_open_map, QLabel(""))

        return box

    def _make_central_pair_panel(self):
        box = QGroupBox("Central pair")
        form = QFormLayout()
        box.setLayout(form)

        self.cen_enable = QCheckBox("Build central pair in center")
        self.cen_enable.setChecked(False)

        self.cen_length = QDoubleSpinBox()
        self.cen_length.setRange(1.0, 1e9)
        self.cen_length.setDecimals(1)
        self.cen_length.setValue(1800.0)

        self.cen_period = QDoubleSpinBox()
        self.cen_period.setRange(1.0, 1e9)
        self.cen_period.setDecimals(1)
        self.cen_period.setValue(320.0)

        self.cen_z_offset = QDoubleSpinBox()
        self.cen_z_offset.setRange(-1e9, 1e9)
        self.cen_z_offset.setDecimals(1)
        self.cen_z_offset.setValue(0.0)

        form.addRow(self.cen_enable, QLabel(""))
        form.addRow("Length", self.cen_length)
        form.addRow("Periodicity", self.cen_period)
        form.addRow("Z offset", self.cen_z_offset)

        return box

    def _make_centriole_panel(self):
        return self._make_central_pair_panel()

    def _on_open_map(self):
        path, _ = QFileDialog.getOpenFileName(self.tool_window.ui_area, "Open map", "", "Map files (*.mrc *.map *.ccp4 *.mrcs);;All files (*)")
        if not path:
            return

        before = set([m.id_string for m in self.session.models.list()])
        try:
            _run(self.session, f'open "{path}"')
        except Exception as e:
            self.session.logger.error(f"open map failed: {e}")
            return

        after = [m for m in self.session.models.list() if m.id_string not in before]
        if after:
            top = after[-1]
            if getattr(top, "id", None) and len(top.id) == 1:
                self.map_model.setValue(int(top.id[0]))

    def _build_command_text(self):
        fmt = self.star_format.currentText().strip()

        cmd = "cbstraight"
        cmd += f" n_cilia {int(self.outer_n.value())}"
        cmd += f" length {float(self.outer_length.value())}"
        cmd += f" bead_spacing {float(self.outer_period.value())}"
        cmd += f" outer_radius {float(self.outer_radius.value())}"
        cmd += f' tomo_name "{self.tomo_name.text().strip()}"'
        cmd += f" pixel_size {float(self.pixel_size.value())}"
        cmd += f" angle_offset {float(self.angle_set.value())}"
        cmd += f" psi_offset {float(self.psi_offset.value())}"
        cmd += f" z_offset {float(self.z_offset.value())}"
        cmd += f' star_format "{fmt}"'
        cmd += " open_star true"
        cmd += " print_star true"

        if self.cen_enable.isChecked():
            cmd += " build_centriole true"
            cmd += f" centriole_length {float(self.cen_length.value())}"
            cmd += f" centriole_spacing {float(self.cen_period.value())}"
            cmd += f" centriole_z_offset {float(self.cen_z_offset.value())}"

        if self.auto_map.isChecked():
            mid = int(self.map_model.value())
            if mid > 0:
                cmd += " auto_map true"
                cmd += f" map_model {mid}"

        return cmd

    def _on_print_cmd(self):
        cmd = self._build_command_text()
        self.session.logger.info(cmd)

    def _on_build(self):
        cmd = self._build_command_text()
        try:
            _run(self.session, cmd)
        except Exception as e:
            self.session.logger.error(f"build failed: {e}")
