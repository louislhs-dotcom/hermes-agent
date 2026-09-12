"""Rate limiter with bounded memory and automatic cleanup."""

import time
import threading
from collections import defaultdict
from typing import Dict, List


class RateLimiter:
    """Per-chat sliding-window rate limiter with bounded memory.

    - Each chat_id gets its own list of timestamps.
    - Idle chats (no activity within 2x window) are auto-pruned to prevent
      unbounded memory growth.
    - A hard cap on the number of tracked chats prevents resource exhaustion.
    """

    MAX_TRACKED_CHATS = 10_000  # Hard cap — prevents unbounded dict growth
    CLEANUP_INTERVAL = 120  # Seconds between automatic cleanup sweeps

    def __init__(self, max_per_window: int = 10, window_seconds: int = 60):
        self.max_per_window = max_per_window
        self.window_seconds = window_seconds
        self._windows: Dict[str, List[float]] = defaultdict(list)
        self._last_cleanup: float = time.time()
        self._lock = threading.Lock()

    def _maybe_cleanup(self):
        """Prune idle chats and enforce hard cap. Called periodically."""
        now = time.time()
        if now - self._last_cleanup < self.CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        cutoff = now - self.window_seconds * 2
        # Remove chats with no active timestamps
        idle = [cid for cid, ts in self._windows.items() if not ts or ts[-1] < cutoff]
        for cid in idle:
            del self._windows[cid]
        # Enforce hard cap — remove oldest chats
        if len(self._windows) > self.MAX_TRACKED_CHATS:
            # Sort by last activity, evict oldest
            sorted_chats = sorted(self._windows.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
            excess = len(self._windows) - self.MAX_TRACKED_CHATS
            for cid, _ in sorted_chats[:excess]:
                del self._windows[cid]

    def check(self, chat_id: str) -> bool:
        """Returns True if the request is allowed, False if rate-limited."""
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            self._windows[chat_id] = [t for t in self._windows[chat_id] if t > cutoff]
            if len(self._windows[chat_id]) >= self.max_per_window:
                self._maybe_cleanup()
                return False
            self._windows[chat_id].append(now)
            self._maybe_cleanup()
            return True

    def remaining(self, chat_id: str) -> int:
        """Returns remaining requests in the current window."""
        with self._lock:
            now = time.time()
            cutoff = now - self.window_seconds
            self._windows[chat_id] = [t for t in self._windows[chat_id] if t > cutoff]
            return max(0, self.max_per_window - len(self._windows[chat_id]))

    def reset(self, chat_id: str):
        """Reset the rate limit for a specific chat."""
        with self._lock:
            self._windows[chat_id] = []

    def cleanup(self):
        """Force cleanup of idle chats."""
        with self._lock:
            self._last_cleanup = time.time()
            cutoff = time.time() - self.window_seconds * 2
            idle = [cid for cid, ts in self._windows.items() if not ts or ts[-1] < cutoff]
            for cid in idle:
                del self._windows[cid]

    def tracked_chat_count(self) -> int:
        """Returns the number of currently tracked chats (for monitoring)."""
        return len(self._windows)
