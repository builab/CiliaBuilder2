# vim: set expandtab shiftwidth=4 softtabstop=4:

import os
from urllib.parse import urlparse


def open_local_apr_package(session, apr_path, name=None):
    return open_local_cellpack_package(session, apr_path, name=name)


def open_local_cellpack_package(session, package_path, name=None):
    from chimerax.core.errors import UserError

    package_path = os.path.abspath(os.path.expanduser(str(package_path)))
    if not os.path.isfile(package_path):
        raise UserError(f'cellPACK file not found: {package_path}')

    try:
        payload = _read_json(package_path)
    except Exception as e:
        raise UserError(f'Could not read cellPACK JSON "{package_path}": {e}')

    if _looks_like_apr_payload(payload):
        return _open_local_apr_payload(session, package_path, payload, name=name)

    if payload.get("format", None) == "ciliabuilder_cellpack_package":
        return _open_ciliabuilder_manifest_package(session, package_path, payload, name=name)

    if _looks_like_ciliabuilder_recipe_payload(payload):
        return _open_ciliabuilder_recipe_package(session, package_path, payload, name=name)

    raise UserError(
        f'Unsupported cellPACK-style JSON "{package_path}". '
        "Expected an .apr.json results file, a ciliabuilder_manifest.json file, or a recipe.json export."
    )


def _open_local_apr_payload(session, apr_path, payload, name=None):
    from chimerax.core.errors import UserError
    from chimerax.core.models import Model
    from chimerax.surface.collada import read_collada_surfaces
    from chimerax.cellpack import read_apr

    package_root = os.path.dirname(apr_path)
    model_name = _default_model_name(apr_path, name=name)

    try:
        recipe_loc, pieces = _read_autopack_results_payload(payload)
    except Exception as e:
        raise UserError(f'Could not read APR file "{apr_path}": {e}')

    recipe_path = _resolve_local_cellpack_path(
        recipe_loc,
        search_dirs=[os.path.dirname(apr_path), package_root],
        kind="recipe",
    )

    try:
        ingr_filenames, comp_surfaces = read_apr.read_autopack_recipe(recipe_path)
    except Exception as e:
        raise UserError(f'Could not read cellPACK recipe "{recipe_path}": {e}')

    cpm = Model(model_name, session)
    cpm._cb_local_apr_path = apr_path
    cpm._cb_local_cellpack_recipe_path = recipe_path

    comp_lookup = {}
    for comp_name, rep_loc, geom_loc in comp_surfaces:
        compartment = Model(comp_name, session)

        if rep_loc is not None:
            rep_path = _resolve_local_cellpack_path(
                rep_loc,
                search_dirs=[os.path.dirname(recipe_path), package_root],
                kind=f'compartment representation for "{comp_name}"',
            )
            slist, _msg = read_collada_surfaces(session, rep_path, "representation")
            compartment.add(slist)

        if geom_loc is not None:
            geom_path = _resolve_local_cellpack_path(
                geom_loc,
                search_dirs=[os.path.dirname(recipe_path), package_root],
                kind=f'compartment bounds for "{comp_name}"',
            )
            slist, _msg = read_collada_surfaces(session, geom_path, "geometry")
            for surf in slist:
                try:
                    surf.display = False
                except Exception:
                    pass
            compartment.add(slist)

        cpm.add([compartment])
        comp_lookup[comp_name] = compartment

    ingr_mesh_path = {}
    placement_count = 0
    for ingr_id in sorted(pieces.keys()):
        ingr_filename = ingr_filenames.get(ingr_id, None)
        if ingr_filename is None:
            raise UserError(
                f'Missing ingredient definition for compartment "{ingr_id[0]}", '
                f'region "{ingr_id[1]}", ingredient "{ingr_id[2]}".'
            )

        mesh_path = ingr_mesh_path.get(ingr_filename, None)
        if mesh_path is None:
            ingr_path = _resolve_local_cellpack_path(
                ingr_filename,
                search_dirs=[os.path.dirname(recipe_path), package_root],
                kind=f'ingredient "{ingr_id[2]}"',
            )
            try:
                mesh_loc = read_apr.read_ingredient(ingr_path)
            except Exception as e:
                raise UserError(f'Could not read ingredient file "{ingr_path}": {e}')
            mesh_path = _resolve_local_cellpack_path(
                mesh_loc,
                search_dirs=[os.path.dirname(ingr_path), os.path.dirname(recipe_path), package_root],
                kind=f'mesh for ingredient "{ingr_id[2]}"',
            )
            ingr_mesh_path[ingr_filename] = mesh_path

        comp_name, interior_or_surface, ingr_name = ingr_id
        region_model = comp_lookup.get((comp_name, interior_or_surface), None)
        if region_model is None:
            parent = comp_lookup.get(comp_name, None)
            if parent is None:
                raise UserError(f'Missing compartment "{comp_name}" in recipe "{recipe_path}".')
            region_model = Model(interior_or_surface, session)
            parent.add([region_model])
            comp_lookup[(comp_name, interior_or_surface)] = region_model

        placements = pieces[ingr_id]
        placement_count += len(placements)
        try:
            isurf = read_apr.create_surface(session, mesh_path, ingr_name, placements)
        except Exception as e:
            raise UserError(f'Could not create surface for ingredient "{ingr_name}" from "{mesh_path}": {e}')
        region_model.add([isurf])

    info = {
        "apr_path": apr_path,
        "recipe_path": recipe_path,
        "compartment_count": len(comp_surfaces),
        "ingredient_count": len(ingr_filenames),
        "placement_count": placement_count,
    }
    return cpm, info


def _open_ciliabuilder_manifest_package(session, manifest_path, payload, name=None):
    from chimerax.core.models import Model

    package_root = os.path.dirname(manifest_path)
    model_name = _default_model_name(
        manifest_path,
        name=name or payload.get("package_name", None),
    )
    root = Model(model_name, session)
    root._cb_local_manifest_path = manifest_path
    root._cb_local_cellpack_recipe_path = payload.get("recipe", None)
    session.models.add([root])

    membrane_info = _load_ciliabuilder_membrane_bundle(
        session,
        package_root,
        payload.get("cellpack_membrane_bundle", None),
        parent=root,
    )

    loaded_outputs = 0
    opened_model_count = 0
    for entry in payload.get("outputs", []) or []:
        if membrane_info is not None and str(entry.get("output_kind", "") or "").lower() == "membrane":
            continue
        rel_path = entry.get("relative_path", None)
        if not rel_path:
            continue
        asset_path = _resolve_export_asset_path(rel_path, package_root)
        opened = _open_local_asset_models(session, asset_path)
        if not opened:
            continue

        output_name = str(entry.get("name", "") or os.path.basename(asset_path))
        if len(opened) == 1:
            model = opened[0]
            try:
                model.name = output_name
            except Exception:
                pass
            session.models.add([model], parent=root)
        else:
            group = Model(output_name, session)
            session.models.add([group], parent=root)
            for model in opened:
                session.models.add([model], parent=group)

        loaded_outputs += 1
        opened_model_count += len(opened)

    info = {
        "path": manifest_path,
        "package_kind": "manifest",
        "output_count": loaded_outputs,
        "model_count": opened_model_count,
    }
    if membrane_info is not None:
        info["membrane_bundle_loaded"] = True
        info["membrane_apr_path"] = membrane_info.get("apr_path", None)
        info["membrane_compartment_count"] = int(membrane_info.get("compartment_count", 0))
        info["membrane_ingredient_count"] = int(membrane_info.get("ingredient_count", 0))
        info["membrane_placement_count"] = int(membrane_info.get("placement_count", 0))
    return root, info


def _open_ciliabuilder_recipe_package(session, recipe_path, payload, name=None):
    from chimerax.core.models import Model

    package_root = os.path.dirname(recipe_path)
    model_name = _default_model_name(
        recipe_path,
        name=name or payload.get("name", None),
    )
    root = Model(model_name, session)
    root._cb_local_cellpack_recipe_path = recipe_path
    session.models.add([root])

    membrane_info = _load_ciliabuilder_membrane_bundle(
        session,
        package_root,
        ((payload.get("ciliabuilder", {}) or {}).get("cellpack_membrane_bundle", None)),
        parent=root,
    )

    loaded_outputs = 0
    opened_model_count = 0
    for object_id, obj in sorted((payload.get("objects", {}) or {}).items()):
        cb_info = (obj.get("ciliabuilder", {}) or {})
        if membrane_info is not None and str(cb_info.get("output_kind", "") or "").lower() == "membrane":
            continue
        mesh_info = (((obj.get("representations", {}) or {}).get("mesh", {})) or {})
        mesh_path = mesh_info.get("path", None)
        if not mesh_path:
            continue
        asset_path = _resolve_export_asset_path(mesh_path, package_root)
        opened = _open_local_asset_models(session, asset_path)
        if not opened:
            continue

        output_name = str(obj.get("name", "") or object_id or os.path.basename(asset_path))
        if len(opened) == 1:
            model = opened[0]
            try:
                model.name = output_name
            except Exception:
                pass
            session.models.add([model], parent=root)
        else:
            group = Model(output_name, session)
            session.models.add([group], parent=root)
            for model in opened:
                session.models.add([model], parent=group)

        loaded_outputs += 1
        opened_model_count += len(opened)

    info = {
        "path": recipe_path,
        "package_kind": "recipe",
        "output_count": loaded_outputs,
        "model_count": opened_model_count,
    }
    if membrane_info is not None:
        info["membrane_bundle_loaded"] = True
        info["membrane_apr_path"] = membrane_info.get("apr_path", None)
        info["membrane_compartment_count"] = int(membrane_info.get("compartment_count", 0))
        info["membrane_ingredient_count"] = int(membrane_info.get("ingredient_count", 0))
        info["membrane_placement_count"] = int(membrane_info.get("placement_count", 0))
    return root, info


def _load_ciliabuilder_membrane_bundle(session, package_root, bundle_info, parent=None):
    from chimerax.core.errors import UserError

    if not isinstance(bundle_info, dict):
        return None

    result_path_text = (
        bundle_info.get("result_path", None)
        or bundle_info.get("apr_path", None)
    )
    if not result_path_text:
        return None

    result_path = _resolve_export_asset_path(result_path_text, package_root)
    try:
        payload = _read_json(result_path)
    except Exception as e:
        raise UserError(f'Could not read membrane APR file "{result_path}": {e}')
    if not _looks_like_apr_payload(payload):
        raise UserError(f'File "{result_path}" is not a valid cellPACK APR results file.')

    model, info = _open_local_apr_payload(session, result_path, payload)
    if parent is None:
        session.models.add([model])
    else:
        session.models.add([model], parent=parent)
    return info


def _default_model_name(apr_path, name=None):
    requested = str(name or "").strip()
    if requested:
        return requested
    base = os.path.basename(str(apr_path))
    if base.endswith(".apr.json"):
        return base[:-9]
    if base.endswith(".json"):
        return base[:-5]
    return os.path.splitext(base)[0]


def _read_json(path):
    import json

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _looks_like_apr_payload(payload):
    recipe = payload.get("recipe", None)
    return isinstance(recipe, dict) and "setupfile" in recipe and "compartments" in payload


def _looks_like_ciliabuilder_recipe_payload(payload):
    return (
        payload.get("format_version", None) is not None
        and isinstance(payload.get("objects", None), dict)
        and isinstance(payload.get("composition", None), list)
    )


def _read_autopack_results_payload(payload):
    recipe_path = payload["recipe"]["setupfile"]
    pieces = {}
    for comp_name, cres in payload["compartments"].items():
        for interior_or_surface, comp_ingr in cres.items():
            for ingr_name, ingr_places in comp_ingr["ingredients"].items():
                for translation, rotation44 in ingr_places["results"]:
                    t0, t1, t2 = translation
                    r00, r01, r02 = rotation44[0][:3]
                    r10, r11, r12 = rotation44[1][:3]
                    r20, r21, r22 = rotation44[2][:3]
                    tf = (
                        (r00, r01, r02, t0),
                        (r10, r11, r12, t1),
                        (r20, r21, r22, t2),
                    )
                    from chimerax.geometry import Place
                    p = Place(tf)
                    ingr_id = (comp_name, interior_or_surface, ingr_name)
                    pieces.setdefault(ingr_id, []).append(p)
    return recipe_path, pieces


def _resolve_export_asset_path(path_text, package_root):
    from chimerax.core.errors import UserError

    raw = str(path_text or "").strip()
    if not raw:
        raise UserError("Missing exported asset path.")
    if os.path.isabs(raw):
        path = os.path.abspath(os.path.expanduser(raw))
    else:
        path = os.path.abspath(os.path.join(package_root, raw))
    if not os.path.exists(path):
        raise UserError(f'Could not find exported asset "{raw}" relative to "{package_root}".')
    return path


def _open_local_asset_models(session, asset_path):
    from chimerax.core.commands import FileNameArg
    from chimerax.core.commands import run as _run

    before = set(session.models.list())
    _run(session, f"open {FileNameArg.unparse(asset_path)}")
    return [m for m in session.models.list() if m not in before]


def _resolve_local_cellpack_path(path_text, search_dirs, kind="file"):
    from chimerax.core.errors import UserError

    raw = str(path_text or "").strip()
    if not raw:
        raise UserError(f"Missing {kind} path in cellPACK package.")

    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme not in ("file",):
        raise UserError(
            f'The local APR loader cannot fetch remote {kind} paths: "{raw}". '
            "Use local files or ChimeraX's built-in cellPACK fetcher instead."
        )

    if parsed.scheme == "file":
        local_path = os.path.abspath(os.path.expanduser(parsed.path))
        if os.path.exists(local_path):
            return local_path

    candidates = []
    normalized = raw.replace("\\", "/")
    suffix = None
    marker = "autoPACKserver/"
    if marker in normalized:
        suffix = normalized.split(marker, 1)[1]

    if os.path.isabs(raw):
        candidates.append(os.path.abspath(os.path.expanduser(raw)))

    for search_dir in search_dirs or ():
        if not search_dir:
            continue
        base = os.path.abspath(os.path.expanduser(str(search_dir)))
        candidates.append(os.path.abspath(os.path.join(base, raw)))
        candidates.append(os.path.abspath(os.path.join(base, normalized)))
        if suffix:
            candidates.append(os.path.abspath(os.path.join(base, suffix)))
        candidates.append(os.path.abspath(os.path.join(base, os.path.basename(normalized))))

    seen = set()
    unique = []
    for path in candidates:
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)

    for path in unique:
        if os.path.exists(path):
            return path

    searched = "\n".join(unique[:8])
    if len(unique) > 8:
        searched += "\n..."
    raise UserError(
        f'Could not find the local {kind} referenced as "{raw}".\n'
        f"Searched these locations:\n{searched}"
    )
