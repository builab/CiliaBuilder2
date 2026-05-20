# vim: set expandtab shiftwidth=4 softtabstop=4:

import json
import math
import os
import re

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
        self._name_counts = {}

    def export(self):
        os.makedirs(self.outputs_dir, exist_ok=True)
        os.makedirs(self.sources_dir, exist_ok=True)

        source_models = self._collect_source_models()
        output_models = self._collect_output_models()
        export_targets = output_models if output_models else source_models
        if not export_targets:
            raise RuntimeError("No CiliaBuilder outputs or source models found to export for cellPACK.")

        source_entries = [self._export_source_model(model) for model in source_models]
        source_by_ref = {}
        for entry in source_entries:
            ref = entry.get("model_ref")
            if ref:
                source_by_ref[ref] = entry

        output_entries = []
        for index, model in enumerate(export_targets, start=1):
            output_entries.append(self._export_output_model(model, index, source_by_ref))

        recipe = self._build_recipe(output_entries)
        manifest = self._build_manifest(source_entries, output_entries, recipe_path="recipe.json")

        recipe_path = os.path.join(self.package_dir, "recipe.json")
        manifest_path = os.path.join(self.package_dir, "ciliabuilder_manifest.json")
        with open(recipe_path, "w", encoding="utf-8") as f:
            json.dump(recipe, f, indent=2)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return {
            "package_dir": self.package_dir,
            "recipe_path": recipe_path,
            "manifest_path": manifest_path,
            "n_sources": len(source_entries),
            "n_outputs": len(output_entries),
        }

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

        for root in self.tool._attached_results.values():
            if root is None:
                continue
            key = id(root)
            if key in seen:
                continue
            seen.add(key)
            out.append(root)

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

    def _package_bounds(self, output_entries):
        mins = [float("inf"), float("inf"), float("inf")]
        maxs = [float("-inf"), float("-inf"), float("-inf")]
        for entry in output_entries:
            bounds = entry["bounds"]
            for i in range(3):
                mins[i] = min(mins[i], float(bounds["min"][i]))
                maxs[i] = max(maxs[i], float(bounds["max"][i]))
        if not output_entries:
            return [[0.0, 0.0, 0.0], [1000.0, 1000.0, 1000.0]]
        return [mins, maxs]

    def _build_recipe(self, output_entries):
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
            "bounding_box": self._package_bounds(output_entries),
            "objects": objects,
            "composition": composition,
            "ciliabuilder": {
                "manifest": "ciliabuilder_manifest.json",
                "notes": "Portable export package from CiliaBuilder2. Objects reference relative asset paths.",
            },
        }

    def _build_manifest(self, source_entries, output_entries, recipe_path):
        return {
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
