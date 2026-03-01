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

from utils import load_config, resolve_path


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
