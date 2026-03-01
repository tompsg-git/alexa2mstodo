"""
Module      : test_synchronizer
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Unit-Tests für synchronizer.py — SyncState-Datenmodell,
              State-Persistenz und die bidirektionale Sync-Logik.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from synchronizer import AnchorItem, SyncState, Synchronizer
from conftest import (
    make_alexa_item, make_todo_item, make_anchor,
    make_mock_alexa, make_mock_todo, build_state,
)


# ---------------------------------------------------------------------------
# SyncState — Datenmodell
# ---------------------------------------------------------------------------

class TestSyncState:

    def test_find_by_alexa_id_found(self):
        state = build_state([make_anchor("a1", "t1", "Milch")])
        result = state.find_by_alexa_id("a1")
        assert result is not None
        assert result.value == "Milch"

    def test_find_by_alexa_id_not_found(self):
        state = build_state([make_anchor("a1", "t1", "Milch")])
        assert state.find_by_alexa_id("x99") is None

    def test_find_by_todo_id_found(self):
        state = build_state([make_anchor("a1", "t1", "Brot")])
        result = state.find_by_todo_id("t1")
        assert result is not None
        assert result.value == "Brot"

    def test_find_by_value_case_insensitive(self):
        state = build_state([make_anchor("a1", "t1", "Milch")])
        assert state.find_by_value("milch") is not None
        assert state.find_by_value("MILCH") is not None
        assert state.find_by_value("Milch") is not None

    def test_find_by_value_not_found(self):
        state = build_state([make_anchor("a1", "t1", "Milch")])
        assert state.find_by_value("Käse") is None

    def test_serialization_round_trip(self):
        original = build_state([
            make_anchor("a1", "t1", "Milch"),
            make_anchor("a2", "t2", "Brot"),
        ])
        original.sync_direction = "both"
        restored = SyncState.from_dict(original.to_dict())
        assert len(restored.items) == 2
        assert restored.sync_direction == "both"
        assert restored.items[0].alexa_id == "a1"
        assert restored.items[1].value == "Brot"

    def test_to_dict_structure(self):
        state = build_state([make_anchor("a1", "t1", "Ei")])
        d = state.to_dict()
        assert "sync_direction" in d
        assert "items" in d
        assert d["items"][0]["alexa_id"] == "a1"

    def test_from_dict_empty(self):
        state = SyncState.from_dict({"items": []})
        assert state.items == []


# ---------------------------------------------------------------------------
# Synchronizer — State-Persistenz
# ---------------------------------------------------------------------------

class TestSynchronizerState:

    def _make_sync(self, config, state_file):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            s = Synchronizer(config, state_path=state_file)
        return s

    def test_load_state_fresh(self, base_config, state_file):
        sync = self._make_sync(base_config, state_file)
        state = sync._load_state()
        assert state.items == []

    def test_load_state_existing(self, base_config, state_file):
        data = {
            "sync_direction": "both",
            "items": [{"alexa_id": "a1", "todo_id": "t1", "value": "Milch"}],
        }
        with open(state_file, "w") as f:
            json.dump(data, f)

        sync = self._make_sync(base_config, state_file)
        state = sync._load_state()
        assert len(state.items) == 1
        assert state.items[0].value == "Milch"

    def test_load_state_corrupted_json(self, base_config, state_file):
        with open(state_file, "w") as f:
            f.write("NOT VALID JSON")
        sync = self._make_sync(base_config, state_file)
        state = sync._load_state()
        assert state.items == []

    def test_load_state_direction_change_resets(self, base_config, state_file):
        data = {
            "sync_direction": "a2m",
            "items": [{"alexa_id": "a1", "todo_id": "t1", "value": "Alt"}],
        }
        with open(state_file, "w") as f:
            json.dump(data, f)

        base_config["sync_direction"] = "both"
        sync = self._make_sync(base_config, state_file)
        state = sync._load_state()
        assert state.items == []
        assert not os.path.exists(state_file)

    def test_save_state(self, base_config, state_file, tmp_path):
        sync = self._make_sync(base_config, state_file)
        state = build_state([make_anchor("a1", "t1", "Milch")])
        sync._save_state(state)
        with open(state_file) as f:
            saved = json.load(f)
        assert len(saved["items"]) == 1
        assert saved["items"][0]["value"] == "Milch"


# ---------------------------------------------------------------------------
# Synchronizer.sync() — Kernlogik
# ---------------------------------------------------------------------------

class TestSynchronizerSync:

    def _make_sync(self, config, state_file, alexa_items=None, todo_items=None,
                   initial_state=None):
        with patch("synchronizer.AlexaAPI") as MockAlexa, \
             patch("synchronizer.MSTodo") as MockTodo:
            s = Synchronizer(config, state_path=state_file)
            s.alexa = make_mock_alexa(alexa_items)
            s.todo = make_mock_todo(todo_items)
            if initial_state:
                with open(state_file, "w") as f:
                    json.dump(initial_state.to_dict(), f)
        return s

    def test_sync_no_changes(self, base_config, state_file):
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[make_todo_item("t1", "Milch")],
            initial_state=initial,
        )
        sync.sync()
        sync.alexa.add_item.assert_not_called()
        sync.todo.add_item.assert_not_called()
        sync.alexa.delete_item.assert_not_called()
        sync.todo.delete_item.assert_not_called()

    def test_sync_new_alexa_item_added_to_todo(self, base_config, state_file):
        new_todo = make_todo_item("t99", "Butter")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a99", "Butter")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.sync()
        sync.todo.add_item.assert_called_once_with("Butter")

    def test_sync_new_todo_item_added_to_alexa(self, base_config, state_file):
        new_alexa = make_alexa_item("a99", "Käse")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[],
            todo_items=[make_todo_item("t99", "Käse")],
        )
        sync.alexa.add_item.return_value = new_alexa
        sync.sync()
        sync.alexa.add_item.assert_called_once_with("Käse")

    def test_sync_alexa_deletion_propagated_to_todo(self, base_config, state_file):
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[],
            todo_items=[make_todo_item("t1", "Milch")],
            initial_state=initial,
        )
        sync.sync()
        sync.todo.delete_item.assert_called_once()

    def test_sync_todo_deletion_propagated_to_alexa(self, base_config, state_file):
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[],
            initial_state=initial,
        )
        sync.sync()
        sync.alexa.delete_item.assert_called_once()

    def test_sync_both_deleted_drops_anchor(self, base_config, state_file):
        anchor = make_anchor("a1", "t1", "Alt")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[],
            todo_items=[],
            initial_state=initial,
        )
        sync.sync()
        with open(state_file) as f:
            saved = json.load(f)
        assert saved["items"] == []

    def test_sync_match_by_name_no_duplicate(self, base_config, state_file):
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[make_todo_item("t1", "Milch")],
        )
        sync.sync()
        sync.todo.add_item.assert_not_called()
        sync.alexa.add_item.assert_not_called()

    def test_sync_match_by_name_case_insensitive(self, base_config, state_file):
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "milch")],
            todo_items=[make_todo_item("t1", "Milch")],
        )
        sync.sync()
        sync.todo.add_item.assert_not_called()

    def test_sync_fetch_error_aborts_cleanly(self, base_config, state_file):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            sync = Synchronizer(base_config, state_path=state_file)
            sync.alexa = MagicMock()
            sync.todo = MagicMock()
            sync.alexa.get_active_items.side_effect = RuntimeError("Network error")
        sync.sync()
        sync.todo.add_item.assert_not_called()

    def test_sync_state_written_on_change(self, base_config, state_file):
        new_todo = make_todo_item("t99", "Neu")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a99", "Neu")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.sync()
        assert os.path.exists(state_file)
        with open(state_file) as f:
            saved = json.load(f)
        assert len(saved["items"]) == 1

    def test_sync_state_not_written_when_no_change(self, base_config, state_file):
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[make_todo_item("t1", "Milch")],
            initial_state=initial,
        )
        import time
        time.sleep(0.05)
        mtime_before = os.path.getmtime(state_file)
        sync.sync()
        assert os.path.getmtime(state_file) == mtime_before

    def test_sync_delete_fails_anchor_retained(self, base_config, state_file):
        """Bug-2-Regression: Anchor wird behalten wenn Delete fehlschlägt."""
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[],
            todo_items=[make_todo_item("t1", "Milch")],
            initial_state=initial,
        )
        sync.todo.delete_item.side_effect = RuntimeError("Delete failed")
        sync.sync()
        with open(state_file) as f:
            saved = json.load(f)
        assert len(saved["items"]) == 1
        assert saved["items"][0]["todo_id"] == "t1"

    def test_sync_todo_delete_fails_item_not_re_added_to_alexa(self, base_config, state_file):
        """Nach fehlgeschlagenem Delete darf Todo-Item nicht als 'neu' gelten."""
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[],
            todo_items=[make_todo_item("t1", "Milch")],
            initial_state=initial,
        )
        sync.todo.delete_item.side_effect = RuntimeError("Delete failed")
        sync.sync()
        sync.alexa.add_item.assert_not_called()


# ---------------------------------------------------------------------------
# Synchronizer.initial_sync()
# ---------------------------------------------------------------------------

class TestSynchronizerInitialSync:

    def _make_sync(self, config, state_file, alexa_items=None, todo_items=None):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            s = Synchronizer(config, state_path=state_file)
            s.alexa = make_mock_alexa(alexa_items)
            s.todo = make_mock_todo(todo_items)
        return s

    def test_initial_sync_both_empty(self, base_config, state_file):
        sync = self._make_sync(base_config, state_file)
        sync.initial_sync()
        with open(state_file) as f:
            saved = json.load(f)
        assert saved["items"] == []

    def test_initial_sync_alexa_only(self, base_config, state_file):
        new_todo = make_todo_item("t99", "Milch")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.initial_sync()
        sync.todo.add_item.assert_called_once_with("Milch")

    def test_initial_sync_todo_only(self, base_config, state_file):
        new_alexa = make_alexa_item("a99", "Brot")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[],
            todo_items=[make_todo_item("t1", "Brot")],
        )
        sync.alexa.add_item.return_value = new_alexa
        sync.initial_sync()
        sync.alexa.add_item.assert_called_once_with("Brot")

    def test_initial_sync_overlap_no_duplicate(self, base_config, state_file):
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[make_todo_item("t1", "milch")],
        )
        sync.initial_sync()
        sync.todo.add_item.assert_not_called()
        sync.alexa.add_item.assert_not_called()
        with open(state_file) as f:
            saved = json.load(f)
        assert len(saved["items"]) == 1

    def test_initial_sync_fetch_error_raises(self, base_config, state_file):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            sync = Synchronizer(base_config, state_path=state_file)
            sync.alexa = MagicMock()
            sync.todo = MagicMock()
            sync.alexa.get_active_items.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError):
            sync.initial_sync()
