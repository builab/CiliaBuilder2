"""Remember GLB input paths which ChimeraX's glTF reader does not retain."""

import glob
import os


def is_glb_path(path):
    return str(path or "").lower().endswith((".glb", ".gltf", ".glb.gz", ".gltf.gz"))


def normalize_glb_name(model):
    name = str(getattr(model, "name", ""))
    if name.lower().endswith((".glb.gz", ".gltf.gz")):
        model._cb_compressed_source_name = name
        model.name = name[:-3]


def remember_glb_source(model, path):
    if model is None or not is_glb_path(path):
        return None
    path = os.path.abspath(os.path.expanduser(str(path)))
    model._cb_original_source_path = path
    normalize_glb_name(model)
    return path


def original_glb_path(model):
    path = getattr(model, "_cb_original_source_path", None)
    if path:
        return path
    for attr in ("path", "filename"):
        path = getattr(model, attr, None)
        if is_glb_path(path):
            return remember_glb_source(model, path)

    # Recover inputs opened before the tool started, when the match is unique.
    history = getattr(getattr(model, "session", None), "file_history", None)
    original_name = str(getattr(model, "_cb_compressed_source_name", "") or getattr(model, "name", ""))
    exact, displayed = set(), set()
    for entry in getattr(history, "files", ()):
        path = getattr(entry, "path", None)
        if getattr(entry, "database", None) is not None or not is_glb_path(path):
            continue
        name = os.path.basename(path)
        display_name = name[:-3] if name.lower().endswith(".gz") else name
        if name == original_name:
            exact.add(path)
        elif display_name == original_name:
            displayed.add(path)
    candidates = exact or displayed
    if len(candidates) == 1:
        return remember_glb_source(model, candidates.pop())
    return None


class _GlbSourceTracker:
    def __init__(self, session):
        from chimerax.core.models import ADD_MODELS

        self.session = session
        self.pending = []
        self.handlers = [
            session.triggers.add_handler("command started", self._command_started),
            session.triggers.add_handler("command finished", self._command_finished),
            session.triggers.add_handler("command failed", self._command_failed),
            session.triggers.add_handler(ADD_MODELS, self._models_added),
        ]
        self._models_added(None, session.models.list())

    def _models_added(self, _trigger, models):
        for model in models:
            if model.parent in (None, self.session.models.scene_root_model) or getattr(model, "_cb_attach_source", False):
                normalize_glb_name(model)

    def _command_started(self, _trigger, text):
        from chimerax.core.commands import StringArg

        command, _, remaining = StringArg.parse(text, self.session)
        if command.lower() not in ("open", "ope", "op", "o"):
            return
        # Only parse literal path tokens. Reusing a file-dialog argument parser
        # here would open an extra dialog for 'open browse'.
        paths = []
        while remaining.strip():
            value, _, remaining = StringArg.parse(remaining.lstrip(), self.session)
            expanded = os.path.expanduser(value)
            matches = [expanded] if os.path.isfile(expanded) else glob.glob(expanded)
            if not matches:
                break
            paths.extend(os.path.abspath(path) for path in matches if os.path.isfile(path))
        if any(is_glb_path(path) for path in paths):
            self.pending.append((text, paths, set(self.session.models.list())))

    def _take_pending(self, text):
        for i in range(len(self.pending) - 1, -1, -1):
            if self.pending[i][0] == text:
                return self.pending.pop(i)
        return None

    def _command_failed(self, _trigger, text):
        self._take_pending(text)

    def _command_finished(self, _trigger, text):
        pending = self._take_pending(text)
        if pending is None:
            return
        _, paths, before = pending
        opened = set(self.session.models.list()) - before
        for model in opened:
            if model.parent in opened:
                continue
            if len(paths) == 1:
                remember_glb_source(model, paths[0])
            else:
                names = {model.name, getattr(model, "_cb_compressed_source_name", "")}
                matches = [path for path in paths if is_glb_path(path) and os.path.basename(path) in names]
                if len(matches) == 1:
                    remember_glb_source(model, matches[0])


def track_glb_sources(session):
    if not hasattr(session, "_cb_glb_source_tracker"):
        session._cb_glb_source_tracker = _GlbSourceTracker(session)
