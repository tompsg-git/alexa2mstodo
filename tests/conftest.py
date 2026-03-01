"""
Module      : conftest
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Gemeinsame Pytest-Fixtures für alle Test-Module.
"""

import pytest
from unittest.mock import MagicMock

from alexa import AlexaItem
from mstodo import MSTodoItem
from synchronizer import AnchorItem, SyncState


@pytest.fixture
def base_config():
    return {
        "amazon_url": "amazon.de",
        "alexa_list_name": "Einkaufsliste",
        "ms_client_id": "test-client-id",
        "ms_tenant_id": "consumers",
        "ms_list_name": "Einkaufsliste",
        "sync_direction": "both",
        "delete_origin": False,
        "sync_interval": 30,
    }


@pytest.fixture
def state_file(tmp_path):
    return str(tmp_path / "state.json")


def make_alexa_item(item_id: str, value: str) -> AlexaItem:
    return AlexaItem(item_id=item_id, value=value)


def make_todo_item(task_id: str, value: str) -> MSTodoItem:
    return MSTodoItem(task_id=task_id, title=value)


def make_anchor(alexa_id: str, todo_id: str, value: str) -> AnchorItem:
    return AnchorItem(alexa_id=alexa_id, todo_id=todo_id, value=value)


def make_mock_alexa(items=None):
    mock = MagicMock()
    mock.get_active_items.return_value = items or []
    mock._ensure_logged_in.return_value = None
    return mock


def make_mock_todo(items=None):
    mock = MagicMock()
    mock.get_items.return_value = items or []
    mock.connect.return_value = None
    return mock


def build_state(anchors: list) -> SyncState:
    s = SyncState()
    s.items = anchors
    return s
