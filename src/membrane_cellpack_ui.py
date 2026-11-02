"""Optional membrane-only preview dialog, using ChimeraX's existing dependencies."""

from pathlib import Path
import copy
import tempfile
import time
import uuid

from Qt.QtCore import QEventLoop, QTimer
from Qt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                          QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                          QTableWidget, QVBoxLayout, QWidget)

from .membrane_cellpack import (MAX_FILL_PARTICLES, MAX_RECIPE_PARTICLES, PACKING_KEY, apply_result,
                               export_packing)
from .membrane_protein import fetch_protein
from .membrane_molecule import ingredient_source, load_lipid, molecular_lipid
from .membrane_recipe import RecipePacker, default_recipe, template_key, validate_recipe


class MembraneCellpackDialog(QDialog):
    def __init__(self, tool, model):
        super().__init__(tool.tool_window.ui_area)
        self.tool, self.model = tool, None
        self.packer = None
        self._running = False
        self._drafts = {}
        self.templates = {}
        self.setWindowTitle("Particle membrane packing")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.target = QComboBox(self)
        form.addRow("Target membrane", self.target)
        self.target.currentIndexChanged.connect(self._target_changed)
        self.automatic_count = QCheckBox("Automatic dense-fill budget", self)
        self.automatic_count.setToolTip("Calculate particle count from leaflet area and bead radius, up to 1,000,000. "
                                       "Smaller beads need more particles; no automatic thinning at 50,000.")
        form.addRow(self.automatic_count)
        self.count = QSpinBox(self)
        self.count.setRange(1, MAX_RECIPE_PARTICLES)
        self.count.setToolTip("Manual preview cap. Too few particles leave gaps, even if every requested particle fits.")
        self.count.setEnabled(not self.automatic_count.isChecked())
        self.automatic_count.toggled.connect(lambda enabled: self.count.setEnabled(not enabled))
        form.addRow("Manual preview limit", self.count)
        self.seed = QSpinBox(self)
        self.seed.setRange(0, 2147483647)
        form.addRow("Random seed", self.seed)
        self.table = QTableWidget(0, 10, self)
        self.table.setHorizontalHeaderLabels(["Use", "Type", "Name", "Amount (%)", "Radius (A)",
                                              "Source", "PDB ID / file", "Outward axis", "Leaflet", "Remove"])
        self.rows = []
        layout.addWidget(self.table)
        self.add_buttons = []
        row_buttons = QHBoxLayout()
        for kind, title in (("lipid", "Add lipid"), ("protein", "Add protein"), ("other", "Add other bead")):
            button = QPushButton(title, self)
            button.clicked.connect(lambda checked=False, kind=kind: self.add_ingredient(kind))
            row_buttons.addWidget(button)
            self.add_buttons.append(button)
        layout.addLayout(row_buttons)
        self.resize(1200, 560)
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.run_button = QPushButton("Pack membrane", self)
        self.run_button.clicked.connect(self.start)
        buttons.addWidget(self.run_button)
        self.export_button = QPushButton("Export package...", self)
        self.export_button.clicked.connect(self.export)
        buttons.addWidget(self.export_button)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        close = QPushButton("Close", self)
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.credit = QLabel('Inspired by <a href="https://doi.org/10.1038/nmeth.3204">'
                             'cellPACK (Johnson et al., 2015)</a>. Independent implementation.', self)
        self.credit.setOpenExternalLinks(True)
        layout.addWidget(self.credit)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.timer = QTimer(self)
        self.timer.setInterval(1)
        self.timer.timeout.connect(self._advance)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self._refresh_targets)
        from chimerax.core.models import ADD_MODELS, REMOVE_MODELS, MODEL_ID_CHANGED, MODEL_NAME_CHANGED
        handlers = [tool.session.triggers.add_handler(name, lambda *_: self.refresh_timer.start(0))
                    for name in (ADD_MODELS, REMOVE_MODELS, MODEL_ID_CHANGED, MODEL_NAME_CHANGED)]

        def disconnect(*_):
            for handler in handlers:
                handler.remove()
            handlers.clear()

        self.finished.connect(disconnect)
        self.destroyed.connect(disconnect)
        self._refresh_targets(model)

    def _refresh_targets(self, preferred=None):
        # Defer scene notifications until their add/remove transaction finishes.
        # Never retarget a running calculation, including synchronous PDB preparation.
        if self._running:
            return
        models = [m for m in self.tool.session.models.list()
                  if getattr(m, "_cb_generated_membrane", False)
                  and getattr(m, "_cb_membrane_state", None)]
        chosen = preferred if preferred in models else self.model
        if chosen not in models:
            chosen = models[-1] if models else None
        self._drafts = {m: state for m, state in self._drafts.items() if m in models}
        previous = self.target.blockSignals(True)
        self.target.clear()
        for model in models:
            self.target.addItem(f"{model.name} (#{model.id_string})", model)
        if chosen is None:
            self.target.addItem("No membranes available", None)
        else:
            self.target.setCurrentIndex(models.index(chosen))
        self.target.blockSignals(previous)
        if chosen is not self.model:
            self._load_target(chosen)
        self._update_controls()

    def _target_changed(self, _index):
        if self._running:
            previous = self.target.blockSignals(True)
            self.target.setCurrentIndex(self.target.findData(self.model))
            self.target.blockSignals(previous)
            return
        chosen = self.target.currentData()
        if chosen is not self.model:
            self._load_target(chosen)
        self._update_controls()

    def _load_target(self, model):
        if self.model in self.tool.session.models.list():
            self._drafts[self.model] = dict(
                saved=self.model._cb_membrane_state.get(PACKING_KEY), recipe=self.recipe(),
                automatic_particle_budget=self.automatic_count.isChecked(),
                particle_limit=self.count.value(), seed=self.seed.value())
        self.model = model
        self.rows.clear()
        self.table.setRowCount(0)
        self.status.setText("" if model is not None else "Build a membrane to pack.")
        if model is None:
            return
        saved = model._cb_membrane_state.get(PACKING_KEY)
        draft = self._drafts.get(model, {})
        settings = draft if draft and draft["saved"] is saved else (saved or {})
        self.templates.update(copy.deepcopy((saved or {}).get("templates", {})))
        recipe = settings.get("recipe")
        if recipe is None:
            recipe = default_recipe(settings.get("lipid_radius") or max(.1, model._cb_membrane_state["thickness"]*.5))
            if settings.get("protein"):
                protein = settings["protein"]
                recipe[1].update(enabled=settings.get("protein_percent", 0) > 0,
                                 amount=settings.get("protein_percent", 0), pdb_id=protein["pdb_id"], axis=protein["axis"])
                self.templates[template_key(protein)] = copy.deepcopy(protein)
        self.automatic_count.setChecked(settings.get("automatic_particle_budget", True))
        self.count.setValue(settings.get("particle_limit", MAX_FILL_PARTICLES))
        self.seed.setValue(settings.get("seed", 1))
        for entry in recipe:
            self.add_ingredient(entry["kind"], entry)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, max(120, self.table.columnWidth(1)))
        self.table.setColumnWidth(6, 230)

    def add_ingredient(self, kind, entry=None):
        if len(self.rows) >= 20:
            self.status.setText("At most 20 ingredients are supported.")
            return
        if entry is None:
            entry = dict(key=uuid.uuid4().hex, kind=kind, label=kind.title(), enabled=True,
                         amount=20 if kind == "protein" else 100, radius=20., region="outer" if kind == "protein" else "both",
                         pdb_id="", axis="Z")
        row = dict(key=entry["key"], kind=kind)
        row["enabled"] = QCheckBox(self.table)
        row["enabled"].setChecked(entry["enabled"])
        row["label"] = QLineEdit(entry["label"], self.table)
        row["amount"] = QDoubleSpinBox(self.table)
        row["amount"].setRange(0, 100)
        row["amount"].setValue(entry["amount"])
        row["amount"].setToolTip("Protein: nominal outer leaflet coverage. Lipids/other beads: relative area share on this leaflet.")
        row["radius"] = QDoubleSpinBox(self.table)
        row["radius"].setRange(.1, 10000)
        row["radius"].setValue(entry["radius"])
        row["radius"].setEnabled(kind != "protein")
        row["pdb_id"] = QLineEdit(entry.get("pdb_id", ""), self.table)
        row["pdb_id"].setPlaceholderText("e.g. 1AFO")
        row["source"] = QComboBox(self.table)
        for title, source in (("Bead", "bead"), ("PDB ID", "pdb"), ("Local file", "file")):
            if kind == "lipid" or (kind == "protein" and source == "pdb") or (kind == "other" and source == "bead"):
                row["source"].addItem(title, source)
        row["source"].setCurrentIndex(row["source"].findData(ingredient_source(entry)))
        row["file_path"] = QLineEdit(entry.get("file_path", ""), self.table)
        row["file_path"].setPlaceholderText("Lipid structure file")
        row["file_path"].editingFinished.connect(lambda row=row: self._normalize_file_path(row))
        row["residue_name"] = QLineEdit(entry.get("residue_name", ""), self.table)
        row["residue_name"].setPlaceholderText("Residue (optional, e.g. DGA)")
        row["residue_name"].setToolTip("One copy of this non-water, non-polymer residue. Required if the source has multiple component types.")
        row["browse"] = QPushButton("Browse...", self.table)
        row["browse"].setAutoDefault(False)
        row["browse"].clicked.connect(lambda checked=False, row=row: self._browse_lipid(row))
        source_panel = QWidget(self.table)
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        file_layout = QHBoxLayout()
        file_layout.addWidget(row["pdb_id"])
        file_layout.addWidget(row["file_path"])
        file_layout.addWidget(row["browse"])
        source_layout.addLayout(file_layout)
        source_layout.addWidget(row["residue_name"])
        row["axis"] = QComboBox(self.table)
        row["axis"].addItems(["Z", "X", "Y", "-Z", "-X", "-Y"])
        row["axis"].setCurrentText(entry.get("axis", "Z"))
        row["axis"].setToolTip("For molecular lipids, point this source axis toward the leaflet exterior; the molecule extends into the wall. Dimensions are not rescaled.")
        row["pdb_id"].setEnabled(kind == "protein")
        row["axis"].setEnabled(kind == "protein")
        row["region"] = QComboBox(self.table)
        row["region"].addItems(["outer"] if kind == "protein" else ["both", "outer", "inner"])
        row["region"].setCurrentText(entry["region"])
        remove = QPushButton("Remove", self.table)
        remove.setAutoDefault(False)
        remove.clicked.connect(lambda checked=False, row=row: self.remove_ingredient(row))
        widgets = [row["enabled"], QLabel("Protein (PDB)" if kind == "protein" else "Lipid" if kind == "lipid" else "Other bead"),
                   row["label"], row["amount"], row["radius"], row["source"], source_panel, row["axis"], row["region"], remove]
        index = self.table.rowCount()
        self.table.insertRow(index)
        for column, widget in enumerate(widgets):
            self.table.setCellWidget(index, column, widget)
        self.rows.append(row)
        row["source"].currentIndexChanged.connect(lambda _index, row=row: self._ingredient_source_changed(row))
        self._ingredient_source_changed(row)

    def _ingredient_source_changed(self, row):
        source = row["source"].currentData()
        row["radius"].setEnabled(source == "bead")
        row["axis"].setEnabled(source != "bead")
        row["pdb_id"].setVisible(source == "pdb")
        row["pdb_id"].setEnabled(source == "pdb")
        row["file_path"].setVisible(source == "file")
        row["browse"].setVisible(source == "file")
        row["residue_name"].setVisible(row["kind"] == "lipid" and source != "bead")
        if row in self.rows:
            self.table.setRowHeight(self.rows.index(row), 62 if row["kind"] == "lipid" and source != "bead" else 30)

    def _normalize_file_path(self, row):
        field = row["file_path"]
        if field.isModified() and field.text().strip():
            field.setText(str(Path(field.text().strip()).expanduser().resolve()))
            field.setModified(False)

    def _browse_lipid(self, row):
        path, _ = QFileDialog.getOpenFileName(self, "Lipid structure", "",
                      "Atomic structures (*.pdb *.ent *.cif *.mmcif *.mol2 *.sdf *.pdb.gz *.cif.gz *.mmcif.gz)")
        if path:
            row["file_path"].setText(str(Path(path).expanduser().resolve()))

    def remove_ingredient(self, row):
        if self.packer is None:
            index = self.rows.index(row)
            self.table.removeRow(index)
            self.rows.pop(index)

    def recipe(self):
        entries = []
        for row in self.rows:
            entry = dict(key=row["key"], kind=row["kind"], enabled=row["enabled"].isChecked(),
                     label=row["label"].text().strip(), amount=row["amount"].value(), radius=row["radius"].value(),
                     pdb_id=row["pdb_id"].text().strip(), axis=row["axis"].currentText(),
                     region=row["region"].currentText())
            if row["kind"] == "lipid" and row["source"].currentData() != "bead":
                self._normalize_file_path(row)
                entry.update(source=row["source"].currentData(), file_path=row["file_path"].text().strip(),
                             residue_name=row["residue_name"].text().strip().upper())
            entries.append(entry)
        return entries

    def _set_running(self, running):
        self._running = running
        if not running:
            self._refresh_targets()
        self._update_controls()

    def _update_controls(self):
        ready = not self._running and self.model is not None
        self.target.setEnabled(ready)
        self.run_button.setEnabled(ready)
        self.export_button.setEnabled(ready and bool(self.model._cb_membrane_state.get(PACKING_KEY)))
        self.cancel_button.setEnabled(self._running)
        for control in (self.automatic_count, self.seed, self.table, *self.add_buttons):
            control.setEnabled(ready)
        self.count.setEnabled(ready and not self.automatic_count.isChecked())

    def start(self):
        if self._running:
            return
        try:
            if self.model not in self.tool.session.models.list():
                raise ValueError("Choose an available target membrane first.")
            self._set_running(True)
            recipe = self.recipe()
            active = validate_recipe(recipe)
            for entry in active:
                if entry["kind"] != "protein" and not molecular_lipid(entry):
                    continue
                key = template_key(entry)
                if key not in self.templates:
                    self.status.setText(f"Preparing reusable molecular geometry for {entry['label']}...")
                    self.cancel_button.setEnabled(False)
                    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                    self.templates[key] = (load_lipid(self.tool.session, entry) if molecular_lipid(entry) else
                                           fetch_protein(self.tool.session, entry["pdb_id"], entry["axis"]))
            if self.model not in self.tool.session.models.list():
                raise ValueError("Target membrane was closed. Packing cancelled.")
            limit = None if self.automatic_count.isChecked() else self.count.value()
            self.packer = RecipePacker(self.model, recipe, self.templates, limit, self.seed.value())
            self.cancel_button.setEnabled(True)
            self.status.setText(f"Area-based target: {self.packer.area_target:,} particles. "
                               f"Packing target: {self.packer.count:,}. Random seeding and gap filling...")
            self.timer.start()
        except Exception as error:
            self._failed(error)

    def _advance(self):
        if self.packer is None:
            return
        try:
            if self.model not in self.tool.session.models.list():
                raise ValueError("Target membrane was closed. Packing cancelled.")
            deadline = time.perf_counter() + 0.006
            while not self.packer.done:
                self.packer.step()
                if time.perf_counter() >= deadline:
                    break
            message = f"Packing: {self.packer.placed:,}/{self.packer.count:,} particles..."
            if self.packer.limit_reached:
                message += f" Sparse preview: dense-fill target is {self.packer.area_target:,}."
            self.status.setText(message)
            if self.packer.done:
                self.timer.stop()
                result = self.packer.result()
                apply_result(self.tool, self.model, result)
                message = f"Packed {result['placed_count']}/{result['requested_count']} particles."
                message += (f" Protein coverage: {result['achieved_protein_percent']:.1f}% "
                            f"(requested {result['protein_percent']:.1f}%).")
                if result["particle_limit_reached"]:
                    message += (f" SPARSE PREVIEW: manual cap reduced the {result['area_target_count']:,}-particle "
                                "area target. Enable Automatic dense-fill budget to fill the membrane.")
                if result["protein_render_limit_reached"]:
                    message += " Molecular rendering safety limit reduced the molecule count."
                if result["placed_count"] < result["requested_count"]:
                    message += " Crowding/finite search prevented some requested placements; no overlaps were accepted."
                message += " " + "; ".join(f"{g['label']}: {len(g['positions'])}/{g['requested_count']}"
                                           for g in result["groups"])
                self.status.setText(message)
                self.tool.session.logger.info(message)
                self.packer = None
                self._set_running(False)
        except Exception as error:
            self._failed(error)

    def _failed(self, error):
        self.timer.stop()
        if self.packer is not None:
            self.packer.cancel()
        self.packer = None
        self._set_running(False)
        self.status.setText(str(error))
        self.tool.session.logger.error(f"Membrane packing: {error}")

    def cancel(self):
        self.timer.stop()
        if self.packer is not None:
            self.status.setText("Packing cancelled; existing scene unchanged.")
            self.packer.cancel()
        self.packer = None
        self._set_running(False)

    def done(self, result):
        self.cancel()
        self.refresh_timer.stop()
        super().done(result)

    def export(self):
        try:
            if self._running or self.model not in self.tool.session.models.list():
                return
            model = self.model
            result = model._cb_membrane_state.get(PACKING_KEY)
            if not result:
                raise ValueError("Pack this membrane before exporting.")
            parent = QFileDialog.getExistingDirectory(self, "Folder for membrane packing package")
            if not parent:
                return
            if model not in self.tool.session.models.list():
                raise ValueError("Target membrane was closed. Export cancelled.")
            folder = Path(tempfile.mkdtemp(prefix="membrane_cellpack_", dir=parent))
            paths = export_packing(self.tool, model, result, folder)
            message = f"Saved membrane-only APR/CPR, meshes and mmCIF to {paths['folder']}"
            self.status.setText(message)
            self.tool.session.logger.info(message)
        except Exception as error:
            self._failed(error)


def show_membrane_cellpack(tool):
    dialog = getattr(tool, "_membrane_cellpack_dialog", None)
    if dialog is not None and dialog.isVisible():
        dialog._refresh_targets(tool._membrane_distortion_target())
        dialog.raise_()
        dialog.activateWindow()
        return dialog
    model = tool._membrane_distortion_target()
    if model is None:
        tool.session.logger.warning("Build a membrane before packing its surface.")
        return None
    dialog = MembraneCellpackDialog(tool, model)
    tool._membrane_cellpack_dialog = dialog
    dialog.show()
    return dialog
