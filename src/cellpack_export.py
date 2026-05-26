# vim: set expandtab shiftwidth=4 softtabstop=4:

import json
import hashlib
import math
import os
import random
import re
import xml.etree.ElementTree as ET

from chimerax.core.commands import run as _run


def export_cellpack_package(tool, package_dir):
    exporter = _CellPackExporter(tool, package_dir)
    return exporter.export()


class _CellPackExporter:
    def __init__(self, tool, package_dir):
        self.tool = tool
        self.session = tool.session
        self.package_dir = os.path.abspath(os.path.expanduser(str(package_dir)))
        self.package_name = os.path.basename(self.package_dir.rstrip(os.sep)) or "cellpack_export"
        self.assets_dir = os.path.join(self.package_dir, "assets")
        self.outputs_dir = os.path.join(self.assets_dir, "outputs")
        self.sources_dir = os.path.join(self.assets_dir, "sources")
        self.cellpack_meshes_dir = os.path.join(self.package_dir, "meshes")
        self.cellpack_ingredients_dir = os.path.join(self.package_dir, "ingredients")
        self._name_counts = {}

    def export(self):
        os.makedirs(self.outputs_dir, exist_ok=True)
        os.makedirs(self.sources_dir, exist_ok=True)

        source_models = self._collect_source_models()
        output_models = self._collect_output_models()
        export_targets = output_models if output_models else source_models
        source_entries = [self._export_source_model(model) for model in source_models]
        source_by_ref = {}
        for entry in source_entries:
            ref = entry.get("model_ref")
            if ref:
                source_by_ref[ref] = entry

        output_entries = []
        for index, model in enumerate(export_targets, start=1):
            output_entries.append(self._export_output_model(model, index, source_by_ref))

        membrane_entries = self._collect_membrane_bundle_entries(output_entries)
        if not export_targets and not membrane_entries:
            raise RuntimeError(
                "No CiliaBuilder outputs, source models, or valid membrane settings found to export for cellPACK."
            )

        package_bounds = self._package_bounds(output_entries, membrane_entries)
        recipe = self._build_recipe(output_entries, package_bounds)
        membrane_bundle = self._build_cellpack_membrane_bundle(membrane_entries, package_bounds)
        if membrane_bundle is not None:
            recipe.setdefault("ciliabuilder", {})
            recipe["ciliabuilder"]["cellpack_membrane_bundle"] = {
                "recipe_path": self._relative_path(membrane_bundle["recipe_path"]),
                "result_path": self._relative_path(membrane_bundle["result_path"]),
                "n_membranes": int(membrane_bundle["n_membranes"]),
                "n_particles": int(membrane_bundle["n_particles"]),
            }
        manifest = self._build_manifest(
            source_entries,
            output_entries,
            recipe_path="recipe.json",
            cellpack_bundle=membrane_bundle,
        )

        recipe_path = os.path.join(self.package_dir, "recipe.json")
        manifest_path = os.path.join(self.package_dir, "ciliabuilder_manifest.json")
        with open(recipe_path, "w", encoding="utf-8") as f:
            json.dump(recipe, f, indent=2)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        result = {
            "package_dir": self.package_dir,
            "recipe_path": recipe_path,
            "manifest_path": manifest_path,
            "n_sources": len(source_entries),
            "n_outputs": len(output_entries),
        }
        if membrane_bundle is not None:
            result.update(
                {
                    "cellpack_recipe_path": membrane_bundle["recipe_path"],
                    "cellpack_result_path": membrane_bundle["result_path"],
                    "n_membranes": membrane_bundle["n_membranes"],
                    "n_membrane_particles": membrane_bundle["n_particles"],
                }
            )
        return result

    def _collect_source_models(self):
        seen = set()
        out = []
        for model in self.tool._all_session_models():
            try:
                if not self.tool._is_selector_attach_source(model):
                    continue
                key = id(model)
                if key in seen:
                    continue
                seen.add(key)
                out.append(model)
            except Exception:
                continue
        return out

    def _collect_output_models(self):
        seen = set()
        out = []

        stale_attach_keys = []
        for attach_key, root in list(self.tool._attached_results.items()):
            if root is None:
                continue
            if not self._is_live_session_model(root) or self._model_ref(root) is None:
                stale_attach_keys.append(attach_key)
                try:
                    self.session.logger.warning(
                        "Skipping stale attached result during cellPACK export: "
                        f"{self._model_name(root)}"
                    )
                except Exception:
                    pass
                continue
            key = id(root)
            if key in seen:
                continue
            seen.add(key)
            out.append(root)
        for attach_key in stale_attach_keys:
            try:
                self.tool._attached_results.pop(attach_key, None)
            except Exception:
                pass

        for model in self.tool._all_session_models():
            try:
                if not getattr(model, "_cb_generated_membrane", False):
                    continue
                key = id(model)
                if key in seen:
                    continue
                seen.add(key)
                out.append(model)
            except Exception:
                continue
        return out

    def _sanitize_stem(self, text):
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "model")).strip("._")
        return stem or "model"

    def _unique_filename(self, stem, ext):
        key = (stem, ext.lower())
        count = self._name_counts.get(key, 0)
        self._name_counts[key] = count + 1
        if count == 0:
            return f"{stem}{ext}"
        return f"{stem}_{count+1}{ext}"

    def _relative_path(self, abs_path):
        return os.path.relpath(abs_path, self.package_dir).replace(os.sep, "/")

    def _model_ref(self, model):
        return self.tool._model_ref(model)

    def _model_name(self, model, fallback="model"):
        return str(getattr(model, "name", "") or fallback)

    def _is_live_session_model(self, model):
        if model is None:
            return False
        for candidate in self.tool._all_session_models():
            if candidate is model:
                return True
        return False

    def _export_source_model(self, model):
        source_path = self.tool._model_source_path(model)
        fetch_spec = self.tool._fetch_spec_for_model(model)

        ext = self._preferred_source_ext(model, source_path)
        stem = self._sanitize_stem(self._model_name(model))
        filename = self._unique_filename(stem, ext)
        out_path = os.path.join(self.sources_dir, filename)
        self._materialize_model_asset(model, out_path, ext, prefer_copy=bool(source_path))

        return {
            "model_ref": self._model_ref(model),
            "name": self._model_name(model),
            "relative_path": self._relative_path(out_path),
            "absolute_path": out_path,
            "format": ext.lstrip("."),
            "source_path": source_path,
            "fetch_type": fetch_spec.get("fetch_type") if fetch_spec else None,
            "fetch_id": fetch_spec.get("fetch_id") if fetch_spec else None,
            "model_kind": self._model_kind(model),
        }

    def _export_output_model(self, model, index, source_by_ref):
        stem = self._sanitize_stem(self._model_name(model, fallback=f"output_{index:03d}"))
        ext = self._preferred_output_ext(model)
        filename = self._unique_filename(stem, ext)
        out_path = os.path.join(self.outputs_dir, filename)
        self._materialize_model_asset(model, out_path, ext, prefer_copy=False)

        bounds = self._model_world_bounds(model)
        radius = self._bounds_radius(bounds)
        source_ref = getattr(model, "_cb_attachment_source_ref", None)
        star_ref = getattr(model, "_cb_attachment_star_ref", None) or getattr(model, "_cb_attached_star_ref", None)
        source_entry = source_by_ref.get(source_ref)

        return {
            "object_id": f"cb_output_{index:03d}",
            "name": self._model_name(model, fallback=f"Output {index}"),
            "model_ref": self._model_ref(model),
            "relative_path": self._relative_path(out_path),
            "absolute_path": out_path,
            "format": ext.lstrip("."),
            "bounds": bounds,
            "radius": radius,
            "instance_count": self._instance_count(model),
            "output_kind": self._output_kind(model),
            "source_ref": source_ref,
            "source_name": getattr(model, "_cb_attachment_map_name", None),
            "source_asset": source_entry["relative_path"] if source_entry is not None else None,
            "star_ref": star_ref,
            "star_name": getattr(model, "_cb_attachment_star_name", None),
            "membrane_state": getattr(model, "_cb_membrane_state", None),
        }

    def _preferred_source_ext(self, model, source_path):
        low_path = str(source_path or "").lower()
        if self.tool._is_atomic_like(model):
            return ".cif"
        if self.tool._is_volume_like(model) or self.tool._is_surface_like(model) or self.tool._is_glb_like(model):
            return ".stl"
        ext = os.path.splitext(low_path)[1].lower()
        return ext or ".dat"

    def _preferred_output_ext(self, model):
        return ".stl"

    def _tree_has_mesh_like(self, model):
        for node in self.tool._iter_model_tree(model):
            try:
                if self.tool._is_volume_like(node) or self.tool._is_surface_like(node) or self.tool._is_glb_like(node):
                    return True
            except Exception:
                pass
        return False

    def _materialize_model_asset(self, model, out_path, ext, prefer_copy):
        source_path = self.tool._model_source_path(model)
        ext = str(ext).lower()

        if prefer_copy and source_path and os.path.exists(source_path):
            # Preserve the original file when that format is already useful for the package.
            src_ext = os.path.splitext(str(source_path))[1].lower()
            if src_ext == ext and ext in (".cif", ".pdb", ".mmcif"):
                import shutil
                shutil.copy2(source_path, out_path)
                return

        if ext == ".stl":
            self._save_model_as_stl(model, out_path)
            return
        if ext == ".cif":
            self._save_model_as_cif(model, out_path)
            return

        if source_path and os.path.exists(source_path):
            import shutil
            shutil.copy2(source_path, out_path)
            return

        raise RuntimeError(f"Cannot export {self._model_name(model)} to {ext}")

    def _save_model_as_stl(self, model, out_path):
        ref = self._model_ref(model)
        if ref is None:
            raise RuntimeError(f"Model {self._model_name(model)} has no ChimeraX id")
        try:
            _run(self.session, f'save "{out_path}" #{ref}', log=False)
            return
        except Exception:
            pass

        if self.tool._is_atomic_like(model):
            created = self.tool._command_created_models(f"surface #{ref}")
            try:
                surface_model = self.tool._pick_opened_model(created, self.tool._is_surface_like)
                if surface_model is None:
                    raise RuntimeError(f"Could not create a surface for {self._model_name(model)}")
                surface_ref = self._model_ref(surface_model)
                _run(self.session, f'save "{out_path}" #{surface_ref}', log=False)
                return
            finally:
                for created_model in created:
                    try:
                        self.session.models.close([created_model])
                    except Exception:
                        pass

        raise RuntimeError(f"Could not export {self._model_name(model)} as STL")

    def _save_model_as_cif(self, model, out_path):
        ref = self._model_ref(model)
        if ref is None:
            raise RuntimeError(f"Model {self._model_name(model)} has no ChimeraX id")
        _run(self.session, f'save "{out_path}" #{ref}', log=False)

    def _model_world_bounds(self, model):
        try:
            bounds = model.bounds()
        except Exception:
            bounds = None
        if bounds is None:
            return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}
        try:
            mn = [float(v) for v in bounds.xyz_min]
            mx = [float(v) for v in bounds.xyz_max]
            return {"min": mn, "max": mx}
        except Exception:
            try:
                c = bounds.center()
                center = [float(c[0]), float(c[1]), float(c[2])]
                return {"min": center[:], "max": center[:]}
            except Exception:
                return {"min": [0.0, 0.0, 0.0], "max": [0.0, 0.0, 0.0]}

    def _bounds_radius(self, bounds):
        mn = bounds["min"]
        mx = bounds["max"]
        dx = float(mx[0] - mn[0])
        dy = float(mx[1] - mn[1])
        dz = float(mx[2] - mn[2])
        return max(1.0, 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz))

    def _instance_count(self, model):
        try:
            positions = getattr(model, "positions", None)
            if positions is not None:
                return max(1, len(positions))
        except Exception:
            pass
        count = 0
        for child in self.tool._iter_model_tree(model):
            try:
                positions = getattr(child, "positions", None)
                if positions is not None:
                    count += max(1, len(positions))
            except Exception:
                pass
        return max(1, count)

    def _model_kind(self, model):
        if self.tool._is_atomic_like(model):
            return "atomic"
        if self.tool._is_volume_like(model):
            return "volume"
        if self.tool._is_glb_like(model):
            return "glb"
        if self.tool._is_surface_like(model):
            return "surface"
        return "model"

    def _output_kind(self, model):
        if getattr(model, "_cb_generated_membrane", False):
            return "membrane"
        if getattr(model, "_cb_generated_attached", False):
            return "attached"
        return "output"

    def _package_bounds(self, output_entries, membrane_entries=None):
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        have_bounds = False
        for entry in output_entries:
            bounds = entry["bounds"]
            for i in range(3):
                mins[i] = min(mins[i], float(bounds["min"][i]))
                maxs[i] = max(maxs[i], float(bounds["max"][i]))
                have_bounds = True
        for entry in membrane_entries or []:
            bounds = self._membrane_bounds(entry.get("membrane_state", None))
            if bounds is None:
                continue
            for i in range(3):
                mins[i] = min(mins[i], float(bounds["min"][i]))
                maxs[i] = max(maxs[i], float(bounds["max"][i]))
                have_bounds = True
        if not have_bounds:
            return [[0.0, 0.0, 0.0], [1000.0, 1000.0, 1000.0]]
        return [mins, maxs]

    def _build_recipe(self, output_entries, package_bounds):
        objects = {}
        composition = []
        for entry in output_entries:
            obj_id = entry["object_id"]
            objects[obj_id] = {
                "name": entry["name"],
                "radius": float(entry["radius"]),
                "jitter_attempts": 20,
                "max_jitter": [1.0, 1.0, 1.0],
                "place_method": "jitter",
                "representations": {
                    "mesh": {
                        "path": entry["relative_path"],
                        "name": os.path.basename(entry["relative_path"]),
                        "format": entry["format"],
                        "coordinate_system": "right",
                    }
                },
                "ciliabuilder": {
                    "output_kind": entry["output_kind"],
                    "instance_count": int(entry["instance_count"]),
                    "source_name": entry.get("source_name", None),
                    "source_asset": entry.get("source_asset", None),
                    "star_name": entry.get("star_name", None),
                },
            }
            composition.append(
                {
                    "id": f"{obj_id}_placement",
                    "object": obj_id,
                    "count": 1,
                    "priority": 0,
                }
            )

        return {
            "format_version": "2.0",
            "name": self.package_name,
            "version": "1.0",
            "bounding_box": package_bounds,
            "objects": objects,
            "composition": composition,
            "ciliabuilder": {
                "manifest": "ciliabuilder_manifest.json",
                "notes": "Portable export package from CiliaBuilder2. Objects reference relative asset paths.",
            },
        }

    def _build_manifest(self, source_entries, output_entries, recipe_path, cellpack_bundle=None):
        manifest = {
            "format": "ciliabuilder_cellpack_package",
            "version": 1,
            "package_name": self.package_name,
            "recipe": recipe_path,
            "sources": source_entries,
            "outputs": [
                {
                    "object_id": entry["object_id"],
                    "name": entry["name"],
                    "relative_path": entry["relative_path"],
                    "format": entry["format"],
                    "output_kind": entry["output_kind"],
                    "instance_count": entry["instance_count"],
                    "source_ref": entry["source_ref"],
                    "source_name": entry["source_name"],
                    "source_asset": entry["source_asset"],
                    "star_ref": entry["star_ref"],
                    "star_name": entry["star_name"],
                    "membrane_state": entry["membrane_state"],
                }
                for entry in output_entries
            ],
        }
        if cellpack_bundle is not None:
            manifest["cellpack_membrane_bundle"] = {
                "recipe_path": self._relative_path(cellpack_bundle["recipe_path"]),
                "result_path": self._relative_path(cellpack_bundle["result_path"]),
                "n_membranes": int(cellpack_bundle["n_membranes"]),
                "n_particles": int(cellpack_bundle["n_particles"]),
            }
        return manifest

    def _collect_membrane_bundle_entries(self, output_entries):
        membrane_entries = []
        for entry in output_entries:
            if entry.get("output_kind") != "membrane":
                continue
            state = self._resolved_membrane_state_for_cellpack(
                entry.get("membrane_state", None),
                output_entries,
            )
            params = self._membrane_particle_params(state)
            if params is None:
                continue
            membrane_entries.append(
                {
                    "name": entry.get("name", None),
                    "membrane_state": state,
                    "params": params,
                    "autobuilt": False,
                }
            )
        if membrane_entries:
            return membrane_entries

        state = self._resolved_membrane_state_for_cellpack(
            self._autobuild_membrane_state(),
            output_entries,
        )
        params = self._membrane_particle_params(state)
        if params is None:
            return []
        return [
            {
                "name": self._autobuild_membrane_name(),
                "membrane_state": state,
                "params": params,
                "autobuilt": True,
            }
        ]

    def _autobuild_membrane_name(self):
        counter = int(getattr(self.tool, "_membrane_counter", 0) or 0)
        return f"Membrane {counter + 1}"

    def _autobuild_membrane_state(self):
        try:
            length = float(self.tool.membrane_length.value())
            radius = float(self.tool.membrane_radius.value())
            thickness = float(self.tool.membrane_thickness.value())
            offset = float(self.tool.membrane_offset.value())
            distortion_level = float(self.tool.membrane_distortion.value())
        except Exception:
            return None

        if length <= 0.0 or radius <= 0.0 or thickness <= 0.0 or thickness >= radius:
            return None

        try:
            anchor = self.tool._membrane_anchor_info()
        except Exception:
            anchor = {
                "star_model": None,
                "center": [0.0, 0.0, 0.0],
                "axis": [0.0, 0.0, 1.0],
                "start_scalar": 0.0,
            }

        axis = self._safe_unit_vector(anchor.get("axis", (0.0, 0.0, 1.0)))
        center = self._safe_xyz(anchor.get("center", (0.0, 0.0, 0.0)))
        center_scalar = self._dot(center, axis)
        start_scalar = float(anchor.get("start_scalar", 0.0) or 0.0) + offset
        start_center = [
            center[i] + (axis[i] * (start_scalar - center_scalar))
            for i in range(3)
        ]
        membrane_center = [
            start_center[i] + (0.5 * length * axis[i])
            for i in range(3)
        ]

        state = {
            "center": [float(v) for v in membrane_center],
            "axis": [float(v) for v in axis],
            "length": float(length),
            "diameter": float(2.0 * radius),
            "thickness": float(thickness),
            "distortion_level": float(distortion_level),
            "radius": float(radius),
            "offset": float(offset),
            "autobuilt_for_cellpack": True,
        }
        star_model = anchor.get("star_model", None)
        star_name = str(getattr(star_model, "name", "") or "").strip()
        if star_name:
            state["source_star_name"] = star_name
        return state

    def _resolved_membrane_state_for_cellpack(self, state, output_entries):
        if not isinstance(state, dict):
            return None

        resolved = dict(state)
        try:
            thickness = float(resolved.get("thickness", 0.0))
            outer_radius = resolved.get("radius", None)
            if outer_radius is None:
                outer_radius = 0.5 * float(resolved.get("diameter", 0.0))
            outer_radius = float(outer_radius)
        except Exception:
            return resolved

        if thickness <= 0.0 or outer_radius <= 0.0:
            return resolved

        required_outer_radius, detail = self._required_membrane_outer_radius(resolved, output_entries)
        resolved["radius"] = float(outer_radius)
        resolved["diameter"] = float(2.0 * outer_radius)
        if required_outer_radius is None or required_outer_radius <= outer_radius:
            return resolved

        resolved["cellpack_requested_radius"] = float(outer_radius)
        resolved["cellpack_radius_adjusted"] = True
        resolved["cellpack_radius_clearance"] = float(required_outer_radius - outer_radius)
        if detail is not None:
            resolved["cellpack_attachment_outer_extent"] = float(detail["outer_extent"])
            resolved["cellpack_gap"] = float(detail["gap"])
            resolved["cellpack_reference_particle_radius"] = float(detail["particle_radius"])
        resolved["radius"] = float(required_outer_radius)
        resolved["diameter"] = float(2.0 * required_outer_radius)
        return resolved

    def _required_membrane_outer_radius(self, state, output_entries):
        if not isinstance(state, dict):
            return None, None

        try:
            center = self._safe_xyz(state.get("center", (0.0, 0.0, 0.0)))
            axis = self._safe_unit_vector(state.get("axis", (0.0, 0.0, 1.0)))
            thickness = float(state.get("thickness", 0.0))
        except Exception:
            return None, None
        if thickness <= 0.0:
            return None, None

        candidates = [
            entry for entry in (output_entries or [])
            if str(entry.get("output_kind", "") or "").lower() == "attached"
        ]
        if not candidates:
            return None, None

        source_star_name = str(state.get("source_star_name", "") or "").strip()
        if source_star_name:
            matching = [
                entry for entry in candidates
                if str(entry.get("star_name", "") or "").strip() == source_star_name
            ]
            if matching:
                candidates = matching

        outer_extent = None
        for entry in candidates:
            extent = self._bounds_radial_extent(entry.get("bounds", None), center, axis)
            if extent is None:
                continue
            if outer_extent is None or extent > outer_extent:
                outer_extent = extent
        if outer_extent is None:
            return None, None

        base_particle_radius = self._membrane_particle_base_radius(thickness)
        particle_classes = self._membrane_particle_class_defs(base_particle_radius)
        max_particle_radius = max(float(cls["particle_radius"]) for cls in particle_classes)
        gap = max(20.0, 0.25 * thickness)
        required_mid_radius = float(outer_extent) + float(max_particle_radius) + float(gap)
        required_outer_radius = required_mid_radius + (0.5 * thickness)
        detail = {
            "outer_extent": float(outer_extent),
            "gap": float(gap),
            "particle_radius": float(max_particle_radius),
        }
        return float(required_outer_radius), detail

    def _membrane_bounds(self, state):
        if not isinstance(state, dict):
            return None
        try:
            center = self._safe_xyz(state.get("center", (0.0, 0.0, 0.0)))
            axis = self._safe_unit_vector(state.get("axis", (0.0, 0.0, 1.0)))
            length = float(state.get("length", 0.0))
            radius = state.get("radius", None)
            if radius is None:
                radius = 0.5 * float(state.get("diameter", 0.0))
            radius = float(radius)
        except Exception:
            return None

        if length <= 0.0 or radius <= 0.0:
            return None

        half_length = 0.5 * length
        extents = []
        for axis_value in axis:
            tangent_scale = math.sqrt(max(0.0, 1.0 - (float(axis_value) * float(axis_value))))
            extents.append((radius * tangent_scale) + (half_length * abs(float(axis_value))))
        return {
            "min": [float(center[i]) - float(extents[i]) for i in range(3)],
            "max": [float(center[i]) + float(extents[i]) for i in range(3)],
        }

    def _bounds_radial_extent(self, bounds, center, axis):
        if not isinstance(bounds, dict):
            return None
        try:
            mn = self._safe_xyz(bounds.get("min", (0.0, 0.0, 0.0)))
            mx = self._safe_xyz(bounds.get("max", (0.0, 0.0, 0.0)))
        except Exception:
            return None

        outer_extent = 0.0
        for x in (mn[0], mx[0]):
            for y in (mn[1], mx[1]):
                for z in (mn[2], mx[2]):
                    vec = [
                        float(x) - float(center[0]),
                        float(y) - float(center[1]),
                        float(z) - float(center[2]),
                    ]
                    axial = self._dot(vec, axis)
                    radial = [
                        vec[0] - (axial * float(axis[0])),
                        vec[1] - (axial * float(axis[1])),
                        vec[2] - (axial * float(axis[2])),
                    ]
                    extent = math.sqrt(self._dot(radial, radial))
                    if extent > outer_extent:
                        outer_extent = extent
        return float(outer_extent)

    def _build_cellpack_membrane_bundle(self, membrane_entries, package_bounds):
        if not membrane_entries:
            return None

        os.makedirs(self.cellpack_meshes_dir, exist_ok=True)
        os.makedirs(self.cellpack_ingredients_dir, exist_ok=True)

        recipe_filename = f"{self.package_name}.cpr.json"
        result_filename = f"{self.package_name}.apr.json"
        recipe = {
            "recipe": {
                "name": self.package_name,
                "version": "1.0",
            },
            "options": {
                "placeMethod": "pandaBullet",
                "overwritePlaceMethod": True,
                "saveResult": False,
                "runTimeDisplay": False,
                "boundingBox": package_bounds,
                "resultfile": result_filename,
                "use_periodicity": False,
                "EnviroOnly": False,
            },
            "compartments": {},
        }
        results = {
            "recipe": {
                "setupfile": recipe_filename,
                "name": self.package_name,
                "version": "1.0",
            },
            "compartments": {},
        }

        total_particles = 0
        for comp_num, membrane_entry in enumerate(membrane_entries, start=1):
            params = membrane_entry["params"]
            comp_stem = self._sanitize_stem(membrane_entry.get("name", f"membrane_{comp_num:03d}"))
            comp_name = f"{comp_stem}_surface_{comp_num:03d}"

            surface_mesh_filename = self._unique_filename(f"{comp_name}_geom", ".dae")
            surface_mesh_path = os.path.join(self.cellpack_meshes_dir, surface_mesh_filename)

            surface_vertices, surface_triangles = self._build_open_cylinder_mesh(
                params["center"],
                params["axis"],
                params["mid_radius"],
                params["length"],
                params["n_theta"],
                params["mesh_ring_count"],
            )
            self._write_collada_mesh(
                surface_vertices,
                surface_triangles,
                surface_mesh_path,
                comp_name,
                rgba=(140, 156, 176, 220),
            )

            placements_by_class = self._build_membrane_particle_results_by_class(params)

            recipe["compartments"][comp_name] = {
                "geom": self._relative_path(surface_mesh_path),
                "name": comp_name,
                "rep_file": self._relative_path(surface_mesh_path),
                "surface": {"ingredients": {}},
            }
            results["compartments"][comp_name] = {
                "surface": {"ingredients": {}}
            }

            for class_info in params.get("particle_classes", []) or []:
                class_suffix = str(class_info["suffix"])
                class_stem = f"{comp_name}_{class_suffix}"
                particle_mesh_filename = self._unique_filename(class_stem, ".dae")
                particle_mesh_path = os.path.join(self.cellpack_meshes_dir, particle_mesh_filename)
                ingredient_filename = self._unique_filename(class_stem, ".json")
                ingredient_path = os.path.join(self.cellpack_ingredients_dir, ingredient_filename)
                ingredient_name = os.path.splitext(ingredient_filename)[0]
                placements = placements_by_class.get(class_suffix, [])
                if not placements:
                    continue

                sphere_vertices, sphere_triangles = self._build_uv_sphere_mesh(class_info["particle_radius"])
                self._write_collada_mesh(
                    sphere_vertices,
                    sphere_triangles,
                    particle_mesh_path,
                    ingredient_name,
                    rgba=class_info["color"],
                )

                ingredient = self._build_membrane_particle_ingredient(
                    ingredient_name=ingredient_name,
                    particle_mesh_path=particle_mesh_path,
                    particle_radius=class_info["particle_radius"],
                    particle_count=len(placements),
                    particle_class=class_info,
                )
                with open(ingredient_path, "w", encoding="utf-8") as f:
                    json.dump(ingredient, f, indent=2)

                recipe["compartments"][comp_name]["surface"]["ingredients"][ingredient_name] = {
                    "name": ingredient_name,
                    "include": self._relative_path(ingredient_path),
                }
                results["compartments"][comp_name]["surface"]["ingredients"][ingredient_name] = {
                    "compNum": int(comp_num),
                    "results": placements,
                    "name": ingredient_name,
                    "encapsulatingRadius": float(class_info["particle_radius"]),
                }
                total_particles += len(placements)

        recipe_path = os.path.join(self.package_dir, recipe_filename)
        result_path = os.path.join(self.package_dir, result_filename)
        with open(recipe_path, "w", encoding="utf-8") as f:
            json.dump(recipe, f, indent=2)
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        return {
            "recipe_path": recipe_path,
            "result_path": result_path,
            "n_membranes": len(membrane_entries),
            "n_particles": total_particles,
        }

    def _safe_xyz(self, values):
        try:
            xyz = [float(v) for v in values]
        except Exception:
            xyz = [0.0, 0.0, 0.0]
        while len(xyz) < 3:
            xyz.append(0.0)
        return xyz[:3]

    def _dot(self, a, b):
        return (
            (float(a[0]) * float(b[0]))
            + (float(a[1]) * float(b[1]))
            + (float(a[2]) * float(b[2]))
        )

    def _membrane_particle_params(self, state):
        if not isinstance(state, dict):
            return None
        try:
            center = [float(v) for v in state.get("center", (0.0, 0.0, 0.0))]
            axis = self._safe_unit_vector(state.get("axis", (0.0, 0.0, 1.0)))
            length = float(state.get("length", 0.0))
            thickness = float(state.get("thickness", 0.0))
            outer_radius = state.get("radius", None)
            if outer_radius is None:
                outer_radius = 0.5 * float(state.get("diameter", 0.0))
            outer_radius = float(outer_radius)
        except Exception:
            return None
        if length <= 0.0 or thickness <= 0.0 or outer_radius <= 0.0:
            return None

        thickness = min(thickness, outer_radius)
        mid_radius = max(1.0, outer_radius - (0.5 * thickness))
        target_spacing = max(80.0, thickness)
        particle_radius = self._membrane_particle_base_radius(thickness)
        particle_classes = self._membrane_particle_class_defs(particle_radius)
        circumference = 2.0 * math.pi * mid_radius
        n_theta = max(12, int(math.ceil(circumference / max(target_spacing, 1.0))))
        n_z = max(2, int(math.ceil(length / max(target_spacing, 1.0))))
        packing_seed = self._membrane_particle_seed(state, particle_classes)
        return {
            "center": center,
            "axis": axis,
            "length": length,
            "thickness": thickness,
            "outer_radius": outer_radius,
            "mid_radius": mid_radius,
            "particle_radius": particle_radius,
            "particle_classes": particle_classes,
            "n_theta": n_theta,
            "n_z": n_z,
            "mesh_ring_count": max(2, n_z + 1),
            "particle_count": int(n_theta * n_z),
            "packing_seed": int(packing_seed),
        }

    def _membrane_particle_base_radius(self, thickness):
        target_spacing = max(80.0, float(thickness))
        return max(1.0, min(0.30 * float(thickness), 0.30 * target_spacing))

    def _membrane_particle_percentages(self):
        defaults = {
            "receptors": 8.0,
            "channels": 7.0,
            "signaling": 7.0,
            "scaffold": 8.0,
            "lipids": 70.0,
        }
        values = {}
        for suffix, default_value in defaults.items():
            value = default_value
            widget = getattr(self.tool, f"membrane_particle_{suffix}_pct", None)
            if widget is not None:
                try:
                    value = float(widget.value())
                except Exception:
                    value = default_value
            values[suffix] = max(0.0, float(value))
        total = sum(values.values())
        if total <= 0.0:
            values = dict(defaults)
            total = sum(values.values())
        return {
            suffix: (float(values[suffix]) / float(total))
            for suffix in defaults.keys()
        }

    def _membrane_particle_class_defs(self, base_radius):
        percentages = self._membrane_particle_percentages()
        return [
            {
                "suffix": "receptors",
                "label": "receptors",
                "role": "signaling_receptors",
                "color": (86, 143, 214, 255),
                "particle_radius": float(base_radius) * 1.10,
                "target_percentage": float(percentages["receptors"]) * 100.0,
                "abundance_weight": float(percentages["receptors"]),
            },
            {
                "suffix": "channels",
                "label": "channels",
                "role": "ion_channels_and_transporters",
                "color": (84, 190, 168, 255),
                "particle_radius": float(base_radius) * 0.98,
                "target_percentage": float(percentages["channels"]) * 100.0,
                "abundance_weight": float(percentages["channels"]),
            },
            {
                "suffix": "signaling",
                "label": "signaling",
                "role": "signaling_complexes",
                "color": (240, 151, 88, 255),
                "particle_radius": float(base_radius) * 0.92,
                "target_percentage": float(percentages["signaling"]) * 100.0,
                "abundance_weight": float(percentages["signaling"]),
            },
            {
                "suffix": "scaffold",
                "label": "scaffold",
                "role": "scaffold_and_adhesion",
                "color": (201, 118, 164, 255),
                "particle_radius": float(base_radius) * 0.88,
                "target_percentage": float(percentages["scaffold"]) * 100.0,
                "abundance_weight": float(percentages["scaffold"]),
            },
            {
                "suffix": "lipids",
                "label": "lipids",
                "role": "lipid_bilayer",
                "color": (214, 196, 128, 255),
                "particle_radius": float(base_radius) * 0.42,
                "target_percentage": float(percentages["lipids"]) * 100.0,
                "abundance_weight": float(percentages["lipids"]),
            },
        ]

    def _membrane_particle_seed(self, state, class_defs):
        payload = {
            "center": [round(float(v), 3) for v in state.get("center", (0.0, 0.0, 0.0))],
            "axis": [round(float(v), 6) for v in state.get("axis", (0.0, 0.0, 1.0))],
            "length": round(float(state.get("length", 0.0)), 3),
            "radius": round(float(state.get("radius", 0.0)), 3),
            "thickness": round(float(state.get("thickness", 0.0)), 3),
            "classes": [
                {
                    "suffix": str(class_info.get("suffix", "")),
                    "radius": round(float(class_info.get("particle_radius", 0.0)), 3),
                    "weight": round(float(class_info.get("abundance_weight", 0.0)), 6),
                }
                for class_info in class_defs or []
            ],
        }
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _build_membrane_particle_ingredient(
        self,
        ingredient_name,
        particle_mesh_path,
        particle_radius,
        particle_count,
        particle_class,
    ):
        radius = float(particle_radius)
        return {
            "nbJitter": 6,
            "molarity": 0,
            "useOrientBias": False,
            "rotRange": 6.283185307179586,
            "gradient": "",
            "meshFile": self._relative_path(particle_mesh_path),
            "meshName": ingredient_name,
            "coordsystem": "right",
            "orientBiasRotRangeMin": -3.141592653589793,
            "cutoff_boundary": 0,
            "jitterMax": [1.0, 1.0, 1.0],
            "perturbAxisAmplitude": 0.0,
            "encapsulatingRadius": radius,
            "partners_position": [],
            "isAttractor": False,
            "principalVector": [0.0, 0.0, 1.0],
            "properties": {
                "ciliabuilder_role": "membrane_particle",
                "ciliabuilder_particle_class": str(particle_class.get("role", "") or ""),
                "ciliabuilder_target_percentage": float(particle_class.get("target_percentage", 0.0)),
            },
            "name": ingredient_name,
            "partners_name": [],
            "nbMol": int(particle_count),
            "weight": 1.0,
            "orientBiasRotRangeMax": 3.141592653589793,
            "packingMode": "random",
            "Type": "MultiSphere",
            "excluded_partners_name": [],
            "rejectionThreshold": float(2.0 * radius),
            "placeType": "pandaBullet",
            "cutoff_surface": radius,
            "packingPriority": 0.0,
            "proba_binding": 0.5,
            "proba_not_binding": 0.5,
            "use_mesh_rb": False,
            "source": {
                "transform": {
                    "center": True,
                }
            },
            "positions": [
                {
                    "coords": [0.0, 0.0, 0.0],
                }
            ],
            "radii": [
                {
                    "radii": [radius],
                }
            ],
        }

    def _build_membrane_particle_results(self, params):
        placements_by_class = self._build_membrane_particle_results_by_class(params)
        placements = []
        for class_info in params.get("particle_classes", []) or []:
            placements.extend(placements_by_class.get(str(class_info["suffix"]), []))
        return placements

    def _build_membrane_particle_results_by_class(self, params):
        center = params["center"]
        basis = self._axis_basis(params["axis"])
        length = float(params["length"])
        radius = float(params["mid_radius"])
        class_defs = params.get("particle_classes", []) or []
        if not class_defs:
            return {}

        sorted_classes = sorted(
            class_defs,
            key=lambda cls: float(cls.get("particle_radius", 0.0)),
            reverse=True,
        )
        min_radius = min(float(cls["particle_radius"]) for cls in sorted_classes)
        max_radius = max(float(cls["particle_radius"]) for cls in sorted_classes)
        circumference = 2.0 * math.pi * radius
        total_weight = sum(max(0.0, float(cls.get("abundance_weight", 0.0))) for cls in sorted_classes)
        if total_weight <= 0.0:
            total_weight = float(len(sorted_classes))
        collision_padding = max(0.5, 0.01 * min_radius)
        placements = {str(class_info["suffix"]): [] for class_info in sorted_classes}
        class_by_suffix = {str(class_info["suffix"]): class_info for class_info in sorted_classes}
        placed_counts = {str(class_info["suffix"]): 0 for class_info in sorted_classes}
        rng = random.Random(int(params.get("packing_seed", 0)))
        candidate_step = max(8.0, 1.0 * min_radius)
        row_step = candidate_step * (math.sqrt(3.0) * 0.5)
        candidate_jitter_u = 0.18 * candidate_step
        candidate_jitter_z = 0.18 * row_step
        candidate_bin_size = max(1.0, max_radius + collision_padding)
        n_u_bins = max(1, int(math.ceil(circumference / candidate_bin_size)))
        n_z_bins = max(1, int(math.ceil(length / candidate_bin_size)))
        half_length = 0.5 * length

        def candidate_bin_index(u_coord, z_coord):
            iu = int(math.floor(u_coord / candidate_bin_size)) % n_u_bins
            z_shift = z_coord + half_length
            iz = int(math.floor(z_shift / candidate_bin_size))
            if iz < 0:
                iz = 0
            elif iz >= n_z_bins:
                iz = n_z_bins - 1
            return iu, iz

        candidate_u = []
        candidate_z = []
        candidate_world = []
        candidate_normal = []
        candidate_capacity = []
        candidate_bucket = []
        available_pos = []
        available_indices = []
        candidate_bins = {}
        capacity_buckets = {}
        bucket_width = 1.0
        placed_particles = []
        placed_bins = {}

        n_rows = max(2, int(math.ceil(length / row_step)) + 2)
        n_cols = max(12, int(math.ceil(circumference / candidate_step)))
        phase_specs = [
            (rng.random() * candidate_step, rng.random() * row_step),
            (
                (rng.random() * candidate_step) + (0.33 * candidate_step),
                (rng.random() * row_step) + (0.5 * row_step),
            ),
        ]
        for u_phase, z_phase in phase_specs:
            for row_index in range(n_rows):
                base_z = (-half_length) + z_phase + (float(row_index) * row_step)
                if base_z < (-half_length) or base_z > half_length:
                    continue
                row_shift = 0.5 * candidate_step if (row_index % 2) else 0.0
                for col_index in range(n_cols):
                    u_coord = (u_phase + row_shift + (float(col_index) * candidate_step)) % circumference
                    if candidate_jitter_u > 0.0:
                        u_coord = (u_coord + rng.uniform(-candidate_jitter_u, candidate_jitter_u)) % circumference
                    z_coord = base_z
                    if candidate_jitter_z > 0.0:
                        z_coord += rng.uniform(-candidate_jitter_z, candidate_jitter_z)
                    if z_coord < (-half_length):
                        z_coord = -half_length
                    elif z_coord > half_length:
                        z_coord = half_length
                    theta = (u_coord / circumference) * (2.0 * math.pi)
                    radial = (math.cos(theta), math.sin(theta), 0.0)
                    local = (radius * radial[0], radius * radial[1], z_coord)
                    world = self._apply_basis(center, basis, local)
                    normal = self._apply_basis((0.0, 0.0, 0.0), basis, radial)
                    index = len(candidate_u)
                    candidate_u.append(float(u_coord))
                    candidate_z.append(float(z_coord))
                    candidate_world.append(
                        [float(world[0]), float(world[1]), float(world[2])]
                    )
                    candidate_normal.append(
                        [float(normal[0]), float(normal[1]), float(normal[2])]
                    )
                    candidate_capacity.append(float(half_length - abs(float(z_coord))))
                    candidate_bucket.append(None)
                    available_pos.append(index)
                    available_indices.append(index)
                    key = candidate_bin_index(u_coord, z_coord)
                    candidate_bins.setdefault(key, []).append(index)

        def bucket_id_for_capacity(capacity):
            return int(math.floor(max(0.0, float(capacity)) / bucket_width))

        def add_to_capacity_bucket(candidate_index):
            bucket_id = bucket_id_for_capacity(candidate_capacity[candidate_index])
            candidate_bucket[candidate_index] = bucket_id
            capacity_buckets.setdefault(bucket_id, set()).add(candidate_index)

        def remove_from_capacity_bucket(candidate_index):
            bucket_id = candidate_bucket[candidate_index]
            if bucket_id is None:
                return
            bucket = capacity_buckets.get(bucket_id, None)
            if bucket is not None:
                bucket.discard(candidate_index)
                if not bucket:
                    capacity_buckets.pop(bucket_id, None)
            candidate_bucket[candidate_index] = None

        def remove_candidate(candidate_index):
            pos = int(available_pos[candidate_index])
            if pos < 0:
                return
            remove_from_capacity_bucket(candidate_index)
            last_index = available_indices[-1]
            available_indices[pos] = last_index
            available_pos[last_index] = pos
            available_indices.pop()
            available_pos[candidate_index] = -1

        for candidate_index, capacity in enumerate(candidate_capacity):
            if capacity < (min_radius - 1e-6):
                remove_candidate(candidate_index)
            elif available_pos[candidate_index] >= 0:
                add_to_capacity_bucket(candidate_index)

        def periodic_delta(u_a, u_b):
            diff = abs(float(u_a) - float(u_b))
            if diff > (0.5 * circumference):
                diff = circumference - diff
            return diff

        def update_candidate_capacities(placed_u, placed_z, placed_world, placed_radius):
            influence = float(placed_radius) + max_radius + collision_padding
            search_span = max(1, int(math.ceil(influence / candidate_bin_size)))
            iu, iz = candidate_bin_index(placed_u, placed_z)
            search_limit = influence + candidate_step
            search_limit_sq = search_limit * search_limit
            for du_bin in range(-search_span, search_span + 1):
                cu = (iu + du_bin) % n_u_bins
                for dz_bin in range(-search_span, search_span + 1):
                    cz = iz + dz_bin
                    if cz < 0 or cz >= n_z_bins:
                        continue
                    key = (cu, cz)
                    for candidate_index in candidate_bins.get(key, ()):
                        if available_pos[candidate_index] < 0:
                            continue
                        du_coord = periodic_delta(candidate_u[candidate_index], placed_u)
                        dz_coord = float(candidate_z[candidate_index]) - float(placed_z)
                        if ((du_coord * du_coord) + (dz_coord * dz_coord)) > search_limit_sq:
                            continue
                        world = candidate_world[candidate_index]
                        dx = float(world[0]) - float(placed_world[0])
                        dy = float(world[1]) - float(placed_world[1])
                        dz_world = float(world[2]) - float(placed_world[2])
                        dist = math.sqrt((dx * dx) + (dy * dy) + (dz_world * dz_world))
                        allowed_radius = dist - (float(placed_radius) + collision_padding)
                        if allowed_radius < candidate_capacity[candidate_index]:
                            remove_from_capacity_bucket(candidate_index)
                            candidate_capacity[candidate_index] = float(allowed_radius)
                            if allowed_radius < (min_radius - 1e-6):
                                remove_candidate(candidate_index)
                            else:
                                add_to_capacity_bucket(candidate_index)

        def exact_candidate_gap(candidate_index, candidate_radius):
            z_gap = half_length - abs(float(candidate_z[candidate_index]))
            if z_gap < candidate_radius:
                return None
            nearest_gap = z_gap - candidate_radius
            world = candidate_world[candidate_index]
            iu, iz = candidate_bin_index(candidate_u[candidate_index], candidate_z[candidate_index])
            search_span = max(
                1,
                int(math.ceil((candidate_radius + max_radius + collision_padding) / candidate_bin_size)),
            )
            seen = set()
            for du_bin in range(-search_span, search_span + 1):
                cu = (iu + du_bin) % n_u_bins
                for dz_bin in range(-search_span, search_span + 1):
                    cz = iz + dz_bin
                    if cz < 0 or cz >= n_z_bins:
                        continue
                    for particle_index in placed_bins.get((cu, cz), ()):
                        if particle_index in seen:
                            continue
                        seen.add(particle_index)
                        other = placed_particles[particle_index]
                        min_dist = candidate_radius + other["radius"] + collision_padding
                        dx = float(world[0]) - float(other["world"][0])
                        dy = float(world[1]) - float(other["world"][1])
                        dz_world = float(world[2]) - float(other["world"][2])
                        dist_sq = (dx * dx) + (dy * dy) + (dz_world * dz_world)
                        if dist_sq < (min_dist * min_dist):
                            return None
                        gap = math.sqrt(dist_sq) - min_dist
                        if gap < nearest_gap:
                            nearest_gap = gap
            return nearest_gap

        def add_particle(class_suffix, candidate_index, candidate_radius):
            world = candidate_world[candidate_index]
            normal = candidate_normal[candidate_index]
            placements[class_suffix].append(
                [
                    [float(world[0]), float(world[1]), float(world[2])],
                    self._rotation44_from_z_axis(normal),
                ]
            )
            placed_counts[class_suffix] = int(placed_counts.get(class_suffix, 0)) + 1
            placed_particles.append(
                {
                    "world": world,
                    "u": float(candidate_u[candidate_index]),
                    "z": float(candidate_z[candidate_index]),
                    "radius": float(candidate_radius),
                }
            )
            placed_bins.setdefault(
                candidate_bin_index(candidate_u[candidate_index], candidate_z[candidate_index]),
                [],
            ).append(len(placed_particles) - 1)
            remove_candidate(candidate_index)
            update_candidate_capacities(
                candidate_u[candidate_index],
                candidate_z[candidate_index],
                world,
                candidate_radius,
            )

        def choose_best_candidate(class_info):
            class_radius = float(class_info["particle_radius"])
            free_count = len(available_indices)
            if free_count <= 0:
                return None
            start_bucket = bucket_id_for_capacity(class_radius)
            if not capacity_buckets:
                return None
            max_bucket = max(capacity_buckets.keys())
            bucket_cursor = start_bucket
            target_pool = 128
            while bucket_cursor <= max_bucket:
                candidate_pool = []
                while bucket_cursor <= max_bucket and len(candidate_pool) < target_pool:
                    bucket = capacity_buckets.get(bucket_cursor, None)
                    if bucket:
                        bucket_items = tuple(bucket)
                        remaining = target_pool - len(candidate_pool)
                        if len(bucket_items) <= remaining:
                            candidate_pool.extend(bucket_items)
                        else:
                            candidate_pool.extend(rng.sample(bucket_items, remaining))
                    bucket_cursor += 1
                if not candidate_pool:
                    continue
                candidate_pool.sort(key=lambda idx: (float(candidate_capacity[idx]), rng.random()))
                for candidate_index in candidate_pool:
                    exact_gap = exact_candidate_gap(candidate_index, class_radius)
                    if exact_gap is not None:
                        return {
                            "candidate_index": int(candidate_index),
                            "gap": float(exact_gap),
                        }
                    remove_candidate(candidate_index)
            return None

        def class_fill_ratio(class_suffix):
            target_fraction = max(
                1e-9,
                float(class_by_suffix[class_suffix].get("abundance_weight", 0.0)) / total_weight,
            )
            return float(placed_counts.get(class_suffix, 0)) / target_fraction

        lipid_suffixes = [
            str(class_info["suffix"])
            for class_info in sorted_classes
            if str(class_info.get("suffix", "")) == "lipids"
        ]
        protein_suffixes = [
            str(class_info["suffix"])
            for class_info in sorted_classes
            if str(class_info.get("suffix", "")) not in set(lipid_suffixes)
        ]
        protein_weight_total = sum(
            max(0.0, float(class_by_suffix[suffix].get("abundance_weight", 0.0)))
            for suffix in protein_suffixes
        )

        def protein_fill_ratio(class_suffix):
            target_fraction = max(
                1e-9,
                float(class_by_suffix[class_suffix].get("abundance_weight", 0.0)) / max(protein_weight_total, 1e-9),
            )
            return float(placed_counts.get(class_suffix, 0)) / target_fraction

        active_suffixes = list(protein_suffixes)
        failed_rounds = {suffix: 0 for suffix in (protein_suffixes + lipid_suffixes)}
        idle_cycles = 0
        max_failed_rounds = 10
        while True:
            if active_suffixes:
                ordered_suffixes = sorted(
                    active_suffixes,
                    key=lambda suffix: (
                        protein_fill_ratio(suffix),
                        -float(class_by_suffix[suffix].get("particle_radius", 0.0)),
                        rng.random(),
                    ),
                )
            elif lipid_suffixes:
                ordered_suffixes = list(lipid_suffixes)
            else:
                break
            placed_this_cycle = False
            for class_suffix in ordered_suffixes:
                class_info = class_by_suffix[class_suffix]
                candidate = choose_best_candidate(class_info)
                if candidate is None:
                    failed_rounds[class_suffix] = int(failed_rounds.get(class_suffix, 0)) + 1
                    if active_suffixes and failed_rounds[class_suffix] >= max_failed_rounds:
                        active_suffixes = [suffix for suffix in active_suffixes if suffix != class_suffix]
                    continue
                failed_rounds[class_suffix] = 0
                add_particle(
                    class_suffix,
                    candidate["candidate_index"],
                    float(class_info["particle_radius"]),
                )
                placed_this_cycle = True
                idle_cycles = 0
                break
            if not placed_this_cycle:
                if active_suffixes:
                    active_suffixes = []
                    idle_cycles = 0
                    continue
                idle_cycles += 1
                if idle_cycles >= 2:
                    break

        return placements

    def _build_open_cylinder_mesh(self, center, axis, radius, length, n_theta, ring_count):
        basis = self._axis_basis(axis)
        vertices = []
        ring_count = max(2, int(ring_count))
        n_theta = max(12, int(n_theta))
        for iz in range(ring_count):
            if ring_count == 1:
                z_local = 0.0
            else:
                z_local = (-0.5 * length) + (length * float(iz) / float(ring_count - 1))
            for it in range(n_theta):
                theta = (2.0 * math.pi * float(it)) / float(n_theta)
                local = (radius * math.cos(theta), radius * math.sin(theta), z_local)
                world = self._apply_basis(center, basis, local)
                vertices.append([float(world[0]), float(world[1]), float(world[2])])

        triangles = []
        for iz in range(ring_count - 1):
            row0 = iz * n_theta
            row1 = (iz + 1) * n_theta
            for it in range(n_theta):
                a = row0 + it
                b = row0 + ((it + 1) % n_theta)
                c = row1 + it
                d = row1 + ((it + 1) % n_theta)
                triangles.append([a, c, b])
                triangles.append([b, c, d])
        return vertices, triangles

    def _build_uv_sphere_mesh(self, radius, lat_count=12, lon_count=24):
        radius = float(radius)
        lat_count = max(4, int(lat_count))
        lon_count = max(8, int(lon_count))

        vertices = [[0.0, 0.0, radius]]
        for ilat in range(1, lat_count):
            phi = math.pi * float(ilat) / float(lat_count)
            ring_radius = radius * math.sin(phi)
            z = radius * math.cos(phi)
            for ilon in range(lon_count):
                theta = (2.0 * math.pi * float(ilon)) / float(lon_count)
                vertices.append(
                    [
                        ring_radius * math.cos(theta),
                        ring_radius * math.sin(theta),
                        z,
                    ]
                )
        vertices.append([0.0, 0.0, -radius])

        triangles = []
        north = 0
        south = len(vertices) - 1
        first_ring = 1
        last_ring = 1 + ((lat_count - 2) * lon_count)

        for ilon in range(lon_count):
            a = first_ring + ilon
            b = first_ring + ((ilon + 1) % lon_count)
            triangles.append([north, a, b])

        for ilat in range(lat_count - 2):
            ring0 = 1 + (ilat * lon_count)
            ring1 = ring0 + lon_count
            for ilon in range(lon_count):
                a = ring0 + ilon
                b = ring0 + ((ilon + 1) % lon_count)
                c = ring1 + ilon
                d = ring1 + ((ilon + 1) % lon_count)
                triangles.append([a, c, b])
                triangles.append([b, c, d])

        if last_ring < south:
            for ilon in range(lon_count):
                a = last_ring + ilon
                b = last_ring + ((ilon + 1) % lon_count)
                triangles.append([a, south, b])
        return vertices, triangles

    def _write_collada_mesh(self, vertices, triangles, out_path, mesh_name, rgba=None):
        mesh_name = self._sanitize_stem(mesh_name or "mesh")
        geometry_id = f"{mesh_name}_geometry"
        positions_id = f"{mesh_name}_positions"
        vertices_id = f"{mesh_name}_vertices"
        material_id = f"{mesh_name}_material"
        effect_id = f"{mesh_name}_effect"
        material_symbol = f"{mesh_name}_mat"

        root = ET.Element(
            "COLLADA",
            {
                "xmlns": "http://www.collada.org/2005/11/COLLADASchema",
                "version": "1.4.1",
            },
        )
        asset = ET.SubElement(root, "asset")
        ET.SubElement(asset, "contributor")
        ET.SubElement(asset, "created").text = "2026-05-22T00:00:00"
        ET.SubElement(asset, "modified").text = "2026-05-22T00:00:00"
        ET.SubElement(asset, "unit", {"name": "angstrom", "meter": "1e-10"})
        ET.SubElement(asset, "up_axis").text = "Z_UP"

        if rgba is not None:
            r, g, b, a = self._collada_color_rgba(rgba)
            library_effects = ET.SubElement(root, "library_effects")
            effect = ET.SubElement(library_effects, "effect", {"id": effect_id})
            profile_common = ET.SubElement(effect, "profile_COMMON")
            technique = ET.SubElement(profile_common, "technique", {"sid": "common"})
            lambert = ET.SubElement(technique, "lambert")
            ET.SubElement(ET.SubElement(lambert, "ambient"), "color").text = f"{r} {g} {b} {a}"
            ET.SubElement(ET.SubElement(lambert, "diffuse"), "color").text = f"{r} {g} {b} {a}"

            library_materials = ET.SubElement(root, "library_materials")
            material = ET.SubElement(
                library_materials,
                "material",
                {"id": material_id, "name": mesh_name},
            )
            ET.SubElement(material, "instance_effect", {"url": f"#{effect_id}"})

        library_geometries = ET.SubElement(root, "library_geometries")
        geometry = ET.SubElement(library_geometries, "geometry", {"id": geometry_id, "name": mesh_name})
        mesh = ET.SubElement(geometry, "mesh")
        source = ET.SubElement(mesh, "source", {"id": positions_id})
        float_array = ET.SubElement(
            source,
            "float_array",
            {
                "id": f"{positions_id}_array",
                "count": str(len(vertices) * 3),
            },
        )
        float_array.text = " ".join(
            f"{float(v[0]):.6f} {float(v[1]):.6f} {float(v[2]):.6f}" for v in vertices
        )
        technique_common = ET.SubElement(source, "technique_common")
        accessor = ET.SubElement(
            technique_common,
            "accessor",
            {
                "source": f"#{positions_id}_array",
                "count": str(len(vertices)),
                "stride": "3",
            },
        )
        ET.SubElement(accessor, "param", {"name": "X", "type": "float"})
        ET.SubElement(accessor, "param", {"name": "Y", "type": "float"})
        ET.SubElement(accessor, "param", {"name": "Z", "type": "float"})

        vertices_node = ET.SubElement(mesh, "vertices", {"id": vertices_id})
        ET.SubElement(
            vertices_node,
            "input",
            {
                "semantic": "POSITION",
                "source": f"#{positions_id}",
            },
        )
        triangles_attrs = {"count": str(len(triangles))}
        if rgba is not None:
            triangles_attrs["material"] = material_symbol
        triangles_node = ET.SubElement(mesh, "triangles", triangles_attrs)
        ET.SubElement(
            triangles_node,
            "input",
            {
                "semantic": "VERTEX",
                "source": f"#{vertices_id}",
                "offset": "0",
            },
        )
        ET.SubElement(triangles_node, "p").text = " ".join(
            f"{int(tri[0])} {int(tri[1])} {int(tri[2])}" for tri in triangles
        )

        library_visual_scenes = ET.SubElement(root, "library_visual_scenes")
        visual_scene = ET.SubElement(library_visual_scenes, "visual_scene", {"id": "Scene", "name": "Scene"})
        node = ET.SubElement(visual_scene, "node", {"id": mesh_name, "name": mesh_name, "type": "NODE"})
        instance_geometry = ET.SubElement(node, "instance_geometry", {"url": f"#{geometry_id}"})
        if rgba is not None:
            bind_material = ET.SubElement(instance_geometry, "bind_material")
            technique_common = ET.SubElement(bind_material, "technique_common")
            ET.SubElement(
                technique_common,
                "instance_material",
                {
                    "symbol": material_symbol,
                    "target": f"#{material_id}",
                },
            )
        scene = ET.SubElement(root, "scene")
        ET.SubElement(scene, "instance_visual_scene", {"url": "#Scene"})

        tree = ET.ElementTree(root)
        try:
            ET.indent(tree, space="  ")
        except Exception:
            pass
        tree.write(out_path, encoding="utf-8", xml_declaration=True)

    def _collada_color_rgba(self, rgba):
        values = list(rgba or ())
        while len(values) < 4:
            values.append(255)
        floats = []
        for value in values[:4]:
            channel = float(value)
            if channel > 1.0:
                channel = channel / 255.0
            floats.append(max(0.0, min(1.0, channel)))
        return tuple(f"{value:.6f}" for value in floats)

    def _safe_unit_vector(self, v):
        try:
            values = [float(c) for c in v]
        except Exception:
            values = [0.0, 0.0, 1.0]
        norm = math.sqrt(sum(c * c for c in values))
        if norm < 1e-12:
            return [0.0, 0.0, 1.0]
        return [c / norm for c in values]

    def _axis_basis(self, axis):
        z_axis = self._safe_unit_vector(axis)
        ref = [1.0, 0.0, 0.0] if abs(z_axis[0]) < 0.9 else [0.0, 1.0, 0.0]
        x_axis = self._safe_unit_vector(self._cross(ref, z_axis))
        y_axis = self._safe_unit_vector(self._cross(z_axis, x_axis))
        return x_axis, y_axis, z_axis

    def _cross(self, a, b):
        return [
            (float(a[1]) * float(b[2])) - (float(a[2]) * float(b[1])),
            (float(a[2]) * float(b[0])) - (float(a[0]) * float(b[2])),
            (float(a[0]) * float(b[1])) - (float(a[1]) * float(b[0])),
        ]

    def _apply_basis(self, center, basis, local):
        x_axis, y_axis, z_axis = basis
        return [
            float(center[0]) + (float(local[0]) * x_axis[0]) + (float(local[1]) * y_axis[0]) + (float(local[2]) * z_axis[0]),
            float(center[1]) + (float(local[0]) * x_axis[1]) + (float(local[1]) * y_axis[1]) + (float(local[2]) * z_axis[1]),
            float(center[2]) + (float(local[0]) * x_axis[2]) + (float(local[1]) * y_axis[2]) + (float(local[2]) * z_axis[2]),
        ]

    def _rotation44_from_z_axis(self, axis):
        x_axis, y_axis, z_axis = self._axis_basis(axis)
        return [
            [float(x_axis[0]), float(y_axis[0]), float(z_axis[0]), 0.0],
            [float(x_axis[1]), float(y_axis[1]), float(z_axis[1]), 0.0],
            [float(x_axis[2]), float(y_axis[2]), float(z_axis[2]), 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
