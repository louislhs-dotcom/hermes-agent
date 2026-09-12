import pathlib
import pytest
import sys
import os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from response_cache import ResponseCache


class TestResponseCache:
    def setup_method(self):
        self.cache = ResponseCache(db_path=":memory:", ttl_seconds=300)
        self.cache.init()

    def test_cache_hit(self):
        key = self.cache._make_key("chat_1", "hello", "ctx_v1")
        self.cache.set(key, "Hello there!")
        result = self.cache.get(key)
        assert result == "Hello there!"

    def test_cache_miss(self):
        result = self.cache.get("nonexistent_key")
        assert result is None

    def test_cache_expiry(self):
        cache = ResponseCache(db_path=":memory:", ttl_seconds=0)
        cache.init()
        key = cache._make_key("chat_1", "hello", "ctx_v1")
        cache.set(key, "Hello!")
        import time
        time.sleep(0.1)
        result = cache.get(key)
        assert result is None

    def test_different_keys_different_chats(self):
        key1 = self.cache._make_key("chat_1", "hello", "ctx_v1")
        key2 = self.cache._make_key("chat_2", "hello", "ctx_v1")
        self.cache.set(key1, "Hello chat 1!")
        self.cache.set(key2, "Hello chat 2!")
        assert self.cache.get(key1) == "Hello chat 1!"
        assert self.cache.get(key2) == "Hello chat 2!"

    def test_context_fingerprint_changes_key(self):
        key1 = self.cache._make_key("chat_1", "hello", "ctx_v1")
        key2 = self.cache._make_key("chat_1", "hello", "ctx_v2")
        self.cache.set(key1, "Hello v1!")
        self.cache.set(key2, "Hello v2!")
        assert self.cache.get(key1) == "Hello v1!"
        assert self.cache.get(key2) == "Hello v2!"

    def test_invalidate_all(self):
        key1 = self.cache._make_key("chat_1", "msg1", "ctx")
        key2 = self.cache._make_key("chat_2", "msg2", "ctx")
        self.cache.set(key1, "resp1")
        self.cache.set(key2, "resp2")
        self.cache.invalidate_all()
        assert self.cache.get(key1) is None
        assert self.cache.get(key2) is None

    def test_stats(self):
        key = self.cache._make_key("chat_1", "test", "ctx")
        self.cache.set(key, "response")
        stats = self.cache.stats()
        assert stats["entries"] == 1

    def test_overwrite_existing(self):
        key = self.cache._make_key("chat_1", "hello", "ctx")
        self.cache.set(key, "Old response")
        self.cache.set(key, "New response")
        assert self.cache.get(key) == "New response"
