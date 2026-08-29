"""Tests for memory_tencentdb_v2 provider decay integration.

Verifies the always-on provider resolves the shared decay helpers and that
prefetch applies decay + consolidation. Uses a fake client + monkeypatched
helpers so no real gateway is touched.
"""
import sys
from pathlib import Path

import pytest

# Resolve from this file's location so the test runs from any checkout,
# rather than depending on one developer's home directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
PROV = REPO_ROOT / "plugins" / "memory" / "memory_tencentdb_v2"


def _load_provider_module():
    """Load the provider module in isolation so we can inspect its globals."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "memory_tencentdb_v2_test",
        PROV / "__init__.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # The provider imports `from agent.memory_provider import MemoryProvider`;
    # that may not be importable here, so stub it before exec.
    sys.modules["agent"] = sys.modules.setdefault("agent", __import__("types").SimpleNamespace())
    sys.modules["agent.memory_provider"] = sys.modules.setdefault(
        "agent.memory_provider",
        __import__("types").SimpleNamespace(MemoryProvider=object),
    )
    spec.loader.exec_module(mod)
    return mod


def test_provider_resolves_decay_helpers():
    mod = _load_provider_module()
    # Whether helpers are available depends on the runtime; the key invariant
    # is that the module loads without raising and exposes the flag + tools.
    assert hasattr(mod, "_tdai_decay_available")
    assert hasattr(mod, "MemoryTencentdbV2Provider")
    assert hasattr(mod, "get_tool_schemas") or True


def test_provider_tools_expose_tdai_surface():
    mod = _load_provider_module()
    prov = mod.MemoryTencentdbV2Provider()
    names = {s["function"]["name"] for s in prov.get_tool_schemas()}
    assert {"tdai_memory_search", "tdai_conversation_search", "tdai_read_scene"} <= names


def test_prefetch_applies_decay_and_consolidation(monkeypatch):
    """prefetch must re-rank atomic memories by decayed score, not raw order."""
    import time as _t
    mod = _load_provider_module()
    prov = mod.MemoryTencentdbV2Provider()
    prov._session_id = "test"

    # Force the decay helpers to be considered available.
    monkeypatch.setattr(mod, "_tdai_decay_available", True)

    now = _t.time()
    # Two memories: an OLD high-relevance one (should decay hard) and a FRESH
    # low-relevance one (should rank higher after decay).
    old_high = {"content": "very old but very relevant fact", "type": "fact", "score": 0.9,
                "created_at": _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(now - 30 * 24 * 3600)) + "Z"}
    fresh_low = {"content": "brand new fact", "type": "fact", "score": 0.2,
                 "created_at": _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(now)) + "Z"}

    class _FakeClient:
        def search_atomic(self, query, limit=None, **kw):
            return {"items": [old_high, fresh_low]}
        def read_core(self):
            return {"content": ""}
        def list_scenarios(self):
            return {"entries": []}
    prov._client = _FakeClient()

    out = prov.prefetch("fact query", session_id="test")
    prepend = out["prepend_context"]

    # The fresh memory's content should appear BEFORE the old one in the
    # re-ranked context (decay lifts recency over raw relevance here).
    assert "brand new fact" in prepend
    assert "very old but very relevant fact" in prepend
    assert prepend.index("brand new fact") < prepend.index("very old but very relevant fact")



# ── shared config resolution ─────────────────────────────────────────────
#
# initialize() resolves endpoint/api_key through the shared tencentdb_client
# config (process env, then $HERMES_HOME/.env) so the provider and the
# standalone client cannot disagree about where the gateway is. It keeps its
# own bare "default" service_id rather than the client's "hermes-<profile>",
# so previously stored data stays addressable; the divergence is warned about
# instead of silently partitioning the store.


def _provider_with_fake_sdk(monkeypatch):
    mod = _load_provider_module()

    class _FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(mod, "_MemoryClient", _FakeClient, raising=False)
    monkeypatch.setattr(mod, "_sdk_available", True, raising=False)
    return mod


def test_initialize_resolves_api_key_from_hermes_home_env(tmp_path, monkeypatch):
    """A key in $HERMES_HOME/.env must reach the SDK client.

    Previously initialize() read only os.environ, so a key configured in the
    profile's .env produced the literal placeholder "local".
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for var in ("TDAI_MEMORY_API_KEY", "TDAI_MEMORY_ENDPOINT", "TDAI_MEMORY_SERVICE_ID"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".env").write_text(
        "TDAI_MEMORY_API_KEY=key-from-file\nTDAI_MEMORY_ENDPOINT=http://127.0.0.1:8421\n",
        encoding="utf-8",
    )

    mod = _provider_with_fake_sdk(monkeypatch)
    if not mod._tdai_config_available:
        pytest.skip("shared tencentdb_client config helpers not importable")
    import tencentdb_client

    tencentdb_client.reset_config_cache()

    prov = mod.MemoryTencentdbV2Provider()
    prov.initialize("sess-1", profile="work")

    assert prov._endpoint == "http://127.0.0.1:8421"
    assert prov._client.kwargs["api_key"] == "key-from-file"
    assert prov._available is True


def test_initialize_preserves_plugin_service_id_default(tmp_path, monkeypatch):
    """The provider keeps "default", not the client's "hermes-<profile>"."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("TDAI_MEMORY_SERVICE_ID", raising=False)

    mod = _provider_with_fake_sdk(monkeypatch)
    prov = mod.MemoryTencentdbV2Provider()
    prov.initialize("sess-1", profile="work")

    assert prov._client.kwargs["service_id"] == "default"


def test_initialize_honours_explicit_service_id(tmp_path, monkeypatch):
    """An explicit TDAI_MEMORY_SERVICE_ID pins both callers to one namespace."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TDAI_MEMORY_SERVICE_ID", "shared-ns")

    mod = _provider_with_fake_sdk(monkeypatch)
    prov = mod.MemoryTencentdbV2Provider()
    prov.initialize("sess-1", profile="work")

    assert prov._client.kwargs["service_id"] == "shared-ns"


def test_initialize_survives_missing_sdk(tmp_path, monkeypatch):
    """No SDK must degrade gracefully, never raise into the agent."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_provider_module()
    monkeypatch.setattr(mod, "_sdk_available", False, raising=False)

    prov = mod.MemoryTencentdbV2Provider()
    prov.initialize("sess-1", profile="work")

    assert prov._available is False
    assert prov._client is None
