"""Security guard plugin for Hermes Agent.

Provides injection detection, sanitization, rate limiting, quarantine,
and response caching for LLM requests.

Hardened:
- Cache uses SHA-256 hashed keys (via ResponseCache._make_key)
- Quarantined/rate-limited messages are never cached
- Context fingerprint uses hashlib (deterministic, not Python hash())
- Request is deep-copied before mutation — caller's dict is untouched
- Safe access to message content (handles missing "content" key)
- Cache is skipped for messages flagged as injection
"""

import copy
import hashlib
import logging
from path_guard import enforce_contained, default_data_path
from injection_patterns import match_injection, get_matched_patterns, MAX_MESSAGE_LENGTH
from sanitizer import sanitize_message, SanitizerConfig
from rate_limiter import RateLimiter
from quarantine import QuarantineManager
from response_cache import ResponseCache

logger = logging.getLogger("security_guard")


class SecurityGuard:
    """Security guard middleware for LLM request processing."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.sanitizer_config = SanitizerConfig(
            patterns=self.config.get("patterns"),
            replacement=self.config.get("replacement", "[REDACTED]"),
        )
        # Nested schema per the plan's config.yaml contract: rate_limit:
        # {max_per_window, window_seconds} — not the flat top-level keys
        # this used to read (which the plan never actually populates).
        rate_limit_cfg = self.config.get("rate_limit")
        if not isinstance(rate_limit_cfg, dict):
            rate_limit_cfg = {}
        max_per_window = self._positive_int(
            rate_limit_cfg.get("max_per_window"), default=5, field="rate_limit.max_per_window"
        )
        window_seconds = self._positive_int(
            rate_limit_cfg.get("window_seconds"), default=60, field="rate_limit.window_seconds"
        )
        self.rate_limiter = RateLimiter(
            max_per_window=max_per_window,
            window_seconds=window_seconds,
        )
        self.quarantine = QuarantineManager()
        self.cache = ResponseCache(
            db_path=self.config.get("cache_path"),
            ttl_seconds=self.config.get("cache_ttl", 300),
        )
        self.cache.init()
        self._stats = {
            "sanitized": 0,
            "blocked": 0,
            "quarantined": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "rate_limited": 0,
        }

    @staticmethod
    def _positive_int(value, default: int, field: str) -> int:
        """Validate a config value is a positive int; fall back with a
        warning otherwise.

        A non-positive ``window_seconds`` is a real rate-limit bypass, not
        just a cosmetic default miss: RateLimiter.check() computes
        ``cutoff = now - window_seconds``, so window_seconds <= 0 makes the
        cutoff >= now, every existing timestamp gets filtered out of the
        window on every call, and the limiter allows every request. A bad
        `bool` also silently passes Python's `isinstance(x, int)` check
        (bool is an int subclass) — explicitly excluded here.
        """
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            if value is not None:
                logger.warning(
                    "[security_guard] invalid %s=%r (must be a positive int) — "
                    "using default %d",
                    field, value, default,
                )
            return default
        return value

    def _get_chat_id(self, request: dict) -> str:
        """Extract or derive a chat identifier from the request."""
        return request.get("chat_id", "unknown")

    def _get_context_fingerprint(self, request: dict) -> str:
        """Create a deterministic fingerprint of the system context.

        Uses hashlib.sha256 instead of Python's hash() which is
        randomized per-process (PYTHONHASHSEED) and would cause
        cache misses across restarts.
        """
        messages = request.get("messages", [])
        system_parts = [
            m.get("content", "") for m in messages if m.get("role") == "system"
        ]
        raw = "|".join(system_parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_content(content):
        """Normalize OpenAI-style multi-part content into a plain string.

        List content (e.g. [{"type": "text", "text": "..."}, {"type":
        "image_url", ...}]) otherwise bypasses match_injection()/
        sanitize_message() entirely — both bail out on non-str input, so an
        injection payload placed in a text part of a list-content message
        was never scanned. Non-text parts (images, etc.) are dropped; only
        text is scanned/sanitized. str and None pass through unchanged so
        existing "no content" / "plain string" behavior is preserved.
        """
        if content is None or isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "\n".join(parts)
        return content

    def _get_last_user_message(self, request: dict) -> str | None:
        """Get the last user message content from the request."""
        messages = request.get("messages", [])
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return self._normalize_content(msg.get("content"))
        return None

    def _llm_request_middleware(self, request: dict) -> dict:
        """Process an LLM request through all security checks.

        Returns a dict with:
        - "request": the (possibly modified) request — a *copy*, not the original
        - "cached_response": (optional) {"content": ...} if cache hit

        Security guarantees:
        - The caller's request dict is NEVER mutated in place.
        - Quarantined messages are never cached.
        - Rate-limited messages are never cached.
        - Injection detection runs on the ORIGINAL message (before sanitization).
        """
        messages = request.get("messages", [])
        if not messages:
            return {"request": request}

        last_user_msg = self._get_last_user_message(request)
        if last_user_msg is None:
            return {"request": request}

        chat_id = self._get_chat_id(request)

        # Work on a deep copy so the caller's request is never mutated
        request = copy.deepcopy(request)
        messages = request["messages"]

        # 1. Check cache first (using hashed key)
        context_fp = self._get_context_fingerprint(request)
        cache_key = self.cache._make_key(chat_id, last_user_msg, context_fp)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return {"request": request, "cached_response": {"content": cached}}

        self._stats["cache_misses"] += 1

        # 2. Check rate limit — do NOT cache rate-limited responses
        if not self.rate_limiter.check(chat_id):
            self._stats["rate_limited"] += 1
            messages[-1]["content"] = (
                "[Rate limit exceeded. Please wait before sending another message.]"
            )
            return {"request": request}

        # 3. Sanitize the message (strip injection patterns).
        #    Always write the normalized content back so list-formatted
        #    messages (OpenAI multi-part) are flattened to a plain string.
        messages[-1]["content"] = last_user_msg
        sanitized = sanitize_message(last_user_msg, self.sanitizer_config)
        if sanitized != last_user_msg:
            self._stats["sanitized"] += 1
            messages[-1]["content"] = sanitized

        # 4. Check for injection in the ORIGINAL message (before sanitization)
        injection_result = match_injection(last_user_msg)
        if injection_result:
            logger.warning(
                "[security_guard] Injection detected in chat %s: %s",
                chat_id,
                injection_result,
            )
            # Quarantine the original message
            self.quarantine.add(chat_id, last_user_msg, injection_result)
            self._stats["quarantined"] += 1
            # Replace content with quarantine notice (do NOT cache this)
            messages[-1]["content"] = (
                f"[Message quarantined by security guard: "
                f"detected pattern '{injection_result}'. "
                f"Your message has been flagged for review.]"
            )
            return {"request": request}

        return {"request": request}

    def handle_outgoing_response(self, request: dict, response_content: str) -> None:
        """Populate the response cache after a real LLM response is received.

        `_llm_request_middleware()` only ever reads from the cache
        (``self.cache.get``) — nothing wrote to it, so ``cache_hits`` was
        always 0 and caching was dead code. The host must call this with the
        ORIGINAL (pre-guard) ``request`` and the actual LLM response text
        once a response comes back, so the cache key here matches the one
        computed on the request path.

        Security: re-checks the last user message for an injection pattern
        and skips caching if one matches — mirrors the request-path
        guarantee ("Cache is skipped for messages flagged as injection")
        even if the host calls this unconditionally rather than only for
        requests that made it past quarantine/rate-limiting.
        """
        messages = request.get("messages", [])
        if not messages:
            return
        last_user_msg = self._get_last_user_message(request)
        if last_user_msg is None or not isinstance(last_user_msg, str):
            return
        if match_injection(last_user_msg):
            return
        chat_id = self._get_chat_id(request)
        context_fp = self._get_context_fingerprint(request)
        cache_key = self.cache._make_key(chat_id, last_user_msg, context_fp)
        self.cache.set(cache_key, response_content)

    def get_quarantine_list(self) -> list:
        """Return list of quarantined messages with IDs."""
        return self.quarantine.list_with_ids()

    def release_quarantine(self, item_id: str) -> bool:
        """Release a quarantined message by ID."""
        return self.quarantine.release(item_id) is not None

    def get_stats(self) -> dict:
        """Return current stats."""
        return dict(self._stats)
