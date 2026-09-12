"""SQLite-backed response cache with TTL and bounded growth.

Path containment:
- Default DB lives inside the plugin's own data/ directory.
- Any caller-supplied db_path is validated by path_guard.enforce_contained().
- No file outside the plugin directory is ever created or written.
"""

import hashlib
import time
import sqlite3
import os
import threading
from typing import Optional
from path_guard import enforce_contained, default_data_path


class ResponseCache:
    """SQLite-backed response cache with TTL and size limits.

    Safety features:
    - SHA-256 key hashing to prevent collision attacks
    - Max entry cap with LRU eviction
    - WAL journal mode with periodic checkpoint
    - Thread-safe via per-instance lock
    - Automatic expired-entry cleanup on access
    - Path containment: DB file stays inside plugin directory
    """

    MAX_ENTRIES = 10_000  # Hard cap — prevents unbounded DB growth
    CLEANUP_INTERVAL = 300  # Run cleanup every 5 minutes (wall clock)

    def __init__(self, db_path: str | None = None, ttl_seconds: int = 300,
                 max_entries: int = MAX_ENTRIES):
        if db_path is None:
            db_path = default_data_path("response_cache.db")
        # Enforce path containment — reject anything outside plugin dir
        self.db_path = enforce_contained(db_path, "cache db_path")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._last_cleanup: float = 0

    def init(self):
        """Initialize the database connection, create tables, migrate old schema."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._is_memory = self.db_path == ":memory:"
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety vs speed
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS response_cache (
                cache_key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL
            )
        """)
        # --- Schema migration: add last_accessed column if missing ---
        cols = [row[1] for row in self._conn.execute("PRAGMA table_info(response_cache)")]
        if "last_accessed" not in cols:
            # Old schema → add column and backfill with created_at
            self._conn.execute("ALTER TABLE response_cache ADD COLUMN last_accessed REAL DEFAULT 0")
            self._conn.execute("UPDATE response_cache SET last_accessed = created_at WHERE last_accessed = 0")
        # ---
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_created
            ON response_cache(created_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_accessed
            ON response_cache(last_accessed)
        """)
        self._conn.commit()
        self._last_cleanup = time.time()

    def _make_key(self, chat_id: str, message_text: str, context_fingerprint: str = "default") -> str:
        """Create a SHA-256 hash key from components. Prevents collision attacks."""
        raw = f"{chat_id}||{message_text}||{context_fingerprint}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _maybe_cleanup(self):
        """Periodically remove expired entries and enforce size cap."""
        now = time.time()
        if now - self._last_cleanup < self.CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        # Delete expired
        self._conn.execute(
            "DELETE FROM response_cache WHERE ? - created_at > ?",
            (now, self.ttl_seconds)
        )
        # Enforce max entries — LRU eviction
        count = self._conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
        if count > self.max_entries:
            excess = count - self.max_entries
            self._conn.execute(
                "DELETE FROM response_cache WHERE cache_key IN "
                "(SELECT cache_key FROM response_cache "
                "ORDER BY last_accessed ASC LIMIT ?)",
                (excess,)
            )
        # WAL checkpoint not needed for :memory: and can cause "table is locked"
        if not self._is_memory:
            self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        self._conn.commit()

    def get(self, cache_key: str) -> Optional[str]:
        """Get a cached response by key. Returns None on miss or expiry."""
        if not self._conn:
            return None
        with self._lock:
            cursor = self._conn.execute(
                "SELECT response, created_at FROM response_cache WHERE cache_key = ?",
                (cache_key,)
            )
            row = cursor.fetchone()
            if row is None:
                self._maybe_cleanup()
                return None
            response, created_at = row
            if time.time() - created_at > self.ttl_seconds:
                self._conn.execute("DELETE FROM response_cache WHERE cache_key = ?", (cache_key,))
                self._conn.commit()
                return None
            # Update last_accessed for LRU
            self._conn.execute(
                "UPDATE response_cache SET last_accessed = ? WHERE cache_key = ?",
                (time.time(), cache_key)
            )
            self._conn.commit()
            return response

    def set(self, cache_key: str, response: str):
        """Store a response in the cache."""
        if not self._conn:
            return
        with self._lock:
            now = time.time()
            self._conn.execute(
                "INSERT OR REPLACE INTO response_cache "
                "(cache_key, response, created_at, last_accessed) "
                "VALUES (?, ?, ?, ?)",
                (cache_key, response, now, now)
            )
            self._conn.commit()
            self._maybe_cleanup()

    def invalidate_all(self):
        """Clear the entire cache."""
        if not self._conn:
            return
        with self._lock:
            self._conn.execute("DELETE FROM response_cache")
            self._conn.commit()

    def stats(self) -> dict:
        """Return cache statistics."""
        if not self._conn:
            return {"entries": 0, "expired": 0}
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM response_cache")
            total = cursor.fetchone()[0]
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM response_cache WHERE ? - created_at > ?",
                (time.time(), self.ttl_seconds)
            )
            expired = cursor.fetchone()[0]
            return {"entries": total, "expired": expired}

    def close(self):
        """Close the database connection."""
        with self._lock:
            if self._conn:
                if not self._is_memory:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.close()
                self._conn = None
