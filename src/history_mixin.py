# vim: set expandtab shiftwidth=4 softtabstop=4:

import copy
import json
import os

from chimerax.core.commands import run as _run


class HistoryMixin:
    """Per-step undo/redo helpers for CiliaBuilder-managed scene content."""

    def _update_history_buttons(self):
        if hasattr(self, "undo_action_btn"):
            self.undo_action_btn.setEnabled(bool(getattr(self, "_history_undo_stack", [])))
        if hasattr(self, "redo_action_btn"):
            self.redo_action_btn.setEnabled(bool(getattr(self, "_history_redo_stack", [])))

    def _history_kind_fields(self):
        return (
            ("source", "attach_sources"),
            ("star", "generated_star_models"),
            ("membrane", "generated_membranes"),
            ("marker_path", "generated_marker_paths"),
            ("attachment", "attachments"),
        )

    def _capture_history_scene_state(self):
        export_cache = {}
        return {
            "attach_sources": copy.deepcopy(self._attach_source_models_state(None, None, export_cache)),
            "generated_star_models": copy.deepcopy(self._generated_star_models()),
            "generated_membranes": copy.deepcopy(self._generated_membrane_models()),
            "generated_marker_paths": copy.deepcopy(self._generated_marker_path_models()),
            "attachments": copy.deepcopy(self._attachment_models_state(None, None, export_cache)),
        }

    def _build_history_action_record(self, before_state, after_state):
        record = {
            "created": {kind: [] for kind, _field in self._history_kind_fields()},
            "deleted": {kind: [] for kind, _field in self._history_kind_fields()},
            "modified_before": {kind: [] for kind, _field in self._history_kind_fields()},
            "modified_after": {kind: [] for kind, _field in self._history_kind_fields()},
        }
        has_changes = False

        for kind, field in self._history_kind_fields():
            before_items = list((before_state or {}).get(field, []) or [])
            after_items = list((after_state or {}).get(field, []) or [])
            before_by_key = {self._history_item_key(kind, item): item for item in before_items}
            after_by_key = {self._history_item_key(kind, item): item for item in after_items}

            for item in after_items:
                key = self._history_item_key(kind, item)
                if key not in before_by_key:
                    record["created"][kind].append(copy.deepcopy(item))
                    has_changes = True

            for item in before_items:
                key = self._history_item_key(kind, item)
                if key not in after_by_key:
                    record["deleted"][kind].append(copy.deepcopy(item))
                    has_changes = True

            for item in before_items:
                key = self._history_item_key(kind, item)
                other = after_by_key.get(key, None)
                if other is None:
                    continue
                if self._history_item_restore_signature(kind, item) != self._history_item_restore_signature(kind, other):
                    record["modified_before"][kind].append(copy.deepcopy(item))
                    record["modified_after"][kind].append(copy.deepcopy(other))
                    has_changes = True

        return record if has_changes else None

    def _history_state_signature(self, payload):
        if payload is None:
            return ""
        return json.dumps(payload, sort_keys=True)

    def _begin_history_action(self):
        if bool(getattr(self, "_history_replaying", False)):
            return None
        return self._capture_history_scene_state()

    def _commit_history_action(self, before_payload):
        if before_payload is None or bool(getattr(self, "_history_replaying", False)):
            self._update_history_buttons()
            return
        after_payload = self._capture_history_scene_state()
        record = self._build_history_action_record(before_payload, after_payload)
        if record is None:
            self._update_history_buttons()
            return
        self._history_undo_stack.append(copy.deepcopy(record))
        if len(self._history_undo_stack) > int(max(1, getattr(self, "_history_limit", 30))):
            self._history_undo_stack = self._history_undo_stack[-int(self._history_limit):]
        self._history_redo_stack = []
        self._update_history_buttons()

    def _reset_history(self):
        self._history_undo_stack = []
        self._history_redo_stack = []
        self._update_history_buttons()

    def _history_source_items(self, payload):
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
        deduped = []
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
            deduped.append(item)
        return deduped

    def _cancel_active_tool_interactions_for_history(self):
        try:
            self._cancel_marker_path_pick_mode(remove_temp=True, log_message=False)
        except Exception:
            pass
        try:
            self._cancel_filament_sub_pick_mode(log_message=False)
        except Exception:
            pass
        self._filament_sub_target = None
        self._filament_sub_edit_pending = False
        dialog = getattr(self, "_filament_sub_dialog", None)
        if dialog is not None:
            try:
                dialog._filament_sub_selected_label.setText("None")
                dialog._filament_sub_status_label.setText(
                    "Press 'Pick filament from STAR point', then click one displayed STAR marker in ChimeraX."
                )
            except Exception:
                pass
            try:
                self._update_filament_sub_buttons()
            except Exception:
                pass
        try:
            self._ift_pick_pending = False
            self._restore_ift_pick_hidden_models()
            self._restore_ift_mouse_mode()
        except Exception:
            pass
        try:
            _run(self.session, "select clear", log=False)
        except Exception:
            pass

    def _history_item_key(self, kind, item):
        kind = str(kind or "").strip().lower()
        if kind == "source":
            return (
                str(item.get("session_source_id", "") or ""),
                str(item.get("fetch_type", "") or ""),
                str(item.get("fetch_id", "") or ""),
                str(item.get("path", "") or ""),
                str(item.get("name", "") or ""),
            )
        if kind == "star":
            return (
                str(item.get("session_star_id", "") or ""),
                str(item.get("name", "") or ""),
            )
        if kind == "membrane":
            return (
                str(item.get("session_membrane_id", "") or ""),
                str(item.get("name", "") or ""),
            )
        if kind == "marker_path":
            return (
                str(item.get("session_marker_path_id", "") or ""),
                str(item.get("name", "") or ""),
            )
        if kind == "attachment":
            return (
                str(item.get("session_attachment_id", "") or ""),
                str(item.get("name", "") or ""),
                str(item.get("star_name", "") or ""),
                str(item.get("map_name", "") or ""),
            )
        return ("", "")

    def _history_item_restore_signature(self, kind, item):
        kind = str(kind or "").strip().lower()
        if kind == "source":
            return json.dumps(
                {
                    "name": item.get("name", ""),
                    "path": item.get("path", None),
                    "fetch_type": item.get("fetch_type", None),
                    "fetch_id": item.get("fetch_id", None),
                    "under_cb_map_group": bool(item.get("under_cb_map_group", False)),
                },
                sort_keys=True,
            )
        if kind == "star":
            return json.dumps(
                {
                    "name": item.get("name", ""),
                    "rows": item.get("rows", []),
                    "star_text": item.get("star_text", None),
                    "clip_info": item.get("clip_info", None),
                },
                sort_keys=True,
            )
        if kind == "membrane":
            return json.dumps(
                {
                    "name": item.get("name", ""),
                    "state": item.get("state", {}),
                },
                sort_keys=True,
            )
        if kind == "marker_path":
            return json.dumps(
                {
                    "name": item.get("name", ""),
                    "state": item.get("state", {}),
                },
                sort_keys=True,
            )
        if kind == "attachment":
            return json.dumps(
                {
                    "name": item.get("name", ""),
                    "star_name": item.get("star_name", ""),
                    "map_name": item.get("map_name", ""),
                    "map_path": item.get("map_path", None),
                    "fetch_type": item.get("fetch_type", None),
                    "fetch_id": item.get("fetch_id", None),
                    "line_rotation": float(item.get("line_rotation", 0.0) or 0.0),
                    "y_rotation": float(item.get("y_rotation", 0.0) or 0.0),
                    "pre_rotate_y_90": bool(item.get("pre_rotate_y_90", False)),
                },
                sort_keys=True,
            )
        return self._history_state_signature(item)

    def _history_live_model_for_item(self, kind, item):
        kind = str(kind or "").strip().lower()
        if kind == "source":
            return self._saved_source_item_model(item)
        if kind == "star":
            return self._saved_star_item_model(item)
        if kind == "membrane":
            return self._saved_membrane_item_model(item)
        if kind == "marker_path":
            return self._saved_marker_path_item_model(item)
        if kind == "attachment":
            return self._saved_attachment_item_model(item)
        return None

    def _prune_attached_results_state(self):
        live = {}
        for attach_key, out_root in list(getattr(self, "_attached_results", {}).items()):
            if out_root is None or self._model_ref(out_root) is None:
                continue
            live[attach_key] = out_root
        self._attached_results = live
        if self._last_attached_result is not None and self._model_ref(self._last_attached_result) is None:
            self._last_attached_result = None

    def _history_attachment_star_model(self, item):
        model = self._restored_session_star_model(item)
        if model is None:
            model = self._find_model_by_name(item.get("star_name"), require_star=True)
        return model

    def _history_attachment_source_model(self, item):
        model = self._restored_session_source_model(item)
        fetch_type = item.get("fetch_type", None)
        fetch_id = item.get("fetch_id", None)
        if model is None and fetch_type and fetch_id:
            model = self._find_model_by_fetch(fetch_type, fetch_id)
        map_path = item.get("map_path", None)
        if model is None and map_path:
            model = self._find_model_by_path(map_path)
        if model is None:
            model = self._find_model_by_name(item.get("map_name"), require_star=False)
        return model

    def _other_live_attachment_uses_model(self, target_model, attr_ref_name, attr_name_name, exclude_model=None):
        if target_model is None:
            return False
        want_ref = self._model_ref(target_model)
        want_name = str(getattr(target_model, "name", "") or "")
        for model in self._all_session_models():
            if model is None or model is exclude_model:
                continue
            if not bool(getattr(model, "_cb_generated_attached", False)):
                continue
            if self._model_ref(model) is None:
                continue
            if want_ref and str(getattr(model, attr_ref_name, None) or "") == str(want_ref):
                return True
            if want_name and str(getattr(model, attr_name_name, "") or "") == want_name:
                return True
        return False

    def _history_remove_item(self, kind, item):
        kind = str(kind or "").strip().lower()
        model = self._history_live_model_for_item(kind, item)
        if model is None:
            return
        if kind == "attachment":
            star_model = self._history_attachment_star_model(item)
            source_model = self._history_attachment_source_model(item)
            self._hide_and_close_model_tree(model)
            self._prune_attached_results_state()
            if source_model is not None and not self._other_live_attachment_uses_model(
                source_model, "_cb_attachment_source_ref", "_cb_attachment_map_name"
            ):
                try:
                    source_model.display = True
                except Exception:
                    pass
            if star_model is not None and not self._other_live_attachment_uses_model(
                star_model, "_cb_attachment_star_ref", "_cb_attachment_star_name"
            ):
                try:
                    star_model.display = True
                except Exception:
                    pass
            return
        self._hide_and_close_model_tree(model)

    def _history_restore_item(self, kind, item):
        kind = str(kind or "").strip().lower()
        if kind == "source":
            self._restore_attach_source_models([copy.deepcopy(item)], base_dir="")
            return
        if kind == "star":
            self._restore_generated_star_models([copy.deepcopy(item)])
            return
        if kind == "membrane":
            self._restore_generated_membranes([copy.deepcopy(item)])
            return
        if kind == "marker_path":
            self._restore_generated_marker_paths([copy.deepcopy(item)])
            return
        if kind == "attachment":
            self._restore_attachments([copy.deepcopy(item)], reset_runtime=False)
            return

    def _apply_history_action_record(self, record, undo=True):
        if not isinstance(record, dict):
            return
        self._history_replaying = True
        try:
            self._cancel_active_tool_interactions_for_history()
            remove_bucket = "created" if undo else "deleted"
            restore_bucket = "deleted" if undo else "created"
            modified_bucket = "modified_before" if undo else "modified_after"

            for kind, _field in reversed(self._history_kind_fields()):
                for item in list(record.get(remove_bucket, {}).get(kind, []) or []):
                    self._history_remove_item(kind, item)

            for kind, _field in self._history_kind_fields():
                for item in list(record.get(restore_bucket, {}).get(kind, []) or []):
                    self._history_restore_item(kind, item)

            for kind, _field in self._history_kind_fields():
                modified_items = list(record.get(modified_bucket, {}).get(kind, []) or [])
                if not modified_items:
                    continue
                if kind in ("attachment", "source"):
                    for item in modified_items:
                        self._history_remove_item(kind, item)
                for item in modified_items:
                    self._history_restore_item(kind, item)

            self._prune_attached_results_state()
            self._refresh_model_selectors()
        finally:
            self._history_replaying = False
            self._update_history_buttons()

    def _undo_last_action(self):
        from Qt.QtWidgets import QMessageBox

        if not self._history_undo_stack:
            self._update_history_buttons()
            return
        record = copy.deepcopy(self._history_undo_stack.pop())
        try:
            self._apply_history_action_record(record, undo=True)
            self._history_redo_stack.append(copy.deepcopy(record))
        except Exception as e:
            self._history_undo_stack.append(record)
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._update_history_buttons()
            self._keep_tool_visible()

    def _redo_last_action(self):
        from Qt.QtWidgets import QMessageBox

        if not self._history_redo_stack:
            self._update_history_buttons()
            return
        record = copy.deepcopy(self._history_redo_stack.pop())
        try:
            self._apply_history_action_record(record, undo=False)
            self._history_undo_stack.append(copy.deepcopy(record))
        except Exception as e:
            self._history_redo_stack.append(record)
            self.session.logger.error(str(e))
            QMessageBox.critical(self.tool_window.ui_area, "CiliaBuilder2", str(e))
        finally:
            self._update_history_buttons()
            self._keep_tool_visible()
