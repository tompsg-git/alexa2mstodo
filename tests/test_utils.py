"""
Module      : test_utils
Date        : 2026-03-01
Version     : 1.0.0
Author      : tompsg-git
Description : Unit-Tests für utils.py — Konfigurationsladung und
              Pfadauflösung.
"""

import json
import os
import sys
import pytest

from utils import load_config, resolve_path, get_list_pairs


class TestLoadConfig:

    def test_load_config_valid(self, tmp_path):
        cfg = {"key": "value", "number": 42}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))
        result = load_config(str(config_file))
        assert result == cfg

    def test_load_config_not_found_exits(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.json")
        with pytest.raises(SystemExit) as exc_info:
            load_config(missing)
        assert exc_info.value.code == 1

    def test_load_config_nested(self, tmp_path):
        cfg = {"a": {"b": {"c": 3}}}
        config_file = tmp_path / "nested.json"
        config_file.write_text(json.dumps(cfg))
        result = load_config(str(config_file))
        assert result["a"]["b"]["c"] == 3


class TestResolvePath:

    def test_absolute_path_unchanged(self, tmp_path):
        abs_path = "/etc/config.json"
        config_path = str(tmp_path / "config.json")
        result = resolve_path(abs_path, config_path)
        assert result == abs_path

    def test_relative_path_resolved_to_config_dir(self, tmp_path):
        config_path = str(tmp_path / "config.json")
        result = resolve_path("alexa_cookie.json", config_path)
        expected = os.path.join(str(tmp_path), "alexa_cookie.json")
        assert result == expected

    def test_relative_path_with_subdir(self, tmp_path):
        config_path = str(tmp_path / "config" / "config.json")
        result = resolve_path("tokens.json", config_path)
        expected = os.path.join(str(tmp_path), "config", "tokens.json")
        assert result == expected


class TestGetListPairs:

    def _base(self):
        return {
            "alexa_list_name": "Einkaufen",
            "ms_list_name": "Einkaufen",
            "sync_direction": "both",
            "delete_origin": False,
        }

    def test_old_format_single_pair(self):
        config = self._base()
        result = get_list_pairs(config)
        assert len(result) == 1
        assert result[0] == {
            "alexa": "Einkaufen",
            "ms": "Einkaufen",
            "sync_direction": "both",
            "delete_origin": False,
        }

    def test_old_format_uses_top_level_defaults(self):
        config = {**self._base(), "sync_direction": "a2m", "delete_origin": True}
        result = get_list_pairs(config)
        assert result[0]["sync_direction"] == "a2m"
        assert result[0]["delete_origin"] is True

    def test_new_format_multiple_pairs(self):
        config = {
            **self._base(),
            "lists": [
                {"alexa": "Einkaufen", "ms": "Groceries"},
                {"alexa": "Aufgaben",  "ms": "Tasks"},
            ],
        }
        result = get_list_pairs(config)
        assert len(result) == 2
        assert result[0]["alexa"] == "Einkaufen"
        assert result[0]["ms"] == "Groceries"
        assert result[1]["alexa"] == "Aufgaben"
        assert result[1]["ms"] == "Tasks"

    def test_new_format_inherits_top_level_defaults(self):
        config = {
            **self._base(),
            "sync_direction": "a2m",
            "lists": [{"alexa": "Liste", "ms": "Liste"}],
        }
        result = get_list_pairs(config)
        assert result[0]["sync_direction"] == "a2m"

    def test_new_format_pair_overrides_direction(self):
        config = {
            **self._base(),
            "sync_direction": "both",
            "lists": [
                {"alexa": "A", "ms": "A", "sync_direction": "a2m"},
                {"alexa": "B", "ms": "B"},
            ],
        }
        result = get_list_pairs(config)
        assert result[0]["sync_direction"] == "a2m"
        assert result[1]["sync_direction"] == "both"

    def test_new_format_pair_overrides_delete_origin(self):
        config = {
            **self._base(),
            "delete_origin": False,
            "lists": [
                {"alexa": "A", "ms": "A", "delete_origin": True},
            ],
        }
        result = get_list_pairs(config)
        assert result[0]["delete_origin"] is True

    def test_new_format_single_entry(self):
        config = {
            **self._base(),
            "lists": [{"alexa": "Einkaufen", "ms": "Einkaufen"}],
        }
        result = get_list_pairs(config)
        assert len(result) == 1
