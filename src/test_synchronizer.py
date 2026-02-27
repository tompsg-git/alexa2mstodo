"""
Unit tests for Synchronizer — Basis-Sync (both directions).

Run:
    cd ~/alexa2mstodo
    python3 src/test_synchronizer.py
"""

import sys
import os
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from synchronizer import Synchronizer, SyncState, AnchorItem


def make_alexa_item(item_id, value):
    item = MagicMock()
    item.id = item_id
    item.value = value
    return item


def make_todo_item(item_id, value):
    item = MagicMock()
    item.id = item_id
    item.value = value
    return item


def make_synchronizer(config, state):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(state.to_dict(), f)
        state_path = f.name
    with patch("synchronizer.AlexaAPI"), patch("synchronizer.MSTodo"):
        sync = Synchronizer(config, state_path=state_path)
    return sync


class TestSyncBoth(unittest.TestCase):
    """Zwei-Wege-Sync (Standard)"""

    def setUp(self):
        self.config = {}

    def test_new_alexa_item_pushed_to_todo(self):
        sync = make_synchronizer(self.config, SyncState())
        sync.alexa.get_active_items.return_value = [make_alexa_item("a1", "milch")]
        sync.todo.get_items.return_value = []
        sync.todo.add_item.return_value = make_alexa_item("t1", "milch")
        sync.sync()
        sync.todo.add_item.assert_called_once()
        sync.alexa.delete_item.assert_not_called()

    def test_new_todo_item_pushed_to_alexa(self):
        sync = make_synchronizer(self.config, SyncState())
        sync.alexa.get_active_items.return_value = []
        sync.todo.get_items.return_value = [make_todo_item("t1", "Butter")]
        sync.alexa.add_item.return_value = make_alexa_item("a1", "Butter")
        sync.sync()
        sync.alexa.add_item.assert_called_once_with("Butter")
        sync.todo.delete_item.assert_not_called()

    def test_delete_alexa_propagates_to_todo(self):
        state = SyncState(items=[AnchorItem("a1", "t1", "milch")])
        sync = make_synchronizer(self.config, state)
        sync.alexa.get_active_items.return_value = []
        sync.todo.get_items.return_value = [make_todo_item("t1", "milch")]
        sync.sync()
        sync.todo.delete_item.assert_called_once()

    def test_delete_todo_propagates_to_alexa(self):
        state = SyncState(items=[AnchorItem("a1", "t1", "milch")])
        sync = make_synchronizer(self.config, state)
        sync.alexa.get_active_items.return_value = [make_alexa_item("a1", "milch")]
        sync.todo.get_items.return_value = []
        sync.sync()
        sync.alexa.delete_item.assert_called_once()

    def test_both_deleted_drops_anchor(self):
        state = SyncState(items=[AnchorItem("a1", "t1", "milch")])
        sync = make_synchronizer(self.config, state)
        sync.alexa.get_active_items.return_value = []
        sync.todo.get_items.return_value = []
        sync.sync()
        sync.alexa.delete_item.assert_not_called()
        sync.todo.delete_item.assert_not_called()

    def test_existing_items_unchanged(self):
        state = SyncState(items=[AnchorItem("a1", "t1", "milch")])
        sync = make_synchronizer(self.config, state)
        sync.alexa.get_active_items.return_value = [make_alexa_item("a1", "milch")]
        sync.todo.get_items.return_value = [make_todo_item("t1", "milch")]
        sync.sync()
        sync.alexa.add_item.assert_not_called()
        sync.todo.add_item.assert_not_called()
        sync.alexa.delete_item.assert_not_called()
        sync.todo.delete_item.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
