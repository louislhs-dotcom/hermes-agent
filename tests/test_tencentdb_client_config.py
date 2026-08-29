"""Tests for tencentdb_client configuration resolution and error surfacing.

Covers the shared config layer used by both the standalone client and the
memory_tencentdb_v2 provider: process-environment precedence, $HERMES_HOME/.env
fallback and parsing, caching/invalidation, the plaintext-HTTP warning, the
service_id split warning, and the detectable-failure contract.

No gateway is contacted. Run:
  python3 -m pytest tests/test_tencentdb_client_config.py -q
"""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import tencentdb_client as t  # noqa: E402

TDAI_VARS = (
    "TDAI_MEMORY_ENDPOINT",
    "TDAI_MEMORY_API_KEY",
    "TDAI_MEMORY_SERVICE_ID",
    "TDAI_MEMORY_TIMEOUT",
)


@pytest.fixture
def env_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with no TDAI_* leaking in from the real environment."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for var in TDAI_VARS:
        monkeypatch.delenv(var, raising=False)
    t.reset_config_cache()
    yield tmp_path
    t.reset_config_cache()


def write_env(home: Path, body: str) -> None:
    (home / ".env").write_text(body, encoding="utf-8")


# ── .env parsing ─────────────────────────────────────────────────────────

def test_reads_settings_from_hermes_home_env_file(env_home):
    write_env(env_home, "TDAI_MEMORY_API_KEY=filekey\nTDAI_MEMORY_ENDPOINT=http://127.0.0.1:9000\n")
    cfg = t.TdaiConfig.from_env("work")
    assert cfg.api_key == "filekey"
    assert cfg.endpoint == "http://127.0.0.1:9000"


def test_env_file_handles_export_quotes_and_inline_comments(env_home):
    write_env(
        env_home,
        "# leading comment\n"
        "export TDAI_MEMORY_API_KEY='quoted-key'   # trailing comment\n"
        'TDAI_MEMORY_ENDPOINT="http://127.0.0.1:9100"\n'
        "\n",
    )
    cfg = t.TdaiConfig.from_env("work")
    assert cfg.api_key == "quoted-key"
    assert cfg.endpoint == "http://127.0.0.1:9100"


def test_hash_without_leading_space_is_literal(env_home):
    """A '#' inside a value is only a comment when preceded by whitespace."""
    write_env(env_home, "TDAI_MEMORY_SERVICE_ID=ns#one\n")
    assert t.TdaiConfig.from_env("work").service_id == "ns#one"


def test_trailing_slash_stripped_from_endpoint(env_home):
    write_env(env_home, "TDAI_MEMORY_ENDPOINT=http://127.0.0.1:9000/\n")
    assert t.TdaiConfig.from_env("work").endpoint == "http://127.0.0.1:9000"


def test_missing_env_file_yields_defaults(env_home):
    cfg = t.TdaiConfig.from_env("solo")
    assert cfg.api_key is None
    assert cfg.endpoint == "http://127.0.0.1:8420"
    assert cfg.service_id == "hermes-solo"


def test_malformed_timeout_falls_back_to_default(env_home):
    write_env(env_home, "TDAI_MEMORY_TIMEOUT=not-a-number\n")
    assert t.TdaiConfig.from_env("work").timeout == 8.0


# ── precedence ───────────────────────────────────────────────────────────

def test_process_env_overrides_env_file(env_home, monkeypatch):
    write_env(env_home, "TDAI_MEMORY_API_KEY=filekey\n")
    monkeypatch.setenv("TDAI_MEMORY_API_KEY", "envkey")
    t.reset_config_cache()
    assert t.TdaiConfig.from_env("work").api_key == "envkey"


def test_blank_env_var_falls_through_to_file(env_home, monkeypatch):
    write_env(env_home, "TDAI_MEMORY_API_KEY=filekey\n")
    monkeypatch.setenv("TDAI_MEMORY_API_KEY", "   ")
    t.reset_config_cache()
    assert t.TdaiConfig.from_env("work").api_key == "filekey"


# ── caching ──────────────────────────────────────────────────────────────

def test_config_is_cached_between_calls(env_home):
    write_env(env_home, "TDAI_MEMORY_API_KEY=k\n")
    assert t.TdaiConfig.from_env("work") is t.TdaiConfig.from_env("work")


def test_cache_invalidated_when_env_file_changes(env_home):
    write_env(env_home, "TDAI_MEMORY_API_KEY=first\n")
    first = t.TdaiConfig.from_env("work")
    # Force a distinct mtime/size rather than relying on clock granularity.
    write_env(env_home, "TDAI_MEMORY_API_KEY=second-longer-value\n")
    second = t.TdaiConfig.from_env("work")
    assert first.api_key == "first"
    assert second.api_key == "second-longer-value"


def test_distinct_profiles_get_distinct_service_ids(env_home):
    assert t.TdaiConfig.from_env("alpha").service_id == "hermes-alpha"
    assert t.TdaiConfig.from_env("beta").service_id == "hermes-beta"


# ── warnings ─────────────────────────────────────────────────────────────

def test_remote_plaintext_endpoint_warns(env_home, monkeypatch, caplog):
    monkeypatch.setenv("TDAI_MEMORY_ENDPOINT", "http://memory.example.com:8420")
    monkeypatch.setenv("TDAI_MEMORY_API_KEY", "secret")
    t.reset_config_cache()
    with caplog.at_level("WARNING"):
        t.TdaiConfig.from_env("work")
    assert "plaintext HTTP" in caplog.text


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:8420",
        "http://localhost:8420",
        "https://memory.example.com",
    ],
)
def test_loopback_and_https_do_not_warn(env_home, monkeypatch, caplog, endpoint):
    monkeypatch.setenv("TDAI_MEMORY_ENDPOINT", endpoint)
    monkeypatch.setenv("TDAI_MEMORY_API_KEY", "secret")
    t.reset_config_cache()
    with caplog.at_level("WARNING"):
        t.TdaiConfig.from_env("work")
    assert "plaintext HTTP" not in caplog.text


def test_no_warning_without_api_key(env_home, monkeypatch, caplog):
    monkeypatch.setenv("TDAI_MEMORY_ENDPOINT", "http://memory.example.com:8420")
    t.reset_config_cache()
    with caplog.at_level("WARNING"):
        t.TdaiConfig.from_env("work")
    assert "plaintext HTTP" not in caplog.text


def test_service_id_split_across_callers_warns(env_home, caplog):
    with caplog.at_level("WARNING"):
        t.warn_on_service_id_split("tencentdb_client", "hermes-work")
        assert "service_id split" not in caplog.text  # agreement so far
        t.warn_on_service_id_split("memory_tencentdb_v2", "default")
    assert "service_id split" in caplog.text
    assert "TDAI_MEMORY_SERVICE_ID" in caplog.text


def test_matching_service_ids_do_not_warn(env_home, caplog):
    with caplog.at_level("WARNING"):
        t.warn_on_service_id_split("tencentdb_client", "shared-ns")
        t.warn_on_service_id_split("memory_tencentdb_v2", "shared-ns")
    assert "service_id split" not in caplog.text


# ── namespacing ──────────────────────────────────────────────────────────

def test_session_namespacing_is_profile_scoped():
    assert t.namespaced_session("work", "sess-1") == "hermes-work/sess-1"


def test_session_key_matches_namespaced_session():
    assert t.session_key("work", "topic") == t.namespaced_session("work", "topic")


# ── failure detection ────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_successful_post_is_not_an_error(monkeypatch):
    monkeypatch.setattr(
        t.urllib.request, "urlopen", lambda *a, **k: _FakeResponse({"data": {"items": []}})
    )
    result = t._post_json(t.TdaiConfig(api_key="k"), "/v2/x", {})
    assert t.is_error(result) is False
    assert result["ok"] is True


def test_http_error_is_detectable_and_logged(monkeypatch, caplog):
    def _raise(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(t.urllib.request, "urlopen", _raise)
    with caplog.at_level("WARNING"):
        result = t._post_json(t.TdaiConfig(api_key="k"), "/v2/x", {})
    assert t.is_error(result) is True
    assert result["code"] == 401
    assert "failed" in caplog.text


def test_network_error_is_detectable(monkeypatch):
    def _raise(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(t.urllib.request, "urlopen", _raise)
    result = t._post_json(t.TdaiConfig(api_key="k"), "/v2/x", {})
    assert t.is_error(result) is True
    assert result["code"] == -1


def test_malformed_json_is_detectable(monkeypatch):
    class _Bad(_FakeResponse):
        def read(self):
            return b"<html>gateway error</html>"

    monkeypatch.setattr(t.urllib.request, "urlopen", lambda *a, **k: _Bad(None))
    assert t.is_error(t._post_json(t.TdaiConfig(api_key="k"), "/v2/x", {})) is True


def test_non_dict_payload_is_wrapped(monkeypatch):
    """A list/str body must not break callers that expect a dict."""
    monkeypatch.setattr(t.urllib.request, "urlopen", lambda *a, **k: _FakeResponse([1, 2]))
    result = t._post_json(t.TdaiConfig(api_key="k"), "/v2/x", {})
    assert result == {"ok": True, "result": [1, 2]}
    assert t.is_error(result) is False


def test_skipped_result_is_reported_separately(env_home):
    """No API key: the call is skipped, which is distinct from a failure."""
    result = t.write_conversation("work", "sess", [{"role": "user", "content": "hi"}])
    assert t.is_skipped(result) is True
    assert t.is_error(result) is False
