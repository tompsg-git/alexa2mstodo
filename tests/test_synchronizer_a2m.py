"""
Module      : test_synchronizer_a2m
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Unit-Tests für synchronizer_a2m.py — Einweg-Sync-Logik
              (Alexa → MS Todo) inklusive delete_origin-Verhalten.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from synchronizer_a2m import SynchronizerA2M
from synchronizer import SyncState
from conftest import (
    make_alexa_item, make_todo_item, make_anchor,
    make_mock_alexa, make_mock_todo, build_state,
)


def _make_sync_a2m(config, state_file, alexa_items=None, todo_items=None,
                   initial_state=None):
    with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
        s = SynchronizerA2M(config, state_path=state_file)
        s.alexa = make_mock_alexa(alexa_items)
        s.todo = make_mock_todo(todo_items)
        if initial_state:
            with open(state_file, "w") as f:
                json.dump(initial_state.to_dict(), f)
    return s


# ---------------------------------------------------------------------------
# sync() — Grundverhalten
# ---------------------------------------------------------------------------

class TestSynchronizerA2MSync:

    def test_new_alexa_item_added_to_todo(self, base_config, state_file):
        new_todo = make_todo_item("t99", "Butter")
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[make_alexa_item("a99", "butter")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.sync()
        sync.todo.add_item.assert_called_once_with("Butter")

    def test_todo_deletion_not_propagated_to_alexa(self, base_config, state_file):
        """In A2M-Modus wird die Alexa-Liste nie gelöscht, auch wenn Todo-Item weg ist."""
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[],
            initial_state=initial,
        )
        sync.todo.add_item.return_value = make_todo_item("t99", "Milch")
        sync.sync()
        sync.alexa.delete_item.assert_not_called()

    def test_alexa_deletion_not_propagated_to_todo(self, base_config, state_file):
        anchor = make_anchor("a1", "t1", "Milch")
        initial = build_state([anchor])
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[],
            todo_items=[make_todo_item("t1", "Milch")],
            initial_state=initial,
        )
        sync.sync()
        sync.todo.delete_item.assert_not_called()

    def test_match_by_name_no_duplicate(self, base_config, state_file):
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[make_todo_item("t1", "Milch")],
        )
        sync.sync()
        sync.todo.add_item.assert_not_called()

    def test_fetch_error_aborts_cleanly(self, base_config, state_file):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            sync = SynchronizerA2M(base_config, state_path=state_file)
            sync.alexa = MagicMock()
            sync.todo = MagicMock()
            sync.alexa.get_active_items.side_effect = RuntimeError("network")
        sync.sync()
        sync.todo.add_item.assert_not_called()


# ---------------------------------------------------------------------------
# sync() — delete_origin-Verhalten
# ---------------------------------------------------------------------------

class TestSynchronizerA2MDeleteOrigin:

    def test_delete_origin_false_no_alexa_delete(self, base_config, state_file):
        base_config["delete_origin"] = False
        new_todo = make_todo_item("t99", "Wurst")
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[make_alexa_item("a99", "wurst")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.sync()
        sync.alexa.delete_item.assert_not_called()

    def test_delete_origin_true_alexa_deleted_after_add(self, base_config, state_file):
        base_config["delete_origin"] = True
        alexa_item = make_alexa_item("a99", "Ei")
        new_todo = make_todo_item("t99", "Ei")
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[alexa_item],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.sync()
        sync.alexa.delete_item.assert_called_once()

    def test_delete_origin_add_fails_no_alexa_delete(self, base_config, state_file):
        base_config["delete_origin"] = True
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[make_alexa_item("a99", "Salz")],
            todo_items=[],
        )
        sync.todo.add_item.side_effect = RuntimeError("Todo API down")
        sync.sync()
        sync.alexa.delete_item.assert_not_called()

    def test_delete_origin_delete_fails_correct_error_message(
            self, base_config, state_file, caplog):
        """Bug-1-Regression: Bei Fehler im Alexa-Delete darf keine
        MS-Todo-Fehlermeldung erscheinen."""
        import logging
        base_config["delete_origin"] = True
        alexa_item = make_alexa_item("a99", "Pfeffer")
        new_todo = make_todo_item("t99", "Pfeffer")
        sync = _make_sync_a2m(
            base_config, state_file,
            alexa_items=[alexa_item],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.alexa.delete_item.side_effect = RuntimeError("Alexa API down")

        with caplog.at_level(logging.ERROR, logger="synchronizer_a2m"):
            sync.sync()

        assert any("delete_origin" in r.message or "Alexa" in r.message
                   for r in caplog.records if r.levelno == logging.ERROR), \
            "Fehlermeldung soll Alexa-Delete erwähnen"
        assert not any("MS Todo" in r.message
                       for r in caplog.records if r.levelno == logging.ERROR), \
            "Fehlermeldung darf nicht MS Todo erwähnen"


# ---------------------------------------------------------------------------
# initial_sync()
# ---------------------------------------------------------------------------

class TestSynchronizerA2MInitialSync:

    def _make_sync(self, config, state_file, alexa_items=None, todo_items=None):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            s = SynchronizerA2M(config, state_path=state_file)
            s.alexa = make_mock_alexa(alexa_items)
            s.todo = make_mock_todo(todo_items)
        return s

    def test_initial_sync_alexa_only(self, base_config, state_file):
        new_todo = make_todo_item("t99", "Milch")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "milch")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.initial_sync()
        sync.todo.add_item.assert_called_once_with("Milch")

    def test_initial_sync_existing_in_todo_no_duplicate(self, base_config, state_file):
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "Milch")],
            todo_items=[make_todo_item("t1", "milch")],
        )
        sync.initial_sync()
        sync.todo.add_item.assert_not_called()

    def test_initial_sync_delete_origin(self, base_config, state_file):
        base_config["delete_origin"] = True
        alexa_item = make_alexa_item("a1", "milch")
        new_todo = make_todo_item("t99", "Milch")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[alexa_item],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.initial_sync()
        sync.alexa.delete_item.assert_called_once()

    def test_initial_sync_fetch_error_raises(self, base_config, state_file):
        with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
            sync = SynchronizerA2M(base_config, state_path=state_file)
            sync.alexa = MagicMock()
            sync.todo = MagicMock()
            sync.alexa.get_active_items.side_effect = RuntimeError("API down")
        with pytest.raises(RuntimeError):
            sync.initial_sync()

    def test_initial_sync_state_written(self, base_config, state_file):
        new_todo = make_todo_item("t99", "Brot")
        sync = self._make_sync(
            base_config, state_file,
            alexa_items=[make_alexa_item("a1", "brot")],
            todo_items=[],
        )
        sync.todo.add_item.return_value = new_todo
        sync.initial_sync()
        with open(state_file) as f:
            saved = json.load(f)
        assert len(saved["items"]) == 1
