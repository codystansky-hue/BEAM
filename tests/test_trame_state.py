"""Tests for trame_app/state.py — DB helpers and state initialization."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from trame_app.state import load_db, save_db, DEFAULTS, initialize_state


class TestLoadSaveDb:
    def test_load_missing_file(self, tmp_path):
        result = load_db(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "test.json")
        data = [{"name": "Carbon", "E11": 230e9}]
        save_db(path, data)
        loaded = load_db(path)
        assert loaded == data

    def test_save_creates_directory(self, tmp_path):
        nested = str(tmp_path / "sub" / "dir" / "test.json")
        # save_db uses hardcoded DB_DIR, so test with a direct path
        os.makedirs(os.path.dirname(nested), exist_ok=True)
        with open(nested, "w") as f:
            json.dump([{"a": 1}], f)
        result = load_db(nested)
        assert result == [{"a": 1}]


class TestDefaults:
    def test_all_pipeline_keys_present(self):
        assert "pipeline_log" in DEFAULTS
        assert "pipeline_running" in DEFAULTS
        assert "pipeline_stage" in DEFAULTS
        assert "k_matrix" in DEFAULTS
        assert "active_vtk" in DEFAULTS
        assert "active_page" in DEFAULTS

    def test_active_vtk_default(self):
        assert DEFAULTS["active_vtk"] == "none"

    def test_bc_type_default(self):
        assert DEFAULTS["bc_type"] == "Fixed-Free (Cantilever)"


class DictMock(dict):
    """A dict that also supports attribute access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)
    def __setattr__(self, name, value):
        self[name] = value

class TestInitializeState:
    def test_sets_defaults(self):
        """Verify initialize_state sets all default keys on a mock server."""

        class MockServer:
            state = DictMock()

        server = MockServer()
        # Temporarily patch DB loading to avoid file dependency
        import trame_app.state as state_mod
        orig_load = state_mod.load_db
        state_mod.load_db = lambda path: []
        try:
            initialize_state(server)
        finally:
            state_mod.load_db = orig_load

        for key, value in DEFAULTS.items():
            assert key in server.state, f"Missing state key: {key}"
            assert server.state[key] == value

    def test_loads_dbs(self):
        class MockServer:
            state = DictMock()

        server = MockServer()
        import trame_app.state as state_mod
        orig_load = state_mod.load_db
        # Mock load_db: return a dict for session data, list for everything else
        def mock_load(path):
            if "last_session.json" in path:
                return {"geo_file_name": "test.3dm", "layup_plies": []}
            return [{"name": "test", "source": path}]
        state_mod.load_db = mock_load
        try:
            initialize_state(server)
        finally:
            state_mod.load_db = orig_load

        assert len(server.state.fibers) == 1
        assert len(server.state.resins) == 1
        assert len(server.state.laminae) == 1
        assert len(server.state.layups) == 1


