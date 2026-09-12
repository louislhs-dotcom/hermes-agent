"""Path containment guard for the security_guard plugin.

Ensures all file operations stay within the plugin's own directory.
No file or directory outside ~/.hermes/plugins/security_guard/ is ever
created, written, or read (except :memory: SQLite databases).
"""

import os
from pathlib import Path
from typing import Optional


# Plugin root = the directory containing this file
PLUGIN_ROOT = Path(__file__).resolve().parent

# Allow writes only under this directory (or :memory:)
ALLOWED_PREFIX = str(PLUGIN_ROOT) + os.sep


def is_contained(path: str) -> bool:
    """Return True if *path* is inside the plugin directory or is :memory:.

    Handles:
    - Relative paths (resolved against CWD, then checked)
    - Symlinks (resolved before comparison)
    - Parent traversal (../)
    - Tilde expansion
    """
    if path == ":memory:":
        return True
    # Expand user and resolve to absolute, canonical path
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        # Resolve relative to CWD
        expanded = os.path.join(os.getcwd(), expanded)
    # Normalize and resolve symlinks (non-strict — path may not exist yet)
    resolved = os.path.realpath(expanded)
    plugin_resolved = str(PLUGIN_ROOT)
    # Check the resolved path is the plugin root or a descendant
    if resolved == plugin_resolved:
        return True
    return resolved.startswith(plugin_resolved + os.sep)


def enforce_contained(path: str, label: str = "path") -> str:
    """Validate that *path* is contained; raise ValueError if not.

    Returns the resolved, safe path on success.
    """
    if path == ":memory:":
        return path
    if not is_contained(path):
        raise ValueError(
            f"Security guard path containment violation: "
            f"{label} '{path}' resolves outside plugin directory "
            f"({PLUGIN_ROOT}). Only paths within the plugin directory "
            f"or ':memory:' are allowed."
        )
    # Return resolved path to prevent any later escaping via symlinks
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.getcwd(), expanded)
    return os.path.realpath(expanded)


def default_data_path(filename: str) -> str:
    """Return a path inside the plugin's data/ subdirectory."""
    data_dir = PLUGIN_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / filename)
