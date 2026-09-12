import pathlib
import pytest
import time
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = RateLimiter(max_per_window=3, window_seconds=60)
        chat_id = "chat_1"
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_per_window=3, window_seconds=60)
        chat_id = "chat_2"
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is False

    def test_window_expires(self):
        rl = RateLimiter(max_per_window=2, window_seconds=1)
        chat_id = "chat_3"
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is True
        assert rl.check(chat_id) is False
        time.sleep(1.1)
        assert rl.check(chat_id) is True

    def test_remaining_counts(self):
        rl = RateLimiter(max_per_window=5, window_seconds=60)
        chat_id = "chat_4"
        assert rl.remaining(chat_id) == 5
        rl.check(chat_id)
        assert rl.remaining(chat_id) == 4
        rl.check(chat_id)
        assert rl.remaining(chat_id) == 3

    def test_reset(self):
        rl = RateLimiter(max_per_window=2, window_seconds=60)
        chat_id = "chat_5"
        rl.check(chat_id)
        rl.check(chat_id)
        assert rl.check(chat_id) is False
        rl.reset(chat_id)
        assert rl.check(chat_id) is True

    def test_independent_chats(self):
        rl = RateLimiter(max_per_window=2, window_seconds=60)
        assert rl.check("chat_a") is True
        assert rl.check("chat_a") is True
        assert rl.check("chat_a") is False
        assert rl.check("chat_b") is True
        assert rl.check("chat_b") is True
        assert rl.check("chat_b") is False
