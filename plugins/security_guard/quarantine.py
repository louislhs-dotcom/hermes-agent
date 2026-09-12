"""Quarantine manager with bounded capacity and auto-expiry."""

import uuid
import time
import threading
from typing import Dict, Optional, List


class QuarantineManager:
    """In-memory quarantine store with auto-expiry and bounded capacity.

    - Items older than ``max_age_seconds`` are auto-removed on access.
    - Hard capacity cap prevents unbounded memory growth; oldest items
      are evicted first (FIFO).
    """

    MAX_ITEMS = 5_000  # Hard cap — prevents unbounded growth
    DEFAULT_MAX_AGE = 3600  # 1 hour

    def __init__(self, max_items: int = MAX_ITEMS, max_age_seconds: int = DEFAULT_MAX_AGE):
        self._items: Dict[str, dict] = {}
        self._max_items = max_items
        self._max_age_seconds = max_age_seconds
        self._lock = threading.Lock()

    def _auto_expire(self):
        """Remove expired items and enforce capacity cap."""
        now = time.time()
        # Remove expired
        expired = [mid for mid, item in self._items.items()
                   if now - item["timestamp"] > self._max_age_seconds]
        for mid in expired:
            del self._items[mid]
        # Enforce capacity — evict oldest if over cap
        if len(self._items) > self._max_items:
            sorted_items = sorted(self._items.items(), key=lambda kv: kv[1]["timestamp"])
            excess = len(self._items) - self._max_items
            for mid, _ in sorted_items[:excess]:
                del self._items[mid]

    def add(self, chat_id: str, text: str, pattern: str) -> str:
        """Quarantine a message. Returns the quarantine ID."""
        with self._lock:
            self._auto_expire()
            # Use full uuid4 (not truncated) to prevent collision
            msg_id = str(uuid.uuid4())
            self._items[msg_id] = {
                "chat_id": chat_id,
                "text": text,
                "pattern": pattern,
                "timestamp": time.time(),
                "status": "quarantined",
            }
            return msg_id

    def review(self, msg_id: str) -> Optional[dict]:
        """Review a quarantined message without removing it."""
        with self._lock:
            self._auto_expire()
            return self._items.get(msg_id)

    def release(self, msg_id: str) -> Optional[str]:
        """Release a quarantined message, returning its text."""
        with self._lock:
            item = self._items.pop(msg_id, None)
            return item["text"] if item else None

    def block(self, msg_id: str) -> bool:
        """Permanently block (remove) a quarantined message."""
        with self._lock:
            return self._items.pop(msg_id, None) is not None

    def count(self) -> int:
        """Current number of quarantined messages."""
        with self._lock:
            self._auto_expire()
            return len(self._items)

    def list_quarantined(self) -> List[dict]:
        """List all quarantined messages (copies)."""
        with self._lock:
            self._auto_expire()
            return [dict(item) for item in self._items.values()]

    def list_with_ids(self) -> List[dict]:
        """List all quarantined messages (copies), each annotated with its id.

        Public equivalent of reaching into ``_items``/``_lock`` directly —
        callers that need the id alongside the item (e.g. to release it
        later) should use this instead of touching private attributes.
        """
        with self._lock:
            self._auto_expire()
            result = []
            for msg_id, item in self._items.items():
                entry = dict(item)
                entry["id"] = msg_id
                result.append(entry)
            return result

    def clear_expired(self, max_age_seconds: Optional[int] = None) -> int:
        """Explicitly clear expired items. Returns count removed."""
        with self._lock:
            max_age = max_age_seconds if max_age_seconds is not None else self._max_age_seconds
            now = time.time()
            expired = [mid for mid, item in self._items.items()
                       if now - item["timestamp"] > max_age]
            for mid in expired:
                del self._items[mid]
            return len(expired)
