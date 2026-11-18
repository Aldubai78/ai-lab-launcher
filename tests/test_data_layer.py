"""
Tests for AI Lab Launcher data layer.

Pure Python — no UI dependencies. Tests JSON persistence, service CRUD,
and state reconstruction via real file I/O in temp directories.

Run: pytest tests/test_data_layer.py -v
"""

import json
import os
import sys
import tempfile
import shutil

# Import the clean data layer (no tkinter needed)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import data_layer as dl


def _temp_services_file():
    """Create a temp dir and return path to services.json inside it."""
    td = tempfile.mkdtemp(prefix="ai_lab_launcher_test_")
    return os.path.join(td, "services.json"), td


def _cleanup(td):
    """Remove temp directory."""
    shutil.rmtree(td, ignore_errors=True)


# ── Helpers ─────────────────────────────────────────────────────────────

def _reset_globals():
    """Reset module-level state between tests."""
    dl.SERVICES.clear()
    dl.SERVICE_ORDER.clear()
    dl._standard_services.clear()


def _write_json(path, data):
    """Write data dict to JSON file."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Tests: Load Path ───────────────────────────────────────────────────

class TestLoadServices:
    """Test load_services() under various file conditions."""

    def test_missing_file_returns_defaults(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            # Don't create the file — it doesn't exist
            data = dl.load_services(path)
            assert isinstance(data, dict)
            assert "storm" in data
            assert "vision" in data
            assert "archivist" in data
            assert "embedding" in data
        finally:
            _cleanup(td)

    def test_defaults_have_required_fields(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            data = dl.load_services(path)
            required = ["name", "port", "tmux_session", "log_file", "command"]
            for key, svc in data.items():
                if key.startswith("_"):
                    continue
                assert isinstance(svc, dict), f"Default {key} is not a dict"
                for field in required:
                    assert field in svc, f"Default service '{key}' missing field: {field}"
        finally:
            _cleanup(td)

    def test_corrupt_json_returns_defaults(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            with open(path, "w") as f:
                f.write("{this is not valid json!!!}")
            data = dl.load_services(path)
            assert isinstance(data, dict)
            assert "storm" in data
        finally:
            _cleanup(td)

    def test_empty_file_returns_defaults(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            with open(path, "w") as f:
                f.write("")
            data = dl.load_services(path)
            assert isinstance(data, dict)
            assert "storm" in data
        finally:
            _cleanup(td)

    def test_valid_json_returns_data(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            custom = {
                "test_svc": {
                    "name": "Test Service",
                    "port": 9999,
                    "tmux_session": "test_session",
                    "log_file": "~/logs/test.log",
                    "command": "echo hello"
                }
            }
            _write_json(path, custom)
            data = dl.load_services(path)
            assert "test_svc" in data
            assert data["test_svc"]["name"] == "Test Service"
            assert data["test_svc"]["port"] == 9999
        finally:
            _cleanup(td)

    def test_missing_keys_merged_from_defaults(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            partial = {
                "storm": {"name": "Storm Server", "port": 8001},
                "vision": {
                    "name": "Vision Server", "port": 8083,
                    "tmux_session": "vision_server",
                    "log_file": "~/logs/vision.log",
                    "command": "test-command"
                }
            }
            _write_json(path, partial)
            data = dl.load_services(path)
            assert "storm" in data
            assert "vision" in data
        finally:
            _cleanup(td)


# ── Tests: Build Path ──────────────────────────────────────────────────

class TestBuildServices:
    """Test build_services() — reconstructs SERVICES, SERVICE_ORDER, _standard_services."""

    def test_build_from_clean_json(self):
        _reset_globals()
        raw = {
            "_order": ["svc_a", "svc_b"],
            "_standard": ["svc_a"],
            "svc_a": {"name": "Service A", "port": 8001, "tmux_session": "sa", "log_file": "~/logs/a.log", "command": "cmd a"},
            "svc_b": {"name": "Service B", "port": 8002, "tmux_session": "sb", "log_file": "~/logs/b.log", "command": "cmd b"},
        }
        dl.build_services(raw)
        assert list(dl.SERVICE_ORDER) == ["svc_a", "svc_b"]
        assert "svc_a" in dl.SERVICES
        assert "svc_b" in dl.SERVICES
        assert dl._standard_services == ["svc_a"]

    def test_build_with_no_order_key(self):
        _reset_globals()
        raw = {
            "z_last": {"name": "Last", "port": 8001, "tmux_session": "zl", "log_file": "~/logs/z.log", "command": "cmd"},
            "a_first": {"name": "First", "port": 8002, "tmux_session": "af", "log_file": "~/logs/a.log", "command": "cmd"},
        }
        dl.build_services(raw)
        assert list(dl.SERVICE_ORDER) == ["z_last", "a_first"]

    def test_build_filters_non_dict_entries(self):
        _reset_globals()
        raw = {
            "_order": ["good_svc", "bad_entry"],
            "good_svc": {"name": "Good", "port": 8001, "tmux_session": "gs", "log_file": "~/logs/g.log", "command": "cmd"},
            "bad_entry": "this is a string not a dict",
        }
        dl.build_services(raw)
        assert "good_svc" in dl.SERVICES
        assert "bad_entry" not in dl.SERVICES
        assert "bad_entry" not in dl.SERVICE_ORDER

    def test_build_filters_non_name_dicts(self):
        _reset_globals()
        raw = {
            "_order": ["has_name", "no_name"],
            "has_name": {"name": "Has Name", "port": 8001, "tmux_session": "hn", "log_file": "~/logs/h.log", "command": "cmd"},
            "no_name": {"port": 8002},
        }
        dl.build_services(raw)
        assert "has_name" in dl.SERVICES
        assert "no_name" not in dl.SERVICES

    def test_standard_services_filtered_to_valid_keys(self):
        _reset_globals()
        raw = {
            "_order": ["svc_a"],
            "_standard": ["svc_a", "nonexistent", "also_missing"],
            "svc_a": {"name": "Service A", "port": 8001, "tmux_session": "sa", "log_file": "~/logs/a.log", "command": "cmd"},
        }
        dl.build_services(raw)
        assert dl._standard_services == ["svc_a"]


# ── Tests: Save Path (Round-Trip) ─────────────────────────────────────

class TestSaveRoundTrip:
    """Test that save → load produces the same data."""

    def test_roundtrip_single_service(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            # Write initial state with new service
            raw = {
                "_order": ["new_svc"],
                "_standard": [],
                "new_svc": {
                    "name": "New Service",
                    "port": 7777,
                    "tmux_session": "new_svc",
                    "log_file": "~/logs/new.log",
                    "command": "echo new"
                }
            }
            _write_json(path, raw)

            # Load and verify
            data = dl.load_services(path)
            assert "new_svc" in data
            assert data["new_svc"]["name"] == "New Service"
            assert data["new_svc"]["port"] == 7777
        finally:
            _cleanup(td)

    def test_roundtrip_order_preserved(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            # Write with custom order — include all defaults so load_services
            # doesn't merge missing ones in
            raw = {
                "_order": ["vision", "storm", "archivist", "embedding"],
                "_standard": [],
                "vision": {"name": "V", "port": 8083, "tmux_session": "v", "log_file": "~/logs/v.log", "command": "cmd"},
                "storm": {"name": "S", "port": 8001, "tmux_session": "s", "log_file": "~/logs/s.log", "command": "cmd"},
                "archivist": {"name": "A", "port": 8081, "tmux_session": "a", "log_file": "~/logs/a.log", "command": "cmd"},
                "embedding": {"name": "E", "port": 8082, "tmux_session": "e", "log_file": "~/logs/e.log", "command": "cmd"},
            }
            _write_json(path, raw)

            # Reload and check order
            data = dl.load_services(path)
            order_keys = [k for k in data.keys() if not k.startswith("_")]
            assert order_keys == ["vision", "storm", "archivist", "embedding"]
        finally:
            _cleanup(td)

    def test_roundtrip_layout_mode_preserved(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            raw = {
                "_order": ["storm"],
                "_standard": [],
                "_layout_mode": "2rows",
                "storm": {"name": "S", "port": 8001, "tmux_session": "s", "log_file": "~/logs/s.log", "command": "cmd"},
            }
            _write_json(path, raw)

            data = dl.load_services(path)
            assert data.get("_layout_mode") == "2rows"
        finally:
            _cleanup(td)

    def test_roundtrip_standard_services_preserved(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            raw = {
                "_order": ["storm", "vision"],
                "_standard": ["storm", "vision"],
                "storm": {"name": "S", "port": 8001, "tmux_session": "s", "log_file": "~/logs/s.log", "command": "cmd"},
                "vision": {"name": "V", "port": 8083, "tmux_session": "v", "log_file": "~/logs/v.log", "command": "cmd"},
            }
            _write_json(path, raw)

            dl.build_services(dl.load_services(path))
            assert set(dl._standard_services) == {"storm", "vision"}
        finally:
            _cleanup(td)


# ── Tests: Edge Cases ─────────────────────────────────────────────────

class TestEdgeCases:
    """Boundary conditions and error handling."""

    def test_empty_json_object(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            with open(path, "w") as f:
                json.dump({}, f)
            data = dl.load_services(path)
            assert "storm" in data
            assert "vision" in data
        finally:
            _cleanup(td)

    def test_json_with_only_metadata(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            with open(path, "w") as f:
                json.dump({"_order": [], "_standard": []}, f)
            data = dl.load_services(path)
            assert "storm" in data
            assert "vision" in data
        finally:
            _cleanup(td)

    def test_write_json_is_valid(self):
        path, td = _temp_services_file()
        try:
            payload = {"_order": ["a", "b"], "_standard": ["a"], "a": {"name": "A", "port": 8001}, "b": {"name": "B", "port": 8002}}
            dl.write_services_json(payload, path)

            with open(path, "r") as f:
                reloaded = json.load(f)
            assert reloaded == payload
        finally:
            _cleanup(td)

    def test_duplicate_order_entries_handled(self):
        _reset_globals()
        raw = {
            "_order": ["svc_a", "svc_b", "svc_a"],
            "svc_a": {"name": "A", "port": 8001, "tmux_session": "sa", "log_file": "~/logs/a.log", "command": "cmd"},
            "svc_b": {"name": "B", "port": 8002, "tmux_session": "sb", "log_file": "~/logs/b.log", "command": "cmd"},
        }
        dl.build_services(raw)
        order_list = dl.SERVICE_ORDER
        assert order_list.count("svc_a") == 1
        assert len(order_list) == len(set(order_list))

    def test_large_port_values(self):
        path, td = _temp_services_file()
        try:
            _reset_globals()
            raw = {
                "big_port": {
                    "name": "Big Port", "port": 65535,
                    "tmux_session": "bp", "log_file": "~/logs/bp.log", "command": "cmd"
                }
            }
            _write_json(path, raw)
            data = dl.load_services(path)
            assert data["big_port"]["port"] == 65535
        finally:
            _cleanup(td)


# ── Tests: Layout Mode Cycling ────────────────────────────────────────

class TestLayoutMode:
    """Test the simple layout mode cycling logic."""

    def test_layout_modes_list(self):
        assert hasattr(dl, '_LAYOUT_MODES'), "data_layer should expose _LAYOUT_MODES"
        assert dl._LAYOUT_MODES == ["2cols", "2rows"]

    def test_cycle_index_wraps(self):
        modes = ["2cols", "2rows"]
        idx = 0

        # Cycle forward
        idx, mode = dl.cycle_layout_mode(idx)
        assert idx == 1
        assert mode == "2rows"

        # Wrap around
        idx, mode = dl.cycle_layout_mode(idx)
        assert idx == 0
        assert mode == "2cols"


# ── Tests: JSON Schema Validity ───────────────────────────────────────

class TestJsonSchema:
    """Verify the JSON structure is well-formed and consistent."""

    def test_save_json_has_indent(self):
        path, td = _temp_services_file()
        try:
            dl.write_services_json({"a": {"b": 1}}, path)
            with open(path, "r") as f:
                content = f.read()
            assert "\n" in content
            assert "    " in content or "  " in content
        finally:
            _cleanup(td)

    def test_save_json_is_utf8_safe(self):
        path, td = _temp_services_file()
        try:
            payload = {
                "utf_svc": {"name": "Uber Service", "port": 8001, "tmux_session": "us", "log_file": "~/logs/u.log", "command": "cmd"}
            }
            dl.write_services_json(payload, path)
            with open(path, "r", encoding="utf-8") as f:
                json.load(f)  # should not raise
        finally:
            _cleanup(td)


# ── Entry Point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
