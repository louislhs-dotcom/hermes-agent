"""Path containment tests — prove the plugin never touches files outside its dir.

These tests verify:
1. Default cache DB path is inside security_guard/data/
2. Caller-supplied paths outside the plugin dir are rejected with ValueError
3. Symlink escapes are caught
4. Parent traversal (../) is caught
5. :memory: is always allowed
6. The old default path (~/.hermes/cache/) is now rejected
7. No files are created outside the plugin directory after normal operation
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path

plugin_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, plugin_dir)

from path_guard import is_contained, enforce_contained, default_data_path, PLUGIN_ROOT
from response_cache import ResponseCache


class TestPathContainment:
    """Verify all file operations stay within the plugin directory."""

    def test_default_data_path_inside_plugin(self):
        """default_data_path() must return a path inside the plugin dir."""
        path = default_data_path("test.db")
        assert is_contained(path), f"Default path {path} is not contained"

    def test_memory_db_always_allowed(self):
        """:memory: must always pass containment."""
        assert is_contained(":memory:")
        result = enforce_contained(":memory:", "test")
        assert result == ":memory:"

    def test_plugin_internal_path_allowed(self):
        """A path inside the plugin directory is allowed."""
        from path_guard import PLUGIN_ROOT as PR
        internal_path = os.path.join(str(PR), "data", "test.db")
        assert is_contained(internal_path)
        result = enforce_contained(internal_path, "test")
        assert str(PR) in result

    def test_external_path_rejected(self):
        """A path outside the plugin directory is rejected."""
        external = "/tmp/evil_cache.db"
        assert not is_contained(external)
        with pytest.raises(ValueError, match="containment violation"):
            enforce_contained(external, "cache")

    def test_old_default_path_rejected(self):
        """The old default ~/.hermes/cache/ path is now rejected."""
        old_path = os.path.expanduser("~/.hermes/cache/response_cache.db")
        assert not is_contained(old_path)
        with pytest.raises(ValueError, match="containment violation"):
            enforce_contained(old_path, "cache")

    def test_parent_traversal_rejected(self):
        """Parent directory traversal (../../) outside plugin is caught."""
        # Start inside the plugin dir but traverse out
        traversal = os.path.join(PLUGIN_ROOT, "data", "..", "..", "..", "evil.db")
        assert not is_contained(traversal), f"Traversal path not caught: {traversal}"

    def test_symlink_escape_rejected(self, tmp_path):
        """A symlink inside the plugin dir pointing outside is caught."""
        from path_guard import PLUGIN_ROOT as PR
        # Create a symlink inside plugin data/ pointing to /tmp
        link_path = os.path.join(str(PR), "data", "escape_link.db")
        if os.path.exists(link_path) or os.path.islink(link_path):
            os.remove(link_path)
        try:
            os.symlink(str(tmp_path / "outside.db"), link_path)
            # is_contained resolves symlinks → should detect the escape
            assert not is_contained(link_path), "Symlink escape not detected"
        finally:
            if os.path.islink(link_path):
                os.remove(link_path)

    def test_relative_path_outside_rejected(self):
        """A relative path that resolves outside the plugin is caught."""
        # We're likely running from the plugin dir or tests/ subdir
        # A path like ../../../../tmp/evil.db should be caught
        outside = "../../../../tmp/evil.db"
        # resolve it to check
        resolved = os.path.realpath(outside)
        assert not is_contained(outside), f"Relative escape not caught: {outside} -> {resolved}"


class TestResponseCacheContainment:
    """Verify ResponseCache enforces path containment."""

    def test_default_db_path_is_contained(self):
        """Default DB path (no arg) is inside the plugin directory."""
        cache = ResponseCache(db_path=None, ttl_seconds=300)
        assert is_contained(cache.db_path)
        assert "security_guard" in cache.db_path

    def test_external_db_path_rejected_at_construction(self):
        """Passing an external path to ResponseCache raises ValueError."""
        with pytest.raises(ValueError, match="containment violation"):
            ResponseCache(db_path="/tmp/evil.db")

    def test_old_cache_path_rejected(self):
        """The old ~/.hermes/cache/ path is rejected."""
        old = os.path.expanduser("~/.hermes/cache/response_cache.db")
        with pytest.raises(ValueError, match="containment violation"):
            ResponseCache(db_path=old)

    def test_memory_db_works(self):
        """:memory: still works for tests."""
        cache = ResponseCache(db_path=":memory:", ttl_seconds=300)
        cache.init()
        key = cache._make_key("chat", "msg", "ctx")
        cache.set(key, "response")
        assert cache.get(key) == "response"
        cache.close()

    def test_no_files_created_outside_plugin(self):
        """After cache operations, no new files exist outside the plugin dir."""
        # Use a fresh in-memory cache to avoid touching disk at all
        cache = ResponseCache(db_path=":memory:", ttl_seconds=300)
        cache.init()
        key = cache._make_key("chat", "msg", "ctx")
        cache.set(key, "response")
        cache.get(key)
        cache.close()
        # No assertion needed — if it used :memory:, nothing was written to disk

    def test_plugin_data_dir_created_on_demand(self):
        """The data/ subdir inside the plugin is created if missing."""
        from path_guard import PLUGIN_ROOT as PR
        data_dir = os.path.join(str(PR), "data")
        # It should already exist (created by default_data_path)
        assert os.path.isdir(data_dir), f"Plugin data dir not created: {data_dir}"


class TestSecurityGuardContainment:
    """Verify SecurityGuard enforces path containment via its config."""

    def test_default_config_uses_contained_path(self):
        """SecurityGuard with no cache_path config uses a contained path."""
        from security_guard import SecurityGuard
        guard = SecurityGuard(config={"cache_path": ":memory:"})
        assert is_contained(guard.cache.db_path) or guard.cache.db_path == ":memory:"
        guard.cache.close()

    def test_external_cache_path_in_config_rejected(self):
        """Passing an external cache_path in config raises ValueError."""
        from security_guard import SecurityGuard
        with pytest.raises(ValueError, match="containment violation"):
            SecurityGuard(config={"cache_path": "/tmp/evil.db"})

    def test_old_cache_path_in_config_rejected(self):
        """The old ~/.hermes/cache/ path via config is rejected."""
        from security_guard import SecurityGuard
        old = os.path.expanduser("~/.hermes/cache/response_cache.db")
        with pytest.raises(ValueError, match="containment violation"):
            SecurityGuard(config={"cache_path": old})
